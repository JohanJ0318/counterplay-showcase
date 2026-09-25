"""What a player can buy, by kind.

The buy analysis reads loadouts as KINDS (rifle, SMG, pistol) rather than as
prices. Prices are read from the demo itself (`current_equip_value`,
`cash_spent_this_round`), which follows every patch without anyone editing
this file. A kind does not change when Valve moves a price.

Anything not listed here is not something a player buys: knives (every skin
has its own name), the C4, a zeus picked up off the floor. A weapon added in
a future update is also missing until it is listed, and drops out of the
loadout rather than being guessed at.
"""
from __future__ import annotations

import math

PISTOL, SMG, HEAVY, RIFLE, SNIPER, GRENADE = (
    "pistol", "smg", "heavy", "rifle", "sniper", "grenade")

KIND = {
    # pistols
    "Glock-18": PISTOL, "USP-S": PISTOL, "P2000": PISTOL, "P250": PISTOL,
    "Five-SeveN": PISTOL, "Tec-9": PISTOL, "CZ75-Auto": PISTOL,
    "Dual Berettas": PISTOL, "Desert Eagle": PISTOL, "R8 Revolver": PISTOL,
    # SMGs
    "MAC-10": SMG, "MP9": SMG, "MP7": SMG, "MP5-SD": SMG, "UMP-45": SMG,
    "P90": SMG, "PP-Bizon": SMG,
    # shotguns and machine guns
    "Nova": HEAVY, "XM1014": HEAVY, "Sawed-Off": HEAVY, "MAG-7": HEAVY,
    "M249": HEAVY, "Negev": HEAVY,
    # rifles
    "Galil AR": RIFLE, "FAMAS": RIFLE, "AK-47": RIFLE, "M4A4": RIFLE,
    "M4A1-S": RIFLE, "SG 553": RIFLE, "AUG": RIFLE,
    # snipers
    "SSG 08": SNIPER, "AWP": SNIPER, "G3SG1": SNIPER, "SCAR-20": SNIPER,
    # utility
    "Flashbang": GRENADE, "Smoke Grenade": GRENADE,
    "High Explosive Grenade": GRENADE, "Molotov": GRENADE,
    "Incendiary Grenade": GRENADE, "Decoy Grenade": GRENADE,
}

# Strongest first: a player holding an AWP and a Deagle is an AWP buy.
_RANK = [SNIPER, RIFLE, HEAVY, SMG, PISTOL]


def loadout(inventory) -> str | None:
    """A freeze-end inventory as the buyable items in it, comma separated.

    None when the demo gave no inventory at all, so "unknown" never reads
    as "bought nothing"."""
    if inventory is None or not hasattr(inventory, "__iter__") \
            or isinstance(inventory, str):
        return None
    items = [str(i) for i in inventory if str(i) in KIND]
    return ", ".join(items)


def main_weapon(loadout_text: str | None) -> str | None:
    """The kind of the best gun in a loadout: sniper, rifle, heavy, smg or
    pistol. None when there is no loadout to read."""
    if loadout_text is None:
        return None
    kinds = {KIND[i] for i in loadout_text.split(", ") if i in KIND}
    return next((k for k in _RANK if k in kinds), PISTOL)


# ---------------------------------------------------------------------------
# The buy decision
#
# Two parts, kept apart on purpose. The money is rules: what a team will have
# next round under each outcome is arithmetic. Only the win chance is
# learned, and it is one curve: P(win) from the ratio of the two sides'
# equipment (tools/econfit.py, which is where every number below comes from
# and where to re-measure them). Every constant here was measured on the 138
# collegiate matches, never on pro demos: a college team is not judged by
# how professionals spend.



