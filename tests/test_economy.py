"""Per-player economy: what reaches the database, and what "unknown" looks like.

Migration 23 made these columns nullable on purpose. A player who started a
round with no money and a demo we never read money from must not look the
same, or every average over "money at the start of the round" is dragged
down by rounds parsed before the column existed.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import tempfile

import pandas as pd

from counterplay import economy, parse


def test_a_loadout_keeps_what_can_be_bought():
    inv = ["Karambit", "Glock-18", "AK-47", "Smoke Grenade", "C4 Explosive"]
    assert economy.loadout(inv) == "Glock-18, AK-47, Smoke Grenade"


def test_no_inventory_is_unknown_not_empty():
    assert economy.loadout(None) is None
    assert economy.loadout(float("nan")) is None
    assert economy.loadout([]) == ""


def test_the_main_weapon_is_the_strongest_gun_held():
    assert economy.main_weapon("USP-S, AWP, Desert Eagle") == "sniper"
    assert economy.main_weapon("Glock-18, MAC-10, Flashbang") == "smg"
    assert economy.main_weapon("Smoke Grenade") == "pistol"
    assert economy.main_weapon("") == "pistol"
    assert economy.main_weapon(None) is None


def test_the_parser_names_every_economy_column():
    for c in ("money_start", "spent", "equip_value", "loadout"):
        assert c in parse.PLAYER_COLUMNS


def _fresh_db():
    tmp = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    os.environ["COUNTERPLAY_DB"] = str(tmp)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    from app import ingest
    importlib.reload(ingest)
    return db_mod, ingest


def test_store_keeps_money_and_keeps_unknown_as_null():
    was = os.environ.get("COUNTERPLAY_DB")
    try:
        db_mod, ingest = _fresh_db()
        now = db_mod.utcnow()
        db_mod.execute("INSERT INTO demos (filename, sha256, created_at) "
                       "VALUES ('a.dem', 'a', ?)", now)
        demo = db_mod.one("SELECT id FROM demos")["id"]
        rounds = pd.DataFrame([{"match_id": "a", "round_num": 1,
                                "map_name": "de_mirage", "tier": "collegiate",
                                "equip_ct": 4100.0, "equip_t": 850.0,
                                "ct_won": True}])
        base = {c: 0 for c in parse.PLAYER_COLUMNS}
        known = dict(base, match_id="a", round_num=1, steamid="1", name="x",
                     side="ct", money_start=3900, spent=3900, equip_value=4100,
                     loadout="USP-S, M4A1-S")
        broke = dict(known, steamid="2", name="y", money_start=0, spent=0,
                     equip_value=200, loadout="")
        unread = dict(known, steamid="3", name="z", money_start=None,
                      spent=None, equip_value=None, loadout=None)
        players = pd.DataFrame([known, broke, unread],
                               columns=parse.PLAYER_COLUMNS)
        ingest.store(demo, "a", rounds, pd.DataFrame(), players,
                     faceit_match_id=None, competition="", tier="collegiate",
                     ingested_at=now)
        got = {r["steamid"]: r for r in db_mod.query(
            "SELECT steamid, money_start, spent, equip_value, loadout "
            "FROM player_rounds")}
        assert (got["1"]["money_start"], got["1"]["spent"],
                got["1"]["equip_value"], got["1"]["loadout"]) == \
            (3900, 3900, 4100, "USP-S, M4A1-S")
        assert got["2"]["money_start"] == 0 and got["2"]["loadout"] == ""
        assert got["3"]["money_start"] is None
        assert got["3"]["spent"] is None
        assert got["3"]["loadout"] is None
    finally:
        if was is None:
            os.environ.pop("COUNTERPLAY_DB", None)
        else:
            os.environ["COUNTERPLAY_DB"] = was
