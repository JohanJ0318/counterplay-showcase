"""The PyTorch network's verdicts for a team, beside the scorer's.

    python -m ml.verdicts_net STEAMID [STEAMID ...]

Same moments, scoring and ranking as tools/verdicts.py (it calls that
module's moments() with a different model), so the two lists differ only
in the model. The network is trained like NETLONG in ml/evaluate.py, its
best setup: ESEA pretraining run longer, half as many ESEA rows as college
rows kept in fine-tuning. It never sees the team's own maps: they are left
out of training as the scorer leaves them out, and it is calibrated with
the same isotonic layer on a quarter of the remaining college matches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
sys.path.insert(0, str(ROOT / "tools"))

from counterplay import model as M  # noqa: E402
from counterplay.schema import LABEL, TIER_IDS  # noqa: E402

from . import data, train  # noqa: E402


class NetScorer:
    """A trained network plus isotonic layer, predicting state rows by
    looking each one up in the snapshot cache."""

    def __init__(self, snap, fit, iso):
        self.snap, self.fit, self.iso = snap, fit, iso
        st = snap.states
        self.row_of = {k: i for i, k in enumerate(
            zip(st["match_id"], st["round_num"], st["event_idx"]))}

    def predict(self, states):
        idx = np.array([self.row_of[k] for k in zip(
            states["match_id"], states["round_num"], states["event_idx"])])
        return self.iso.predict(self.fit.predict(self.snap, idx))


def make_fit(seed: int = 7):
    snap = data.load()
    st = snap.states
    esea = np.flatnonzero(st["tier_id"].to_numpy() == TIER_IDS["esea"])

    def fit(train_states):
        keep = set(train_states["match_id"])
        pool = np.flatnonzero((st["tier_id"].to_numpy() == TIER_IDS["league"])
                              & st["match_id"].isin(keep).to_numpy())
        split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1)
        tr, cal = next(split.split(pool, groups=st["match_id"].to_numpy()[pool]))
        tr, cal = pool[tr], pool[cal]
        net = train.train(snap, tr, seed=seed, pretrain_idx=esea,
                          pretrain_patience=10, pretrain_epochs=80, keep_mix=0.5)
        iso = M._make_calibrator("isotonic")
        iso.fit(net.predict(snap, cal), st[LABEL].to_numpy()[cal].astype(int))
        return NetScorer(snap, net, iso)

    return fit


def moments(steamids, n: int = 10, demos=None):
    import verdicts
    return verdicts.moments(steamids, n=n, demos=demos, fit=make_fit())


if __name__ == "__main__":
    for i, m in enumerate(moments(sys.argv[1:]), 1):
        mins, secs = divmod(m["seconds"], 60)
        print(f"{i:2d}. {m['map']} round {m['round']}, {mins}:{secs:02d} in, as "
              f"{m['side'].upper()}: {m['situation']}  {m['before']}% -> {m['after']}%")
