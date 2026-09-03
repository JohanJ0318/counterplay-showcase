"""Positional data: where everyone was, sampled through each round.

The one thing the event-based parse deliberately throws away, and the thing
Pattern Finder needs to exist. "A-site execute off a mid smoke" is not
detectable from a list of deaths — you have to know where five people were.

Stored as one packed blob per ROUND, not one row per player per tick. A round
at 8 Hz is ~1,400 player-samples; a season is millions. Those samples are only
ever read a whole round at a time — to draw a replay window, or to scan a round
for a pattern — never queried individually, so a blob is both the right shape
and roughly forty times smaller than the equivalent rows.

    round → header + roster + samples
    sample = one tick × every player on the server that round

Everything about the format is fixed-width, so unpacking is a numpy view rather
than a parse.

WHY 8 Hz
--------
An eighth of a second is finer than any decision a coach discusses. Measured on
a real 22-round Premier demo: 8 Hz costs 0.6 seconds and 1.7MB per match, and
64 Hz costs 6.5 seconds and 14MB to answer no question anyone is asking.

WHY int16 COORDINATES
---------------------
CS2 world units are roughly an inch. Across seven maps the widest coordinate
seen is -2,642 to 3,514, so int16 holds every map with ~29,000 units of
headroom and truncation loses less than one unit. Storing float32 would triple
the size for precision nobody can act on.

DEAD PLAYERS ARE NOT DROPPED
----------------------------
A dead player's position stops updating and holds where they died, which is
exactly the information a death-location heatmap needs. They are kept, with the
alive bit cleared, so a reader can tell "standing here" from "died here".
"""
from __future__ import annotations

import struct

import numpy as np

# The sampling rate, in ticks. CS2 runs at 64 ticks/second, so 8 ticks is 8 Hz.
SAMPLE_STEP = 8
TICK_RATE = 64.0

FORMAT_VERSION = 1

# Per player per sample: x, y, z (int16), yaw (uint8), health (uint8),
# flags (uint8). 9 bytes.
SAMPLE_DTYPE = np.dtype([
    ("x", "<i2"), ("y", "<i2"), ("z", "<i2"),
    ("yaw", "u1"), ("health", "u1"), ("flags", "u1"),
])

FLAG_ALIVE = 0b0001
FLAG_CT = 0b0010
# Bits 2-3 hold `which_bomb_zone`: 0 = not in a bombsite, 1 and 2 are the two
# sites as CS2 itself defines them. This is the whole reason no map geometry
# has to be authored by hand — the game already knows where its bombsites are,
# so "how many players were in the site at 30 seconds" is answerable without
# anyone drawing a polygon. Zone numbering is consistent within a map; which
# of 1 and 2 is called A is a naming question, not a data one.
ZONE_SHIFT = 2
ZONE_MASK = 0b1100

# version, tick_start, tick_step, n_samples, n_players
HEADER = struct.Struct("<BIHHB")

TEAM_CT = 3


def _quantise_yaw(yaw: np.ndarray) -> np.ndarray:
    """-180..180 degrees into a single byte. 1.4 degrees per step.

    Facing is used for "which way were they looking", never for aim analysis,
    so a byte is ample and a float would cost four times as much for nothing.
    """
    y = np.nan_to_num(np.asarray(yaw, dtype=np.float64), nan=0.0)
    return np.clip(((y + 180.0) / 360.0 * 255.0).round(), 0, 255).astype(np.uint8)


