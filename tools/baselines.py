"""Is the model, the calibration, or the data the bottleneck? Four arms.

    python tools/baselines.py              # every arm
    python tools/baselines.py LOGPRO SMALL # just these

Asked on 2026-10-14: would a bigger model (PyTorch) help, and would the 104
pro maps help? Before either, the cheap questions:

  LGB     the shipped setup: LightGBM, isotonic fitted on 25% of the
          training matches.
  LOGIT   logistic regression on the same state, with alive difference and
          the log equipment ratio as features, same isotonic layer. If this
          is about as good, model capacity is not what holds the scorer back,
          and a bigger model than LightGBM has nothing to add on this data.
  XFIT    LightGBM with CROSS-FITTED isotonic: five boosters on five match
          folds, the calibrator fitted on all their out-of-fold predictions,
          the five averaged at prediction time. Every training match then
          calibrates as well as trains, and which 25% happened to be the
          calibration slice stops deciding which fit a coach gets.
  PRO     the shipped setup, with the 104 pro maps added to the BOOSTER's
          training (tier_id tells them apart). Calibration stays collegiate
          only, and so does every test map.

  LOGPRO  LOGIT with the pro maps in its training, collegiate calibration.
  SMALL   LightGBM with 7 leaves, 300 rows a leaf, 200 trees, L2 5: is the
          gap to LOGIT the trees overfitting?

Two protocols, 20 seeds each, the same seeds for every arm:
  DIV   train on the 138 placement maps, test on the 26 division maps
        (tools/holdout.py; an easy draw, per tools/gapcheck.py).
  RAND  test on 26 random maps of all 164, train on the other 138.

Nothing here changes what ships. It is the measurement that decides it.
"""
from __future__ import annotations

import os
import statistics
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus, db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)
FOLDS = 5

db.init()
division = {r["match_key"] for r in db.query(
    """SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
        WHERE m.tier = 'league' AND d.created_at >= '2026-10-13'""")}
league = state_mod.build_states(*corpus.load_frames(tier="league"))
pro = state_mod.build_states(*corpus.load_frames(tier="pro"))
is_div = league["match_id"].isin(division).to_numpy()
place, div = league[~is_div], league[is_div]
CAT_IDX = [M.FEATURES.index(c) for c in M.CATEGORICAL]


def booster(seed):
    return lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
        random_state=seed, verbose=-1)


def fit_lgb(frame, seed):
    b = booster(seed)
    b.fit(frame[M.FEATURES], frame[M.LABEL].astype(int),
          categorical_feature=CAT_IDX)
    return lambda f: b.predict_proba(f[M.FEATURES])[:, 1]


NUM = ["alive_ct", "alive_t", "alive_diff", "equip_log_ratio", "equip_ct",
       "equip_t", "time_left", "bomb_planted", "time_since_plant"]
CAT = ["map_id", "round_type_id", "plant_site"]


def logit_frame(f):
    out = f[NUM[:2] + NUM[4:] + CAT].copy()
    out["alive_diff"] = f["alive_ct"] - f["alive_t"]
    out["equip_log_ratio"] = np.log((f["equip_ct"] + 500) / (f["equip_t"] + 500))
    return out


def fit_logit(frame, seed):
    pipe = make_pipeline(
        ColumnTransformer([("num", StandardScaler(), NUM),
                           ("cat", OneHotEncoder(handle_unknown="ignore"), CAT)]),
        LogisticRegression(max_iter=2000, C=1.0))
    pipe.fit(logit_frame(frame), frame[M.LABEL].astype(int))
    return lambda f: pipe.predict_proba(logit_frame(f))[:, 1]


def split_cal(pool, seed):
    s = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr, cal = next(s.split(pool, groups=pool["match_id"]))
    return pool.iloc[tr], pool.iloc[cal]


def calibrated(raw_fn, cal):
    iso = M._make_calibrator("isotonic")
    iso.fit(raw_fn(cal), cal[M.LABEL].astype(int))
    return lambda f: iso.predict(raw_fn(f))


