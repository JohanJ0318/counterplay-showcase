"""Fill in how each stored kill happened, without a full re-parse.

    python tools/kill_details.py              # every corpus tier
    python tools/kill_details.py league       # just one

Migration 27 added thrusmoke, penetrated, distance and attacker_blind to
events; the parser writes them from now on. For kills parsed before, this
reads ONLY the player_death events from each demo (seconds, not the 13 of a
full parse) and matches them to the stored kills: the n-th time a player
died in the demo is the n-th time he died in the database, ordered by round
and time, and the killer must agree too, so a kill is only filled when both
sides of it match.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, ingest  # noqa: E402
from counterplay.parse import _flag, _num, _sid  # noqa: E402


def demo_file(row, work: Path) -> Path | None:
    url = row["source_url"] or ""
    stored = ingest.stored_path(row["sha256"])
    if stored is not None:
        src = stored
    elif ingest.in_archive(url):
        rar, member = ingest.in_archive(url)
        if not rar.exists():
            return None
        src = ingest.extract_member(rar, member, work)
    elif url.startswith("file://"):
        src = Path(ingest.url2path(url))
        if not src.exists():
            return None
    else:
        return None
    if ingest.packing_of(src):
        out = work / "demo.dem"
        ingest.decompress(src, out)
        return out
    return src


def fill(match_key: str, path: Path) -> tuple[int, int]:
    from demoparser2 import DemoParser
    deaths = DemoParser(str(path)).parse_event("player_death")
    by_victim = defaultdict(list)
    for d in deaths.sort_values("tick").itertuples(index=False):
        v = _sid(getattr(d, "user_steamid", None))
        if v:
            by_victim[v].append(d)
    stored = defaultdict(list)
    for e in db.query("""SELECT id, victim_steamid, attacker_steamid FROM events
                          WHERE type = 'death' AND match_key = ?
                       ORDER BY round_num, seconds""", match_key):
        stored[e["victim_steamid"]].append(e)
    # Kills in the warmup or in a dropped round are in the demo but not the
    # database: align each victim's two lists from the END, where both have
    # every round of the match, and require the killer to agree.
    updates, total = [], 0
    for v, rows in stored.items():
        demo = by_victim.get(v, [])
        total += len(rows)
        for e, d in zip(reversed(rows), reversed(demo)):
            if (_sid(getattr(d, "attacker_steamid", None)) or None) != (e["attacker_steamid"] or None):
                continue
            updates.append((_flag(getattr(d, "thrusmoke", None)),
                            _num(getattr(d, "penetrated", None), int),
                            _num(getattr(d, "distance", None), float),
                            _flag(getattr(d, "attackerblind", None)), e["id"]))
    with db.connect() as conn:
        conn.executemany("""UPDATE events SET thrusmoke = ?, penetrated = ?,
                                   distance = ?, attacker_blind = ? WHERE id = ?""",
                         updates)
    return len(updates), total


def main():
    db.init()
    tiers = sys.argv[1:] or ["league", "esea", "pro"]
    marks = ",".join("?" * len(tiers))
    rows = db.query(f"""SELECT m.match_key, d.sha256, d.source_url, m.tier
                          FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
                         WHERE m.tier IN ({marks})
                           AND EXISTS (SELECT 1 FROM events e WHERE e.match_key = m.match_key
                                         AND e.type = 'death' AND e.distance IS NULL)""",
                    *tiers)
    print(f"{len(rows)} matches to fill", flush=True)
    filled = total = skipped = 0
    for i, r in enumerate(rows, 1):
        work = Path(tempfile.mkdtemp(prefix="cp-kills-"))
        try:
            path = demo_file(r, work)
            if path is None:
                skipped += 1
                continue
            a, b = fill(r["match_key"], path)
            filled += a
            total += b
        except Exception as exc:                     # noqa: BLE001
            skipped += 1
            print(f"  {r['match_key']}: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}: {filled} of {total} kills filled", flush=True)
    print(f"done: {filled} of {total} kills filled ({filled / max(total, 1):.1%}), "
          f"{skipped} matches skipped", flush=True)


if __name__ == "__main__":
    main()
