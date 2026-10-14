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

How a snapshot is read (alive from death events, positions from 8 Hz
samples) is in counterplay/posfeat.py; this module only builds and caches
them for every tier.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app import corpus, db
from counterplay import posfeat as PF
from counterplay import state as state_mod

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ml"
CACHE_VERSION = 5

# The snapshot itself lives in counterplay/posfeat.py, shared with the
# decision scorer's tree model, so both read positions the same way.
PLAYER_FEATURES, SLOTS, POSFEAT = PF.PLAYER_FEATURES, PF.SLOTS, PF.POSFEAT

TIERS = ("league", "pro", "esea")


@dataclass
class Snapshots:
    states: pd.DataFrame
    players: np.ndarray
    posfeat: np.ndarray
    has_positions: np.ndarray       # False where the round had no blob


def build() -> Snapshots:
    db.init()
    frames = []
    for t in TIERS:
        rounds, events = corpus.load_frames(tier=t)
        if len(rounds):                 # a tier with no matches yet is skipped
            frames.append(state_mod.build_states(rounds, events))
    states = pd.concat(frames, ignore_index=True)
    # Each side's skill level that round (ml/levels.py): NECC division,
    # ESEA division or pro, as ids into levels.LEVELS.
    from . import levels
    lv = levels.load()
    states = states.merge(lv, on=["match_id", "round_num"], how="left")
    for side in ("ct", "t"):
        states[f"level_{side}_id"] = (states[f"level_{side}"].fillna("unknown")
                                      .map(levels.LEVEL_IDS).astype(int))
    players, posfeat, has = PF.snapshots(states, with_players=True)
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
