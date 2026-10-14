"""Does seeing positions beat the best tree model? Measured like everything else.

    python -m ml.evaluate                  # every arm, 20 seeds
    python -m ml.evaluate NET NETPRO --seeds 5

Same protocols, splits, calibration and gate as tools/baselines.py, so the
rows compare with that table directly:

  DIV   train on the 138 placement maps, test on the 26 division maps.
  RAND  test on 26 random collegiate maps, train on the other 138.

Calibration is the shipped isotonic layer, fitted on 25% of the training
matches that the model never trained on. Test maps are always collegiate.

Arms:
  SMALL     the bar: LightGBM cut down (tools/baselines.py's best tree arm),
            the shipped eleven features.
  SMALLPOS  the same trees plus hand-made position summaries (ml.data.POSFEAT:
            health per side, players in each site, spread, closest enemy).
            The cheap test of whether positions carry signal at all.
  MLP       the network without positions: same eleven numbers as SMALL.
            If NET beats SMALL but MLP does too, it was the model family.
  NET       the network with all ten players, college maps only.
  NETPRO    NET pretrained with the 104 pro maps, then fine-tuned on college.
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))

from app import db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay.schema import CATEGORICAL, FEATURES, LABEL, TIER_IDS  # noqa: E402

from . import data, train  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)

db.init()
snap = data.load()
st = snap.states
LEAGUE = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["league"])
PRO = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["pro"])
division = {r["match_key"] for r in db.query(
    """SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
        WHERE m.tier = 'league' AND d.created_at >= '2026-10-13'""")}
is_div = st["match_id"].isin(division).to_numpy()
PLACE, DIV = LEAGUE[~is_div[LEAGUE]], LEAGUE[is_div[LEAGUE]]
Y = st[LABEL].astype(int).to_numpy()


def tree_frame(idx, with_pos):
    f = st.iloc[idx][FEATURES].copy()
    if with_pos:
        for j, c in enumerate(data.POSFEAT):
            f[c] = snap.posfeat[idx, j]
    return f


def small_tree(tr, seed, with_pos):
    b = lgb.LGBMClassifier(
        n_estimators=200, learning_rate=0.05, num_leaves=7,
        min_child_samples=300, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.9, reg_lambda=5.0, random_state=seed, verbose=-1)
    b.fit(tree_frame(tr, with_pos), Y[tr],
          categorical_feature=[FEATURES.index(c) for c in CATEGORICAL])
    return lambda idx: b.predict_proba(tree_frame(idx, with_pos))[:, 1]


def net(tr, seed, use_players, pro):
    fit = train.train(snap, tr, seed=seed, use_players=use_players,
                      pretrain_idx=PRO if pro else None)
    return lambda idx: fit.predict(snap, idx)


ARMS = {
    "SMALL": lambda tr, s: small_tree(tr, s, False),
    "SMALLPOS": lambda tr, s: small_tree(tr, s, True),
    "MLP": lambda tr, s: net(tr, s, False, False),
    "NET": lambda tr, s: net(tr, s, True, False),
    "NETPRO": lambda tr, s: net(tr, s, True, True),
}


def split_cal(pool, seed):
    s = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr, cal = next(s.split(pool, groups=st["match_id"].to_numpy()[pool]))
    return pool[tr], pool[cal]


def rand_protocol(seed):
    ids = np.array(sorted(st["match_id"].iloc[LEAGUE].unique()))
    chosen = set(np.random.default_rng(seed).choice(ids, size=26, replace=False))
    test = np.array([st["match_id"].iat[i] in chosen for i in LEAGUE])
    return LEAGUE[~test], LEAGUE[test]


PROTOCOLS = {"DIV": lambda seed: (PLACE, DIV), "RAND": rand_protocol}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="*", default=list(ARMS))
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    args = ap.parse_args()
    seeds = SEEDS[:args.seeds]
    print(f"{len(PLACE)} placement rows, {len(DIV)} division rows, "
          f"{len(PRO)} pro rows; {len(seeds)} seeds\n")
    print("%-5s %-9s %8s %10s %10s %8s %8s %7s" % (
        "proto", "arm", "passed", "ratio med", "range", "AUC", "logloss", "secs"))
    for pname, protocol in PROTOCOLS.items():
        for aname in args.arms:
            t0 = time.time()
            ratios, aucs, losses = [], [], []
            for seed in seeds:
                pool, test = protocol(seed)
                tr, cal = split_cal(pool, seed)
                raw = ARMS[aname](tr, seed)
                iso = M._make_calibrator("isotonic")
                iso.fit(raw(cal), Y[cal])
                p = np.clip(iso.predict(raw(test)), 1e-6, 1 - 1e-6)
                ratios.append(M.expected_calibration_error(Y[test], p)
                              / M.null_calibration_floor(p))
                aucs.append(roc_auc_score(Y[test], p))
                losses.append(log_loss(Y[test], p))
            ok = sum(r < M.ECE_FLOOR_MULTIPLE for r in ratios)
            print("%-5s %-9s %5d/%-2d %10.2f %4.1f-%-5.1f %8.4f %8.4f %7.0f" % (
                pname, aname, ok, len(seeds), statistics.median(ratios),
                min(ratios), max(ratios), statistics.median(aucs),
                statistics.median(losses), time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
