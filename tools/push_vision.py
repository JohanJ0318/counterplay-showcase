"""Bring the PC's vision data up to the server for team matches.

    python tools/push_vision.py export BOX_MATCHES.json OUT.json   # on the PC
    python tools/push_vision.py apply OUT.json                     # on the box

The PC re-parsed the corpus with positions version 2 (who could see whom)
and the kill details of migration 27. Most team matches on the server came
from the same demo files, but were parsed there before either existed, and
most have no file on the server to re-parse (CLAUDE.md, "Most of the box's
matches have no file on the box"). This copies the new data across for a
match only when both sides agree on it exactly: the same rounds with the
same winners, and in every round the same kills in the same order, killer
and victim. Matched by demo sha256, the way the ADR fix was (2026-09-27).

What it replaces on the box: that match's round_positions blobs, and the
four kill-detail columns on its death events. Nothing else.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def _signature(match_key: str) -> dict:
    rounds = {r["round_num"]: int(r["ct_won"]) for r in db.query(
        "SELECT round_num, ct_won FROM rounds WHERE match_key = ?", match_key)}
    kills = {}
    for e in db.query("""SELECT round_num, victim_steamid, attacker_steamid FROM events
                          WHERE type = 'death' AND match_key = ? ORDER BY round_num, seconds""",
                      match_key):
        kills.setdefault(str(e["round_num"]), []).append(
            [e["victim_steamid"], e["attacker_steamid"]])
    return {"rounds": {str(k): v for k, v in rounds.items()}, "kills": kills}


def export(box_file: str, out_file: str):
    db.init()
    box = json.loads(Path(box_file).read_text(encoding="utf-8"))
    payload = []
    for b in box:
        pc = db.one("""SELECT m.match_key FROM demos d JOIN matches m ON m.demo_id = d.id
                        WHERE d.sha256 = ?""", b["sha256"])
        if pc is None:
            continue
        mk = pc["match_key"]
        blobs = {str(r["round_num"]): base64.b64encode(r["data"]).decode()
                 for r in db.query("SELECT round_num, data FROM round_positions WHERE match_key = ?", mk)}
        if not blobs or any(base64.b64decode(v)[0] != 2 for v in blobs.values()):
            continue
        kills = [[e["round_num"], e["victim_steamid"], e["attacker_steamid"],
                  e["thrusmoke"], e["penetrated"], e["distance"], e["attacker_blind"]]
                 for e in db.query("""SELECT round_num, victim_steamid, attacker_steamid,
                                             thrusmoke, penetrated, distance, attacker_blind
                                        FROM events WHERE type = 'death' AND match_key = ?
                                    ORDER BY round_num, seconds""", mk)]
        payload.append({"sha256": b["sha256"], "box_match_key": b["match_key"],
                        "signature": _signature(mk), "blobs": blobs, "kills": kills})
    Path(out_file).write_text(json.dumps(payload), encoding="utf-8")
    print(f"exported {len(payload)} matches to {out_file}")


def apply(in_file: str):
    db.init()
    payload = json.loads(Path(in_file).read_text(encoding="utf-8"))
    done = 0
    for p in payload:
        mk = p["box_match_key"]
        here = _signature(mk)
        if here != p["signature"]:
            print(f"  {mk}: rounds or kills differ from the PC's parse, left alone")
            continue
        with db.connect() as conn:
            for rn, b64 in p["blobs"].items():
                conn.execute("""UPDATE round_positions SET data = ? WHERE match_key = ?
                                 AND round_num = ?""", (base64.b64decode(b64), mk, int(rn)))
            # Kills in the same order on both sides: fill them by position.
            ids = [r["id"] for r in conn.execute(
                """SELECT id FROM events WHERE type = 'death' AND match_key = ?
                 ORDER BY round_num, seconds""", (mk,))]
            for eid, k in zip(ids, p["kills"]):
                conn.execute("""UPDATE events SET thrusmoke = ?, penetrated = ?, distance = ?,
                                       attacker_blind = ? WHERE id = ?""",
                             (k[3], k[4], k[5], k[6], eid))
        done += 1
        print(f"  {mk}: vision and kill details copied")
    print(f"applied {done} of {len(payload)}")


if __name__ == "__main__":
    {"export": lambda: export(sys.argv[2], sys.argv[3]),
     "apply": lambda: apply(sys.argv[2])}[sys.argv[1]]()
