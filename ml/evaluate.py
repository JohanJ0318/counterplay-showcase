"""Does seeing positions beat the best tree model? Measured like everything else.

    python -m ml.evaluate                  # every arm, 20 seeds
    python -m ml.evaluate NET NETPRO --seeds 5

Same protocols, splits, calibration and gate as tools/baselines.py, so the
rows compare with that table directly:

  DIV   train on the 138 placement maps, test on the 26 division maps.
  RAND  test on 26 random collegiate maps, train on the other 138.

Calibration is the shipped isotonic layer, fitted on 25% of the training
matches that the model never trained on. Test maps are always collegiate.

  NEW   train on every college map parsed before 2026-10-23, test on the
        NECC weeks 3-4 maps parsed that day: maps no model has seen.
  SWEEP tools/seedsweep.py's split: 25% of all 164 college maps as test.
        DIV is tools/holdout.py's protocol, whose rule is 18 of 20.

Arms:
  LGB       the shipped LightGBM (counterplay/model.py), unchanged.
  SMALL     the bar: LightGBM cut down (tools/baselines.py's best tree arm),
            the shipped eleven features.
  SMALLPOS  the same trees plus hand-made position summaries (ml.data.POSFEAT:
            health per side, players in each site, spread, closest enemy).
            The cheap test of whether positions carry signal at all.
  MLP       the network without positions: same eleven numbers as SMALL.
            If NET beats SMALL but MLP does too, it was the model family.
  NET       the network with all ten players, college maps only.
  NETPRO    NET pretrained with the 104 pro maps, then fine-tuned on college.
  NETESEA   the same, pretrained with ESEA League maps (tools/esea.py).
  NETBOTH   pretrained with pro and ESEA together.
  SMALLPOS+ESEA  SMALLPOS with the ESEA maps as extra training rows.
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
from . import extras  # noqa: E402
snap.extras = extras.load(snap)
st = snap.states
LEAGUE = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["league"])
PRO = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["pro"])
ESEA = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["esea"])
# ESEA's Open and Intermediate rounds: the two divisions that predicted
# NECC divisions best when trained on alone (Open for D1, D3 and D4,
# Intermediate for D2; ml/README.md). Main never did.
_lvl = st["level_ct"].to_numpy()
ESEA_MATCHED = ESEA[np.isin(_lvl[ESEA], ["esea_open", "esea_intermediate"])]
EXTRA = {None: None, "pro": PRO, "esea": ESEA,
         "both": np.concatenate([PRO, ESEA]), "matched": ESEA_MATCHED}
def _league_since(start, end="9999"):
    return {r["match_key"] for r in db.query(
        """SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
            WHERE m.tier = 'league' AND d.created_at >= ? AND d.created_at < ?""",
        start, end)}


# Weeks 1-2 of the NECC divisions arrived 2026-10-13, weeks 3-4 on
# 2026-10-23. NEW is the fair test: every college map parsed before weeks
# 3-4 trains, and the weeks 3-4 maps, which no model has seen, are the test.
is_div = st["match_id"].isin(_league_since("2026-10-13", "2026-10-23")).to_numpy()
is_new = st["match_id"].isin(_league_since("2026-10-23")).to_numpy()
OLD = LEAGUE[~is_new[LEAGUE]]
PLACE, DIV = OLD[~is_div[OLD]], OLD[is_div[OLD]]
NEW = LEAGUE[is_new[LEAGUE]]
Y = st[LABEL].astype(int).to_numpy()


LEVEL_COLS = ["level_ct_id", "level_t_id"]


def tree_frame(idx, with_pos, with_lvl=False):
    f = st.iloc[idx][FEATURES].copy()
    if with_pos:
        for j, c in enumerate(data.POSFEAT):
            f[c] = snap.posfeat[idx, j]
    if with_lvl:
        for c in LEVEL_COLS:
            f[c] = st[c].to_numpy()[idx]
    return f


def shipped_tree(tr, seed):
    """counterplay/model.py's booster, unchanged: the reference."""
    b = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
        random_state=seed, verbose=-1)
    b.fit(tree_frame(tr, False), Y[tr],
          categorical_feature=[FEATURES.index(c) for c in CATEGORICAL])
    return lambda idx: b.predict_proba(tree_frame(idx, False))[:, 1]


def small_tree(tr, seed, with_pos, with_lvl=False):
    # counterplay/model.py's params, so this and the scorer cannot drift.
    b = lgb.LGBMClassifier(**M.SMALL_PARAMS, random_state=seed, verbose=-1)
    frame = tree_frame(tr, with_pos, with_lvl)
    cats = [frame.columns.get_loc(c) for c in CATEGORICAL
            + (LEVEL_COLS if with_lvl else [])]
    b.fit(frame, Y[tr], categorical_feature=cats)
    return lambda idx: b.predict_proba(tree_frame(idx, with_pos, with_lvl))[:, 1]


_TIMED: dict = {}


