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

import numpy as np

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

# Paid per player for a win: $3,250 either side, and T's bomb money brings
# theirs to about $3,400 on average.
WIN_REWARD = {"ct": 3250, "t": 3400}

# Every CT is paid $50 for each kill their team makes, won or lost. Found
# in what was left over after the loss bonus and each player's own kill
# money on 11,000 CT losses: $0 at no kills, $50 at one, up to $250 at
# five, in 90% or more of rows at every count. T sides get nothing like it.
# It is also why a CT win looked like $3,500: $3,250 plus five kills.
CT_TEAM_KILL_BONUS = 50
CT_KILLS = {True: 4.93, False: 2.47}    # a CT team's kills, won and lost

# What one kill pays, by the weapon names death events carry. Checked
# indirectly but exactly: with each player's kills priced by this table,
# what was left of a CT loss came out in clean $50 steps (the team kill
# bonus above) on 90% or more of rows.
MONEY_CAP = 16000


def kill_reward(weapon: str | None) -> int:
    w = (weapon or "").lower()
    if w.startswith("knife") or w == "bayonet":
        return 1500
    if w in ("awp",):
        return 100
    if w in ("cz75a",):
        return 100
    if w in ("taser",):
        return 0
    if w in ("mac10", "mp9", "mp7", "mp5sd", "ump45", "bizon"):
        return 600
    if w in ("nova", "sawedoff", "mag7"):
        return 900
    if w == "xm1014":
        return 600
    return 300


def income(side: str, won: bool, counter_before: int, own_kill_money: int,
           team_kills: int, planted: bool) -> int:
    """What one player is paid at the end of a round, before the cap.

    A win is counted at its $3,250 floor, without the bomb or defuse extra,
    so anything built on this (the money lost to the cap) is never
    overstated."""
    pay = 3250 if won else loss_bonus(counter_before)
    if side == "t" and not won and planted:
        pay += 600
    if side == "ct":
        pay += CT_TEAM_KILL_BONUS * team_kills
    return pay + own_kill_money


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

# How far ahead a call is judged, and how sure the rounds after this one
# are allowed to be. Both are measured, not chosen: tools/buycheck.py plays
# every real call forward and compares with what happened. Re-measure both
# whenever anything above changes (set FUTURE_SLOPE = 1.0 first).
HORIZON = 12              # rounds, this one included; the half ends first
FUTURE_SLOPE = 1.0
SIMS = 400

# The product's own buckets (counterplay/schema.classify_round).
ECO_BELOW, FULL_FROM = 5000, 20000

# What real teams went on to win from that round to the end of the half,
# with no model in it: the evidence the match report shows beside a flag.
# Printed by tools/buycheck.py (section 6); copy it here when it moves.
# "underbuy" is a team that could afford a full buy ($22k+ with what it
# carried) and bought less, against a side on a full buy.
EVIDENCE = {   # (spot, call): (rounds won, rounds played), to the half's end
    ("underbuy", "force"): (377, 1023),     # 37%
    ("underbuy", "full"): (4019, 8046),     # 50%
}

# Which calls the check will name, and by how much the other call has to
# come out ahead over the rest of the half before it does.
#
# ONLY "you bought less than the full buy you could afford". Over the rest
# of the half real teams back it: 37% of rounds won after under-buying
# against a full buy, 50% after full buying, and the teams it flags then do
# WORSE than the model predicted (0.375 won against 0.45), so it errs the
# safe way. The model also likes forcing over saving, and over two rounds
# the data agreed (0.72 against 0.61), but over the rest of the half teams
# that saved and teams that forced with $12k to $20k both won 41%. A call
# the data does not back is not printed, however sure the model is.
FLAG_CALLS = {("force", "full")}
MARGIN = 0.05


def p_win(mine: float, theirs: float, side: str) -> float:
    x = (CURVE_INTERCEPT + (CURVE_CT if side == "ct" else 0.0) +
         CURVE_SLOPE * (math.log(max(mine, EQUIP_FLOOR)) -
                        math.log(max(theirs, EQUIP_FLOOR))))
    return 1.0 / (1.0 + math.exp(-x))


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


def _table(side: str):
    """ENEMY_BUY as an array, row = $ available // ENEMY_STEP, for sampling."""
    top = max(k for _, k in ENEMY_BUY)
    rows = [ENEMY_BUY[(side, max(i, 1))] for i in range(top + 1)]
    return np.array(rows, dtype=float), top


_TABLES = {}


