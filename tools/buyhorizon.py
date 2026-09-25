"""How far ahead can the buy check look, and how sure may the later rounds be?

    python tools/buyhorizon.py

For every real call in the collegiate corpus, the simulation predicts the
rounds that team will win over the next H rounds of the half, this one
included. That is compared with the rounds it actually won over the same
window. Two numbers per setting:

  slope  what happened, regressed on what was predicted, across calls
         (both centred). 1.0 means the spread is right; below 1 means the
         predictions are more spread out than the outcomes, i.e.
         overconfident, which is what made the first version flag too much.
  bias   mean predicted minus mean happened.

FUTURE_SLOPE pulls every round after this one toward 50% on the logit.
The setting to use is the one whose slope is nearest 1 at the horizon the
check uses; economy.py records the choice.
"""
from __future__ import annotations

import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def measure(keys, buys, E, horizon, slope):
    E.HORIZON, E.FUTURE_SLOPE = horizon, slope
    pred, real = [], []
    for mk in keys:
        calls = buys.match_calls(mk)
        won = {(c["round"], c["side"]): c["won"] for c in calls}
        for c in calls:
            window = [won.get((c["round"] + k, c["side"])) for k in range(c["rounds"])]
            if any(w is None for w in window):
                continue           # a round in the window was not judged
            pred.append(c["v"])
            real.append(sum(window))
    pred, real = np.array(pred), np.array(real, dtype=float)
    pc, rc = pred - pred.mean(), real - real.mean()
    return (float((pc * rc).sum() / (pc * pc).sum()),
            float(pred.mean() - real.mean()), len(pred))


def main() -> int:
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from app import buys, db
    from counterplay import economy as E
    keys = [r["match_key"] for r in db.query(
        "SELECT m.match_key FROM matches m JOIN demos d ON d.id = m.demo_id "
        "WHERE d.tier = 'league' AND d.status = 'parsed'")]
    print(f"{len(keys)} collegiate matches\n")
    print(f"{'horizon':>7s} {'future slope':>12s} {'slope':>6s} {'bias':>7s} {'calls':>6s}")
    for horizon in (2, 3, 5, 12):
        for fs in (1.0, 0.7, 0.5, 0.3):
            sl, bias, n = measure(keys, buys, E, horizon, fs)
            print(f"{horizon:7d} {fs:12.1f} {sl:6.2f} {bias:+7.3f} {n:6d}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
