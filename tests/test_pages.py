"""The pages a coach's link opens actually open.

Every player page answered 500 for a day and a half: report.player_matches()
renamed a key to "added" and main.py went on reading "ingested_at". Nothing
loaded a player page, so nothing noticed. These tests render the shared pages
over a small fake season and assert two things a coach would see at once: the
page is there, and every link out of it stays inside the share link rather
than bouncing a player to the login screen.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import re
import tempfile

import pytest

TOKEN = "tok-pages-test"


@pytest.fixture()
def client():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    now = db_mod.utcnow()
    db_mod.execute("""INSERT INTO teams (name, slug, league, plan, created_at,
                                         share_token)
                      VALUES ('Us', 'us', 'NECC', 'free', ?, ?)""", now, TOKEN)
    team = db_mod.one("SELECT id FROM teams WHERE slug = 'us'")["id"]

    for i in (1, 2):
        mk = f"m{i}"
        db_mod.execute("""INSERT INTO demos (team_id, filename, sha256, created_at)
                          VALUES (?,?,?,?)""", team, f"{mk}.dem", mk, now)
        demo = db_mod.one("SELECT id FROM demos WHERE sha256 = ?", mk)["id"]
        db_mod.execute("""INSERT INTO matches (match_key, demo_id, map_name,
                                               created_at, ingested_at, rounds)
                          VALUES (?,?,?,?,?,?)""",
                       mk, demo, "de_mirage", now, now, 12)
        for rn in range(1, 13):
            db_mod.execute("""INSERT INTO rounds (match_key, round_num, map_name, ct_won)
                              VALUES (?,?,?,?)""", mk, rn, "de_mirage", rn % 2)
            for p in range(5):
                for sid, side in ((f"ours{p}", "ct"), (f"opp{i}_{p}", "t")):
                    db_mod.execute("""INSERT INTO player_rounds
                                        (match_key, round_num, steamid, name, side,
                                         kills, deaths, damage)
                                      VALUES (?,?,?,?,?,?,?,?)""",
                                   mk, rn, sid, sid, side, 1, 1, 80.0)

    from app import report, main
    importlib.reload(report)
    importlib.reload(main)
    yield main

    if was is None:
        os.environ.pop("COUNTERPLAY_DB", None)
    else:
        os.environ["COUNTERPLAY_DB"] = was
    importlib.reload(db_mod)


def _links(html: str) -> list[str]:
    return re.findall(r'href="(/[^"]*)"', html)


# The route functions are called directly: starlette's TestClient needs an
# HTTP package this project does not otherwise install.
def _get(main, path: str):
    routes = {
        "": lambda: main.shared_season(TOKEN),
        "/players": lambda: main.shared_players(TOKEN),
        "/p/ours0": lambda: main.shared_player(TOKEN, "ours0"),
        "/m/m1": lambda: main.shared_match(TOKEN, "m1"),
    }
    r = routes[path]()
    return r.status_code, r.body.decode("utf-8")


def test_a_shared_player_page_opens(client):
    status, html = _get(client, "/p/ours0")
    assert status == 200, html[:500]
    assert "ours0" in html


def test_a_shared_match_opens(client):
    status, html = _get(client, "/m/m1")
    assert status == 200, html[:500]


@pytest.mark.parametrize("path", ["", "/players", "/p/ours0", "/m/m1"])
def test_links_out_of_a_shared_page_stay_inside_the_link(client, path):
    html = _get(client, path)[1]
    leaks = [h for h in _links(html)
             if h.startswith(("/player/", "/match/", "/stats", "/players",
                              "/matches", "/trends", "/dashboard"))]
    assert not leaks, leaks


def test_the_coach_is_on_the_roster_as_a_coach(client):
    """A FACEIT coach sits in a player slot on your side and never shoots.
    They belong on the roster, named as the coach, with none of the artifact
    numbers standing still produces, and no link to a page of them."""
    from app import db
    for mk in ("m1", "m2"):
        for rn in range(1, 13):
            db.execute("""INSERT INTO player_rounds
                            (match_key, round_num, steamid, name, side,
                             kills, deaths, damage)
                          VALUES (?,?,?,?,?,?,?,?)""",
                       mk, rn, "coachsid", "Coach Carter", "ct", 0, 0, 0.0)
    html = _get(client, "/players")[1]
    row = re.search(r"<tr><td class=\"name\">Coach Carter</td>.*?</tr>", html)
    assert row, "the coach is missing from the roster"
    assert 'class="role">Coach<' in row.group(0)
    assert "coachsid" not in html            # no link to a player page
    assert "and your coach" in html


def test_the_zone_map_script_is_one_statement_list():
    """The zone map's script is the page's data followed by ZONE_JS. A comma
    where the data ends ("N={...},var F=") is a syntax error that leaves every
    place uncoloured and silent, and nothing else on the page complains. The
    test page has no positions to draw a map from, so this checks the join in
    the source and the start of the constant it joins to."""
    import inspect
    from app import main
    src = inspect.getsource(main)
    join = src[src.index("N={json.dumps(znames"):]
    join = join[:join.index("ZONE_JS")]
    assert "))};'" in join, join
    assert main.ZONE_JS.lstrip().startswith("var ")


def test_tab_puts_every_section_under_its_name():
    from app.main import _tab, PAGE_TABS
    out = _tab("Positions", '<section class="lead">a</section><section>b</section>')
    assert out.count('<section data-tab="Positions"') == 2
    assert _tab("X", "") == ""
    # The sections come after the script, so it must wait for the page.
    assert "DOMContentLoaded" in PAGE_TABS
