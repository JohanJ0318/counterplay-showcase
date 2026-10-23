"""What a team could know at a moment: the rule every suggestion obeys.

A suggestion about what a player should have done may use only what that
player's team could have known then (Johan, 2026-10-14). Their own players
they always know. An enemy they know only as far as the game showed him:

  visible     a teammate can see him now (the demo's approximate_spotted_by,
              stored per sample since positions version 2)
  last seen   where he was the last time any of them could see him, and how
              many seconds ago, so a player could reason how far he can
              have gone since
  unknown     never seen this round

Rounds parsed before version 2 carry no vision; Round.vision is False and
every question here answers None rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import positions as P


@dataclass
class Sighting:
    state: str                  # "visible", "last_seen", "unknown"
    seconds_ago: float | None   # 0 when visible
    x: float | None
    y: float | None
    z: float | None


class Round:
    """One round's samples with the roster resolved to steamids and sides."""

    def __init__(self, blob: bytes):
        got = P.unpack_round(blob)
        if got is None:
            raise ValueError("no position data for this round")
        self.meta, sids, self.samples = got
        self.vision = bool(self.meta.get("vision"))
        self.steamids = [str(int(s)) for s in sids]
        self.index = {sid: i for i, sid in enumerate(self.steamids)}
        self.secs = P.sample_seconds(self.meta)
        flags = self.samples["flags"]
        early = (flags[:16] & P.FLAG_ALIVE) != 0
        self.played = early.any(axis=0)
        self.is_ct = ((flags[:16] & P.FLAG_CT) != 0).any(axis=0)

    def at(self, seconds: float) -> int:
        """The last sample at or before `seconds` (what was true then)."""
        i = int(np.searchsorted(self.secs, seconds, side="right")) - 1
        return max(0, min(i, self.meta["n_samples"] - 1))

    def side_of(self, steamid: str) -> str | None:
        i = self.index.get(str(steamid))
        if i is None:
            return None
        return "ct" if self.is_ct[i] else "t"

    def team(self, side: str) -> list[int]:
        want = side == "ct"
        return [i for i in range(len(self.steamids))
                if self.played[i] and self.is_ct[i] == want]

    def alive(self, i: int, s: int) -> bool:
        return bool(self.samples["flags"][s, i] & P.FLAG_ALIVE)

    def pos(self, i: int, s: int) -> np.ndarray:
        p = self.samples[s, i]
        return np.array([float(p["x"]), float(p["y"]), float(p["z"])])

    def seen_by(self, i: int, s: int) -> set[int]:
        """Roster indices who can see player i at sample s."""
        if not self.vision:
            return set()
        m = int(self.samples["seen_by"][s, i])
        return {k for k in range(min(len(self.steamids), P.MAX_SEEN_BY)) if m >> k & 1}

    def sighting(self, enemy: int, team: list[int], s: int) -> Sighting | None:
        """What `team` knew about `enemy` at sample s. None without vision."""
        if not self.vision:
            return None
        mask = 0
        for k in team:
            if k < P.MAX_SEEN_BY:
                mask |= 1 << k
        col = self.samples["seen_by"][: s + 1, enemy].astype(np.int64) & mask
        hits = np.flatnonzero(col)
        if not len(hits):
            return Sighting("unknown", None, None, None, None)
        last = int(hits[-1])
        x, y, z = self.pos(enemy, last)
        ago = float(self.secs[s] - self.secs[last])
        return Sighting("visible" if last == s else "last_seen", ago, x, y, z)


def view_angle_to(rnd: Round, viewer: int, target: int, s: int) -> float:
    """Degrees between where `viewer` was looking and `target`'s head at s.

    Yaw and pitch come from the samples (pitch since version 2; without it
    the angle is horizontal only). 64 units is eye height standing.
    """
    v, t = rnd.samples[s, viewer], rnd.samples[s, target]
    yaw = np.radians(float(v["yaw"]) / 255.0 * 360.0 - 180.0)
    pitch = (np.radians(float(v["pitch"]) * 90.0 / 127.0)
             if rnd.vision else 0.0)
    look = np.array([np.cos(pitch) * np.cos(yaw), np.cos(pitch) * np.sin(yaw),
                     -np.sin(pitch)])
    d = np.array([float(t["x"]) - float(v["x"]), float(t["y"]) - float(v["y"]),
                  (float(t["z"]) + 64.0) - (float(v["z"]) + 64.0)])
    if not rnd.vision:
        look[2], d[2] = 0.0, 0.0
    n = np.linalg.norm(look) * np.linalg.norm(d)
    if n == 0:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(look @ d / n, -1.0, 1.0))))
