"""The coach's read checker (tools/coach_read.py): a note shows only if every
number and round in it comes from the facts it cites."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import coach_read  # noqa: E402

PACK = {"facts": [
    {"id": "F1", "text": "You win a force round: 3 of 14 (21%); college teams 40%.",
     "verdict": -1, "rounds": []},
    {"id": "F2", "text": "dust2 CT: won 6 of 7 rounds (86%).", "verdict": 1,
     "rounds": ["dust2 4"]},
]}


def _note(**over):
    p = {"headline": "Force with a plan", "what_happens":
         "You won 3 of 14 force buys (21%), against 40% for college teams.",
         "practice": "Call the site before a 4v5 force.", "rounds_to_watch": [],
         "facts": ["F1"], "kind": "fix"}
    p.update(over)
    return {"summary": "Forcing is costing you.", "points": [p]}


def test_a_note_built_from_its_facts_passes():
    assert coach_read.check(PACK, _note()) == []


def test_an_invented_number_fails():
    bad = _note(what_happens="You won 3 of 14 force buys, against 45%.")
    assert any("45" in p for p in coach_read.check(PACK, bad))


def test_a_number_from_an_uncited_fact_fails():
    bad = _note(what_happens="You won 6 of 7 CT rounds.")
    assert coach_read.check(PACK, bad)


def test_rounds_and_keep_need_backing():
    assert coach_read.check(PACK, _note(rounds_to_watch=["dust2 4"]))
    assert coach_read.check(PACK, _note(kind="keep"))
    ok = _note(facts=["F2"], kind="keep", rounds_to_watch=["dust2 4"],
               what_happens="You won 6 of 7 CT rounds on Dust2 (86%).",
               practice="Keep the default.")
    assert coach_read.check(PACK, ok) == []


def test_unknown_fact_and_numbers_in_summary_fail():
    assert coach_read.check(PACK, _note(facts=["F9"]))
    n = _note()
    n["summary"] = "You lost 11 forces."
    assert coach_read.check(PACK, n)


def test_a_map_name_with_a_digit_is_not_a_number():
    n = _note()
    n["summary"] = "Your dust2 CT side is the strength."
    assert coach_read.check(PACK, n) == []


PACK["facts"].append({"id": "F3", "text": "anubis T: won 4 of 11 rounds (36%); "
                      "college teams win 57% on anubis T.", "verdict": 0,
                      "rounds": []})


def test_a_check_must_say_how_many_rounds_it_rests_on():
    lead = _note(facts=["F3"], kind="check",
                 what_happens="You won 4 of 11 Anubis T rounds against 57%: "
                              "a lead to check, not a verdict.",
                 practice="Watch the lost rounds.")
    assert coach_read.check(PACK, lead) == []
    vague = _note(facts=["F3"], kind="check",
                  what_happens="Anubis T went badly, 36% against 57%.",
                  practice="Watch the lost rounds.")
    assert coach_read.check(PACK, vague)
    assert coach_read.check(PACK, _note(facts=["F3"], kind="fix",
                                        what_happens="4 of 11.",
                                        practice="Watch."))


def test_a_ranking_word_needs_a_fact_that_ranks():
    bad = _note(what_happens="Your weakest buy: 3 of 14 force rounds won.")
    assert any("weakest" in p for p in coach_read.check(PACK, bad))


def test_word_limits_and_numbers_in_practice():
    long = _note(what_happens="You won 3 of 14 force buys " + "and lost " * 20)
    assert any("words" in p for p in coach_read.check(PACK, long))
    drill = _note(practice="Run 10 force setups.")
    assert any("practice: carries a number" in p for p in coach_read.check(PACK, drill))


def test_scorer_facts_only_in_a_check():
    PACK["facts"].append({"id": "F9", "kind": "scorer", "text": "Experimental "
                          "scorer: nuke round 6; win chance fell from 44% to 15%.",
                          "verdict": None, "rounds": ["nuke 6"]})
    as_fix = _note(facts=["F1", "F9"])
    assert any("scorer" in p for p in coach_read.check(PACK, as_fix))