# P(win) = logistic(INTERCEPT + CT * is_ct + SLOPE * ln(yours / theirs)).
# 20 seeds held out by match: ECE 0.92x its noise floor. Maps added nothing.
#
# These are the numbers WITH a team-strength control (tools/econconfound.py),
# not the plain fit. A better team is richer as well as better, so the plain
# curve (slope 1.228) credited equipment with some of what skill did. With
# each team's round-win rate over the rest of the match beside it, 89% of
# the slope survives (1.095; 90% range 0.99 to 1.19). The buy check asks
# "had you bought instead", which is a question about equipment alone, so
# it takes the smaller slope, at an even matchup.
CURVE_INTERCEPT = 0.121
CURVE_CT = -0.242
CURVE_SLOPE = 1.095
EQUIP_FLOOR = 200.0        # a side holding nothing still has pistols

# The loss bonus, as the demos pay it. The counter starts each half at 1, a
# loss adds one (to at most 5) and pays $1,400 + $500 for each step past the
# first, and a WIN TAKES TWO OFF. "A win resets it" matched 83% of 8,369 T
# losses and "a win takes one off" 79%; this matches 96.5%, and nearly all
# of the rest are one step out where a round was dropped from the demo.
LOSS_START, LOSS_MAX, LOSS_WIN_STEP = 1, 5, 2
LOSS_BASE, LOSS_STEP = 1400, 500

# Paid per player for a win, read off the same rounds. CT's is $3,500; T's
# is $3,250 plus bomb money, which averages out near $3,400.
WIN_REWARD = {"ct": 3500, "t": 3400}

# Kill money a whole team makes in a round, on average.
KILL_MONEY = {("ct", True): 1500, ("ct", False): 740,
              ("t", True): 1480, ("t", False): 660}

# Share of this round's equipment still held next round. Survivors keep
# their guns; the dead keep nothing but come back with a pistol.
CARRY = {("ct", True): 0.53, ("ct", False): 0.06,
         ("t", True): 0.48, ("t", False): 0.04}
DEFAULT_KIT = 5 * EQUIP_FLOOR

# What a full buy comes to, the median of every full-buy round. A buy
# spends toward this and no further.
FULL_BUY = {"ct": 26700, "t": 24175}

# What the other side will hold, from what it can afford: its money plus
# what it carried in, both known at buy time. Five points across what real
# teams with that much available ended up holding (tools/econenemy.py, which
# prints this table). The check averages the win chance over them instead of
# using the other side's actual buy, which would be hindsight: a save must
# not look wrong just because the other side happened to force. The median
# lands $1,450 from the real buy. Under $4,000 available across five
# players almost never happens and its rows are noise, so it reads $4,000.
ENEMY_STEP = 4000
ENEMY_BUY = {    # (side, $ available // STEP): equipment at percentiles (10, 30, 50, 70, 90)
    ("ct",  1): [1400, 1900, 2500, 4460, 10140],
    ("ct",  2): [1400, 1900, 2450, 4180, 10220],
    ("ct",  3): [2000, 2950, 4000, 5630, 12540],
    ("ct",  4): [5270, 7250, 9450, 15900, 17740],
    ("ct",  5): [15860, 18950, 20400, 21450, 22680],
    ("ct",  6): [20100, 22300, 23450, 24200, 25420],
    ("ct",  7): [22950, 24650, 25850, 26700, 27850],
    ("ct",  8): [24040, 25750, 26950, 27950, 29350],
    ("ct",  9): [23830, 26200, 27900, 28810, 30050],
    ("ct", 10): [27000, 28650, 29800, 30450, 31500],
    ("t",  1): [1500, 2000, 2800, 5710, 10370],
    ("t",  2): [1500, 2000, 2780, 5470, 10390],
    ("t",  3): [2500, 4120, 5820, 11050, 13850],
    ("t",  4): [6550, 12250, 15050, 16800, 18550],
    ("t",  5): [14600, 18240, 19600, 20600, 22100],
    ("t",  6): [19300, 21300, 22500, 23350, 24500],
    ("t",  7): [21250, 22900, 23800, 24920, 26250],
    ("t",  8): [21260, 23490, 24500, 25400, 27050],
    ("t",  9): [21670, 24020, 25200, 26280, 27550],
    ("t", 10): [24400, 25400, 26000, 27350, 27870],
}


