"""What to do on Monday.

The product has been scrupulous about not over-claiming, and the cost of that
was a report that never landed a recommendation. "Your first death is in top
mid in 8 of 32 rounds and you win 1 of those 8" is one sentence away from "stop
taking that duel", and it never took the step.

This takes the step. It is not prediction and it is not a model — every line
here is a conclusion drawn from a fact the report already proved, and it prints
that fact underneath so a coach can disagree with the reasoning rather than
having to trust it.

HOW A RECOMMENDATION EARNS ITS PLACE
------------------------------------
Three tests, all of which have to pass:

  1. ENOUGH ROUNDS. Below MIN_ROUNDS it is an anecdote, and the product's whole
     credibility rests on refusing to dress anecdotes as findings.
  2. A GAP WORTH ACTING ON. The situation has to differ from this team's own
     baseline by at least MIN_GAP percentage points. Not from a professional
     benchmark, not from a league average — from what this same team does the
     rest of the time.
  3. SOMETHING TO ACTUALLY DO. If the honest advice is "keep doing that", it
     says so, and if no action follows from the finding, no line is produced.

ONE PLACE, ONE RECOMMENDATION
-----------------------------
The first version produced three separate items about Mirage's A main: the
group stalls there, and the first death happens there, and those are the same
sentence twice. Findings that share a map, a side and a place are now merged
into one item that says both things, because a coach running Monday's practice
runs one drill for one place.

Grouped by map on the way out, because practice is planned one map at a time
even though the ranking that decides what matters is global.
"""
from __future__ import annotations

from . import db, movement
from .report import _side_by_round, team_anchors, team_stats

# An anecdote below this. Deliberately higher than the reporting threshold: it
# is one thing to show a coach a count, another to tell them to change practice
# because of it.
MIN_ROUNDS = 8

# Percentage points from this team's own baseline before a difference is worth
# a Monday. Under ten points is inside the noise of a season this short.
MIN_GAP = 12.0

# Above this, a habit is working and the advice is to keep it — said out loud,
# because a report that only ever lists problems trains people to stop reading.
GOOD_GAP = 15.0

MAX_ITEMS = 8

# Utility thresholds. Deliberately not tuned against this season's own numbers:
# these are the points past which a coach would act, chosen before looking.
#
# A flash that blinds your own side happens to everybody. Half of them is a
# habit. Measured across eleven real Premier matches the figure was 67%, which
# is the reason this finding exists at all.
OWN_FLASH_LIMIT = 40.0

# Under a third of flashes blinding anybody means they are being thrown from
# the wrong place, not thrown badly.
LANDED_FLASH_FLOOR = 33.0

# A fifth of a season's grenades never leaving anyone's hand.
UNUSED_LIMIT = 20.0

# Below this many grenades, a percentage of them is noise. Same reasoning as
# MIN_ROUNDS, applied to a different denominator.
MIN_UTILITY = 30


def _pct(hit, of):
    return 100.0 * hit / of if of else 0.0


def _keep_copy(zone: str, side: str, share: float, rate: float,
               against: float, hit: int, of: int) -> str:
    """Why THIS hold is worth keeping, in terms specific to this hold.

    The first version emitted one sentence for every positive finding — "This
    is working. When two or more of you hold X at twelve seconds you win well
    above your own average" — three times on one page, word for word. Identical
    copy under different numbers reads as generated, which is the last thing
    the section a coach most needs to trust can afford.

    So the sentence is chosen from what actually distinguishes one hold from
    another: how often they set up this way, how far above their own normal it
    lands, and which side they were on. Two findings collide only if they match
    on all three, and then they are genuinely the same observation.
    """
    lead = round(rate - against)
    s = side.upper()

    if share >= 0.55:
        return (f"Your main {s} setup here and your best: {lead} points "
                f"above your other {s} rounds on this map. Keep it the "
                f"default when a round goes wrong early.")
    if share <= 0.30 and lead >= 35:
        return (f"Your strongest position on this map, used in only {hit} of "
                f"{of} rounds. Worth asking why it is the exception.")
    if share <= 0.30:
        return (f"Only {hit} of {of} {s} rounds start this way and they convert "
                f"{lead} points better. Small sample, clear direction.")
    if lead >= 30:
        return (f"The widest gap on this map, in your favour. Your other {s} "
                f"rounds are not getting whatever the read is here.")
    return (f"Holding {zone} converts {lead} points better than your other "
            f"{s} rounds here. Worth keeping as the default rather than "
            f"drifting off it.")


