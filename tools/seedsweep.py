"""Refit the decision engine on many random splits and report the spread.

    python tools/seedsweep.py

WHAT A SEED IS HERE
-------------------
There is one collegiate corpus and it is small, so the model cannot be
measured on data it has never seen without first setting some of that corpus
aside. A seed is the number that decides WHICH part gets set aside. Change
the seed and you get a different train/calibrate/test carve-up of the same
matches, a different model, and a different score.

model.train(states, seed=N) feeds N into three places:

  1. GroupShuffleSplit(random_state=N)      picks the 25% of MATCHES that
                                            become the test set
  2. GroupShuffleSplit(random_state=N + 1)  picks 25% of what is left to fit
                                            the isotonic calibrator on
  3. LGBMClassifier(random_state=N)         the booster's own randomness:
                                            subsample=0.9 and
                                            colsample_bytree=0.9 mean every
                                            tree sees a random 90% of rows
                                            and 90% of features

The split is by match and never by row, because rows inside one round are
correlated: if half a round trains and half tests, the model has effectively
seen the answer. That is also why the seed matters so much at this size. With
88 maps, a 25% test set is about 22 of them, so ONE unusual match landing in
test moves every number on the row.

WHY NOT JUST RUN IT ONCE
------------------------
Because a single seed is a sample of one and was already misleading twice.
run.py defaults to seed 7, and on the 42-map corpus seed 7 passed the
calibration gate at 2.25x while the median across eight seeds was 3.46x. The
default was simply one of the lucky splits. Reporting it would have meant
shipping a number the data does not support.

So the honest statistic is not any one fit, it is the distribution: where the
middle sits, and how often it fails. That is what this prints.

WHY TWENTY AND NOT EIGHT
------------------------
Eight was enough while the question was "is the centre anywhere near the
gate". It is not enough now. At 88 maps the sweep failed 2 of 8, and 2 of 8
is consistent with a true failure rate anywhere from roughly 5% to 45%. The
tail is the thing being measured now, and a tail needs more draws than a
centre does.

The first eight seeds are the ORIGINAL eight, unchanged, so the numbers stay
directly comparable to the 42-map run recorded in TODO.md. The twelve added
are spaced out on purpose: train() uses seed for the outer split and seed + 1
for the inner one, so consecutive seeds partly share a split, and picking
1..20 would have made the extra draws less independent than they look.

Takes a few minutes. Twenty LightGBM fits, single threaded.
"""
import os
import sys
import statistics

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus  # noqa: E402
from counterplay import model as model_mod  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

# The original eight first, so every row can still be compared against the
# 42-map sweep. Then twelve more, spaced so no seed is another seed's + 1.
SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)

rounds, events = corpus.load_frames(tier="league")
print("league corpus: %d rounds, %d events" % (len(rounds), len(events)))

states = state_mod.build_states(rounds, events)
print("state rows: %d" % len(states))
print("matches:    %d" % states["match_id"].nunique())
print("\nrefitting on %d seeds, this takes a few minutes...\n" % len(SEEDS))

print("%-6s %8s %8s %8s %8s %8s  %s"
      % ("seed", "AUC", "Brier", "ECE", "floor", "ratio", "gate 2.5x"))
ratios, aucs = [], []
for seed in SEEDS:
    try:
        _m, res, _c = model_mod.train(states, seed=seed)
    except Exception as exc:
        print("%-6d  failed: %s" % (seed, type(exc).__name__))
        continue
    ratios.append(res.ece_ratio)
    aucs.append(res.auc)
    print("%-6d %8.4f %8.4f %8.4f %8.4f %8.2f  %s"
          % (seed, res.auc, res.brier, res.ece, res.ece_floor, res.ece_ratio,
             "PASS" if res.passes else "FAIL"))

if ratios:
    s = sorted(ratios)
    passes = sum(1 for r in s if r < model_mod.ECE_FLOOR_MULTIPLE)
    # Quartiles say more than min and max do. The extremes of twenty draws are
    # the two least stable numbers on the page; the quartiles are where the
    # bulk actually sits.
    q1, q3 = statistics.quantiles(s, n=4)[0], statistics.quantiles(s, n=4)[2]
    print()
    print("passed %d of %d seeds  (%.0f%%)" % (passes, len(s), 100 * passes / len(s)))
    print("ratio  min %.2f   q1 %.2f   median %.2f   q3 %.2f   max %.2f"
          % (min(s), q1, statistics.median(s), q3, max(s)))
    print("AUC    min %.4f  median %.4f  max %.4f"
          % (min(aucs), statistics.median(aucs), max(aucs)))
    print()

    # The verdict is about the whole distribution, not about any one fit.
    # A median under the gate with a quarter of splits failing is a model that
    # is usually calibrated, which is not the same as one that can be shipped:
    # a coach gets whichever fit happens to be in production.
    if passes == len(s):
        print("Every split clears the gate. That is the result to act on.")
    elif statistics.median(s) < model_mod.ECE_FLOOR_MULTIPLE:
        print("Median clears the gate but %d split(s) do not." % (len(s) - passes))
        print("Usually calibrated is not shippable: production runs ONE fit,")
        print("and a coach gets whichever one it was. More matches, then rerun.")
    else:
        print("Median is above the gate. This is not calibrated on this corpus.")
        print("README is right that the answer is matches, not code.")
