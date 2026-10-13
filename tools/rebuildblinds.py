"""Recompute every flash counter from the stored blind rows.

    python tools/rebuildblinds.py [--check]

Two constants in `counterplay.utility` decide what a flash is credited with:
`MIN_BLIND_SECONDS`, how long it has to hold somebody before it counts as
having blinded them, and `KILL_GRACE_SECONDS`, how long after a blind lifts a
death still belongs to it. Both decisions are made while a demo is parsed, so
moving either would normally mean parsing every demo again, and a demo file
does not have to still be on disk for its season to be in the database.

It does not need to be. Every `player_blind` event is stored with its duration,
counted or not, and every death is in `events`, precisely so this is a query
rather than a re-parse. It rewrites:

  * `blinds.died_blind`, the one stored column that is a judgement rather than
    a reading. True when the blinded opponent died to one of the thrower's own
    side inside the blind plus the grace.
  * `grenades.hit_enemy`, `hit_own` and `kills`, for flashes. One flashbang
    blinds everyone who can see it, and the blinds from one flash all carry the
    same tick, so grouping on thrower and time rebuilds the grenade.
  * `player_rounds.enemies_flashed`, `teammates_flashed`, `blind_enemy_secs`,
    `blind_team_secs`, `flash_assists` and `flash_kills`. The last two are
    behind the same threshold as the rest: a flash that "got somebody killed"
    has to be one that blinded them first, or two numbers on the same card
    contradict each other.

Set both constants to zero and this must change nothing. That is the test that
it is a rebuild rather than a second implementation that happens to be close.

Idempotent. Run it after changing either constant, on any database, as often as
you like.
"""
from __future__ import annotations

import sys

import pathlib as _pl
import sys as _sys
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from app import db
from counterplay.utility import (KILL_GRACE_SECONDS, MIN_BLIND_SECONDS,
                                 blinding)


