"""Utility: what was thrown, where it landed, and what it did.

The parser read one utility fact — how many flashes a player threw, and how
many opponents each blinded. That is the smallest true thing you can say about
utility, and it left four questions a coach actually asks unanswered:

  * did the flash land on an enemy, or on your own entry?
  * did anybody die while blind, and was it your flash that blinded them?
  * did the molotov move anyone, or burn an empty corridor?
  * did you die holding the grenades you paid for?

All four are answerable from a CS2 demo. This module reads them.

WHAT THE DEMO ACTUALLY CARRIES
------------------------------
`player_blind` is the good one: victim, thrower, blind duration in seconds,
and the tick. Everything about flashes follows from it, including the number
nobody tracks, which is how often a flash blinds your own side. Measured on a
real match: 85 flashes landed on somebody, and 37 of them landed on the
thrower's own team, most for over a second and a half.

Every grenade type detonates with an event carrying x, y, z and the thrower:
`flashbang_detonate`, `smokegrenade_detonate`, `hegrenade_detonate`,
`inferno_startburn` and `decoy_started`. Smokes and molotovs also carry an
expiry, so each one has a life as well as a place, which is what makes "was
anybody in there while it burned" a question with an answer.

WHAT IT DOES NOT CARRY, AND IS THEREFORE NOT CLAIMED
----------------------------------------------------
There is no event for an HE opening a hole in a smoke, so no such number is
produced. Nothing here estimates what a player could see. `assistedflash` on
`player_death` exists but is not used: on a match with five deaths off a flash
it fired once, because Valve's assist rules are narrower than the question.
The blind windows are cross-referenced against death ticks instead.
"""
from __future__ import annotations

# Inventory names, as CS2 writes them, to the kind we count.
NADE_ITEMS = {
    "Flashbang": "flash",
    "High Explosive Grenade": "he",
    "Smoke Grenade": "smoke",
    "Incendiary Grenade": "molotov",
    "Molotov": "molotov",
    "Decoy Grenade": "decoy",
}

# What each one costs to buy, in CS2. A grenade that dies in a hand cost this
# much and bought nothing, which is a sentence a coach can act on in a way that
# "you died holding 1.4 grenades" is not.
#
# The two fire grenades are not the same price: the CT incendiary is $600 and
# the T molotov is $400, so the inventory name is what sets the cost rather
# than the kind they both map to.
NADE_COST = {
    "Flashbang": 200,
    "High Explosive Grenade": 300,
    "Smoke Grenade": 300,
    "Molotov": 400,
    "Incendiary Grenade": 600,
    "Decoy Grenade": 50,
}

# How long a flash has to hold somebody before it counts as having blinded
# them.
#
# CS2 fires `player_blind` for anything at all, including the quarter second a
# player catches at the edge of a flash while turning away. Counting those the
# same as a full four-second blind put the season at "67% of your flashes blind
# your own side" against 62% blinding an opponent, which reads as a team that
# flashes itself more than the opposition. It is an artefact: half the own-side
# blinds were under a second while half the enemy blinds ran past three.
#
# 0.7s is the line because that is about where a blind stops being a flinch and
# starts being time somebody cannot fight through. It is one number and it is
# meant to be argued with, which is why every blind is still STORED with its
# duration; this only decides which ones are counted.
MIN_BLIND_SECONDS = 0.7

# How long after a blind ends a death still belongs to it.
#
# The window used to be the blind exactly: died while blind, or it did not
# count. That drew a line through the middle of one event. Across a season 30
# blinded opponents died inside the window and another 10 died to us within a
# second of it lifting, which is the same play: you flash, they turn away, it
# drops, and they are dead before they have found you again. Beyond a second or
# so the round has moved on and the flash is no longer why anybody died, so it
# stops there rather than running to the end of the round.
KILL_GRACE_SECONDS = 1.0


def blinding(duration) -> bool:
    """Did this blind last long enough to count as one."""
    return (duration or 0.0) >= MIN_BLIND_SECONDS


# The detonation event for each kind, and where it lands.
NADE_EVENTS = (
    ("flashbang_detonate", "flash"),
    ("smokegrenade_detonate", "smoke"),
    ("hegrenade_detonate", "he"),
    ("inferno_startburn", "molotov"),
    ("decoy_started", "decoy"),
)

# The matching expiry event, for the two kinds that occupy space over time.
EXPIRY_EVENTS = (
    ("smokegrenade_expired", "smoke"),
    ("inferno_expire", "molotov"),
)

TICK_RATE = 64.0

# A blind under this is a flicker: the screen whitens and the player keeps
# aiming. Recorded either way, but a coach asking "did the flash work" means
# the ones that took someone out of the round for a moment.
REAL_BLIND_SECONDS = 1.0

