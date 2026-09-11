"""Tests for the utility parser and the numbers drawn off it.

Utility is the part of the report most able to be quietly wrong, because every
one of its numbers is a join: a blind to the flash that caused it, a grenade to
the round it landed in, a molotov to the people standing near it. A join that
misses does not raise, it returns zero, and zero looks like "they threw no
grenades" rather than "the parser is broken". Every bug found while building
this was of exactly that shape:

  * steamids routed through float() lost their last two digits, so every
    lookup missed and every utility figure on the page read 0
  * blind EVENTS were counted as flashes that landed, which double-counted
    every flashbang that blinded more than one person
  * "unused" grenades counted survivors, and survivors keep their utility in
    rounds they were already winning, so the number said 93% won

So these tests are about the joins and the denominators, not the wording.
Written against a fake parser: the assertions are about the rules rather than
about whatever happens to be true of one demo.
"""
from __future__ import annotations

import pandas as pd
import pytest

from counterplay import utility as parse_util

TICK = 64.0

# Two real steamids, one digit apart at the end. Any code that routes these
# through a float collapses them to the same number.
ALICE = "76561190000000101"
BOB = "76561190000000102"
ENEMY = "76561190000000103"


class FakeParser:
    """Just enough of demoparser2 to drive the extraction."""

    def __init__(self, **frames):
        self.frames = {k: pd.DataFrame(v) for k, v in frames.items()}

    def parse_event(self, name):
        if name not in self.frames:
            raise ValueError(f"no such event: {name}")
        return self.frames[name]

    def parse_ticks(self, props, ticks=None):
        raise ValueError("no inventory")


def _fixture(**frames):
    """A one-round match starting at tick 1000 and ending at 7000."""
    parser = FakeParser(**frames)
    freeze = {1: 1000}
    end = {1: 7000}

    def round_of(tick):
        return 1 if 1000 <= tick <= 7000 else None

    side_of = {(1, ALICE): "t", (1, BOB): "t", (1, ENEMY): "ct"}
    credited: dict = {}

    def credit(rn, sid, field, amount=1):
        if sid is None:
            return
        credited[(rn, str(sid), field)] = credited.get((rn, str(sid), field), 0) + amount

    return parser, round_of, set(), freeze, end, side_of, credit, credited


# ------------------------------------------------------------------ steamids

def test_a_steamid_survives_normalisation():
    """17 digits do not fit in a float64, and the last two are the join."""
    assert parse_util._sid(ALICE) == ALICE
    assert parse_util._sid(ALICE) != parse_util._sid(BOB)


def test_a_steamid_arriving_as_a_float_string_loses_its_decimal():
    assert parse_util._sid("76561190000000101.0") == ALICE


def test_a_missing_steamid_is_none_not_the_string_nan():
    assert parse_util._sid(float("nan")) is None
    assert parse_util._sid(None) is None
    assert parse_util._sid("nan") is None


# -------------------------------------------------------------------- blinds

def test_a_flash_on_the_other_side_is_not_an_own_side_flash():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 2000, "user_steamid": ENEMY,
                       "attacker_steamid": ALICE, "blind_duration": 3.0}])
    rows = parse_util.blinds(parser, round_of, tainted, fz, side, None, credit)
    assert len(rows) == 1 and rows[0]["own_side"] == 0
    assert got[(1, ALICE, "enemies_flashed")] == 1
    assert (1, ALICE, "teammates_flashed") not in got


def test_blinding_a_teammate_is_counted_as_own_side():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 2000, "user_steamid": BOB,
                       "attacker_steamid": ALICE, "blind_duration": 2.5}])
    rows = parse_util.blinds(parser, round_of, tainted, fz, side, None, credit)
    assert rows[0]["own_side"] == 1
    assert got[(1, ALICE, "teammates_flashed")] == 1
    assert got[(1, ALICE, "blind_team_secs")] == 2.5


def test_blinding_yourself_counts_as_own_side_too():
    """From a coach's chair it is the same mistake with the same fix."""
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 2000, "user_steamid": ALICE,
                       "attacker_steamid": ALICE, "blind_duration": 1.8}])
    rows = parse_util.blinds(parser, round_of, tainted, fz, side, None, credit)
    assert rows[0]["own_side"] == 1


