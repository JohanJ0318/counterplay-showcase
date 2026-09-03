"""Reconstruct round state from events alone.

This is the key efficiency decision in v1. Rather than parsing 64 ticks/second
of positional data, we rebuild the state series from a handful of events:
deaths, the plant, and the round boundaries. A round becomes ~12 rows instead
of ~7,000, and the model needs nothing more.
"""
from __future__ import annotations

import pandas as pd

from .schema import (DEFAULT_TIER, MAP_IDS, PLANT_SECONDS, ROUND_SECONDS,
                     ROUND_TYPE_IDS, TIER_IDS, classify_round)


def build_states(rounds: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Turn (rounds, events) into one state row per event, plus round start.

    rounds columns: match_id, round_num, map_name, equip_ct, equip_t, ct_won
    events columns: match_id, round_num, seconds, type, victim_side
                    type is 'death' or 'plant'; victim_side is 'ct'/'t' for deaths.

    Returns a frame with the model features plus bookkeeping columns,
    including `victim_side` — which side lost the player on a death row, and
    None on round-start and plant rows.
    """
    out = []

    ev_by_round = {k: g for k, g in events.groupby(["match_id", "round_num"])}

    for r in rounds.itertuples(index=False):
        key = (r.match_id, r.round_num)
        evs = ev_by_round.get(key)
        if evs is None:
            evs = events.iloc[0:0]
        evs = evs.sort_values("seconds")

        alive_ct, alive_t = 5, 5
        planted, plant_at = 0, None

        map_id = MAP_IDS.get(r.map_name, 0)
        tier_id = TIER_IDS.get(getattr(r, "tier", DEFAULT_TIER), TIER_IDS[DEFAULT_TIER])
        rt_ct = ROUND_TYPE_IDS[classify_round(r.equip_ct, r.round_num)]

        def row(seconds, event_idx, etype, victim_side=None):
            if planted:
                time_left = max(0.0, PLANT_SECONDS - (seconds - plant_at))
                since = seconds - plant_at
            else:
                time_left = max(0.0, ROUND_SECONDS - seconds)
                since = 0.0
            return {
                "match_id": r.match_id,
                "round_num": r.round_num,
                "seconds": seconds,
                "event_idx": event_idx,
                "event_type": etype,
                # WHO died, carried through explicitly. Downstream used to infer
                # this from the sign of the win-probability delta, which is a
                # guess about the model rather than a fact about the round.
                "victim_side": victim_side,
                "alive_ct": alive_ct,
                "alive_t": alive_t,
                "equip_ct": r.equip_ct,
                "equip_t": r.equip_t,
                "time_left": time_left,
                "bomb_planted": planted,
                "time_since_plant": since,
                "map_id": map_id,
                "tier_id": tier_id,
                "round_type_id": rt_ct,
                "ct_won": int(r.ct_won),
            }

        # state at round start, before anything happens
        out.append(row(0.0, 0, "start"))

        for i, e in enumerate(evs.itertuples(index=False), start=1):
            victim = None
            if e.type == "plant":
                planted, plant_at = 1, e.seconds
            elif e.type == "death":
                victim = e.victim_side
                if victim == "ct":
                    alive_ct -= 1
                else:
                    alive_t -= 1
            out.append(row(e.seconds, i, e.type, victim))

    return pd.DataFrame(out)