# An eighth of a second before the death tick. On the death tick itself CS2 has
# already emptied the player's inventory, so this is the last moment at which
# what they were carrying can be read.
DEATH_LOOKBACK_TICKS = 8


def _sid(v):
    """A steamid as a string, or None.

    The same rule as parse.py, and it has to be exactly the same rule or the
    join to the roster fails silently and every utility number reads zero.
    Never route one through float(): a 17-digit steamid does not survive
    float64, and 76561190000000101 comes back as a different number, which matches nothing.
    """
    if v is None or v != v:
        return None
    s = str(v)
    if s in ("", "nan", "None"):
        return None
    return s[:-2] if s.endswith(".0") else s


def _event(parser, name):
    """One event frame, or None. A demo missing an event is not an error."""
    try:
        df = parser.parse_event(name)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        # demoparser2 is Rust: a demo it cannot read this event out of panics
        # rather than raising, and a panic is a BaseException.
        return None
    return df if hasattr(df, "itertuples") and len(df) else None


def _lifetimes(parser):
    """(kind, entity id) -> the ticks at which that entity expired.

    Entity ids are reused within a match, so a detonation is matched to the
    FIRST expiry after it rather than to the id alone. Matching on the id
    without the tick gave one molotov two lifetimes and another none.
    """
    out: dict = {}
    for name, kind in EXPIRY_EVENTS:
        df = _event(parser, name)
        if df is None:
            continue
        for r in df.itertuples(index=False):
            eid = getattr(r, "entityid", None)
            if eid is None or eid != eid:
                continue
            out.setdefault((kind, int(eid)), []).append(int(r.tick))
    for key in out:
        out[key].sort()
    return out


def grenades(parser, round_of, tainted, freeze_by_round, side_of):
    """Every grenade that landed: kind, thrower, side, where and when.

    Positions are kept because "you smoke Top mid and then walk Mid" is a
    sentence about two places, and neither of them is in a count.
    """
    lives = _lifetimes(parser)
    rows = []
    for name, kind in NADE_EVENTS:
        df = _event(parser, name)
        if df is None:
            continue
        for g in df.itertuples(index=False):
            tick = int(g.tick)
            rn = round_of(tick)
            if rn is None or rn in tainted:
                continue
            sid = _sid(getattr(g, "user_steamid", None))
            if sid is None:
                continue
            life = None
            eid = getattr(g, "entityid", None)
            if eid is not None and eid == eid:
                after = [t for t in lives.get((kind, int(eid)), []) if t >= tick]
                if after:
                    life = (after[0] - tick) / TICK_RATE
            rows.append({
                "round_num": rn,
                "tick": tick,
                "seconds": max(0.0, (tick - freeze_by_round[rn]) / TICK_RATE),
                "kind": kind,
                "steamid": sid,
                "side": side_of.get((rn, sid)),
                "x": float(getattr(g, "x", 0.0) or 0.0),
                "y": float(getattr(g, "y", 0.0) or 0.0),
                "z": float(getattr(g, "z", 0.0) or 0.0),
                "life": life,
                # Filled in by attribute(), once the blinds and the damage are
                # known. A grenade that did nothing carries zeroes, which is
                # the whole point of counting per grenade rather than per blind.
                #
                # `kills` is the one that matters: an opponent this grenade
                # blinded who then died before it wore off. A flash that lands
                # is activity; a flash somebody dies behind is the reason to
                # throw it.
                "hit_enemy": 0, "hit_own": 0, "damage": 0.0, "kills": 0,
            })
    rows.sort(key=lambda r: (r["round_num"], r["seconds"]))
    return rows


# A blind is emitted on the same tick the flashbang detonates. A couple of
# ticks of slack costs nothing and survives a demo that rounds differently.
SAME_EVENT_TICKS = 4

# A molotov keeps burning after the thrower has moved on, so its damage is
# claimed over its whole life rather than at one tick.
INFERNO_SLACK_TICKS = 32


