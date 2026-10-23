"""Demo → (rounds, events, players, positions).

VALIDATED against a real Valve matchmaking CS2 demo (de_dust2, patch 14176).
Every field name below was confirmed with --inspect rather than assumed.

Things that surprised the first draft, kept here because they will surprise you
too if you extend this:

  * There is NO `round_end` event in CS2 demos. The round events that exist
    (`round_officially_ended`, `round_freeze_end`, `round_prestart`,
    `round_poststart`) carry a `tick` column and nothing else — no winner, no
    reason. The winner lives in tick data as `round_win_status`.
  * `round_win_status` uses team numbers: 2 = T, 3 = CT. Same convention as
    `team_num`. It is only meaningful in the moment before the round is
    officially over, so we sample a couple of ticks before the end.
  * `player_death` carries no team column by default. Request it as a player
    prop and it comes back prefixed: `user_team_num`, `attacker_team_num`.
  * Events expose `total_rounds_played` directly when asked for, which is
    zero-indexed. Use it instead of mapping ticks to rounds by hand.
  * `total_rounds_played` has ALREADY INCREMENTED by the time you read it near
    `round_officially_ended`. Read the round number at the freeze-end tick
    instead, or every round is off by one relative to its own deaths.
  * `round_start_equip_value` at freeze-end is lagged by a round — it reports
    the previous round's buy. Use `current_equip_value` at freeze-end, which is
    what the players are actually holding as the round goes live.
  * `parse_ticks` returns `steamid` and `name` alongside whatever properties
    you ask for, so the freeze-end tick read that collects equipment also
    yields the round's roster for free — no second pass, no extra cost.
  * `player_hurt` carries `dmg_health` per hit with both steamids, which is
    where ADR comes from. Self-damage and team damage are excluded; counting
    them would flatter anyone who eats their own molotov. `dmg_health` is the
    RAW hit, not capped at the victim's health (an AWP on 30 HP reads ~110),
    so `_hurt_credits` tracks health per victim and caps each hit.
  * WARMUP ROUNDS SHARE AN OFFICIAL END. A FACEIT match began with three
    freeze-ends before the first `round_officially_ended`, every one of them
    reporting `total_rounds_played = 0`. Only the last freeze before a given
    end is the round that counted; the rest are warmup and produce duplicate
    round numbers if kept.
  * There is NO `bomb_planted` EVENT either. A real FACEIT match exposes only
    `bomb_dropped` and `bomb_pickup`, and `parse_event("bomb_planted")` comes
    back as an empty LIST rather than a dataframe — so it does not even have
    `.itertuples`. The plant lives in tick data as `is_bomb_planted`, found by
    scanning for the tick where it flips within each round.
  * `player_death` can carry NO VICTIM. On a real FACEIT match two of
    ninety-three deaths came back with `user_name` and `user_team_num` both
    NaN and a perfectly normal attacker — a player who disconnected. `int()`
    on that raises. The round gets dropped rather than the death, because
    skipping just the death leaves a dead player alive in the state series.
  * `total_rounds_played` on EVENTS lags across round boundaries. Two plants
    came back tagged to the same round because the counter had not ticked over
    yet. Do not use it to assign events to rounds — map by tick interval
    against the freeze-end boundaries, which is exact.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from . import economy, utility

TICK_RATE = 64.0
TEAM_T, TEAM_CT = 2, 3
WIN_STATUS_PROBE = 2      # ticks before round_officially_ended to read the winner

# There is no bomb_planted EVENT in a CS2 demo — see the note above. The plant
# is recovered by scanning the `is_bomb_planted` tick property for the moment it
# flips. 32 ticks is half a second, which is far finer than win probability
# needs and keeps the scan to a few thousand rows per match.
PLANT_SCAN_STEP = 32

# Positional sampling is on by default: measured on a real 22-round Premier
# demo it costs 0.5 seconds and 1.1MB, which is nothing, and it is the data
# Pattern Finder needs to exist. Set COUNTERPLAY_POSITIONS=0 to skip it.
WANT_POSITIONS = os.environ.get("COUNTERPLAY_POSITIONS", "1") != "0"

# Sniper kills, for role detection. Both AWP names appear across demo versions.
AWP_WEAPONS = {"awp", "ssg08"}

PLAYER_COLUMNS = ["match_id", "round_num", "steamid", "name", "tier", "side",
                  "kills", "deaths", "assists", "headshots", "damage",
                  "opening_kill", "opening_death", "awp_kills",
                  "util_damage", "flashes_thrown", "enemies_flashed",
                  "trade_kills", "traded_deaths",
                  "clutch_tried", "clutch_won", "clutch_vs", "multi_kills",
                  # Utility, read by counterplay.utility. Thrown and landed are
                  # kept apart, and so are the two things a flash can land on.
                  "teammates_flashed", "blind_enemy_secs", "blind_team_secs",
                  "flash_assists", "flash_kills",
                  "nades_thrown", "nades_start", "nades_unused",
                  "nades_value", "nades_wasted",
                  # Economy, read by the buy analysis. None on a demo that
                  # does not carry them, never 0: "had no money" and "we do
                  # not know" must not look the same.
                  "money_start", "spent", "equip_value", "loadout"]

# Weapons whose damage is utility damage rather than aim.
UTIL_WEAPONS = {"hegrenade", "molotov", "incgrenade", "inferno", "flashbang",
                "decoy", "smokegrenade"}

# How long after a teammate dies a kill still counts as trading them. Five
# seconds is the window coaches already use when they say "nobody traded him":
# long enough to cross a doorway, short enough that an unrelated kill half a
# minute later does not collect the credit.
TRADE_WINDOW_SECONDS = 5.0


def _sid(v):
    """A steamid as a string, or None. They arrive as floats often enough that
    str() alone yields '7.65611984e+16' and silently breaks every join."""
    if v is None or v != v:
        return None
    s = str(v)
    return s[:-2] if s.endswith(".0") else s


def _txt(v):
    return None if v is None or v != v else str(v)


def _flag(v):
    """A boolean field as 0/1, or None when the demo did not say."""
    return None if v is None or v != v else int(bool(v))


def _num(v, cast):
    return None if v is None or v != v else cast(v)


def inspect(path: str) -> None:
    """Print what this demo actually contains. Run before trusting anything."""
    from demoparser2 import DemoParser
    p = DemoParser(path)
    print("HEADER")
    for k, v in p.parse_header().items():
        print(f"  {k}: {v}")
    print("\nEVENTS AVAILABLE")
    print("  " + ", ".join(sorted(p.list_game_events())))
    for ev in ("round_officially_ended", "round_freeze_end", "player_death", "bomb_planted"):
        try:
            df = p.parse_event(ev)
            print(f"\n{ev}  ({len(df)} rows)\n  columns: {list(df.columns)}")
        except Exception as exc:
            print(f"\n{ev}: {exc}")


def _plant_ticks(parser, bounds) -> dict[int, int]:
    """Round number -> tick the bomb went down, for rounds where it did.

    There is no plant event to read, so this samples `is_bomb_planted` across
    each round and takes the first tick it is True.

    The flag is required to be False earlier in the same round before a True
    counts. Without that guard a plant left set at a round boundary would be
    reported as a plant at freeze-end, which is impossible and would put every
    round of that match into post-plant from the first second.
    """
    scan = []
    for start, end, _ in bounds:
        scan.extend(range(start, end + 1, PLANT_SCAN_STEP))
    if not scan:
        return {}
    df = parser.parse_ticks(["is_bomb_planted"], ticks=scan)
    if not hasattr(df, "groupby") or "is_bomb_planted" not in df.columns:
        return {}
    # a gamerules property: identical for every player on a given tick
    flags = df.groupby("tick")["is_bomb_planted"].first().sort_index()

    out: dict[int, int] = {}
    for start, end, rn in bounds:
        seg = flags[(flags.index >= start) & (flags.index <= end)]
        seen_false = False
        for tick, planted in seg.items():
            if not planted:
                seen_false = True
            elif seen_false:
                out[rn] = int(tick)
                break
    return out


def _hurt_credits(hurt, round_of, tainted, side_of):
    """(round, attacker, damage, weapon) for every hit that counts toward ADR.

    `dmg_health` is the raw hit, NOT what the victim lost: an AWP body shot on
    a player with 30 left reports about 110. Summed as it came, one
    player-round read 1,417 and ADR ran about a third high. So each victim's
    health is tracked through the round, starting at 100, and a hit is worth
    at most what they had before it.

    Every hit moves the victim's health, including the ones that earn nobody
    credit (world, self and team damage), or the next enemy hit would be
    capped against health the victim no longer had. `health` on the event is
    what is left after the hit; a demo without it falls back to subtracting.
    """
    health: dict[tuple[int, str], float] = {}
    rows = sorted(hurt.itertuples(index=False), key=lambda h: h.tick)
    for h in rows:
        rn = round_of(h.tick)
        if rn is None or rn in tainted:
            continue
        att, vic = getattr(h, "attacker_steamid", None), getattr(h, "user_steamid", None)
        raw = float(getattr(h, "dmg_health", 0) or 0)
        key = (rn, str(vic))
        before = health.get(key, 100.0)
        dmg = max(0.0, min(raw, before))
        after = getattr(h, "health", None)
        health[key] = (float(after) if after is not None and after == after
                       else before - dmg)
        if att is None or att != att or str(att) == str(vic):
            continue                      # world damage, or your own molotov
        if side_of.get((rn, str(att))) == side_of.get((rn, str(vic))):
            continue                      # team damage does not count as ADR
        yield rn, att, dmg, str(getattr(h, "weapon", "")).lower()


def _trades_and_clutches(deaths, round_of, tainted, roster, credit,
                         ct_won_by_round) -> None:
    """Trades, clutches and multi-kill rounds, all read off the death order.

    These need a round's deaths in sequence rather than in aggregate, which is
    why they are not folded into the main credit loop.

    A trade is: a teammate dies, and within TRADE_WINDOW_SECONDS someone on
    their side kills whoever killed them. Both halves are recorded — the
    avenger gets a trade kill, the dead player a traded death — because "we do
    not trade" and "I keep dying where nobody can trade me" are different
    problems with different fixes.

    A clutch is counted from the moment it starts, won or lost, so the
    denominator is every clutch attempted rather than only the ones that came
    off.
    """
    per_round: dict[int, list] = {}
    for d in deaths.itertuples(index=False):
        rn = round_of(d.tick)
        if rn is None or rn in tainted:
            continue
        per_round.setdefault(rn, []).append(d)

    for rn, ds in per_round.items():
        ds.sort(key=lambda x: x.tick)
        sides = {sid: r["side"] for (r_n, sid), r in roster.items() if r_n == rn}
        alive = {"ct": sum(1 for v in sides.values() if v == "ct"),
                 "t": sum(1 for v in sides.values() if v == "t")}
        kills_by: dict[str, int] = {}
        clutcher: dict[str, str | None] = {"ct": None, "t": None}
        dead_so_far: set[str] = set()

        for i, d in enumerate(ds):
            vic = str(getattr(d, "user_steamid", None))
            att = getattr(d, "attacker_steamid", None)
            att = str(att) if att is not None and att == att else None
            v_side = sides.get(vic)

            if att and att != vic and sides.get(att) and sides.get(att) != v_side:
                kills_by[att] = kills_by.get(att, 0) + 1
                # Did this kill trade a teammate who died moments ago?
                for e in reversed(ds[:i]):
                    if (d.tick - e.tick) / TICK_RATE > TRADE_WINDOW_SECONDS:
                        break
                    dead = str(getattr(e, "user_steamid", None))
                    killer = getattr(e, "attacker_steamid", None)
                    killer = str(killer) if killer is not None and killer == killer else None
                    # The trade test: the player just killed IS the one who
                    # killed the teammate, and the avenger is on the dead
                    # player's side. Comparing the two KILLERS instead — which
                    # this did at first — asks "did the same player get two
                    # kills", which is a different thing entirely and found one
                    # trade in a match that had fifty.
                    if killer is not None and killer == vic and                             sides.get(dead) == sides.get(att):
                        credit(rn, att, "trade_kills")
                        credit(rn, dead, "traded_deaths")
                        break

            if v_side in alive:
                dead_so_far.add(vic)
                alive[v_side] -= 1
                other = "t" if v_side == "ct" else "ct"
                if alive[v_side] == 1 and alive[other] >= 1 and clutcher[v_side] is None:
                    survivor = next((s for s, sd in sides.items()
                                     if sd == v_side and s not in dead_so_far), None)
                    if survivor is not None:
                        clutcher[v_side] = survivor
                        credit(rn, survivor, "clutch_tried")
                        credit(rn, survivor, "clutch_vs", alive[other])

        ct_won = ct_won_by_round.get(rn)
        if ct_won is not None:
            for side, sid in clutcher.items():
                if sid is not None and bool(ct_won) == (side == "ct"):
                    credit(rn, sid, "clutch_won")

        # A multi-kill round is two or more, the unit coaches talk in.
        for sid, n in kills_by.items():
            if n >= 2:
                credit(rn, sid, "multi_kills", 1)


def _money(v):
    """A dollar amount as an int, or None when the demo did not say."""
    if v is None or v != v:
        return None
    return int(v)


def _money_sum(a, b):
    """a + b in dollars, or None if the demo gave either as missing."""
    a, b = _money(a), _money(b)
    return None if a is None or b is None else a + b


def _economy(parser, roster, end_by_round) -> None:
    """What each player spent, per round.

    Money at the start of the round, equipment and the loadout at freeze-end
    are already on the roster row. Spending is read at the END of the round,
    not at freeze-end: buy time runs a few seconds past freeze-end, so a
    freeze-end read misses the late buys. `cash_spent_this_round` cannot grow
    after buy time and does not reset until the next round starts.

    A rifle bought for a teammate is in the BUYER's `spent` and the
    RECEIVER's `equip_value`; the two together are how a drop shows.

    Not read from `item_purchase`. On a real collegiate demo that event
    re-emitted purchases mid-round and missed others inside the buy window,
    so 107 of 240 player-rounds listed items that did not add up to what was
    spent. The tick props agreed with the team totals on every round.
    """
    ends = sorted({t - WIN_STATUS_PROBE for t in end_by_round.values()})
    end_round = {end_by_round[rn] - WIN_STATUS_PROBE: rn for rn in end_by_round}
    try:
        df = parser.parse_ticks(["cash_spent_this_round"], ticks=ends)
    except Exception:
        return
    if not hasattr(df, "itertuples") or "cash_spent_this_round" not in df.columns:
        return
    for r in df.itertuples(index=False):
        row = roster.get((end_round.get(int(r.tick)), str(r.steamid)))
        if row is not None:
            row["spent"] = _money(r.cash_spent_this_round)


def _ended_on_purpose(parser) -> bool | None:
    """Did the game show its end-of-match panel?

    The difference between a surrender and a truncated recording. Both stop
    before anyone reaches the win target, and only this event tells them apart.
    None when the demo carries no such event at all, in which case nothing is
    claimed either way.
    """
    try:
        df = parser.parse_event("cs_win_panel_match")
    except Exception:
        return None
    if not hasattr(df, "__len__"):
        return None
    return len(df) > 0


def _match_score(rounds, roster):
    """The real match score, by following the two teams through the side swap.

    Rounds won by side, summed over a match, is not a score: sides swap, so
    neither total belongs to a team. A real 28-round Inferno read "16-12" by
    side while the actual result was 15-13.

    The demo does carry team_rounds_total, but it is not safe to read: CS2
    reports it against whichever side a team currently occupies, the event
    fires twice per round, and the two rows disagree across a swap. Reading the
    last row gave four of these eleven matches a score that summed correctly
    and belonged to nobody.

    So the teams are followed instead. Team A is whoever started on CT. For
    each round, A is on CT if most of its players are — majority, so a
    substitution or a reconnect cannot flip a team's identity. That needs no
    event, no roster upload, and no guess about who is who.

    Returns (score_a, score_b, finished, a_started_ct=True).
    """
    if not len(rounds):
        return None, None, None

    first = min(r["round_num"] for r in rounds)
    team_a = {sid for (rn, sid), row in roster.items()
              if rn == first and row["side"] == "ct"}
    if not team_a:
        return None, None, None

    score_a = score_b = 0
    for r in rounds:
        rn = r["round_num"]
        on_ct = sum(1 for (r_n, sid), row in roster.items()
                    if r_n == rn and sid in team_a and row["side"] == "ct")
        on_t = sum(1 for (r_n, sid), row in roster.items()
                   if r_n == rn and sid in team_a and row["side"] == "t")
        if on_ct == on_t:
            continue                      # cannot tell; count it for neither
        a_is_ct = on_ct > on_t
        if bool(r["ct_won"]) == a_is_ct:
            score_a += 1
        else:
            score_b += 1

    # The FORMAT, read off the side swap rather than assumed.
    #
    # MR12 is first to 13 with the swap after round 12; MR15 is first to 16
    # with the swap after 15. Assuming MR12 everywhere marked a pile of pro
    # demos "finished" at scores MR12 cannot produce — 14-3, 14-5, 25-22 — and
    # a unit test caught it, which is the entire reason the test exists.
    #
    # The swap is observable: team A is CT for a run of rounds and then is not.
    swap = None
    prev = None
    for r in sorted(rounds, key=lambda q: q["round_num"]):
        rn = r["round_num"]
        on_ct = sum(1 for (r_n, sid), row in roster.items()
                    if r_n == rn and sid in team_a and row["side"] == "ct")
        on_t = sum(1 for (r_n, sid), row in roster.items()
                   if r_n == rn and sid in team_a and row["side"] == "t")
        if on_ct == on_t:
            continue
        now = on_ct > on_t
        if prev is not None and now != prev:
            swap = rn - 1
            break
        prev = now

    # A swap at 15 means MR15; anything else is treated as MR12, which is
    # every current competitive format.
    win_at = 16 if swap == 15 else 13
    ot_from = win_at - 1

    hi, lo = max(score_a, score_b), min(score_a, score_b)
    if hi >= win_at and lo < ot_from:
        finished = True
    else:
        target = win_at + 3
        while lo >= target - 3 and hi < target:
            target += 4
        finished = hi >= target
    return score_a, score_b, finished


def parse_demo(path: str, tier: str = "premier"):
    """Parse one demo into (rounds, events, players).

    `players` is one row per player per round: who they were, which side
    they were on that round, and what they did in it. Round-level rather
    than match-level because sides swap after round 12, so a match-level row
    cannot answer "how do they play as CT" — which is most of what a coach
    wants. Everything else aggregates up from it.

    `positions` maps round number to a packed blob of everyone's position
    through that round, sampled at 8 Hz. See counterplay/positions.py.

    `tier` labels which population this match came from: pro, collegiate,
    league, or premier. The model conditions on it, so getting it right
    matters — a pro match labelled premier teaches the model that Premier
    players retake like professionals.
    """
    from demoparser2 import DemoParser

    parser = DemoParser(path)
    header = parser.parse_header()
    map_name = header.get("map_name", "unknown")
    match_id = Path(path).stem

    def ticks_of(event_name: str) -> list[int]:
        """Sorted distinct ticks for an event, or [] if the demo has none.

        demoparser2 returns an empty LIST rather than an empty dataframe when an
        event never fires, so subscripting it by column name raises TypeError.
        A truncated recording — the `part1` files in a split broadcast — has no
        `round_officially_ended` at all and used to crash here.
        """
        got = parser.parse_event(event_name)
        if not hasattr(got, "columns") or "tick" not in getattr(got, "columns", ()):
            return []
        return sorted(set(got["tick"].tolist()))

    freeze = ticks_of("round_freeze_end")
    ends = ticks_of("round_officially_ended")
    if not freeze or not ends:
        raise ValueError(
            "no round boundaries found — this is usually a partial recording "
            "(a 'part1' file from a split broadcast) rather than a bad parser")

    # Round number and equipment both come from the freeze-end tick.
    eq = parser.parse_ticks(["team_num", "current_equip_value", "total_rounds_played",
                             "balance", "cash_spent_this_round", "inventory"],
                            ticks=freeze)

    # Winner is read just before the round is officially over.
    probe = [t - WIN_STATUS_PROBE for t in ends]
    snap = parser.parse_ticks(["round_win_status"], ticks=probe)
    win_by_probe = snap.groupby("tick")["round_win_status"].first().to_dict()

    # WARMUP. A real FACEIT demo opened with three freeze-ends (ticks 1280,
    # 4952, 7425) that all pointed at the SAME official end, all reporting
    # total_rounds_played = 0. They are warmup rounds: the match restarts, and
    # only the last freeze before a given end is the round that actually
    # counted. Keeping all three produced three rows numbered 1 and tripped the
    # duplicate-round check.
    #
    # So: group freeze-ends by the official end that follows them, and keep only
    # the last of each group.
    last_freeze_for_end: dict[int, int] = {}
    trailing: list[int] = []
    for t in freeze:
        after = [e for e in ends if e > t]
        if after:
            last_freeze_for_end[after[0]] = t      # later ticks overwrite earlier
        else:
            trailing.append(t)
    freeze = sorted(last_freeze_for_end.values())

    # THE DECIDING ROUND.
    #
    # CS2 stops recording the moment a match is won, so the round that won it
    # never gets a `round_officially_ended`. Requiring one silently dropped the
    # last round of every match: eleven Premier demos all "ended" at match
    # point — 12-9, 12-7, 12-11, 12-4 — which is not a coincidence, it is the
    # deciding round missing from all of them. The most important round of the
    # match was the one round never analysed.
    #
    # So the final freeze-end is kept and closed at the last tick the demo
    # still knows who is winning. If the recording really does cut mid-round,
    # round_win_status never resolves and the round is dropped as before.
    final_freeze = max(trailing) if trailing else None
    final_end = final_win = None
    if final_freeze is not None:
        # A round cannot run longer than 1:55 plus a 40-second bomb, so this
        # window covers any round without scanning the whole demo.
        probe_ticks = list(range(final_freeze, final_freeze + 12000, 320))
        try:
            tail = parser.parse_ticks(["round_win_status"], ticks=probe_ticks)
        except Exception:
            tail = None
        if tail is not None and hasattr(tail, "empty") and not tail.empty:
            decided = tail[tail["round_win_status"].isin([TEAM_CT, TEAM_T])]
            if not decided.empty:
                final_end = int(decided["tick"].max())
                final_win = int(decided.sort_values("tick")
                                ["round_win_status"].iloc[-1])
        if final_end is not None:
            freeze = sorted(freeze + [final_freeze])

    rounds = []
    freeze_by_round: dict[int, int] = {}
    end_by_round: dict[int, int] = {}
    rn = 0
    for start_tick in freeze:
        e = eq[eq["tick"] == start_tick]
        if e.empty:
            continue

        # the first official end after this freeze belongs to this round
        after = [t for t in ends if t > start_tick]
        if after:
            end_tick = after[0]
            win = win_by_probe.get(end_tick - WIN_STATUS_PROBE)
        elif start_tick == final_freeze and final_end is not None:
            end_tick, win = final_end, final_win   # the deciding round
        else:
            continue                                     # round never finished
        if win is None:
            continue

        # Number rounds by ORDER, not by total_rounds_played. That counter is
        # zero-based in a Valve matchmaking demo and one-based in the pro demos
        # tested here, so `trp + 1` produced rounds 2..23 on five of them and
        # tripped the contiguity check. The kept freezes are already sorted and
        # already collapsed to one per official end, so counting them is exact
        # and depends on no counter at all.
        rn += 1
        freeze_by_round[rn] = start_tick
        end_by_round[rn] = end_tick
        rounds.append({
            "match_id": match_id, "round_num": rn, "map_name": map_name,
            "tier": tier,
            "equip_ct": float(e[e["team_num"] == TEAM_CT]["current_equip_value"].sum()),
            "equip_t": float(e[e["team_num"] == TEAM_T]["current_equip_value"].sum()),
            "ct_won": bool(int(win) == TEAM_CT),
        })

    rounds_df = pd.DataFrame(rounds).sort_values("round_num").reset_index(drop=True)
    ct_won_by_round = {r["round_num"]: r["ct_won"] for r in rounds}

    # --- roster ------------------------------------------------------------
    # Who was on which side, per round. Read from the same freeze-end tick as
    # the equipment above; parse_ticks hands back steamid and name whether or
    # not you ask for them.
    roster: dict[tuple[int, str], dict] = {}
    for rn, start_tick in freeze_by_round.items():
        for r in eq[eq["tick"] == start_tick].itertuples(index=False):
            sid = str(r.steamid)
            if not sid or sid == "nan":
                continue
            # A row at freeze-end with no team is someone not playing the round:
            # a spectator, a coach in the server, or a player still connecting.
            # They have no side, so they get no roster row and no denominator.
            if r.team_num is None or r.team_num != r.team_num:
                continue
            if int(r.team_num) not in (TEAM_CT, TEAM_T):
                continue                      # spectator slot
            roster[(rn, sid)] = {
                "match_id": match_id, "round_num": rn, "steamid": sid,
                "name": str(r.name), "tier": tier,
                "side": "ct" if int(r.team_num) == TEAM_CT else "t",
                "kills": 0, "deaths": 0, "assists": 0, "headshots": 0,
                "damage": 0.0, "opening_kill": 0, "opening_death": 0,
                "awp_kills": 0, "util_damage": 0.0, "flashes_thrown": 0,
                "enemies_flashed": 0, "trade_kills": 0, "traded_deaths": 0,
                "clutch_tried": 0, "clutch_won": 0, "clutch_vs": 0,
                "multi_kills": 0,
                "teammates_flashed": 0, "blind_enemy_secs": 0.0,
                "blind_team_secs": 0.0, "flash_assists": 0, "flash_kills": 0,
                "nades_thrown": 0, "nades_start": 0, "nades_unused": 0,
                "nades_value": 0, "nades_wasted": 0,
                # What they had before buying: what is left plus what went.
                # Not `start_balance`, which is not updated when overtime
                # resets everyone's money, so it read $3,700 at the start of
                # every overtime on 32 of 253 matches. Nobody earns anything
                # in freeze time, so the sum is exact.
                "money_start": _money_sum(getattr(r, "balance", None),
                                          getattr(r, "cash_spent_this_round", None)),
                "spent": None,
                "equip_value": _money(r.current_equip_value),
                "loadout": economy.loadout(getattr(r, "inventory", None)),
            }

    # --- events -----------------------------------------------------------
    deaths = parser.parse_event("player_death", player=["team_num"])
    if not hasattr(deaths, "itertuples"):
        raise ValueError("no player_death rows — run --inspect")

    # Exact tick -> round mapping. Rounds are CLOSED intervals: a round runs
    # from its freeze-end to its official end, and the gap between one round's
    # end and the next freeze-end belongs to neither. Kills land in that gap
    # constantly — players keep shooting after the round is decided — and
    # attributing them to the round that just finished puts six deaths on a
    # five-player side.
    bounds = sorted((freeze_by_round[rn], end_by_round[rn], rn)
                    for rn in freeze_by_round)

    def round_of(tick: int):
        for start, end, rn in bounds:
            if start <= tick <= end:
                return rn
        return None

    events = []
    tainted: set[int] = set()

    def emit(tick, etype, victim_side=None, **extra):
        rn = round_of(tick)
        if rn is None:
            return                                # before the first round: warmup
        st = freeze_by_round[rn]
        row = {"match_id": match_id, "round_num": rn,
               "seconds": max(0.0, (tick - st) / TICK_RATE),
               "type": etype, "victim_side": victim_side,
               "victim_steamid": None, "victim_name": None,
               "attacker_steamid": None, "attacker_name": None,
               "headshot": 0, "weapon": None}
        row.update(extra)
        events.append(row)

    for d in deaths.itertuples(index=False):
        # A real FACEIT demo turned up deaths with NO VICTIM: user_name and
        # user_team_num both NaN, attacker named normally. Two of ninety-three,
        # and they crashed int(). It is almost certainly a player who
        # disconnected — the entity was gone by the time the parser resolved it.
        #
        # We cannot say which side lost a player, and skipping the death alone
        # would leave that player alive for the rest of the round: the state
        # series would show a 5v4 that was really a 4v4, and the model would
        # train on it without complaint. So the whole ROUND is dropped. Losing
        # one round is cheap; silently keeping a wrong one is not.
        side_num = getattr(d, "user_team_num", None)
        if side_num is None or side_num != side_num:      # NaN is not equal to itself
            rn = round_of(d.tick)
            if rn is not None:
                tainted.add(rn)
            continue
        att = getattr(d, "attacker_steamid", None)
        emit(d.tick, "death", "ct" if int(side_num) == TEAM_CT else "t",
             victim_steamid=_sid(getattr(d, "user_steamid", None)),
             victim_name=_txt(getattr(d, "user_name", None)),
             attacker_steamid=_sid(att),
             attacker_name=_txt(getattr(d, "attacker_name", None)),
             headshot=int(bool(getattr(d, "headshot", False))),
             weapon=_txt(getattr(d, "weapon", None)),
             thrusmoke=_flag(getattr(d, "thrusmoke", None)),
             penetrated=_num(getattr(d, "penetrated", None), int),
             distance=_num(getattr(d, "distance", None), float),
             attacker_blind=_flag(getattr(d, "attackerblind", None)))

    for rn, tick in _plant_ticks(parser, bounds).items():
        emit(tick, "plant")

    # --- credit each player what they did ----------------------------------
    def credit(rn: int, sid, field: str, amount=1):
        """Add to a player's row for a round, if they were on the server for it.

        A steamid with no roster row is someone who was not at that round's
        freeze-end — a late joiner, or a coach in the server. Dropping them is
        correct: a player with no round to their name has no denominator, and
        every rate downstream would divide by zero.
        """
        if sid is None or sid != sid:
            return
        row = roster.get((rn, str(sid)))
        if row is not None:
            row[field] += amount

    first_seen: set[int] = set()
    for d in deaths.itertuples(index=False):
        rn = round_of(d.tick)
        if rn is None or rn in tainted:
            continue
        victim = getattr(d, "user_steamid", None)
        attacker = getattr(d, "attacker_steamid", None)
        credit(rn, victim, "deaths")
        # A player cannot kill themselves for credit, and world deaths (falling)
        # have no attacker at all.
        if attacker is not None and attacker == attacker and str(attacker) != str(victim):
            credit(rn, attacker, "kills")
            if bool(getattr(d, "headshot", False)):
                credit(rn, attacker, "headshots")
            if str(getattr(d, "weapon", "")).lower() in AWP_WEAPONS:
                credit(rn, attacker, "awp_kills")
        assister = getattr(d, "assister_steamid", None)
        if assister is not None and assister == assister:
            credit(rn, assister, "assists")
        # The opening duel: the first death of the round, whoever won it.
        if rn not in first_seen:
            first_seen.add(rn)
            credit(rn, victim, "opening_death")
            if attacker is not None and attacker == attacker:
                credit(rn, attacker, "opening_kill")

    # --- damage, for ADR ----------------------------------------------------
    try:
        hurt = parser.parse_event("player_hurt")
    except Exception:
        hurt = None
    # Which side each player was on, per round. Hoisted out of the damage loop
    # because utility needs it too, and a demo with no player_hurt rows used to
    # leave it undefined.
    side_of = {(rn, sid): r["side"] for (rn, sid), r in roster.items()}
    if hasattr(hurt, "itertuples"):
        for rn, att, dmg, weapon in _hurt_credits(hurt, round_of, tainted, side_of):
            credit(rn, att, "damage", dmg)
            # Utility damage is a SUBSET of damage, not a separate total: a
            # nade doing 60 counts once toward ADR and once here, so the two
            # stay comparable without anything being counted twice.
            if weapon in UTIL_WEAPONS:
                credit(rn, att, "util_damage", dmg)

    # --- utility -----------------------------------------------------------
    #
    # Grenades first, because the flash rows are the ones every other utility
    # number is drawn from. Each of these degrades on its own: a demo missing
    # an event loses that measure and nothing else.
    grenade_rows = utility.grenades(parser, round_of, tainted,
                                    freeze_by_round, side_of)
    for g in grenade_rows:
        credit(g["round_num"], g["steamid"], "nades_thrown")
        if g["kind"] == "flash":
            credit(g["round_num"], g["steamid"], "flashes_thrown")
    blind_rows = utility.blinds(parser, round_of, tainted, freeze_by_round,
                                side_of, deaths, credit)
    # Which grenade did what. One flashbang blinds everyone who can see it, so
    # counting blind events as "flashes that landed" doubles the number.
    utility.attribute(grenade_rows, blind_rows, parser, round_of, tainted,
                      side_of)
    utility.unused(parser, roster, freeze_by_round, end_by_round, deaths,
                   tainted, credit)

    _trades_and_clutches(deaths, round_of, tainted, roster, credit, ct_won_by_round)

    _economy(parser, roster, end_by_round)

    if tainted:
        print(f"    dropped {len(tainted)} round(s) with an unattributable death: "
              f"{sorted(tainted)}")
        rounds_df = rounds_df[~rounds_df["round_num"].isin(tainted)].reset_index(drop=True)
        roster = {k: v for k, v in roster.items() if k[0] not in tainted}

    grenade_rows = [g for g in grenade_rows if g["round_num"] not in tainted]
    blind_rows = [b for b in blind_rows if b["round_num"] not in tainted]

    events_df = pd.DataFrame(events)
    # drop anything referencing a round we did not keep (warmup, aborted rounds,
    # and rounds tainted above)
    valid = set(rounds_df["round_num"])
    if len(events_df):
        events_df = events_df[events_df["round_num"].isin(valid)].reset_index(drop=True)

    players_df = pd.DataFrame(
        [r for (rn, _), r in sorted(roster.items()) if rn in valid],
        columns=PLAYER_COLUMNS)
    grenade_rows = [g for g in grenade_rows if g["round_num"] in valid]
    blind_rows = [b for b in blind_rows if b["round_num"] in valid]

    # Positions last: it is the only step that can be skipped, and skipping it
    # must not change anything above.
    position_blobs: dict[int, bytes] = {}
    if WANT_POSITIONS:
        from . import positions as _positions
        kept = [(st, en_, rn) for st, en_, rn in bounds if rn in valid]
        try:
            position_blobs = _positions.extract(parser, kept)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            # Positions are an enrichment. A demo that parses into good rounds
            # and events is still worth keeping if only this part fails.
            print(f"    positions unavailable: {type(exc).__name__}: {exc}")

    # The real match score, attached to the frame so it reaches the database
    # without changing this function's shape. score_a belongs to the team that
    # started on CT.
    kept_rounds = [r for r in rounds if r["round_num"] in valid]
    a, b, decided = _match_score(kept_rounds, roster)
    concluded = _ended_on_purpose(parser)
    if decided:
        reason = "normal"
    elif concluded:
        # The game showed its end-of-match panel with nobody at the target, so
        # somebody conceded. In Premier that is a surrender vote.
        reason = "surrender"
    elif concluded is False:
        reason = "cut"
    else:
        reason = None
    rounds_df.attrs["final_ct"] = a
    rounds_df.attrs["final_t"] = b
    # "Finished" now means the match ended, however it ended — a surrender is a
    # finished match, just a short one.
    rounds_df.attrs["finished"] = (None if reason is None
                                   else int(reason in ("normal", "surrender")))
    rounds_df.attrs["end_reason"] = reason

    return (rounds_df, events_df, players_df, position_blobs,
            {"grenades": grenade_rows, "blinds": blind_rows})


def parse_directory(directory: str, tier: str = "premier"):
    """Parse every .dem in a directory. Keep one tier per directory —
    demos/pro/, demos/collegiate/, demos/league/, demos/premier/ — so the
    label is structural rather than something you have to remember."""
    all_r, all_e, all_p = [], [], []
    for dem in sorted(Path(directory).glob("*.dem")):
        try:
            r, e, pl, _pos, _util = parse_demo(str(dem), tier=tier)
            all_r.append(r); all_e.append(e); all_p.append(pl)
            print(f"  parsed {dem.name}: {len(r)} rounds, {len(e)} events, "
                  f"{pl['steamid'].nunique() if len(pl) else 0} players")
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            # demoparser2 is Rust: a malformed demo panics rather than raising,
            # and a panic is a BaseException. One bad file must not end the run.
            print(f"  SKIPPED {dem.name}: {type(exc).__name__}: {exc}")
    if not all_r:
        raise SystemExit("no demos parsed")
    return (pd.concat(all_r, ignore_index=True),
            pd.concat(all_e, ignore_index=True),
            pd.concat(all_p, ignore_index=True) if all_p else pd.DataFrame(columns=PLAYER_COLUMNS))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", type=str)
    a = ap.parse_args()
    if a.inspect:
        inspect(a.inspect)
