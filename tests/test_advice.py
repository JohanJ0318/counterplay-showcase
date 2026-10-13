"""Tests for the recommendation engine.

`advice.py` is the only code in this product that tells a coach to change what
they do. Everything else reports; this concludes. That makes it the code most
able to be confidently wrong, and it had no tests at all.

What is worth guarding is not the wording but the discipline behind it:

  * nothing is recommended off a handful of rounds
  * nothing is recommended that is close to the team's own average
  * a positive finding is labeled positive and a negative one negative
  * ranking follows rounds at stake, not the size of the percentage
  * one place produces one recommendation, not three
  * every item carries the evidence it was drawn from

Written against a fake team, so the assertions are about the rules rather than
about whatever happens to be true of one real season.
"""
from __future__ import annotations

import pytest

from app import advice


# The rate the rest of a map and side wins at when a test says nothing about
# it, which is the same as the fake team's overall rate. A finding is judged
# against the rounds where it did not happen, so leaving this at the baseline
# is what makes "close to normal" mean the same thing it used to.
BASELINE = 0.49


def _pattern(kind, zone, mp, side, hit, of, won, other=None, other_won=None,
             zone_index=None):
    """One row shaped the way `movement.positional_patterns` returns them.

    `other` is the rest of that map and that side: the rounds where this did
    not happen. It is what a positional finding is measured against now,
    rather than the season average, because on a real season only one map and
    side in nine differs from the rest by more than chance and a Nuke CT row
    read against a season figure is largely saying "Nuke CT".

    Both default to the complement at the team's own rate, so a test that
    cares about a threshold and not about the comparison gets a comparison
    that says "normal".
    """
    other = (of - hit) if other is None else other
    other_won = round(other * BASELINE) if other_won is None else other_won
    win_pct = 100.0 * won / hit if hit else 0.0
    other_pct = 100.0 * other_won / other if other else 0.0
    return {"kind": kind, "zone": zone, "map": mp, "side": side,
            # Distinct clusters get distinct indices unless a test deliberately
            # reuses one, which is how "two zones share a name" is expressed.
            "zone_index": zone_index if zone_index is not None else id(zone) % 9973,
            "hit": hit, "of": of, "won": won,
            "other": other, "other_won": other_won, "other_pct": other_pct,
            "gap": win_pct - other_pct,
            "side_rounds": of, "answered": of,
            "pct": 100.0 * hit / of, "win_pct": win_pct,
            "detail": "", "extra": ""}


def _stats(baseline_won=49, baseline_rounds=100, **over):
    """A team whose overall round win rate is `baseline_won` percent."""
    base = {
        "you": {"rounds": baseline_rounds, "won": baseline_won,
                "opening_took": 0, "opening_converted": 0,
                "opening_lost": 0, "opening_saved": 0},
        "you_buys": {},
        "maps": {},
        "anchors": {"confident": True},
    }
    base.update(over)
    return base


@pytest.fixture
def engine(monkeypatch):
    """Drives `monday()` with data we control instead of the database.

    ALL FIVE of the readings it makes, not the two that were obvious. It also
    asks the utility module about flashes, unused grenades and the rounds a
    habit turned up in, and those three went to the database: on this laptop
    that quietly worked, because there is a database sitting there with a
    season in it, and the tests were reading a real team while claiming to
    read a fake one. On a runner with no database at all it fails outright,
    which is how it was noticed.

    Utility returns nothing here. These tests are about the ranking and the
    thresholds, and a utility finding is counted in flashes and dollars rather
    than rounds, so leaving it empty keeps the assertions about the rules the
    tests were written for.
    """
    def run(patterns, stats=None):
        monkeypatch.setattr(advice, "team_stats",
                            lambda _tid: stats or _stats())
        monkeypatch.setattr(advice.movement, "positional_patterns",
                            lambda _tid: patterns)
        from app import utility
        monkeypatch.setattr(utility, "round_splits", lambda _tid: {})
        monkeypatch.setattr(utility, "flashes", lambda _tid: None)
        monkeypatch.setattr(utility, "unused", lambda _tid: None)
        return advice.monday(1)
    return run


# ----------------------------------------------------------------- thresholds

def test_nothing_is_recommended_off_too_few_rounds(engine):
    """Seven rounds is an anecdote however extreme it looks.

    A 0-of-7 record is a 49-point gap, which would top the ranking if only the
    gap mattered. It produces nothing.
    """
    out = engine([_pattern("death", "top mid", "de_mirage", "t",
                           hit=7, of=30, won=0)])
    assert out["items"] == []


