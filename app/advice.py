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
     rest of the time. A team that wins 49% of rounds and 12% of one particular
     situation has found something; a team that wins 49% and 44% has not.
  3. SOMETHING TO ACTUALLY DO. If the honest advice is "keep doing that", it
     says so, and if there is no action that follows from the finding, no line
     is produced at all.

Ranked by ROUNDS AT STAKE — how many rounds the gap covers — because a nine
point gap over thirty rounds is worth more of a Monday than a forty point gap
over eight.
"""
from __future__ import annotations

from . import db, movement
from .report import _side_by_round, team_anchors, team_stats

# An anecdote below this. Deliberately higher than the reporting threshold: it
# is one thing to show a coach a count, another to tell them to change practice
# because of it.
MIN_ROUNDS = 8

# Percentage points away from this team's own baseline before a difference is
# worth a Monday. Under ten points is inside the noise of a season this short.
MIN_GAP = 12.0

# Above this, a habit is working and the advice is to keep it — said out loud,
# because a report that only ever lists problems trains people to stop reading.
GOOD_GAP = 15.0

MAX_ITEMS = 8


def _pct(hit, of):
    return 100.0 * hit / of if of else 0.0


def monday(team_id: int) -> dict:
    """Recommendations, strongest first, each carrying the count behind it.

    Returns {"baseline": float, "items": [...]} so the page can say what
    everything is being compared against.
    """
    st = team_stats(team_id)
    if st is None:
        return {"baseline": 0.0, "items": []}

    you = st["you"]
    baseline = _pct(you["won"], you["rounds"]) if you["rounds"] else 0.0
    if not baseline:
        return {"baseline": 0.0, "items": []}

    items: list[dict] = []

    def add(do, because, evidence, hit, of, *, mp=None, side=None, good=False):
        """One recommendation. `hit/of` is the situation's own record."""
        rate = _pct(hit, of)
        gap = rate - baseline
        items.append({
            "do": do, "because": because, "evidence": evidence,
            "hit": hit, "of": of, "rate": rate, "gap": gap,
            "map": (mp or "").replace("de_", ""), "side": side,
            "good": good,
            # Rounds at stake: how many rounds this covers, times how far off
            # the team's own normal it is. A big gap over few rounds and a
            # small gap over many are both real; this weighs them the same way
            # a coach would.
            "stake": abs(gap) / 100.0 * of,
        })

    # ---------------------------------------------------------------- position
    pos = movement.positional_patterns(team_id)

    for p in pos:
        if p["of"] < MIN_ROUNDS or p["hit"] < MIN_ROUNDS:
            continue
        rate = _pct(p["won"], p["hit"])
        gap = rate - baseline
        where = f'{p["zone"]} on {p["map"].replace("de_", "")}'
        side = p["side"].upper()

        if p["kind"] == "death" and gap <= -MIN_GAP:
            add(f"Change how you take {p['zone']}",
                f"When the first of you dies in {where} as {side}, the round is "
                f"usually already gone. That is not bad luck at that rate — it "
                f"is the same duel being taken the same way.",
                f"First death in {p['zone']} in {p['hit']} of {p['of']} "
                f"{side} rounds; you win {p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"])

        elif p["kind"] == "commit" and gap <= -MIN_GAP:
            add(f"Your {side} opening on {p['map'].replace('de_', '')} stops at "
                f"{p['zone']}",
                f"When {where} is the furthest three of you get together, you "
                f"lose most of those rounds. Either the space past it needs "
                f"utility it is not getting, or the group should not be there "
                f"at all.",
                f"Group gets no further than {p['zone']} in {p['hit']} of "
                f"{p['of']} {side} rounds; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"])

        elif p["kind"] == "setup" and gap >= GOOD_GAP:
            add(f"Keep the {p['zone']} setup on {p['map'].replace('de_', '')}",
                f"This is working. When two or more of you hold {p['zone']} at "
                f"twelve seconds you win well above your own average, so it is "
                f"worth defending as a default rather than drifting off it.",
                f"Held in {p['hit']} of {p['of']} {side} rounds; you win "
                f"{p['won']} of those {p['hit']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"], good=True)

        elif p["kind"] == "setup" and gap <= -MIN_GAP:
            add(f"Rethink the {p['zone']} default on "
                f"{p['map'].replace('de_', '')}",
                f"You set up here more than anywhere else on this map and it is "
                f"your worst-converting position. A default you keep losing "
                f"from is a habit, not a plan.",
                f"Two or more of you here at twelve seconds in {p['hit']} of "
                f"{p['of']} {side} rounds; you win {p['won']}",
                p["won"], p["hit"], mp=p["map"], side=p["side"])

    # ---------------------------------------------------------------- trades
    if you["opening_lost"] >= MIN_ROUNDS:
        rate = _pct(you["opening_saved"], you["opening_lost"])
        if rate - baseline <= -MIN_GAP:
            add("Practice trading the opening duel",
                "Losing the first duel is normal. Losing the round almost every "
                "time you lose it is not — it means the second player is too far "
                "away to punish the trade, which is a spacing problem you can "
                "run in practice rather than an aim problem you cannot.",
                f"You win {you['opening_saved']} of {you['opening_lost']} rounds "
                f"after losing the opening duel",
                you["opening_saved"], you["opening_lost"])

    if you["opening_took"] >= MIN_ROUNDS:
        rate = _pct(you["opening_converted"], you["opening_took"])
        if rate - baseline <= -MIN_GAP:
            add("Close out the rounds you start ahead",
                "You take the first duel and then lose the round more often than "
                "your own average. The advantage is being made and then given "
                "back, which is about what happens in the twenty seconds after "
                "the kill, not the kill itself.",
                f"You win {you['opening_converted']} of {you['opening_took']} "
                f"rounds after taking the opening duel",
                you["opening_converted"], you["opening_took"])

    # ---------------------------------------------------------------- economy
    for kind, v in sorted(st["you_buys"].items()):
        if v["n"] < MIN_ROUNDS:
            continue
        rate = _pct(v["won"], v["n"])
        gap = rate - baseline
        if kind == "full" and gap <= -MIN_GAP:
            add("Full buys are not converting",
                "The full buy is the round you are most expected to win, and you "
                "win them at below your own overall rate. Whatever is going "
                "wrong is going wrong in the rounds where you had every "
                "resource, which is the most expensive place for it to happen.",
                f"You win {v['won']} of {v['n']} full-buy rounds, against "
                f"{baseline:.0f}% overall",
                v["won"], v["n"])
        elif kind == "force" and rate < 20 and v["n"] >= MIN_ROUNDS:
            add("Stop forcing, or force differently",
                "A force buy trades economy for tempo. At this rate you are "
                "getting neither — the round is lost and the next one is "
                "poorer for it. Either save properly or commit five players to "
                "the force rather than two.",
                f"You win {v['won']} of {v['n']} force-buy rounds",
                v["won"], v["n"])

    # ---------------------------------------------------------------- maps
    for name, m in st["maps"].items():
        for side in ("ct", "t"):
            s = m.get(side) or {}
            if s.get("rounds", 0) < MIN_ROUNDS:
                continue
            rate = _pct(s["won"], s["rounds"])
            gap = rate - baseline
            if gap <= -MIN_GAP:
                add(f"Your {side.upper()} side on {name.replace('de_', '')} "
                    f"needs a rebuild",
                    f"This is your weakest side-map combination by a distance. "
                    f"One map's one side, well below what you manage everywhere "
                    f"else — that is a set of defaults to change, not a run of "
                    f"bad games.",
                    f"You win {s['won']} of {s['rounds']} {side.upper()} rounds "
                    f"on {name.replace('de_', '')}, against {baseline:.0f}% "
                    f"overall",
                    s["won"], s["rounds"], mp=name, side=side)

    items.sort(key=lambda x: -x["stake"])
    return {"baseline": baseline, "items": items[:MAX_ITEMS]}


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
                       "separately — a repeated loss on a full buy is usually "
                       "one habit, not four bad rounds.",
            "evidence": f"{won_full} of {won_full + lost_full} full buys won"})
    if took_open >= 4 and lost_after_open >= took_open * 0.5:
        out.append({
            "do": f"You took the opening duel {took_open} times and lost "
                  f"{lost_after_open} of those rounds anyway",
            "because": "The man advantage was made and given back inside the "
                       "same round. Those are the clips to pull.",
            "evidence": f"{took_open - lost_after_open} of {took_open} converted"})
    return out
