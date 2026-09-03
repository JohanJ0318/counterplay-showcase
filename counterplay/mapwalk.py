"""Map geometry from a walk-through demo.

    python -m counterplay.mapwalk path\\to\\walk.dem

THE PROBLEM
-----------
Every picture this product draws of a map is drawn from where players actually
stood. That is the right way to find the busy areas — it is how the zones were
found — but it is the wrong way to draw the map itself, because a corner nobody
walked through comes out blank and the map looks like it has a hole in it. The
map is still there. Nobody has stood in it yet.

More matches help and they do not fix it: after 475 rounds of Mirage the
picture still misses the far edges of spawn, the back of apartments, the parts
of the map that exist and are simply never contested.

THE FIX
-------
One person flies through the map once, with the demo recording, and the
recording contains a position for everywhere they went. That is the map.

    In CS2:  map de_mirage
             sv_cheats 1 ; noclip
             record mirage_walk
             ... fly everywhere, including the corners nobody plays ...
             stop

Then hand the file to this. One demo per map, once, and every drawing of that
map is complete from then on.

WHY A SEPARATE PATH
-------------------
A walk-through is not a match: no rounds, no freeze-ends, no teams. `parse.py`
correctly refuses it — a demo with no round boundaries is normally a broken
recording, and loosening that check to admit this would let real broken demos
through. So this reads ticks directly and never touches the match pipeline.

WHAT IS STORED
--------------
Not the raw samples. A flight covers millions of ticks and the drawing only
ever asks "is there map here", so what is kept is the set of occupied cells on
a CELL-unit grid: two int16 per cell, a few hundred KB for a whole map, and
exactly the question the renderer asks.
"""
from __future__ import annotations

import pathlib
import struct

import numpy as np

# Grid resolution in world units. CS2 units are roughly an inch, so 16 is about
# a foot and a quarter — finer than any line the drawing can render, and coarse
# enough that a whole map is a few hundred kilobytes.
CELL = 16

# Every Nth tick. A player flying at noclip speed covers ~320 units a second,
# so 8 Hz leaves a 40-unit gap between samples — under three cells, which the
# renderer's own binning closes.
SAMPLE_STEP = 8

HEADER = struct.Struct("<BHI")      # version, cell size, point count
VERSION = 1


def pack(x, y, z) -> bytes:
    """Occupied cells, deduplicated, as packed int16 triples."""
    gx = np.floor_divide(np.asarray(x, dtype=np.int32), CELL).astype(np.int16)
    gy = np.floor_divide(np.asarray(y, dtype=np.int32), CELL).astype(np.int16)
    gz = np.floor_divide(np.asarray(z, dtype=np.int32), CELL).astype(np.int16)
    cells = np.unique(np.column_stack([gx, gy, gz]), axis=0)
    return HEADER.pack(VERSION, CELL, len(cells)) + cells.astype("<i2").tobytes()


def unpack(blob: bytes):
    """(x, y, z) world coordinates at cell centres, or None."""
    if not blob or len(blob) < HEADER.size:
        return None
    version, cell, n = HEADER.unpack_from(blob, 0)
    if version != VERSION:
        raise ValueError(f"map geometry version {version}, expected {VERSION}")
    a = np.frombuffer(blob, dtype="<i2", count=n * 3,
                      offset=HEADER.size).reshape(n, 3).astype(np.int32)
    return (a[:, 0] * cell, a[:, 1] * cell, a[:, 2] * cell)


def extract(path: str, sample_step: int = SAMPLE_STEP):
    """(map_name, x, y, z) from a walk-through demo."""
    from demoparser2 import DemoParser

    parser = DemoParser(str(path))
    map_name = parser.parse_header().get("map_name", "unknown")

    frame = parser.parse_ticks(["X", "Y", "Z"])
    if not hasattr(frame, "columns") or "X" not in frame.columns:
        raise ValueError("no position data in this demo")

    # Thin by tick rather than by row: every player on the server contributes,
    # which is a bonus if someone recorded a walk with friends along.
    if "tick" in frame.columns and sample_step > 1:
        frame = frame[frame["tick"] % sample_step == 0]

    x = frame["X"].to_numpy()
    y = frame["Y"].to_numpy()
    z = frame["Z"].to_numpy()
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    return map_name, x[keep], y[keep], z[keep]


def store(map_name: str, x, y, z, source: str = "") -> int:
    """Merge a walk into whatever geometry a map already has.

    Merging rather than replacing means several shorter walks add up, which is
    how anyone actually does this: fly A site, realise you missed B, fly again.
    """
    from app import db

    row = db.one("SELECT cells FROM map_geometry WHERE map_name = ?", map_name)
    if row is not None:
        old = unpack(row["cells"])
        if old is not None:
            x = np.concatenate([np.asarray(x, dtype=np.int32), old[0]])
            y = np.concatenate([np.asarray(y, dtype=np.int32), old[1]])
            z = np.concatenate([np.asarray(z, dtype=np.int32), old[2]])

    blob = pack(x, y, z)
    n = HEADER.unpack_from(blob, 0)[2]
    db.execute("""INSERT INTO map_geometry (map_name, cells, n_cells, source, built_at)
                  VALUES (?,?,?,?,?)
                  ON CONFLICT(map_name) DO UPDATE SET
                      cells = excluded.cells, n_cells = excluded.n_cells,
                      source = excluded.source, built_at = excluded.built_at""",
               map_name, blob, n, source, db.utcnow())
    return n


def load(map_name: str):
    """(x, y, z) of this map's known geometry, or None if none was imported."""
    from app import db

    row = db.one("SELECT cells FROM map_geometry WHERE map_name = ?", map_name)
    return unpack(row["cells"]) if row else None


def main() -> int:
    import argparse

    from app import db

    ap = argparse.ArgumentParser(
        description="Import map geometry from a walk-through demo")
    ap.add_argument("demo", nargs="*", help="one or more .dem files")
    ap.add_argument("--list", action="store_true", help="what is already stored")
    args = ap.parse_args()
    db.init()

    if args.list or not args.demo:
        rows = db.query("""SELECT map_name, n_cells, source, built_at
                             FROM map_geometry ORDER BY map_name""")
        if not rows:
            print("No map geometry imported yet.\n")
            print("  In CS2:  map de_mirage")
            print("           sv_cheats 1 ; noclip")
            print("           record mirage_walk")
            print("           ...fly everywhere, including where nobody plays...")
            print("           stop")
            print("\nThe file lands in your csgo folder. Then:")
            print("  python -m counterplay.mapwalk mirage_walk.dem")
            return 0
        print(f"{'map':<12}{'cells':>9}  imported")
        for r in rows:
            print(f"{r['map_name'].replace('de_', ''):<12}{r['n_cells']:>9}  "
                  f"{r['built_at'][:16]}")
        return 0

    for path in args.demo:
        f = pathlib.Path(path)
        if not f.exists():
            print(f"  {f.name}: not found")
            continue
        try:
            map_name, x, y, z = extract(str(f))
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            # BaseException because demoparser2 is Rust: a malformed file
            # raises a PanicException, which does not inherit from Exception
            # and would otherwise take the whole import down. One bad file
            # should not stop the other six maps being read.
            print(f"  {f.name}: {type(exc).__name__}: {exc}")
            continue
        if len(x) == 0:
            print(f"  {f.name}: no positions in it")
            continue
        n = store(map_name, x, y, z, source=f.name)
        print(f"  {f.name}: {map_name} — {len(x):,} samples → {n:,} cells")
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
