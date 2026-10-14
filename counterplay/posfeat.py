"""Where everyone stood at each moment the win-probability model scores.

    states = posfeat.attach(states)              # adds the POSFEAT columns
    players, feats, has = posfeat.snapshots(states, with_players=True)

The decision scorer's model (counterplay/model.py, config "smallpos") reads
nine summaries of the ten players on top of the eleven state numbers, and
the PyTorch network (ml/) reads every player. Both come from here, so the
two cannot compute "players in bombsite 1" two different ways. No torch,
nothing but numpy and the database.

Positions are read at the first 8 Hz sample at or after each event. Alive
or dead is NOT read from the samples: a trade lands two deaths inside an
eighth of a second, a sample just after the first catches the second too,
and that disagreed with the row's alive counts on 1.4% to 3% of rows
(2026-10-14). It comes from the death events, which carry the victim and
the exact time; positions and health come from the samples. The remaining
0.8% disagreement is rounds a side played short (a disconnect), where these
counts are right and state.py's 5-on-5 start is not (TODO.md).

Player slots 0-4 are CT and 5-9 are T; an empty slot is all zeros.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app import db

from . import positions as P
from .schema import POSFEAT as SCHEMA_POSFEAT

# Per player: x, y, z (normalised per map), health / 100, alive, facing as
# sin and cos, standing in bombsite 1, in bombsite 2.
PLAYER_FEATURES = ["x", "y", "z", "health", "alive", "yaw_sin", "yaw_cos",
                   "site1", "site2"]
SLOTS = 10

# What a tree model reads (named in schema.py): total health per side (in
# players' worth, so 5.0 is five full-health players), players in each
# bombsite per side, how spread out each side is and the closest CT-T pair
# (thousands of units). The order is the order _snapshot returns them in.
POSFEAT = SCHEMA_POSFEAT

_NO_NORM = (0.0, 0.0, 0.0, 1.0, 1.0)


def _round_players(flags):
    """Indices of the (up to) five CT and five T who played the round:
    anyone alive in the first two seconds, which leaves out coaches and
    spectators, who are on the server but never alive."""
    early = (flags[: 16] & P.FLAG_ALIVE) != 0
    played = early.any(axis=0)
    is_ct = ((flags[: 16] & P.FLAG_CT) != 0).any(axis=0)
    ct = [i for i in np.flatnonzero(played & is_ct)][:5]
    t = [i for i in np.flatnonzero(played & ~is_ct)][:5]
    return ct, t


def _snapshot(samples, row_idx, ct, t, norm, dead):
    """One (10, F) snapshot and its summary features. `dead` is the roster
    indices the death events have killed by this moment."""
    mx, my, mz, sxy, sz = norm
    s = samples[row_idx]
    out = np.zeros((SLOTS, len(PLAYER_FEATURES)), dtype=np.float32)
    pts = {"ct": [], "t": []}
    hp = {"ct": 0.0, "t": 0.0}
    site = {("ct", 1): 0, ("ct", 2): 0, ("t", 1): 0, ("t", 2): 0}
    for base, side, idx in ((0, "ct", ct), (5, "t", t)):
        for k, i in enumerate(idx):
            p = s[i]
            alive = i not in dead
            health = int(p["health"])
            if alive and not (p["flags"] & P.FLAG_ALIVE):
                # Killed a tick or two after this event, so the sample shows
                # them dead already: take their last living health.
                back = samples[max(0, row_idx - 16):row_idx, i]
                live = back[(back["flags"] & P.FLAG_ALIVE) != 0]
                health = int(live["health"][-1]) if len(live) else 100
            zone = int((p["flags"] & P.ZONE_MASK) >> P.ZONE_SHIFT)
            yaw = (p["yaw"] / 255.0) * 2 * np.pi - np.pi
            out[base + k] = (
                (p["x"] - mx) / sxy, (p["y"] - my) / sxy, (p["z"] - mz) / sz,
                health / 100.0 if alive else 0.0, float(alive),
                np.sin(yaw), np.cos(yaw), float(zone == 1), float(zone == 2))
            if alive:
                pts[side].append((float(p["x"]), float(p["y"])))
                hp[side] += health
                if zone in (1, 2):
                    site[(side, zone)] += 1

    def spread(v):
        if len(v) < 2:
            return 0.0
        a = np.asarray(v)
        return float(np.mean(np.linalg.norm(a - a.mean(axis=0), axis=1))) / 1000.0

    if pts["ct"] and pts["t"]:
        a, b = np.asarray(pts["ct"]), np.asarray(pts["t"])
        closest = float(np.min(np.linalg.norm(a[:, None] - b[None], axis=2))) / 1000.0
    else:
        closest = 0.0
    feat = np.array([hp["ct"] / 100.0, hp["t"] / 100.0, site[("ct", 1)],
                     site[("ct", 2)], site[("t", 1)], site[("t", 2)],
                     spread(pts["ct"]), spread(pts["t"]), closest],
                    dtype=np.float32)
    return out, feat


def map_norms(match_keys) -> dict:
    """Per map: centre and scale of the positions stored for it, for the
    per-player coordinates. Unsupervised, so pooling matches leaks no label.
    The summaries in POSFEAT do not use it."""
    maps = {r["match_key"]: r["map_name"]
            for r in db.query("SELECT match_key, map_name FROM matches")}
    by_map: dict[str, list] = {}
    for k in match_keys:
        by_map.setdefault(maps.get(k, ""), []).append(k)
    norms = {}
    for mp, keys in by_map.items():
        xs, ys, zs = [], [], []
        for k in keys[:400]:                      # a sample is plenty
            for r in db.query("SELECT data FROM round_positions WHERE match_key = ? "
                              "LIMIT 3", k):
                got = P.unpack_round(r["data"])
                if got is None:
                    continue
                s = got[2][::16].ravel()
                live = (s["flags"] & P.FLAG_ALIVE) != 0
                xs.append(s["x"][live]); ys.append(s["y"][live]); zs.append(s["z"][live])
        if not xs:
            norms[mp] = _NO_NORM
            continue
        x, y, z = (np.concatenate(v).astype(np.float64) for v in (xs, ys, zs))
        norms[mp] = (x.mean(), y.mean(), z.mean(),
                     max(x.std(), y.std(), 1.0), max(z.std(), 1.0))
    return {k: norms[maps.get(k, "")] for k in match_keys}


def snapshots(states: pd.DataFrame, with_players: bool = False):
    """(players, feats, has) for every row of `states`, in row order.

    players is (rows, 10, PLAYER_FEATURES), all zeros unless with_players;
    feats is (rows, len(POSFEAT)); has is False where the round has no
    stored positions, whose rows keep zeros.
    """
    n_rows = len(states)
    players = np.zeros((n_rows, SLOTS, len(PLAYER_FEATURES)), dtype=np.float32)
    feats = np.zeros((n_rows, len(POSFEAT)), dtype=np.float32)
    has = np.zeros(n_rows, dtype=bool)
    if not n_rows:
        return players, feats, has
    keys = list(states["match_id"].unique())
    norms = map_norms(keys) if with_players else {k: _NO_NORM for k in keys}
    marks = ",".join("?" * len(keys))
    deaths: dict = {}
    for e in db.query(f"""SELECT match_key, round_num, seconds, victim_steamid
                            FROM events WHERE type = 'death'
                             AND match_key IN ({marks})""", *keys):
        if e["victim_steamid"]:
            deaths.setdefault((e["match_key"], e["round_num"]), []).append(
                (float(e["seconds"]), int(e["victim_steamid"])))
    pos = states.reset_index(drop=True)
    for (mk, rn), rows in pos.groupby(["match_id", "round_num"]).indices.items():
        r = db.one("SELECT data FROM round_positions WHERE match_key = ? AND "
                   "round_num = ?", mk, int(rn))
        got = P.unpack_round(r["data"]) if r else None
        if got is None or not got[0]["n_samples"]:
            continue
        meta, sids, samples = got
        slot_of = {int(sid): i for i, sid in enumerate(sids)}
        died = [(sec, slot_of[v]) for sec, v in deaths.get((mk, int(rn)), [])
                if v in slot_of]
        ct, t = _round_players(samples["flags"])
        n = meta["n_samples"]
        for row in rows:
            secs = float(pos.at[row, "seconds"])
            i = min(n - 1, int(np.ceil(secs * P.TICK_RATE / meta["tick_step"])))
            dead = {slot for sec, slot in died if sec <= secs + 1e-6}
            players[row], feats[row] = _snapshot(samples, i, ct, t, norms[mk], dead)
            has[row] = True
    return players, feats, has


def attach(states: pd.DataFrame) -> pd.DataFrame:
    """`states` with the POSFEAT columns added (a copy). A round with no
    stored positions gets zeros, which the trees read as "unknown"."""
    _players, feats, _has = snapshots(states)
    out = states.copy()
    for j, c in enumerate(POSFEAT):
        out[c] = feats[:, j]
    return out
