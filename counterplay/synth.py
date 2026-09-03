"""Synthetic round generator.

Exists so you can validate the model and ranking pipeline before you have a
single demo parsed. Rounds are simulated from a hidden strength function, so
the win-probability model has real structure to learn and calibration means
something. Delete this module once real demos are flowing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import MAPS, PLANT_SECONDS, ROUND_SECONDS


def _duel_ct_wins(alive_ct, alive_t, equip_ct, equip_t, rng):
    """Hidden truth: who wins the next duel. Man count dominates, gear matters."""
    strength_ct = alive_ct * 1.0 + (equip_ct / 25000.0) * 1.2
    strength_t = alive_t * 1.0 + (equip_t / 25000.0) * 1.2
    p = strength_ct / (strength_ct + strength_t)
    return rng.random() < p


def generate(n_matches=60, rounds_per_match=24, seed=7, tier="premier"):
    """Return (rounds, events) frames shaped exactly like the real parser's output."""
    rng = np.random.default_rng(seed)
    rounds, events = [], []

    for m in range(n_matches):
        match_id = f"synth_{m:04d}"
        map_name = MAPS[rng.integers(0, len(MAPS))]

        for rn in range(1, rounds_per_match + 1):
            if rn in (1, 13):
                equip_ct = equip_t = float(rng.integers(3800, 4600))
            else:
                equip_ct = float(rng.integers(1500, 28000))
                equip_t = float(rng.integers(1500, 28000))

            alive_ct, alive_t = 5, 5
            t = float(rng.uniform(8, 20))
            planted, plant_at = False, None
            evs = []

            # T side plants between 35-75s, but only if they have won enough
            # map control to get there. Gating on a man advantage plus a coin
            # flip lands the plant rate near 45%, which is roughly real.
            plant_target = float(rng.uniform(35, 75))
            plant_intent = rng.random() < 0.62

            while alive_ct > 0 and alive_t > 0:
                if (not planted and t >= plant_target and plant_intent
                        and alive_t >= alive_ct and alive_t >= 1):
                    planted, plant_at = True, t
                    evs.append({"seconds": t, "type": "plant", "victim_side": None})
                    t += float(rng.uniform(3, 9))
                    continue

                deadline = (plant_at + PLANT_SECONDS) if planted else ROUND_SECONDS
                if t >= deadline:
                    break

                if _duel_ct_wins(alive_ct, alive_t, equip_ct, equip_t, rng):
                    alive_t -= 1
                    evs.append({"seconds": t, "type": "death", "victim_side": "t"})
                else:
                    alive_ct -= 1
                    evs.append({"seconds": t, "type": "death", "victim_side": "ct"})
                t += float(rng.uniform(4, 14))

            # resolve the round
            if alive_t == 0 and not planted:
                ct_won = True
            elif alive_ct == 0:
                ct_won = False
            elif planted:
                ct_won = alive_ct > 0 and alive_t == 0   # retake cleared before timer
            else:
                ct_won = True                            # time expired, no plant

            rounds.append({
                "match_id": match_id, "round_num": rn, "map_name": map_name,
                "equip_ct": equip_ct, "equip_t": equip_t, "ct_won": bool(ct_won),
                "tier": tier,
            })
            for e in evs:
                events.append({"match_id": match_id, "round_num": rn, **e})

    return pd.DataFrame(rounds), pd.DataFrame(events)
