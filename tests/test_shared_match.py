"""A match both teams played belongs to both teams' seasons, parsed once each.

On 2026-09-27 North Georgia (team 6, demo 123) uploaded their placement
against the UCF Knights, which UCF (team 5, demo 121) had sent in first. The
duplicate guard matched any team's parsed copy, so demo 123 was marked
'duplicate' and never parsed, and every reading is scoped to a team through
demos.team_id: North Georgia's season simply did not have the match.

The rules guarded here:

  * the second team's upload is parsed, under its own match_key
  * the first team gains nothing from it: same keys, same match
  * a share link for one team still refuses the other team's copy
  * a demo already marked duplicate parses once it is re-queued (the box fix)
  * a corpus row with no team is still skipped: nobody's report can see it
  * league-wide readings (corpus_matches, corpus.load_frames) count it once
  * forgetting one team does not delete the file the other team re-parses from
"""
from __future__ import annotations

import importlib
import os
import pathlib
import tempfile

import pandas as pd
import pytest

pytest.importorskip("zstandard")

SHA = "c0ffee" * 10 + "abcd"


def _frames(*_a, **_k):
    rounds = pd.DataFrame({"round_num": [1, 2, 3], "map_name": ["de_mirage"] * 3,
                           "equip_ct": [4000.0] * 3, "equip_t": [4000.0] * 3,
                           "ct_won": [True, False, True]})
    events = pd.DataFrame(columns=["round_num", "seconds", "type", "victim_side"])
    return rounds, events, None, {}, {}, "de_mirage"


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp / "t.db")
    from app import db as db_mod
    importlib.reload(db_mod)
    monkeypatch.setattr(db_mod, "DEMO_DIR", tmp / "demos")
    db_mod.init()
    from app import alert, corpus, ingest, report
    for m in (ingest, report, corpus):
        importlib.reload(m)
    monkeypatch.setattr(ingest, "parse_to_frames", _frames)
    monkeypatch.setattr(ingest, "check", lambda r, e: (True, "ok"))
    monkeypatch.setattr(ingest, "should_keep", lambda row: True)
    monkeypatch.setattr(alert, "parsed", lambda *a, **k: None)
    for slug in ("ucf", "ngu"):
        db_mod.execute("""INSERT INTO teams (name, slug, league, plan, created_at)
                          VALUES (?,?,?,?,?)""",
                       slug.upper(), slug, "NECC", "free", db_mod.utcnow())
    yield db_mod, ingest, report, corpus

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def _team(db, slug):
    return db.one("SELECT * FROM teams WHERE slug = ?", slug)["id"]


def _upload(db, team_id, name="placement.dem", source="upload"):
    """A demo row and its file in the store, as the upload form leaves them.

    The store is keyed by content, so the second team's upload finds the file
    the first one left (compressed by then, as on the box).
    """
    db.DEMO_DIR.mkdir(parents=True, exist_ok=True)
    if not list(db.DEMO_DIR.glob(f"{SHA}.dem*")):
        (db.DEMO_DIR / f"{SHA}.dem").write_bytes(b"PBDEMS2\x00" + b"x" * 64)
    return db.execute(
        """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes, sha256,
                              tier, status, created_at, source)
           VALUES (?,NULL,?,?,?,'league','pending',?,?)""",
        team_id, name, 72, SHA, db.utcnow(), source)


def _process(db, ingest, demo_id):
    return ingest.process(db.one("SELECT * FROM demos WHERE id = ?", demo_id))


def _status(db, demo_id):
    return db.one("SELECT status FROM demos WHERE id = ?", demo_id)["status"]


def _both_parsed(env):
    db, ingest, report, _c = env
    ucf, ngu = _team(db, "ucf"), _team(db, "ngu")
    first = _upload(db, ucf)
    _process(db, ingest, first)
    second = _upload(db, ngu)
    ok, note = _process(db, ingest, second)
    return ucf, ngu, first, second, ok, note


# ------------------------------------------------------------ demo 123

def test_the_second_team_gets_the_match(env):
    db, ingest, report, _c = env
    ucf, ngu, first, second, ok, note = _both_parsed(env)
    assert ok, note
    assert "duplicate" not in note
    assert _status(db, second) == "parsed"
    assert len(report._team_match_keys(ngu)) == 1
    assert report._team_match_keys(ngu) != report._team_match_keys(ucf)


