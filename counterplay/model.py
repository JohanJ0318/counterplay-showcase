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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

from .schema import CATEGORICAL, FEATURES, LABEL, POSFEAT

# Gate on Expected Calibration Error (sample-weighted MEAN deviation), not on
# the max across bins. Max-of-bins is a badly noisy statistic: a PERFECTLY
# calibrated model measured on 7,700 rows scores ~0.034 on it from sampling
# noise alone, so a 0.05 max-error gate is mostly measuring your test-set size.
# ECE on the same data lands near 0.012. Run null_calibration_floor() below to
# see the noise floor for your own predictions before trusting either number.
# The gate is RELATIVE to the noise floor, not absolute. A fixed threshold
# silently becomes stricter as your test set shrinks, so a small dataset would
# fail for having few rows rather than for being miscalibrated.
#
# 2.5 IS NOT RE-DERIVED. It was set when "uncalibrated lands 4-7x and
# calibrated lands around 2x" was measured against the OLD uniform null, and
# that null has since been shown wrong by 0.88x on real predictions. Both
# anchors shift by about 1.14x under the corrected floor and neither has been
# re-measured, so the threshold is inherited, not justified. Run the negative
# control before trusting it: tools/calibcheck.py --raw fits the same booster
# with the isotonic layer removed and reports where an UNCALIBRATED model
# actually lands now. If that gap is narrow, this number is wrong.
#
# The old comment here claimed 2.5x "separates them cleanly at any size".
# That is false and our own runs falsified it. The ratio is ECE over a floor
# that shrinks as 1/sqrt(test rows) while real miscalibration does not, so any
# residual bias makes the ratio climb forever as matches are added: 88 maps
# scored 1.79 and 138 maps scored 2.53 on the same eight seeds with ECE flat
# at 0.029 and 0.031. Adding data makes this gate harder, not easier.
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


# Any constant works as long as it cannot collide with whatever produced p.
# Seeding this from the same stream as the predictions makes the first trial
# draw that stream twice, so y = (p < p), all zeros, and one degenerate trial
# drags the mean of forty up by about 2x. That is a plausible-looking wrong
# answer rather than a crash, which is the kind worth naming.
_FLOOR_SEED = 12345


def null_calibration_floor(p, bins: int = 10, trials: int = 40,
                           seed: int = _FLOOR_SEED) -> float:
    """ECE a PERFECTLY calibrated model would score on THESE predictions.

    Compare your model's ECE against this, not against zero.

    Takes the predictions and not a row count, because the floor depends on
    the SHAPE of the prediction distribution and not only on how many there
    are. This used to draw p from rng.uniform(0, 1, n), and a real model is
    nothing like uniform: ours puts only 29% of its mass between .35 and .65.
    Measured over 20 seeds on 138 maps, the uniform null sat 1.14x too high,
    which quietly made the gate 13% too lenient.

    Holding p fixed and drawing y ~ Bernoulli(p) keeps the shape, the ties and
    the row count exactly as the model produced them, and removes the one
    thing being measured. That is a parametric bootstrap, and it is the
    question this function always meant to ask.
    """
    if np.ndim(p) == 0:
        raise TypeError(
            "null_calibration_floor takes the model's predictions, not a row "
            "count. Passing n compared against a uniform null, which measures "
            "the wrong thing: see the note on ECE_FLOOR_MULTIPLE.")
    p = np.asarray(p, dtype=float)
    rng = np.random.default_rng(seed)
    return float(np.mean([
        expected_calibration_error((rng.random(len(p)) < p).astype(int), p, bins)
        for _ in range(trials)
    ]))


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
    """LightGBM booster plus an isotonic calibration layer.

    Carries the feature list it was trained on: the "smallpos" config reads
    the position summaries too, and predicting with the wrong columns would
    be a silent nonsense number rather than an error.
    """

    def __init__(self, booster, calibrator, features=None):
        self.booster = booster
        self.calibrator = calibrator
        self.features = list(features or FEATURES)

    def predict(self, states: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.features if c not in states.columns]
        if missing:
            # Position summaries are computed from the database on demand.
            from . import posfeat
            if set(missing) <= set(posfeat.POSFEAT):
                states = posfeat.attach(states)
            else:
                raise KeyError(f"states lack {missing}")
        raw = self.booster.predict_proba(states[self.features])[:, 1]
        return self.calibrator.predict(raw)


class _Platt:
    """Platt scaling: a sigmoid fitted to the booster's raw probabilities.

    Offered against isotonic because the two fail differently. Isotonic is
    non-parametric and can fit any monotone shape, which is why it is the
    default, but it is a step function fitted on one held-out slice and it
    has nothing to say between the steps. Platt has two parameters and cannot
    fit a shape the booster did not already roughly have, which makes it much
    steadier on a small calibration set.

    Matches the fit/predict surface IsotonicRegression exposes, so
    WinProbabilityModel does not care which one it is holding.
    """

    def __init__(self):
        self.lr = LogisticRegression(solver="lbfgs", C=1e10)

    @staticmethod
    def _logit(p):
        p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def fit(self, p, y):
        self.lr.fit(self._logit(p), np.asarray(y))
        return self

    def predict(self, p):
        return self.lr.predict_proba(self._logit(p))[:, 1]


CALIBRATORS = ("isotonic", "sigmoid")


