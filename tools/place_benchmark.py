"""How a typical team fights in each place, measured over every match.

    python tools/place_benchmark.py > counterplay/benchmark.json

The zone map used to judge a place against the team's OWN average on that
map. After a loss that average is low everywhere, so a place only went red
if it was far worse than an already bad average: UCF lost on Anubis and
nothing was red. And a place that favours whoever stands in it (Anubis A
site for the side that holds it) went green for every team.

So a place is judged against how every team on the box did in the same
place, on the same side, under the same phase and buy: [kills, deaths,
damage dealt, damage taken], placed where the victim stood, exactly as
movement._place_readings counts a team's own rounds. Each round is read
from both sides. The page weights these by the team's own mix of sides,
phases and buys, so a team that played mostly T is held to T numbers.

Keyed by place NAME, the way zone names are data, so the file survives a
renumbering. It includes every team's rounds, the team being judged too;
at 250 matches that pulls the typical team toward any one team by very
little. Rebuild after a large batch of new matches.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db, movement  # noqa: E402
from counterplay.positions import (FLAG_ALIVE, FLAG_CT,  # noqa: E402
                                   sample_seconds, unpack_round)
from counterplay.schema import classify_round  # noqa: E402

# COLLEGIATE ONLY. The first build counted every match in the database, and
# on the box that is 104 pro matches to 10 collegiate ones, so the page's
# "typical collegiate team" was a pro team. tier = 'league' is the collegiate
# corpus (tools/corpus.py puts every NECC demo there); it lives on Johan's PC
# (138 matches on 2026-09-27), so build there and ship the JSON.
TIER = "league"


def benchmark(map_name: str) -> dict:
    got = movement._centres(map_name)
    if got is None:
        return {}
    centres, group_of, names, _g = got
    nz = len(names)
    keys = [r["match_key"] for r in db.query(
        "SELECT match_key FROM corpus_matches WHERE map_name = ? AND tier = ?",
        map_name, TIER)]
    plants = movement._plant_lookup(keys)
    out: dict = {}
    for r in db.query("""SELECT rp.match_key, rp.round_num, rp.data,
                                r.equip_ct, r.equip_t
                           FROM round_positions rp
                           JOIN corpus_matches m ON m.match_key = rp.match_key
                           JOIN rounds  r ON r.match_key = rp.match_key
                                         AND r.round_num = rp.round_num
                          WHERE m.map_name = ? AND m.tier = ?""", map_name, TIER):
        u = unpack_round(r["data"])
        if u is None:
            continue
        meta, _sids, sm = u
        secs = sample_seconds(meta)
        if len(secs) < 2:
            continue
        plant = plants.get((r["match_key"], r["round_num"]))
        post = (secs >= plant if plant is not None
                else np.zeros(len(secs), dtype=bool))
        alive = (sm["flags"] & FLAG_ALIVE).astype(bool)
        is_ct = (sm["flags"] & FLAG_CT).astype(bool)
        gid = group_of[movement._assign(centres, sm["x"], sm["y"], sm["z"])]
        for side, ours in (("t", ~is_ct), ("ct", is_ct)):
            buy = classify_round(r["equip_ct"] if side == "ct" else r["equip_t"],
                                 r["round_num"])
            got_p = movement._place_readings(alive, ours, gid, sm["health"],
                                             secs, post, nz, lambda _p: False)
            for (z, is_post), v in got_p.items():
                key = f"{side},{'post' if is_post else 'pre'},{buy}"
                acc = out.setdefault(names[z], {}).setdefault(key, [0, 0, 0, 0])
                acc[0] += int(v[0])
                acc[1] += int(v[1])
                acc[2] += int(v[3])
                acc[3] += int(v[4])
    return out


def main() -> int:
    maps = [r["map_name"] for r in db.query(
        "SELECT DISTINCT map_name FROM corpus_matches WHERE tier = ? ORDER BY map_name",
        TIER)]
    n = db.one("SELECT COUNT(*) n FROM corpus_matches WHERE tier = ?", TIER)["n"]
    result = {mp: b for mp in maps if (b := benchmark(mp))}
    json.dump({"_how": "tools/place_benchmark.py: every collegiate (tier league) team, per "
                       "place and 'side,phase,buy': [kills, deaths, damage "
                       f"dealt, damage taken]. Built over {n} matches.",
               "maps": result}, sys.stdout, separators=(",", ":"))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
