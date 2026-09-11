"""What each smoke is for, how well you throw it, and who else throws it.

    "X box and mid doors smoke usually stops them from seeing suicide and lets
     you walk up cat to A site."

That sentence is why none of this is a denial metric. A smoke is not only a wall
nobody walks through: most are thrown to take a sightline away so that YOUR side
can move somewhere else. Asking whether an opponent stood in the cloud answers
the wrong question about the mid doors smoke, because nobody was ever going to
stand in mid doors.

So a smoke gets three questions here, and none of them needs a lineup site or a
professional's demo:

  WHAT IT WAS FOR. Read off the round itself: which side threw it, how far in,
  whether the bomb was down, and where the thrower's four teammates were
  standing when he let go. A smoke thrown with two mates inside 700 units is
  part of an execute; the same smoke thrown with the nearest mate 1,100 units
  away is a lurk's. That is better than a label copied off a tutorial, because
  it says how THIS team used it rather than what it is nominally for.

  HOW WELL IT WAS THROWN. Every call has a spot, and the spot is the median of
  your own throws at it. A throw that lands 250 units off is a different smoke
  covering different ground, and the rounds either side of that line can be
  counted.

  WHO ELSE THROWS IT. The opponents in your own demos are a reference corpus:
  eleven different sides, 438 smokes. Their recurring spots are the standard
  smokes on the maps you play, found from demos rather than from prose.

THE COMPARISONS ARE COMPARISONS, NOT CAUSES
-------------------------------------------
Putting two sets of rounds beside each other is not the same as counting a
thing that happened, and the rounds differ in more ways than the smoke. This is
sharpest for the zone lines: you throw the X box smoke in the rounds you were
going up cat anyway, so that line says what the call IS and never that the
smoke caused it. Both denominators are printed on every row so the weight of
the evidence is visible instead of implied.
"""
from __future__ import annotations

import numpy as np

from . import db
from .movement import _assign, _centres, _rounds_with_positions
from .report import _side_by_round, _team_match_keys, team_anchors
from .utility import FLOOR_TOLERANCE, SMOKE_LIFE, SMOKE_RADIUS
from counterplay.positions import FLAG_ALIVE, FLAG_CT, sample_seconds, unpack_round

# Two smokes landing this close are the same call. A smoke lands where it lands,
# and the same throw off the same spot scatters a good hundred units between a
# jump-throw and a stand-throw, so the spot has to be wider than the cloud.
SPOT_RADIUS = 250.0

# Both sides of a comparison need this many rounds. Six is below the eight a
# rate normally needs, deliberately: `report.rate` marks anything under eight as
# thin and shows the raw count, which is the right behaviour here. Any higher
# and an eleven match season produces nothing at all.
MIN_EACH = 6

# How long past the smoke to keep watching your side move. The cover lasts
# eighteen seconds and the ground it buys does not stop mattering as it fades.
REACH_AFTER = 10.0

# A zone has to differ by this many points between the two sets before it earns
# a line, and be somewhere you actually go. Twenty of thirty against nine of
# fourteen is noise at these sample sizes, and a table of noise is worse than a
# shorter table.
MIN_GAP = 20.0
MIN_REACH = 0.25

# ---- what the smoke was for
#
# Distances between the thrower and his own side at the moment of the throw.
# Not thresholds anybody can look up: they are chosen to match how far apart
# players are when they are doing a thing together rather than separately, and
# they are named so they can be argued with.
EXECUTE_NEAR = 700.0      # a teammate inside this is with him
EXECUTE_MATES = 2         # two of them and it is a group, not a pair passing
LURK_APART = 1100.0       # nearest mate beyond this and he is on his own

# ---- how well it was thrown
#
# Inside this of your own median for that call, the cloud substantially covers
# the ground the call wants covered. It is deliberately less than the smoke's
# own radius: two clouds 100 units apart still overlap through the middle and
# differ at the edges, and the edges are what a sightline runs through.
ON_SPOT = 100.0

# ---- what counts as a spot in the reference corpus
#
# Not MIN_EACH. A reference spot does not need to be thrown often, it needs to
# be thrown by more than one side: that is what separates a standard smoke from
# one team's habit. Requiring six throws meant only the smokes EVERY side throws
# survived, and a coverage number that says "you throw 4 of their 4" on every
# map is not telling anybody anything.
MIN_REF_THROWS = 3
MIN_REF_SIDES = 2


