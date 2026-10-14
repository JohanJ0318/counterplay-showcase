"""The resource library behind the coach's read (tools/resources.py,
app/resources.py). What is guarded: only rows Johan marked KEEP count as
vetted; a guide for one map or side is never retrieved for another; a note
may cite only a resource retrieved for the facts its point rests on; and
the card draws the link.

No embedding model is loaded here: retrieval's ranking runs on the PC, and
these tests cover the rules around it.
"""
import importlib.util
import pathlib

from app import coach, resources

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("resources_tool",
                                              ROOT / "tools" / "resources.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

MD = """
| Topic (tag) | Video | Keep? |
|---|---|---|
| nuke / CT / default | [Lock Down Nuke's CT Side](https://www.youtube.com/watch?v=a) | KEEP |
| anubis / T / default | [Anubis T default](https://www.youtube.com/watch?v=b) | CUT |
| ancient / CT / retakes | [Retake A](https://www.youtube.com/watch?v=c) and [Retake B on Ancient](https://www.youtube.com/watch?v=d) | |
| economy / force | [Economy guide](https://example.com/eco) (2025) | keep, decent |
"""


def test_only_keep_rows_are_vetted_and_each_link_is_its_own_resource():
    rows = tool.parse(MD)
    assert [r["title"] for r in rows] == [
        "Lock Down Nuke's CT Side", "Anubis T default", "Retake A (ancient)",
        "Retake B on Ancient", "Economy guide"]
    assert [r["vetted"] for r in rows] == [True, False, False, False, True]
    assert rows[0]["kind"] == "video" and rows[-1]["kind"] == "article"


def test_a_guide_is_never_retrieved_for_another_map_or_side():
    nuke_ct = {"tags": "nuke / CT / default"}
    assert tool.allowed(nuke_ct, ("nuke", "ct", "default"))
    assert not tool.allowed(nuke_ct, ("nuke", "t", "default"))
    assert not tool.allowed(nuke_ct, ("train", "ct", "default"))
    assert not tool.allowed(nuke_ct, ("any", "any", "trading"))
    eco = {"tags": "economy / force"}
    assert tool.allowed(eco, ("any", "any", "economy"))
    assert not tool.allowed(eco, ("nuke", "ct", "default"))
    both = {"tags": "inferno / CT, T"}
    assert tool.allowed(both, ("inferno", "t", "default"))


def test_facts_map_to_the_questions_they_raise():
    side = {"kind": "map_side", "scope": "nuke CT", "text": "nuke CT: won 3 of 12"}
    assert resources.keys_for(side) == [("nuke", "ct", "default"),
                                        ("nuke", "ct", "retake")]
    force = {"kind": "pattern", "scope": "all maps",
             "text": "You win a force round: 3 of 14 (21%)."}
    assert resources.keys_for(force) == [("any", "any", "economy")]
    assert resources.keys_for({"kind": "result", "scope": "nuke",
                               "text": "nuke: you lost the map 6 to 13."}) == []


PACK = {"team": "T", "reference": "r", "resources": {"R1": {"title": "x",
                                                             "kind": "video"}},
        "facts": [
            {"id": "F1", "kind": "pattern", "scope": "all maps",
             "text": "You win a force round: 3 of 14 (21%); college teams 40%.",
             "verdict": -1, "rounds": [], "resources": ["R1"]},
            {"id": "F2", "kind": "pattern", "scope": "all maps",
             "text": "Flashes blind nobody: 89 of 132.", "verdict": -1,
             "rounds": [], "resources": []}]}


def note(fact, rid):
    return {"summary": "Force buys cost you rounds.", "points": [
        {"kind": "fix", "headline": "Force with a plan", "facts": [fact],
         "what_happens": "You win 3 of 14 force rounds." if fact == "F1"
                         else "89 of 132 flashes blind nobody.",
         "practice": "Only force when the caller names the site.",
         "rounds_to_watch": [], "resource": rid}]}


def test_a_note_may_cite_only_what_was_retrieved_for_its_facts():
    assert coach.check(PACK, note("F1", "R1")) == []
    assert coach.check(PACK, note("F1", "")) == []
    assert any("not retrieved" in p for p in coach.check(PACK, note("F2", "R1")))
    assert any("not retrieved" in p for p in coach.check(PACK, note("F1", "R9")))


def test_the_card_links_a_resource_and_drops_one_cut_since(monkeypatch):
    from app import main
    monkeypatch.setattr(resources, "_cache", {
        "resources": {"R1": {"title": "Lock Down Nuke's CT Side",
                             "url": "https://www.youtube.com/watch?v=a",
                             "kind": "video"}}, "keys": {}})
    html = main.coach_read_block(note("F1", "R1"))
    assert "Watch: <a href=\"https://www.youtube.com/watch?v=a\"" in html
    assert 'rel="noopener noreferrer"' in html
    assert "Watch:" not in main.coach_read_block(note("F1", "R2"))


def test_the_shipped_index_holds_only_vetted_resources():
    ix = resources.index()
    vetted = {r["url"] for r in tool.parse(tool.SOURCE.read_text(encoding="utf-8"))
              if r["vetted"]}
    assert {r["url"] for r in ix["resources"].values()} <= vetted
