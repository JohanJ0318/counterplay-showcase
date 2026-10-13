"""Why a team is below collegiate teams, not just that it is.

NC State Red's captain, 2026-09-30: the stats "are like leetify's, which I
stopped checking because they weren't particularly actionable. For this to be
something I checked often, it would need to tell me (or guess with some
degree of confidence) why I'm below a given benchmark."

A rate like "you win 21% of rounds after losing the opening duel, college
teams win 30%" is the END of a short chain of events, and every link of that
chain can be counted and compared with collegiate teams on its own:

    lost the opening duel
      -> was that death traded within 5 seconds?        (trade)
           traded:     back to 4v4, did you win?         (after a trade)
           not traded: a real 4v5, did you win?          (playing 4v5)

The round rate is exactly  traded * won_after_trade + (1 - traded) * won_4v5,
so the gap to college teams splits EXACTLY into one share per link (a
Shapley split over the three links: every order of swapping a link to the
college value, averaged, so the shares add up to the whole gap and no order
is privileged). The link that costs the most rounds is the likely "why",
and it is said with the confidence its own count supports, by the same test
as everything else (league.judge): "clear" when that link alone is too far
off to be luck, "most likely" when it is the biggest share but not clear on
its own. With no link costing a round, nothing is claimed.

The same chain after WINNING the opening duel: did they trade it back, and
what happened in the 4v4 or the 5v4.

Counted the same way for the reference (tools/league_rates.py, key
"opening_chain") and for a team here, from `events`, so the two cannot drift.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import permutations

from . import db, league

# Same window as the parser's trade (counterplay/parse.py).
TRADE_SECONDS = 5.0

# Rounds a link must cost, against college teams, to be named as a cause.
MIN_ROUNDS = 1.0


def empty() -> dict:
    """Counts for one side. `lost` is from the side that lost the opening
    duel, `took` from the side that won it."""
    return {"lost": {"n": 0, "traded": 0, "traded_won": 0, "open_won": 0},
            "took": {"n": 0, "traded": 0, "traded_won": 0, "open_won": 0}}


def opening_events(deaths: list) -> tuple | None:
    """(side that lost the opening duel, was it traded) from one round's
    deaths in time order, each a mapping with seconds, victim_side,
    victim_steamid and attacker_steamid. None for a round with no duel.

    Traded means the opening killer died within TRADE_SECONDS, which is the
    parser's definition of a trade."""
    if not deaths:
        return None
    first = deaths[0]
    loser = first["victim_side"]
    if loser not in ("ct", "t"):
        return None
    killer = first["attacker_steamid"]
    traded = any(d["victim_steamid"] == killer
                 and d["seconds"] - first["seconds"] <= TRADE_SECONDS
                 for d in deaths[1:]) if killer else False
    return loser, traded


def tally(counts: dict, role: str, traded: bool, won: bool) -> None:
    c = counts[role]
    c["n"] += 1
    if traded:
        c["traded"] += 1
        c["traded_won"] += int(won)
    else:
        c["open_won"] += int(won)


def team_counts(team_id: int) -> tuple[dict, dict]:
    """This team's chain counts by side, and the rounds behind each branch:
    {side: counts}, {(role, traded, won): [(map, round, match_key)]}."""
    from .report import our_sides       # report imports advice imports this
    sides = our_sides(team_id)
    if not sides:
        return {}, {}
    keys = sorted({k for k, _ in sides})
    marks = ",".join("?" * len(keys))
    rounds = {(r["match_key"], r["round_num"]): r for r in db.query(
        f"""SELECT match_key, round_num, ct_won, map_name FROM rounds
             WHERE match_key IN ({marks})""", *keys)}
    deaths = defaultdict(list)
    for e in db.query(f"""SELECT match_key, round_num, seconds, victim_side,
                                 victim_steamid, attacker_steamid
                            FROM events WHERE type = 'death'
                             AND match_key IN ({marks})
                        ORDER BY match_key, round_num, seconds""", *keys):
        deaths[(e["match_key"], e["round_num"])].append(e)
    out = {s: empty() for s in ("ct", "t")}
    where = defaultdict(list)
    for key, side in sides.items():
        r = rounds.get(key)
        o = opening_events(deaths.get(key, []))
        if r is None or o is None:
            continue
        loser, traded = o
        won = bool(r["ct_won"]) == (side == "ct")
        role = "lost" if loser == side else "took"
        tally(out[side], role, traded, won)
        where[(role, traded, won)].append(
            ((r["map_name"] or "").replace("de_", ""), key[1], key[0]))
    return out, where


def _sum(by_side: dict, role: str) -> dict:
    tot = {"n": 0, "traded": 0, "traded_won": 0, "open_won": 0}
    for s in by_side.values():
        for k in tot:
            tot[k] += s[role][k]
    return tot


def _rates(c: dict) -> tuple | None:
    """(traded share, won after a trade, won with no trade), or None."""
    if not c["n"]:
        return None
    t = c["traded"] / c["n"]
    wt = c["traded_won"] / c["traded"] if c["traded"] else None
    open_ = c["n"] - c["traded"]
    wu = c["open_won"] / open_ if open_ else None
    return t, wt, wu


