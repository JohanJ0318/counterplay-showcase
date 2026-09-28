"""The collegiate reference every recurring pattern is read against.

Built by tools/league_rates.py into counterplay/league_rates.json; read by
app/league.py, which weights every figure by the team's own mix.
"""
from app import league


def test_the_reference_file_is_collegiate_and_complete():
    r = league.ref()
    assert "collegiate" in r["_how"]
    assert r["matches"] >= 100
    for side in ("ct", "t"):
        o = r["opening"][side]
        assert 20 < 100 * o["saved"] / o["lost"] < 45
        assert 55 < 100 * o["converted"] / o["took"] < 80


def test_a_side_is_weighted_by_the_team_s_own_maps():
    """A team that played its CT rounds on one map is held to that map."""
    on_one = league.side("ct", {"de_anubis": {"you_ct": 20, "you_t": 0}})
    assert abs(on_one[0] - league.side_on_map("ct", "de_anubis")[0]) < 1e-9
    mixed = league.side("ct", {"de_anubis": {"you_ct": 10, "you_t": 0},
                               "de_cache": {"you_ct": 10, "you_t": 0}})
    a = league.side_on_map("ct", "de_anubis")[0]
    c = league.side_on_map("ct", "de_cache")[0]
    assert abs(mixed[0] - (a + c) / 2) < 1e-9


def test_judge_needs_a_wide_gap_and_enough_rounds():
    ref = (30.0, 300, 1000)
    assert league.judge(6, 29, ref) == 0      # 21% vs 30%: NC State Red, noise
    assert league.judge(2, 40, ref) == -1     # 5% vs 30% over 40: real
    assert league.judge(1, 2, ref) == 0       # a gap on two rounds is nothing
    assert league.judge(28, 100, ref) == 0    # real enough, too small to act on
    assert league.judge(20, 40, ref) == 1     # clearly above
    assert league.judge(5, 10, None) == 0     # no reference, no verdict


def test_the_bar_shows_the_college_average():
    from app import charts
    html = charts.bars([("You win the round after losing the opening duel", 6, 29)],
                       refs=[30.0], verdicts=[0])
    assert "college avg 30%" in html and 'class="hb-ref"' in html
    assert 'class="hb-val"' in html            # no colour without a verdict
    assert 'hb-val down' in charts.bars([("x", 2, 40)], refs=[30.0], verdicts=[-1])
