"""Patterns in where people go, not just what happened to them.

Everything else in the report counts events: kills, deaths, buys, round wins.
Those answer "what happened" and never "why". A team that loses its T rounds on
Inferno already knows it loses its T rounds on Inferno. What it cannot see from
a scoreboard is that four of them walk into Banana inside the first twenty
seconds of nearly every one of those rounds, and that the three rounds they did
not, they won.

That question needs positions, and positions need names, because no coach can
act on "zone 8". So this joins two things built separately: the packed
per-round position samples, and the zone names a person typed once per map.

Named zones only. An unnamed zone is skipped rather than printed as a number.

COUNTED, NOT MODELLED
---------------------
Same rule as the rest of the report. Every line is "this happened in N rounds
out of M", both numbers shown, nothing estimated and nothing weighted. Below
MIN_PATTERN_CHANCES a line is dropped rather than shown as a percentage of four.
"""
from __future__ import annotations

import numpy as np

from . import db, memo
from .report import (MIN_PATTERN_CHANCES, _side_by_round, _team_match_keys,
                     team_anchors)
from counterplay import zonemodel as ZM
from counterplay.schema import classify_round
from counterplay.positions import FLAG_ALIVE, FLAG_CT, sample_seconds, unpack_round

# How many of a side have to be somewhere before it is a commitment rather than
# one player wandering. Three of five is a decision the other two live with.
COMMIT_PLAYERS = 3

# The window a commitment has to fall in, in seconds from freeze-end. Before
# five seconds everyone is still in spawn; after forty-five a group arriving
# somewhere is a rotation or a retake, which is a different thing with a
# different name and should not be counted as the same habit.
COMMIT_FROM, COMMIT_TO = 5.0, 45.0

# A group has to stay put this long before it counts. Five players filing
# through a corridor on the way somewhere else are momentarily "together" in
# it; that is not a decision, it is a doorway. Holding a zone for two seconds
# is.
COMMIT_DWELL = 2.0

# Where the round started, measured from the side's own position this early.
# Used to work out how FAR a group gets, not to exclude anything.
ORIGIN_BY = 2.0

# Where a side stands once the round has shape but before contact decides it.
SETUP_AT = 12.0

# How many have to be in one place at SETUP_AT to call it a hold rather than a
# player passing through.
SETUP_PLAYERS = 2

# A zone has to carry this share of rounds to be a habit rather than a thing
# that happened twice.
MIN_ZONE_SHARE = 0.15


def _centres(map_name):
    """The stored zone model for a map, with same-named zones merged.

    Read from the STORED model, never re-clustered here. Re-clustering would
    move the centres as the corpus grows and quietly re-point every name.

    Two zones given the same name ARE the same place — clustering split Inferno's
    T ramp in two and Nuke's B site in two because those places are big, not
    because they are two places. Merging them matters for more than tidy output:
    a group of three standing across both halves of B site would otherwise count
    as two of one zone and one of another, and register as nowhere at all.

    Assignment still uses all twenty zones, so the geometry stays as fine as
    the clustering made it; only the reporting collapses.

    The first element is a ZM.Zones, not a bare array: it carries the walked
    ground as well as the centres, and `_assign` is the only thing that reads
    it.
    """
    zs = ZM.load(map_name)
    if not zs:
        return None
    names = ZM.names(map_name)
    if not names:
        return None
    centres = np.array([[q["cx"], q["cy"], q["cz"]] for q in zs], dtype=np.float64)

    group_of = np.zeros(len(zs) + 1, dtype=int)   # zone index -> group, 0 = drop
    by_name: dict[str, int] = {}
    g_names: dict[int, str] = {}
    g_pts: dict[int, list] = {}
    for i in range(1, len(zs) + 1):
        nm = names.get(i)
        if not nm or _is_spawn(nm):
            continue                              # unnamed and spawn never report
        key = nm.strip().lower()
        if key not in by_name:
            by_name[key] = len(by_name) + 1
            g_names[by_name[key]] = nm.strip()
        g = by_name[key]
        group_of[i] = g
        g_pts.setdefault(g, []).append((centres[i - 1], zs[i - 1]["share"]))

    # A merged group sits at its parts' traffic-weighted centre.
    n_g = len(by_name)
    g_centres = np.zeros((n_g + 1, 3), dtype=np.float64)
    for g, parts in g_pts.items():
        w = np.array([max(p[1], 1e-9) for p in parts])
        g_centres[g] = (np.array([p[0] for p in parts]) * w[:, None]).sum(0) / w.sum()
    return ZM.Zones(centres, ZM.walk(map_name, zs)), group_of, g_names, g_centres