def monday(team_id: int) -> dict:
    """Recommendations, strongest first, each carrying the count behind it.

    Returns {"baseline", "items", "by_map"} — the flat ranked list and the same
    items bucketed by map, because the ranking answers "what matters most" and
    the buckets answer "what do we run on Tuesday".
    """
    st = team_stats(team_id)
    if st is None:
        return {"baseline": 0.0, "items": [], "by_map": []}

    you = st["you"]
    baseline = _pct(you["won"], you["rounds"]) if you["rounds"] else 0.0
    if not baseline:
        return {"baseline": 0.0, "items": [], "by_map": []}

    raw: list[dict] = []

    def add(do, because, evidence, hit, of, *, mp=None, side=None, zone=None,
            good=False, stake=None, foot=None, against=None):
        # `against` is the rate this finding should be read against when the
        # season baseline is the wrong thing: a place is compared with the
        # same map and side without it, not with a season that is mostly
        # other maps.
        rate = _pct(hit, of)
        gap = rate - (baseline if against is None else against)
        raw.append({
            # The line under each card. Every finding except the utility ones
            # is a share of ROUNDS against the team's round win rate, so the
            # default sentence is true of them and of nothing else. A finding
            # counted in flashes or in dollars supplies its own, because
            # "a gap of 19 points across 745200 rounds" is not a sentence.
            "foot": foot,
            "do": do, "because": because, "evidence": [evidence],
            "hit": hit, "of": of, "rate": rate, "gap": gap,
            "map": (mp or "").replace("de_", ""), "side": side, "zone": zone,
            "good": good,
            # Rounds at stake: how far off normal, times how many rounds it
            # covers. A big gap over few rounds and a small gap over many are
            # both real; this weighs them the way a coach would.
            #
            # `of` is rounds for every finding EXCEPT the utility ones, where
            # it is grenades. Those pass their own stake, measured in the
            # rounds the habit actually appeared in, so a season of 374
            # flashes cannot outrank a season of 120 rounds by counting a
            # different thing.
            "stake": abs(gap) / 100.0 * of if stake is None else stake,
        })

    # ---------------------------------------------------------------- position
    for p in movement.positional_patterns(team_id):
        # Rounds on BOTH sides of the comparison. Without the second test a
        # place covering 24 of 26 rounds could earn a card off a two-round
        # comparison group.
        if (p["of"] < MIN_ROUNDS or p["hit"] < MIN_ROUNDS
                or p["other"] < MIN_ROUNDS):
            continue
        rate = _pct(p["won"], p["hit"])
        gap = p["gap"]          # against the same map and side, not the season
        mp_short = p["map"].replace("de_", "")
        side = p["side"].upper()
        share = p["hit"] / p["of"] if p["of"] else 0
        # Rounds the difference is worth, measured in the smaller of the two
        # groups: a gap is only as solid as the thinner side of it.
        pstake = abs(gap) / 100.0 * min(p["hit"], p["other"])
        pfoot = (f"{rate:.0f}% in those {p['hit']} rounds against "
                 f"{p['other_pct']:.0f}% in your other {p['other']} "
                 f"{side} rounds on {mp_short}")

        if p["kind"] == "death" and gap <= -MIN_GAP:
            add(f"Change how you take {p['zone']}",
                f"When your first death is in {p['zone']}, the round is "
                f"usually gone. This often, it is the same duel taken the same "
                f"way, not bad luck.",
                f"First death in {p['zone']} in {p['hit']} of {p['of']} {side} "
                f"rounds; you win {p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"],
                stake=pstake, foot=pfoot, against=p["other_pct"])

        elif p["kind"] == "commit" and gap <= -MIN_GAP:
            add(f"Your {side} opening stops at {p['zone']}",
                f"When {p['zone']} is as far as three of you get together, "
                f"you lose most of those rounds. Either the space past it needs "
                f"utility, or the group should not be there.",
                f"Group gets no further than {p['zone']} in {p['hit']} of "
                f"the {p['of']} {side} rounds where three of you grouped up "
                f"at all; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"],
                stake=pstake, foot=pfoot, against=p["other_pct"])

        elif p["kind"] == "setup" and gap >= GOOD_GAP:
            add(f"Keep the {p['zone']} setup",
                _keep_copy(p["zone"], p["side"], share, rate,
                           p["other_pct"], p["hit"], p["of"]),
                f"Held in {p['hit']} of {p['of']} {side} rounds; you win "
                f"{p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"],
                good=True, stake=pstake, foot=pfoot, against=p["other_pct"])

        elif p["kind"] == "setup" and gap <= -MIN_GAP:
            add(f"Rethink the {p['zone']} default",
                "Your most common setup on this map and your worst. A "
                "default you keep losing from is a habit, not a plan.",
                f"Two or more of you here at twelve seconds in {p['hit']} of "
                f"{p['of']} {side} rounds; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"],
                stake=pstake, foot=pfoot, against=p["other_pct"])

    # ---------------------------------------------------------------- trades
    if you["opening_lost"] >= MIN_ROUNDS:
        if _pct(you["opening_saved"], you["opening_lost"]) - baseline <= -MIN_GAP:
            add("Practice trading the opening duel",
                "Losing the first duel is normal; losing the round nearly "
                "every time is not. Your second man is too far away to trade "
                "the kill. That is spacing, and you can drill it.",
                f"You win {you['opening_saved']} of {you['opening_lost']} rounds "
                f"after losing the opening duel",
                you["opening_saved"], you["opening_lost"])

    if you["opening_took"] >= MIN_ROUNDS:
        if _pct(you["opening_converted"], you["opening_took"]) - baseline <= -MIN_GAP:
            add("Close out the rounds you start ahead",
                "You win the first duel and lose the round more often than "
                "your own average. The problem is the twenty seconds after the "
                "kill, not the kill.",
                f"You win {you['opening_converted']} of {you['opening_took']} "
                f"rounds after winning the opening duel",
                you["opening_converted"], you["opening_took"])

    # ---------------------------------------------------------------- economy
    for kind, v in sorted(st["you_buys"].items()):
        if v["n"] < MIN_ROUNDS:
            continue
        rate = _pct(v["won"], v["n"])
        if kind == "full" and rate - baseline <= -MIN_GAP:
            add("Full buys are not converting",
                "The round you are most expected to win, and you win it "
                "below your own average. The most expensive place for a "
                "problem to be.",
                f"You win {v['won']} of {v['n']} full-buy rounds, against "
                f"{baseline:.0f}% overall", v["won"], v["n"])
        elif kind == "force" and rate < 20:
            add("Stop forcing, or force differently",
                "A force trades economy for tempo. At this rate you get "
                "neither. Either save properly or force with all five.",
                f"You win {v['won']} of {v['n']} force-buy rounds",
                v["won"], v["n"])

    # ---------------------------------------------------------------- maps
    for name, m in st["maps"].items():
        for side in ("ct", "t"):
            s = m.get(side) or {}
            if s.get("rounds", 0) < MIN_ROUNDS:
                continue
            if _pct(s["won"], s["rounds"]) - baseline <= -MIN_GAP:
                add(f"Your {side.upper()} side needs a rebuild",
                    "Your weakest side anywhere, by a distance. That is a "
                    "set of defaults to change, not a run of bad games.",
                    f"You win {s['won']} of {s['rounds']} {side.upper()} rounds "
                    f"on {name.replace('de_', '')}, against {baseline:.0f}% "
                    f"overall",
                    s["won"], s["rounds"], mp=name, side=side)

    # ---------------------------------------------------------------- utility
    #
    # Utility competes for the same eight slots as everything else rather than
    # getting a section of its own. If the team's flashes are fine it never
    # appears; if half of them blind their own entry it displaces a weaker
    # positional finding, which is the correct outcome either way.
    #
    # These are the only three that are worth a Monday. "You threw 340
    # grenades" is not advice, and a rate with no action attached is a
    # statistic pretending to be one.
    from . import utility as _utility
    splits = _utility.round_splits(team_id)

    def _round_stake(name):
        """Rounds at stake for a habit, measured in rounds it happened in."""
        hit, of = splits.get(name, (0, 0))
        if not of:
            return 0.0
        return abs(_pct(hit, of) - baseline) / 100.0 * of

    def _round_foot(name):
        """The footer for a finding counted in something other than rounds.

        Says what happened in the rounds the habit turned up in, which is the
        only claim about rounds these findings can honestly make.
        """
        hit, of = splits.get(name, (0, 0))
        if not of:
            return None
        return (f"You win {hit} of the {of} rounds it happens in "
                f"({_pct(hit, of):.0f}%), against {baseline:.0f}% overall")

    uf = _utility.flashes(team_id)
    if uf and uf["thrown"] >= MIN_UTILITY:
        own = _pct(uf["hit_own"], uf["thrown"])
        if own >= OWN_FLASH_LIMIT:
            # The headline is the whole own-side number, and the second
            # sentence takes it apart, because most of it is not the problem
            # the third sentence describes. A flash that blinds two defenders
            # and clips your entry on the way through worked. The one to drill
            # is the flash that blinded a teammate and nobody else.
            add("Fix who your flashes land on",
                f"{own:.0f}% of your flashes blind your own side. The "
                f"{uf['team_no_enemy']} that blind a teammate and no opponent "
                f"are the ones to drill: the site is still held and your entry "
                f"cannot see it.",
                f"{uf['hit_own']} of {uf['thrown']} flashes blinded your "
                f"own side: {uf['own_and_enemy']} also blinded an opponent, "
                f"{uf['team_no_enemy']} a teammate only, "
                f"{uf['self_no_enemy']} only the thrower",
                uf["hit_own"], uf["thrown"],
                stake=_round_stake("own_flash"),
                foot=_round_foot("own_flash"))
        landed = _pct(uf["hit_enemy"], uf["thrown"])
        if landed <= LANDED_FLASH_FLOOR:
            add("Your flashes are not landing on anybody",
                f"Only {landed:.0f}% of your flashes blind an opponent. "
                f"That is where and when they are thrown, not aim. Pick two "
                f"throws per map and drill them.",
                f"{uf['hit_enemy']} of {uf['thrown']} flashes blinded an "
                f"opponent; {uf['wasted']} blinded nobody at all",
                uf["hit_enemy"], uf["thrown"],
                stake=_round_stake("enemy_flash"),
                foot=_round_foot("enemy_flash"))

    uu = _utility.unused(team_id)
    if uu and uu["bought"] >= MIN_UTILITY:
        left = _pct(uu["wasted"], uu["spent"]) if uu["spent"] else 0.0
        if left >= UNUSED_LIMIT:
            add("You are dying with the utility still on you",
                f"${uu['per_round']:.0f} of grenades a round die in "
                f"somebody's hand, {left:.0f}% of what you spend on utility. "
                f"Usually a grenade saved for a moment the round never "
                f"reaches.",
                f"${uu['wasted']:,} of ${uu['spent']:,} of utility died in "
                f"its owner's hand, across {uu['rounds_holding']} rounds",
                uu["wasted"], uu["spent"],
                stake=_round_stake("died_holding"),
                foot=_round_foot("died_holding"))

    items = _merge_same_place(raw)
    items.sort(key=lambda x: -x["stake"])
    items = items[:MAX_ITEMS]

    # Bucketed by map for planning, keeping each bucket in ranked order.
    buckets: dict[str, list] = {}
    for it in items:
        buckets.setdefault(it["map"] or "", []).append(it)
    by_map = sorted(buckets.items(),
                    key=lambda kv: -max(x["stake"] for x in kv[1]))

    return {"baseline": baseline, "items": items, "by_map": by_map}


