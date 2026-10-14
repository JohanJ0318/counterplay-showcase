"""Training WinNet: the loop, early stopping, and pro-then-college fine-tuning.

    fit = train(snap, train_idx, seed=7)                    # college only
    fit = train(snap, train_idx, seed=7, pretrain_idx=pro)  # pro first
    p_raw = fit.predict(snap, test_idx)                     # uncalibrated

Every split is by MATCH (the caller passes row indices that already respect
that): moments inside one round are near copies of each other, and a split
by row would leak the answer and flatter every number.

Early stopping holds out a tenth of the training matches and stops when
their log loss has not improved for PATIENCE epochs, keeping the best
weights. Calibration is NOT done here: the caller fits the same isotonic
layer the shipped model uses, on matches this never saw, so the comparison
with LightGBM is like for like.

Pretraining on pro maps and then fine-tuning on college maps is the reason
this exists at all: 104 pro maps teach what positions mean in general, and
the college rounds then adjust that to how college teams actually play.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from counterplay.schema import LABEL

from .model import WinNet, global_features

BATCH = 512
PATIENCE = 4
MAX_EPOCHS = 40


def tensors(snap, idx):
    """The model's inputs and the label for rows `idx`."""
    st = snap.states.iloc[idx]
    return (torch.from_numpy(snap.players[idx]),
            torch.from_numpy(global_features(st)),
            torch.from_numpy(st["map_id"].to_numpy(dtype=np.int64, copy=True)),
            torch.from_numpy(st["round_type_id"].to_numpy(dtype=np.int64, copy=True)),
            torch.from_numpy(st["plant_site"].clip(0, 2).to_numpy(dtype=np.int64, copy=True)),
            torch.from_numpy(st["tier_id"].to_numpy(dtype=np.int64, copy=True)),
            torch.from_numpy(st[LABEL].to_numpy(dtype=np.float32, copy=True)))


def _split_matches(snap, idx, frac, seed):
    """Hold out `frac` of the matches in idx: (keep, held)."""
    ids = snap.states["match_id"].to_numpy()[idx]
    uniq = np.unique(ids)
    held = set(np.random.default_rng(seed).choice(
        uniq, size=max(1, int(len(uniq) * frac)), replace=False))
    mask = np.array([i in held for i in ids])
    return idx[~mask], idx[mask]


@torch.no_grad()
def _loss(model, data):
    model.eval()
    *x, y = data
    return float(nn.functional.binary_cross_entropy_with_logits(model(*x), y))


def _run(model, train_data, val_data, lr, seed, max_epochs=MAX_EPOCHS):
    """One training run with early stopping. Returns the best val loss."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    gen = torch.Generator().manual_seed(seed)
    n = len(train_data[-1])
    best, best_state, stale = float("inf"), None, 0
    for _epoch in range(max_epochs):
        model.train()
        order = torch.randperm(n, generator=gen)
        for start in range(0, n, BATCH):
            b = order[start:start + BATCH]
            *x, y = (t[b] for t in train_data)
            loss = nn.functional.binary_cross_entropy_with_logits(model(*x), y)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        v = _loss(model, val_data)
        if v < best - 1e-4:
            best, stale = v, 0
            best_state = {k: t.clone() for k, t in model.state_dict().items()}
        else:
            stale += 1
            if stale >= PATIENCE:
                break
    model.load_state_dict(best_state)
    return best


@dataclass
class Fit:
    model: WinNet
    val_loss: float

    @torch.no_grad()
    def predict(self, snap, idx) -> np.ndarray:
        self.model.eval()
        *x, _y = tensors(snap, idx)
        out = []
        for s in range(0, len(idx), 4096):
            out.append(torch.sigmoid(self.model(*(t[s:s + 4096] for t in x))))
        return torch.cat(out).numpy()


def train(snap, train_idx, seed: int = 7, use_players: bool = True,
          pretrain_idx=None) -> Fit:
    torch.manual_seed(seed)
    model = WinNet(use_players=use_players)
    fit_idx, val_idx = _split_matches(snap, np.asarray(train_idx), 0.1, seed)
    val = tensors(snap, val_idx)
    lr = 2e-3
    if pretrain_idx is not None:
        # Pro and college together first, early-stopped on COLLEGE matches,
        # then college alone at a lower rate so the pro habits are adjusted
        # rather than forgotten.
        both = np.concatenate([fit_idx, np.asarray(pretrain_idx)])
        _run(model, tensors(snap, both), val, lr, seed)
        lr = 5e-4
    best = _run(model, tensors(snap, fit_idx), val, lr, seed + 1)
    return Fit(model, best)
