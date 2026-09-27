"""The outreach path end to end: build a team for a coach, then hand it over.

Two gaps stopped this working for more than one coach. A team built for a
coach could only be made by hand in the database. And a coach arriving from
a handover link was sent to sign up, which made them an empty team of their
own, and then left them on the dashboard with no way back to the link.

Route functions are called directly, as tests/test_pages.py does.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import tempfile
import types

import pytest


@pytest.fixture()
def app_mod():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    from app import auth, main
    importlib.reload(auth)
    importlib.reload(main)
    yield main
    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def _user(main, email, admin=False):
    db, auth = main.db, main.auth
    uid = db.execute(
        """INSERT INTO users (email, email_key, password_hash, name, role, plan,
                              verify_token, created_at, is_admin)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        email, auth.email_key(email), auth.hash_password("correct-horse-battery"),
        "x", "coach", "free", "t", db.utcnow(), int(admin))
    token, _ = auth.start_session(uid, "test")
    session = auth.session_user(token)
    return uid, token, session["csrf"]


def _req(token=None):
    cookies = {main_cookie(): token} if token else {}
    return types.SimpleNamespace(cookies=cookies, headers={"user-agent": "test"},
                                 query_params={})


def main_cookie():
    from app import auth
    return auth.SESSION_COOKIE


def _signup(main, **kw):
    """Every form field, as a browser sends them. Called directly, a route's
    missing arguments would be FastAPI's Form() placeholders, not strings."""
    fields = dict(team="", league="", role="coach", name="", email="",
                  password="", faceit_url="", homepage="", claim="")
    fields.update(kw)
    return main.signup_post(_req(), **fields)


def _loc(resp):
    return resp.headers.get("location")


def test_the_master_account_builds_a_team_and_lands_on_it(app_mod):
    main, db = app_mod, app_mod.db
    uid, tok, csrf = _user(main, "admin@example.edu", admin=True)
    r = main.team_new(_req(tok), name="UCF Knights", league="NECC", csrf=csrf)
    assert _loc(r) == "/dashboard"
    team = db.team_for_user(uid)
    assert team["name"] == "UCF Knights" and team["member_role"] == "owner"
    assert team["plan"] == main.DEFAULT_TEAM_PLAN


def test_a_normal_account_cannot_build_a_team(app_mod):
    main, db = app_mod, app_mod.db
    uid, tok, csrf = _user(main, "coach@example.edu")
    main.team_new(_req(tok), name="Somebody Else", league="NECC", csrf=csrf)
    assert db.team_for_user(uid) is None
    assert db.one("SELECT COUNT(*) n FROM teams")["n"] == 0


def test_signing_up_from_a_handover_link_makes_no_team_and_returns_to_it(app_mod):
    main, db = app_mod, app_mod.db
    uid, tok, csrf = _user(main, "admin@example.edu", admin=True)
    main.team_new(_req(tok), name="UCF Knights", league="NECC", csrf=csrf)
    team = db.team_for_user(uid)
    db.execute("UPDATE teams SET claim_token = 'claim-abc' WHERE id = ?", team["id"])

    page = main.signup_get(_req(), claim="claim-abc").body.decode()
    assert 'name="claim"' in page and 'name="team"' not in page

    r = _signup(main, email="ash@example.edu",
                password="correct-horse-battery", claim="claim-abc")
    assert _loc(r) == "/claim/claim-abc"
    new = db.one("SELECT id FROM users WHERE email = 'ash@example.edu'")["id"]
    assert db.team_for_user(new) is None          # no empty second team
    # Nothing has moved yet: the handover is the confirm page's button.
    assert db.team_for_user(uid)["id"] == team["id"]


def test_a_spent_handover_link_falls_back_to_an_ordinary_signup(app_mod):
    main = app_mod
    r = _signup(main, email="late@example.edu",
                password="correct-horse-battery", claim="gone")
    assert r.status_code == 400
    assert "already been used" in r.body.decode()


def test_the_claim_page_buttons_carry_the_token(app_mod):
    main, db = app_mod, app_mod.db
    uid, tok, csrf = _user(main, "admin@example.edu", admin=True)
    main.team_new(_req(tok), name="UCF Knights", league="NECC", csrf=csrf)
    db.execute("UPDATE teams SET claim_token = 'claim-abc'")
    html = main.claim_page(_req(), "claim-abc").body.decode()
    assert "/signup?claim=claim-abc" in html
    assert "/login?next=/claim/claim-abc" in html


def test_login_returns_to_a_handover_page_and_nowhere_else(app_mod):
    main = app_mod
    _user(main, "ash@example.edu")
    r = main.login_post(_req(), email="ash@example.edu",
                        password="correct-horse-battery", next="/claim/claim-abc")
    assert _loc(r) == "/claim/claim-abc"
    for bad in ("https://evil.example", "//evil.example", "/dashboard",
                "/claim//evil.example", "/claim/\\evil"):
        assert main.safe_next(bad) == "", bad