def _merge_same_place(raw: list[dict]) -> list[dict]:
    """One place, one recommendation.

    "Your T opening stops at A main" and "change how you take A main" are the
    same finding wearing two hats: the group stalls there, and that is where
    the first player dies. Reported separately they filled three of eight slots
    with one map's T side and pushed four other maps off the page.

    Merged, the item keeps the strongest framing and carries both counts, so
    nothing is lost except the repetition.
    """
    by_place: dict[tuple, list] = {}
    loose: list[dict] = []
    for it in raw:
        if it["zone"]:
            by_place.setdefault((it["map"], it["side"], it["zone"].lower()),
                                []).append(it)
        else:
            loose.append(it)

    out = list(loose)
    for group in by_place.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        # A positive and a negative finding about one place is not a
        # contradiction — the setup works and the entry into it does not — so
        # they stay separate rather than cancelling.
        good = [g for g in group if g["good"]]
        bad = [g for g in group if not g["good"]]
        for bucket in (good, bad):
            if not bucket:
                continue
            lead = max(bucket, key=lambda g: g["stake"])
            merged = dict(lead)
            merged["evidence"] = [e for g in bucket for e in g["evidence"]]
            if len(bucket) > 1:
                merged["stake"] = sum(g["stake"] for g in bucket)
            out.append(merged)
    return out


