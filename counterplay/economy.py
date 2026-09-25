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
CURVE_INTERCEPT = 0.089
CURVE_CT = -0.178
CURVE_SLOPE = 1.223
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

# What a team spends when it saves: pistols and some armour. The median eco
# round in the corpus spent $2,300 (quartiles $1,300 and $3,600). Modelling a
# save as spending nothing made it look worse than the saves teams play.
ECO_SPEND = 2300

# NEXT round is far less certain than the "full buy or save" projection
# makes it look: real teams half-buy, drop, and save guns. On 4,014 judged
# collegiate rounds the projected next-round chance, regressed on what
# happened, came out at a logit slope of 0.40 (this round's: 0.97, i.e. the
# curve itself is fine). A projected 84% won 71%. So the next-round chance
# is pulled toward 50% by exactly that, and every two-round comparison,
# which is what raises a flag, is built on the tempered number.
NEXT_SLOPE = 0.40

# The product's own buckets (counterplay/schema.classify_round).
ECO_BELOW, FULL_FROM = 5000, 20000

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

    `their_equip` is what the other side actually held. At buy time a team
    reads the other side's money off the scoreboard, so this is close to
    what they knew, and it keeps a force that met another force from being
    judged against a full buy that never came."""
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


def options(money: float, carried: float, side: str) -> dict[str, tuple[float, float]]:
    """{call: (equipment, money left)} for saving and for buying.

    A save still spends ECO_SPEND, the way real ones do.
    Buying spends toward a full buy and stops there. Whether it lands as a
    force or a full buy is what the money allows, so it is named after the
    fact by kind()."""
    carried = max(carried, DEFAULT_KIT)
    spend = min(money, max(FULL_BUY[side] - carried, 0.0))
    light = min(money, ECO_SPEND)
    return {"save": (carried + light, money - light),
            "buy": (carried + spend, money - spend)}


def judge(money: float, spent: float, equip: float, side: str, counter: int,
          their_equip: float, their_money: float, their_spent: float,
          their_counter: int, last_of_half: bool) -> dict:
    """The call a team made, against saving and against buying.

    Everything is team totals. `equip - spent` is what the team carried in:
    a drop moves money between teammates and cancels out of the sum."""
    their_left = their_money - their_spent
    args = (side, counter, their_equip, their_left, their_counter, last_of_half)
    p_actual, v_actual = value(equip, money - spent, *args)
    alt = {}
    for call, (eq, left) in options(money, equip - spent, side).items():
        p, v = value(eq, left, *args)
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