def enemy_buys(available: float, side: str) -> list[float]:
    b = min(max(int(available // ENEMY_STEP), 1), max(k for _, k in ENEMY_BUY))
    return [float(x) for x in ENEMY_BUY[(side, b)]]


# What a team spends when it saves: pistols and some armour. The median eco
# round in the corpus spent $2,300 (quartiles $1,300 and $3,600). Modelling a
# save as spending nothing made it look worse than the saves teams play.
ECO_SPEND = 2300

# NEXT round is far less certain than the "full buy or save" projection
# makes it look: real teams half-buy, drop, and save guns. On the collegiate
# corpus the projected next-round chance, regressed on what happened, came
# out at a logit slope of 0.50 (0.40 before the other side's buy was read
# as an expectation; this round's own slope is 1.13, so the curve itself is
# if anything cautious). So the next-round chance is pulled toward 50% by
# exactly that, and every two-round comparison, which is what raises a
# flag, is built on the tempered number. Re-measure with NEXT_SLOPE = 1.0
# whenever anything above changes.
NEXT_SLOPE = 0.50

# The product's own buckets (counterplay/schema.classify_round).
ECO_BELOW, FULL_FROM = 5000, 20000

# What real teams went on to win, over that round and the next, in the two
# spots the check flags most, both against a full buy. No model in it: this
# is what the match report shows beside a flag, so a coach sees the rounds
# rather than a decimal the model has not earned. Printed by
# tools/buycheck.py (section 6); copy it here when it moves.
#   underbuy:      could afford a full buy ($22k+ with what they carried)
#   save_or_force: $12k to $20k available
EVIDENCE = {   # (spot, call): (rounds won of the next 2, teams)
    ("save_or_force", "eco"): (0.61, 151),
    ("save_or_force", "force"): (0.72, 478),
    ("underbuy", "force"): (0.72, 204),
    ("underbuy", "full"): (1.00, 1826),
}

# Two rounds' worth of wins a different call has to be ahead by before it is
# worth saying. Below this the curve cannot tell the calls apart.
MARGIN = 0.10


def p_win(mine: float, theirs: float, side: str) -> float:
    x = (CURVE_INTERCEPT + (CURVE_CT if side == "ct" else 0.0) +
         CURVE_SLOPE * (math.log(max(mine, EQUIP_FLOOR)) -
                        math.log(max(theirs, EQUIP_FLOOR))))
    return 1.0 / (1.0 + math.exp(-x))


def _temper(p: float) -> float:
    """A next-round chance pulled toward 50% by NEXT_SLOPE on the logit."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return 1.0 / (1.0 + math.exp(-NEXT_SLOPE * math.log(p / (1 - p))))


def loss_counter(results: list[bool]) -> int:
    """The counter going INTO the next round, from this half's results so far
    (True = won), oldest first."""
    n = LOSS_START
    for won in results:
        n = max(n - LOSS_WIN_STEP, 0) if won else min(n + 1, LOSS_MAX)
    return n


def loss_bonus(counter_before: int) -> int:
    """What each player is paid for losing a round entered on this counter."""
    after = min(counter_before + 1, LOSS_MAX)
    return LOSS_BASE + LOSS_STEP * (after - 1)


def kind(equip: float) -> str:
    """eco, force or full: the same cut the rest of the product uses."""
    return "eco" if equip < ECO_BELOW else "force" if equip < FULL_FROM else "full"


def next_equip(money_left: float, equip_now: float, side: str, won: bool,
               counter_before: int) -> float:
    """A team's equipment next round, if it wins or loses this one.

    Next round is assumed to go the way coaches teach: full buy if the
    money reaches it, save if not. That assumption is what makes a force
    costly, which is the whole point of looking a round ahead."""
    money = (money_left + KILL_MONEY[(side, won)] +
             5 * (WIN_REWARD[side] if won else loss_bonus(counter_before)))
    carried = max(DEFAULT_KIT, CARRY[(side, won)] * equip_now)
    if carried + money >= FULL_FROM:
        return max(carried, min(FULL_BUY[side], carried + money))
    return carried


def value(equip: float, money_left: float, side: str, counter: int,
          their_equip: float, their_left: float, their_counter: int,
          last_of_half: bool) -> tuple[float, float]:
    """(P(win this round), expected rounds won over this round and the next).

    `their_equip` is one guess at what the other side holds; judge() passes
    each of the ENEMY_BUY points in turn and averages."""
    other = "t" if side == "ct" else "ct"
    p = p_win(equip, their_equip, side)
    if last_of_half:
        return p, p                      # money resets; nothing to carry over
    nxt = 0.0
    for won, weight in ((True, p), (False, 1.0 - p)):
        us = next_equip(money_left, equip, side, won, counter)
        them = next_equip(their_left, their_equip, other, not won, their_counter)
        nxt += weight * _temper(p_win(us, them, side))
    return p, p + nxt


def options(money: float, reach: float, side: str) -> dict[str, tuple[float, float]]:
    """{call: (equipment, money left)} for saving and for buying.

    `reach` is the most equipment the team could have held: what it held
    plus what it kept (equip + money - spent). NOT equip - spent + money
    built from a carried-in figure: `spent` is read at the round's end and
    takes in buys made after freeze-end, which freeze-end equipment does
    not, so "carried" came out negative and clamping it up invented money.
    That put a team on $18,250 down as able to full buy.

    A save still spends ECO_SPEND, the way real ones do. Buying spends
    toward a full buy and stops there; whether it lands as a force or a
    full buy is what the money allows, named after the fact by kind()."""
    carried = min(max(reach - money, DEFAULT_KIT), reach)
    save = min(reach, carried + min(money, ECO_SPEND))
    buy = min(reach, max(FULL_BUY[side], carried))
    return {"save": (save, max(money - (save - carried), 0.0)),
            "buy": (buy, max(money - (buy - carried), 0.0))}


def judge(money: float, spent: float, equip: float, side: str, counter: int,
          their_equip: float, their_money: float, their_spent: float,
          their_counter: int, last_of_half: bool) -> dict:
    """The call a team made, against saving and against buying.

    Everything is team totals, so a drop moves money between teammates and
    cancels out of the sum."""
    # The other side as it looked at buy time: what it could afford, and the
    # spread of what teams with that much actually hold (ENEMY_BUY).
    other = "t" if side == "ct" else "ct"
    their_reach = their_equip + their_money - their_spent
    their_carried = min(max(their_reach - their_money, DEFAULT_KIT), their_reach)
    theirs = [min(te, their_reach) for te in enemy_buys(their_reach, other)]

    def expected(eq, left):
        ps, vs = [], []
        for te in theirs:
            their_left = max(their_money - max(te - their_carried, 0.0), 0.0)
            p, v = value(eq, left, side, counter, te, their_left,
                         their_counter, last_of_half)
            ps.append(p)
            vs.append(v)
        return sum(ps) / len(ps), sum(vs) / len(vs)

    p_actual, v_actual = expected(equip, money - spent)
    alt = {}
    for call, (eq, left) in options(money, equip + money - spent, side).items():
        p, v = expected(eq, left)
        alt[call] = {"equip": eq, "kind": kind(eq), "p": p, "v": v}
    best = max(alt, key=lambda k: alt[k]["v"])
    made = kind(equip)
    # A different call only counts when it lands in a different bucket: a
    # $21k full buy is not "wrong" next to a $24k one.
    differs = (alt[best]["kind"] != made and
               not (best == "save" and made == "eco"))
    return {"made": made, "equip": equip, "p": p_actual, "v": v_actual,
            "options": alt, "best": best,
            "gain": alt[best]["v"] - v_actual,
            "flag": differs and alt[best]["v"] - v_actual >= MARGIN}
