"""What a typical college team loses to each cause, per round, per side.

    python tools/whylost_baseline.py     # writes counterplay/whylost_baseline.json

counterplay/whylost.py sorts a match's swings of win chance into causes.
On its own that always names "duels lost" first, because deaths are how win
chance falls for every team. What says something about a team is the
EXCESS: how much more it lost to a cause than a college team does over the
same number of rounds on the same side. This is that college team: every
college round, from both sides, with the scorer's model cross-fitted by
match so no round is scored by a model that trained on it.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import corpus, db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay import posfeat  # noqa: E402
from counterplay import state as state_mod  # noqa: E402
from counterplay import whylost as W  # noqa: E402

FOLDS = 5


def main():
    db.init()
    states = posfeat.attach(state_mod.build_states(*corpus.load_frames(tier="league")))
    states = states.sort_values(["match_id", "round_num", "event_idx"]).reset_index(drop=True)
    ids = np.array(sorted(states["match_id"].unique()))
    fold_of = dict(zip(ids, np.random.default_rng(7).permutation(len(ids)) % FOLDS))
    folds = states["match_id"].map(fold_of).to_numpy()
    wp = np.empty(len(states))
    for k in range(FOLDS):
        model, _r, _c = M.train(states[folds != k].reset_index(drop=True), seed=7 + k)
        wp[folds == k] = model.predict(states[folds == k])
    states["wp"] = wp

    totals = {"ct": defaultdict(float), "t": defaultdict(float)}
    rounds = {"ct": 0, "t": 0}
    for i, (mk, st) in enumerate(states.groupby("match_id", sort=False), 1):
        keys = {(mk, int(r)) for r in st["round_num"].unique()}
        for side in ("ct", "t"):
            b = W.explain_match(st, st["wp"].to_numpy(), {k: side for k in keys})
            rounds[side] += b.rounds_won + b.rounds_lost
            for c, v in b.by_side[side].items():
                totals[side][c] += v
        if i % 25 == 0:
            print(f"  {i}/{len(ids)} matches", flush=True)
    out = {side: {c: round(v / rounds[side], 5) for c, v in totals[side].items()}
           for side in ("ct", "t")}
    out["_rounds"] = rounds
    (ROOT / "counterplay" / "whylost_baseline.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    for side in ("ct", "t"):
        print(f"\nper {side.upper()} round, a college team:")
        for c, v in sorted(out[side].items(), key=lambda cv: cv[1]):
            print(f"  {W.LABEL.get(c, c):55s} {v:+.3f}")


if __name__ == "__main__":
    main()
