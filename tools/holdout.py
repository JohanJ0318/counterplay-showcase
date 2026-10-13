"""The decision engine scored ONCE on matches it has never seen.

    python tools/holdout.py

Every earlier measurement re-split one corpus (tools/seedsweep.py), which
measures split sensitivity, not how the model does on new games (TODO.md,
"Stop chasing features"). On 2026-10-13 a real held-out set existed for the
first time: 26 NECC Fall 2026 division maps (weeks 1-2), played after every
placement map the model trains on and never used to choose anything.

The production setup, reproduced: train and calibrate on the 138 placement
maps only, split train/calibrate 20 ways (the split is what decides which
fit a coach gets), and score EVERY fit on the same 26 unseen maps.

THE PASS RULE WAS WRITTEN DOWN BEFORE THE RUN, AND IS NOT TO BE MOVED:
at least 18 of the 20 fits under the 2.5x gate. A coach gets one fit, so it
has to be calibrated almost every time, not usually. Anything less is a
fail, and the answer is not to rerun until it passes.
"""
from __future__ import annotations

import os
import statistics
import sys

import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus, db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)
NEEDED = 18
# Demos parsed from the division weeks 1-2 folder (2026-10-13).
HOLDOUT_SINCE = "2026-10-13"

db.init()
holdout = {r["match_key"] for r in db.query(
    """SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
        WHERE m.tier = 'league' AND d.created_at >= ?""", HOLDOUT_SINCE)}

rounds, events = corpus.load_frames(tier="league")
states = state_mod.build_states(rounds, events)
test_mask = states["match_id"].isin(holdout).to_numpy()
old, new = states[~test_mask], states[test_mask]
print(f"train/calibrate on {old['match_id'].nunique()} placement maps "
      f"({len(old)} rows); test on {new['match_id'].nunique()} unseen "
      f"division maps ({len(new)} rows)\n")

X_new, y_new = new[M.FEATURES], new[M.LABEL].astype(int)
print("%-6s %8s %8s %8s %8s  %s" % ("seed", "AUC", "ECE", "floor", "ratio", "gate"))
ratios = []
for seed in SEEDS:
    split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr, cal = next(split.split(old, groups=old["match_id"]))
    X, y = old[M.FEATURES], old[M.LABEL].astype(int)
    booster = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
        random_state=seed, verbose=-1)
    booster.fit(X.iloc[tr], y.iloc[tr],
                categorical_feature=[M.FEATURES.index(c) for c in M.CATEGORICAL])
    calib = M._make_calibrator("isotonic")
    calib.fit(booster.predict_proba(X.iloc[cal])[:, 1], y.iloc[cal])
    p = M.WinProbabilityModel(booster, calib).predict(new)
    ece = M.expected_calibration_error(y_new, p)
    floor = M.null_calibration_floor(p)
    ratio = ece / floor
    ratios.append(ratio)
    print("%-6d %8.4f %8.4f %8.4f %8.2f  %s" % (
        seed, roc_auc_score(y_new, p), ece, floor, ratio,
        "PASS" if ratio < M.ECE_FLOOR_MULTIPLE else "FAIL"))

passed = sum(r < M.ECE_FLOOR_MULTIPLE for r in ratios)
print(f"\npassed {passed} of {len(ratios)}; median ratio "
      f"{statistics.median(ratios):.2f}; min {min(ratios):.2f} max {max(ratios):.2f}")
print("VERDICT:", "PASS" if passed >= NEEDED else "FAIL",
      f"(rule fixed before the run: {NEEDED} of 20)")
