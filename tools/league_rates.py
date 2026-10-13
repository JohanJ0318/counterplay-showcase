"""What collegiate teams do, for every recurring pattern and round-based advice.

    python tools/league_rates.py > counterplay/league_rates.json

A coach (NC State Red's captain, 2026-09-27) asked what the trade feedback
was compared to. It was the team's own round win rate: Red won 21% of rounds
after losing the opening duel against 45% overall, so it was flagged, while
collegiate teams win about 30% of those rounds and 29 rounds cannot tell 21
from 30. His call: every recurring pattern should be read against collegiate
teams, not against the team itself. This builds the collegiate side.

Counted over the collegiate corpus only (tier 'league', one row per match via
the `corpus_matches` view), from both sides of every round, so each round
counts once for the CT and once for the T:

  opening   side -> took, converted (won the round after winning the first
            duel), lost, saved (won the round after losing it)
  sides     map -> ct rounds, ct won
  buys      side -> buy kind -> rounds, won
  flash     side -> rounds where that side's flash blinded an opponent, won
  opening_chain  side -> lost / took -> n, traded, traded_won, open_won
            (the opening duel as a chain of steps, app/why.py)

Ship the JSON: the box holds 10 collegiate matches to 104 pro ones, and the
corpus lives on Johan's PC. app/league.py reads it and weights every figure
by the team's own mix of sides, maps and buys.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db, why  # noqa: E402
from counterplay.schema import classify_round  # noqa: E402

TIER = "league"


def main() -> int:
    db.init()
    keys = [r["match_key"] for r in db.query(
        "SELECT match_key FROM corpus_matches WHERE tier = ?", TIER)]
    if not keys:
        print("no collegiate matches", file=sys.stderr)
        return 1
    marks = ",".join("?" * len(keys))
    rounds = db.query(f"""SELECT match_key, round_num, map_name, ct_won,
                                 equip_ct, equip_t FROM rounds
                           WHERE match_key IN ({marks})""", *keys)
    first_death = {}
    deaths = defaultdict(list)
    for e in db.query(f"""SELECT match_key, round_num, seconds, victim_side,
                                 victim_steamid, attacker_steamid
                            FROM events WHERE type = 'death'
                             AND match_key IN ({marks})
                        ORDER BY match_key, round_num, seconds""", *keys):
        first_death.setdefault((e["match_key"], e["round_num"]), e["victim_side"])
        deaths[(e["match_key"], e["round_num"])].append(e)
    flashed = set()
    for g in db.query(f"""SELECT DISTINCT match_key, round_num, side FROM grenades
                           WHERE kind = 'flash' AND hit_enemy > 0
                             AND match_key IN ({marks})""", *keys):
        flashed.add((g["match_key"], g["round_num"], g["side"]))

    opening = {s: {"took": 0, "converted": 0, "lost": 0, "saved": 0}
               for s in ("ct", "t")}
    sides: dict = defaultdict(lambda: {"ct_rounds": 0, "ct_won": 0})
    buys: dict = {s: defaultdict(lambda: [0, 0]) for s in ("ct", "t")}
    flash = {s: [0, 0] for s in ("ct", "t")}
    # The opening duel as a chain (app/why.py): was it traded, and what
    # happened after, counted exactly the way why.team_counts counts a team.
    chain = {s: why.empty() for s in ("ct", "t")}
    for r in rounds:
        key = (r["match_key"], r["round_num"])
        ct_won = bool(r["ct_won"])
        m = sides[r["map_name"]]
        m["ct_rounds"] += 1
        m["ct_won"] += int(ct_won)
        for side in ("ct", "t"):
            won = ct_won if side == "ct" else not ct_won
            kind = classify_round(r["equip_ct"] if side == "ct" else r["equip_t"],
                                  r["round_num"])
            buys[side][kind][0] += 1
            buys[side][kind][1] += int(won)
            if (r["match_key"], r["round_num"], side) in flashed:
                flash[side][0] += 1
                flash[side][1] += int(won)
            o = why.opening_events(deaths.get(key, []))
            if o is not None:
                why.tally(chain[side], "lost" if o[0] == side else "took",
                          o[1], won)
            loser = first_death.get(key)
            if loser is None:
                continue
            o = opening[side]
            if loser == side:
                o["lost"] += 1
                o["saved"] += int(won)
            else:
                o["took"] += 1
                o["converted"] += int(won)
    # Utility, per grenade and in dollars, the way app/utility.py counts a
    # team: flashes only from matches whose demo recorded blinds at all (a
    # demo without player_blind events reads every flash as a miss).
    measured = {r["match_key"] for r in db.query(
        f"SELECT DISTINCT match_key FROM blinds WHERE match_key IN ({marks})",
        *keys)}
    fl = [0, 0, 0]
    for g in db.query(f"""SELECT match_key, hit_enemy, hit_own FROM grenades
                           WHERE kind = 'flash' AND match_key IN ({marks})""",
                      *keys):
        if g["match_key"] in measured:
            fl[0] += 1
            fl[1] += int((g["hit_enemy"] or 0) > 0)
            fl[2] += int((g["hit_own"] or 0) > 0)
    u = db.one(f"""SELECT SUM(nades_value) v, SUM(nades_wasted) w
                     FROM player_rounds WHERE match_key IN ({marks})""", *keys)
    utility = {"flash_thrown": fl[0], "flash_hit_enemy": fl[1],
               "flash_hit_own": fl[2], "measured_matches": len(measured),
               "value_spent": int(u["v"] or 0), "value_wasted": int(u["w"] or 0)}
    json.dump({"_how": "tools/league_rates.py: collegiate (tier league) "
                       f"matches, one per sha, both sides of every round. "
                       f"Built over {len(keys)} matches, {len(rounds)} rounds.",
               "matches": len(keys), "rounds": len(rounds),
               "opening": opening, "sides": dict(sides),
               "buys": {s: dict(v) for s, v in buys.items()},
               "flash": flash, "utility": utility,
               "opening_chain": chain}, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