def test_a_finding_at_the_threshold_is_recommended(engine):
    out = engine([_pattern("death", "top mid", "de_mirage", "t",
                           hit=8, of=30, won=0)])
    assert len(out["items"]) == 1
    assert "top mid" in out["items"][0]["do"]


def test_nothing_is_recommended_close_to_the_teams_own_average(engine):
    """44% against a 49% baseline is not a finding, it is a season."""
    out = engine([_pattern("death", "top mid", "de_mirage", "t",
                           hit=25, of=40, won=11)])   # 44%
    assert out["items"] == []


def test_a_place_is_judged_against_the_same_map_and_side(engine):
    """Not against the season, which is mostly the map pool.

    The same 30% conversion is a problem or it is normal depending entirely on
    what the REST of that map and that side does. Against a complement winning
    half its rounds it is twenty points down and worth a Monday; against a
    complement winning 35% it is five points down and worth nothing.

    This used to compare with the team's season average, which on a real
    season is largely a statement about the map pool: of nine map-and-sides
    only one differed from the rest by more than chance, so a Nuke CT row read
    against a season figure was in large part saying "Nuke CT".
    """
    bad = _pattern("death", "top mid", "de_mirage", "t", hit=20, of=40, won=6,
                   other=20, other_won=10)        # 30% against 50%
    normal = _pattern("death", "top mid", "de_mirage", "t", hit=20, of=40,
                      won=6, other=20, other_won=7)   # 30% against 35%
    assert engine([bad])["items"], "twenty points below the rest should surface"
    assert not engine([normal])["items"], "five points below should not"


def _lost_openings(stats, lost, saved):
    """Openings lost and rounds saved, all on T side, as team_stats() splits them."""
    stats["you"].update(opening_lost=lost, opening_saved=saved, opening_side={
        "t": {"took": 0, "converted": 0, "lost": lost, "saved": saved},
        "ct": {"took": 0, "converted": 0, "lost": 0, "saved": 0}})
    return stats


def test_season_findings_are_read_against_collegiate_teams(engine):
    """NC State Red's captain, 2026-09-27: 21% after losing the opening duel
    against the team's own 45% says nothing; against the collegiate 30% it
    says whether there is a problem. So the team's own win rate no longer
    decides: the same record is judged the same for a strong and a weak team.
    """
    from app import league
    ref = league.opening("lost", {"t": {"lost": 40}})[0]
    assert 25 < ref < 40, ref          # collegiate T side, about 31%

    for won in (49, 30):
        close = engine([], _lost_openings(_stats(baseline_won=won), 40, 10))
        assert not any("after losing the opening duel" in i["evidence"][0] for i in close["items"]), \
            "25% against about 31% is inside the noise, strong team or weak"
        far = engine([], _lost_openings(_stats(baseline_won=won), 40, 3))
        assert any("after losing the opening duel" in i["evidence"][0] for i in far["items"]), \
            "8% against about 31% over 40 rounds is a finding either way"


def test_the_card_draws_collegiate_teams_as_its_second_bar(engine):
    out = engine([], _lost_openings(_stats(), 40, 3))
    card = next(i for i in out["items"] if "after losing the opening duel" in i["evidence"][0])
    assert card["vs"][1][0] == "Collegiate teams"


def test_a_weak_side_of_a_map_is_found(engine):
    """This rule read m.get("ct"), a key the map rows never had, so it had
    never fired for anyone. The rows carry you_ct / you_ct_won."""
    stats = _stats(maps={"de_nuke": {"you_ct": 30, "you_ct_won": 5,
                                     "you_t": 0, "you_t_won": 0}})
    out = engine([], stats)
    assert any("CT side on nuke" in i["do"] for i in out["items"])


# ----------------------------------------------------------------- direction

def test_a_strong_setup_is_labeled_keep_not_fix(engine):
    out = engine([_pattern("setup", "Ramp", "de_nuke", "ct",
                           hit=13, of=21, won=10)])   # 77% vs 49%
    assert len(out["items"]) == 1
    assert out["items"][0]["good"] is True
    assert "Keep" in out["items"][0]["do"]


def test_a_weak_setup_is_labeled_fix(engine):
    out = engine([_pattern("setup", "lobby", "de_nuke", "t",
                           hit=10, of=24, won=3)])    # 30% vs 49%
    assert out["items"][0]["good"] is False
    assert "Rethink" in out["items"][0]["do"]


def test_positive_findings_need_a_wider_gap_than_negative_ones(engine):
    """GOOD_GAP is deliberately above MIN_GAP.

    Telling a team something is working is a stronger claim than telling them
    something is not, so it takes more evidence.
    """
    assert advice.GOOD_GAP > advice.MIN_GAP
    marginal = engine([_pattern("setup", "Ramp", "de_nuke", "ct",
                                hit=20, of=30, won=13)])   # 65%, +16
    assert marginal["items"] and marginal["items"][0]["good"]


