"""A coach is not a player.

A FACEIT coach occupies a slot in the demo, is alive every round and never
shoots. team_stats() had filtered them for a long time; team_players(), which
builds the season roster, had not, so the roster listed the coach as a Rifle
on 0 ADR. Both now go through report.is_coach().
"""
from __future__ import annotations

import importlib
import os
import pathlib
import tempfile

import pytest


@pytest.fixture()
def rep():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    now = db_mod.utcnow()
    db_mod.execute("""INSERT INTO teams (name, slug, league, plan, created_at)
                      VALUES ('Us', 'us', 'NECC', 'free', ?)""", now)
    team = db_mod.one("SELECT id FROM teams WHERE slug = 'us'")["id"]

    def pr(mk, rn, sid, side, kills=0, deaths=0, damage=0.0):
        db_mod.execute("""INSERT INTO player_rounds
                            (match_key, round_num, steamid, name, side,
                             kills, deaths, damage)
                          VALUES (?,?,?,?,?,?,?,?)""",
                       mk, rn, sid, sid, side, kills, deaths, damage)

    for i in (1, 2):
        mk = f"m{i}"
        db_mod.execute("""INSERT INTO demos (team_id, filename, sha256, created_at)
                          VALUES (?,?,?,?)""", team, f"{mk}.dem", mk, now)
        demo = db_mod.one("SELECT id FROM demos WHERE sha256 = ?", mk)["id"]
        db_mod.execute("""INSERT INTO matches (match_key, demo_id, map_name, created_at)
                          VALUES (?,?,?,?)""", mk, demo, "de_mirage", now)
        for rn in range(1, 13):
            db_mod.execute("""INSERT INTO rounds (match_key, round_num, map_name, ct_won)
                              VALUES (?,?,?,?)""", mk, rn, "de_mirage", rn % 2)
            for p in range(5):
                pr(mk, rn, f"ours{p}", "ct", kills=1, deaths=1, damage=80.0)
                pr(mk, rn, f"opp{i}_{p}", "t", kills=1, deaths=1, damage=80.0)
            pr(mk, rn, "coach", "ct")
    # A stand-in who played match 1 for us and had one quiet round against
    # us in match 2. Judged on that one round alone they would look like a
    # coach and vanish from the "against" split.
    for rn in range(1, 13):
        pr("m1", rn, "standin", "ct", kills=1, deaths=1, damage=70.0)
    pr("m2", 1, "standin", "t")

    from app import report
    importlib.reload(report)
    yield report, team

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def test_is_coach_is_no_kills_no_deaths_no_damage():
    from app.report import is_coach
    assert is_coach({"kills": 0, "deaths": 0, "damage": 0.0})
    assert not is_coach({"kills": 0, "deaths": 1, "damage": 0.0})
    assert not is_coach({"kills": 0, "deaths": 0, "damage": 3.0})
    assert not is_coach({"kills": 1, "deaths": 0, "damage": 0.0})


def test_the_season_roster_has_no_coach(rep):
    report, team = rep
    ids = {a["steamid"] for a in report.team_players(team)}
    assert "coach" not in ids
    assert {f"ours{p}" for p in range(5)} <= ids


def test_the_coach_is_on_neither_side_of_the_split(rep):
    report, team = rep
    sq = report.squad(team)
    everyone = {a["steamid"] for a in sq["yours"] + sq["others"]}
    assert "coach" not in everyone
    assert not any(a["role"] == "Rifle" and a["adr"] == 0 for a in sq["yours"])


def test_a_quiet_subset_does_not_make_a_player_a_coach(rep):
    report, team = rep
    against = {a["steamid"] for a in report.team_players(team, ours_only=False)}
    assert "standin" in against
