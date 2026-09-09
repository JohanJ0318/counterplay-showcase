"""Tests for password resets.

This is the one flow in the product where getting it slightly wrong hands
somebody else an account. The rules worth guarding are not the wording of the
pages but the six properties underneath them:

  * the token in the database is a hash, never the token itself
  * a token expires
  * a token works once
  * spending one invalidates every other outstanding token for that account
  * spending one ends every session that account has open
  * the request path never reveals whether an address has an account

Written against a temporary database so the assertions are about the rules
rather than about whatever happens to be in the real one.
"""
from __future__ import annotations

import os
import tempfile
import pathlib

import pytest


@pytest.fixture()
def app_db(monkeypatch):
    """A fresh database with one account, and the modules pointed at it."""
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    # db.py reads the path at import, so the variable has to be set before the
    # reload and put back afterwards. Leaving it set would point every later
    # test in the run at this throwaway file.
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    import importlib
    from app import db as db_mod
    importlib.reload(db_mod)
    # db.init() is the whole bootstrap: schema.sql first, then the
    # migrations. Running only the migrations builds a database with no
    # `users` table for them to alter.
    db_mod.init()
    from app import auth as auth_mod, resets as resets_mod
    importlib.reload(auth_mod)
    importlib.reload(resets_mod)
    db_mod.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role,
                              plan, email_verified, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        "coach@example.com", "coach@example.com",
        auth_mod.hash_password("original-password-1"), "Coach", "coach",
        "free", 0, db_mod.utcnow())
    yield db_mod, auth_mod, resets_mod

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)
    importlib.reload(auth_mod)
    importlib.reload(resets_mod)


def _user(db):
    return db.one("SELECT * FROM users WHERE email_key = 'coach@example.com'")


# ------------------------------------------------------------------ storage

def test_the_token_is_not_stored(app_db):
    """A leaked backup must not be a set of live password resets."""
    db, _auth, resets = app_db
    token, _ = resets.issue("coach@example.com")
    rows = db.query("SELECT token_hash FROM password_resets")
    assert len(rows) == 1
    assert token not in rows[0]["token_hash"]
    assert len(rows[0]["token_hash"]) == 64        # sha256 hex


def test_an_unknown_address_issues_nothing(app_db):
    db, _auth, resets = app_db
    assert resets.issue("nobody@example.com") is None
    assert db.query("SELECT * FROM password_resets") == []


# -------------------------------------------------------------- the token

def test_a_fresh_token_finds_its_owner(app_db):
    _db, _auth, resets = app_db
    token, _ = resets.issue("coach@example.com")
    assert resets.holder(token)["email"] == "coach@example.com"


def test_an_expired_token_is_dead(app_db):
    db, _auth, resets = app_db
    token, _ = resets.issue("coach@example.com")
    db.execute("UPDATE password_resets SET expires_at = ?",
               db.minutes_ago(1))
    assert resets.holder(token) is None
    assert resets.spend(token, "a-new-password-99") is False


def test_a_token_works_once(app_db):
    _db, _auth, resets = app_db
    token, _ = resets.issue("coach@example.com")
    assert resets.spend(token, "a-new-password-99") is True
    assert resets.spend(token, "another-password-99") is False


def test_a_made_up_token_is_dead(app_db):
    _db, _auth, resets = app_db
    resets.issue("coach@example.com")
    assert resets.holder("not-a-real-token") is None
    assert resets.holder("") is None


# ------------------------------------------------------------- consequences

def test_spending_one_token_burns_every_other_one(app_db):
    """Two requests in a row must not leave a spare key behind."""
    _db, _auth, resets = app_db
    first, _ = resets.issue("coach@example.com")
    second, _ = resets.issue("coach@example.com")
    assert resets.spend(second, "a-new-password-99") is True
    assert resets.holder(first) is None


def test_the_password_actually_changes(app_db):
    db, auth, resets = app_db
    token, _ = resets.issue("coach@example.com")
    resets.spend(token, "a-new-password-99")
    stored = _user(db)["password_hash"]
    assert auth.verify_password("a-new-password-99", stored)
    assert not auth.verify_password("original-password-1", stored)


def test_spending_one_signs_the_account_out_everywhere(app_db):
    """"I forgot my password" and "somebody is in my account" look identical."""
    db, auth, resets = app_db
    uid = _user(db)["id"]
    auth.start_session(uid)
    auth.start_session(uid)
    assert db.one("SELECT COUNT(*) n FROM sessions")["n"] == 2
    token, _ = resets.issue("coach@example.com")
    resets.spend(token, "a-new-password-99")
    assert db.one("SELECT COUNT(*) n FROM sessions")["n"] == 0


def test_a_reset_clears_the_login_throttle(app_db):
    """Otherwise the failed guesses that preceded it lock the real owner out."""
    _db, auth, resets = app_db
    for _ in range(auth.MAX_ATTEMPTS):
        auth.record_failure("coach@example.com")
    assert auth.too_many_attempts("coach@example.com")
    token, _ = resets.issue("coach@example.com")
    resets.spend(token, "a-new-password-99")
    assert not auth.too_many_attempts("coach@example.com")


# ------------------------------------------------------------- rate limiting

def test_an_address_can_only_be_mailed_so_often(app_db):
    _db, _auth, resets = app_db
    for _ in range(resets.MAX_REQUESTS):
        assert not resets.too_many("coach@example.com")
        resets.issue("coach@example.com")
    assert resets.too_many("coach@example.com")


def test_an_address_with_no_account_is_never_rate_limited(app_db):
    """It has nothing to rate limit, and saying so would leak the account."""
    _db, _auth, resets = app_db
    for _ in range(resets.MAX_REQUESTS * 2):
        assert resets.too_many("nobody@example.com") is False
