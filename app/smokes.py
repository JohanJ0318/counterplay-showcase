"""What changes in the rounds you throw a particular smoke.

    "Xbox and mid doors smoke usually stops them from seeing suicide and lets
     you walk up cat to A site."

That sentence is why this module is not a denial metric. A smoke is not only a
wall somebody does not walk through: most of them are thrown to take a sightline
away so that YOUR side can move somewhere else entirely. Measuring whether an
opponent stood in the cloud answers the wrong question about the mid doors
smoke, because nobody was ever going to stand in mid doors. The question is
whether you got up cat.

So this measures a smoke the only way a demo can answer honestly: find the
smokes you throw over and over at the same spot, split your rounds into the ones
where you threw it and the ones where you did not, and print what is different
between the two sets. Three things, all counted:

  * whether you won the round
  * whether an opponent was in the space the smoke covered
  * where your own side got to, zone by zone, in the same window on the clock

THIS IS A COMPARISON, NOT A CAUSE
---------------------------------
Every other number in this product is a count of a thing that happened. This one
puts two sets of rounds beside each other, and those rounds differ in more ways
than the smoke: the buy, the call, the other four grenades. A gap here means
"these rounds went differently", never "the smoke did it". The page says so, and
both denominators are printed on every line so the size of the evidence is
visible rather than implied.
"""
from __future__ import annotations

import numpy as np

from . import db
from .movement import _assign, _centres, _rounds_with_positions
from .report import _side_by_round, _team_match_keys, team_anchors
from .utility import FLOOR_TOLERANCE, SMOKE_LIFE, SMOKE_RADIUS
from counterplay.positions import FLAG_ALIVE, FLAG_CT, sample_seconds, unpack_round

# Two smokes landing this close are the same call. A smoke lands where it lands,
# and the same throw off the same spot scatters by a good hundred units between
# a jump-throw and a stand-throw, so the spot has to be wider than the cloud.
SPOT_RADIUS = 250.0

# Both sides of the comparison need this many rounds. Six is below the eight a
# rate normally needs, and deliberately: `report.rate` marks anything under
# eight as thin and shows the raw count, which is the right behaviour here. Any
# higher and an eleven match season produces nothing at all.
MIN_EACH = 6

# How long past the smoke to keep watching your side move. The smoke is cover
# for about eighteen seconds and the ground it bought does not stop mattering
# the instant it fades.
REACH_AFTER = 10.0

# A zone has to differ by this many points between the two sets before it is
# worth a line. Twenty of thirty rounds against nine of fourteen is noise at
# these sample sizes, and a table of noise is worse than a shorter table.
MIN_GAP = 20.0

# And it has to be somewhere you actually go. A zone entered in two rounds of
# thirty is not a route, whatever the percentage gap says.
MIN_REACH = 0.25


def _cluster(points: np.ndarray) -> list[int]:
    """Greedy spot labels for a set of landing points.

    Greedy and not k-means on purpose. k-means needs to be told how many spots
    there are, and the answer is "however many places this team throws smokes
    at", which is the thing being asked. Greedy at a fixed radius answers it
    without being told, and it is stable: the same smokes in a different order
    give the same spots, because the radius decides and not the seeding.
    """
    centres: list[np.ndarray] = []
    labels: list[int] = []
    for p in points:
        hit = None
        for i, c in enumerate(centres):
            flat = float(np.hypot(p[0] - c[0], p[1] - c[1]))
            if flat < SPOT_RADIUS and abs(p[2] - c[2]) < FLOOR_TOLERANCE:
                hit = i
                break
        if hit is None:
            centres.append(p.copy())
            hit = len(centres) - 1
        labels.append(hit)
    return labels


def _near_name(centres, group_of, names, g_centres, xyz) -> str:
    """The named zone a smoke landed in, so the spot can be called something."""
    if centres is None:
        return ""
    zone = int(_assign(centres, np.array([xyz[0]]), np.array([xyz[1]]),
                       np.array([xyz[2]]))[0])
    return names.get(int(group_of[zone]), "") if zone else ""


def _team_smokes(team_id: int):
    """Your smokes, with the map and side of the round they were thrown in."""
    keys = _team_match_keys(team_id)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    out: dict = {}
    for g in db.query(f"""SELECT g.match_key, g.round_num, g.side, g.seconds,
                                 g.x, g.y, g.z, m.map_name
                            FROM grenades g
                            JOIN matches m ON m.match_key = g.match_key
                           WHERE g.kind = 'smoke' AND g.match_key IN ({marks})
                        ORDER BY g.match_key, g.round_num, g.seconds""", *keys):
        key = (g["match_key"], g["round_num"])
        if sides.get(key) != g["side"]:
            continue
        out.setdefault((g["map_name"], g["side"]), []).append(g)
    return out