def _make_calibrator(kind: str):
    if kind == "isotonic":
        return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    if kind == "sigmoid":
        return _Platt()
    raise ValueError(f"calibrator must be one of {CALIBRATORS}, got {kind!r}")


def _split3(states, seed, cal_frac: float = 0.25):
    """Three disjoint match-level splits: train / calibrate / test.

    `cal_frac` is the share of the NON-TEST data given to the calibrator, so
    the default 0.25 leaves 56.25% training, 18.75% calibrating, 25% testing.
    """
    groups = states["match_id"]
    outer = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    rest, test = next(outer.split(states, groups=groups))

    rest_states = states.iloc[rest]
    inner = GroupShuffleSplit(n_splits=1, test_size=cal_frac, random_state=seed + 1)
    tr_rel, cal_rel = next(inner.split(rest_states, groups=rest_states["match_id"]))
    return rest[tr_rel], rest[cal_rel], test


# The booster as it shipped until 2026-10-14: too big for this data.
SHIPPED_PARAMS = dict(n_estimators=400, learning_rate=0.05, num_leaves=31,
                      min_child_samples=40, subsample=0.9, colsample_bytree=0.9)
# Cut down, which alone gained about 0.02 AUC (tools/baselines.py, SMALL).
# ml/evaluate.py reads these, so the measured trees and these cannot drift.
SMALL_PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=7,
                    min_child_samples=300, subsample=0.8, subsample_freq=1,
                    colsample_bytree=0.9, reg_lambda=5.0)

# name -> (features, booster params, extra training tiers)
#
# "smallpos" is the scorer's model since 2026-10-14: the small booster, the
# nine position summaries (counterplay/posfeat.py) and the ESEA League maps
# as extra TRAINING rows (tier_id tells them apart). Calibration and every
# test stay collegiate, because the calibrator is fitted on, and the gate
# measured on, the states passed in. Best of thirteen models across both
# held-out protocols (ml/README.md). "shipped" is the old one, kept so
# tools/compare.py can still put the two side by side.
CONFIGS = {
    "shipped": (FEATURES, SHIPPED_PARAMS, ()),
    "smallpos": (FEATURES + POSFEAT, SMALL_PARAMS, ("esea",)),
}
DEFAULT_CONFIG = "smallpos"

_extra_cache: dict = {}


def extra_rows(tiers) -> pd.DataFrame | None:
    """State rows (with position summaries) for the extra training tiers,
    built once per process. None when there are none."""
    if not tiers:
        return None
    key = tuple(tiers)
    if key not in _extra_cache:
        from app import corpus
        from . import posfeat
        from . import state as state_mod
        frames = []
        for t in tiers:
            rounds, events = corpus.load_frames(tier=t)
            if len(rounds):
                frames.append(state_mod.build_states(rounds, events))
        _extra_cache[key] = (posfeat.attach(pd.concat(frames, ignore_index=True))
                             if frames else None)
    return _extra_cache[key]


def train(states: pd.DataFrame, seed: int = 7, cal_frac: float = 0.25,
          calibrator: str = "isotonic", config: str = DEFAULT_CONFIG):
    """Fit booster + calibrator and score on a held-out third of the matches.

    The defaults are the shipped model. Vary them through tools/compare.py,
    which holds the seed fixed across both arms so the change is not buried
    under which matches happened to land in test.

    `states` are the collegiate rows: split, calibrated and tested on. The
    config's extra tiers only ever join the TRAINING split.
    """
    features, params, tiers = CONFIGS[config]
    if any(c not in states.columns for c in features):
        from . import posfeat
        states = posfeat.attach(states)
    X, y = states[features], states[LABEL].astype(int)
    tr, cal, te = _split3(states, seed, cal_frac)

    X_tr, y_tr = X.iloc[tr], y.iloc[tr]
    extra = extra_rows(tiers)
    if extra is not None:
        X_tr = pd.concat([X_tr, extra[features]], ignore_index=True)
        y_tr = pd.concat([y_tr, extra[LABEL].astype(int)], ignore_index=True)

    booster = lgb.LGBMClassifier(**params, random_state=seed, verbose=-1)
    booster.fit(X_tr, y_tr,
                categorical_feature=[features.index(c) for c in CATEGORICAL])

    # fit the calibrator on data the booster has never seen
    raw_cal = booster.predict_proba(X.iloc[cal])[:, 1]
    cal_model = _make_calibrator(calibrator)
    cal_model.fit(raw_cal, y.iloc[cal])

    model = WinProbabilityModel(booster, cal_model, features)

    p = model.predict(states.iloc[te])
    frac_pos, mean_pred = calibration_curve(y.iloc[te], p, n_bins=10, strategy="quantile")

    report = Report(
        auc=roc_auc_score(y.iloc[te], p),
        brier=brier_score_loss(y.iloc[te], p),
        logloss=log_loss(y.iloc[te], np.clip(p, 1e-6, 1 - 1e-6)),
        ece=expected_calibration_error(y.iloc[te], p),
        ece_floor=null_calibration_floor(p),
        max_calib_error=float(np.max(np.abs(frac_pos - mean_pred))),
        n_train=len(tr), n_calib=len(cal), n_test=len(te),
    )
    return model, report, (mean_pred, frac_pos)