def _timed():
    """The event snapshot with the timed moments (ml/data.load_timed)
    appended AFTER it, so every event row keeps its index, and per match
    the indices of its timed rows. Built once, on first use."""
    if not _TIMED:
        import pandas as pd
        t = data.load_timed(snap)
        t.extras = extras.load(t, name="_timed")
        n = len(snap.states)
        merged = data.Snapshots(
            pd.concat([snap.states, t.states], ignore_index=True),
            np.concatenate([snap.players, t.players]),
            np.concatenate([snap.posfeat, t.posfeat]),
            np.concatenate([snap.has_positions, t.has_positions]))
        merged.extras = extras.Extras(*(np.concatenate([getattr(snap.extras, f),
                                                        getattr(t.extras, f)])
                                        for f in extras.Extras.__dataclass_fields__))
        by_match: dict = {}
        for i, m in enumerate(t.states["match_id"].to_numpy()):
            by_match.setdefault(m, []).append(n + i)
        _TIMED.update(snap=merged, by_match=by_match)
    return _TIMED


def _plus_timed(idx):
    if idx is None:
        return None
    by = _timed()["by_match"]
    more = [j for m in np.unique(st["match_id"].to_numpy()[idx]) for j in by.get(m, ())]
    return np.concatenate([np.asarray(idx), np.asarray(more, dtype=np.int64)])


def net(tr, seed, use_players, extra=None, timed=False, copies=1, **kw):
    """`timed` trains on the 2-second moments too (tested on events only);
    `copies` averages that many networks trained from different seeds."""
    S = _timed()["snap"] if timed else snap
    tr_ = _plus_timed(tr) if timed else tr
    pre = _plus_timed(EXTRA[extra]) if timed else EXTRA[extra]
    fits = [train.train(S, tr_, seed=seed * 100 + j, use_players=use_players,
                        pretrain_idx=pre, **kw) for j in range(copies)]
    return lambda idx: np.mean([f.predict(S, idx) for f in fits], axis=0)


ARMS = {
    "LGB": shipped_tree,
    "SMALL": lambda tr, s: small_tree(tr, s, False),
    "SMALLPOS": lambda tr, s: small_tree(tr, s, True),
    # The trees get ESEA rows as extra training rows (tier_id is a feature,
    # so they can tell them apart); calibration and test stay collegiate.
    "SMALLPOS+ESEA": lambda tr, s: small_tree(np.concatenate([tr, ESEA]), s, True),
    "MLP": lambda tr, s: net(tr, s, False),
    "NET": lambda tr, s: net(tr, s, True),
    "NETPRO": lambda tr, s: net(tr, s, True, "pro"),
    "NETESEA": lambda tr, s: net(tr, s, True, "esea"),
    "NETBOTH": lambda tr, s: net(tr, s, True, "both"),
    # Taoish's point (2026-10-14): divisions differ, some ESEA ones are
    # close to some NECC ones. LVL gives each side's level as an input;
    # MATCH pretrains only on the ESEA divisions closest to NECC.
    "SMALLPOS+ESEA+LVL": lambda tr, s: small_tree(np.concatenate([tr, ESEA]), s, True, True),
    "NETESEA+LVL": lambda tr, s: net(tr, s, True, "esea", use_levels=True),
    "NETMATCH": lambda tr, s: net(tr, s, True, "matched"),
    # Longer pretraining (patience 10, up to 80 epochs) and half as many
    # ESEA rows as college rows kept in the college stage.
    "NETLONG": lambda tr, s: net(tr, s, True, "esea", pretrain_patience=10,
                                 pretrain_epochs=80, keep_mix=0.5),
    # Per-player movement, weapon and grenades on top of NETESEA.
    "NETKIT": lambda tr, s: net(tr, s, True, "esea", use_kit=True),
    # 2026-10-23 (ml/extras.py). VIEW: which callout each player stands in
    # and what the enemy can see of them. LESSONS: also learn who dies next
    # and whether the bomb goes down. PLUS: both.
    "NETVIEW": lambda tr, s: net(tr, s, True, "esea", use_callouts=True, use_vision=True),
    "NETLESSONS": lambda tr, s: net(tr, s, True, "esea", aux=True),
    "NETPLUS": lambda tr, s: net(tr, s, True, "esea", use_callouts=True,
                                 use_vision=True, aux=True),
    # The trees and a network averaged before calibration: they err
    # differently, so the average can beat both.
    "ENS": lambda tr, s: _average(ARMS["SMALLPOS+ESEA"](tr, s), ARMS["NETESEA"](tr, s)),
    "ENSPLUS": lambda tr, s: _average(ARMS["SMALLPOS+ESEA"](tr, s), ARMS["NETPLUS"](tr, s)),
    "ENSLESSONS": lambda tr, s: _average(ARMS["SMALLPOS+ESEA"](tr, s),
                                         ARMS["NETLESSONS"](tr, s)),
    # Later on 2026-10-23, each on top of NETLESSONS: T the 2-second moments,
    # M more lessons (who kills next, how soon, how the round ends), W the
    # lessons weighted 0.6 instead of 0.3, LONG the longer pretraining,
    # REG callouts grouped into regions every map shares.
    "NETT": lambda tr, s: net(tr, s, True, "esea", aux=True, timed=True),
    "NETTM": lambda tr, s: net(tr, s, True, "esea", aux=True, timed=True,
                               more_lessons=True),
    "NETTMW": lambda tr, s: net(tr, s, True, "esea", aux=True, timed=True,
                                more_lessons=True, aux_weight=0.6),
    "NETTMLONG": lambda tr, s: net(tr, s, True, "esea", aux=True, timed=True,
                                   more_lessons=True, pretrain_patience=10,
                                   pretrain_epochs=80, keep_mix=0.5),
    "NETTMREG": lambda tr, s: net(tr, s, True, "esea", aux=True, timed=True,
                                  more_lessons=True, use_regions=True),
    # The timed moments cost ranking on both tests (screen of 2026-10-23,
    # ml/README.md), so the rest are retested on event rows only.
    "NETM": lambda tr, s: net(tr, s, True, "esea", aux=True, more_lessons=True),
    "NETMW": lambda tr, s: net(tr, s, True, "esea", aux=True, more_lessons=True,
                               aux_weight=0.6),
    "NETMREG": lambda tr, s: net(tr, s, True, "esea", aux=True, more_lessons=True,
                                 use_regions=True),
    "NETLESSONSx5": lambda tr, s: net(tr, s, True, "esea", aux=True, copies=5),
    "NETMx5": lambda tr, s: net(tr, s, True, "esea", aux=True, more_lessons=True,
                                copies=5),
}


