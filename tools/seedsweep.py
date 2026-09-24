"""Is the collegiate gate a pass, or is it one lucky split?

tier=league cleared at 2.25x against a gate of 2.5x. That is a pass with
about ten percent of headroom, on ONE random split of 42 matches. The split
is by match, so which matches land in test moves the number a lot when there
are only 42 of them.

A single seed is not a result at that margin. This refits on several and
reports the spread, which is the only honest way to say whether the engine
is calibrated on collegiate data or whether seed 7 was kind.
"""
import os
import sys

sys.path.insert(0, r"C:/Users/Johan/counterplay")
os.chdir(r"C:/Users/Johan/counterplay")
os.environ.setdefault("COUNTERPLAY_DB", "data/counterplay.db")

from app import corpus  # noqa: E402
from counterplay import model as model_mod  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

rounds, events = corpus.load_frames(tier="league")
print("league corpus: %d rounds, %d events" % (len(rounds), len(events)))

states = state_mod.build_states(rounds, events)
print("state rows: %d" % len(states))
print("matches:    %d" % states["match_id"].nunique())
print()

print("%-6s %8s %8s %8s %8s %8s  %s"
      % ("seed", "AUC", "Brier", "ECE", "floor", "ratio", "gate 2.5x"))
ratios = []
for seed in (7, 1, 2, 3, 4, 5, 11, 23):
    try:
        _m, res, _c = model_mod.train(states, seed=seed)
    except Exception as exc:
        print("%-6d  failed: %s" % (seed, type(exc).__name__))
        continue
    ratios.append(res.ece_ratio)
    print("%-6d %8.4f %8.4f %8.4f %8.4f %8.2f  %s"
          % (seed, res.auc, res.brier, res.ece, res.ece_floor, res.ece_ratio,
             "PASS" if res.passes else "FAIL"))

if ratios:
    print()
    passes = sum(1 for r in ratios if r < model_mod.ECE_FLOOR_MULTIPLE)
    print("passed %d of %d seeds" % (passes, len(ratios)))
    print("ratio  min %.2f  median %.2f  max %.2f"
          % (min(ratios), sorted(ratios)[len(ratios) // 2], max(ratios)))
