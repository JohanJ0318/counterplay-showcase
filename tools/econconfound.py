"""Is the equipment slope equipment, or is it the better team being richer?

    python tools/econconfound.py

A stronger team wins more rounds, so it has more money, so it holds more
equipment. The win curve cannot tell that apart from equipment winning
rounds on its own, and if strength is hiding in the slope, every "you should
have spent more" the buy check prints is overstated.

The test: give each team a strength score, its round-win rate over the REST
of the match (this round left out, so it cannot contain the answer), and fit
the curve again with that score beside the equipment ratio. If the slope
holds, the equipment effect is real. If it falls, the curve had been
crediting equipment with some of what skill did, and the smaller slope is
the one a counterfactual ("had you bought instead") should use.

Bootstrapped by match, 200 draws, so the two slopes come with a range.
"""
from __future__ import annotations

import math
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def rows(tier: str = "league"):
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from app import buys, db
    keys = [r["match_key"] for r in db.query(
        "SELECT m.match_key FROM matches m JOIN demos d ON d.id = m.demo_id "
        "WHERE d.tier = ? AND d.status = 'parsed'", tier)]
    out = []
    for mk in keys:
        rounds, players = buys._load(mk)
        half = buys._halves(rounds, players)
        eq = {r["round_num"]: (r["equip_ct"], r["equip_t"]) for r in db.query(
            "SELECT round_num, equip_ct, equip_t FROM rounds WHERE match_key = ?", mk)}
        awps = {}                                   # (round, side) -> AWPs held
        for rn, ps in players.items():
            for p in ps:
                if p["loadout"] and "AWP" in p["loadout"].split(", "):
                    awps[(rn, p["side"])] = awps.get((rn, p["side"]), 0) + 1
        # Team A is CT in even halves. Overtime alternates too.
        res = []                                   # (round, a_won)
        for rn in sorted(rounds):
            a_ct = half[rn] % 2 == 0
            ct_won = bool(rounds[rn]["ct_won"])
            res.append((rn, ct_won == a_ct))
        wins_a, n = sum(w for _, w in res), len(res)
        for rn, a_won in res:
            if rn not in eq:
                continue
            a_ct = half[rn] % 2 == 0
            for team_a in (True, False):
                won = a_won if team_a else not a_won
                # this team's round-win rate over the rest of the match
                w = (wins_a - a_won) if team_a else ((n - wins_a) - (not a_won))
                rate = (w + 1) / (n - 1 + 2)               # shrunk, never 0 or 1
                side = "ct" if a_ct == team_a else "t"
                mine = eq[rn][0] if side == "ct" else eq[rn][1]
                theirs = eq[rn][1] if side == "ct" else eq[rn][0]
                other = "t" if side == "ct" else "ct"
                out.append((mk, side, float(mine), float(theirs),
                            math.log(rate / (1 - rate)), int(won),
                            min(awps.get((rn, side), 0), 1),
                            min(awps.get((rn, other), 0), 1)))
    return out


def matrix(data, with_strength, with_awp=False):
    ct = np.array([d[1] == "ct" for d in data], dtype=float)
    ratio = np.log(np.maximum([d[2] for d in data], 200.0) /
                   np.maximum([d[3] for d in data], 200.0))
    cols = [ct, ratio] + ([np.array([d[4] for d in data])] if with_strength else [])
    if with_awp:
        cols += [np.array([d[6] for d in data], float),
                 np.array([d[7] for d in data], float)]
    return np.column_stack(cols), np.array([d[5] for d in data])


def fit(data, with_strength, with_awp=False):
    from sklearn.linear_model import LogisticRegression
    X, y = matrix(data, with_strength, with_awp)
    lr = LogisticRegression(C=1e6, max_iter=5000).fit(X, y)
    return lr.intercept_[0], lr.coef_[0]


def held_out(data, keys, with_awp):
    """Median log-loss and ECE over 20 match splits, 1 in 5 held out."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    sys.path.insert(0, str(ROOT / "tools"))
    from econfit import ece
    X, y = matrix(data, True, with_awp)
    key = np.array([d[0] for d in data])
    ll, ec = [], []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        test = set(rng.permutation(keys)[: len(keys) // 5])
        te = np.array([k in test for k in key])
        lr = LogisticRegression(C=1e6, max_iter=5000).fit(X[~te], y[~te])
        p = lr.predict_proba(X[te])[:, 1]
        ll.append(log_loss(y[te], p))
        ec.append(ece(p, y[te]))
    return float(np.median(ll)), float(np.median(ec))


def main() -> int:
    data = rows()
    keys = sorted({d[0] for d in data})
    by = {}
    for d in data:
        by.setdefault(d[0], []).append(d)
    print(f"{len(data) // 2} rounds, {len(keys)} collegiate matches\n")
    b0, c0 = fit(data, False)
    b1, c1 = fit(data, True)
    print(f"equipment only:        slope {c0[1]:.3f}  CT {c0[0]:+.3f}  "
          f"intercept {b0:+.3f}")
    print(f"with team strength:    slope {c1[1]:.3f}  CT {c1[0]:+.3f}  "
          f"strength {c1[2]:.3f}  intercept {b1:+.3f}")
    rng = np.random.default_rng(7)
    s0, s1 = [], []
    for _ in range(200):
        pick = rng.choice(keys, size=len(keys))
        boot = [d for k in pick for d in by[k]]
        s0.append(fit(boot, False)[1][1])
        s1.append(fit(boot, True)[1][1])
    q = lambda v: (np.percentile(v, 5), np.percentile(v, 95))  # noqa: E731
    print(f"\nslope, 90% range over 200 match bootstraps")
    print(f"  equipment only       {q(s0)[0]:.3f} to {q(s0)[1]:.3f}")
    print(f"  with team strength   {q(s1)[0]:.3f} to {q(s1)[1]:.3f}")
    print(f"  kept: {c1[1] / c0[1]:.0%} of the slope survives the control")

    # Does holding an AWP matter beyond its price? The price is already in
    # the equipment ratio; this asks whether the gun is worth more than it
    # costs. Held out by match, the bar maps failed to clear.
    b2, c2 = fit(data, True, True)
    print()
    print(f"with AWPs too:         slope {c2[1]:.3f}  CT {c2[0]:+.3f}  "
          f"strength {c2[2]:.3f}  your AWP {c2[3]:+.3f}  their AWP {c2[4]:+.3f}  "
          f"intercept {b2:+.3f}")
    a = held_out(data, keys, False)
    b = held_out(data, keys, True)
    print(f"held out, 20 splits:   without AWPs log-loss {a[0]:.4f} ECE {a[1]:.4f}")
    print(f"                       with AWPs    log-loss {b[0]:.4f} ECE {b[1]:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
