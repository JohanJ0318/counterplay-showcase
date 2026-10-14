"""The position summaries the scorer's model reads (counterplay/posfeat.py).

One synthetic round with answers worked out by hand: two CTs (one on 60
health, one in bombsite 1), two Ts, and a coach on the CT side who is on
the server and never alive. A T dies at 2.0 s; the other T dies at 2.05 s,
inside the same eighth of a second, so the 8 Hz sample read for the first
death already shows the second one dead. That is the trade that made the
first version of these snapshots disagree with the event counts.

Guarded: alive comes from the death events and not the sample; a player
the sample shows dead early keeps their last living health; the coach is
not counted; and the model config that reads these refuses nothing when the
columns are missing, it computes them.
"""
import importlib
import os
import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

CT, T = 3, 2
# steamid: (team, x, y, health, bombsite zone, dies at sample index)
PLAYERS = {
    1: (CT, 0, 0, 100, 1, None),
    2: (CT, 1000, 0, 60, 0, None),
    3: (T, 0, 500, 100, 0, 17),      # event at 2.0 s; sample 17 is 2.125 s
    4: (T, 3000, 0, 100, 0, 16),     # event at 2.05 s, but sample 16 (2.0 s)
                                     # already shows them dead
    5: (CT, 9000, 9000, 100, 0, 0),  # the coach: never alive
}
N_SAMPLES, STEP, START = 40, 8, 1000


@pytest.fixture
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    from counterplay import positions as P
    from counterplay import posfeat
    importlib.reload(posfeat)

    ticks = [START + i * STEP for i in range(N_SAMPLES)]
    rows = []
    for i, tick in enumerate(ticks):
        for sid, (team, x, y, hp, zone, dies) in PLAYERS.items():
            dead = dies is not None and i >= dies
            rows.append({"tick": tick, "steamid": sid, "X": x, "Y": y, "Z": 0,
                         "yaw": 0.0, "health": 0 if dead else hp,
                         "is_alive": not dead, "team_num": team,
                         "which_bomb_zone": zone})
    blob = P.pack_round(ticks, list(PLAYERS), pd.DataFrame(rows))
    db_mod.execute("""INSERT INTO round_positions (match_key, round_num, tick_start,
                          tick_step, n_samples, n_players, data)
                      VALUES (?,?,?,?,?,?,?)""",
                   "m1", 1, START, STEP, N_SAMPLES, len(PLAYERS), blob)
    for secs, victim in ((2.0, 3), (2.05, 4)):
        db_mod.execute("""INSERT INTO events (match_key, round_num, seconds, type,
                              victim_side, victim_steamid)
                          VALUES (?,?,?,?,?,?)""", "m1", 1, secs, "death", "t",
                       str(victim))
    states = pd.DataFrame({"match_id": ["m1"] * 3, "round_num": [1] * 3,
                           "seconds": [0.0, 2.0, 2.05]})
    yield posfeat, states
    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def feats(posfeat, states):
    out = posfeat.attach(states)
    return [dict(zip(posfeat.POSFEAT, r)) for r in out[posfeat.POSFEAT].to_numpy()]


def test_the_round_start_reads_everyone_but_the_coach(env):
    posfeat, states = env
    start = feats(posfeat, states)[0]
    assert start["hp_ct"] == pytest.approx(1.6)      # 100 + 60, coach not counted
    assert start["hp_t"] == pytest.approx(2.0)
    assert start["ct_site1"] == 1 and start["t_site1"] == 0
    assert start["closest_enemy"] == pytest.approx(0.5)   # CT 1 to T 3, 500 units


def test_alive_comes_from_the_events_not_the_sample(env):
    posfeat, states = env
    first, second = feats(posfeat, states)[1:]
    # At 2.0 s only T 3 is dead. T 4's sample already reads dead (killed at
    # 2.05 s): the events say alive, and they keep their 100 health.
    assert first["hp_t"] == pytest.approx(1.0)
    assert first["closest_enemy"] == pytest.approx(2.0)   # CT 2 to T 4
    assert second["hp_t"] == 0 and second["closest_enemy"] == 0


def test_a_round_with_no_positions_reads_zeros(env):
    posfeat, states = env
    other = pd.DataFrame({"match_id": ["nope"], "round_num": [1], "seconds": [0.0]})
    _p, f, has = posfeat.snapshots(other)
    assert not has.any() and not f.any()


def test_the_scorer_config_reads_positions_and_esea_only_trains():
    from counterplay import model as M
    from counterplay.schema import FEATURES, POSFEAT
    features, _params, tiers = M.CONFIGS[M.DEFAULT_CONFIG]
    assert features == FEATURES + POSFEAT and tiers == ("esea",)
    assert M.CONFIGS["shipped"][0] == FEATURES and M.CONFIGS["shipped"][2] == ()


def test_a_loadout_reads_as_one_weapon_class_and_a_grenade_count():
    from counterplay.posfeat import kit_of
    # rifle, awp, smg, pistol only, grenades / 4
    assert kit_of("AWP, Desert Eagle, Flashbang, Smoke Grenade") == (0, 1, 0, 0, 0.5)
    assert kit_of("AK-47, AWP") == (0, 1, 0, 0, 0)        # the AWP decides
    assert kit_of("M4A1-S, Molotov") == (1, 0, 0, 0, 0.25)
    assert kit_of("MP9, Flashbang") == (0, 0, 1, 0, 0.25)
    assert kit_of("Glock-18") == (0, 0, 0, 1, 0)
    assert kit_of(None) == (0, 0, 0, 1, 0)                # nothing recorded
    assert kit_of("Flashbang, Flashbang, Smoke Grenade, Molotov, "
                  "High Explosive Grenade")[4] == 1.0     # capped at four