def analyse(team_id: int) -> list[dict]:
    """One entry per recurring smoke spot, with both sets of rounds measured."""
    smokes = _team_smokes(team_id)
    if not smokes:
        return []

    won = {(r["match_key"], r["round_num"]): bool(r["ct_won"])
           for r in db.query(
               "SELECT match_key, round_num, ct_won FROM rounds WHERE match_key IN "
               "(%s)" % ",".join("?" * len(_team_match_keys(team_id))),
               *_team_match_keys(team_id))}
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))

    # Rounds with position data, grouped the way the spots are.
    rounds: dict = {}
    for r in _rounds_with_positions(team_id):
        side = sides.get((r["match_key"], r["round_num"]))
        if side in ("ct", "t"):
            rounds.setdefault((r["map_name"], side), []).append(r)

    out: list[dict] = []
    zone_cache: dict = {}
    for (mp, side), gs in smokes.items():
        here = rounds.get((mp, side), [])
        if len(here) < MIN_EACH * 2:
            continue
        if mp not in zone_cache:
            zone_cache[mp] = _centres(mp)
        got = zone_cache[mp]
        centres, group_of, names, g_centres = got if got else (None,) * 4

        pts = np.array([[g["x"], g["y"], g["z"]] for g in gs], dtype=np.float64)
        labels = _cluster(pts)

        spots: dict = {}
        for g, lab in zip(gs, labels):
            s = spots.setdefault(lab, {"rounds": {}, "pts": [], "times": []})
            # One round can carry two smokes at the same spot; the round is
            # counted once and the earliest throw is the one that opened it.
            key = (g["match_key"], g["round_num"])
            s["rounds"][key] = min(s["rounds"].get(key, 1e9), g["seconds"])
            s["pts"].append([g["x"], g["y"], g["z"]])
            s["times"].append(g["seconds"])

        for lab, s in spots.items():
            with_r = set(s["rounds"])
            without_r = {(r["match_key"], r["round_num"]) for r in here} - with_r
            if len(with_r) < MIN_EACH or len(without_r) < MIN_EACH:
                continue
            centre = np.array(s["pts"], dtype=np.float64).mean(axis=0)
            # The window is the same stretch of clock in both sets of rounds.
            # Comparing "while the smoke was up" against "the whole round"
            # would find a difference in every zone on the map.
            t0 = float(np.median(s["times"]))
            t1 = t0 + SMOKE_LIFE + REACH_AFTER

            tally = {True: {"n": 0, "won": 0, "seen": 0, "zones": {}},
                     False: {"n": 0, "won": 0, "seen": 0, "zones": {}}}
            for r in here:
                key = (r["match_key"], r["round_num"])
                threw = key in with_r
                unpacked = unpack_round(r["data"])
                if unpacked is None:
                    continue
                meta, _ids, sm = unpacked
                secs = sample_seconds(meta)
                window = (secs >= t0) & (secs <= t1)
                if not window.any():
                    continue
                block = sm[window]
                alive = (block["flags"] & FLAG_ALIVE).astype(bool)
                is_ct = (block["flags"] & FLAG_CT).astype(bool)
                ours = (is_ct if side == "ct" else ~is_ct) & alive
                theirs = (~is_ct if side == "ct" else is_ct) & alive

                t = tally[threw]
                t["n"] += 1
                ct_won = won.get(key)
                if ct_won is not None and ct_won == (side == "ct"):
                    t["won"] += 1

                # Was an opponent in the space the smoke covered.
                d2 = ((block["x"].astype(np.float64) - centre[0]) ** 2
                      + (block["y"].astype(np.float64) - centre[1]) ** 2)
                floor = np.abs(block["z"].astype(np.float64)
                               - centre[2]) <= FLOOR_TOLERANCE
                if bool(((d2 <= SMOKE_RADIUS ** 2) & floor & theirs).any()):
                    t["seen"] += 1

                # Where your own side got to in the same window.
                if centres is None:
                    continue
                zs = _assign(centres, block["x"], block["y"], block["z"])
                grouped = group_of[zs]
                for g_id in np.unique(grouped[ours]):
                    if g_id:
                        t["zones"][int(g_id)] = t["zones"].get(int(g_id), 0) + 1

            a, b = tally[True], tally[False]
            if a["n"] < MIN_EACH or b["n"] < MIN_EACH:
                continue

            reach = []
            for g_id, hit in a["zones"].items():
                other = b["zones"].get(g_id, 0)
                pa, pb = 100.0 * hit / a["n"], 100.0 * other / b["n"]
                if max(hit / a["n"], other / b["n"]) < MIN_REACH:
                    continue
                if abs(pa - pb) < MIN_GAP:
                    continue
                reach.append({"zone": names.get(g_id, f"zone {g_id}"),
                              "with": hit, "without": other, "gap": pa - pb})
            # And zones you only reach WITHOUT it, which is the same finding
            # pointing the other way.
            for g_id, other in b["zones"].items():
                if g_id in a["zones"]:
                    continue
                if other / b["n"] < MIN_REACH:
                    continue
                if 100.0 * other / b["n"] < MIN_GAP:
                    continue
                reach.append({"zone": names.get(g_id, f"zone {g_id}"),
                              "with": 0, "without": other,
                              "gap": -100.0 * other / b["n"]})
            reach.sort(key=lambda z: -abs(z["gap"]))

            out.append({
                "map": mp, "side": side,
                "where": _near_name(centres, group_of, names, g_centres, centre),
                "at": t0, "thrown": len(s["pts"]),
                "with": a, "without": b,
                "reach": reach[:3],
            })
    out.sort(key=lambda s: -(s["with"]["n"] + s["without"]["n"]))
    return out