def attribute(grenade_rows, blind_rows, parser, round_of, tainted, side_of):
    """Say which grenade each blind and each point of utility damage came from.

    Blinds match on thrower and tick: one flashbang blinds everyone who can see
    it, and they are all emitted together. Damage matches on attacker, weapon
    and tick, which is exact for an HE and a window for a molotov, because a
    fire burns for seconds after the grenade that started it has landed.

    Anything that cannot be matched is left unattributed rather than assigned
    to the nearest candidate. A grenade credited with damage it did not do is
    worse than a grenade credited with none.
    """
    flashes = [g for g in grenade_rows if g["kind"] == "flash"]
    by_thrower: dict = {}
    for g in flashes:
        by_thrower.setdefault((g["round_num"], g["steamid"]), []).append(g)

    for b in blind_rows:
        cands = by_thrower.get((b["round_num"], b["thrower_steamid"]))
        if not cands:
            continue
        tick = b.get("tick")
        if tick is None:
            continue
        best = min(cands, key=lambda g: abs(g["tick"] - tick))
        if abs(best["tick"] - tick) > SAME_EVENT_TICKS:
            continue
        # A flash is credited with what it actually held somebody through.
        if not blinding(b.get("duration")):
            continue
        best["hit_own" if b["own_side"] else "hit_enemy"] += 1
        if not b["own_side"] and b.get("died_blind"):
            best["kills"] += 1

    # --- damage ----------------------------------------------------------
    df = _event(parser, "player_hurt")
    if df is None:
        return
    WEAPON_KIND = {"hegrenade": "he", "inferno": "molotov",
                   "molotov": "molotov", "incgrenade": "molotov",
                   "flashbang": "flash", "decoy": "decoy"}
    by_kind: dict = {}
    for g in grenade_rows:
        by_kind.setdefault((g["round_num"], g["steamid"], g["kind"]), []).append(g)

    for h in df.itertuples(index=False):
        kind = WEAPON_KIND.get(str(getattr(h, "weapon", "")).lower())
        if kind is None:
            continue
        tick = int(h.tick)
        rn = round_of(tick)
        if rn is None or rn in tainted:
            continue
        att = _sid(getattr(h, "attacker_steamid", None))
        vic = _sid(getattr(h, "user_steamid", None))
        if att is None or att == vic:
            continue                       # your own molotov, under your feet
        if side_of.get((rn, att)) == side_of.get((rn, vic)):
            continue                       # team damage is not what utility is for
        cands = by_kind.get((rn, att, kind))
        if not cands:
            continue
        dmg = float(getattr(h, "dmg_health", 0) or 0)
        if kind == "molotov":
            live = [g for g in cands
                    if g["tick"] - INFERNO_SLACK_TICKS <= tick
                    <= g["tick"] + (g["life"] or 7.0) * TICK_RATE + INFERNO_SLACK_TICKS]
            if not live:
                continue
            live[0]["damage"] += dmg
            continue
        best = min(cands, key=lambda g: abs(g["tick"] - tick))
        if abs(best["tick"] - tick) > SAME_EVENT_TICKS:
            continue
        best["damage"] += dmg


def blinds(parser, round_of, tainted, freeze_by_round, side_of, deaths, credit):
    """Every flash that blinded somebody, and whether they died for it.

    Own-side blinds are recorded alongside enemy ones rather than filtered out.
    They are not a failure to measure, they are the finding.
    """
    df = _event(parser, "player_blind")
    if df is None:
        return []

    # Death ticks per victim, so "died while blind" is a lookup rather than a
    # scan of the whole death frame per blind.
    died_at: dict = {}
    if deaths is not None and hasattr(deaths, "itertuples"):
        for d in deaths.itertuples(index=False):
            sid = _sid(getattr(d, "user_steamid", None))
            if sid is None:
                continue
            died_at.setdefault(sid, []).append(
                (int(d.tick), _sid(getattr(d, "attacker_steamid", None))))
    for sid in died_at:
        died_at[sid].sort()

    rows = []
    for b in df.itertuples(index=False):
        tick = int(b.tick)
        rn = round_of(tick)
        if rn is None or rn in tainted:
            continue
        victim = _sid(getattr(b, "user_steamid", None))
        thrower = _sid(getattr(b, "attacker_steamid", None))
        if victim is None or thrower is None:
            continue
        duration = float(getattr(b, "blind_duration", 0.0) or 0.0)
        v_side = side_of.get((rn, victim))
        t_side = side_of.get((rn, thrower))
        # Own side covers both a teammate and the thrower themselves. From a
        # coach's point of view they are the same mistake with the same fix.
        own = (v_side is not None and v_side == t_side) or victim == thrower

        # Did the blinded player die before it wore off, or in the second
        # after, and to whom?
        end = tick + (duration + KILL_GRACE_SECONDS) * TICK_RATE
        killer = None
        for d_tick, d_att in died_at.get(victim, ()):
            if tick <= d_tick <= end:
                killer = d_att
                break
        ours = (killer is not None and not own
                and side_of.get((rn, killer)) == t_side)

        rows.append({
            "round_num": rn,
            "tick": tick,
            "seconds": max(0.0, (tick - freeze_by_round[rn]) / TICK_RATE),
            "victim_steamid": victim, "victim_side": v_side,
            "thrower_steamid": thrower, "thrower_side": t_side,
            "duration": duration,
            "own_side": int(own),
            # A KILL THIS FLASH IS RESPONSIBLE FOR, which is narrower than "the
            # blinded player died". It has to be an opponent, and they have to
            # have died to one of the thrower's own side: a blinded teammate
            # who then dies is not a flash kill, and neither is an opponent who
            # falls or is killed by their own team while blind. This used to be
            # any death at all, which put a `died_blind` on 31 own-side blinds
            # in a season. Nothing read it, because every consumer checked
            # `own_side` first, but a column that means one thing and is named
            # for another is a bug waiting for its second reader.
            "died_blind": int(ours),
        })

        # The row is stored either way: a blind too short to count is still
        # something that happened, and keeping it means this threshold can be
        # moved later without parsing every demo again.
        if not blinding(duration):
            continue
        if own:
            credit(rn, thrower, "teammates_flashed")
            credit(rn, thrower, "blind_team_secs", duration)
            continue
        credit(rn, thrower, "enemies_flashed")
        credit(rn, thrower, "blind_enemy_secs", duration)
        if not ours:
            continue
        # The flash is credited to whoever threw it and the kill to whoever
        # took it, and they are usually not the same player. Crediting one
        # number to both is how a duo's work becomes one player's stat.
        credit(rn, thrower, "flash_assists")
        credit(rn, killer, "flash_kills")
    return rows


