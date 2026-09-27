"""ADR credits what the victim lost, not the raw hit.

CS2's `player_hurt` reports `dmg_health` uncapped: an AWP body shot on a
player with 30 left reads about 110. Summed as it came, one player-round in
the local corpus read 1,417 damage and ADR ran about a third high.
"""
from __future__ import annotations

import pandas as pd

from counterplay.parse import _hurt_credits

A, B, C = "76561190000000001", "76561190000000002", "76561190000000003"
SIDES = {(1, A): "ct", (1, B): "t", (1, C): "t"}


def _credits(hits):
    """hits: (tick, attacker, victim, dmg_health, health_after, weapon)."""
    df = pd.DataFrame(hits, columns=["tick", "attacker_steamid", "user_steamid",
                                     "dmg_health", "health", "weapon"])
    return list(_hurt_credits(df, lambda t: 1, set(), SIDES))


def test_a_huge_hit_on_a_full_player_credits_100():
    assert [c[2] for c in _credits([(10, A, B, 448, 0, "awp")])] == [100.0]


def test_a_huge_hit_on_a_30hp_player_credits_30():
    got = _credits([(10, A, B, 70, 30, "ak47"), (20, A, B, 448, 0, "awp")])
    assert [c[2] for c in got] == [70.0, 30.0]


def test_team_and_self_damage_still_lower_health_but_earn_nothing():
    got = _credits([(10, C, B, 60, 40, "ak47"),        # teammate: no credit
                    (15, B, B, 10, 30, "molotov"),     # self: no credit
                    (20, A, B, 448, 0, "awp")])
    assert [(c[1], c[2]) for c in got] == [(A, 30.0)]


def test_hits_are_walked_in_tick_order():
    got = _credits([(20, A, B, 448, 0, "awp"), (10, A, B, 70, 30, "ak47")])
    assert sorted(c[2] for c in got) == [30.0, 70.0]


def test_a_demo_without_health_falls_back_to_subtracting():
    got = _credits([(10, A, B, 70, None, "ak47"), (20, A, B, 448, None, "awp")])
    assert [c[2] for c in got] == [70.0, 30.0]
