"""Which places on each map are neutral ground, measured over every match.

    python tools/neutral_ground.py > counterplay/neutral.json

Neutral space in Counter-Strike is the contested middle of a map that
neither side owns by default and both race to take: mid on Dust2 and
Mirage, banana and car on Inferno. It is the only place where "control"
says something about how a team played rather than which side it was on:
a CT holds its own bombsite and a T holds its spawn exit every round.

Measured, not listed by hand. Before the plant, over every round of every
team on the box, for each place: the seconds only Ts stood there and the
seconds only CTs did. A place is neutral when Ts hold between NEUTRAL_LO
and NEUTRAL_HI of that one-side time. Seconds with both sides in it are
the fight, and left out. Bombsites are never neutral, whatever the number:
before the plant they are CT ground that Ts pass through to plant, which
can look balanced on a map where executes are fast.

The file is data, like the zone names: readable, and corrected by hand if
a place comes out wrong. The page (ZONE_JS) prints a place's control line
only when the place is listed here.
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

NEUTRAL_LO, NEUTRAL_HI = 0.30, 0.70
# Under this many seconds of one-side time a place's share is not measured.
MIN_SECONDS = 120


def ground(map_name: str) -> dict:
    got = movement._centres(map_name)
    if got is None:
        return {}
    centres, group_of, names, _g = got
    nz = len(names)
    keys = [r["match_key"] for r in db.query(
        "SELECT match_key FROM matches WHERE map_name = ?", map_name)]
    plants = movement._plant_lookup(keys)
    t_only = np.zeros(nz + 1)
    ct_only = np.zeros(nz + 1)
    for r in db.query("""SELECT rp.match_key, rp.round_num, rp.data
                           FROM round_positions rp
                           JOIN matches m ON m.match_key = rp.match_key
                          WHERE m.map_name = ?""", map_name):
        u = unpack_round(r["data"])
        if u is None:
            continue
        meta, _sids, sm = u
        secs = sample_seconds(meta)
        if len(secs) < 2:
            continue
        plant = plants.get((r["match_key"], r["round_num"]))
        pre = secs < plant if plant is not None else np.ones(len(secs), bool)
        dt = np.diff(secs, append=secs[-1] + np.median(np.diff(secs)))
        alive = (sm["flags"] & FLAG_ALIVE).astype(bool)
        is_ct = (sm["flags"] & FLAG_CT).astype(bool)
        gid = group_of[movement._assign(centres, sm["x"], sm["y"], sm["z"])]
        rowi = np.repeat(np.arange(len(secs)), gid.shape[1])
        occ = []
        for side in (~is_ct, is_ct):
            o = np.zeros((len(secs), nz + 1), dtype=np.int32)
            np.add.at(o, (rowi, np.where(alive & side, gid, 0).ravel()), 1)
            occ.append(o)
        w = (dt * pre)[:, None]
        t_only += (((occ[0] > 0) & (occ[1] == 0)) * w).sum(axis=0)
        ct_only += (((occ[1] > 0) & (occ[0] == 0)) * w).sum(axis=0)
    out = {}
    for g in range(1, nz + 1):
        tot = t_only[g] + ct_only[g]
        if tot < MIN_SECONDS:
            continue
        share = t_only[g] / tot
        site = "site" in names[g].lower()
        out[names[g]] = {"t_share": round(float(share), 3),
                         "seconds": int(tot),
                         "neutral": bool(NEUTRAL_LO <= share <= NEUTRAL_HI
                                         and not site)}
    return out


def main() -> int:
    maps = [r["map_name"] for r in db.query(
        "SELECT DISTINCT map_name FROM matches ORDER BY map_name")]
    result = {}
    for mp in maps:
        g = ground(mp)
        if g:
            result[mp] = dict(sorted(g.items(), key=lambda kv: kv[1]["t_share"]))
    json.dump({"_how": "tools/neutral_ground.py: pre-plant T share of one-side "
                       f"time, neutral within {NEUTRAL_LO}-{NEUTRAL_HI}, "
                       "bombsites never", "maps": result},
              sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
