"""Train the scorer's model on the whole corpus and save it for the server.

    python tools/ship_scorer.py     # writes counterplay/scorer_model.pkl

The server holds ten college matches and cannot train the model; it can run
one. This trains counterplay/model.py's default config ("smallpos": the
small booster, the position summaries, the ESEA maps as extra training rows)
on every college map with its calibration fitted on a quarter of them, and
pickles it beside the code. Re-run and redeploy it when the corpus grows.

It reads its own training data, so on a team whose matches are in the
corpus it is mildly optimistic about that team's own rounds; the measured
calibration (tools/seedsweep.py) is for matches it has never seen.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import corpus, db  # noqa: E402
from counterplay import model as M  # noqa: E402
from counterplay import posfeat  # noqa: E402
from counterplay import state as state_mod  # noqa: E402

OUT = ROOT / "counterplay" / "scorer_model.pkl"


def main():
    db.init()
    states = posfeat.attach(state_mod.build_states(*corpus.load_frames(tier="league")))
    model, report, _curve = M.train(states, seed=7)
    print(report)
    OUT.write_bytes(pickle.dumps(model))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e3:.0f} KB), "
          f"{states['match_id'].nunique()} college maps")


if __name__ == "__main__":
    main()
