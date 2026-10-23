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

# x, y, z, health, alive, facing (2), bombsite (2): the snapshot as first
# measured. The rest of PLAYER_FEATURES is movement, weapon and grenades.
BASE_PLAYER = 9

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
                 use_players: bool = True, use_levels: bool = False,
                 use_kit: bool = False, use_callouts: bool = False,
                 use_vision: bool = False, aux: bool = False,
                 use_regions: bool = False, more_lessons: bool = False):
        super().__init__()
        self.use_players = use_players
        # 2026-10-23 (ml/extras.py), all off by default so every earlier arm
        # is the same network: which callout each player stands in, as an
        # embedding per (map, callout); what the enemy can see of each
        # player; and `aux`, heads that learn who dies next and whether the
        # bomb goes down, from the same rounds, beside the win.
        # Later the same day: `use_regions`, each callout as one of a few
        # regions every map shares (ml/extras.REGIONS); `more_lessons`, who
        # gets the next kill, how soon, and how the round ends.
        from .extras import END_KINDS, N_CALLOUT_IDS, N_GAP, N_VIS, REGIONS
        self.use_callouts, self.use_vision, self.aux = use_callouts, use_vision, aux
        self.use_regions, self.more_lessons = use_regions, more_lessons and aux
        if use_callouts:
            self.callout_emb = nn.Embedding(N_CALLOUT_IDS, 8)
        if use_regions:
            self.region_emb = nn.Embedding(len(REGIONS), 4)
        n_extra = ((8 if use_callouts else 0) + (N_VIS if use_vision else 0)
                   + (4 if use_regions else 0))
        self.map_emb = nn.Embedding(len(MAPS) + 1, 8)      # + UNKNOWN_MAP_ID
        self.type_emb = nn.Embedding(len(ROUND_TYPES), 4)
        self.site_emb = nn.Embedding(3, 4)                 # none, site 1, site 2
        self.tier_emb = nn.Embedding(len(TIERS), 4)
        # Each side's skill level (ml/levels.py: NECC division, ESEA
        # division, pro), one shared table so "D2" means the same on either
        # side. Off by default: the measured arms say whether it helps.
        self.use_levels = use_levels
        # Movement over the last second, weapon class and grenades per
        # player (posfeat.PLAYER_FEATURES after the first BASE_PLAYER) are
        # off by default: measured 2026-10-14, they lost 0.001 to 0.002 AUC
        # on both protocols (ml/README.md). Kept so the test can be rerun.
        self.n_player = len(PLAYER_FEATURES) if use_kit else BASE_PLAYER
        if use_levels:
            from .levels import LEVELS
            self.level_emb = nn.Embedding(len(LEVELS), 4)
        pooled = 0
        if use_players:
            self.encode = nn.Sequential(
                nn.Linear(self.n_player + 8 + n_extra, d), nn.GELU(),
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
        if aux:
            self.side_head = nn.Linear(64, 3)          # CT dies next, T, nobody
            self.plant_head = nn.Linear(64, 1)         # bomb down within 10 s
            self.none_head = nn.Linear(64, 1)          # "nobody" beside 10 slots
            self.slot_head = nn.Linear(d, 1) if use_players else None
            if self.more_lessons:
                self.gap_head = nn.Linear(64, N_GAP)
                self.end_head = nn.Linear(64, len(END_KINDS))
                self.killer_none = nn.Linear(64, 1)
                self.killer_head = nn.Linear(d, 1) if use_players else None

    def forward(self, players, glob, map_id, type_id, site, tier, levels=None,
                cid=None, vis=None, reg=None, with_aux: bool = False):
        m = self.map_emb(map_id)
        parts = [glob, m, self.type_emb(type_id), self.site_emb(site),
                 self.tier_emb(tier)]
        if self.use_levels:
            parts += [self.level_emb(levels[:, 0]), self.level_emb(levels[:, 1])]
        if self.use_players:
            players = players[..., :self.n_player]
            # A slot is empty when nobody played it (all zeros, including the
            # alive bit AND the coordinates). A dead player is NOT empty: where
            # they died is information.
            empty = players.abs().sum(-1) == 0                       # (B, 10)
            mm = m.unsqueeze(1).expand(-1, players.shape[1], -1)
            per = [players, mm]
            if self.use_callouts:
                per.append(self.callout_emb(cid))
            if self.use_vision:
                per.append(vis)
            if self.use_regions:
                per.append(self.region_emb(reg))
            h = self.encode(torch.cat(per, -1))
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
        trunk = self.head[:-1](torch.cat(parts, -1))
        win = self.head[-1](trunk).squeeze(-1)
        if not with_aux:
            return win
        out = {"win": win}
        if self.aux:
            out["side"] = self.side_head(trunk)
            out["plant"] = self.plant_head(trunk).squeeze(-1)
            none = self.none_head(trunk)
            if self.use_players:
                slots = self.slot_head(h).squeeze(-1).masked_fill(empty, -1e4)
                out["slot"] = torch.cat([slots, none], -1)        # (B, 11)
            if self.more_lessons:
                out["gap"] = self.gap_head(trunk)
                out["end"] = self.end_head(trunk)
                if self.use_players:
                    k = self.killer_head(h).squeeze(-1).masked_fill(empty, -1e4)
                    out["killer"] = torch.cat([k, self.killer_none(trunk)], -1)
        return out


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
