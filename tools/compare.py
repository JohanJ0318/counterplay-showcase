"""Two model configurations over the SAME splits, so a small change is visible.

    python tools/compare.py --b-cal-frac 0.35
    python tools/compare.py --b-calibrator sigmoid
    python tools/compare.py --b-cal-frac 0.40 --b-calibrator sigmoid --quick

WHY PAIRING IS THE WHOLE POINT
------------------------------
At 138 maps the ratio ranges 1.40 to 3.48 across seeds on ONE corpus. That
spread is not the model being unstable, it is which 35 matches landed in the
test set, and it swamps anything a tuning change could do. Comparing the
MEDIAN of two runs can therefore only see effects bigger than the spread,
which is to say effects that were never in doubt.

Holding the seed fixed across both arms removes that. Seed 7 tests on exactly
the same matches in arm A and arm B, so the difference between them is the
change and not the draw. Paired this way, a shift several times smaller than
the spread becomes readable.

This was worth building because reading medians already produced a wrong
answer once. Plant site went in and the median moved 2.33 to 2.39, which read
as a regression. Paired over the same 20 seeds it was 11 better, 9 worse,
mean -0.053: a wash. The median had moved because of WHICH seeds shifted.

WHAT IT REPORTS
---------------
Paired difference on the calibration ratio (lower is better) and on AUC
(higher is better), plus a two-sided sign test. The sign test asks only how
often B beat A, so one seed swinging wildly cannot carry the result, which is
the failure mode a mean has on twenty noisy draws.

READ THE SIGN TEST AS A FILTER, NOT A BLESSING. p < 0.05 over twenty paired
re-splits of one corpus says the change does something on THIS data. It does
not say the model is calibrated, and it does not say the change survives on
matches nobody has parsed yet. Nothing measurable here can say that.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus  # noqa: E402
from counterplay import model as model_mod  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

SEEDS = (7, 1, 2, 3, 4, 5, 11, 23,
         31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79)


def sign_test(diffs, better=lambda d: d < 0) -> tuple[int, int, float]:
    """(wins, ties, two-sided p) that B differs from A more often than chance.

    Exact binomial on the signs. Ties are dropped, which is the standard
    handling and costs nothing here because exact ties do not occur on floats.
    """
    wins = sum(1 for d in diffs if better(d))
    ties = sum(1 for d in diffs if d == 0)
    n = len(diffs) - ties
    if n == 0:
        return wins, ties, 1.0
    k = max(wins, n - wins)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return wins, ties, min(1.0, 2 * tail)


def arm(states, seed, cal_frac, calibrator):
    _m, res, _c = model_mod.train(states, seed=seed, cal_frac=cal_frac,
                                  calibrator=calibrator)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="5 seeds instead of 20")
    ap.add_argument("--a-cal-frac", type=float, default=0.25)
    ap.add_argument("--a-calibrator", default="isotonic",
                    choices=model_mod.CALIBRATORS)
    ap.add_argument("--b-cal-frac", type=float, default=0.25)
    ap.add_argument("--b-calibrator", default="isotonic",
                    choices=model_mod.CALIBRATORS)
    args = ap.parse_args()
    seeds = SEEDS[:5] if args.quick else SEEDS

    a = (args.a_cal_frac, args.a_calibrator)
    b = (args.b_cal_frac, args.b_calibrator)
    if a == b:
        print("A and B are the same configuration; nothing to compare.")
        print("Pass one of --b-cal-frac / --b-calibrator.")
        return 2

    rounds, events = corpus.load_frames(tier="league")
    states = state_mod.build_states(rounds, events)
    print("league corpus: %d rounds, %d state rows, %d matches"
          % (len(rounds), len(states), states["match_id"].nunique()))
    print("A: cal_frac=%.2f calibrator=%s" % a)
    print("B: cal_frac=%.2f calibrator=%s" % b)
    print("%d seeds, both arms on identical splits...\n" % len(seeds))

    gate = model_mod.ECE_FLOOR_MULTIPLE
    print("%-5s | %8s %8s %8s | %8s %8s %8s"
          % ("seed", "A ratio", "B ratio", "diff", "A AUC", "B AUC", "diff"))
    print("-" * 66)

    rd, ad, ra, rb = [], [], [], []
    for seed in seeds:
        try:
            ra_, rb_ = arm(states, seed, *a), arm(states, seed, *b)
        except Exception as exc:
            print("%-5d  failed: %s: %s" % (seed, type(exc).__name__, exc))
            continue
        d_ratio = rb_.ece_ratio - ra_.ece_ratio
        d_auc = rb_.auc - ra_.auc
        rd.append(d_ratio)
        ad.append(d_auc)
        ra.append(ra_.ece_ratio)
        rb.append(rb_.ece_ratio)
        print("%-5d | %8.2f %8.2f %+8.2f | %8.4f %8.4f %+8.4f"
              % (seed, ra_.ece_ratio, rb_.ece_ratio, d_ratio,
                 ra_.auc, rb_.auc, d_auc))

    if not rd:
        return 1

    spread = max(ra) - min(ra)
    wins, _ties, p = sign_test(rd)                       # lower ratio is better
    awins, _at, ap_ = sign_test(ad, better=lambda d: d > 0)   # higher AUC better

    print()
    print("A  passed %2d of %d   ratio median %.2f"
          % (sum(1 for r in ra if r < gate), len(ra), statistics.median(ra)))
    print("B  passed %2d of %d   ratio median %.2f"
          % (sum(1 for r in rb if r < gate), len(rb), statistics.median(rb)))
    print()
    print("PAIRED, which is the number that matters:")
    print("  ratio  mean %+.3f   median %+.3f   B better on %d of %d   sign p=%.3f"
          % (statistics.mean(rd), statistics.median(rd), wins, len(rd), p))
    print("  AUC    mean %+.4f  median %+.4f  B better on %d of %d   sign p=%.3f"
          % (statistics.mean(ad), statistics.median(ad), awins, len(ad), ap_))
    print()
    print("  for scale, A's ratio spans %.2f across these seeds; the paired"
          % spread)
    print("  mean above is %.0f%% of that, and comparing run medians could not"
          % (100 * abs(statistics.mean(rd)) / spread if spread else 0))
    print("  have seen it.")
    print()

    if p < 0.05:
        direction = "BETTER" if wins > len(rd) / 2 else "WORSE"
        print("B is reliably %s on this corpus (sign p=%.3f)." % (direction, p))
        print("Reliable is not large: median ratio moved %.2f to %.2f against"
              % (statistics.median(ra), statistics.median(rb)))
        print("a gate of %.1f. Check that before adopting it." % gate)
    else:
        print("No reliable difference (sign p=%.3f, B better on %d of %d)."
              % (p, wins, len(rd)))
        print("That is a real answer, not a failed experiment: this knob does")
        print("not move calibration on this corpus, and it can be crossed off")
        print("rather than guessed about.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