def test_a_blind_outside_the_round_is_dropped():
    """Flashes fly after the round is decided; they belong to no round."""
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 9999, "user_steamid": ENEMY,
                       "attacker_steamid": ALICE, "blind_duration": 3.0}])
    assert parse_util.blinds(parser, round_of, tainted, fz, side, None, credit) == []


def test_a_death_inside_the_blind_window_credits_both_players():
    """The flash goes to whoever threw it and the kill to whoever took it.

    Usually not the same player, and crediting one number to both is how a
    duo's work becomes one player's stat.
    """
    deaths = pd.DataFrame([{"tick": 2100, "user_steamid": ENEMY,
                            "attacker_steamid": BOB}])
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 2000, "user_steamid": ENEMY,
                       "attacker_steamid": ALICE, "blind_duration": 3.0}])
    rows = parse_util.blinds(parser, round_of, tainted, fz, side, deaths, credit)
    assert rows[0]["died_blind"] == 1
    assert got[(1, ALICE, "flash_assists")] == 1     # threw it
    assert got[(1, BOB, "flash_kills")] == 1         # took it


def test_a_death_after_the_blind_wore_off_is_not_a_flash_kill():
    deaths = pd.DataFrame([{"tick": 2000 + int(3.0 * TICK) + 200,
                            "user_steamid": ENEMY, "attacker_steamid": BOB}])
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        player_blind=[{"tick": 2000, "user_steamid": ENEMY,
                       "attacker_steamid": ALICE, "blind_duration": 3.0}])
    rows = parse_util.blinds(parser, round_of, tainted, fz, side, deaths, credit)
    assert rows[0]["died_blind"] == 0
    assert (1, ALICE, "flash_assists") not in got


# ------------------------------------------------------------------ grenades

def test_every_grenade_kind_is_read_with_its_position():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        flashbang_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 10.0, "y": 20.0, "z": 30.0}],
        smokegrenade_detonate=[{"tick": 2100, "user_steamid": ALICE,
                                "entityid": 2, "x": 1.0, "y": 2.0, "z": 3.0}],
        hegrenade_detonate=[{"tick": 2200, "user_steamid": BOB,
                             "entityid": 3, "x": 0.0, "y": 0.0, "z": 0.0}],
        inferno_startburn=[{"tick": 2300, "user_steamid": BOB,
                            "entityid": 4, "x": 5.0, "y": 5.0, "z": 5.0}],
    )
    rows = parse_util.grenades(parser, round_of, tainted, fz, side)
    assert {r["kind"] for r in rows} == {"flash", "smoke", "he", "molotov"}
    flash = next(r for r in rows if r["kind"] == "flash")
    assert (flash["x"], flash["y"], flash["z"]) == (10.0, 20.0, 30.0)
    assert flash["side"] == "t"
    assert flash["seconds"] == pytest.approx((2000 - 1000) / TICK)


def test_a_smoke_gets_its_life_from_the_matching_expiry():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        smokegrenade_detonate=[{"tick": 2000, "user_steamid": ALICE,
                                "entityid": 7, "x": 0.0, "y": 0.0, "z": 0.0}],
        smokegrenade_expired=[{"tick": 2000 + int(18 * TICK), "entityid": 7,
                               "user_steamid": ALICE, "x": 0.0, "y": 0.0, "z": 0.0}],
    )
    rows = parse_util.grenades(parser, round_of, tainted, fz, side)
    assert rows[0]["life"] == pytest.approx(18.0)


def test_a_reused_entity_id_takes_the_expiry_that_follows_it():
    """Entity ids come round again inside one match.

    Matching on the id alone gave one smoke two lifetimes and the other none.
    """
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        smokegrenade_detonate=[
            {"tick": 2000, "user_steamid": ALICE, "entityid": 7,
             "x": 0.0, "y": 0.0, "z": 0.0},
            {"tick": 5000, "user_steamid": ALICE, "entityid": 7,
             "x": 0.0, "y": 0.0, "z": 0.0}],
        smokegrenade_expired=[
            {"tick": 3152, "entityid": 7, "user_steamid": ALICE,
             "x": 0.0, "y": 0.0, "z": 0.0},
            {"tick": 6152, "entityid": 7, "user_steamid": ALICE,
             "x": 0.0, "y": 0.0, "z": 0.0}],
    )
    rows = parse_util.grenades(parser, round_of, tainted, fz, side)
    assert [round(r["life"], 1) for r in rows] == [18.0, 18.0]