def _average(a, b):
    return lambda idx: (a(idx) + b(idx)) / 2.0


def split_cal(pool, seed):
    s = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr, cal = next(s.split(pool, groups=st["match_id"].to_numpy()[pool]))
    return pool[tr], pool[cal]


def rand_protocol(seed):
    ids = np.array(sorted(st["match_id"].iloc[LEAGUE].unique()))
    chosen = set(np.random.default_rng(seed).choice(ids, size=26, replace=False))
    test = np.array([st["match_id"].iat[i] in chosen for i in LEAGUE])
    return LEAGUE[~test], LEAGUE[test]


def sweep_protocol(seed):
    """tools/seedsweep.py's split, exactly: model._split3's outer split, 25%
    of the 164 college maps as test. split_cal then makes its inner one."""
    outer = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    rest, test = next(outer.split(LEAGUE, groups=st["match_id"].to_numpy()[LEAGUE]))
    return LEAGUE[rest], LEAGUE[test]


PROTOCOLS = {"DIV": lambda seed: (PLACE, DIV), "NEW": lambda seed: (OLD, NEW),
             "RAND": rand_protocol,
             "SWEEP": sweep_protocol}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms", nargs="*", default=list(ARMS))
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--protocols", default="DIV,RAND",
                    help="comma list of DIV, RAND, SWEEP")
    args = ap.parse_args()
    seeds = SEEDS[:args.seeds]
    print(f"{len(PLACE)} placement rows, {len(DIV)} division rows, "
          f"{len(NEW)} weeks 3-4 rows, "
          f"{len(PRO)} pro rows, {len(ESEA)} ESEA rows; {len(seeds)} seeds\n")
    # ECE itself beside the ratio: the floor shrinks as the test grows, so
    # the ratio (and "passed") is stricter on a big test like NEW's 148
    # maps; ECE compares across protocols, the ratio does not.
    print("%-5s %-17s %8s %10s %10s %8s %8s %8s %7s" % (
        "proto", "arm", "passed", "ratio med", "range", "ECE", "AUC", "logloss", "secs"))
    for pname in args.protocols.split(","):
        protocol = PROTOCOLS[pname]
        for aname in args.arms:
            t0 = time.time()
            ratios, aucs, losses, eces = [], [], [], []
            for seed in seeds:
                pool, test = protocol(seed)
                tr, cal = split_cal(pool, seed)
                raw = ARMS[aname](tr, seed)
                iso = M._make_calibrator("isotonic")
                iso.fit(raw(cal), Y[cal])
                p = np.clip(iso.predict(raw(test)), 1e-6, 1 - 1e-6)
                eces.append(M.expected_calibration_error(Y[test], p))
                ratios.append(eces[-1] / M.null_calibration_floor(p))
                aucs.append(roc_auc_score(Y[test], p))
                losses.append(log_loss(Y[test], p))
            ok = sum(r < M.ECE_FLOOR_MULTIPLE for r in ratios)
            print("%-5s %-17s %5d/%-2d %10.2f %4.1f-%-5.1f %8.4f %8.4f %8.4f %7.0f" % (
                pname, aname, ok, len(seeds), statistics.median(ratios),
                min(ratios), max(ratios), statistics.median(eces),
                statistics.median(aucs),
                statistics.median(losses), time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
