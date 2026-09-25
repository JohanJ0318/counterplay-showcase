"""How much does a round's equipment decide it? The one curve the buy analysis needs.

    python tools/econfit.py             20 seeds, the number to quote
    python tools/econfit.py --quick     5 seeds

WHY A CURVE AND NOT A MODEL
---------------------------
"The optimal buy" is mostly arithmetic. Loss bonus, kill rewards and the
plant bonus are fixed rules, so what a team will have next round under each
choice (full buy, force, save) is computed, not learned. The only thing that
needs data is how likely a round is won given what each side is holding:
P(win | your equipment, theirs, side). That is a handful of parameters, where
the decision engine is a model of a whole round unfolding, which is why this
can pass on a corpus the decision engine cannot.

WHAT IT MEASURES
----------------
One row per side per round: that side's freeze-end equipment (rounds.equip_ct
or equip_t, the same reading player_rounds.equip_value sums to), the other
side's, which side, and whether it won. Candidates, simplest first:

    side          the side's base rate and nothing else: the bar to beat
    log ratio     side + ln(yours) - ln(theirs), one slope
    log both      side + ln(yours) + ln(theirs), two slopes
    log + map     log both, plus a term per map
    ratio + sq    log ratio, plus a signed square, so the curve can be
                  steeper in the middle than a plain logistic allows

Held out by MATCH, never by round: rounds of one match share players, so a
round-level split would let the test set leak into the training set. Twenty
shuffles of the match split, as tools/seedsweep.py does for the decision
engine, and the median is the number. A single seed is never quoted.

Log-loss and Brier say how good the probabilities are; ECE says whether a
predicted 70% wins 70% of the time, which is what a coach is actually shown.
The noise floor for ECE is bootstrapped off the model's own predictions,
the method calibcheck.py settled on: labels drawn from the predictions
themselves, so the floor is what a PERFECT model of this shape would score.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BINS = 10


def load(tier: str | None):
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from app import db
    rows = db.query(
        "SELECT r.match_key, r.round_num, r.map_name, r.equip_ct, r.equip_t, "
        "       r.ct_won "
        "FROM rounds r JOIN matches m ON m.match_key = r.match_key "
        "JOIN demos d ON d.id = m.demo_id "
        "WHERE d.status = 'parsed'" + (" AND d.tier = ?" if tier else ""),
        *([tier] if tier else []))
    out = []
    for r in rows:
        for side in ("ct", "t"):
            mine = r["equip_ct"] if side == "ct" else r["equip_t"]
            theirs = r["equip_t"] if side == "ct" else r["equip_ct"]
            won = bool(r["ct_won"]) == (side == "ct")
            out.append((r["match_key"], r["map_name"], side,
                        float(mine), float(theirs), int(won)))
    return out


def features(rows, kind, maps):
    # $200 floor: a team holding nothing is five default pistols, and ln(0)
    # is not a number.
    mine = np.log(np.maximum([r[3] for r in rows], 200.0) / 1000.0)
    theirs = np.log(np.maximum([r[4] for r in rows], 200.0) / 1000.0)
    ct = np.array([r[2] == "ct" for r in rows], dtype=float)
    if kind == "side":
        return ct[:, None]
    if kind == "log ratio":
        return np.column_stack([ct, mine - theirs])
    if kind == "ratio + sq":
        d = mine - theirs
        return np.column_stack([ct, d, d * np.abs(d)])
    cols = [ct, mine, theirs]
    if kind == "log + map":
        for m in maps[1:]:
            mm = np.array([r[1] == m for r in rows], dtype=float)
            cols += [mm, mm * ct]      # a map is CT- or T-sided, not just hard
    return np.column_stack(cols)


def ece(p, y):
    edges = np.linspace(0, 1, BINS + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, BINS - 1)
    tot = 0.0
    for b in range(BINS):
        m = idx == b
        if m.any():
            tot += m.sum() * abs(p[m].mean() - y[m].mean())
    return tot / len(p)


def floor(p, rng, draws=200):
    """ECE a perfectly calibrated model with these predictions would score."""
    return float(np.median([ece(p, (rng.random(len(p)) < p).astype(float))
                            for _ in range(draws)]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tier")
    args = ap.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss

    rows = load(args.tier)
    matches = sorted({r[0] for r in rows})
    maps = sorted({r[1] for r in rows})
    y = np.array([r[5] for r in rows], dtype=float)
    key = np.array([r[0] for r in rows])
    print(f"{len(rows) // 2} rounds, {len(matches)} matches, {len(maps)} maps"
          f"{' (tier ' + args.tier + ')' if args.tier else ''}\n")

    seeds = range(5 if args.quick else 20)
    kinds = ["side", "log ratio", "log both", "log + map", "ratio + sq"]
    got = {k: {"ll": [], "brier": [], "ece": [], "floor": []} for k in kinds}
    for seed in seeds:
        rng = np.random.default_rng(seed)
        test_m = set(rng.permutation(matches)[: len(matches) // 5])
        te = np.array([k in test_m for k in key])
        for kind in kinds:
            X = features(rows, kind, maps)
            lr = LogisticRegression(C=1.0, max_iter=2000).fit(X[~te], y[~te])
            p = lr.predict_proba(X[te])[:, 1]
            got[kind]["ll"].append(log_loss(y[te], p))
            got[kind]["brier"].append(brier_score_loss(y[te], p))
            got[kind]["ece"].append(ece(p, y[te]))
            got[kind]["floor"].append(floor(p, rng))

    print(f"held out by match, 1 in 5, median of {len(seeds)} seeds\n")
    print(f"{'model':12s} {'log-loss':>9s} {'brier':>7s} {'ECE':>7s} "
          f"{'floor':>7s} {'ECE/floor':>9s}")
    for kind in kinds:
        g = {k: float(np.median(v)) for k, v in got[kind].items()}
        print(f"{kind:12s} {g['ll']:9.4f} {g['brier']:7.4f} {g['ece']:7.4f} "
              f"{g['floor']:7.4f} {g['ece'] / g['floor']:9.2f}")

    # The curve itself, fitted on everything, at the buys coaches name.
    X = features(rows, "log both", maps)
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(X, y)
    b = lr.coef_[0]
    print(f"\nlog both on every round: intercept {lr.intercept_[0]:+.3f}, "
          f"CT {b[0]:+.3f}, ln(yours) {b[1]:+.3f}, ln(theirs) {b[2]:+.3f}")
    buys = [("eco", 2500), ("half", 10000), ("force", 15000), ("full", 22000),
            ("full+", 26000)]
    for side in ("ct", "t"):
        print(f"\n  P(win) as {side.upper()}, yours down, theirs across")
        print("  " + " " * 14 + "".join(f"{n:>8s}" for n, _ in buys))
        for n, mine in buys:
            cells = []
            for _, theirs in buys:
                x = features([("", maps[0], side, mine, theirs, 0)], "log both", maps)
                cells.append(lr.predict_proba(x)[0, 1])
            print(f"  {n:>6s} ${mine / 1000:>4.1f}k " +
                  "".join(f"{c:8.0%}" for c in cells))

    # What the rounds themselves say, binned, so the curve can be checked
    # against raw counts rather than trusted.
    print("\n  raw: rounds won, by your buy against theirs (both sides)")
    edges = [0, 5000, 12000, 18000, 1e9]
    names = ["eco", "half", "force", "full"]
    mine = np.array([r[3] for r in rows])
    theirs = np.array([r[4] for r in rows])
    print("  " + " " * 7 + "".join(f"{n:>14s}" for n in names))
    for i, n in enumerate(names):
        cells = []
        for j in range(len(names)):
            m = ((mine >= edges[i]) & (mine < edges[i + 1]) &
                 (theirs >= edges[j]) & (theirs < edges[j + 1]))
            cells.append(f"{y[m].mean():5.0%} of {int(m.sum()):4d}" if m.sum()
                         else "            -")
        print(f"  {n:>5s}  " + "".join(f"{c:>14s}" for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