def _assign(zones, sx, sy, sz):
    """Zone index for every sample in a round. 1-based; 0 means nowhere.

    WALKED, not straight-line: a position belongs to the zone whose anchor
    it is fewest walked units from, over ground people have stood on, so a
    zone cannot reach through a wall into the next room. See the walking
    notes in counterplay/zonemodel.py.

    Height is weighted exactly as the clustering weighted it. That is not a
    detail: on Nuke the two bombsites sit 369 units above each other, so
    unweighted distance would file half of B site under A.
    """
    return zones.assign(sx, sy, sz)


def groups_of_samples(map_name, x, y, z, chunk: int = 200_000):
    """The name-group every sample is counted under, by the rule scan() uses.

    For the zone drawing, so a region is painted where its kills and deaths
    were actually counted. It used to be painted by its own rule, nearest
    centre in the plane over one floor, and numbered by zone index while the
    counts were numbered by group, so from the first repeated name onward every
    shape carried another place's numbers and another place's name.

    Returns (groups per sample, group_of) or None when the map has no names.
    Chunked, because a map's samples times its centres in float64 is most of
    a gigabyte on Mirage.
    """
    got = _centres(map_name)
    if got is None:
        return None
    centres, group_of, _names, _gc = got
    x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
    out = np.zeros(len(x), dtype=np.int32)
    for s in range(0, len(x), chunk):
        e = s + chunk
        out[s:e] = group_of[_assign(centres, x[s:e], y[s:e], z[s:e])]
    return out, group_of


def _rounds_with_positions(team_id):
    """Every round of this team's that has position samples, with its outcome."""
    keys = _team_match_keys(team_id)
    if not keys:
        return []
    marks = ",".join("?" * len(keys))
    return db.query(f"""SELECT rp.match_key, rp.round_num, rp.data,
                               m.map_name, r.ct_won, r.equip_ct, r.equip_t
                          FROM round_positions rp
                          JOIN matches m ON m.match_key = rp.match_key
                          JOIN rounds  r ON r.match_key = rp.match_key
                                        AND r.round_num = rp.round_num
                         WHERE rp.match_key IN ({marks})
                      ORDER BY m.map_name, rp.match_key, rp.round_num""", *keys)


def _is_spawn(name: str) -> bool:
    """Standing in spawn is not a commitment, however many of you do it."""
    return "spawn" in name.lower()


def _plant_lookup(keys) -> dict:
    """(match_key, round_num) -> seconds into the round the bomb went down.

    Absent means no plant, which makes every death in that round pre-plant.
    events.seconds shares its origin with positions.sample_seconds: both are
    measured from the round's freeze-end.
    """
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    return {(r["match_key"], r["round_num"]): float(r["s"])
            for r in db.query(f"""SELECT match_key, round_num, MIN(seconds) s
                                    FROM events
                                   WHERE match_key IN ({marks})
                                     AND type = 'plant'
                                GROUP BY match_key, round_num""", *keys)}


def _traded_lookup(keys) -> dict:
    """(match_key, round_num, steamid) -> was that death traded.

    A player dies at most once in a CS2 round, so `traded_deaths` on their
    player-round row is 0 or 1 and answers the question for that one death
    without needing a per-death table.
    """
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    return {(r["match_key"], r["round_num"], r["steamid"]): bool(r["traded_deaths"])
            for r in db.query(f"""SELECT match_key, round_num, steamid,
                                         traded_deaths
                                    FROM player_rounds
                                   WHERE match_key IN ({marks})
                                     AND traded_deaths > 0""", *keys)}


def _fights(alive, on_our_side, gid):
    """Every death in a round: (sample index, place, whether it was ours).

    One of ours dying is a death, one of theirs a kill. The place is where the
    victim fell, read at the first sample they are dead and, when that sample
    places them nowhere, the last one they were alive.

    Side is read at t_i, while the player is still standing: a player missing
    from a tick is written all-zero, which would read as T side.

    `on_our_side` used to be called `theirs`, which it never was. The code
    was right and the name said the opposite, so it read as a bug to anyone
    who looked; tests/test_movement.py pins the direction.
    """
    for t_i, p_i in np.argwhere(alive[:-1] & ~alive[1:]):
        z = int(gid[t_i + 1, p_i]) or int(gid[t_i, p_i])
        if z:
            yield int(t_i), z, bool(on_our_side[t_i, p_i])


