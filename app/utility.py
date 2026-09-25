"""What your utility actually did, counted.

Three questions, three shapes of answer, all of them arithmetic:

  * FLASHES. Who they blinded, for how long, and whether anybody died for it.
    Read straight off the `blinds` table, one row per flash that landed.
  * UNUSED. Grenades bought and never thrown, per player per round. Read off
    `player_rounds`. The cheapest number here and close to the most useful.
  * SPACE. Whether a molotov moved anybody and whether an enemy walked through
    a smoke. Neither is an event: both are the grenade's landing point joined
    against the position samples for the round it landed in.

COUNTED, NOT MODELLED
---------------------
Same rule as everything else. "Denied space" is not a judgement here, it is
"an enemy was standing inside the radius when it landed, and outside it before
it burned out". Nothing estimates what a player could see, because a demo does
not record that, and no number here is a weighted score of the others.
"""
from __future__ import annotations

import numpy as np

from . import db, memo
from .report import _side_by_round, _team_match_keys, team_anchors
from counterplay.positions import FLAG_ALIVE, FLAG_CT, sample_seconds, unpack_round
# KILL_GRACE_SECONDS is imported to be RE-EXPORTED: the stats page prints the
# window in its own words ("within a second of it lifting") and reads the
# number from here rather than retyping it, so the sentence cannot drift from
# the constant it describes.
from counterplay.utility import (KILL_GRACE_SECONDS, MIN_BLIND_SECONDS,
                                 blinding)

# A CS2 molotov spreads to roughly 150 units. 220 is generous on purpose: the
# question is whether someone had to move, and a player standing 200 units from
# the edge of a fire in a corridor has to move.
MOLOTOV_RADIUS = 220.0

# A CS2 smoke's radius. 165 was here before and it was wrong twice over: the
# note beside it said 144 units ACROSS, which would put the radius at 72, and
# the constant it was justifying was 165. 144 is the radius.
SMOKE_RADIUS = 144.0

# And it blocks for 18 seconds.
#
# `smokegrenade_expired` is not that moment. Across 756 smokes it fires at a
# very tight 22.1 seconds after detonation, because it marks the end of the
# dissipation rather than the end of the cover. Trusting it gave every smoke
# four seconds of life it did not have, which is four more seconds for somebody
# to wander in and be counted as having walked through it.
SMOKE_LIFE = 18.0

# A molotov burns for about seven.
MOLOTOV_LIFE = 7.0

# Under this, an opponent was standing there as the smoke landed rather than
# walking into it afterwards. Two position samples at 8 Hz.
LANDED_ON_SECONDS = 0.25

# Two zones can share an x and y and be different floors. Nuke's bombsites sit
# 495 units apart vertically, so without this a molotov on the upper site would
# "deny space" to everybody standing on the lower one.
FLOOR_TOLERANCE = 120.0

# A grenade thrown in the last seconds of a round it was already going to win
# is not a habit worth counting against. Rounds are counted whole; this only
# bounds the position scan.
MAX_GRENADE_SECONDS = 115.0

# Below this many of a thing, a percentage is noise wearing a percent sign.
# Same floor as the rest of the report.
MIN_UTILITY = 8

# Position samples are 8 Hz, so eight of them is the first second: long enough
# for a molotov to spread, short enough that it is still "as it landed".
LANDING_SAMPLES = 8


def _match_keys(team_id):
    return _team_match_keys(team_id)


# ------------------------------------------------------------------ flashes