# ----------------------------------------------------------------- ranking

def test_ranking_follows_rounds_at_stake_not_the_percentage(engine):
    """A small gap over many rounds outranks a big gap over few.

    This is the whole reason `stake` exists. A 20-point gap across 60 rounds is
    twelve rounds of season; a 40-point gap across 9 is under four.
    """
    out = engine([
        _pattern("death", "narrow", "de_mirage", "t", hit=9, of=30, won=1),
        _pattern("death", "broad", "de_dust2", "t", hit=60, of=90, won=17),
    ])
    assert [i["zone"] for i in out["items"]][0] == "broad"


def test_no_more_than_max_items(engine):
    many = [_pattern("death", f"zone{i}", f"de_map{i}", "t",
                     hit=20, of=40, won=2) for i in range(20)]
    assert len(engine(many)["items"]) <= advice.MAX_ITEMS


# ----------------------------------------------------------------- one place

def test_two_findings_about_one_place_become_one_recommendation(engine):
    """The group stalls at A main, and the first death is at A main.

    Reported separately those filled three of eight slots with one map's T
    side and pushed four other maps off the page. They are one problem.
    """
    out = engine([
        _pattern("commit", "A main", "de_mirage", "t", hit=14, of=34, won=4),
        _pattern("death", "A main", "de_mirage", "t", hit=10, of=34, won=3),
    ])
    assert len(out["items"]) == 1, "same map, side and place is one item"
    assert len(out["items"][0]["evidence"]) == 2, "and it keeps both counts"


def test_the_same_place_on_different_sides_stays_separate(engine):
    """A main as T and A main as CT are different problems."""
    out = engine([
        _pattern("death", "A main", "de_mirage", "t", hit=12, of=30, won=2),
        _pattern("death", "A main", "de_mirage", "ct", hit=12, of=30, won=2),
    ])
    assert len(out["items"]) == 2


def test_a_good_and_a_bad_finding_about_one_place_do_not_cancel(engine):
    """The setup works and the entry into it does not — both are true."""
    out = engine([
        _pattern("setup", "Banana", "de_inferno", "ct", hit=15, of=25, won=12),
        _pattern("death", "Banana", "de_inferno", "ct", hit=12, of=25, won=2),
    ])
    assert len(out["items"]) == 2
    assert {i["good"] for i in out["items"]} == {True, False}


# ----------------------------------------------------------------- evidence

def test_every_item_carries_its_evidence_and_its_numbers(engine):
    out = engine([_pattern("death", "top mid", "de_mirage", "t",
                           hit=20, of=40, won=3)])
    it = out["items"][0]
    assert it["evidence"] and all(e.strip() for e in it["evidence"])
    assert it["of"] > 0 and 0 <= it["rate"] <= 100
    assert "20" in it["evidence"][0] and "40" in it["evidence"][0]


def test_keep_items_do_not_share_a_sentence(engine):
    """Identical copy under different numbers reads as generated.

    Three positive findings once produced three word-for-word identical
    paragraphs on one page.
    """
    out = engine([
        _pattern("setup", "Ramp", "de_nuke", "ct", hit=13, of=21, won=10),
        _pattern("setup", "A default", "de_mirage", "ct", hit=9, of=37, won=8),
        _pattern("setup", "Cat", "de_dust2", "t", hit=8, of=34, won=6),
    ])
    keeps = [i["because"] for i in out["items"] if i["good"]]
    assert len(keeps) == 3
    assert len(set(keeps)) == 3, "each positive finding needs its own sentence"


def test_grouping_by_map_keeps_every_item(engine):
    out = engine([
        _pattern("death", "top mid", "de_mirage", "t", hit=20, of=40, won=3),
        _pattern("death", "lobby", "de_nuke", "t", hit=20, of=40, won=3),
    ])
    flat = sum(len(items) for _mp, items in out["by_map"])
    assert flat == len(out["items"])
    assert {mp for mp, _ in out["by_map"]} == {"mirage", "nuke"}


def test_no_team_data_produces_no_advice(monkeypatch):
    monkeypatch.setattr(advice, "team_stats", lambda _tid: None)
    out = advice.monday(1)
    assert out["items"] == [] and out["baseline"] == 0.0


def test_a_team_with_no_rounds_produces_no_advice(monkeypatch):
    monkeypatch.setattr(advice, "team_stats",
                        lambda _tid: _stats(baseline_won=0, baseline_rounds=0))
    assert advice.monday(1)["items"] == []