def unused(parser, roster, freeze_by_round, end_by_round, deaths, tainted, credit):
    """Grenades bought, and grenades still in hand on the player who died.

    Read from `inventory` at two ticks per player-round: freeze-end, which is
    everything they paid for, and just before the moment they died, which is
    everything they did not get to use.

    A PLAYER WHO SURVIVES THE ROUND CONTRIBUTES NOTHING HERE. Their grenades
    go into the next round, so they were not wasted; they were saved. An
    earlier version read survivors at the round end as well, and it made the
    number meaningless: rounds where somebody finished holding a flash were won
    93% of the time, because you keep your utility in rounds you are already
    winning. Carrying a smoke out is not waste. Dying with it is.

    This is the cheapest number in the module and close to the most useful. A
    team that dies holding two hundred grenades a season is not short of
    utility, it is short of the habit of throwing it.
    """
    want_ticks: set = set()
    for rn, tick in freeze_by_round.items():
        if rn not in tainted:
            want_ticks.add(int(tick))
    # The tick a player died on, and the tick their round ended on.
    death_tick: dict = {}
    if deaths is not None and hasattr(deaths, "itertuples"):
        for d in deaths.itertuples(index=False):
            sid = _sid(getattr(d, "user_steamid", None))
            if sid is None:
                continue
            death_tick.setdefault(sid, []).append(int(d.tick))
    for sid in death_tick:
        death_tick[sid].sort()
    # Read the inventory just BEFORE the death tick. On the tick a player dies
    # their inventory is already empty in the demo, so sampling at the death
    # itself says every player died holding nothing, which is how this number
    # first came back as a flat zero.
    for ticks in death_tick.values():
        want_ticks.update(t - DEATH_LOOKBACK_TICKS for t in ticks)
    if not want_ticks:
        return

    try:
        inv = parser.parse_ticks(["inventory"], ticks=sorted(want_ticks))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        print(f"    inventory unavailable: {type(exc).__name__}: {exc}")
        return

    held: dict = {}
    for r in inv.itertuples(index=False):
        sid = _sid(getattr(r, "steamid", None))
        if sid is None:
            continue
        items = getattr(r, "inventory", None)
        if items is None:
            continue
        names = [str(it) for it in items if str(it) in NADE_ITEMS]
        # Count and value both, because the count is the honest denominator
        # (a player with no grenades bought nothing) and the value is what a
        # coach can act on.
        held[(int(r.tick), sid)] = (len(names),
                                    sum(NADE_COST.get(n, 0) for n in names))

    for (rn, sid) in roster:
        if rn in tainted:
            continue
        bought = held.get((int(freeze_by_round[rn]), sid))
        if bought is None:
            continue
        start, start_value = bought
        if not start:
            continue
        credit(rn, sid, "nades_start", start)
        credit(rn, sid, "nades_value", start_value)
        # Unused means STILL IN THE HAND OF A PLAYER WHO DIED.
        #
        # The first cut also counted grenades a survivor finished the round
        # with, and that made the number meaningless: rounds where somebody
        # ended holding a flash were won 93% of the time, because you keep
        # your utility in rounds you were already winning. Carrying a smoke
        # into the next round is not waste. Dying with it is.
        lo, hi = int(freeze_by_round[rn]), int(end_by_round[rn])
        when = None
        for t in death_tick.get(sid, ()):
            if lo <= t <= hi:
                when = t
                break
        if when is None:
            continue                       # survived; the grenades keep
        remaining = held.get((when - DEATH_LOOKBACK_TICKS, sid))
        if remaining is None:
            continue
        left, left_value = remaining
        # Picking a dead teammate's grenades up off the floor is real, so a
        # player can die holding more than they started with. That is not
        # utility they failed to use, so both figures are capped at what they
        # actually bought.
        credit(rn, sid, "nades_unused", min(left, start))
        credit(rn, sid, "nades_wasted", min(left_value, start_value))