@memo.by_team
def scan(team_id: int) -> dict:
    """Walk every round once, collecting the counts every pattern needs.

    One pass: unpacking a round and assigning its samples to zones is the
    expensive part, and there is no reason to pay it once per pattern.
    """
    anchors = team_anchors(team_id)
    sides = _side_by_round(team_id, anchors.get("anchors", {}))
    rows = _rounds_with_positions(team_id)
    traded = _traded_lookup(_team_match_keys(team_id))
    plants = _plant_lookup(_team_match_keys(team_id))
    opening: dict = {}

    commit: dict = {}
    setup: dict = {}
    # map -> zone -> (side, phase, buy) -> [kills, deaths]
    duels: dict = {}
    death: dict = {}
    seen: dict = {}
    # Rounds WON per map and side, so a row can be read against the rest of
    # the same map and side rather than against a season average that is
    # mostly the map pool.
    seen_won: dict = {}
    # Rounds where three of them held anything at all. The commit denominator:
    # a round where the group never grouped is not a round where they went
    # somewhere else.
    answered: dict = {}
    cache: dict = {}

    for r in rows:
        side = sides.get((r["match_key"], r["round_num"]))
        if side not in ("ct", "t"):
            continue          # cannot say which five are theirs; skip, never guess
        mp = r["map_name"]
        if mp not in cache:
            cache[mp] = _centres(mp)
        got = cache[mp]
        if got is None:
            continue
        centres, group_of, names, g_centres = got

        unpacked = unpack_round(r["data"])
        if unpacked is None:
            continue
        meta, _sids, sm = unpacked
        secs = sample_seconds(meta)
        alive = (sm["flags"] & FLAG_ALIVE).astype(bool)
        is_ct = (sm["flags"] & FLAG_CT).astype(bool)

        # Who is ours: the players on our side. Read per sample rather than
        # once, so a late joiner or a disconnect is handled by the alive bit
        # instead of by a fixed index into the roster.
        on_our_side = is_ct if side == "ct" else ~is_ct
        ours_alive = on_our_side & alive
        if not ours_alive.any():
            continue

        won = bool(r["ct_won"]) == (side == "ct")
        seen.setdefault(mp, {}).setdefault(side, 0)
        seen[mp][side] += 1
        seen_won.setdefault(mp, {}).setdefault(side, 0)
        seen_won[mp][side] += won

        # Assign against every centre, then collapse same-named zones into one.
        gid = group_of[_assign(centres, sm["x"], sm["y"], sm["z"])]
        nz = len(names)

        masked = np.where(ours_alive, gid, 0)
        occ = np.zeros((len(secs), nz + 1), dtype=np.int32)
        rowi = np.repeat(np.arange(len(secs)), masked.shape[1])
        np.add.at(occ, (rowi, masked.ravel()), 1)
        occ[:, 0] = 0

        # ---- how far the group gets, and where
        #
        # The first zone three of them share is worthless: on Inferno it is
        # always T ramp and on Nuke always lobby, in 92% and 96% of rounds,
        # because those are the only ways out of spawn. A thing that happens
        # every round is the map, not the team.
        #
        # What varies is how FAR they push together. So among every zone the
        # group actually holds inside the window, take the one furthest from
        # where the round began. On Inferno that is Banana or B site rather
        # than the corridor leading to them; on CT it is the forward hold
        # rather than spawn. Same measure, no per-map list.
        early = secs <= ORIGIN_BY
        oa = ours_alive[early]
        if not oa.any():
            continue
        ox = float(np.median(sm["x"][early][oa].astype(np.int32)))
        oy = float(np.median(sm["y"][early][oa].astype(np.int32)))
        oz = float(np.median(sm["z"][early][oa].astype(np.int32)))

        win = (secs >= COMMIT_FROM) & (secs <= COMMIT_TO)
        if win.any():
            sub = occ[win]
            held = sub >= COMMIT_PLAYERS
            # Sustained, not a passing frame: the group has to still be there
            # COMMIT_DWELL later. Five players filing through a doorway are
            # momentarily "together" in it; that is not a decision.
            step = max(1, int(round(COMMIT_DWELL / max(secs[1] - secs[0], 1e-6))))
            if step > 1 and len(held) > step:
                held = held[:-step] & held[step:]
            zones = np.nonzero(held.any(axis=0))[0]
            if len(zones):
                d = np.hypot(g_centres[zones, 0] - ox, g_centres[zones, 1] - oy)
                z_i = int(zones[int(np.argmax(d))])
                t_i = int(np.argmax(held[:, z_i]))
                rec = commit.setdefault(mp, {}).setdefault(side, {}).setdefault(
                    z_i, {"n": 0, "won": 0, "secs": []})
                rec["n"] += 1
                rec["won"] += won
                rec["secs"].append(float(secs[win][t_i]))
                answered.setdefault(mp, {}).setdefault(side, 0)
                answered[mp][side] += 1

        # ---- the default setup
        at = int(np.argmin(np.abs(secs - SETUP_AT)))
        if abs(secs[at] - SETUP_AT) < 3.0:
            for z_i in np.nonzero(occ[at] >= SETUP_PLAYERS)[0]:
                d = setup.setdefault(mp, {}).setdefault(side, {}).setdefault(
                    int(z_i), {"n": 0, "won": 0, "players": 0})
                d["n"] += 1
                d["won"] += won
                d["players"] += int(occ[at, z_i])

        # ---- every kill and death, bucketed for the filters
        #
        # Same walk as the opening duel below, without stopping at the first
        # transition. Ours are deaths, theirs are kills.
        plant_at = plants.get((r["match_key"], r["round_num"]))
        buy = classify_round(
            r["equip_ct"] if side == "ct" else r["equip_t"], r["round_num"])
        for t_i, z_d, was_ours in _fights(alive, on_our_side, gid):
            phase = ("post" if plant_at is not None
                     and secs[t_i + 1] >= plant_at else "pre")
            rec = duels.setdefault(mp, {}).setdefault(z_d, {}).setdefault(
                (side, phase, buy), [0, 0])
            rec[1 if was_ours else 0] += 1

        # ---- the opening duel: the first death on EITHER side
        #
        # `fell` is every alive-to-dead transition regardless of side, so the
        # first one is the round's opening kill. Whether the faller was ours
        # decides whether we won it.
        #
        # Side is read at t_i, the last sample the player was ALIVE. A dead
        # slot keeps its team flag in practice, but a player missing from a
        # tick is written all-zero, which would read as T side; taking it
        # while they are still standing cannot be wrong.
        fell = alive[:-1] & ~alive[1:]
        if fell.any():
            t_i, p_i = np.argwhere(fell)[0]
            z = int(gid[t_i + 1, p_i]) or int(gid[t_i, p_i])
            if z:
                d = opening.setdefault(mp, {}).setdefault(side, {}).setdefault(
                    z, {"n": 0, "won_duel": 0, "lost": 0, "traded": 0,
                        "round_won": 0})
                d["n"] += 1
                d["round_won"] += won
                if bool(on_our_side[t_i, p_i]):
                    d["lost"] += 1
                    sid_o = str(int(_sids[p_i]))
                    d["traded"] += int(traded.get(
                        (r["match_key"], r["round_num"], sid_o), False))
                else:
                    d["won_duel"] += 1

        # ---- where the first of ours dies, and whether anyone got him back
        #
        # The place alone says where a round starts going wrong. Whether the
        # death was traded says whether it went wrong: the same first death,
        # traded, leaves a 4v4, and untraded leaves a 4v5.
        died = alive[:-1] & ~alive[1:] & on_our_side[1:]
        if died.any():
            t_i, p_i = np.argwhere(died)[0]
            z = int(gid[t_i + 1, p_i])
            if z:
                d = death.setdefault(mp, {}).setdefault(side, {}).setdefault(
                    z, {"n": 0, "won": 0, "traded": 0})
                d["n"] += 1
                d["won"] += won
                sid = str(int(_sids[p_i]))
                d["traded"] += int(traded.get(
                    (r["match_key"], r["round_num"], sid), False))

    return {"commit": commit, "setup": setup, "death": death,
            "opening": opening, "duels": duels, "seen": seen,
            "seen_won": seen_won, "answered": answered,
            "names": {m: (cache[m][2] if cache.get(m) else {}) for m in cache}}


