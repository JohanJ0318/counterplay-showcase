"""Where the bomb went: deriving it, and not leaking it.

The leak test is the important one. plant_site is a round-level fact, and the
rounds frame carries it for every row of the round including the ones before
the plant. If those rows get the site, the model is being handed the future
and will score beautifully in testing while being useless live.
"""
import numpy as np
import pandas as pd

from counterplay import positions, state
from counterplay.schema import (FEATURES, MAP_IDS, MAPS, UNKNOWN_MAP_ID,
                                CATEGORICAL)

TEAM_T = 2


def blob(players, n_samples=40):
    """Pack a round where every player holds one zone for the whole round.

    `players` is a list of (team_num, is_alive, which_bomb_zone).
    """
    ticks = [1000 + i * positions.SAMPLE_STEP for i in range(n_samples)]
    steamids = [7656119000000000 + i for i in range(len(players))]
    rows = []
    for t in ticks:
        for sid, (team, alive, zone) in zip(steamids, players):
            rows.append({"tick": t, "steamid": sid, "X": 100.0, "Y": 200.0,
                         "Z": 0.0, "yaw": 0.0, "health": 100 if alive else 0,
                         "is_alive": alive, "team_num": team,
                         "which_bomb_zone": zone})
    return positions.pack_round(ticks, steamids, pd.DataFrame(rows))


def test_site_is_the_modal_zone_of_living_ts():
    # Two Ts on site 2, one lurking on site 1. Site 2 wins on the count.
    b = blob([(TEAM_T, True, 2), (TEAM_T, True, 2), (TEAM_T, True, 1)])
    assert positions.site_at(b, 2.5) == 2


def test_dead_players_do_not_vote():
    # Without the alive filter this is 2 votes each and ties back to site 1.
    b = blob([(TEAM_T, True, 2), (TEAM_T, True, 2),
              (TEAM_T, True, 1), (TEAM_T, False, 1)])
    assert positions.site_at(b, 2.5) == 2


def test_cts_do_not_vote():
    # A CT stacking the other site must not decide where the T side planted.
    b = blob([(TEAM_T, True, 2), (TEAM_T, True, 2),
              (TEAM_T, True, 1), (positions.TEAM_CT, True, 1)])
    assert positions.site_at(b, 2.5) == 2


def test_players_outside_any_site_do_not_vote():
    b = blob([(TEAM_T, True, 1), (TEAM_T, True, 0), (TEAM_T, True, 0)])
    assert positions.site_at(b, 2.5) == 1


def test_unknown_when_no_t_is_in_a_site():
    # A real case, not a failure: the caller must read 0 as "do not know".
    b = blob([(TEAM_T, True, 0), (positions.TEAM_CT, True, 1)])
    assert positions.site_at(b, 2.5) == 0


def test_unknown_on_a_missing_blob():
    assert positions.site_at(b"", 2.5) == 0
    assert positions.site_at(None, 2.5) == 0


# --------------------------------------------------------------- the leak


def _round(plant_site):
    return pd.DataFrame([{
        "match_id": "m1", "round_num": 5, "map_name": "de_mirage",
        "equip_ct": 25000.0, "equip_t": 24000.0, "ct_won": False,
        "tier": "league", "plant_site": plant_site,
    }])


def _events():
    return pd.DataFrame([
        {"match_id": "m1", "round_num": 5, "seconds": 10.0,
         "type": "death", "victim_side": "t"},
        {"match_id": "m1", "round_num": 5, "seconds": 30.0,
         "type": "plant", "victim_side": None},
        {"match_id": "m1", "round_num": 5, "seconds": 40.0,
         "type": "death", "victim_side": "ct"},
    ])


def test_plant_site_is_zero_before_the_plant():
    df = state.build_states(_round(2), _events())
    before = df[df["seconds"] < 30.0]
    assert len(before) == 2                      # round start and the 10s death
    assert set(before["plant_site"]) == {0}, \
        "the site is known to the ROUND from the start; the model must not see it"


def test_plant_site_is_set_from_the_plant_onward():
    df = state.build_states(_round(2), _events())
    after = df[df["seconds"] >= 30.0]
    assert len(after) == 2                       # the plant and the 40s death
    assert set(after["plant_site"]) == {2}


def test_an_unplanted_round_is_all_zero():
    evs = _events()
    df = state.build_states(_round(0), evs[evs["type"] == "death"])
    assert set(df["plant_site"]) == {0}


def test_site_zero_stays_zero_even_after_a_plant():
    # Unknown site, planted round. Must not invent a 1.
    df = state.build_states(_round(0), _events())
    assert set(df["plant_site"]) == {0}


# --------------------------------------------------------------- map ids


def test_de_cache_has_its_own_id():
    # It used to be absent, and MAP_IDS.get(name, 0) IS de_mirage, so 133
    # collegiate rounds trained as Mirage.
    assert "de_cache" in MAP_IDS
    assert MAP_IDS["de_cache"] != MAP_IDS["de_mirage"]


def test_an_unknown_map_does_not_become_mirage():
    rounds = _round(0)
    rounds.loc[0, "map_name"] = "de_somethingnobodyhasheardof"
    df = state.build_states(rounds, _events())
    assert set(df["map_id"]) == {UNKNOWN_MAP_ID}
    assert UNKNOWN_MAP_ID != MAP_IDS["de_mirage"]


def test_map_ids_are_append_only():
    # Inserting renumbers every map after the insert and silently relabels
    # rounds already in the database.
    assert MAPS[0] == "de_mirage" and MAP_IDS["de_mirage"] == 0
    assert MAP_IDS[MAPS[-1]] == len(MAPS) - 1
    assert UNKNOWN_MAP_ID == len(MAPS)


def test_plant_site_is_in_the_feature_contract():
    assert "plant_site" in FEATURES
    assert "plant_site" in CATEGORICAL
    # Every categorical has to be locatable by index, which is how the booster
    # is told which columns they are.
    for c in CATEGORICAL:
        assert FEATURES.index(c) >= 0


def test_build_states_emits_every_declared_feature():
    df = state.build_states(_round(1), _events())
    for f in FEATURES:
        assert f in df.columns, f"{f} is in FEATURES but build_states never emits it"
    assert not df[list(FEATURES)].isna().any().any()
    assert np.issubdtype(df["plant_site"].dtype, np.integer)
