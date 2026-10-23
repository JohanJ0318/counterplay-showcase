"""More for WinNet to read, and more for it to learn, from the same demos.

    ex = extras.load(snap)          # cached in data/ml/, aligned to snap.states

Johan, 2026-10-23: make the network beat the trees "given that it is more
capable and more understanding of the game". Two things the trees cannot use:

INPUTS, per player (the trees only get team totals):
  cid   (rows, 10) int64   which of the game's callouts they stand in
                           (counterplay/callouts.py), as map * CALLOUTS_PER_MAP
                           + callout, 0 for an empty slot or a map without
                           callout files. Learned as an embedding, so "B Site
                           on Nuke" is its own thing to the network.
  vis   (rows, 10, 4)      how many enemies can see them / 5, how many enemies
                           they can see / 5, whether the demo carries vision
                           at all (positions version 2; version 1 rounds read
                           as unknown, never as "nobody sees"), and how long
                           since any enemy last saw them / SEEN_LOOKBACK (1 if
                           not within it). The game's spotting is sparse: a
                           living player is seen by an enemy in 1.7% of
                           samples, so "seen right now" is mostly zero and the
                           recency carries most of what vision knows.

LESSONS, per moment (one round gives one win label, shared by every moment
in it, which is very little to learn the game from; these are several per
moment, read off the death and plant events that follow it):
  next_side  (rows,)  0 a CT dies next, 1 a T dies next, 2 nobody else dies
  next_slot  (rows,)  which of the ten slots dies next, 10 nobody
  plant10    (rows,)  the bomb is planted within PLANT_WINDOW seconds
  plant_ok   (rows,)  plant10 means something: not planted yet

Slots, alive-ness and the moment's sample are read exactly as
counterplay/posfeat.py reads them, so slot k here is slot k in snap.players.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app import db
from counterplay import callouts as CO
from counterplay import positions as P
from counterplay import posfeat as PF
from counterplay.schema import MAPS

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ml"
VERSION = 3
CALLOUTS_PER_MAP = 64
N_CALLOUT_IDS = (len(MAPS) + 1) * CALLOUTS_PER_MAP
PLANT_WINDOW = 10.0
N_VIS = 4
# How far back "last seen by the enemy" looks, in seconds.
SEEN_LOOKBACK = 10.0
# Seconds until the next death, as classes: within 2, 5, 10, 20, later or never.
GAP_EDGES = (2.0, 5.0, 10.0, 20.0)
N_GAP = len(GAP_EDGES) + 1
# How the round ends, read off the events (no end reason is stored): the
# CTs all died, the bomb went off (planted, Ts won, CTs left), the Ts all
# died, a defuse (planted, CTs won, Ts left), or time ran out.
END_KINDS = ("ct_dead", "bomb", "t_dead", "defuse", "time")
# Simpler places (2026-10-23): ~190 callouts were too many to learn from
# this many rounds, so each callout is also one of a few regions shared by
# every map, "A site" meaning the same thing on Mirage and Nuke.
REGIONS = ("unknown", "a_site", "b_site", "mid", "t_ground", "ct_ground", "contested")


def region_of(c: dict) -> int:
    name = (c.get("label") or "").lower()
    if name in ("a site", "bombsitea") or name.startswith("a site"):
        return 1
    if name in ("b site", "bombsiteb") or name.startswith("b site"):
        return 2
    if "mid" in name.split() or name in ("middle", "top of mid", "lower mid", "second mid"):
        return 3
    share = c.get("t_share")
    if "t spawn" in name or (share is not None and share > 0.65):
        return 4
    if "ct spawn" in name or (share is not None and share < 0.35):
        return 5
    return 6


@dataclass
class Extras:
    cid: np.ndarray
    vis: np.ndarray
    next_side: np.ndarray
    next_slot: np.ndarray
    plant10: np.ndarray
    plant_ok: np.ndarray
    reg: np.ndarray
    next_killer: np.ndarray
    next_gap: np.ndarray
    round_end: np.ndarray


def build(states) -> Extras:
    n = len(states)
    cid = np.zeros((n, PF.SLOTS), dtype=np.int64)
    vis = np.zeros((n, PF.SLOTS, N_VIS), dtype=np.float32)
    next_side = np.full(n, 2, dtype=np.int64)
    next_slot = np.full(n, 10, dtype=np.int64)
    plant10 = np.zeros(n, dtype=np.float32)
    plant_ok = np.zeros(n, dtype=bool)
    reg = np.zeros((n, PF.SLOTS), dtype=np.int64)
    next_killer = np.full(n, 10, dtype=np.int64)
    next_gap = np.full(n, N_GAP - 1, dtype=np.int64)
    round_end = np.zeros(n, dtype=np.int64)
    if not n:
        return Extras(cid, vis, next_side, next_slot, plant10, plant_ok,
                      reg, next_killer, next_gap, round_end)
    pos = states.reset_index(drop=True)
    keys = list(pos["match_id"].unique())
    marks = ",".join("?" * len(keys))
    maps = {r["match_key"]: r["map_name"] for r in db.query(
        f"SELECT match_key, map_name FROM matches WHERE match_key IN ({marks})", *keys)}
    deaths: dict = {}
    plants: dict = {}
    for e in db.query(f"""SELECT match_key, round_num, seconds, type, victim_steamid,
                                   attacker_steamid
                            FROM events WHERE match_key IN ({marks})""", *keys):
        k = (e["match_key"], e["round_num"])
        if e["type"] == "death" and e["victim_steamid"]:
            att = e["attacker_steamid"]
            deaths.setdefault(k, []).append((float(e["seconds"]), int(e["victim_steamid"]),
                                             int(att) if att else None))
        elif e["type"] == "plant":
            plants[k] = min(plants.get(k, 1e9), float(e["seconds"]))

    for (mk, rn), rows in pos.groupby(["match_id", "round_num"]).indices.items():
        r = db.one("SELECT data FROM round_positions WHERE match_key = ? AND "
                   "round_num = ?", mk, int(rn))
        got = P.unpack_round(r["data"]) if r else None
        if got is None or not got[0]["n_samples"]:
            continue
        meta, sids, samples = got
        slot_of = {int(sid): i for i, sid in enumerate(sids)}
        died = sorted((sec, slot_of[v], slot_of.get(a)) for sec, v, a in
                      deaths.get((mk, int(rn)), []) if v in slot_of)
        ct, t = PF._round_players(samples["flags"])
        slot = {i: k for k, i in enumerate(ct)}
        slot.update({i: 5 + k for k, i in enumerate(t)})
        side_of = {i: 0 for i in ct} | {i: 1 for i in t}
        mp = maps.get(mk, "")
        co = CO.load(mp)
        m_id = MAPS.index(mp) if mp in MAPS else len(MAPS)
        has_vision = bool(meta.get("vision"))
        planted_at = plants.get((mk, int(rn)))
        n_s = meta["n_samples"]
        ct_won = bool(pos.at[rows[0], "ct_won"])
        ct_left = len(ct) - sum(1 for _s, v, _a in died if v in ct)
        t_left = len(t) - sum(1 for _s, v, _a in died if v in t)
        if not ct_won:
            end = 0 if ct_left <= 0 else 1
        else:
            end = 2 if t_left <= 0 else (3 if planted_at is not None else 4)
        reg_of = ({k: region_of(c) for k, c in co.callouts.items()} if co else {})
        for row in rows:
            secs = float(pos.at[row, "seconds"])
            i = min(n_s - 1, int(np.ceil(secs * P.TICK_RATE / meta["tick_step"])))
            s = samples[i]
            dead = {sl for sec, sl, _a in died if sec <= secs + 1e-6}
            round_end[row] = end
            roster = [(base + k, ix) for base, idx in ((0, ct), (5, t))
                      for k, ix in enumerate(idx)]
            if co is not None and roster:
                ix = np.array([q[1] for q in roster])
                got_c = co.assign(s["x"][ix].astype(float), s["y"][ix].astype(float),
                                  s["z"][ix].astype(float))
                for (sl, _), c in zip(roster, got_c):
                    if c:
                        cid[row, sl] = m_id * CALLOUTS_PER_MAP + min(int(c), CALLOUTS_PER_MAP - 1)
                        reg[row, sl] = reg_of.get(int(c), 0)
            if has_vision:
                seen = s["seen_by"]
                back = max(0, i - int(SEEN_LOOKBACK * P.TICK_RATE / meta["tick_step"]))
                for sl, ix in roster:
                    if ix in dead:
                        vis[row, sl, 2:] = (1.0, 1.0)
                        continue
                    enemies = t if ix in ct else ct
                    live_en = [j for j in enemies if j not in dead]
                    by = sum(1 for j in live_en if (int(seen[ix]) >> j) & 1)
                    sees = sum(1 for j in live_en if (int(seen[j]) >> ix) & 1)
                    emask = sum(1 << j for j in enemies if j < P.MAX_SEEN_BY)
                    hits = np.flatnonzero(samples["seen_by"][back:i + 1, ix].astype(int) & emask)
                    ago = ((i - back - hits[-1]) * meta["tick_step"] / P.TICK_RATE
                           if len(hits) else SEEN_LOOKBACK)
                    vis[row, sl] = (by / 5.0, sees / 5.0, 1.0,
                                    min(ago, SEEN_LOOKBACK) / SEEN_LOOKBACK)
            nxt = next(((sec, sl, a) for sec, sl, a in died if sec > secs + 1e-6
                        and sl in slot), None)
            if nxt is not None:
                next_side[row] = side_of[nxt[1]]
                next_slot[row] = slot[nxt[1]]
                if nxt[2] in slot:
                    next_killer[row] = slot[nxt[2]]
                next_gap[row] = int(np.searchsorted(GAP_EDGES, nxt[0] - secs))
            if planted_at is None or planted_at > secs + 1e-6:
                plant_ok[row] = True
                plant10[row] = float(planted_at is not None
                                     and planted_at - secs <= PLANT_WINDOW)
    return Extras(cid, vis, next_side, next_slot, plant10, plant_ok,
                  reg, next_killer, next_gap, round_end)


def load(snap, rebuild: bool = False, name: str = "") -> Extras:
    """Cached next to the snapshot cache; rebuilt when the row count moves.
    `name` keeps a second set apart (the timed moments, ml/data.py)."""
    path = CACHE / f"extras{name}_v{VERSION}.npz"
    if path.exists() and not rebuild:
        z = np.load(path)
        if len(z["cid"]) == len(snap.states):
            return Extras(*(z[f] for f in Extras.__dataclass_fields__))
    ex = build(snap.states)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **{f: getattr(ex, f) for f in Extras.__dataclass_fields__})
    return ex


if __name__ == "__main__":
    import os
    import time
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from . import data
    db.init()
    snap = data.load()
    t0 = time.time()
    ex = load(snap, rebuild=True)
    print(f"{len(ex.cid)} rows in {time.time() - t0:.0f}s; callout known for "
          f"{(ex.cid > 0).mean():.1%} of slots; vision on "
          f"{ex.vis[:, :, 2].max(1).astype(bool).mean():.1%} of rows; next death "
          f"CT/T/none {np.bincount(ex.next_side, minlength=3) / len(ex.cid)}; "
          f"plant within 10 s on {ex.plant10[ex.plant_ok].mean():.1%} of unplanted rows")
