"""Where the map exists, taken from Valve's own radar image.

The zone pictures are drawn from where players have stood, and a corner that
somebody crosses twice a match is one or two samples in a grid of twenty-two
thousand cells. Those corners came out as holes: behind both spawns on Nuke,
suicide and T plat on Dust2, the ground before second mid on Inferno.

Valve already ships the answer. Every radar PNG has an alpha channel, and the
opaque part of it is the map: 48% of Dust2's square, 30% of Nuke's. That is a
better statement of "the map is here" than any number of rounds of position
data, because it does not depend on anybody having walked there.

WHAT IT IS USED FOR, AND WHAT IT IS NOT
---------------------------------------
The mask does NOT get filled in on its own. Valve's alpha covers roofs, walls
and the tops of buildings as well as the floor a player can stand on, so
painting all of it would draw zones across solid geometry.

It is used as a BOUNDARY instead: the played area is grown outward a few cells
at a time, and a cell may only be entered if the radar says there is map
there. That reaches into a corner adjacent to somewhere people go, and stops
at the void. The result is the played area with its corners completed, never a
guess about a part of the map nobody has visited.

WHY A HAND-WRITTEN PNG READER
-----------------------------
Pillow is not installed on the server and this is the only thing in the whole
product that needs to read an image. A one-file decoder for the exact subset
Valve ships, 8-bit RGBA, non-interlaced, is a smaller commitment than a
compiled imaging dependency to install, pin and keep current on the box.

The masks are built once by `python -m counterplay.radarmask` and stored, so
the decoder never runs while anybody is waiting for a page.
"""
from __future__ import annotations

import json
import pathlib
import struct
import zlib

import numpy as np

from . import radar as RD

# The stored mask's resolution. The pictures bin to 150, so 256 is finer than
# anything that reads it and still a 65KB boolean per map before compression.
MASK_N = 256

MASK_DIR = pathlib.Path(__file__).resolve().parents[1] / "site" / "radars"
MASK_FILE = MASK_DIR / "masks.json"

# Alpha below this is the transparent surround rather than faint map art.
ALPHA_FLOOR = 8

# NUKE'S LOWER IMAGE DRAWS THE UPPER FLOOR AS A GHOST, at alpha ~41, around
# the lower floor at 255. Counted as map, it let the drawing grow GROW_PASSES
# cells past every wall of the lower floor into the ghost. Measured
# 2026-09-27: 72.5% of that image's visible pixels are faint (alpha 9 to
# 127), at most 4% on any other radar, and no player position lands on one.
# An image whose faint pixels are the majority is read at SOLID_FLOOR.
SOLID_FLOOR = 128

_CACHE: dict | None = None


def _read_png(path) -> np.ndarray | None:
    """(h, w, 4) uint8, or None for anything outside the subset Valve ships."""
    d = pathlib.Path(path).read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    i, idat, hdr = 8, bytearray(), None
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        if typ == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", d[i + 8:i + 8 + ln])
        elif typ == b"IDAT":
            idat += d[i + 8:i + 8 + ln]
        elif typ == b"IEND":
            break
        i += 12 + ln
    if hdr is None:
        return None
    w, h, depth, ctype, _comp, _filt, interlace = hdr
    if depth != 8 or ctype not in (2, 6) or interlace:
        return None
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    pos = 0
    for y in range(h):
        f = raw[pos]
        pos += 1
        line = np.frombuffer(raw[pos:pos + stride], dtype=np.uint8).astype(np.int32)
        pos += stride
        if f == 0:
            cur = line
        elif f == 2:                      # Up: whole row at once
            cur = (line + prev) & 255
        elif f == 1:                      # Sub: a cumulative sum per channel
            cur = line.copy()
            cur = cur.reshape(-1, ch).cumsum(axis=0).reshape(-1) & 255
        else:                             # Average and Paeth are sequential
            cur = np.zeros(stride, dtype=np.int32)
            for xi in range(stride):
                a = cur[xi - ch] if xi >= ch else 0
                b = prev[xi]
                c = prev[xi - ch] if xi >= ch else 0
                v = line[xi]
                if f == 3:
                    v += (a + b) // 2
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    v += a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[xi] = v & 255
        out[y] = cur.astype(np.uint8)
        prev = cur.astype(np.int32)
    img = out.reshape(h, w, ch)
    if ch == 3:                           # no alpha: the whole image is map
        img = np.dstack([img, np.full((h, w), 255, np.uint8)])
    return img


