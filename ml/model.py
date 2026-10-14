"""WinNet: a round win-probability model that can see where everyone is.

Input per moment:
  players  (10, F)  five CT slots then five T slots (ml.data.PLAYER_FEATURES)
  globals  (G,)     what the shipped model already sees: alive counts, the
                    equipment ratio, time left, the bomb (see GLOBAL below)
  map, buy type, plant site, tier   as small learned embeddings

Shape of the network:

  1. Each player is encoded on its own by a small MLP, with the map's
     embedding concatenated in: the same (x, y) means a different place on
     every map, so the encoder has to know which map it is reading.
  2. A learned "side" vector is added, CT or T.
  3. One self-attention layer lets every player look at every other: this
     is where spacing, a crossfire or a lone lurker can show up, which no
     count of alive players can express. Empty slots are masked out.
  4. Each side is pooled (mean and max over its slots), so the order of
     players inside a side never matters: the input is a set, not a list.
  5. The pooled sides, the global numbers and the embeddings go through a
     final MLP to one logit: P(CT wins the round).

About 40,000 parameters. The data is roughly 4,000 collegiate rounds plus
2,000 pro ones (tools/baselines.py showed even the shipped LightGBM was too
big for it), so the network is kept small and regularised on purpose.
`use_players=False` drops steps 1 to 4, which leaves an MLP on the same
eleven numbers LightGBM sees: the control that says whether positions, and
not just a different model family, are what moved the result.
"""
from __future__ import annotations

import numpy as np
import torch
from torch import nn

from counterplay.schema import MAPS, ROUND_TYPES, TIERS

from .data import PLAYER_FEATURES

GLOBAL = ["alive_ct", "alive_t", "equip_log_ratio", "equip_ct", "equip_t",
          "time_left", "bomb_planted", "time_since_plant"]


def global_features(states) -> np.ndarray:
    """The shipped model's numeric state, scaled to roughly unit range."""
    return np.stack([
        states["alive_ct"] / 5.0,
        states["alive_t"] / 5.0,
        np.log((states["equip_ct"] + 500.0) / (states["equip_t"] + 500.0)),
        states["equip_ct"] / 30000.0,
        states["equip_t"] / 30000.0,
        states["time_left"] / 115.0,
        states["bomb_planted"].astype(float),
        states["time_since_plant"] / 40.0,
    ], axis=1).astype(np.float32)


class WinNet(nn.Module):
    def __init__(self, d: int = 48, heads: int = 4, dropout: float = 0.1,
                 use_players: bool = True, use_levels: bool = False):
        super().__init__()
        self.use_players = use_players
        self.map_emb = nn.Embedding(len(MAPS) + 1, 8)      # + UNKNOWN_MAP_ID
        self.type_emb = nn.Embedding(len(ROUND_TYPES), 4)
        self.site_emb = nn.Embedding(3, 4)                 # none, site 1, site 2
        self.tier_emb = nn.Embedding(len(TIERS), 4)
        # Each side's skill level (ml/levels.py: NECC division, ESEA
        # division, pro), one shared table so "D2" means the same on either
        # side. Off by default: the measured arms say whether it helps.
        self.use_levels = use_levels
        if use_levels:
            from .levels import LEVELS
            self.level_emb = nn.Embedding(len(LEVELS), 4)
        pooled = 0
        if use_players:
            self.encode = nn.Sequential(
                nn.Linear(len(PLAYER_FEATURES) + 8, d), nn.GELU(),
                nn.Linear(d, d))
            self.side = nn.Parameter(torch.zeros(2, d))
            self.attn = nn.MultiheadAttention(d, heads, dropout=dropout,
                                              batch_first=True)
            self.norm = nn.LayerNorm(d)
            pooled = 4 * d                                 # (mean, max) x 2 sides
        self.head = nn.Sequential(
            nn.Linear(pooled + len(GLOBAL) + 8 + 4 + 4 + 4
                      + (8 if use_levels else 0), 64), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(64, 1))

    def forward(self, players, glob, map_id, type_id, site, tier, levels=None):
        m = self.map_emb(map_id)
        parts = [glob, m, self.type_emb(type_id), self.site_emb(site),
                 self.tier_emb(tier)]
        if self.use_levels:
            parts += [self.level_emb(levels[:, 0]), self.level_emb(levels[:, 1])]
        if self.use_players:
            # A slot is empty when nobody played it (all zeros, including the
            # alive bit AND the coordinates). A dead player is NOT empty: where
            # they died is information.
            empty = players.abs().sum(-1) == 0                       # (B, 10)
            mm = m.unsqueeze(1).expand(-1, players.shape[1], -1)
            h = self.encode(torch.cat([players, mm], -1))
            h = h + torch.repeat_interleave(self.side, 5, dim=0)    # CT x5, T x5
            # Guard: a row with every slot empty would make attention NaN.
            safe = empty.clone()
            safe[safe.all(1)] = False
            a, _ = self.attn(h, h, h, key_padding_mask=safe)
            h = self.norm(h + a)
            keep = (~empty).unsqueeze(-1).float()
            for lo in (0, 5):
                hs, ks = h[:, lo:lo + 5], keep[:, lo:lo + 5]
                n = ks.sum(1).clamp(min=1.0)
                parts.append((hs * ks).sum(1) / n)                    # mean
                parts.append((hs * ks - (1 - ks) * 1e4).max(1).values  # max
                             .clamp(min=-1e3))
        return self.head(torch.cat(parts, -1)).squeeze(-1)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
