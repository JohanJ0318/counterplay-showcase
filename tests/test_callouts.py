"""Places from the game's own callouts (counterplay/callouts.py).

Pins positions to the place they must count under, from the shipped files:
each bombsite's centre (tools/site_centres.py, measured off the game's own
bomb-zone flags) on its site, Nuke's two sites apart by height alone, and
the numbering scan() relies on: groups 1..n with no gap, spawns dropped.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from app import movement
from counterplay import callouts as CO

SITES = json.loads((Path(CO.__file__).parent / "site_centres.json").read_text())
MAPS = ["de_mirage", "de_inferno", "de_dust2", "de_ancient", "de_anubis",
        "de_nuke", "de_cache"]


def _label(co, x, y, z):
    k = int(co.assign(np.array([x]), np.array([y]), np.array([z]))[0])
    return co.callouts[k]["label"] if k else None


@pytest.mark.parametrize("mp", MAPS)
def test_every_map_has_its_files(mp):
    co = CO.load(mp)
    assert co is not None
    assert co.draw["floors"] and all(f["paths"] for f in co.draw["floors"])


@pytest.mark.parametrize("mp", [m for m in MAPS if m in SITES])
def test_site_centres_count_on_their_site(mp):
    # A centre is an average of positions and can fall on a crate nobody
    # stands in (Ancient's and Anubis's B), which is nowhere. The ground a
    # step around it must be the site, and nothing there another place.
    co = CO.load(mp)
    for site, want in (("1", "A Site"), ("2", "B Site")):
        c = SITES[mp][site]
        got = [_label(co, c["x"] + dx, c["y"] + dy, c["z"])
               for dx, dy in ((0, 0), (80, 0), (-80, 0), (0, 80), (0, -80))]
        assert got.count(want) >= 3, (mp, site, got)
        assert set(got) <= {want, None}, (mp, site, got)


def test_nuke_sites_are_told_apart_by_height():
    co = CO.load("de_nuke")
    a, b = SITES["de_nuke"]["1"], SITES["de_nuke"]["2"]
    # B site sits under A: at A's x, y but B's height, it must not be A.
    assert _label(co, a["x"], a["y"], b["z"]) != "A Site"
    assert _label(co, b["x"], b["y"], a["z"]) != "B Site"


def test_far_off_the_ground_is_nowhere():
    co = CO.load("de_mirage")
    c = SITES["de_mirage"]["1"]
    assert _label(co, c["x"], c["y"], c["z"] + 1000) is None
    assert _label(co, 1e6, 1e6, 0) is None


@pytest.mark.parametrize("mp", MAPS)
def test_groups_are_contiguous_and_spawns_dropped(mp):
    co, group_of, names, centres = movement._centres(mp)
    assert sorted(names) == list(range(1, len(names) + 1))
    assert len(centres) == len(names) + 1
    for k, c in co.callouts.items():
        if "spawn" in c["label"].lower():
            assert group_of[k] == 0
        else:
            assert names[group_of[k]] == c["label"]


def test_drawing_is_keyed_by_the_counting_groups():
    co, group_of, names, _ = movement._centres("de_mirage")
    fl = co.draw["floors"][0]
    svg = CO.svg("de_mirage", fl, None, stat_zones=True, groups=group_of)
    import re
    drawn = {int(z) for z in re.findall(r'data-z="(\d+)"', svg)}
    assert drawn and drawn <= set(names)
    assert "zlab" in svg and 'class="zborder"' in svg