def _cluster(points: np.ndarray) -> list[int]:
    """Greedy spot labels for a set of landing points.

    Greedy rather than k-means on purpose. k-means has to be told how many
    spots there are, and the answer is "however many places this team throws
    smokes at", which is the thing being asked. Greedy at a fixed radius
    answers it without being told, and it is order-independent: the radius
    decides, not the seeding.
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


def _spot_centre(points: np.ndarray) -> np.ndarray:
    """The median landing point, not the mean.

    One throw that slid off a roof pulls a mean a hundred units and takes the
    reference spot with it. The median is the throw they meant.
    """
    return np.median(points, axis=0)


def _purpose(side: str, planted: bool, mates_near: int, nearest: float) -> str:
    """What this smoke was part of, from the round it was thrown in."""
    if planted:
        return "retake" if side == "ct" else "post-plant"
    if nearest > LURK_APART:
        return "lurk"
    if mates_near >= EXECUTE_MATES:
        return "execute" if side == "t" else "push"
    return "map control" if side == "t" else "default"


PURPOSE_BLURB = {
    "execute": "Thrown with two or more of your side inside "
               f"{int(EXECUTE_NEAR)} units of the thrower, before the bomb was "
               "down. A group going somewhere together.",
    "push": "A CT group moving together behind it, before any plant.",
    "lurk": f"The thrower's nearest teammate was over {int(LURK_APART)} units "
            "away. Whatever this smoke was for, he was doing it alone.",
    "retake": "Thrown by the CT side after the bomb was down.",
    "post-plant": "Thrown by the T side after their own plant, holding the "
                  "site rather than taking it.",
    "map control": "A T smoke with nobody committed behind it: taking ground "
                   "or hiding a rotation rather than opening a site.",
    "default": "A CT smoke with nobody grouped behind it. The standard "
               "opening off this position.",
}


def _smokes_with_context(team_id: int, ours: bool = True) -> dict:
    """Every smoke, keyed by (map, side), with the thrower's situation.

    `ours=False` gives the opponents' smokes from the same demos, which is the
    reference corpus: eleven different sides on the maps this team plays.
    """
    keys = _team_match_keys(team_id)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    planted = {(r["match_key"], r["round_num"]) for r in db.query(
        f"""SELECT match_key, round_num FROM events
             WHERE type = 'plant' AND match_key IN ({marks})""", *keys)}
    plant_at = {(r["match_key"], r["round_num"]): r["seconds"] for r in db.query(
        f"""SELECT match_key, round_num, seconds FROM events
             WHERE type = 'plant' AND match_key IN ({marks})""", *keys)}
    blobs = {(r["match_key"], r["round_num"]): r["data"] for r in db.query(
        f"""SELECT match_key, round_num, data FROM round_positions
             WHERE match_key IN ({marks})""", *keys)}

    out: dict = {}
    cache: dict = {}
    for g in db.query(f"""SELECT g.match_key, g.round_num, g.side, g.seconds,
                                 g.steamid, g.x, g.y, g.z, m.map_name
                            FROM grenades g
                            JOIN matches m ON m.match_key = g.match_key
                           WHERE g.kind = 'smoke' AND g.match_key IN ({marks})
                        ORDER BY g.match_key, g.round_num, g.seconds""", *keys):
        key = (g["match_key"], g["round_num"])
        mine = sides.get(key)
        if mine is None or (g["side"] == mine) != ours:
            continue

        mates_near, nearest = 0, 9e9
        if key not in cache:
            blob = blobs.get(key)
            cache[key] = unpack_round(blob) if blob else None
        unpacked = cache[key]
        if unpacked is not None:
            meta, ids, sm = unpacked
            sid = [str(x) for x in ids]
            if g["steamid"] in sid:
                col = sid.index(g["steamid"])
                secs = sample_seconds(meta)
                row = sm[int(np.argmin(np.abs(secs - g["seconds"])))]
                alive = (row["flags"] & FLAG_ALIVE) != 0
                is_ct = (row["flags"] & FLAG_CT) != 0
                side_mask = (is_ct if g["side"] == "ct" else ~is_ct) & alive
                side_mask[col] = False
                if side_mask.any():
                    d = np.hypot(row["x"][side_mask].astype(float) - float(row["x"][col]),
                                 row["y"][side_mask].astype(float) - float(row["y"][col]))
                    mates_near = int((d < EXECUTE_NEAR).sum())
                    nearest = float(d.min())

        pt = plant_at.get(key)
        after_plant = pt is not None and g["seconds"] >= pt
        out.setdefault((g["map_name"], g["side"]), []).append({
            "match_key": g["match_key"], "round_num": g["round_num"],
            "seconds": g["seconds"], "x": g["x"], "y": g["y"], "z": g["z"],
            "purpose": _purpose(g["side"], after_plant, mates_near, nearest),
        })
    return out


def catalogue(team_id: int) -> dict:
    """The spots the teams you played throw at, per (map, side).

    Not a scraped list of lineups. These are the smokes that recur across the
    opposing sides in this team's own demos, which is both a better source than
    prose and the only one that describes the league rather than the top of the
    game.
    """
    out: dict = {}
    for key, gs in _smokes_with_context(team_id, ours=False).items():
        pts = np.array([[g["x"], g["y"], g["z"]] for g in gs], dtype=np.float64)
        labels = _cluster(pts)
        spots = []
        for lab in sorted(set(labels)):
            sel = pts[[i for i, l in enumerate(labels) if l == lab]]
            rounds = {(gs[i]["match_key"], gs[i]["round_num"])
                      for i, l in enumerate(labels) if l == lab}
            matches = {r[0] for r in rounds}
            if len(sel) < MIN_REF_THROWS or len(matches) < MIN_REF_SIDES:
                continue
            spots.append({"centre": _spot_centre(sel), "thrown": len(sel),
                          "matches": len(matches)})
        if spots:
            out[key] = spots
    return out


def analyse(team_id: int) -> list[dict]:
    """One entry per recurring smoke of yours, measured three ways."""
    smokes = _smokes_with_context(team_id, ours=True)
    if not smokes:
        return []

    keys = _team_match_keys(team_id)
    marks = ",".join("?" * len(keys))
    won = {(r["match_key"], r["round_num"]): bool(r["ct_won"]) for r in db.query(
        f"SELECT match_key, round_num, ct_won FROM rounds WHERE match_key IN ({marks})",
        *keys)}
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    ref = catalogue(team_id)

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
        centres, group_of, names, _g_centres = got if got else (None,) * 4

        pts = np.array([[g["x"], g["y"], g["z"]] for g in gs], dtype=np.float64)
        labels = _cluster(pts)

        # Every round of this map and side, unpacked ONCE. The old version
        # unpacked them again per spot, which on seventeen spots meant reading
        # the same blob seventeen times.
        unpacked: dict = {}
        for r in here:
            u = unpack_round(r["data"])
            if u is not None:
                unpacked[(r["match_key"], r["round_num"])] = u

        spots: dict = {}
        for g, lab in zip(gs, labels):
            s = spots.setdefault(lab, {"throws": [], "rounds": {}})
            s["throws"].append(g)
            key = (g["match_key"], g["round_num"])
            s["rounds"][key] = min(s["rounds"].get(key, 1e9), g["seconds"])

        for lab, s in spots.items():
            with_r = set(s["rounds"])
            without_r = {(r["match_key"], r["round_num"]) for r in here} - with_r
            if len(with_r) < MIN_EACH or len(without_r) < MIN_EACH:
                continue
            throw_pts = np.array([[g["x"], g["y"], g["z"]] for g in s["throws"]],
                                 dtype=np.float64)
            centre = _spot_centre(throw_pts)
            t0 = float(np.median([g["seconds"] for g in s["throws"]]))
            t1 = t0 + SMOKE_LIFE + REACH_AFTER

            # ---- how well it was thrown, and how those rounds went
            off = np.hypot(throw_pts[:, 0] - centre[0], throw_pts[:, 1] - centre[1])
            on_rounds, off_rounds = set(), set()
            for g, d in zip(s["throws"], off):
                (on_rounds if d <= ON_SPOT else off_rounds).add(
                    (g["match_key"], g["round_num"]))
            # A round with one throw on the spot and one off is on: the ground
            # the call wanted covered was covered.
            off_rounds -= on_rounds

            def score(rs):
                w = sum(1 for r in rs
                        if won.get(r) is not None and won[r] == (side == "ct"))
                return {"n": len(rs), "won": w}

            tally = {True: {"n": 0, "won": 0, "seen": 0, "zones": {}},
                     False: {"n": 0, "won": 0, "seen": 0, "zones": {}}}
            for r in here:
                key = (r["match_key"], r["round_num"])
                u = unpacked.get(key)
                if u is None:
                    continue
                meta, _ids, sm = u
                secs = sample_seconds(meta)
                window = (secs >= t0) & (secs <= t1)
                if not window.any():
                    continue
                block = sm[window]
                alive = (block["flags"] & FLAG_ALIVE).astype(bool)
                is_ct = (block["flags"] & FLAG_CT).astype(bool)
                ours = (is_ct if side == "ct" else ~is_ct) & alive
                theirs = (~is_ct if side == "ct" else is_ct) & alive

                t = tally[key in with_r]
                t["n"] += 1
                ct_won = won.get(key)
                if ct_won is not None and ct_won == (side == "ct"):
                    t["won"] += 1

                d2 = ((block["x"].astype(np.float64) - centre[0]) ** 2
                      + (block["y"].astype(np.float64) - centre[1]) ** 2)
                floor = np.abs(block["z"].astype(np.float64)
                               - centre[2]) <= FLOOR_TOLERANCE
                if bool(((d2 <= SMOKE_RADIUS ** 2) & floor & theirs).any()):
                    t["seen"] += 1

                if centres is None:
                    continue
                grouped = group_of[_assign(centres, block["x"], block["y"],
                                           block["z"])]
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
            for g_id, other in b["zones"].items():
                if g_id in a["zones"] or other / b["n"] < MIN_REACH:
                    continue
                if 100.0 * other / b["n"] < MIN_GAP:
                    continue
                reach.append({"zone": names.get(g_id, f"zone {g_id}"),
                              "with": 0, "without": other,
                              "gap": -100.0 * other / b["n"]})
            reach.sort(key=lambda z: -abs(z["gap"]))

            # ---- who else throws it
            near_ref = None
            for spot in ref.get((mp, side), []):
                d = float(np.hypot(spot["centre"][0] - centre[0],
                                   spot["centre"][1] - centre[1]))
                if abs(spot["centre"][2] - centre[2]) > FLOOR_TOLERANCE:
                    continue
                if d <= SPOT_RADIUS and (near_ref is None or d < near_ref["off"]):
                    near_ref = {"off": d, "thrown": spot["thrown"],
                                "matches": spot["matches"]}

            purposes: dict = {}
            for g in s["throws"]:
                purposes[g["purpose"]] = purposes.get(g["purpose"], 0) + 1
            top = max(purposes.items(), key=lambda kv: kv[1])

            out.append({
                "map": mp, "side": side,
                "where": _near_zone(centres, group_of, names, centre),
                "at": t0, "thrown": len(s["throws"]),
                "purpose": top[0], "purpose_n": top[1], "purposes": purposes,
                "with": a, "without": b, "reach": reach[:3],
                "on_spot": score(on_rounds), "off_spot": score(off_rounds),
                "median_off": float(np.median(off)),
                "reference": near_ref,
            })
    out.sort(key=lambda s: -(s["with"]["n"] + s["without"]["n"]))
    return out


def _near_zone(centres, group_of, names, xyz) -> str:
    """The named zone a smoke landed in, so the call can be called something."""
    if centres is None:
        return ""
    zone = int(_assign(centres, np.array([xyz[0]]), np.array([xyz[1]]),
                       np.array([xyz[2]]))[0])
    return names.get(int(group_of[zone]), "") if zone else ""


def coverage(team_id: int) -> dict:
    """How many of the league's recurring smokes you throw at all.

    A spot you never use is not a mistake, and this does not call it one. It is
    the cheapest thing to notice about a map pool and the hardest to see from
    inside your own demos.
    """
    ref = catalogue(team_id)
    if not ref:
        return {}
    mine = _smokes_with_context(team_id, ours=True)
    out: dict = {}
    for key, spots in ref.items():
        yours = mine.get(key, [])
        pts = (np.array([[g["x"], g["y"], g["z"]] for g in yours],
                        dtype=np.float64) if yours else np.zeros((0, 3)))
        hit = 0
        for spot in spots:
            if not len(pts):
                continue
            d = np.hypot(pts[:, 0] - spot["centre"][0],
                         pts[:, 1] - spot["centre"][1])
            floor = np.abs(pts[:, 2] - spot["centre"][2]) <= FLOOR_TOLERANCE
            if bool(((d <= SPOT_RADIUS) & floor).any()):
                hit += 1
        out[key] = {"theirs": len(spots), "yours_hit": hit}
    return out