@memo.by_team
def by_kind(team_id: int) -> dict:
    """Every grenade this team threw, grouped by kind, with what it did.

    Per GRENADE, not per effect. One flashbang blinds everyone who can see it,
    so counting blind events as flashes that landed gave 731 landings from 356
    flashes. `hit_enemy` here is how many grenades blinded at least one
    opponent; `blinded` is how many opponents they blinded between them.
    """
    keys = _match_keys(team_id)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    rows = db.query(f"""SELECT match_key, round_num, kind, side,
                               hit_enemy, hit_own, damage, kills
                          FROM grenades WHERE match_key IN ({marks})""", *keys)
    out: dict = {}
    for r in rows:
        mine = sides.get((r["match_key"], r["round_num"]))
        if mine is None or r["side"] != mine:
            continue
        k = out.setdefault(r["kind"], {
            "thrown": 0, "hit_enemy": 0, "hit_own": 0, "hit_none": 0,
            "blinded": 0, "blinded_own": 0, "damage": 0.0, "did_damage": 0,
            "kills": 0, "got_a_kill": 0})
        k["thrown"] += 1
        k["blinded"] += r["hit_enemy"] or 0
        k["blinded_own"] += r["hit_own"] or 0
        k["hit_enemy"] += 1 if (r["hit_enemy"] or 0) else 0
        k["hit_own"] += 1 if (r["hit_own"] or 0) else 0
        if not (r["hit_enemy"] or 0) and not (r["hit_own"] or 0):
            k["hit_none"] += 1
        k["damage"] += r["damage"] or 0.0
        k["did_damage"] += 1 if (r["damage"] or 0) else 0
        k["kills"] += r["kills"] or 0
        k["got_a_kill"] += 1 if (r["kills"] or 0) else 0
    return out


@memo.by_team
def flashes(team_id: int) -> dict | None:
    """Every flash this team threw, and what it landed on.

    Own-side blinds sit beside enemy blinds rather than being filtered out of
    them. They are not a failure to measure, they are the finding.

    "Blinded" means held for at least `MIN_BLIND_SECONDS`. Everything shorter
    is in the `blinds` table and is not counted here, because a flash that
    catches somebody for a quarter second while they turn away is not the same
    event as one that holds them through a duel, and counting the two together
    made own-side flashes look like the majority of a team's utility.
    """
    kinds = by_kind(team_id)
    f = kinds.get("flash")
    if not f or not f["thrown"]:
        return None
    keys = _match_keys(team_id)
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    rows = db.query(f"""SELECT match_key, round_num, seconds, thrower_side,
                               own_side, duration, died_blind,
                               victim_steamid, thrower_steamid
                          FROM blinds WHERE match_key IN ({marks})""", *keys)
    enemy_secs = own_secs = kills = 0.0
    # People blinded, split three ways. The grenade rows say how many FLASHES
    # blinded their own side; only the blind rows can say whether "own side"
    # meant a teammate or the thrower's own screen, and those are different
    # mistakes with different fixes.
    blinded_team = blinded_self = 0
    # The blinds from one flashbang are emitted on the same tick, so grouping
    # on thrower and time reconstructs the flash. That is what lets this say
    # which flashes blinded an opponent AND their own side, and the difference
    # matters: a flash going through a doorway that catches your entry's edge
    # while taking two defenders' sight is not the same mistake as one that
    # blinded a teammate and nobody else.
    by_flash: dict = {}
    for b in rows:
        mine = sides.get((b["match_key"], b["round_num"]))
        if mine is None or b["thrower_side"] != mine:
            continue
        # The same threshold the flash counters were built with. Every blind is
        # stored, including the quarter second somebody catches at the edge of
        # one while turning away, and without this line the split here would
        # count more teammates blinded than there were flashes that blinded a
        # teammate.
        if not blinding(b["duration"]):
            continue
        fl = by_flash.setdefault(
            (b["match_key"], b["round_num"], b["thrower_steamid"], b["seconds"]),
            {"enemy": False, "team": False, "self": False})
        if b["own_side"]:
            fl["self" if b["victim_steamid"] == b["thrower_steamid"]
               else "team"] = True
        else:
            fl["enemy"] = True
        if b["own_side"]:
            own_secs += b["duration"] or 0.0
            if b["victim_steamid"] == b["thrower_steamid"]:
                blinded_self += 1
            else:
                blinded_team += 1
        else:
            enemy_secs += b["duration"] or 0.0
            kills += int(b["died_blind"] or 0)
    # The three ways an own-side flash goes, which are three different
    # conversations at practice.
    own_and_enemy = sum(1 for v in by_flash.values()
                        if v["enemy"] and (v["team"] or v["self"]))
    team_no_enemy = sum(1 for v in by_flash.values()
                        if v["team"] and not v["enemy"])
    self_no_enemy = sum(1 for v in by_flash.values()
                        if v["self"] and not v["team"] and not v["enemy"])
    return {
        "thrown": f["thrown"],
        # Of the flashes that blinded your own side: how many also blinded an
        # opponent (so the flash worked and clipped somebody on the way), how
        # many blinded a teammate and nobody else (the actual mistake), and how
        # many blinded only the thrower.
        "own_and_enemy": own_and_enemy,
        "team_no_enemy": team_no_enemy,
        "self_no_enemy": self_no_enemy,
        # The two that matter: how often a flash takes an opponent's sight,
        # and how often somebody dies behind it. The rest is context.
        "got_a_kill": f["got_a_kill"], "kills_from": f["kills"],
        "hit_enemy": f["hit_enemy"], "hit_own": f["hit_own"],
        "blinded": f["blinded"], "blinded_own": f["blinded_own"],
        "blinded_team": blinded_team, "blinded_self": blinded_self,
        "enemy_secs": enemy_secs, "own_secs": own_secs,
        "kills": int(kills),
        # A flash that blinded nobody at all. Not a mistake in the way an
        # own-side flash is, but not a flash that did anything either. Counted
        # from the grenade rows rather than subtracted from the other two,
        # because one flash can blind an enemy AND a teammate.
        "wasted": f["hit_none"],
    }