# ---- one match
#
# A match cannot support a claim about habits, and the old version of this knew
# that and then said almost nothing: two possible findings, both of the shape
# "N full buys went down, worth watching those rounds together", neither naming
# a round. A section titled "worth pulling up at practice" that does not say
# WHICH rounds to pull up has not done its job.
#
# So every finding below names its rounds, and every one is a thing that
# happened in this game rather than a rate dressed as one.

# A round lost from a man up is the most expensive kind there is, and the one
# most likely to be a habit rather than an accident.
MIN_THROWN = 2

# BUT A MAN UP HAS TO MEAN SOMETHING. Every opening kill puts a team one ahead
# for as long as it takes the other side to trade it, so counting any advantage
# at all gave the same eight rounds two different headings: lost from a man up,
# and took first blood and lost. An advantage is only a position a team was in
# if they were in it, so either it lasted long enough to play or it was bigger
# than one.
HELD_UP_SECONDS = 10.0
CLEAR_ADVANTAGE = 2

# Most of the rounds have to have gone badly before a repeated first death is
# worth the projector. Dying first in the same place and winning anyway is a
# trade working, not a default being read.
# A losing run shorter than this is a bad patch, not a collapse.
MIN_STREAK = 3
# First deaths in the same place, in one match.
MIN_SAME_PLACE = 3
MOSTLY_LOST = 0.6


