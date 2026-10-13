"""Why the held-out test passed 19 of 20 when the sweep passed 12 of 20.

    python tools/gapcheck.py

tools/holdout.py (train on 138 placement maps, test on 26 division maps)
passed 19 of 20; tools/seedsweep.py (164 maps, random 25% test) passed 12
of 20. Three explanations, and the protocols differ in all three at once:

  SIZE   The gate divides ECE by the ECE a perfect model scores on the same
         predictions, and that floor GROWS as the test set shrinks (it is
         sampling noise). 26 test maps against 41 makes the gate easier.
  TRAIN  The held-out fits train on 75% of 138 maps (about 103), the sweep's
         on 56% of 164 (about 92).
  GAMES  The division maps are genuinely easier to be calibrated on.

Each arm below changes ONE thing from the held-out protocol, 20 seeds each:

  A  test on 26 random PLACEMENT maps instead of the division maps,
     train/calibrate on the other 112 placement maps.   (GAMES)
  B  the division test, but train/calibrate on 92 placement maps, the
     sweep's share.                                    (TRAIN)
  C  the sweep's protocol on all 164 maps, but with a 26-map test set.
                                                       (SIZE)
"""
from __future__ import annotations

import os
import statistics
import sys

import lightgbm as lgb
import numpy as np
from sklearn.model_selection import GroupShuffleSplit

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus, db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)

db.init()
division = {r["match_key"] for r in db.query(
    """SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
        WHERE m.tier = 'league' AND d.created_at >= '2026-10-13'""")}
rounds, events = corpus.load_frames(tier="league")
states = state_mod.build_states(rounds, events)
is_div = states["match_id"].isin(division).to_numpy()
place, div = states[~is_div], states[is_div]


def fit_and_score(train_pool, test, seed):
    """Calibrate on 25% of the pool's matches, train on the rest, score test."""
    split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr, cal = next(split.split(train_pool, groups=train_pool["match_id"]))
    X, y = train_pool[M.FEATURES], train_pool[M.LABEL].astype(int)
    booster = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
        random_state=seed, verbose=-1)
    booster.fit(X.iloc[tr], y.iloc[tr],
                categorical_feature=[M.FEATURES.index(c) for c in M.CATEGORICAL])
    calib = M._make_calibrator("isotonic")
    calib.fit(booster.predict_proba(X.iloc[cal])[:, 1], y.iloc[cal])
    p = M.WinProbabilityModel(booster, calib).predict(test)
    yt = test[M.LABEL].astype(int)
    return M.expected_calibration_error(yt, p) / M.null_calibration_floor(p)


def pick(frame, n_maps, seed):
    """n_maps whole matches from frame, and the rest."""
    ids = np.array(sorted(frame["match_id"].unique()))
    rng = np.random.default_rng(seed)
    chosen = set(rng.choice(ids, size=n_maps, replace=False))
    mask = frame["match_id"].isin(chosen).to_numpy()
    return frame[mask], frame[~mask]


def arm(name, make):
    ratios = []
    for seed in SEEDS:
        pool, test = make(seed)
        ratios.append(fit_and_score(pool, test, seed))
    ok = sum(r < M.ECE_FLOOR_MULTIPLE for r in ratios)
    print(f"{name}: passed {ok} of 20, median {statistics.median(ratios):.2f}, "
          f"range {min(ratios):.2f} to {max(ratios):.2f}", flush=True)


print(f"{place['match_id'].nunique()} placement maps, "
      f"{div['match_id'].nunique()} division maps\n")


def a(seed):                          # GAMES: placement test, same size
    test, pool = pick(place, 26, seed)
    return pool, test


def b(seed):                          # TRAIN: fewer training maps
    _drop, pool = pick(place, 138 - 123, seed)   # 123 maps: 92 train + 31 cal
    return pool, div


def c(seed):                          # SIZE: sweep protocol, 26-map test
    test, pool = pick(states, 26, seed)
    return pool, test


arm("A  placement test (26 maps), train on 112 placement", a)
arm("B  division test, train on 123 placement (sweep share)", b)
arm("C  all 164, random 26-map test", c)