@memo.by_team
def positional_patterns(team_id: int) -> list[dict]:
    """Habits in where this team goes, one line each.

    Ordered by how many rounds back them, so the thing that happens most is
    read first. Each carries its map and side, because "you push Banana" is a
    sentence about Inferno's T side and nowhere else.
    """
    raw = scan(team_id)
    names = raw["names"]
    out: list[dict] = []

    def add(kind, mp, side, zone, hit, of, won, detail, extra="", traded=None):
        if of < MIN_PATTERN_CHANCES or hit / of < MIN_ZONE_SHARE:
            return
        # The rest of this map and this side. Every round on it either had the
        # thing or did not, so the two groups are a partition and subtracting
        # is exact rather than approximate.
        side_n = raw["seen"][mp][side]
        side_won = raw["seen_won"][mp][side]
        other = side_n - hit
        other_won = side_won - won
        out.append({
            "kind": kind, "map": mp, "side": side,
            "zone": names.get(mp, {}).get(zone, f"zone {zone}"),
            # The CLUSTER, carried alongside its name. Two clusters can share
            # a name: Mirage has three called "A main" because A main is big
            # enough to split three ways. Keying anything on the name alone
            # silently treats them as one place.
            "zone_index": zone,
            "hit": hit, "of": of, "pct": 100.0 * hit / of,
            "won": won, "win_pct": (100.0 * won / hit) if hit else 0.0,
            # What the same map and side did in the rounds without it.
            "other": other, "other_won": other_won,
            "other_pct": (100.0 * other_won / other) if other else 0.0,
            # The two denominators this map and side can have: every round,
            # and the rounds where three of them held anything at all. A
            # commit row is counted out of the second, and the difference
            # between them is a fact about the team rather than a technicality.
            "side_rounds": side_n,
            "answered": raw["answered"].get(mp, {}).get(side, 0),
            "gap": ((100.0 * won / hit) if hit else 0.0)
                   - ((100.0 * other_won / other) if other else 0.0),
            # Only a first death can be traded, so this is None for the other
            # two kinds rather than zero. Zero would render as "traded 0 of 14"
            # under a setup, which is not a thing that can happen.
            "traded": traded,
            "traded_pct": (100.0 * traded / hit) if traded is not None and hit
                          else 0.0,
            "detail": detail, "extra": extra})

    for mp, per_side in raw["commit"].items():
        for side, zones in per_side.items():
            # Out of the rounds that HAVE an answer, not out of every round.
            of = raw["answered"].get(mp, {}).get(side, 0)
            for z, d in zones.items():
                med = float(np.median(d["secs"]))
                add("commit", mp, side, z, d["n"], of, d["won"],
                    f"The furthest {COMMIT_PLAYERS} of you get together inside "
                    f"the first {int(COMMIT_TO)} seconds, and hold. Corridors "
                    f"on the way do not count; this is where the group "
                    f"actually arrives.",
                    f"usually by {med:.0f}s")

    for mp, per_side in raw["setup"].items():
        for side, zones in per_side.items():
            of = raw["seen"][mp][side]
            for z, d in zones.items():
                avg = d["players"] / d["n"]
                add("setup", mp, side, z, d["n"], of, d["won"],
                    f"{SETUP_PLAYERS} or more of you are here {int(SETUP_AT)} "
                    f"seconds in, after the round has shape and before contact "
                    f"decides it. This is your default.",
                    f"{avg:.1f} players on average")

    for mp, per_side in raw["death"].items():
        for side, zones in per_side.items():
            of = raw["seen"][mp][side]
            for z, d in zones.items():
                tr = d.get("traded", 0)
                add("death", mp, side, z, d["n"], of, d["won"],
                    "The first of you to die, dies here, and whether anybody "
                    "got him back. Where a round starts going wrong is more "
                    "useful than how often it does, and a first death that is "
                    "traded leaves a 4v4 rather than a 4v5.",
                    f"traded {tr} of {d['n']}",
                    traded=tr)

    return sorted(out, key=lambda p: (-p["hit"], p["map"]))


