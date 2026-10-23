"""The match and season coaching sections (app/coaching.py, main.py blocks).

Guarded: nothing is drawn when there is nothing to say (no cause past half a
round, no habit); what is drawn is coaching words with a practice line and
rounds to watch; no em dash; and the coaching module never raises into a
page, whatever the database holds.
"""
from app import coaching, main

LOSS = {"won": 8, "lost": 13, "causes": [
    {"cause": "crosshair", "label": "Crosshair not on the enemy when he appeared",
     "rounds": 0.8, "rounds_text": "about a round",
     "practice": "Keep your crosshair at head height on the angle the enemy "
                 "will come from, before you see him.",
     "watch": ["round 21, 0:38 in", "round 17, 1:10 in"]}]}
HABITS = {"deaths": 286, "habits": [
    {"code": "through_smoke", "sentence": "You keep dying through smokes.",
     "n": 27, "of": 286, "rate": 0.094, "college": 0.066,
     "watch": ["nuke round 4, 0:30 in"]}]}


def test_nothing_to_say_draws_nothing():
    assert main.match_loss_block(None) == ""
    assert main.match_loss_block({"won": 13, "lost": 5, "causes": []}) == ""
    assert main.habits_block(None) == ""
    assert main.habits_block({"deaths": 200, "habits": []}) == ""


def test_a_cause_reads_as_coaching():
    html = main.match_loss_block(LOSS)
    assert "What cost you this match" in html and 'data-tab="Rounds"' in html
    assert "Crosshair not on the enemy" in html and "about a round" in html
    assert "Practice:" in html and "round 21, 0:38 in" in html
    assert chr(8212) not in html


def test_a_habit_reads_as_coaching():
    html = main.habits_block(HABITS)
    assert "What keeps happening" in html and "You keep dying through smokes." in html
    assert "On 27 of your 286 deaths" in html and "nuke round 4" in html
    assert chr(8212) not in html


def test_rounds_are_said_to_the_half():
    assert coaching._rounds_text(0.4) == "about half a round"
    assert coaching._rounds_text(1.1) == "about a round"
    assert coaching._rounds_text(1.3) == "about 1.5 rounds"
    assert coaching._rounds_text(2.2) == "about 2 rounds"


def test_the_module_never_raises_into_a_page():
    assert coaching.match_loss("no-such-match", 999999) is None
    assert coaching.season_habits(999999) is None


def test_a_win_is_titled_as_what_still_cost_rounds():
    won = {**LOSS, "won": 13, "lost": 6}
    assert "What still cost you rounds" in main.match_loss_block(won)
    assert "What cost you this match" in main.match_loss_block(LOSS)


def test_a_cause_at_the_round_start_names_just_the_round():
    assert coaching._where(9, 0.0) == "round 9"
    assert coaching._where(9, 104.2) == "round 9, 1:44 in"