def _alive_swings(match_key: str, sides: dict, ends: dict) -> dict:
    """Per round: the best man advantage this team held, and for how long.

    Read off the death events in time order. Five a side at freeze-end, then
    every death takes one off whichever side it belonged to; the running
    difference is the advantage. Both numbers matter and for different reasons:
    the size says how good the position was, the duration says whether it was a
    position at all or only the gap between an opening kill and the trade.
    """
    per: dict = {}
    by_round: dict = {}
    for e in db.query("""SELECT round_num, seconds, victim_side
                           FROM events
                          WHERE type = 'death' AND match_key = ?
                       ORDER BY round_num, seconds""", match_key):
        by_round.setdefault(e["round_num"], []).append(e)
    for rn, deaths in by_round.items():
        mine = sides.get((match_key, rn))
        if mine not in ("ct", "t"):
            continue
        us = them = 5
        best = 0
        held = 0.0
        last = deaths[0]["seconds"] if deaths else 0.0
        for d in deaths:
            # Credit the stretch that just ended to whatever the state was
            # during it, then apply this death.
            if us > 0 and them > 0 and us > them:
                held += max(0.0, d["seconds"] - last)
            last = d["seconds"]
            if d["victim_side"] == mine:
                us -= 1
            elif d["victim_side"]:
                them -= 1
            # 5v0 is a won round, not an advantage that was held and lost.
            if us > 0 and them > 0:
                best = max(best, us - them)
        # And the stretch from the last death to the end of the round.
        if us > 0 and them > 0 and us > them:
            held += max(0.0, ends.get(rn, last) - last)
        per[rn] = {"best": best, "held": held}
    return per