# One match is not a season, so a per-match view reports fewer rounds and says
# so rather than pretending a habit is visible in twenty-four of them.
MATCH_MIN_ROUNDS = 3


def match_positions(match_key: str, team_id: int) -> dict:
    """Where this team went in ONE match, round by round.

    Everything positional was season-level, which meant a coach opening a single
    game — because something went wrong in THAT game — got a scoreboard, buys
    and a timeline, and not the one thing this product is actually good at.

    The data was always there; every round has its positions stored. What was
    missing was asking the question of one match instead of eleven.

    Returns the same three views the season page uses, plus a per-round list so
    a coach can read down the match and see where each round was decided.
    """
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)
    traded = _traded_lookup([match_key])

    rows = db.query("""SELECT rp.round_num, rp.data, m.map_name, r.ct_won
                         FROM round_positions rp
                         JOIN matches m ON m.match_key = rp.match_key
                         JOIN rounds  r ON r.match_key = rp.match_key
                                       AND r.round_num = rp.round_num
                        WHERE rp.match_key = ?
                     ORDER BY rp.round_num""", match_key)
    if not rows:
        return {"rounds": [], "commit": [], "death": [], "map": None}

    mp = rows[0]["map_name"]
    got = _centres(mp)
    if got is None:
        return {"rounds": [], "commit": [], "death": [], "map": mp}
    centres, group_of, names, g_centres = got

    per_round, commit_tally, death_tally = [], {}, {}

    for r in rows:
        side = sides.get((match_key, r["round_num"]))
        unpacked = unpack_round(r["data"])
        if side not in ("ct", "t") or unpacked is None:
            continue
        meta, _sids, sm = unpacked
        secs = sample_seconds(meta)
        alive = (sm["flags"] & FLAG_ALIVE).astype(bool)
        is_ct = (sm["flags"] & FLAG_CT).astype(bool)
        on_our_side = is_ct if side == "ct" else ~is_ct
        ours = on_our_side & alive
        if not ours.any():
            continue
        won = bool(r["ct_won"]) == (side == "ct")

        gid = group_of[_assign(centres, sm["x"], sm["y"], sm["z"])]
        nz = len(names)
        masked = np.where(ours, gid, 0)
        occ = np.zeros((len(secs), nz + 1), dtype=np.int32)
        rowi = np.repeat(np.arange(len(secs)), masked.shape[1])
        np.add.at(occ, (rowi, masked.ravel()), 1)
        occ[:, 0] = 0

        # Where the group got to, by the same measure the season view uses.
        early = secs <= ORIGIN_BY
        oa = ours[early]
        went = at = None
        if oa.any():
            ox = float(np.median(sm["x"][early][oa].astype(np.int32)))
            oy = float(np.median(sm["y"][early][oa].astype(np.int32)))
            win = (secs >= COMMIT_FROM) & (secs <= COMMIT_TO)
            if win.any():
                sub = occ[win]
                held = sub >= COMMIT_PLAYERS
                step = max(1, int(round(COMMIT_DWELL /
                                        max(secs[1] - secs[0], 1e-6))))
                if step > 1 and len(held) > step:
                    held = held[:-step] & held[step:]
                zs_ = np.nonzero(held.any(axis=0))[0]
                if len(zs_):
                    d = np.hypot(g_centres[zs_, 0] - ox, g_centres[zs_, 1] - oy)
                    z_i = int(zs_[int(np.argmax(d))])
                    went = names.get(z_i)
                    at = float(secs[win][int(np.argmax(held[:, z_i]))])
                    if went:
                        c = commit_tally.setdefault(went, {"n": 0, "won": 0})
                        c["n"] += 1
                        c["won"] += won

        # Where the first of ours died.
        died_in = None
        was_traded = None
        fell = alive[:-1] & ~alive[1:] & on_our_side[1:]
        if fell.any():
            t_i, p_i = np.argwhere(fell)[0]
            z = int(gid[t_i + 1, p_i])
            if z:
                died_in = names.get(z)
                sid = str(int(_sids[p_i]))
                was_traded = bool(traded.get((match_key, r["round_num"], sid)))
                if died_in:
                    d = death_tally.setdefault(
                        died_in, {"n": 0, "won": 0, "traded": 0})
                    d["n"] += 1
                    d["won"] += won
                    d["traded"] += int(was_traded)

        per_round.append({"round_num": r["round_num"], "side": side, "won": won,
                          "went": went, "at": at, "died_in": died_in,
                          "traded": was_traded})

    def rank(tally):
        return sorted(({"zone": k, "n": v["n"], "won": v["won"],
                        "traded": v.get("traded")}
                       for k, v in tally.items()
                       if v["n"] >= MATCH_MIN_ROUNDS),
                      key=lambda x: -x["n"])

    return {"rounds": per_round, "commit": rank(commit_tally),
            "death": rank(death_tally), "map": mp}
