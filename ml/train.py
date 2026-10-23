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


LESSONS = ("next_side", "next_slot", "plant10", "plant_ok", "next_killer",
           "next_gap", "round_end")


def tensors(snap, idx):
    """(inputs, label, lessons) for rows `idx`. Inputs are in WinNet.forward's
    order; lessons are ml/extras.py's next_side, next_slot, plant10 and
    plant_ok, zeros when the snapshot carries no extras."""
    st = snap.states.iloc[idx]
    ex = getattr(snap, "extras", None)
    n = len(idx)
    if ex is not None:
        cid, vis = torch.from_numpy(ex.cid[idx]), torch.from_numpy(ex.vis[idx])
        reg = torch.from_numpy(ex.reg[idx])
        lessons = [torch.from_numpy(getattr(ex, f)[idx]) for f in LESSONS]
    else:
        from .extras import N_GAP, N_VIS
        cid = torch.zeros((n, 10), dtype=torch.int64)
        reg = torch.zeros((n, 10), dtype=torch.int64)
        vis = torch.zeros((n, 10, N_VIS))
        lessons = [torch.full((n,), 2), torch.full((n,), 10), torch.zeros(n),
                   torch.zeros(n, dtype=torch.bool), torch.full((n,), 10),
                   torch.full((n,), N_GAP - 1), torch.zeros(n, dtype=torch.int64)]
    inputs = [torch.from_numpy(snap.players[idx]),
              torch.from_numpy(global_features(st)),
              torch.from_numpy(st["map_id"].to_numpy(dtype=np.int64, copy=True)),
              torch.from_numpy(st["round_type_id"].to_numpy(dtype=np.int64, copy=True)),
              torch.from_numpy(st["plant_site"].clip(0, 2).to_numpy(dtype=np.int64, copy=True)),
              torch.from_numpy(st["tier_id"].to_numpy(dtype=np.int64, copy=True)),
              torch.from_numpy(st[["level_ct_id", "level_t_id"]].to_numpy(dtype=np.int64, copy=True)),
              cid, vis, reg]
    return inputs, torch.from_numpy(st[LABEL].to_numpy(dtype=np.float32, copy=True)), lessons


def _take(data, b):
    x, y, a = data
    return [t[b] for t in x], y[b], [t[b] for t in a]


# Weight of each extra lesson beside the win (ml/extras.py). The win is what
# is measured; the lessons are there to teach the game, so they count less.
AUX_WEIGHT = 0.3


def _objective(model, x, y, a, aux_weight=None):
    if not getattr(model, "aux", False):
        return nn.functional.binary_cross_entropy_with_logits(model(*x), y)
    out = model(*x, with_aux=True)
    side, slot, plant, plant_ok, killer, gap, end = a
    loss = nn.functional.binary_cross_entropy_with_logits(out["win"], y)
    extra = nn.functional.cross_entropy(out["side"], side)
    if "slot" in out:
        extra = extra + nn.functional.cross_entropy(out["slot"], slot)
    if plant_ok.any():
        extra = extra + nn.functional.binary_cross_entropy_with_logits(
            out["plant"][plant_ok], plant[plant_ok])
    if "gap" in out:
        extra = extra + nn.functional.cross_entropy(out["gap"], gap)
        extra = extra + nn.functional.cross_entropy(out["end"], end)
    if "killer" in out:
        extra = extra + nn.functional.cross_entropy(out["killer"], killer)
    return loss + (AUX_WEIGHT if aux_weight is None else aux_weight) * extra


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
    """Validation is judged on the win alone, the thing that is measured."""
    model.eval()
    x, y, _a = data
    return float(nn.functional.binary_cross_entropy_with_logits(model(*x), y))


def _run(model, train_data, val_data, lr, seed, max_epochs=MAX_EPOCHS,
         patience=PATIENCE, aux_weight=None):
    """One training run with early stopping. Returns the best val loss."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    gen = torch.Generator().manual_seed(seed)
    n = len(train_data[1])
    best, best_state, stale = float("inf"), None, 0
    for _epoch in range(max_epochs):
        model.train()
        order = torch.randperm(n, generator=gen)
        for start in range(0, n, BATCH):
            b = order[start:start + BATCH]
            x, y, a = _take(train_data, b)
            loss = _objective(model, x, y, a, aux_weight)
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
            if stale >= patience:
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
        x, _y, _a = tensors(snap, idx)
        out = []
        for s in range(0, len(idx), 4096):
            out.append(torch.sigmoid(self.model(*(t[s:s + 4096] for t in x))))
        return torch.cat(out).numpy()


def train(snap, train_idx, seed: int = 7, use_players: bool = True,
          pretrain_idx=None, use_levels: bool = False,
          pretrain_patience: int = PATIENCE, pretrain_epochs: int = MAX_EPOCHS,
          keep_mix: float = 0.0, use_kit: bool = False,
          use_callouts: bool = False, use_vision: bool = False,
          aux: bool = False, use_regions: bool = False,
          more_lessons: bool = False, aux_weight: float | None = None) -> Fit:
    """`pretrain_patience` and `pretrain_epochs` let the pretraining stage
    run longer before it gives up; `keep_mix` keeps that share of
    pretraining rows (relative to the college rows) in the fine-tuning
    stage, so the college stage adjusts what pretraining learned instead
    of overwriting it. Both measured in ml/evaluate.py (NETLONG)."""
    torch.manual_seed(seed)
    model = WinNet(use_players=use_players, use_levels=use_levels, use_kit=use_kit,
                   use_callouts=use_callouts, use_vision=use_vision, aux=aux,
                   use_regions=use_regions, more_lessons=more_lessons)
    fit_idx, val_idx = _split_matches(snap, np.asarray(train_idx), 0.1, seed)
    val = tensors(snap, val_idx)
    lr = 2e-3
    if pretrain_idx is not None:
        # Pro and college together first, early-stopped on COLLEGE matches,
        # then college alone at a lower rate so the pro habits are adjusted
        # rather than forgotten.
        both = np.concatenate([fit_idx, np.asarray(pretrain_idx)])
        _run(model, tensors(snap, both), val, lr, seed,
             max_epochs=pretrain_epochs, patience=pretrain_patience,
             aux_weight=aux_weight)
        lr = 5e-4
    tune_idx = fit_idx
    if pretrain_idx is not None and keep_mix > 0:
        extra = np.random.default_rng(seed).choice(
            np.asarray(pretrain_idx), size=min(len(pretrain_idx),
                                               int(keep_mix * len(fit_idx))),
            replace=False)
        tune_idx = np.concatenate([fit_idx, extra])
    best = _run(model, tensors(snap, tune_idx), val, lr, seed + 1, aux_weight=aux_weight)
    return Fit(model, best)
