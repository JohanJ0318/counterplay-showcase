"""The coach's read in the app (app/coach.py): written, held, approved, shown.

A fake Claude client stands in for the API, so nothing here spends money or
needs a network. What is guarded: a note that fails the checker or the
reviewer twice is never shown; an approval with an edit is held to the same
checker; auto-approval switches on only after a clean run of approvals and
off again on one edit; nothing sent to the API carries a player's identity.
"""
import importlib
import json
import os
import pathlib
import tempfile
from types import SimpleNamespace

import pytest

PACK = {
    "team": "Test U", "team_id": 1, "anchors": ["76561198000000001"],
    "demos": ["abc"], "reference": "NECC collegiate teams, 164 matches",
    "facts": [
        {"id": "F1", "kind": "pattern", "scope": "all maps",
         "text": "You win a force round: 3 of 14 (21%); college teams 40%.",
         "verdict": -1, "rounds": []},
        {"id": "F2", "kind": "map_side", "scope": "anubis T",
         "text": "anubis T: won 4 of 11 rounds (36%); college teams win 57% "
                 "on anubis T.", "verdict": 0, "rounds": []},
    ],
}
GOOD = {"summary": "Force buys are costing you rounds.", "points": [
    {"headline": "Force with a plan", "kind": "fix", "facts": ["F1"],
     "what_happens": "You win 3 of 14 force rounds (21%). College teams win 40%.",
     "practice": "Only force when the caller names the site.",
     "rounds_to_watch": []}]}
BAD = {**GOOD, "points": [{**GOOD["points"][0],
                           "what_happens": "You win 3 of 14, against 45%."}]}


class FakeClient:
    """Answers each call by which prompt it was given."""

    def __init__(self, note=GOOD, verdict="SHIP"):
        self.note, self.verdict, self.calls = note, verdict, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if kw["system"].startswith("You review"):
            out = {"verdict": self.verdict,
                   "problems": [] if self.verdict == "SHIP" else ["too long"]}
        else:
            out = self.note
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(out))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
            stop_reason="end_turn")


@pytest.fixture
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    from app import coach as coach_mod
    importlib.reload(coach_mod)
    db_mod.init()
    uid = db_mod.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role,
                              plan, verify_token, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        "j@example.edu", "j@example.edu", "x", "J", "coach", "free", "t",
        db_mod.utcnow())
    tid = db_mod.execute(
        """INSERT INTO teams (name, slug, league, faceit_url, plan, created_at,
                              created_by) VALUES (?,?,?,?,?,?,?)""",
        "Test U", "test-u", "NECC", "", "free", db_mod.utcnow(), uid)
    monkeypatch.setattr(coach_mod, "evidence", lambda team_id: dict(PACK))
    yield SimpleNamespace(db=db_mod, coach=coach_mod, uid=uid, tid=tid)
    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def test_a_clean_note_waits_for_approval_then_shows(env):
    nid = env.coach.generate(env.tid, FakeClient())
    row = env.db.one("SELECT status, cost_usd FROM coach_notes WHERE id = ?", nid)
    assert row["status"] == "pending" and row["cost_usd"] > 0
    assert env.coach.latest(env.tid) is None          # not shown until approved
    assert env.coach.decide(nid, env.uid, True) == []
    assert env.coach.latest(env.tid)["summary"] == GOOD["summary"]


def test_a_note_that_fails_twice_is_never_shown(env):
    nid = env.coach.generate(env.tid, FakeClient(note=BAD))
    row = env.db.one("SELECT status, problems FROM coach_notes WHERE id = ?", nid)
    assert row["status"] == "failed" and "45" in row["problems"]
    nid = env.coach.generate(env.tid, FakeClient(verdict="FIX"))
    assert env.db.one("SELECT status FROM coach_notes WHERE id = ?",
                      nid)["status"] == "failed"
    assert env.coach.latest(env.tid) is None


def test_an_edit_is_held_to_the_checker(env):
    nid = env.coach.generate(env.tid, FakeClient())
    invented = {"summary": GOOD["summary"], "points": [
        {"headline": "Force with a plan",
         "what_happens": "You win 3 of 14 force rounds. College teams win 55%.",
         "practice": "Only force when the caller names the site."}]}
    assert env.coach.decide(nid, env.uid, True, invented)
    assert env.coach.latest(env.tid) is None          # refused, nothing saved
    fine = {**invented, "points": [{**invented["points"][0],
                                    "what_happens": "You win 3 of 14 force rounds "
                                                    "(21%), college teams 40%."}]}
    assert env.coach.decide(nid, env.uid, True, fine) == []
    assert env.db.one("SELECT edited FROM coach_notes WHERE id = ?", nid)["edited"] == 1


def test_auto_approval_needs_a_clean_run_and_one_edit_stops_it(env):
    for _ in range(env.coach.AUTO_APPROVE_AFTER):
        nid = env.coach.generate(env.tid, FakeClient())
        assert env.coach.decide(nid, env.uid, True) == []
    nid = env.coach.generate(env.tid, FakeClient())
    assert env.db.one("SELECT status, auto FROM coach_notes WHERE id = ?",
                      nid)["auto"] == 1
    # One rejection by a person and the queue is back on.
    nid = env.coach.generate(env.tid, FakeClient())
    env.db.execute("UPDATE coach_notes SET status = 'pending', auto = 0 WHERE id = ?", nid)
    env.coach.decide(nid, env.uid, False)
    nid = env.coach.generate(env.tid, FakeClient())
    assert env.db.one("SELECT status FROM coach_notes WHERE id = ?",
                      nid)["status"] == "pending"


def test_nothing_sent_identifies_a_player(env):
    client = FakeClient()
    env.coach.generate(env.tid, client)
    sent = " ".join(m["content"] for c in client.calls for m in c["messages"])
    assert "76561198000000001" not in sent and '"anchors"' not in sent
    assert '"demos"' not in sent


def test_no_key_means_no_notes_and_no_error(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(env.coach, "api_key", lambda: "")
    assert env.coach.refresh() == []


def test_the_read_renders_as_the_lead_of_overview():
    from app import main
    html = main.coach_read_block({**GOOD})
    assert "Coach's read" in html and "work on this" in html
    assert "Practice:" in html and 'class="lead"' in html
    assert "Written by Claude" not in html      # Johan cut it, 2026-10-14