# ----------------------------------------------------------- the utility copy
#
# The `engine` fixture stubs utility out entirely, so nothing above this line
# ever sees a utility finding. These build one.


def _utility_engine(monkeypatch, splits, unused=None, flashes=None,
                    won=23, rounds=42):
    monkeypatch.setattr(advice, "team_stats",
                        lambda _tid: _stats(baseline_won=won,
                                            baseline_rounds=rounds))
    monkeypatch.setattr(advice.movement, "positional_patterns", lambda _tid: [])
    from app import utility
    monkeypatch.setattr(utility, "round_splits", lambda _tid: splits)
    monkeypatch.setattr(utility, "flashes", lambda _tid: flashes)
    monkeypatch.setattr(utility, "unused", lambda _tid: unused)
    return advice.monday(1)


# 45% of utility value dying unused: well past the collegiate 29%, so the
# card appears and these tests can read its wording.
UNUSED = {"bought": 100, "thrown": 60, "unused": 40, "rounds": 42,
          "rounds_holding": 31, "spent": 10000, "wasted": 4500,
          "per_round": 1171.0}


def test_dying_with_utility_is_read_against_college_teams(monkeypatch):
    """29% of utility value dies unused for college teams. The old fixed 20%
    line flagged UCF, NC State Red and NC State BLK for being normal."""
    typical = dict(UNUSED, wasted=2900)                    # 29%
    out = _utility_engine(monkeypatch, {"died_holding": (15, 31)},
                          unused=typical)
    assert not out["items"]
    out = _utility_engine(monkeypatch, {"died_holding": (15, 31)},
                          unused=UNUSED)
    assert "other college teams" in _only_item(out)["because"]


def _only_item(out):
    assert len(out["items"]) == 1, [i["do"] for i in out["items"]]
    return out["items"][0]


def test_the_footer_says_how_often_not_how_often_you_won(monkeypatch):
    """The old footer invited a causal reading its sample could not support.

    "You win 15 of the 31 rounds it happens in (48%), against 55% overall" is
    a seven point gap on thirty-one rounds, where the standard error is near
    nine. MIN_CHANCES refuses rates on thinner evidence than that.

    And the arrow plausibly points the other way: you die holding utility
    BECAUSE you died, so the win rate beside the habit reads as cause when it
    is closer to consequence.
    """
    out = _utility_engine(monkeypatch, {"died_holding": (15, 31)},
                          unused=UNUSED)
    foot = _only_item(out)["foot"]
    assert foot == "Happens in 31 of your 42 rounds"
    assert "against" not in foot and "overall" not in foot
    assert "48" not in foot and "%" not in foot


def test_utility_findings_never_call_it_grenades(monkeypatch):
    """The numbers were never only grenades.

    unused() reads nades_value and nades_wasted, and utility.py prices a
    flashbang at $200 and a CT incendiary at $600, so flashes, smokes,
    mollies and decoys are all in the figure. In CS a "nade" usually means an
    HE, so "of grenades a round" claims something narrower than the data, and
    a coach checking it against their HE spend would find it wrong.
    """
    out = _utility_engine(monkeypatch, {"died_holding": (15, 31)},
                          unused=UNUSED)
    item = _only_item(out)
    text = " ".join([item["do"], item["because"]] + list(item["evidence"]))
    assert "grenade" not in text.lower(), text
    assert "utility" in item["because"].lower()
    # Priced in dollars, and formatted the way the evidence line beneath it is.
    assert "$1,171" in item["because"]


def test_two_clusters_sharing_a_name_stay_separate(engine):
    """de_mirage has three zones called "A main"; they are different places.

    Merging is keyed on the cluster and not on its name. Keyed on the name,
    findings about genuinely different parts of the map collapsed into one
    recommendation, and a coach was told to drill a spot that was really two.
    """
    out = engine([
        _pattern("commit", "A main", "mirage", "t", 20, 40, 4, zone_index=8),
        _pattern("death", "A main", "mirage", "t", 18, 40, 3, zone_index=14),
    ])
    assert len(out["items"]) == 2, [i["do"] for i in out["items"]]


def test_one_cluster_seen_two_ways_still_merges(engine):
    """The behaviour the merge exists for has to survive the fix.

    The group stalling at a place and the first death happening there are one
    recommendation, as long as it really is one place.
    """
    out = engine([
        _pattern("commit", "A main", "mirage", "t", 20, 40, 4, zone_index=8),
        _pattern("death", "A main", "mirage", "t", 18, 40, 3, zone_index=8),
    ])
    assert len(out["items"]) == 1, [i["do"] for i in out["items"]]