# ----------------------------------------------------------------- attribute

def test_one_flashbang_that_blinds_three_people_is_still_one_flash():
    """The bug this whole column exists to prevent.

    Counting blind events as flashes that landed turned 356 flashes into 731
    landings on a real season.
    """
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        flashbang_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    blinds = [{"round_num": 1, "tick": 2000, "own_side": 0,
               "thrower_steamid": ALICE, "duration": 3.0} for _ in range(3)]
    parse_util.attribute(grens, blinds, parser, round_of, tainted, side)
    assert len(grens) == 1
    assert grens[0]["hit_enemy"] == 3      # three people
    assert sum(1 for g in grens if g["hit_enemy"]) == 1   # one flash


def test_a_blind_from_a_different_flash_is_not_credited_to_this_one():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        flashbang_detonate=[
            {"tick": 2000, "user_steamid": ALICE, "entityid": 1,
             "x": 0.0, "y": 0.0, "z": 0.0},
            {"tick": 4000, "user_steamid": ALICE, "entityid": 2,
             "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(
        grens, [{"round_num": 1, "tick": 4000, "own_side": 0,
                 "thrower_steamid": ALICE, "duration": 3.0}],
        parser, round_of, tainted, side)
    assert [g["hit_enemy"] for g in grens] == [0, 1]


def test_a_blind_too_short_to_matter_is_not_counted_as_one():
    """The quarter second somebody catches while turning away.

    CS2 fires `player_blind` for any exposure at all. Counting those the same
    as a full blind put a real season at "67% of your flashes blind your own
    side" against 62% blinding an opponent, which is an artefact of the
    measurement rather than a fact about the team.
    """
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        flashbang_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    below = parse_util.MIN_BLIND_SECONDS - 0.01
    parse_util.attribute(
        grens, [{"round_num": 1, "tick": 2000, "own_side": 0,
                 "thrower_steamid": ALICE, "duration": below}],
        parser, round_of, tainted, side)
    assert grens[0]["hit_enemy"] == 0

    # And the same flash, held a hundredth of a second longer, does count.
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(
        grens, [{"round_num": 1, "tick": 2000, "own_side": 0,
                 "thrower_steamid": ALICE,
                 "duration": parse_util.MIN_BLIND_SECONDS}],
        parser, round_of, tainted, side)
    assert grens[0]["hit_enemy"] == 1


def test_a_kill_behind_a_blind_too_short_to_count_is_not_a_flash_kill():
    """Otherwise the page says a flash that blinded nobody got somebody killed."""
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        flashbang_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(
        grens, [{"round_num": 1, "tick": 2000, "own_side": 0,
                 "thrower_steamid": ALICE, "duration": 0.2, "died_blind": 1}],
        parser, round_of, tainted, side)
    assert grens[0]["kills"] == 0


def test_he_damage_lands_on_the_he_that_caused_it():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        hegrenade_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[{"tick": 2000, "attacker_steamid": ALICE,
                      "user_steamid": ENEMY, "weapon": "hegrenade",
                      "dmg_health": 43}],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(grens, [], parser, round_of, tainted, side)
    assert grens[0]["damage"] == 43


def test_damage_to_your_own_side_is_not_credited_to_the_grenade():
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        hegrenade_detonate=[{"tick": 2000, "user_steamid": ALICE,
                             "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[{"tick": 2000, "attacker_steamid": ALICE,
                      "user_steamid": BOB, "weapon": "hegrenade",
                      "dmg_health": 43}],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(grens, [], parser, round_of, tainted, side)
    assert grens[0]["damage"] == 0


def test_molotov_damage_is_claimed_across_the_whole_burn():
    """A fire keeps burning long after the grenade that started it landed."""
    parser, round_of, tainted, fz, end, side, credit, got = _fixture(
        inferno_startburn=[{"tick": 2000, "user_steamid": ALICE,
                            "entityid": 1, "x": 0.0, "y": 0.0, "z": 0.0}],
        inferno_expire=[{"tick": 2000 + int(7 * TICK), "entityid": 1,
                         "user_steamid": ALICE, "x": 0.0, "y": 0.0, "z": 0.0}],
        player_hurt=[{"tick": 2000 + int(5 * TICK), "attacker_steamid": ALICE,
                      "user_steamid": ENEMY, "weapon": "inferno",
                      "dmg_health": 11}],
    )
    grens = parse_util.grenades(parser, round_of, tainted, fz, side)
    parse_util.attribute(grens, [], parser, round_of, tainted, side)
    assert grens[0]["damage"] == 11


# -------------------------------------------------------------------- unused

class InventoryParser(FakeParser):
    def __init__(self, inventory, **frames):
        super().__init__(**frames)
        self._inv = pd.DataFrame(inventory)

    def parse_ticks(self, props, ticks=None):
        return self._inv


def test_a_player_who_died_holding_grenades_is_counted():
    """Read an eighth of a second before the death, not on it.

    On the death tick CS2 has already emptied the inventory, so sampling there
    said every player in the corpus died holding nothing.
    """
    deaths = pd.DataFrame([{"tick": 3000, "user_steamid": ALICE,
                            "attacker_steamid": ENEMY}])
    parser = InventoryParser([
        {"tick": 1000, "steamid": ALICE,
         "inventory": ["AK-47", "Flashbang", "Smoke Grenade"]},
        {"tick": 3000 - parse_util.DEATH_LOOKBACK_TICKS, "steamid": ALICE,
         "inventory": ["AK-47", "Smoke Grenade"]},
        {"tick": 3000, "steamid": ALICE, "inventory": []},
    ])
    credited: dict = {}

    def credit(rn, sid, field, amount=1):
        credited[(rn, str(sid), field)] = credited.get((rn, str(sid), field), 0) + amount

    parse_util.unused(parser, {(1, ALICE): {}}, {1: 1000}, {1: 7000},
                      deaths, set(), credit)
    assert credited[(1, ALICE, "nades_start")] == 2
    assert credited[(1, ALICE, "nades_unused")] == 1


def test_a_survivor_who_kept_grenades_is_not_counted_as_wasting_them():
    """Carrying a smoke into the next round is not waste.

    Counting it made rounds the team WON look like the problem: rounds where
    somebody finished holding utility came back won 93% of the time.
    """
    parser = InventoryParser([
        {"tick": 1000, "steamid": ALICE,
         "inventory": ["AK-47", "Flashbang", "Smoke Grenade"]},
        {"tick": 7000, "steamid": ALICE,
         "inventory": ["AK-47", "Flashbang", "Smoke Grenade"]},
    ])
    credited: dict = {}

    def credit(rn, sid, field, amount=1):
        credited[(rn, str(sid), field)] = credited.get((rn, str(sid), field), 0) + amount

    parse_util.unused(parser, {(1, ALICE): {}}, {1: 1000}, {1: 7000},
                      pd.DataFrame([]), set(), credit)
    assert credited[(1, ALICE, "nades_start")] == 2
    assert (1, ALICE, "nades_unused") not in credited


def test_picking_up_a_dead_teammates_grenades_cannot_exceed_what_you_bought():
    deaths = pd.DataFrame([{"tick": 3000, "user_steamid": ALICE,
                            "attacker_steamid": ENEMY}])
    parser = InventoryParser([
        {"tick": 1000, "steamid": ALICE, "inventory": ["AK-47", "Flashbang"]},
        {"tick": 3000 - parse_util.DEATH_LOOKBACK_TICKS, "steamid": ALICE,
         "inventory": ["AK-47", "Flashbang", "Smoke Grenade",
                       "High Explosive Grenade"]},
    ])
    credited: dict = {}

    def credit(rn, sid, field, amount=1):
        credited[(rn, str(sid), field)] = credited.get((rn, str(sid), field), 0) + amount

    parse_util.unused(parser, {(1, ALICE): {}}, {1: 1000}, {1: 7000},
                      deaths, set(), credit)
    assert credited[(1, ALICE, "nades_unused")] == 1     # not 3


def test_a_demo_with_no_inventory_data_produces_nothing_rather_than_zeroes():
    """A parser that cannot answer must not be recorded as "bought nothing"."""
    credited: dict = {}

    def credit(rn, sid, field, amount=1):
        credited[(rn, str(sid), field)] = 1

    parse_util.unused(FakeParser(), {(1, ALICE): {}}, {1: 1000}, {1: 7000},
                      pd.DataFrame([]), set(), credit)
    assert credited == {}