def test_the_first_team_gains_nothing(env):
    db, ingest, report, _c = env
    ucf = _team(db, "ucf")
    first = _upload(db, ucf)
    _process(db, ingest, first)
    before = report._team_match_keys(ucf)
    rounds_before = db.one("SELECT COUNT(*) n FROM rounds WHERE match_key = ?",
                           before[0])["n"]

    second = _upload(db, _team(db, "ngu"))
    _process(db, ingest, second)

    assert report._team_match_keys(ucf) == before
    assert db.one("SELECT COUNT(*) n FROM rounds WHERE match_key = ?",
                  before[0])["n"] == rounds_before
    assert [m["match_key"] for m in report.team_matches(ucf)] == before


def test_a_demo_marked_duplicate_parses_when_requeued(env):
    """What the box needs for demo 123: re-queue it and let the worker run."""
    db, ingest, report, _c = env
    ucf, ngu = _team(db, "ucf"), _team(db, "ngu")
    _process(db, ingest, _upload(db, ucf))
    stuck = _upload(db, ngu)
    db.execute("""UPDATE demos SET status='duplicate',
                  status_note='same bytes as demo 1 (league), not parsed again'
                  WHERE id = ?""", stuck)
    assert report._team_match_keys(ngu) == []

    db.execute("UPDATE demos SET status='pending', attempts=0 WHERE id=?", stuck)
    ok, note = _process(db, ingest, stuck)
    assert ok, note
    assert _status(db, stuck) == "parsed"
    assert len(report._team_match_keys(ngu)) == 1


def test_a_share_link_still_refuses_the_other_teams_copy(env):
    db, ingest, report, _c = env
    ucf, ngu, *_ = _both_parsed(env)
    from app import main
    ngu_key = report._team_match_keys(ngu)[0]
    ucf_team = db.one("SELECT * FROM teams WHERE id = ?", ucf)
    resp = main._match_body(ngu_key, share="tok", share_team=ucf_team)
    assert resp.status_code == 404


# ------------------------------------------------ the guard that remains

def test_a_teamless_corpus_copy_is_still_skipped(env):
    db, ingest, report, _c = env
    _both_parsed(env)
    orphan = _upload(db, None, name="corpus.dem", source="local")
    ok, note = _process(db, ingest, orphan)
    assert ok and "duplicate" in note
    assert _status(db, orphan) == "duplicate"


def test_twin_of_is_scoped_to_the_team(env):
    db, ingest, report, _c = env
    ucf, ngu = _team(db, "ucf"), _team(db, "ngu")
    first = _upload(db, ucf)
    _process(db, ingest, first)
    assert ingest.twin_of(999, SHA, ngu) is None
    assert ingest.twin_of(999, SHA, ucf)["id"] == first
    assert ingest.twin_of(999, SHA, None)["id"] == first
    assert ingest.twin_of(first, SHA, ucf) is None


# ------------------------------------------------ league-wide, counted once

def test_corpus_matches_counts_the_match_once(env):
    db, ingest, report, corpus = env
    ucf, ngu, first, second, *_ = _both_parsed(env)
    assert db.one("SELECT COUNT(*) n FROM matches")["n"] == 2
    rows = db.query("SELECT demo_id FROM corpus_matches")
    assert [r["demo_id"] for r in rows] == [first]

    rounds, _e = corpus.load_frames()
    assert rounds["match_id"].nunique() == 1
    assert len(rounds) == 3
    assert corpus.summary()["matches"] == 1
    # Each team's own frames still carry the match.
    for team in (ucf, ngu):
        r, _e = corpus.load_frames(team_id=team)
        assert r["match_id"].nunique() == 1


def test_corpus_matches_keeps_the_survivor_when_the_first_team_leaves(env):
    db, ingest, report, corpus = env
    ucf, ngu, first, second, *_ = _both_parsed(env)
    ingest.forget_team(ucf)
    rows = db.query("SELECT demo_id FROM corpus_matches")
    assert [r["demo_id"] for r in rows] == [second]


def test_forgetting_one_team_keeps_the_file_the_other_needs(env):
    db, ingest, report, _c = env
    ucf, ngu, *_ = _both_parsed(env)
    got = ingest.forget_team(ngu)
    assert got["files_removed"] == 0
    assert ingest.stored_path(SHA) is not None
    assert len(report._team_match_keys(ucf)) == 1

    # The last team holding it does take the file with it.
    got = ingest.forget_team(ucf)
    assert got["files_removed"] == 1
    assert ingest.stored_path(SHA) is None