def arm_lgb(pool, seed):
    tr, cal = split_cal(pool, seed)
    return calibrated(fit_lgb(tr, seed), cal)


def arm_logit(pool, seed):
    tr, cal = split_cal(pool, seed)
    return calibrated(fit_logit(tr, seed), cal)


def arm_pro(pool, seed):
    tr, cal = split_cal(pool, seed)
    return calibrated(fit_lgb(pd.concat([tr, pro], ignore_index=True), seed), cal)


def arm_xfit(pool, seed):
    ids = np.array(sorted(pool["match_id"].unique()))
    fold_of = dict(zip(ids, np.random.default_rng(seed).permutation(len(ids)) % FOLDS))
    folds = pool["match_id"].map(fold_of).to_numpy()
    oof = np.empty(len(pool))
    models = []
    for k in range(FOLDS):
        fn = fit_lgb(pool[folds != k], seed + k)
        oof[folds == k] = fn(pool[folds == k])
        models.append(fn)
    iso = M._make_calibrator("isotonic")
    iso.fit(oof, pool[M.LABEL].astype(int))
    return lambda f: iso.predict(np.mean([m(f) for m in models], axis=0))


def arm_logit_pro(pool, seed):
    tr, cal = split_cal(pool, seed)
    return calibrated(fit_logit(pd.concat([tr, pro], ignore_index=True), seed), cal)


def arm_small(pool, seed):
    """LightGBM cut down: does a smaller tree model close the gap to LOGIT?"""
    tr, cal = split_cal(pool, seed)
    b = lgb.LGBMClassifier(
        n_estimators=200, learning_rate=0.05, num_leaves=7,
        min_child_samples=300, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.9, reg_lambda=5.0, random_state=seed, verbose=-1)
    b.fit(tr[M.FEATURES], tr[M.LABEL].astype(int), categorical_feature=CAT_IDX)
    return calibrated(lambda f: b.predict_proba(f[M.FEATURES])[:, 1], cal)


ARMS = {"LGB": arm_lgb, "LOGIT": arm_logit, "XFIT": arm_xfit, "PRO": arm_pro,
        "LOGPRO": arm_logit_pro, "SMALL": arm_small}
if len(sys.argv) > 1:                 # python tools/baselines.py LOGPRO SMALL
    ARMS = {k: v for k, v in ARMS.items() if k in sys.argv[1:]}


def pick(frame, n_maps, seed):
    ids = np.array(sorted(frame["match_id"].unique()))
    chosen = set(np.random.default_rng(seed).choice(ids, size=n_maps, replace=False))
    mask = frame["match_id"].isin(chosen).to_numpy()
    return frame[~mask], frame[mask]


PROTOCOLS = {"DIV": lambda seed: (place, div),
             "RAND": lambda seed: pick(league, 26, seed)}

print(f"{place['match_id'].nunique()} placement, {div['match_id'].nunique()} "
      f"division, {pro['match_id'].nunique()} pro maps "
      f"({len(league)} league rows, {len(pro)} pro rows)\n", flush=True)
print("%-5s %-6s %8s %10s %8s %8s %8s" % (
    "proto", "arm", "passed", "ratio med", "range", "AUC", "logloss"))
for pname, protocol in PROTOCOLS.items():
    for aname, make in ARMS.items():
        ratios, aucs, losses = [], [], []
        for seed in SEEDS:
            pool, test = protocol(seed)
            p = np.clip(make(pool, seed)(test), 1e-6, 1 - 1e-6)
            y = test[M.LABEL].astype(int)
            ratios.append(M.expected_calibration_error(y, p)
                          / M.null_calibration_floor(p))
            aucs.append(roc_auc_score(y, p))
            losses.append(log_loss(y, p))
        ok = sum(r < M.ECE_FLOOR_MULTIPLE for r in ratios)
        print("%-5s %-6s %5d/20 %10.2f %4.1f-%-4.1f %8.4f %8.4f" % (
            pname, aname, ok, statistics.median(ratios), min(ratios),
            max(ratios), statistics.median(aucs), statistics.median(losses)),
            flush=True)