# ------------------------------------------------------------------- unused

@memo.by_team
def unused(team_id: int) -> dict | None:
    """Utility bought and never thrown, and the rounds people died holding it.

    Every kind, not only HE: the nades_* columns are named for grenades but
    carry flashes, smokes, mollies and decoys, which is why the dollar figure
    below is the honest unit and a count of "nades" would not be.

    `nades_start` doubles as the honest denominator: a demo parsed before this
    existed reads zero everywhere, and zero grenades bought is indistinguishable
    from no data in a sum. Rounds where nobody on the team is recorded as
    starting with anything are left out rather than counted as perfect.
    """
    keys = _match_keys(team_id)
    if not keys:
        return None
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    rows = db.query(f"""SELECT match_key, round_num, side, steamid,
                               nades_start, nades_thrown, nades_unused,
                               nades_value, nades_wasted
                          FROM player_rounds WHERE match_key IN ({marks})""", *keys)
    bought = thrown = left = 0
    spent = wasted = 0
    rounds = set()
    died_holding = set()
    for r in rows:
        mine = sides.get((r["match_key"], r["round_num"]))
        if mine is None or r["side"] != mine:
            continue
        if not r["nades_start"]:
            continue
        rounds.add((r["match_key"], r["round_num"]))
        bought += r["nades_start"]
        thrown += r["nades_thrown"] or 0
        left += r["nades_unused"] or 0
        spent += r["nades_value"] or 0
        wasted += r["nades_wasted"] or 0
        if (r["nades_unused"] or 0) > 0:
            died_holding.add((r["match_key"], r["round_num"]))
    if not rounds:
        return None
    return {"bought": bought, "thrown": thrown, "unused": left,
            "rounds": len(rounds), "rounds_holding": len(died_holding),
            # Dollars. A flashbang is $200 and a CT incendiary is $600, so
            # counting pieces treats a third of a rifle as the same waste as
            # a tenth of one.
            "spent": spent, "wasted": wasted,
            "per_round": wasted / len(rounds) if rounds else 0.0}


# -------------------------------------------------------------------- space

def _grenades_with_positions(team_id, kinds):
    """Every grenade of these kinds thrown by this team, with its round's samples."""
    keys = _match_keys(team_id)
    if not keys:
        return []
    marks = ",".join("?" * len(keys))
    marks_k = ",".join("?" * len(kinds))
    return db.query(f"""SELECT g.match_key, g.round_num, g.kind, g.seconds,
                               g.side, g.x, g.y, g.z, g.life, rp.data
                          FROM grenades g
                          JOIN round_positions rp
                            ON rp.match_key = g.match_key
                           AND rp.round_num = g.round_num
                         WHERE g.match_key IN ({marks})
                           AND g.kind IN ({marks_k})
                      ORDER BY g.match_key, g.round_num, g.seconds""",
                    *keys, *kinds)


def _enemy_mask(samples, mine: str):
    """Which columns are the OTHER side, per sample. Shape (n_samples, n_players)."""
    is_ct = (samples["flags"] & FLAG_CT) != 0
    return is_ct if mine == "t" else ~is_ct