def for_match(match_key: str, team_id: int) -> list[dict]:
    """What THIS game says, with the rounds to watch.

    Not a set of recommendations: one match cannot earn those, and the season
    view is where coaching belongs. This is a list of the rounds worth the
    projector, and why each group of them is worth it.
    """
    from .report import build

    r = build(match_key)
    if r is None:
        return []
    sides = _side_by_round(team_id, team_anchors(team_id).get("anchors", {}))

    ours = []
    for row in r["rows"]:
        side = sides.get((match_key, row["round_num"]))
        if side not in ("ct", "t"):
            continue
        ours.append({
            "n": row["round_num"], "side": side,
            "won": bool(row["ct_won"]) == (side == "ct"),
            "buy": row["buy_ct"] if side == "ct" else row["buy_t"],
            "took_opening": bool(row["opening_loser"])
                            and row["opening_loser"] != side,
        })
    if not ours:
        return []
    ours.sort(key=lambda x: x["n"])
    won_of = {x["n"]: x["won"] for x in ours}
    lost_total = sum(1 for x in ours if not x["won"])
    out = []

    def add(do, because, evidence, rounds, good=False):
        if rounds:
            out.append({"do": do, "because": because, "evidence": evidence,
                        "rounds": sorted(rounds), "good": good})

    # ---- rounds given back from a man up
    ends = {row["round_num"]: (row["duration"] or 0.0) for row in r["rows"]}
    swings = _alive_swings(match_key, sides, ends)
    thrown = [x["n"] for x in ours if not x["won"]
              and (swings.get(x["n"], {}).get("held", 0) >= HELD_UP_SECONDS
                   or swings.get(x["n"], {}).get("best", 0) >= CLEAR_ADVANTAGE)]
    if len(thrown) >= MIN_THROWN:
        add(f"{len(thrown)} rounds lost from a man up",
            f"You were a player up for {int(HELD_UP_SECONDS)} seconds or "
            f"more, or up by two, and lost anyway. The most expensive shape a "
            f"round can take.",
            f"{len(thrown)} of the {lost_total} rounds you lost", thrown)

    # ---- the run that decided it
    best_run, run = [], []
    for x in ours:
        run = run + [x["n"]] if not x["won"] else []
        if len(run) > len(best_run):
            best_run = list(run)
    if len(best_run) >= MIN_STREAK:
        before = sum(1 for x in ours if x["n"] < best_run[0] and x["won"])
        DASH = "\u2013"
        add(f"{len(best_run)} rounds lost in a row",
            "Rarely that many separate problems. Watched back to back, the "
            "same read or the same economy hole usually turns up in all of "
            "them.",
            f"rounds {best_run[0]} to {best_run[-1]}, and the score went from "
            f"{before}{DASH}{best_run[0] - 1 - before} to "
            f"{before}{DASH}{best_run[-1] - before}", best_run)

    # ---- the advantage made and handed back
    gave_back = [x["n"] for x in ours if x["took_opening"] and not x["won"]]
    took = sum(1 for x in ours if x["took_opening"])
    # Only the rounds the finding above did not already cover. An opening kill
    # traded back immediately is this finding; one that was held is that one,
    # and a round printed under both headings says nothing twice.
    gave_back = [n for n in gave_back if n not in set(thrown)]
    if len(gave_back) >= MIN_THROWN and took:
        add(f"First blood taken and the round lost {len(gave_back)} times",
            "The advantage was made and given back in the same round. "
            "These are the clips that show what you do after an opening "
            "kill.",
            f"{took - len(gave_back)} of {took} converted", gave_back)

    # ---- the same place, over and over
    where = movement.match_positions(match_key, team_id) or {}
    by_place: dict = {}
    for q in where.get("rounds", []):
        if q.get("died_in"):
            by_place.setdefault((q["side"], q["died_in"]), []).append(q["round_num"])
    for (side, place), rounds in sorted(by_place.items(),
                                        key=lambda kv: -len(kv[1])):
        if len(rounds) >= MIN_SAME_PLACE:
            lost = [n for n in rounds if not won_of.get(n, True)]
            if len(lost) < MOSTLY_LOST * len(rounds):
                continue
            add(f"First death in {place} {len(rounds)} times as {side.upper()}",
                "The same spot, taken the same way. One is a duel; this "
                "many in a game is a default they had read.",
                f"{len(lost)} of those {len(rounds)} rounds lost", rounds)
            break

    # ---- and one thing that went right
    stolen = [x["n"] for x in ours if x["won"] and x["buy"] in ("eco", "force")]
    cheap = sum(1 for x in ours if x["buy"] in ("eco", "force"))
    if len(stolen) >= MIN_THROWN:
        add(f"{len(stolen)} rounds won on an eco or a force",
            "You were not expected to win these. Whatever you did is "
            "worth naming out loud and doing on purpose.",
            f"{len(stolen)} of {cheap} eco and force rounds", stolen, good=True)

    # Most rounds at stake first, and the good news last whatever its size.
    out.sort(key=lambda f: (f["good"], -len(f["rounds"])))
    return out
