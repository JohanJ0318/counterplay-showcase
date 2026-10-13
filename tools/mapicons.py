"""Build one small purple silhouette per map, for the map chips.

    python tools/mapicons.py

WHY NOT THE RADAR PNG, WHICH WAS ALREADY THERE
----------------------------------------------
`map_chip` drew Valve's radar image inside a 20px circle. Three things wrong
with that. At twenty pixels a full radar is a grey smudge, legible as "a map"
and never as "which map". It is the only full-colour artwork on a site whose
whole palette is one purple, so every chip reads as a foreign object in the
row it sits in. And it is Valve's asset, shipped as decoration.

Shape is the only thing that survives twenty pixels, and shape is exactly what
tells mirage from nuke.

HOW
---
`radarmask` already stores what is wanted: a 256x256 boolean of Valve's alpha
channel, which is the map's own outline, built once and committed.

Three passes turn that into something readable at chip size, and all three are
needed. Downsampling alone gave speckle: the alpha channel is full of interior
holes for roofs and walls, and at 20px a shape with holes in it reads as
noise rather than as a map.

    1. shrink        256 -> 56, keeping a cell a third full, because a
                     majority vote erases the corridors that make a map
                     recognisable
    2. largest piece only, which on nuke removes the scattered fragments
                     outside the building that stretched its bounding box into
                     a thin smear
    3. fill speckle  interior gaps up to ten cells are artefacts of Valve's
                     alpha and get filled; anything larger is a courtyard or
                     an open middle and stays, because those are the features
                     that tell one map from another

Then it is cropped to its own bounding box, because an icon of mostly empty
square is the problem this is here to solve.

THE GRID IS SIZED FOR THE CHIP, NOT FOR THE PRETTIEST PICTURE. 112 cells
crops to about 99 across, and a chip is 22 pixels wide: five and a half cells
of detail averaged into every pixel, which the renderer resolves as grey mush.
It looked superb at 64px and blurry everywhere it is actually used. 56 crops
to about 49, so roughly two cells a pixel, which holds an edge.

No `shape-rendering="crispEdges"` either. Snapping edges to the pixel grid is
right when a drawing is shown at its own size and wrong when it is scaled to
an arbitrary one: at two cells a pixel it drops some rows and doubles others,
and the unevenness reads as noise. Ordinary antialiasing is what a downscaled
shape wants.

Written as runs of rects rather than one per cell: a row is a handful of
spans. Files land at 2 to 5KB, which is why these are generated to disk and
masked in rather than inlined into every chip on a page.

The fill is `currentColor`, so a chip takes the colour of the text around it
and one file serves light and dark.

de_overpass and de_train have no stored mask and are skipped; `map_chip` keeps
its old behaviour for any map without an icon.
"""
from __future__ import annotations

import pathlib
from collections import deque

import numpy as np

import pathlib as _pl
import sys as _sys
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from counterplay import radarmask as RM

OUT = pathlib.Path(__file__).resolve().parent.parent / "site" / "icons" / "maps"
GRID = 56          # cells across before cropping
HOLE_MAX = 10      # interior gaps up to this many cells are speckle
MAPS = ["de_ancient", "de_anubis", "de_cache", "de_dust2", "de_inferno",
        "de_mirage", "de_nuke", "de_overpass", "de_train"]


def shrink(mask: np.ndarray, n: int) -> np.ndarray:
    """256 -> n by block mean, kept where a block is a third full."""
    side = mask.shape[0] // n
    blocks = mask[:n * side, :n * side].reshape(n, side, n, side)
    return blocks.mean(axis=(1, 3)) >= 0.33


def _flood(seed_edge: np.ndarray, passable: np.ndarray) -> np.ndarray:
    """Cells reachable from the seeded border, moving only through `passable`."""
    h, w = passable.shape
    seen = np.zeros_like(passable)
    q: deque = deque()
    for y, x in zip(*np.where(seed_edge & passable)):
        seen[y, x] = True
        q.append((int(y), int(x)))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and passable[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def largest_piece(grid: np.ndarray) -> np.ndarray:
    """Only the biggest connected blob. Nuke ships fragments off to one side."""
    h, w = grid.shape
    seen = np.zeros_like(grid)
    best = np.zeros_like(grid)
    for sy, sx in zip(*np.where(grid)):
        if seen[sy, sx]:
            continue
        piece = np.zeros_like(grid)
        q = deque([(int(sy), int(sx))])
        seen[sy, sx] = piece[sy, sx] = True
        while q:
            y, x = q.popleft()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = piece[ny, nx] = True
                    q.append((ny, nx))
        if piece.sum() > best.sum():
            best = piece
    return best


def fill_holes(grid: np.ndarray, hole_max: int) -> np.ndarray:
    """Fill the speckle and keep the rooms.

    Filling every interior gap gave a solid blob that read cleanly at 20px and
    told you nothing at 64: mirage and ancient became the same rounded lump.
    Keeping every gap gave the original noise, because Valve's alpha is
    peppered with one and two cell holes for walls and railings.

    So the holes are measured. Anything up to `hole_max` cells is a rendering
    artefact and gets filled; anything larger is a courtyard, a pit or an open
    middle, and those are exactly the features that tell one map from another.
    """
    h, w = grid.shape
    edge = np.zeros_like(grid)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    outside = _flood(edge, ~grid)
    out = grid.copy()
    seen = outside.copy()
    for sy, sx in zip(*np.where(~grid & ~seen)):
        if seen[sy, sx]:
            continue
        cells = []
        q = deque([(int(sy), int(sx))])
        seen[sy, sx] = True
        while q:
            y, x = q.popleft()
            cells.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if (0 <= ny < h and 0 <= nx < w and not grid[ny, nx]
                        and not seen[ny, nx]):
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(cells) <= hole_max:
            for y, x in cells:
                out[y, x] = True
    return out


def runs(grid: np.ndarray) -> str:
    """Each row as spans of set cells, one rect per span."""
    out = []
    for y in range(grid.shape[0]):
        row, x = grid[y], 0
        while x < len(row):
            if not row[x]:
                x += 1
                continue
            start = x
            while x < len(row) and row[x]:
                x += 1
            out.append(f'<rect x="{start}" y="{y}" width="{x - start}" height="1"/>')
    return "".join(out)


def build_one(map_name: str) -> str | None:
    mask = RM.load(map_name)
    if mask is None or not mask.any():
        return None
    grid = fill_holes(largest_piece(shrink(mask, GRID)), HOLE_MAX)
    if not grid.any():
        return None
    ys, xs = np.where(grid)
    grid = grid[int(ys.min()):int(ys.max()) + 1,
                int(xs.min()):int(xs.max()) + 1]
    h, w = grid.shape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'fill="currentColor">'
            f'{runs(grid)}</svg>')


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for m in MAPS:
        svg = build_one(m)
        if svg is None:
            print(f"  {m}: no mask, skipped")
            continue
        (OUT / f"{m}.svg").write_text(svg, encoding="utf-8")
        print(f"  {m}: {len(svg):,} bytes")
        made.append(m)
    print(f"{len(made)} icons -> {OUT}")
    print("ICON_FOR =", sorted(made))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
