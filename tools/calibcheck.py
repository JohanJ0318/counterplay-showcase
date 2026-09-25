"""Is the calibration gate comparing against the right noise floor?

    python tools/calibcheck.py            all 20 seeds, same as the sweep
    python tools/calibcheck.py --quick    5 seeds, for a first look

THE PROBLEM THIS EXISTS TO SETTLE
---------------------------------
The gate is ECE / floor < 2.5, where floor comes from null_calibration_floor().
Across two corpus sizes the ratio moved a long way while ECE barely moved:

                    88 maps        138 maps
    ECE median      0.0293         0.0310      flat
    floor median    0.0164         0.0126      down 23%
    ratio median    1.79           2.53        up, entirely from the floor

The floor falling is correct: it shrinks as 1/sqrt(test rows) and the test set
got 1.59x bigger. sqrt(1.59) = 1.26, observed 1.30. Nothing is broken.

But the floor is only the right reference if the null resembles the thing being
measured, and in one specific way it does not. null_calibration_floor draws its
null predictions from rng.uniform(0, 1, n). The model's predictions are not
uniform. A round win-probability model puts early-round states near 50/50 and
late-round states near 0 or 1, so the distribution is its own shape entirely.

That matters, because the floor depends on that shape. Measured on 6,000 rows,
holding everything else equal:

    uniform, what the gate assumes                 1.00x
    beta(5,5), predictions bunched near the middle 1.23x
    beta(2,2), mild centre mass                    1.15x
    beta(.6,.6), mass out at the ends              0.91x

So a model whose predictions cluster mid-range is being held to a floor up to
23% too LOW, and every ratio it has ever scored is too high by that much. A
model whose predictions pile up at the ends has the opposite problem and has
been getting an easier gate than it deserved. At a median of 2.53 against a
gate of 2.5, 20% in either direction decides the verdict.

Ties were the other suspect and they are not the problem. Isotonic output is a
step function, so predictions repeat, and repeated values can collapse quantile
bin edges. Measured: at 41, 21 and 11 distinct values the floor moves between
0.97x and 1.02x, which is nothing. Bins only start collapsing below about ten
distinct values. The distinct count is still printed below, because if it ever
does drop that far every number here stops meaning anything.

WHAT THE HONEST NULL IS
-----------------------
Hold the model's own predictions fixed and ask what ECE a PERFECTLY calibrated
model would score on them: draw y ~ Bernoulli(p) with p the real predictions.
Shape, ties and row count are then exactly what the model produced, and the one
thing removed is the miscalibration. That is a parametric bootstrap, and it is
the question the floor was always meant to answer.

    uniform floor   what a perfect model scores on n rows of uniform p
    matched floor   what a perfect model scores on THESE n predictions

This changes no threshold. It measures whether 2.5x is being applied to the
right number.

A TRAP WORTH KNOWING ABOUT
--------------------------
When bootstrapping, the generator drawing y must be independent of whatever
produced p. Seeding both from default_rng(0) makes the first trial draw the
same stream twice, so y = (p < p), all zeros, and one degenerate trial drags
the mean of forty up by about 2x. That is a plausible-looking wrong answer,
not a crash. Here p comes from the fitted model so there is no shared stream,
and BOOTSTRAP_SEED is kept distinct anyway.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus  # noqa: E402
from counterplay import model as model_mod  # noqa: E402
from counterplay import state as state_mod  # noqa: E402
from counterplay.schema import LABEL  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)
TRIALS = 40          # same as null_calibration_floor, so the two are comparable
BINS = 10
BOOTSTRAP_SEED = 12345   # see "A trap worth knowing about" above


def occupied_bins(p, bins: int = BINS) -> int:
    """How many of the requested bins actually hold rows.

    Replicates the binning inside expected_calibration_error exactly. With
    well-spread predictions this returns `bins`; anything less is ties
    collapsing quantile edges.
    """
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e-9, 1 + 1e-9
    idx = np.digitize(p, edges[1:-1])
    return int(sum((idx == k).sum() > 0 for k in range(bins)))


def matched_floor(p, trials: int = TRIALS, bins: int = BINS,
                  seed: int = BOOTSTRAP_SEED) -> float:
    """ECE a PERFECTLY calibrated model would score on these exact predictions.

    Same estimator and same trial count as null_calibration_floor. The only
    difference is that p is the model's real output rather than a uniform
    draw, so shape and ties are preserved and miscalibration is removed.
    """
    rng = np.random.default_rng(seed)
    p = np.asarray(p)
    return float(np.mean([
        model_mod.expected_calibration_error(
            (rng.random(len(p)) < p).astype(int), p, bins)
        for _ in range(trials)
    ]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="5 seeds instead of 20")
    args = ap.parse_args()
    seeds = SEEDS[:5] if args.quick else SEEDS

    rounds, events = corpus.load_frames(tier="league")
    states = state_mod.build_states(rounds, events)
    y_all = states[LABEL].astype(int)
    print("league corpus: %d rounds, %d state rows, %d matches"
          % (len(rounds), len(states), states["match_id"].nunique()))
    print("refitting on %d seeds...\n" % len(seeds))

    gate = model_mod.ECE_FLOOR_MULTIPLE
    print("%-5s %6s %5s %5s %8s | %8s %6s %-4s | %8s %6s %-4s"
          % ("seed", "rows", "distc", "bins", "ECE",
             "unifFlr", "ratio", "gate", "matchFlr", "ratio", "gate"))
    print("-" * 90)

    uni, mat, lift, mids = [], [], [], []
    for seed in seeds:
        try:
            model, res, _curve = model_mod.train(states, seed=seed)
            # _split3 is deterministic in the seed, so this is the same test
            # set train() just scored on.
            _tr, _cal, te = model_mod._split3(states, seed)
            p = model.predict(states.iloc[te])
        except Exception as exc:
            print("%-5d  failed: %s: %s" % (seed, type(exc).__name__, exc))
            continue

        # Recompute rather than trusting res.ece, so a mismatch surfaces here
        # instead of quietly invalidating the comparison.
        ece = model_mod.expected_calibration_error(y_all.iloc[te], p, BINS)
        if abs(ece - res.ece) > 1e-9:
            print("  WARNING seed %d: recomputed ECE %.6f != report %.6f"
                  % (seed, ece, res.ece))

        mf = matched_floor(p)
        r_u, r_m = ece / res.ece_floor, ece / mf
        uni.append(r_u)
        mat.append(r_m)
        lift.append(mf / res.ece_floor)
        mids.append(float(np.mean((p > 0.35) & (p < 0.65))))
        print("%-5d %6d %5d %5d %8.4f | %8.4f %6.2f %-4s | %8.4f %6.2f %-4s"
              % (seed, len(te), len(np.unique(p)), occupied_bins(p), ece,
                 res.ece_floor, r_u, "PASS" if r_u < gate else "FAIL",
                 mf, r_m, "PASS" if r_m < gate else "FAIL"))

    if not uni:
        return 1

    med_lift = statistics.median(lift)
    print()
    print("uniform floor   passed %2d of %d   ratio median %.2f  (min %.2f max %.2f)"
          % (sum(1 for r in uni if r < gate), len(uni),
             statistics.median(uni), min(uni), max(uni)))
    print("matched floor   passed %2d of %d   ratio median %.2f  (min %.2f max %.2f)"
          % (sum(1 for r in mat if r < gate), len(mat),
             statistics.median(mat), min(mat), max(mat)))
    print()
    print("matched floor is %.2fx the uniform floor, median across seeds."
          % med_lift)
    print("%.0f%% of predictions sit between .35 and .65, median across seeds."
          % (100 * statistics.median(mids)))
    print()

    # The verdict is about which null to trust, not about the model.
    if abs(med_lift - 1.0) < 0.05:
        print("The two nulls agree within 5%. The uniform null is fine for this")
        print("prediction distribution, so the gate is measuring real")
        print("miscalibration and every ratio recorded so far stands.")
        print("More matches will not move it; the calibrator or the features")
        print("have to change.")
    elif med_lift > 1.0:
        print("The matched floor is HIGHER, so the gate has been too STRICT.")
        print("A perfectly calibrated model scores %.0f%% more on these"
              % (100 * (med_lift - 1)))
        print("predictions than on uniform ones, and the model was being")
        print("charged for that. The right-hand ratios are the honest ones.")
    else:
        print("The matched floor is LOWER, so the gate has been too LENIENT.")
        print("The model is FURTHER from calibrated than every number recorded")
        print("so far says, by about %.0f%%. The right-hand ratios are the"
              % (100 * (1 / med_lift - 1)))
        print("honest ones and they are worse.")
    print()
    print("Either way, do NOT hand-tune ECE_FLOOR_MULTIPLE to compensate. The")
    print("bias depends on the prediction distribution and moves every refit,")
    print("so the fix belongs in model.null_calibration_floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