def pack_round(ticks: list[int], steamids: list[int], frame) -> bytes | None:
    """Pack one round's samples.

    `frame` is the parse_ticks dataframe for this round, `steamids` fixes the
    player order, and `ticks` the sample order. A player missing from a tick —
    disconnected, or joined late — is written as all-zero with the alive bit
    clear, so every sample is the same width and the reader needs no index.
    """
    if not ticks or not steamids:
        return None

    n_s, n_p = len(ticks), len(steamids)
    grid = np.zeros((n_s, n_p), dtype=SAMPLE_DTYPE)

    tick_pos = {t: i for i, t in enumerate(ticks)}
    sid_pos = {int(s): i for i, s in enumerate(steamids)}

    t_idx = frame["tick"].map(tick_pos)
    s_idx = frame["steamid"].astype("uint64").map(sid_pos)
    keep = t_idx.notna() & s_idx.notna()
    if not keep.any():
        return None
    f = frame[keep]
    ti = t_idx[keep].to_numpy(dtype=np.int64)
    si = s_idx[keep].to_numpy(dtype=np.int64)

    # Truncation, not rounding: half a world unit is a quarter of an inch.
    grid["x"][ti, si] = np.clip(np.nan_to_num(f["X"].to_numpy()), -32768, 32767).astype(np.int16)
    grid["y"][ti, si] = np.clip(np.nan_to_num(f["Y"].to_numpy()), -32768, 32767).astype(np.int16)
    grid["z"][ti, si] = np.clip(np.nan_to_num(f["Z"].to_numpy()), -32768, 32767).astype(np.int16)
    grid["yaw"][ti, si] = _quantise_yaw(f["yaw"].to_numpy())
    grid["health"][ti, si] = np.clip(np.nan_to_num(f["health"].to_numpy()), 0, 255).astype(np.uint8)

    alive = f["is_alive"].fillna(False).to_numpy().astype(bool)
    is_ct = (f["team_num"].fillna(0).to_numpy().astype(int) == TEAM_CT)
    zone = np.clip(np.nan_to_num(f["which_bomb_zone"].to_numpy() if
                                 "which_bomb_zone" in f.columns else 0), 0, 3).astype(np.uint8)
    grid["flags"][ti, si] = (alive * FLAG_ALIVE + is_ct * FLAG_CT
                             + (zone << ZONE_SHIFT)).astype(np.uint8)

    head = HEADER.pack(FORMAT_VERSION, int(ticks[0]), SAMPLE_STEP, n_s, n_p)
    roster = np.asarray(steamids, dtype="<u8").tobytes()
    return head + roster + grid.tobytes()


def unpack_round(blob: bytes):
    """(meta, steamids, samples) — samples is an (n_samples, n_players) array.

    Returned as a numpy view over the buffer, so reading a round costs a memcpy
    of the header and nothing else.
    """
    if not blob or len(blob) < HEADER.size:
        return None
    version, tick_start, tick_step, n_s, n_p = HEADER.unpack_from(blob, 0)
    if version != FORMAT_VERSION:
        raise ValueError(f"position blob version {version}, expected {FORMAT_VERSION}")
    off = HEADER.size
    steamids = np.frombuffer(blob, dtype="<u8", count=n_p, offset=off)
    off += n_p * 8
    samples = np.frombuffer(blob, dtype=SAMPLE_DTYPE, count=n_s * n_p,
                            offset=off).reshape(n_s, n_p)
    meta = {"tick_start": tick_start, "tick_step": tick_step,
            "n_samples": n_s, "n_players": n_p,
            "seconds": [(tick_start + i * tick_step - tick_start) / TICK_RATE
                        for i in range(0, 1)]}
    return meta, steamids, samples


def zone_of(flags) -> np.ndarray:
    """Which bombsite each sample is standing in: 0 for none, else 1 or 2."""
    return (np.asarray(flags) & ZONE_MASK) >> ZONE_SHIFT


def sample_seconds(meta: dict) -> np.ndarray:
    """Seconds since the round's freeze-end, one per sample."""
    return (np.arange(meta["n_samples"]) * meta["tick_step"]) / TICK_RATE


def extract(parser, bounds, sample_step: int = SAMPLE_STEP) -> dict[int, bytes]:
    """round number -> packed positions, for every round with samples.

    `bounds` is parse.py's (freeze_tick, end_tick, round_num) list. One
    parse_ticks call covers the whole match; splitting it per round would pay
    the demo's setup cost once per round instead of once per match.
    """
    scan: list[int] = []
    per_round: dict[int, list[int]] = {}
    for start, end, rn in bounds:
        rt = list(range(int(start), int(end) + 1, sample_step))
        if rt:
            per_round[rn] = rt
            scan.extend(rt)
    if not scan:
        return {}

    frame = parser.parse_ticks(
        ["X", "Y", "Z", "yaw", "health", "is_alive", "team_num",
         "which_bomb_zone"], ticks=scan)
    if not hasattr(frame, "columns") or "steamid" not in getattr(frame, "columns", ()):
        return {}

    out: dict[int, bytes] = {}
    by_tick = {rn: set(t) for rn, t in per_round.items()}
    for rn, ticks in per_round.items():
        chunk = frame[frame["tick"].isin(by_tick[rn])]
        if chunk.empty:
            continue
        # Fixed player order for the round, so a sample row is positional.
        steamids = sorted(int(s) for s in chunk["steamid"].dropna().unique())
        blob = pack_round(ticks, steamids, chunk)
        if blob:
            out[rn] = blob
    return out
