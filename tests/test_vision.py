"""What a team could know (counterplay/vision.py) and the detectors that
use it (counterplay/decisions.detect), on a synthetic round.

Two CTs, two Ts. T 3 is seen by CT 1 from sample 4 to 6, then disappears;
T 4 is never seen. CT 1 looks due east (yaw 0) at a T standing due east,
so his crosshair is on him; CT 2 looks north at the same T, 90 degrees off.
"""
import numpy as np
import pandas as pd
import pytest

from counterplay import decisions as D
from counterplay import positions as P
from counterplay import vision as V

CT, T = 3, 2
N = 12


def _blob(version=2):
    ticks = [1000 + i * 8 for i in range(N)]
    players = {1: (CT, 0, 0, 0.0), 2: (CT, 0, 500, 90.0),
               3: (T, 1000, 0, 180.0), 4: (T, 3000, 3000, 180.0)}
    rows = []
    for i, tick in enumerate(ticks):
        for sid, (team, x, y, yaw) in players.items():
            row = {"tick": tick, "steamid": sid, "X": x, "Y": y, "Z": 0,
                   "yaw": yaw, "health": 100, "is_alive": True,
                   "team_num": team, "which_bomb_zone": 0}
            if version == 2:
                seen = [1] if (sid == 3 and 4 <= i <= 6) else []
                row.update(pitch=0.0, spotted=bool(seen),
                           approximate_spotted_by=seen)
            rows.append(row)
    return P.pack_round(ticks, list(players), pd.DataFrame(rows))


def test_version_two_round_trips_and_version_one_still_reads():
    meta, sids, s = P.unpack_round(_blob(2))
    assert meta["version"] == 2 and meta["vision"]
    assert s["seen_by"][5, 2] == 1                 # T 3 seen by roster index 0
    assert s["flags"][5, 2] & P.FLAG_SPOTTED
    meta1, _sids, s1 = P.unpack_round(_blob(1))
    assert meta1["version"] == 1 and not meta1["vision"]
    assert "pitch" not in s1.dtype.names and s1["x"][0, 2] == 1000


def test_a_team_knows_an_enemy_as_visible_last_seen_or_unknown():
    rnd = V.Round(_blob(2))
    cts = rnd.team("ct")
    t3, t4 = rnd.index["3"], rnd.index["4"]
    assert rnd.sighting(t3, cts, 2).state == "unknown"
    assert rnd.sighting(t3, cts, 5).state == "visible"
    later = rnd.sighting(t3, cts, 10)
    assert later.state == "last_seen" and later.seconds_ago == pytest.approx(4 / 8)
    assert (later.x, later.y) == (1000, 0)
    assert rnd.sighting(t4, cts, 10).state == "unknown"


def test_no_vision_means_no_answer_not_a_guess():
    rnd = V.Round(_blob(1))
    assert rnd.sighting(rnd.index["3"], rnd.team("ct"), 5) is None


def test_crosshair_angle_to_the_enemy():
    rnd = V.Round(_blob(2))
    on = V.view_angle_to(rnd, rnd.index["1"], rnd.index["3"], 5)
    off = V.view_angle_to(rnd, rnd.index["2"], rnd.index["3"], 5)
    assert on == pytest.approx(0, abs=1.5)         # yaw is a byte: 1.4 deg steps
    # CT 2 at (0, 500) looks north; T 3 is south-east of him.
    assert off == pytest.approx(90 + np.degrees(np.arctan2(500, 1000)), abs=2)


# A death where nothing went wrong: a teammate close, the killer in front
# and aimed at, utility used, no plant. Each case changes one fact.
BASE = {"vision": True, "seconds": 30.0, "side": "t", "nearest_mate": 300.0,
        "mates_near": 2, "alive_us": 4, "alive_them": 4,
        "thrusmoke": 0, "penetrated": 0, "distance": 10.0, "in_zone": 0,
        "plant_t": None, "plant_site": None,
        "angle_to_killer": 5.0, "killer_angle": 5.0,
        "known_enemies_near": 1, "killer_known": "visible",
        "victim_saw_killer": True, "mates_saw_killer_ago": None,
        "repeek": False, "blinded": False, "nades_bought": 2, "has_rifle": True,
        "nades_thrown": 1, "entry": False, "exec_site": None, "retake_site": None,
        "std_util_thrown": None, "retake_spread": None, "stacked": None}


@pytest.mark.parametrize("change,codes", [
    ({"nearest_mate": 1500.0}, ["no_trade"]),
    ({"nearest_mate": None}, ["no_trade"]),
    ({"entry": True, "nearest_mate": 1500.0}, ["no_trade", "entry_alone"]),
    ({"repeek": True}, ["repeek"]),
    ({"angle_to_killer": 150.0}, ["from_behind"]),
    ({"angle_to_killer": 80.0}, ["from_side"]),
    ({"thrusmoke": 1, "angle_to_killer": 150.0}, ["through_smoke"]),
    ({"penetrated": 1}, ["wallbang"]),
    ({"mates_saw_killer_ago": 3.0, "victim_saw_killer": False}, ["known_angle"]),
    ({"side": "ct", "known_enemies_near": 3}, ["outnumbered"]),
    ({"side": "t", "known_enemies_near": 3}, []),
    ({"angle_to_killer": 40.0}, ["crosshair"]),
    ({"nades_thrown": 0}, ["utility_unused"]),
    ({"blinded": True}, ["fought_blind"]),
    ({"exec_site": 2, "std_util_thrown": 0}, ["no_site_utility"]),
    ({"retake_site": 1, "std_util_thrown": 0}, ["no_site_utility_retake"]),
    ({"retake_spread": 6.0}, ["staggered_retake"]),
    ({"stacked": True}, ["stacked"]),
    ({"alive_us": 1, "alive_them": 4}, ["missed_save"]),
    ({"alive_us": 1, "alive_them": 4, "has_rifle": False}, []),
])
def test_each_detector_fires_on_its_own_fact_and_only_then(change, codes):
    assert D.detect(BASE) == []
    assert D.detect({**BASE, **change}) == codes


def test_a_teammate_seeing_him_in_the_same_instant_is_not_a_head_start():
    f = {**BASE, "mates_saw_killer_ago": 0.0, "victim_saw_killer": False}
    assert "known_angle" not in D.detect(f)


def test_every_detector_has_both_sentences_and_a_known_proof():
    for code, d in D.DETECTORS.items():
        assert d["once"] and d["habit"], code
        assert d["proof"] in ("trade", "duel", "round", "death", "economy"), code
        assert chr(8212) not in d["once"] + d["habit"], code
