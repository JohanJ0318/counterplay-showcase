"""Why a match was lost: every swing of win chance, sorted into causes.

The scorer's model gives a team's chance of winning the round at every
moment. From the start of a round to its end those chances move from the
start value to 1 or 0, so over a match every change adds up exactly to
rounds won minus half the rounds played. Sorting each change into a cause
says where a match went, in rounds:

  money           the round started below even: the buy, before a shot
  <a detector>    one of our deaths, by the first proven detector it fits
                  (counterplay/decisions.py): no trade, crosshair, from
                  the side, through smoke, ...
  lost duel       one of our deaths where none of them fits: the fight
                  itself was lost
  our kills       enemy deaths (gains)
  plant           the bomb going down (a loss on CT, a gain on T)
  round end       what happened after the last kill: the clock, the
                  defuse, a save

Only what the team could have known feeds the detectors, and only the
deaths are described, never a guess at what else might have happened.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from . import decisions as D

# A death goes to the first of these that fires on it. Specific causes
# first: "through a smoke" says more than "no one to trade you".
PRIORITY = ["through_smoke", "wallbang", "from_behind", "from_side",
            "known_angle", "crosshair", "fought_blind", "entry_alone",
            "no_trade", "utility_unused"]

LABEL = {
    "money": "Rounds started behind on money",
    "lost_duel": "Duels lost with nothing else wrong",
    "our_kills": "Your kills",
    "plant": "The bomb going down",
    "round_end": "After the last kill (clock, defuse, saves)",
    "no_trade": "Deaths with no one close enough to trade",
    "entry_alone": "Going onto the site first, alone",
    "from_behind": "Shot from behind",
    "from_side": "Shot from the side, from angles no one was watching",
    "through_smoke": "Killed through smokes",
    "wallbang": "Killed through walls",
    "known_angle": "Walking into enemies the team had already seen",
    "crosshair": "Crosshair not on the enemy when he appeared",
    "fought_blind": "Fighting while flashed",
    "utility_unused": "Dying with grenades never thrown",
}

PRACTICE = {
    "money": "Agree as a team when to full-save, so the next buy is a full one "
             "and not two broken buys in a row.",
    "lost_duel": "Nothing around these fights went wrong; the duel itself was lost. "
                 "Warm up on the angles you hold, and pre-aim them in practice.",
    "no_trade": "Play in pairs: the second player stays close enough to swing the "
                "moment the first one dies.",
    "entry_alone": "Enter sites as a pair, with the second player a step behind "
                   "the first.",
    "from_behind": "Call where you are and what you have cleared; whoever holds the "
                   "flank says so out loud.",
    "from_side": "Clear or utility the angle beside you before you commit, or have "
                 "a teammate hold it.",
    "through_smoke": "Do not push through or hold right behind a smoke someone may "
                     "be spraying; wait for it to fade or go around.",
    "wallbang": "Learn the spots on this map that can be shot through and don't "
                "stand still in them.",
    "known_angle": "When a teammate calls an enemy, check that angle before you "
                   "walk past it.",
    "crosshair": "Keep your crosshair at head height on the angle the enemy will "
                 "come from, before you see him.",
    "fought_blind": "When you are flashed, turn away or fall back instead of taking "
                    "the fight.",
    "utility_unused": "Throw your grenades before the fight they are for.",
    "plant": "Watch where each of you was when the bomb went down, and fix the "
             "setup that let it.",
    "round_end": "Look at how these rounds ended after the last kill: the time, "
                 "the defuse, or a save.",
}


@dataclass
class Breakdown:
    rounds_won: int = 0
    rounds_lost: int = 0
    causes: dict = field(default_factory=lambda: defaultdict(float))
    by_side: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))
    examples: dict = field(default_factory=lambda: defaultdict(list))

    def worst(self, n: int = 3):
        """The causes that cost most, as (cause, rounds lost), worst first.
        Gains (our kills) never appear here."""
        losses = [(c, v) for c, v in self.causes.items() if v < 0 and c != "our_kills"]
        return sorted(losses, key=lambda cv: cv[1])[:n]


def cause_of_death(match_key, round_num, seconds, side, rf) -> str:
    f = D.facts(match_key, round_num, seconds, side, rf)
    if f is None:
        return "lost_duel"
    fired = set(D.detect(f))
    for code in PRIORITY:
        if code in fired and D.proven(code):
            return code
    return "lost_duel"


def explain_match(states, wp_ct, side_of: dict) -> Breakdown:
    """`states`: one match's state rows (counterplay.state), in order;
    `wp_ct`: the model's CT win chance for each row; `side_of`:
    (match_key, round_num) -> our side."""
    st = states.assign(wp_ct=np.asarray(wp_ct)).sort_values(
        ["match_id", "round_num", "event_idx"])
    out = Breakdown()
    for (mk, rn), rows in st.groupby(["match_id", "round_num"], sort=True):
        side = side_of.get((mk, int(rn)))
        if side is None:
            continue
        rf = D.RoundFacts(mk, int(rn))
        ours = (lambda p: p) if side == "ct" else (lambda p: 1.0 - p)
        won = bool(rows["ct_won"].iloc[0]) == (side == "ct")
        out.rounds_won += won
        out.rounds_lost += not won

        def add(cause, value, secs=None):
            out.causes[cause] += value
            out.by_side[side][cause] += value
            if value < 0 and secs is not None:
                out.examples[cause].append((mk, int(rn), float(secs), round(-value, 2)))

        prev = None
        last_t = 0.0
        for r in rows.itertuples(index=False):
            p = ours(r.wp_ct)
            last_t = float(r.seconds)
            if prev is None:
                # The round's start: a round begun behind on money is its own
                # example, at 0 seconds (a page shows it as just the round).
                add("money", p - 0.5, 0.0)
            else:
                delta = p - prev
                if r.event_type == "death" and r.victim_side == side:
                    add(cause_of_death(mk, int(rn), float(r.seconds), side, rf), delta, r.seconds)
                elif r.event_type == "death":
                    add("our_kills", delta)
                elif r.event_type == "plant":
                    add("plant", delta, r.seconds)
                else:
                    add("round_end", delta, r.seconds)
            prev = p
        add("round_end", float(won) - prev, last_t)
    for c in out.examples:
        out.examples[c].sort(key=lambda e: -e[3])
    return out