@memo.by_team
def space(team_id: int) -> dict | None:
    """Did the molotov move anyone, and did an enemy walk through the smoke.

    For each grenade: take the position samples inside its life, keep the
    enemies who are alive, and measure their distance to where it landed. A
    molotov "moved someone" when an enemy is inside the radius as it lands and
    outside it before it burns out. A smoke was "crossed" when an enemy is
    inside the radius at any point while it is up, and a crossed smoke also
    carries HOW LONG it held the space first: the seconds from landing to the
    first opponent inside it. An opponent who was already standing there is
    counted apart, because a smoke thrown onto somebody is not the same event
    as a smoke somebody walked into.

    Neither says anything about intent, and neither is a score. A molotov that
    burned an empty corridor is reported as exactly that.
    """
    rows = _grenades_with_positions(team_id, ("molotov", "smoke"))
    if not rows:
        return None
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))

    out = {"molotovs": 0, "moved": 0, "empty": 0, "burned": 0, "denied": 0,
           "denied_secs": 0.0, "smokes": 0, "crossed": 0, "uncrossed": 0,
           "landed_on": 0, "entered": 0, "held_secs": 0.0}
    cache: dict = {}
    for g in rows:
        mine = sides.get((g["match_key"], g["round_num"]))
        if mine is None or g["side"] != mine:
            continue
        key = (g["match_key"], g["round_num"])
        if key not in cache:
            cache[key] = unpack_round(g["data"])
        unpacked = cache[key]
        if unpacked is None:
            continue
        meta, _ids, samples = unpacked
        secs = sample_seconds(meta)

        radius = MOLOTOV_RADIUS if g["kind"] == "molotov" else SMOKE_RADIUS
        # A grenade with no recorded expiry gets the kind's nominal life, so a
        # missing expiry event costs precision rather than dropping the row.
        # The game's own numbers rather than the expiry event. A molotov's
        # recorded life is real, because a fire goes out when the event says it
        # does; a smoke's is four seconds late, so the constant wins and the
        # recorded life only caps it when a round ended early.
        if g["kind"] == "molotov":
            life = g["life"] if g["life"] else MOLOTOV_LIFE
        else:
            life = min(g["life"], SMOKE_LIFE) if g["life"] else SMOKE_LIFE
        window = (secs >= g["seconds"]) & (secs <= g["seconds"] + life)
        if not window.any():
            continue

        block, t = samples[window], secs[window]
        alive = (block["flags"] & FLAG_ALIVE) != 0
        enemy = _enemy_mask(block, mine)
        near = (
            (block["x"].astype(np.float32) - g["x"]) ** 2
            + (block["y"].astype(np.float32) - g["y"]) ** 2
        ) <= radius ** 2
        near &= np.abs(block["z"].astype(np.float32) - g["z"]) <= FLOOR_TOLERANCE
        inside = near & alive & enemy

        if g["kind"] == "smoke":
            out["smokes"] += 1
            if not inside.any():
                out["uncrossed"] += 1
                continue
            out["crossed"] += 1
            # HOW LONG IT HELD THE SPACE. The seconds between the smoke landing
            # and the first opponent inside it, which is what a bare "somebody
            # crossed it" cannot say: a smoke they walked through at eleven
            # seconds did nearly its whole job and one they walked through at
            # two did not.
            when = float(t[inside.any(axis=1)][0] - g["seconds"])
            if when < LANDED_ON_SECONDS:
                # They were already standing there. A smoke thrown onto
                # somebody is a different thing from a smoke somebody walked
                # into, and it is often deliberate.
                out["landed_on"] += 1
            else:
                out["entered"] += 1
                out["held_secs"] += when
            continue

        out["molotovs"] += 1
        if not inside.any():
            out["empty"] += 1
            continue
        out["burned"] += 1
        # Ground an opponent could not stand on: the seconds, summed across
        # everyone the fire was actually on top of. A molotov that holds one
        # player off a site for six seconds has done more than one that
        # brushed three people for half a second each, and a count of
        # molotovs cannot tell those apart.
        step = float(secs[1] - secs[0]) if len(secs) > 1 else 0.125
        out["denied_secs"] += float(inside.sum()) * step
        # Somebody was in it. Did they get out before it went out?
        #
        # "In it" means in it AS IT LANDS, not at any point in its life:
        # walking into a fire that is already burning is the opponent ignoring
        # it, which is not the same as the fire moving them.
        #
        # And they have to be ALIVE at the end to have moved. A player who
        # burned to death in it has the alive bit cleared, so without this an
        # opponent dying in the fire read as an opponent who left it.
        landing = inside[:LANDING_SAMPLES].any(axis=0)
        alive_end = (block["flags"][-1] & FLAG_ALIVE) != 0
        if bool((landing & alive_end & ~inside[-1]).any()):
            out["moved"] += 1
        out["denied"] += 1
    return out


