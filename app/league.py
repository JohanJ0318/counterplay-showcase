"""What collegiate teams do: the reference every recurring pattern is read against.

NC State Red's captain, 2026-09-27, on the trade feedback: comparing a team's
rounds after losing the opening duel with its own round win rate says little;
comparing them with other collegiate teams says whether it is a problem. So
every pattern and every round-based piece of advice is now read against
collegiate teams, counted in counterplay/league_rates.json
(tools/league_rates.py, 138 NECC placement matches).

Every reference is WEIGHTED BY THE TEAM'S OWN MIX. A team that played most of
its CT rounds on Nuke is compared with collegiate CT rounds on Nuke, not with
a pooled CT rate that is mostly Mirage and Dust2; a team's buys and opening
duels are split by side the same way.

`judge()` is the one test: a finding is flagged when the team is at least
MIN_GAP points off the collegiate rate AND an exact binomial test on the
team's own rounds puts the gap below P. Both, because a 12-point gap on 9
rounds is noise and a 3-point gap on 400 rounds is real but not worth a
Monday.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

REF_FILE = Path(__file__).resolve().parent.parent / "counterplay" / "league_rates.json"

# Percentage points below collegiate teams before a finding is worth acting on.
MIN_GAP = 8.0
# Two-sided exact binomial test on the team's own rounds.
P = 0.20

_REF: dict | None = None


def ref() -> dict:
    """The reference file, or {} when it is missing (every reading then falls
    back to showing the team's own numbers with no collegiate line)."""
    global _REF
    if _REF is None:
        try:
            _REF = json.loads(REF_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _REF = {}
    return _REF


def _weighted(parts):
    """parts: [(team_chances, league_hit, league_of)] -> (pct, hit, of) or None.

    The collegiate rate for each part, weighted by how many chances the team
    had in it. `hit` and `of` are the league's own counts across the parts,
    rescaled so hit/of prints the weighted rate, for the bar a card draws.
    """
    num = den = of = 0.0
    for n, lh, lo in parts:
        if n and lo:
            num += n * lh / lo
            den += n
            of += lo
    if not den:
        return None
    pct = 100.0 * num / den
    return pct, round(pct / 100.0 * of), int(of)


def opening(which: str, by_side: dict):
    """Collegiate rate after winning ("won") or losing ("lost") the opening
    duel, weighted by the team's own openings per side."""
    o = ref().get("opening", {})
    if which == "won":
        parts = [(by_side.get(s, {}).get("took", 0), o[s]["converted"], o[s]["took"])
                 for s in ("ct", "t") if s in o]
    else:
        parts = [(by_side.get(s, {}).get("lost", 0), o[s]["saved"], o[s]["lost"])
                 for s in ("ct", "t") if s in o]
    return _weighted(parts)


def side(which: str, maps: dict):
    """Collegiate CT or T win rate, weighted by the team's rounds on each map
    on that side. `maps` is team_stats()["maps"]."""
    s = ref().get("sides", {})
    parts = []
    for mp, m in maps.items():
        r = s.get(mp)
        if not r:
            continue
        n = m.get("you_ct" if which == "ct" else "you_t", 0)
        won = r["ct_won"] if which == "ct" else r["ct_rounds"] - r["ct_won"]
        parts.append((n, won, r["ct_rounds"]))
    return _weighted(parts)


def side_on_map(which: str, mp: str):
    """Collegiate CT or T win rate on one map."""
    r = ref().get("sides", {}).get(mp)
    if not r or not r["ct_rounds"]:
        return None
    won = r["ct_won"] if which == "ct" else r["ct_rounds"] - r["ct_won"]
    return 100.0 * won / r["ct_rounds"], won, r["ct_rounds"]


def buy(kind: str, by_side: dict):
    """Collegiate win rate for a buy kind, weighted by the team's rounds of
    that kind on each side. `by_side` is {side: rounds of this kind}."""
    b = ref().get("buys", {})
    parts = [(by_side.get(s, 0), b[s][kind][1], b[s][kind][0])
             for s in ("ct", "t") if kind in b.get(s, {})]
    return _weighted(parts)


def flash():
    """Collegiate win rate in rounds where a side blinded an opponent."""
    f = ref().get("flash", {})
    parts = [(f[s][0], f[s][1], f[s][0]) for s in ("ct", "t") if s in f]
    return _weighted(parts)


def flash_rate(which: str):
    """Collegiate share of flashes that blind an opponent ("enemy") or the
    thrower's own side ("own"), per grenade, from matches with blind data."""
    u = ref().get("utility", {})
    if not u.get("flash_thrown"):
        return None
    hit = u["flash_hit_enemy" if which == "enemy" else "flash_hit_own"]
    return 100.0 * hit / u["flash_thrown"], hit, u["flash_thrown"]


def unused_share():
    """Collegiate share of utility value still in hand at death."""
    u = ref().get("utility", {})
    if not u.get("value_spent"):
        return None
    return 100.0 * u["value_wasted"] / u["value_spent"]


def pval(k: int, n: int, p: float) -> float:
    """Exact two-sided binomial p-value of k successes in n at rate p."""
    if n <= 0 or p <= 0 or p >= 1:
        return 1.0
    lp = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
          + i * math.log(p) + (n - i) * math.log(1 - p) for i in range(n + 1)]
    cut = lp[k] + 1e-9
    return min(1.0, sum(math.exp(x) for x in lp if x <= cut))


def judge(hit: int, of: int, reference) -> int:
    """-1 clearly below collegiate teams, +1 clearly above, 0 otherwise."""
    if not reference or not of:
        return 0
    gap = 100.0 * hit / of - reference[0]
    if abs(gap) < MIN_GAP or pval(hit, of, reference[0] / 100.0) >= P:
        return 0
    return 1 if gap > 0 else -1