def _buy(available, side, rng):
    """What a team with this much available holds: one draw per simulation
    from what real teams in that spot held (ENEMY_BUY), never more than it
    can reach."""
    if side not in _TABLES:
        _TABLES[side] = _table(side)
    tab, top = _TABLES[side]
    row = np.clip((available // ENEMY_STEP).astype(int), 1, top)
    pick = rng.integers(0, tab.shape[1], size=len(available))
    return np.minimum(tab[row, pick], available)


def _p(mine, theirs, side, slope=1.0):
    x = (CURVE_INTERCEPT + (CURVE_CT if side == "ct" else 0.0) +
         CURVE_SLOPE * (np.log(np.maximum(mine, EQUIP_FLOOR)) -
                        np.log(np.maximum(theirs, EQUIP_FLOOR))))
    return 1.0 / (1.0 + np.exp(-slope * x))


def _pay(money_left, equip, side, won, counter):
    """Money and carried equipment going into the next round, per simulation."""
    kill = np.where(won, KILL_MONEY[(side, True)], KILL_MONEY[(side, False)])
    after = np.minimum(counter + 1, LOSS_MAX)
    bonus = LOSS_BASE + LOSS_STEP * (after - 1)
    money = money_left + kill + 5 * np.where(won, WIN_REWARD[side], bonus)
    if side == "ct":
        money = money + 5 * CT_TEAM_KILL_BONUS * np.where(
            won, CT_KILLS[True], CT_KILLS[False])
    money = np.minimum(money, 5 * MONEY_CAP)
    frac = np.where(won, CARRY[(side, True)], CARRY[(side, False)])
    carried = np.maximum(DEFAULT_KIT, frac * equip)
    counter = np.where(won, np.maximum(counter - LOSS_WIN_STEP, 0), after)
    return money, carried, counter


def simulate(equip: float, money_left: float, side: str, counter: int,
             their_money: float, their_carried: float, their_counter: int,
             rounds: int, n: int = SIMS, seed: int = 0) -> tuple[float, float]:
    """(P(win this round), expected rounds won over the next `rounds` rounds,
    this one included), with this round's buy fixed at `equip`.

    Each simulation plays the rounds out: the other side's buy this round,
    and both sides' buys after it, are drawn from what real teams with that
    much money held (ENEMY_BUY), not from a rule like "full buy or save",
    which made the next round look far more certain than it was. Money moves
    by the measured rules. Rounds after this one are pulled toward 50% by
    FUTURE_SLOPE, measured on what happened (tools/buycheck.py).

    Every call with the same seed uses the same random draws, so two calls
    for the same round differ only by the call being compared."""
    rng = np.random.default_rng(seed)
    other = "t" if side == "ct" else "ct"
    us_eq = np.full(n, float(equip))
    us_left = np.full(n, float(money_left))
    us_cnt = np.full(n, counter)
    th_carried = np.full(n, float(their_carried))
    th_money = np.full(n, float(their_money))
    th_eq = _buy(th_carried + th_money, other, rng)
    th_left = th_money - np.maximum(th_eq - th_carried, 0.0)
    th_cnt = np.full(n, their_counter)
    total, p_now = np.zeros(n), None
    for k in range(rounds):
        p = _p(us_eq, th_eq, side, 1.0 if k == 0 else FUTURE_SLOPE)
        if k == 0:
            p_now = float(p.mean())
        total += p
        if k == rounds - 1:
            break
        won = rng.random(n) < p
        us_money, us_carried, us_cnt = _pay(us_left, us_eq, side, won, us_cnt)
        th_money, th_carried, th_cnt = _pay(th_left, th_eq, other, ~won, th_cnt)
        us_eq = _buy(us_carried + us_money, side, rng)
        us_left = us_money - np.maximum(us_eq - us_carried, 0.0)
        th_eq = _buy(th_carried + th_money, other, rng)
        th_left = th_money - np.maximum(th_eq - th_carried, 0.0)
    return p_now, float(total.mean())


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
          their_counter: int, rounds_left: int, seed: int = 0) -> dict:
    """The call a team made, against saving and against buying, over the
    next HORIZON rounds of the half (fewer if the half ends sooner).

    Everything is team totals, so a drop moves money between teammates and
    cancels out of the sum. The other side is read as it looked at buy time:
    what it could afford, never what it bought."""
    their_reach = their_equip + their_money - their_spent
    their_carried = min(max(their_reach - their_money, DEFAULT_KIT), their_reach)
    rounds = max(1, min(rounds_left, HORIZON))

    def run(eq, left):
        return simulate(eq, left, side, counter, their_money, their_carried,
                        their_counter, rounds, seed=seed)

    p_actual, v_actual = run(equip, money - spent)
    alt = {}
    for call, (eq, left) in options(money, equip + money - spent, side).items():
        p, v = run(eq, left)
        alt[call] = {"equip": eq, "kind": kind(eq), "p": p, "v": v}
    best = max(alt, key=lambda k: alt[k]["v"])
    made = kind(equip)
    # Only a call in FLAG_CALLS is ever named, and a different call only
    # counts when it lands in a different bucket: a $21k full buy is not
    # "wrong" next to a $24k one.
    differs = (made, alt[best]["kind"]) in FLAG_CALLS
    return {"made": made, "equip": equip, "p": p_actual, "v": v_actual,
            "rounds": rounds, "options": alt, "best": best,
            "gain": alt[best]["v"] - v_actual,
            "flag": differs and alt[best]["v"] - v_actual >= MARGIN}
