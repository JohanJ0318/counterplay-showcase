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
               baseline: float, hit: int, of: int) -> str:
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
    lead = round(rate - baseline)
    s = side.upper()

    if share >= 0.55:
        return (f"This is your main {s} setup here and your best one: you take "
                f"{zone} in most rounds on this map and win {lead} points above "
                f"your own average from it. The thing to protect is that it stays "
                f"the default when a round goes wrong early.")
    if share <= 0.30 and lead >= 35:
        return (f"The strongest position you have on this map, and you use it in "
                f"{hit} rounds of {of}. A {lead}-point edge you take that rarely "
                f"is worth a conversation about why it is the exception.")
    if share <= 0.30:
        return (f"Only {hit} of your {of} {s} rounds start this way, and they "
                f"convert {lead} points better than the rest. Small sample, clear "
                f"direction, worth trying deliberately rather than by accident.")
    if lead >= 30:
        return (f"The widest gap on this map, and it is in your favour. Whatever "
                f"the read is when you hold {zone}, the rest of your {s} rounds "
                f"are not getting it.")
    return (f"Holding {zone} converts {lead} points better than your average "
            f"round. Steady rather than spectacular, and worth keeping as a "
            f"default rather than drifting off it.")


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
            good=False, stake=None, foot=None):
        rate = _pct(hit, of)
        gap = rate - baseline
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
        if p["of"] < MIN_ROUNDS or p["hit"] < MIN_ROUNDS:
            continue
        rate = _pct(p["won"], p["hit"])
        gap = rate - baseline
        mp_short = p["map"].replace("de_", "")
        side = p["side"].upper()
        share = p["hit"] / p["of"] if p["of"] else 0

        if p["kind"] == "death" and gap <= -MIN_GAP:
            add(f"Change how you take {p['zone']}",
                f"When the first of you dies in {p['zone']} as {side}, the round "
                f"is usually already gone. At that rate it is not bad luck. It "
                f"is the same duel taken the same way.",
                f"First death in {p['zone']} in {p['hit']} of {p['of']} {side} "
                f"rounds; you win {p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"])

        elif p["kind"] == "commit" and gap <= -MIN_GAP:
            add(f"Your {side} opening stops at {p['zone']}",
                f"When {p['zone']} is the furthest three of you get together, "
                f"you lose most of those rounds. Either the space past it needs "
                f"utility it is not getting, or the group should not be there.",
                f"Group gets no further than {p['zone']} in {p['hit']} of "
                f"{p['of']} {side} rounds; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"])

        elif p["kind"] == "setup" and gap >= GOOD_GAP:
            add(f"Keep the {p['zone']} setup",
                _keep_copy(p["zone"], p["side"], share, rate, baseline,
                           p["hit"], p["of"]),
                f"Held in {p['hit']} of {p['of']} {side} rounds; you win "
                f"{p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"],
                good=True)

        elif p["kind"] == "setup" and gap <= -MIN_GAP:
            add(f"Rethink the {p['zone']} default",
                f"You set up here more than anywhere else on this map and it is "
                f"your worst-converting position. A default you keep losing from "
                f"is a habit, not a plan.",
                f"Two or more of you here at twelve seconds in {p['hit']} of "
                f"{p['of']} {side} rounds; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], zone=p["zone"])

    # ---------------------------------------------------------------- trades
    if you["opening_lost"] >= MIN_ROUNDS:
        if _pct(you["opening_saved"], you["opening_lost"]) - baseline <= -MIN_GAP:
            add("Practice trading the opening duel",
                "Losing the first duel is normal. Losing the round almost every "
                "time you lose it is not. It means the second player is too far "
                "away to punish the trade, which is a spacing problem you can run "
                "in practice rather than an aim problem you cannot.",
                f"You win {you['opening_saved']} of {you['opening_lost']} rounds "
                f"after losing the opening duel",
                you["opening_saved"], you["opening_lost"])

    if you["opening_took"] >= MIN_ROUNDS:
        if _pct(you["opening_converted"], you["opening_took"]) - baseline <= -MIN_GAP:
            add("Close out the rounds you start ahead",
                "You take the first duel and then lose the round more often than "
                "your own average. The advantage is being made and given back "
                "inside the same round, which is about the twenty seconds after "
                "the kill rather than the kill itself.",
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
                "The full buy is the round you are most expected to win, and you "
                "win them below your own overall rate. Whatever is going wrong is "
                "going wrong in the rounds where you had every resource, which is "
                "the most expensive place for it to happen.",
                f"You win {v['won']} of {v['n']} full-buy rounds, against "
                f"{baseline:.0f}% overall", v["won"], v["n"])
        elif kind == "force" and rate < 20:
            add("Stop forcing, or force differently",
                "A force buy trades economy for tempo. At this rate you are "
                "getting neither: the round is lost and the next one is poorer "
                "for it. Either save properly or commit five players to the force "
                "rather than two.",
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
                    "This is your weakest side here by a distance: one map's one "
                    "side, well below what you manage everywhere else. That is a "
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
            add("Fix who your flashes land on",
                f"{own:.0f}% of the flashes you throw blind someone on your own "
                f"side. A flash that blinds your entry is worse than no flash: "
                f"the site is still held and the man going in cannot see it. "
                f"This is a pop-flash and a timing problem, and it is fixed in "
                f"practice rather than in a match.",
                f"{uf['hit_own']} of {uf['thrown']} flashes blinded a teammate "
                f"or the thrower, for {uf['own_secs']:.0f} seconds against "
                f"{uf['enemy_secs']:.0f} seconds of the opposition",
                uf["hit_own"], uf["thrown"],
                stake=_round_stake("own_flash"),
                foot=_round_foot("own_flash"))
        landed = _pct(uf["hit_enemy"], uf["thrown"])
        if landed <= LANDED_FLASH_FLOOR:
            add("Your flashes are not landing on anybody",
                f"Only {landed:.0f}% of your flashes blind an opponent at all. "
                f"That is not aim and it is not luck, it is where they are being "
                f"thrown from and when. Pick two throws per map and drill them "
                f"until they are the default.",
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
                f"${uu['per_round']:.0f} of grenades a round die in somebody's "
                f"hand, which is {left:.0f}% of what you spend on utility. Over "
                f"a half that is a rifle nobody bought. The usual cause is "
                f"saving a grenade for a perfect moment the round never reaches.",
                f"${uu['wasted']:,} of ${uu['spent']:,} spent on utility was "
                f"still in a hand when its owner died, across "
                f"{uu['rounds_holding']} rounds",
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
                merged["because"] = (
                    lead["because"] + " Two separate readings of this map point "
                    "at the same place, which is usually one problem rather than "
                    "two.")
                merged["stake"] = sum(g["stake"] for g in bucket)
            out.append(merged)
    return out


def for_match(match_key: str, team_id: int) -> list[dict]:
    """The same idea for one match: what this game says, not the season.

    Deliberately thinner. One match cannot support a recommendation about
    habits, so this reports only what happened in it and leaves the coaching to
    the season view.
    """
    from .report import build

    r = build(match_key)
    if r is None:
        return []
    anchors = team_anchors(team_id).get("anchors", {})
    sides = _side_by_round(team_id, anchors)

    out = []
    lost_full = won_full = 0
    lost_after_open = took_open = 0
    for row in r["rows"]:
        side = sides.get((match_key, row["round_num"]))
        if side not in ("ct", "t"):
            continue
        ct = side == "ct"
        won = bool(row["ct_won"]) == ct
        buy = row["buy_ct"] if ct else row["buy_t"]
        if buy == "full":
            won_full += won
            lost_full += not won
        if row["opening_loser"] and row["opening_loser"] != side:
            took_open += 1
            lost_after_open += not won

    if lost_full >= 4:
        out.append({
            "do": f"{lost_full} full buys went down in this match",
            "because": "Worth watching those rounds together rather than "
                       "separately, because a repeated loss on a full buy is usually one "
                       "habit, not four bad rounds.",
            "evidence": f"{won_full} of {won_full + lost_full} full buys won"})
    if took_open >= 4 and lost_after_open >= took_open * 0.5:
        out.append({
            "do": f"You took the opening duel {took_open} times and lost "
                  f"{lost_after_open} of those rounds anyway",
            "because": "The man advantage was made and given back inside the same "
                       "round. Those are the clips to pull.",
            "evidence": f"{took_open - lost_after_open} of {took_open} converted"})
    return out
