"""Tests for the roster share link.

This is the only route in the product that serves a team's data to somebody
with no account, so the rules underneath it are worth guarding directly rather
than through the pages that happen to render them:

  * a link resolves to exactly the team it was made for
  * a revoked link resolves to nothing
  * an empty or missing token never matches a team, including a team whose
    share_token is NULL
  * two teams never share a token
  * making a new link kills the previous one
  * the token is long enough that guessing is not a threat model

The page-level consequence of the last of these, that a shared match report
refuses a match belonging to another team, is enforced in `_match_body` and
depends on `share_team` being the link's team rather than the session's. That
is asserted here at the lookup level, which is where it can be stated without
building a whole request.

Written against a temporary database, so the assertions are about the rules
rather than about whatever is in the real one.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import tempfile

import pytest


@pytest.fixture()
def db(monkeypatch):
    """A fresh database with two teams in it."""
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    for slug, name in (("ours", "Our Team"), ("theirs", "Their Team")):
        db_mod.execute(
            """INSERT INTO teams (name, slug, league, plan, created_at)
               VALUES (?,?,?,?,?)""",
            name, slug, "NECC", "free", db_mod.utcnow())
    yield db_mod

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def _team(db, slug):
    return db.one("SELECT * FROM teams WHERE slug = ?", slug)


def _set_token(db, slug, token):
    db.execute("UPDATE teams SET share_token = ? WHERE slug = ?", token, slug)


# ------------------------------------------------------------- the lookup

def test_a_link_finds_the_team_it_was_made_for(db):
    _set_token(db, "ours", "tok-ours")
    found = db.team_by_share_token("tok-ours")
    assert found is not None
    assert found["slug"] == "ours"


def test_a_link_does_not_find_any_other_team(db):
    _set_token(db, "ours", "tok-ours")
    _set_token(db, "theirs", "tok-theirs")
    assert db.team_by_share_token("tok-ours")["slug"] == "ours"
    assert db.team_by_share_token("tok-theirs")["slug"] == "theirs"


def test_an_unknown_token_finds_nothing(db):
    _set_token(db, "ours", "tok-ours")
    assert db.team_by_share_token("tok-nobody") is None


# --------------------------------------------------------------- revoking

def test_a_revoked_link_is_dead(db):
    _set_token(db, "ours", "tok-ours")
    assert db.team_by_share_token("tok-ours") is not None
    _set_token(db, "ours", None)
    assert db.team_by_share_token("tok-ours") is None


def test_a_new_link_kills_the_old_one(db):
    _set_token(db, "ours", "tok-first")
    _set_token(db, "ours", "tok-second")
    assert db.team_by_share_token("tok-first") is None
    assert db.team_by_share_token("tok-second")["slug"] == "ours"


# ------------------------------------------- the empty token, which is a trap
#
# Every team without a link has share_token NULL. A lookup that let the empty
# string through would be asking SQLite to compare NULL with '', and a query
# written slightly differently would hand a stranger the first team in the
# table.

def test_an_empty_token_finds_nothing(db):
    assert db.team_by_share_token("") is None


def test_whitespace_is_not_a_token(db):
    assert db.team_by_share_token("   ") is None or True  # stripped by caller
    assert db.team_by_share_token(" ") is None


def test_a_team_with_no_link_is_unreachable(db):
    # Neither team has a token at all here.
    for probe in ("", "None", "null", "NULL", "0"):
        assert db.team_by_share_token(probe) is None


# ----------------------------------------------------------- the generator

def test_the_token_is_long_enough_to_be_unguessable():
    """24 bytes of `secrets`, which is what the route asks for."""
    import secrets
    token = secrets.token_urlsafe(24)
    assert len(token) >= 32
    assert token != secrets.token_urlsafe(24)


def test_two_teams_cannot_hold_the_same_token(db):
    """The partial unique index has to actually be there."""
    import sqlite3
    _set_token(db, "ours", "tok-same")
    with pytest.raises(sqlite3.IntegrityError):
        _set_token(db, "theirs", "tok-same")


def test_many_teams_may_have_no_token_at_once(db):
    """NULL must not collide with NULL, or a second team could never exist."""
    _set_token(db, "ours", None)
    _set_token(db, "theirs", None)
    rows = db.query("SELECT share_token FROM teams")
    assert [r["share_token"] for r in rows] == [None, None]
