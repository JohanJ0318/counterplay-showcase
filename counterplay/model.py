"""Round win-probability model.

Deliberately boring: gradient-boosted trees on tabular features. No GPU, no
sequence model. The thing that matters here is not accuracy, it is CALIBRATION
— when the model says 30%, that side must win about 30% of the time. An
uncalibrated model produces confident nonsense a good coach spots in one look.

Raw LightGBM is reliably overconfident at the extremes on this problem, so the
booster is wrapped in an isotonic calibrator fitted on a held-out split. The
three-way split is by MATCH, never by row: rows within a round are highly
correlated and a random split leaks, flattering every metric below.
"""
from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

from .schema import CATEGORICAL, FEATURES, LABEL

# Gate on Expected Calibration Error (sample-weighted MEAN deviation), not on
# the max across bins. Max-of-bins is a badly noisy statistic: a PERFECTLY
# calibrated model measured on 7,700 rows scores ~0.034 on it from sampling
# noise alone, so a 0.05 max-error gate is mostly measuring your test-set size.
# ECE on the same data lands near 0.012. Run null_calibration_floor() below to
# see the noise floor for your own row count before trusting either number.
# The gate is RELATIVE to the noise floor, not absolute. A fixed threshold
# silently becomes stricter as your test set shrinks, so a small dataset would
# fail for having few rows rather than for being miscalibrated. Empirically an
# uncalibrated booster lands 4-7x above the floor and a calibrated one lands
# around 2x, so 2.5x separates them cleanly at any size.
ECE_FLOOR_MULTIPLE = 2.5


def expected_calibration_error(y_true, p, bins: int = 10) -> float:
    """Sample-weighted mean gap between predicted and observed frequency."""
    y_true = np.asarray(y_true)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e-9, 1 + 1e-9
    idx = np.digitize(p, edges[1:-1])
    total, n = 0.0, len(p)
    for k in range(bins):
        m = idx == k
        if m.sum() == 0:
            continue
        total += m.sum() / n * abs(y_true[m].mean() - p[m].mean())
    return float(total)


def null_calibration_floor(n: int, bins: int = 10, trials: int = 40,
                           seed: int = 0) -> float:
    """ECE a perfectly calibrated model would score on n rows, from noise alone.

    Compare your model's ECE against this, not against zero.
    """
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(trials):
        p = rng.uniform(0, 1, n)
        y = (rng.random(n) < p).astype(int)
        vals.append(expected_calibration_error(y, p, bins))
    return float(np.mean(vals))


@dataclass
class Report:
    auc: float
    brier: float
    logloss: float
    ece: float
    ece_floor: float
    max_calib_error: float
    n_train: int
    n_calib: int
    n_test: int

    @property
    def ece_ratio(self) -> float:
        return self.ece / self.ece_floor if self.ece_floor else float("inf")

    @property
    def passes(self) -> bool:
        return self.ece_ratio < ECE_FLOOR_MULTIPLE

    def __str__(self):
        verdict = "PASS" if self.passes else "FAIL — do not ship"
        return (f"  AUC              {self.auc:.4f}\n"
                f"  Brier            {self.brier:.4f}   (lower is better)\n"
                f"  Log loss         {self.logloss:.4f}\n"
                f"  ECE              {self.ece:.4f}   {verdict}\n"
                f"                   {self.ece_ratio:.2f}x the noise floor "
                f"of {self.ece_floor:.4f}  (gate: {ECE_FLOOR_MULTIPLE}x)\n"
                f"  Max calib error  {self.max_calib_error:.4f}   "
                f"(diagnostic only — noisy)\n"
                f"  Rows             {self.n_train} train / {self.n_calib} calib "
                f"/ {self.n_test} test")


class WinProbabilityModel:
    """LightGBM booster plus an isotonic calibration layer."""

    def __init__(self, booster, calibrator):
        self.booster = booster
        self.calibrator = calibrator

    def predict(self, states: pd.DataFrame) -> np.ndarray:
        raw = self.booster.predict_proba(states[FEATURES])[:, 1]
        return self.calibrator.predict(raw)


def _split3(states, seed):
    """Three disjoint match-level splits: train / calibrate / test."""
    groups = states["match_id"]
    outer = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    rest, test = next(outer.split(states, groups=groups))

    rest_states = states.iloc[rest]
    inner = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
    tr_rel, cal_rel = next(inner.split(rest_states, groups=rest_states["match_id"]))
    return rest[tr_rel], rest[cal_rel], test


def train(states: pd.DataFrame, seed: int = 7):
    X, y = states[FEATURES], states[LABEL].astype(int)
    tr, cal, te = _split3(states, seed)

    booster = lgb.LGBMClassifier(
        n_estimators=400, learning_rate=0.05, num_leaves=31,
        min_child_samples=40, subsample=0.9, colsample_bytree=0.9,
        random_state=seed, verbose=-1,
    )
    booster.fit(X.iloc[tr], y.iloc[tr],
                categorical_feature=[FEATURES.index(c) for c in CATEGORICAL])

    # fit the calibrator on data the booster has never seen
    raw_cal = booster.predict_proba(X.iloc[cal])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw_cal, y.iloc[cal])

    model = WinProbabilityModel(booster, calibrator)

    p = model.predict(states.iloc[te])
    frac_pos, mean_pred = calibration_curve(y.iloc[te], p, n_bins=10, strategy="quantile")

    report = Report(
        auc=roc_auc_score(y.iloc[te], p),
        brier=brier_score_loss(y.iloc[te], p),
        logloss=log_loss(y.iloc[te], np.clip(p, 1e-6, 1 - 1e-6)),
        ece=expected_calibration_error(y.iloc[te], p),
        ece_floor=null_calibration_floor(len(te)),
        max_calib_error=float(np.max(np.abs(frac_pos - mean_pred))),
        n_train=len(tr), n_calib=len(cal), n_test=len(te),
    )
    return model, report, (mean_pred, frac_pos)
