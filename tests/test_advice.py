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


def _pattern(kind, zone, mp, side, hit, of, won):
    return {"kind": kind, "zone": zone, "map": mp, "side": side,
            "hit": hit, "of": of, "won": won,
            "pct": 100.0 * hit / of, "win_pct": 100.0 * won / hit if hit else 0,
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
    """Drives `monday()` with data we control instead of the database."""
    def run(patterns, stats=None):
        monkeypatch.setattr(advice, "team_stats",
                            lambda _tid: stats or _stats())
        monkeypatch.setattr(advice.movement, "positional_patterns",
                            lambda _tid: patterns)
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


def test_the_baseline_is_the_teams_own_rate_not_a_fixed_number(engine):
    """The same situation is a problem for a good team and normal for a bad one.

    30% conversion is 19 points below a 49% team and 5 points below a 35% team.
    Only the first is worth a Monday.
    """
    p = [_pattern("death", "top mid", "de_mirage", "t", hit=20, of=40, won=6)]
    good = engine(p, _stats(baseline_won=49))
    weak = engine(p, _stats(baseline_won=35))
    assert good["items"], "19 points below a 49% team should surface"
    assert not weak["items"], "5 points below a 35% team should not"


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
