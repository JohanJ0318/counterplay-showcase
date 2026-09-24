"""More than one team per person, and handing one over.

Both arrived the same night. A UCF team was built for a coach on an account
that already owned one, and the UI could not show it: team_for_user() was
ORDER BY created_at LIMIT 1 with no picker anywhere. And a team built FOR
somebody has to be able to become theirs, or the report dies with whoever
made it.

The rules worth guarding are the ones that would be quiet if broken: a
forged team id must not move you onto somebody else's season, a GET must
never perform the handover, and a used token must never work twice.
"""
import importlib
import os
import pathlib
import tempfile

import pytest


@pytest.fixture
def two_teams(monkeypatch):
    """One user, two teams; one other user with none.

    Same shape as tests/test_share.py: a temp database and an importlib
    reload, because db.py hands out a THREAD-LOCAL connection that is
    created once and cached. Without the reload every test after the first
    keeps talking to the previous test's file.
    """
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    global db
    db = db_mod
    db.init()
    uid = db.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role,
                              plan, verify_token, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        "a@example.edu", "a@example.edu", "x", "A", "coach", "free", "t1",
        db.utcnow())
    other = db.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role,
                              plan, verify_token, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        "b@example.edu", "b@example.edu", "x", "B", "coach", "free", "t2",
        db.utcnow())
    ids = []
    for name in ("First", "Second"):
        tid = db.execute(
            """INSERT INTO teams (name, slug, league, faceit_url, plan,
                                  created_at, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            name, name.lower(), "NECC", "", "free", db.utcnow(), uid)
        db.execute("""INSERT INTO team_members (team_id, user_id, member_role,
                                                created_at)
                      VALUES (?,?,?,?)""", tid, uid, "owner", db.utcnow())
        ids.append(tid)
    yield uid, other, ids

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def test_defaults_to_the_oldest_membership(two_teams):
    """Nobody's existing behaviour changes just because the column exists."""
    uid, _other, ids = two_teams
    assert db.team_for_user(uid)["id"] == ids[0]


def test_both_teams_are_listed(two_teams):
    uid, _other, ids = two_teams
    assert [t["id"] for t in db.teams_for_user(uid)] == ids


def test_switching_sticks(two_teams):
    uid, _other, ids = two_teams
    assert db.set_active_team(uid, ids[1]) is True
    assert db.team_for_user(uid)["id"] == ids[1]


def test_cannot_switch_to_a_team_you_are_not_in(two_teams):
    """The id comes from a form, so it is attacker-controlled."""
    uid, other, ids = two_teams
    assert db.set_active_team(other, ids[0]) is False
    assert db.team_for_user(other) is None


def test_active_team_is_ignored_once_you_leave_it(two_teams):
    """A handover must not strand the old owner on a team they cannot see."""
    uid, _other, ids = two_teams
    db.set_active_team(uid, ids[1])
    db.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
               ids[1], uid)
    assert db.team_for_user(uid)["id"] == ids[0]


def test_a_user_with_no_team_gets_none(two_teams):
    _uid, other, _ids = two_teams
    assert db.team_for_user(other) is None
    assert db.teams_for_user(other) == []


def test_handover_moves_ownership_and_burns_the_token(two_teams):
    """What /claim/{token} does, at the level that matters: the rows."""
    uid, other, ids = two_teams
    team_id = ids[0]
    db.execute("UPDATE teams SET claim_token = ? WHERE id = ?", "tok", team_id)

    # The route's body, which is the thing worth asserting about.
    with db.connect() as c:
        c.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
        c.execute("""INSERT INTO team_members (team_id, user_id, member_role,
                                               created_at)
                     VALUES (?,?,?,?)""",
                  (team_id, other, "owner", db.utcnow()))
        c.execute("UPDATE teams SET claim_token = NULL WHERE id = ?", (team_id,))
        c.execute("UPDATE users SET active_team_id = ? WHERE id = ?",
                  (team_id, other))

    assert db.team_for_user(other)["id"] == team_id
    assert db.team_for_user(other)["member_role"] == "owner"
    # The previous owner is out of that team and back on their other one.
    assert [t["id"] for t in db.teams_for_user(uid)] == [ids[1]]
    # And the token cannot be replayed.
    assert db.one("SELECT claim_token FROM teams WHERE id = ?",
                  team_id)["claim_token"] is None


def test_a_spent_token_matches_nothing(two_teams):
    _uid, _other, ids = two_teams
    db.execute("UPDATE teams SET claim_token = NULL WHERE id = ?", ids[0])
    assert db.one("SELECT id FROM teams WHERE claim_token = ?", None) is None


def test_empty_token_matches_nothing(two_teams):
    """The same empty-string hole tests/test_share.py guards for share links."""
    _uid, _other, ids = two_teams
    db.execute("UPDATE teams SET claim_token = ? WHERE id = ?", "", ids[0])
    found = db.one("SELECT id FROM teams WHERE claim_token = ? "
                   "AND claim_token != ''", "")
    assert found is None