def build() -> dict:
    """Read every radar and store its downsampled mask. Run this once."""
    masks = {}
    for png in sorted(MASK_DIR.glob("*_radar_psd.png")):
        key = png.name.replace("_radar_psd.png", "")
        img = _read_png(png)
        if img is None:
            print(f"  {key}: unsupported PNG, skipped")
            continue
        alpha = img[..., 3]
        h, w = alpha.shape
        # Downsample by "any opaque pixel in the block", so a one-pixel-wide
        # corridor survives instead of being averaged away.
        ys = np.array_split(np.arange(h), MASK_N)
        xs = np.array_split(np.arange(w), MASK_N)
        grid = np.zeros((MASK_N, MASK_N), dtype=bool)
        opaque = alpha > ALPHA_FLOOR
        if (alpha[opaque] < SOLID_FLOOR).mean() > 0.5:
            opaque = alpha >= SOLID_FLOOR
        for r, yy in enumerate(ys):
            band = opaque[yy[0]:yy[-1] + 1, :]
            for c, xx in enumerate(xs):
                grid[r, c] = band[:, xx[0]:xx[-1] + 1].any()
        masks[key] = "".join("1" if v else "0" for v in grid.ravel())
        print(f"  {key}: {100.0 * grid.mean():.1f}% of the square is map")
    MASK_FILE.write_text(json.dumps({"n": MASK_N, "masks": masks}), encoding="utf-8")
    print(f"wrote {MASK_FILE} ({MASK_FILE.stat().st_size / 1024:.0f} KB)")
    return masks


def load(map_name: str, level: str | None = None):
    """The stored mask as (n, n) bool in IMAGE orientation, or None."""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(MASK_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {"n": MASK_N, "masks": {}}
    # radar.py already names the asset for a map and floor; the mask is keyed
    # the same way so Nuke's lower floor gets its own lower-floor image.
    key = RD._asset(map_name, level).replace("_radar_psd", "")
    bits = _CACHE["masks"].get(key) or _CACHE["masks"].get(map_name)
    if not bits:
        return None
    n = _CACHE["n"]
    return np.frombuffer(bits.encode("ascii"), dtype=np.uint8).reshape(n, n) == ord("1")


def sample(map_name, level, x0, x1, y0, y1, bins, radar):
    """The mask resampled onto a picture's own (bins, bins) grid.

    Returned in the same [x, y] orientation the histogram uses, so it can be
    combined with an occupancy grid directly.
    """
    grid = load(map_name, level)
    if grid is None or radar is None:
        return None
    n = grid.shape[0]
    rx0, rx1 = float(radar["x0"]), float(radar["x1"])
    ry0, ry1 = float(radar["y0"]), float(radar["y1"])
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    xs = (np.linspace(x0, x1, bins, endpoint=False) + (x1 - x0) / (2 * bins))
    ys = (np.linspace(y0, y1, bins, endpoint=False) + (y1 - y0) / (2 * bins))
    col = np.clip(((xs - rx0) / (rx1 - rx0) * n).astype(int), 0, n - 1)
    # The image's first row is the TOP of the map, which is the largest y.
    row = np.clip(((ry1 - ys) / (ry1 - ry0) * n).astype(int), 0, n - 1)
    return grid[np.ix_(row, col)].T


if __name__ == "__main__":
    build()