def rebuild(check: bool = False) -> dict:
    rows = db.query("""SELECT match_key, round_num, seconds, duration, own_side,
                              died_blind, victim_steamid, thrower_steamid
                         FROM blinds ORDER BY match_key, round_num, seconds""")
    if not rows:
        return {"blinds": 0}

    # Deaths, and the side everybody was on, so a kill behind a flash can be
    # credited the way the parser credits it: the assist to whoever threw it
    # and the kill to whoever took it, which are usually not the same player.
    deaths: dict = {}
    for e in db.query("""SELECT match_key, round_num, seconds, victim_steamid,
                                attacker_steamid
                           FROM events WHERE type = 'death'"""):
        deaths.setdefault((e["match_key"], e["round_num"],
                           e["victim_steamid"]), []).append(e)
    for v in deaths.values():
        v.sort(key=lambda d: d["seconds"])
    side_of = {(r["match_key"], r["round_num"], r["steamid"]): r["side"]
               for r in db.query("""SELECT match_key, round_num, steamid, side
                                      FROM player_rounds""")}

    # ---- did this blind end in a kill, and who took it
    #
    # Recomputed rather than read back, because the width of the window is a
    # decision this code makes rather than something the demo said.
    killer: dict = {}
    died_now: dict = {}
    n_blind = 0
    for i, b in enumerate(rows):
        end = b["seconds"] + (b["duration"] or 0.0) + KILL_GRACE_SECONDS
        hit = next((d for d in deaths.get((b["match_key"], b["round_num"],
                                           b["victim_steamid"]), ())
                    if b["seconds"] <= d["seconds"] <= end), None)
        att = hit["attacker_steamid"] if hit else None
        t_side = side_of.get((b["match_key"], b["round_num"],
                              b["thrower_steamid"]))
        # An own-side blind is never credited with a kill, and a blinded
        # opponent who dies to their own teammate is not something your
        # flashbang did.
        ours = bool(att) and side_of.get((b["match_key"], b["round_num"],
                                          att)) == t_side
        died = int(ours and not b["own_side"])
        killer[i] = att if died else None
        died_now[i] = died
        if died != b["died_blind"]:
            n_blind += 1
            if not check:
                db.execute("""UPDATE blinds SET died_blind = ?
                               WHERE match_key=? AND round_num=? AND seconds=?
                                 AND victim_steamid=? AND thrower_steamid=?""",
                           died, b["match_key"], b["round_num"], b["seconds"],
                           b["victim_steamid"], b["thrower_steamid"])

    def blank():
        return {"enemies_flashed": 0, "teammates_flashed": 0,
                "blind_enemy_secs": 0.0, "blind_team_secs": 0.0,
                "flash_assists": 0, "flash_kills": 0}

    # ---- per flash, and per player-round
    flash: dict = {}
    player: dict = {}
    counted = 0
    for i, b in enumerate(rows):
        if not blinding(b["duration"]):
            continue
        counted += 1
        fk = (b["match_key"], b["round_num"], b["thrower_steamid"], b["seconds"])
        f = flash.setdefault(fk, {"hit_enemy": 0, "hit_own": 0, "kills": 0})
        p = player.setdefault((b["match_key"], b["round_num"],
                               b["thrower_steamid"]), blank())
        if b["own_side"]:
            # `hit_own` counts the thrower's own screen as well as a
            # teammate's; the split between the two lives in the blind rows.
            f["hit_own"] += 1
            p["teammates_flashed"] += 1
            p["blind_team_secs"] += b["duration"] or 0.0
            continue
        f["hit_enemy"] += 1
        p["enemies_flashed"] += 1
        p["blind_enemy_secs"] += b["duration"] or 0.0
        if died_now[i]:
            f["kills"] += 1
            p["flash_assists"] += 1
            player.setdefault((b["match_key"], b["round_num"], killer[i]),
                              blank())["flash_kills"] += 1

    # ONLY matches that actually have blind rows.
    #
    # A database can hold demos parsed before this module existed: their
    # `player_rounds` carry an `enemies_flashed` written by an older code path
    # and there is no `blinds` row anywhere to rebuild it from. Rebuilding
    # those from an empty set does not recompute them, it erases them. A match
    # with no blind rows is a match this script knows nothing about.
    scope = [r["match_key"] for r in
             db.query("SELECT DISTINCT match_key FROM blinds")]
    marks = ",".join("?" * len(scope))

    nades = db.query(f"""SELECT id, match_key, round_num, seconds, steamid,
                                hit_enemy, hit_own, kills
                           FROM grenades
                          WHERE kind = 'flash' AND match_key IN ({marks})""",
                     *scope)
    # A blind lands within a few ticks of the detonation it came from, not
    # necessarily on it, so each flash takes the nearest candidate.
    by_thrower: dict = {}
    for g in nades:
        by_thrower.setdefault((g["match_key"], g["round_num"], g["steamid"]),
                              []).append(g)
    SLACK = 4 / 64.0        # the parser's own matching window, in seconds

    want: dict = {}
    for (mk, rn, sid, secs), f in flash.items():
        cands = by_thrower.get((mk, rn, sid))
        if not cands:
            continue
        best = min(cands, key=lambda g: abs((g["seconds"] or 0.0) - secs))
        if abs((best["seconds"] or 0.0) - secs) > SLACK:
            continue
        w = want.setdefault(best["id"], {"hit_enemy": 0, "hit_own": 0, "kills": 0})
        for k in w:
            w[k] += f[k]

    n_nade = 0
    for g in nades:
        w = want.get(g["id"], {"hit_enemy": 0, "hit_own": 0, "kills": 0})
        if (g["hit_enemy"], g["hit_own"], g["kills"]) == (w["hit_enemy"],
                                                          w["hit_own"], w["kills"]):
            continue
        n_nade += 1
        if not check:
            db.execute("""UPDATE grenades SET hit_enemy=?, hit_own=?, kills=?
                           WHERE id=?""",
                       w["hit_enemy"], w["hit_own"], w["kills"], g["id"])

    n_pr = 0
    INTS = ("enemies_flashed", "teammates_flashed", "flash_assists", "flash_kills")
    SECS = ("blind_enemy_secs", "blind_team_secs")
    for r in db.query(f"""SELECT match_key, round_num, steamid, enemies_flashed,
                                 teammates_flashed, blind_enemy_secs,
                                 blind_team_secs, flash_assists, flash_kills
                            FROM player_rounds
                           WHERE match_key IN ({marks})""", *scope):
        w = player.get((r["match_key"], r["round_num"], r["steamid"]), blank())
        if (all(r[k] == w[k] for k in INTS)
                and all(abs((r[k] or 0) - w[k]) < 1e-6 for k in SECS)):
            continue
        n_pr += 1
        if not check:
            db.execute("""UPDATE player_rounds
                             SET enemies_flashed=?, teammates_flashed=?,
                                 blind_enemy_secs=?, blind_team_secs=?,
                                 flash_assists=?, flash_kills=?
                           WHERE match_key=? AND round_num=? AND steamid=?""",
                       w["enemies_flashed"], w["teammates_flashed"],
                       w["blind_enemy_secs"], w["blind_team_secs"],
                       w["flash_assists"], w["flash_kills"],
                       r["match_key"], r["round_num"], r["steamid"])

    return {"blinds": len(rows), "counted": counted, "matches": len(scope),
            "blinds_changed": n_blind, "grenades_changed": n_nade,
            "player_rounds_changed": n_pr}


if __name__ == "__main__":
    check = "--check" in sys.argv
    db.init()
    out = rebuild(check=check)
    if not out["blinds"]:
        print("No blind rows in this database. Nothing to rebuild.")
        raise SystemExit(0)
    print(f"blind at least        {MIN_BLIND_SECONDS}s")
    print(f"kill within           {KILL_GRACE_SECONDS}s of it lifting")
    print(f"matches with blinds   {out['matches']:,}")
    print(f"blind events          {out['blinds']:,}")
    print(f"counted as blinds     {out['counted']:,} "
          f"({100 * out['counted'] / out['blinds']:.0f}%)")
    verb = "would change" if check else "changed"
    print(f"blind rows {verb}    {out['blinds_changed']:,}")
    print(f"flashes {verb}       {out['grenades_changed']:,}")
    print(f"player rounds {verb} {out['player_rounds_changed']:,}")
    if check:
        print("\n--check: nothing was written.")
