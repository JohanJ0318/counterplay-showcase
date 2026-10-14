"""Where all ten players stood at every moment the win-probability model scores.

The shipped model (counterplay/model.py) sees eleven numbers per moment:
players alive, equipment, time, the bomb, the map, the buy. It never sees a
position, so it cannot tell a stacked site from a spread one. This module
attaches a snapshot of every player to EXACTLY the rows that model is scored
on (counterplay.state.build_states), so anything trained on it is compared
with LightGBM on the same moments, the same matches and the same labels.

    snap = load()             # cached in data/ml/, built on first call
    snap.states               # the state rows, as build_states returns them
    snap.players              # (rows, 10, PLAYER_FEATURES) float32
    snap.posfeat              # (rows, len(POSFEAT)) hand-made summaries

Player slots 0-4 are CT and 5-9 are T, alive or not; an empty slot (a
player who disconnected) is all zeros. Within a side the order carries no
meaning, and the network treats it as a set.

Positions are read at the first sample at or after each event (8 Hz).
Alive or dead is NOT read from the samples: a trade lands two deaths within
an eighth of a second, a sample read just after the first catches the
second too, and on 2026-10-14 that disagreed with the row's alive counts on
1.4% to 3% of rows depending on where the read was taken. It comes from the
death events instead, which carry the victim and the exact time.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app import corpus, db
from counterplay import positions as P
from counterplay import state as state_mod

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ml"
CACHE_VERSION = 3

# Per player: x, y, z (normalised per map), health / 100, alive, facing as
# sin and cos, standing in bombsite 1, in bombsite 2.
PLAYER_FEATURES = ["x", "y", "z", "health", "alive", "yaw_sin", "yaw_cos",
                   "site1", "site2"]
SLOTS = 10

# Summaries a tree model can use: total health per side, players in each
# bombsite per side, how spread out each side is, and the closest CT-T pair.
POSFEAT = ["hp_ct", "hp_t", "ct_site1", "ct_site2", "t_site1", "t_site2",
           "ct_spread", "t_spread", "closest_enemy"]

TIERS = ("league", "pro", "esea")


@dataclass
class Snapshots:
    states: pd.DataFrame
    players: np.ndarray
    posfeat: np.ndarray
    has_positions: np.ndarray       # False where the round had no blob


def _round_players(samples, flags):
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
    indices the death events have killed by this moment: alive or dead
    comes from them, positions and health from the samples."""
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


def _map_norms(keys_by_map):
    """Per map: centre and scale of every position stored for it. Positions
    are unsupervised, so pooling every match here leaks no label."""
    norms = {}
    for mp, keys in keys_by_map.items():
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
        x, y, z = (np.concatenate(v).astype(np.float64) for v in (xs, ys, zs))
        norms[mp] = (x.mean(), y.mean(), z.mean(),
                     max(x.std(), y.std(), 1.0), max(z.std(), 1.0))
    return norms


def build() -> Snapshots:
    db.init()
    frames = []
    for t in TIERS:
        rounds, events = corpus.load_frames(tier=t)
        if len(rounds):                 # a tier with no matches yet is skipped
            frames.append(state_mod.build_states(rounds, events))
    states = pd.concat(frames, ignore_index=True)
    maps = {r["match_key"]: r["map_name"]
            for r in db.query("SELECT match_key, map_name FROM matches")}
    by_map: dict[str, list] = {}
    for k in states["match_id"].unique():
        by_map.setdefault(maps.get(k, ""), []).append(k)
    norms = _map_norms(by_map)

    players = np.zeros((len(states), SLOTS, len(PLAYER_FEATURES)), dtype=np.float32)
    posfeat = np.zeros((len(states), len(POSFEAT)), dtype=np.float32)
    has = np.zeros(len(states), dtype=bool)
    deaths: dict = {}
    for e in db.query("""SELECT match_key, round_num, seconds, victim_steamid
                           FROM events WHERE type = 'death'"""):
        if e["victim_steamid"]:
            deaths.setdefault((e["match_key"], e["round_num"]), []).append(
                (float(e["seconds"]), int(e["victim_steamid"])))
    groups = states.groupby(["match_id", "round_num"]).indices
    for (mk, rn), rows in groups.items():
        r = db.one("SELECT data FROM round_positions WHERE match_key = ? AND "
                   "round_num = ?", mk, int(rn))
        got = P.unpack_round(r["data"]) if r else None
        if got is None or not got[0]["n_samples"]:
            continue
        meta, sids, samples = got
        slot_of = {int(sid): i for i, sid in enumerate(sids)}
        died = [(sec, slot_of[v]) for sec, v in deaths.get((mk, int(rn)), [])
                if v in slot_of]
        ct, t = _round_players(samples, samples["flags"])
        norm = norms[maps.get(mk, "")]
        n = meta["n_samples"]
        for row in rows:
            secs = float(states.at[row, "seconds"])
            i = min(n - 1, int(np.ceil(secs * P.TICK_RATE / meta["tick_step"])))
            dead = {slot for sec, slot in died if sec <= secs + 1e-6}
            players[row], posfeat[row] = _snapshot(samples, i, ct, t, norm, dead)
            has[row] = True
    return Snapshots(states, players, posfeat, has)


def load(rebuild: bool = False) -> Snapshots:
    path = CACHE / f"snapshots_v{CACHE_VERSION}.npz"
    sp = CACHE / f"states_v{CACHE_VERSION}.pkl"
    if path.exists() and sp.exists() and not rebuild:
        z = np.load(path)
        return Snapshots(pd.read_pickle(sp), z["players"], z["posfeat"], z["has"])
    snap = build()
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, players=snap.players, posfeat=snap.posfeat,
                        has=snap.has_positions)
    snap.states.to_pickle(sp)
    return snap


if __name__ == "__main__":
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    s = load(rebuild=True)
    print(f"{len(s.states)} rows, {s.has_positions.mean():.1%} with positions; "
          f"tiers {s.states['tier_id'].value_counts().to_dict()}")