def _college(role: str, team: dict) -> tuple | None:
    """The collegiate rates for this role, weighted by the team's own rounds
    per side, as (traded, won after trade, won no trade)."""
    ref = league.ref().get("opening_chain")
    if not ref:
        return None
    parts = []
    for side, c in team.items():
        n = c[role]["n"]
        r = _rates(ref.get(side, {}).get(role, {"n": 0}))
        if n and r and None not in r:
            parts.append((n, r))
    tot = sum(n for n, _ in parts)
    if not tot:
        return None
    return tuple(sum(n * r[i] for n, r in parts) / tot for i in range(3))


def _expected(t, wt, wu):
    return t * wt + (1 - t) * wu


def _shapley(mine: tuple, ref: tuple) -> list[float]:
    """Each link's share of (mine - ref) in the round rate, exactly."""
    share = [0.0, 0.0, 0.0]
    orders = list(permutations(range(3)))
    for order in orders:
        cur = list(ref)
        before = _expected(*cur)
        for i in order:
            cur[i] = mine[i]
            after = _expected(*cur)
            share[i] += after - before
            before = after
    return [s / len(orders) for s in share]


# What each link is called, what the college teams do, and what to work on.
LINKS = {
    "lost": [
        ("Opening death traded within 5 seconds",
         "Your second player is not close enough to trade the first death. "
         "Drill the spacing: the entry and the trade go together."),
        ("Rounds won after the trade (4v4)",
         "You get the trade and still lose the 4v4: the problem is the round "
         "after the duel, not the duel. Look at what the four do next."),
        ("Rounds won 4v5 with no trade",
         "Down a player with no trade, you lose more than college teams do. "
         "Decide the 4v5 plan before the round: stack, retake or save."),
    ],
    "took": [
        ("They traded your opening kill within 5 seconds",
         "Your opening kills get traded straight back: the player taking the "
         "duel is alone. Take it with a teammate in line to refrag."),
        ("Rounds won after they traded (4v4)",
         "After they trade your opening kill you lose the 4v4 more than "
         "college teams do."),
        ("Rounds won 5v4",
         "You keep the man advantage and still lose the round: a 5v4 needs a "
         "plan to close it, not more duels."),
    ],
}


def explain(team: dict, where: dict, role: str) -> dict | None:
    """The chain for one role ("lost" or "took") against college teams.

    Returns {"links": [...], "culprit": index or None, "confidence": "clear"
    | "likely" | None, "rounds": [...]} or None without a reference. Each
    link: label, hit, of, pct, college pct, rounds it costs (negative is
    rounds lost against college teams), verdict from league.judge.
    """
    mine_c = _sum(team, role)
    mine = _rates(mine_c)
    ref = _college(role, team)
    if not mine or not ref or None in mine:
        return None
    n = mine_c["n"]
    # For "took", a trade is THEIR trade, so a higher rate is worse for you.
    shares = _shapley(mine, ref)
    open_n = n - mine_c["traded"]
    counts = [(mine_c["traded"], n), (mine_c["traded_won"], mine_c["traded"]),
              (mine_c["open_won"], open_n)]
    links = []
    for i, ((label, advice), (hit, of)) in enumerate(zip(LINKS[role], counts)):
        verdict = league.judge(hit, of, (100 * ref[i],)) if of else 0
        if role == "took" and i == 0:
            verdict = -verdict          # their trade rate: higher is worse
        links.append({"label": label, "advice": advice, "hit": hit, "of": of,
                      "pct": 100.0 * hit / of if of else 0.0,
                      "college": 100.0 * ref[i],
                      "rounds": shares[i] * n, "verdict": verdict})
    total = (_expected(*mine) - _expected(*ref)) * n
    # A cause is named only when the team is really behind here (a round or
    # more against college teams) and one link carries a round of that. Every
    # other link costing a round is named too: two weak links are two things
    # to work on, and hiding the second would be a guess dressed as an answer.
    order = sorted(range(3), key=lambda i: links[i]["rounds"])
    culprits = ([i for i in order if links[i]["rounds"] <= -MIN_ROUNDS]
                if total <= -MIN_ROUNDS else [])
    confidence = None
    if culprits:
        confidence = "clear" if links[culprits[0]]["verdict"] < 0 else "likely"
    # The rounds to watch are the LOST rounds down the worst link's branch.
    branch = {0: (role, role == "took", False), 1: (role, True, False),
              2: (role, False, False)}
    rounds = sorted(where.get(branch[culprits[0]], [])) if culprits else []
    return {"links": links, "culprits": culprits, "confidence": confidence,
            "total": total, "n": n, "rounds": rounds}


def for_team(team_id: int) -> dict:
    """{"lost": explain(...), "took": explain(...)} for one team, either
    None without a reference or a team side."""
    team, where = team_counts(team_id)
    if not team:
        return {"lost": None, "took": None}
    return {role: explain(team, where, role) for role in ("lost", "took")}


def rounds_line(rounds: list) -> str:
    """'Rounds to watch: anubis 4, 9, 17; dust2 3' grouped by match."""
    by = defaultdict(list)
    names = {}
    for mp, rn, key in rounds:
        by[key].append(rn)
        names[key] = mp
    parts = [f"{names[k]} {', '.join(str(r) for r in sorted(v))}"
             for k, v in sorted(by.items(), key=lambda kv: names[kv[0]])]
    return "Rounds to watch: " + "; ".join(parts) if parts else ""