# ------------------------------------------------------------------ per team

@memo.by_team
def summary(team_id: int) -> dict | None:
    """The four numbers that go on the team page, and nothing else.

    Four, because the page is already long and a coach reading a utility strip
    wants to know whether their flashes work, whether they flash each other,
    whether their molotovs land on anybody, and whether they die holding the
    grenades they bought. Everything finer belongs on a player's own page.
    """
    f = flashes(team_id)
    u = unused(team_id)
    s = space(team_id)
    if not f or not f["thrown"]:
        return None
    return {"flashes": f, "unused": u, "space": s, "kinds": by_kind(team_id)}


# ------------------------------------------------------------- round patterns

@memo.by_team
def round_splits(team_id: int) -> dict:
    """Rounds grouped by what the team's utility did in them, with the outcome.

    Everything else in the product ranks a finding by rounds at stake, which
    only works if the denominator is rounds. "67% of your flashes blind your
    own side" has grenades underneath it, and treating 374 grenades as 374
    rounds would put utility above every other finding by arithmetic rather
    than by importance.

    So each utility finding also carries the ROUNDS it happened in and how
    those rounds went. That is a counted number, not a claim of cause: rounds
    where you blind your own entry are not necessarily lost because of it.
    """
    keys = _match_keys(team_id)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))
    won = {(r["match_key"], r["round_num"]): bool(r["ct_won"])
           for r in db.query(f"""SELECT match_key, round_num, ct_won FROM rounds
                                  WHERE match_key IN ({marks})""", *keys)}

    groups: dict = {"enemy_flash": set(), "own_flash": set(),
                    "died_holding": set()}
    for g in db.query(f"""SELECT match_key, round_num, side, hit_enemy, hit_own
                            FROM grenades
                           WHERE match_key IN ({marks}) AND kind = 'flash'""",
                      *keys):
        key = (g["match_key"], g["round_num"])
        if sides.get(key) != g["side"]:
            continue
        if g["hit_enemy"]:
            groups["enemy_flash"].add(key)
        if g["hit_own"]:
            groups["own_flash"].add(key)
    for r in db.query(f"""SELECT match_key, round_num, side FROM player_rounds
                           WHERE match_key IN ({marks}) AND nades_unused > 0""",
                      *keys):
        key = (r["match_key"], r["round_num"])
        if sides.get(key) == r["side"]:
            groups["died_holding"].add(key)

    out: dict = {}
    for name, rounds in groups.items():
        hit = of = 0
        for key in rounds:
            mine, ct_won = sides.get(key), won.get(key)
            if mine is None or ct_won is None:
                continue
            of += 1
            hit += int(ct_won if mine == "ct" else not ct_won)
        out[name] = (hit, of)
    return out


# Named, because the sample report prints this line too.
FLASH_ROUND_PATTERN = (
    "You win the round after blinding an opponent",
    "Rounds where one of your flashes blinded somebody on the other side.")


@memo.by_team
def round_patterns(team_id: int) -> list[tuple]:
    """Utility findings in the shape the Recurring patterns table already uses.

    (name, rounds won, rounds it applied to, explanation). One line, not a
    section: a coach reading down a column of win rates should not have to
    change units halfway to read about grenades.
    """
    hit, of = round_splits(team_id).get("enemy_flash", (0, 0))
    if not of:
        return []
    return [(FLASH_ROUND_PATTERN[0], hit, of, FLASH_ROUND_PATTERN[1])]
