"""Is the calibration gate comparing against the right noise floor, and is 2.5 real?

    python tools/calibcheck.py            all 20 seeds
    python tools/calibcheck.py --quick    5 seeds, for a first look
    python tools/calibcheck.py --raw      also fit WITHOUT the isotonic layer

WHAT THIS ALREADY SETTLED
-------------------------
The floor question is answered and the answer is in the code now. The old
null_calibration_floor drew its predictions from rng.uniform(0, 1, n), and a
real model is nothing like uniform: ours puts only 29% of its mass between
.35 and .65, because a round win-probability model spends most of its time
confident. The floor depends on that shape. Measured on 6,000 rows, holding
everything else equal:

    uniform, what the gate used to assume           1.00x
    beta(5,5), bunched near the middle              1.23x
    beta(2,2), mild centre mass                     1.15x
    beta(.6,.6), mass out at the ends               0.91x

Over 20 seeds on 138 maps the matched floor came out 0.88x the uniform one,
so the gate had been too LENIENT by about 13%: 10 of 20 seeds at median 2.33,
not 13 of 20 at 2.06. null_calibration_floor now bootstraps off the model's
own predictions, so res.ece_floor IS the matched floor. The uniform column
below is computed locally, only so the correction stays visible.

Ties were the other suspect and are not the problem. Isotonic output repeats
values, but at 41, 21 and 11 distinct predictions the floor moves 0.97x to
1.02x, and real fits run 72 to 108 distinct with ten filled bins. The distinct
and bins columns stay because if that ever collapses below about ten, every
number here stops meaning anything.

WHAT IS STILL OPEN, AND WHAT --raw IS FOR
-----------------------------------------
ECE_FLOOR_MULTIPLE = 2.5 is inherited, not justified. It was set when
"uncalibrated lands 4-7x and calibrated lands around 2x" was measured against
the OLD uniform null. Both anchors shift about 1.14x under the corrected floor
and neither has been re-measured. The calibrated model now sits at 2.33 with
the gate at 2.5, which is 7% of headroom against a threshold whose own
justification says a calibrated model lands "around 2x". Either the anchor is
stale or the gate was always this tight, and nothing on record distinguishes
those.

--raw runs the negative control that does. It takes the same fitted booster,
skips the isotonic calibrator, and scores the raw probabilities against their
own matched floor. That is the uncalibrated arm of the comparison 2.5 was
supposed to separate.

    wide gap    the calibrator is working and 2.5 is merely brutal. The
                threshold is defensible; the model needs better features.
    narrow gap  isotonic is barely earning its place. The calibrator is the
                bug, and raising the gate would be hiding it.

Do NOT hand-tune ECE_FLOOR_MULTIPLE off one run either way. Whatever this
prints is one more measurement with a 20-seed spread on it.

A TRAP WORTH KNOWING ABOUT
--------------------------
When bootstrapping, the generator drawing y must be independent of whatever
produced p. Seeding both from default_rng(0) makes the first trial draw the
same stream twice, so y = (p < p), all zeros, and one degenerate trial drags
the mean of forty up by about 2x. A plausible-looking wrong answer, not a
crash. p here comes from a fitted model so there is no shared stream, and the
seeds are kept distinct anyway.
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
from counterplay.schema import FEATURES, LABEL  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)
TRIALS = 40      # same as null_calibration_floor, so the two are comparable
BINS = 10
UNIFORM_SEED = 54321   # distinct from model._FLOOR_SEED, see the trap above


def occupied_bins(p, bins: int = BINS) -> int:
    """How many of the requested bins actually hold rows.

    Replicates the binning inside expected_calibration_error exactly. With
    well-spread predictions this returns `bins`; less means ties collapsed
    quantile edges.
    """
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e-9, 1 + 1e-9
    idx = np.digitize(p, edges[1:-1])
    return int(sum((idx == k).sum() > 0 for k in range(bins)))


def uniform_floor(n: int, trials: int = TRIALS, bins: int = BINS,
                  seed: int = UNIFORM_SEED) -> float:
    """What null_calibration_floor used to return: the null from uniform p.

    Kept here, and only here, so the size of the correction stays measurable
    after the fix landed in model.py. Nothing should use this as a gate.
    """
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(trials):
        p = rng.uniform(0, 1, n)
        y = (rng.random(n) < p).astype(int)
        vals.append(model_mod.expected_calibration_error(y, p, bins))
    return float(np.mean(vals))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="5 seeds instead of 20")
    ap.add_argument("--raw", action="store_true",
                    help="also score the booster with the isotonic layer removed")
    args = ap.parse_args()
    seeds = SEEDS[:5] if args.quick else SEEDS

    rounds, events = corpus.load_frames(tier="league")
    states = state_mod.build_states(rounds, events)
    y_all = states[LABEL].astype(int)
    print("league corpus: %d rounds, %d state rows, %d matches"
          % (len(rounds), len(states), states["match_id"].nunique()))
    print("refitting on %d seeds%s...\n"
          % (len(seeds), ", plus the uncalibrated control" if args.raw else ""))

    gate = model_mod.ECE_FLOOR_MULTIPLE
    head = ("%-5s %6s %5s %5s %8s | %8s %6s | %8s %6s %-4s"
            % ("seed", "rows", "distc", "bins", "ECE",
               "unifFlr", "ratio", "matchFlr", "ratio", "gate"))
    if args.raw:
        head += " || %8s %8s %6s %-4s" % ("rawECE", "rawFlr", "ratio", "gate")
    print(head)
    print("-" * (len(head) + 2))

    uni, mat, lift, mids, raw = [], [], [], [], []
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

        uf, mf = uniform_floor(len(te)), res.ece_floor
        r_u, r_m = ece / uf, ece / mf
        uni.append(r_u)
        mat.append(r_m)
        lift.append(mf / uf)
        mids.append(float(np.mean((p > 0.35) & (p < 0.65))))
        line = ("%-5d %6d %5d %5d %8.4f | %8.4f %6.2f | %8.4f %6.2f %-4s"
                % (seed, len(te), len(np.unique(p)), occupied_bins(p), ece,
                   uf, r_u, mf, r_m, "PASS" if r_m < gate else "FAIL"))

        if args.raw:
            # Same booster, same split, isotonic removed. Nothing is refitted:
            # this is the model the calibrator was wrapped around.
            rp = model.booster.predict_proba(states.iloc[te][FEATURES])[:, 1]
            rece = model_mod.expected_calibration_error(y_all.iloc[te], rp, BINS)
            rfl = model_mod.null_calibration_floor(rp)
            r_r = rece / rfl
            raw.append(r_r)
            line += " || %8.4f %8.4f %6.2f %-4s" % (
                rece, rfl, r_r, "PASS" if r_r < gate else "FAIL")
        print(line)

    if not uni:
        return 1

    med_lift, med_mat = statistics.median(lift), statistics.median(mat)
    print()
    print("uniform floor (OLD, wrong)   passed %2d of %d   ratio median %.2f"
          % (sum(1 for r in uni if r < gate), len(uni), statistics.median(uni)))
    print("matched floor (shipped)      passed %2d of %d   ratio median %.2f"
          "  (min %.2f max %.2f)"
          % (sum(1 for r in mat if r < gate), len(mat), med_mat,
             min(mat), max(mat)))
    if raw:
        print("UNCALIBRATED control         passed %2d of %d   ratio median %.2f"
              "  (min %.2f max %.2f)"
              % (sum(1 for r in raw if r < gate), len(raw),
                 statistics.median(raw), min(raw), max(raw)))
    print()
    print("matched floor is %.2fx the uniform floor, median across seeds."
          % med_lift)
    print("%.0f%% of predictions sit between .35 and .65, median across seeds."
          % (100 * statistics.median(mids)))
    print()

    if not raw:
        print("Run with --raw for the negative control. Without it there is no")
        print("evidence that %.1f separates a calibrated model from an" % gate)
        print("uncalibrated one on THIS data, which is the only thing that")
        print("would justify the threshold.")
        return 0

    # The verdict is about whether the threshold means anything, not about
    # whether this particular fit passed.
    med_raw = statistics.median(raw)
    sep = med_raw / med_mat if med_mat else float("inf")
    print("Calibrating divides the ratio by %.2f: %.2f uncalibrated down to %.2f."
          % (sep, med_raw, med_mat))
    print()
    if sep < 1.3:
        print("NARROW. The isotonic layer is barely earning its place, so the")
        print("gate is not separating what it claims to separate and raising")
        print("it would hide that. Fix the calibrator before touching %.1f:" % gate)
        print("try a larger calibration fraction than 18.75%, Platt against")
        print("isotonic, or cross-validated calibration so it sees all of")
        print("training rather than one held-out slice.")
    elif med_raw < gate:
        print("The UNCALIBRATED model also clears %.1f. The gate cannot tell" % gate)
        print("the two arms apart on this data, so passing it means nothing")
        print("here whatever the number says. The threshold needs re-deriving")
        print("from this corpus, not inheriting from the old uniform null.")
    else:
        print("WIDE, and the control fails while the calibrated model is at")
        print("%.2f. The calibrator is doing real work and %.1f is defensible."
              % (med_mat, gate))
        print("That makes this a features problem, not a calibration one, and")
        print("not a corpus one: 88 to 138 maps moved ECE from 0.029 to 0.031.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
