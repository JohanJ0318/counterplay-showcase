"""Build and read the stored zone model.

    python -m counterplay.zonemodel --build

Zones are clustered once and written down. Everything else — the naming sheet,
the pattern engine, the pictures — reads the stored centres rather than
re-clustering, so a zone number always means the same place and the names keyed
to it stay true.

Rebuilding is deliberate, and it warns when names already exist: more demos
move the clusters, and a name pinned to zone 7 is only correct while zone 7 is
where it was when someone looked at it.
"""
from __future__ import annotations

import pathlib

import numpy as np

from . import zones as Z

def _official_splits() -> dict[str, float]:
    """Floor boundaries as the game itself defines them.

    CS2 ships an overview description per map at `resource/overviews/<map>.txt`,
    and a stacked map declares its floors there:

        "verticalsections" { "default" { "AltitudeMin" "-495" } ... }

    Nuke's boundary is -495. A hand-derived -543, read off the gap in the height
    histogram, landed in the same 200-unit dead space between the floors and so
    sorted every zone identically — but one of the two numbers is a measurement
    and the other is the answer, and there is no reason to prefer the guess.
    Vertigo and Train come along free, before anyone uploads one.

    These are constants — a boundary altitude and a radar origin — not artwork.
    """
    import json
    try:
        raw = json.loads((pathlib.Path(__file__).parent / "overviews.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"de_nuke": -495.0}
    return {m: r["floor_split"] for m, r in raw.items() if "floor_split" in r}


SPLIT_LEVELS = _official_splits()

ZONES_PER_LEVEL = 10        # when a map is split, per floor
ROUNDS_SAMPLED = 400


def _fit(x, y, z, n_zones):
    centres, labels, counts = Z.find_zones(x, y, z, n_zones=n_zones)
    total = counts.sum() or 1
    out = []
    for i, (c, n) in enumerate(zip(centres, counts)):
        pts = np.column_stack([x[labels == i], y[labels == i]])
        d = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) if len(pts) else np.array([0.0])
        out.append({"cx": float(c[0]), "cy": float(c[1]), "cz": float(c[2]),
                    "share": float(n / total), "radius": float(np.percentile(d, 68))})
    return out


def build(map_name: str, rounds_sampled: int = ROUNDS_SAMPLED) -> list[dict]:
    """Cluster one map and return its zones, ready to store."""
    from app import db

    rows = db.query("""SELECT rp.data FROM round_positions rp
                         JOIN matches m ON m.match_key = rp.match_key
                        WHERE m.map_name = ? LIMIT ?""", map_name, rounds_sampled)
    if len(rows) < 20:
        return []
    x, y, z = Z.collect([r["data"] for r in rows])
    if len(x) == 0:
        return []

    split = SPLIT_LEVELS.get(map_name)
    if split is None:
        zones = _fit(x, y, z, Z.DEFAULT_ZONES)
        for zn in zones:
            zn["level"] = None
        return zones

    # Split maps get their own model per floor, numbered upper first.
    zones = []
    for level, sel in (("upper", z >= split), ("lower", z < split)):
        if sel.sum() < ZONES_PER_LEVEL * 20:
            continue
        for zn in _fit(x[sel], y[sel], z[sel], ZONES_PER_LEVEL):
            zn["level"] = level
            zones.append(zn)
    return zones



# Cell size for finding where a zone really is. Small enough that a wall shows
# up as a gap between blobs, large enough that 8 Hz sampling does not shatter a
# corridor into confetti.
ANCHOR_CELL = 40


def label_anchors(map_name: str, rounds_sampled: int = 300) -> dict[int, tuple]:
    """Where each zone's name should be drawn: zone index -> (x, y, z).

    Three things this is not, each of which was tried:

    A CENTROID is the average of a zone's members, and an average is not
    necessarily a place. On Anubis one sat 123 units inside geometry nobody can
    enter.

    THE BUSIEST CELL is where most of a zone's traffic is, which sounds right
    and is not: the busiest ground in a zone is usually the choke where it
    meets the next one, so Nuke's "lobby" came to rest six units from another
    zone's floor and "Hut" three. A name on the border reads as a name pointing
    at the wrong room.

    THE DEEPEST CELL IN THREE DIMENSIONS looks correct and is barely better,
    because the label is drawn on a top-down picture and a zone one cell tall
    is on a vertical boundary immediately. Depth has to be measured the way the
    picture is read.

    So: flatten the zone to the floor plan, take its largest connected area,
    and put the label on the square furthest from any ground belonging to
    another zone. That is where a person pointing at the map would point.
    """
    from collections import deque

    from app import db

    from . import zones as Z

    zs = load(map_name)
    if not zs:
        return {}
    rows = db.query("""SELECT rp.data FROM round_positions rp
                         JOIN matches m ON m.match_key = rp.match_key
                        WHERE m.map_name = ? LIMIT ?""", map_name, rounds_sampled)
    x, y, z = Z.collect([r["data"] for r in rows], thin=3, alive_only=False)
    if len(x) == 0:
        return {}

    C = np.array([[q["cx"], q["cy"], q["cz"]] for q in zs], dtype=np.float64)
    dz = (z[:, None] - C[None, :, 2]) * Z.Z_WEIGHT
    d = (x[:, None] - C[None, :, 0]) ** 2 + (y[:, None] - C[None, :, 1]) ** 2 + dz ** 2
    lab = np.argmin(d, axis=1)

    split = SPLIT_LEVELS.get(map_name)
    NEIGH = ((1, 0), (-1, 0), (0, 1), (0, -1))
    out: dict[int, tuple] = {}

    for i in range(len(zs)):
        # A stacked map is read one floor at a time, so the floor plan is built
        # from that floor only — otherwise Nuke's two levels overlap into one
        # unreadable outline and every label lands on a wall in the other one.
        keep = lab == i
        if split is not None and zs[i]["level"]:
            keep = keep & ((z >= split) if zs[i]["level"] == "upper" else (z < split))
        floor = (z >= split) if (split is not None and zs[i]["level"] == "upper") else (
            (z < split) if split is not None else np.ones(len(z), dtype=bool))
        if keep.sum() < 20:
            out[i + 1] = (zs[i]["cx"], zs[i]["cy"], zs[i]["cz"])
            continue

        def grid(mask):
            k = np.column_stack([x[mask] // ANCHOR_CELL,
                                 y[mask] // ANCHOR_CELL]).astype(np.int64)
            cells, counts = np.unique(k, axis=0, return_counts=True)
            return {tuple(c): int(n) for c, n in zip(cells, counts)}

        mine = grid(keep)
        everyone = grid(floor)
        # Squares this zone holds outright, so a shared doorway counts as the
        # neighbour's and the label is pushed off it.
        owned = {c for c, n in mine.items() if n >= 0.5 * everyone.get(c, n)}
        if len(owned) < 3:
            owned = set(mine)

        seen, best_blob, best_w = set(), None, -1
        for c in owned:
            if c in seen:
                continue
            q, blob, w = deque([c]), [], 0
            seen.add(c)
            while q:
                a = q.popleft()
                blob.append(a)
                w += mine[a]
                for s0, s1 in NEIGH:
                    nb = (a[0] + s0, a[1] + s1)
                    if nb in owned and nb not in seen:
                        seen.add(nb)
                        q.append(nb)
            if w > best_w:
                best_w, best_blob = w, blob
        blob = set(best_blob)

        dist: dict[tuple, int] = {}
        q = deque()
        for c in blob:
            if any((c[0] + s0, c[1] + s1) not in blob for s0, s1 in NEIGH):
                dist[c] = 0
                q.append(c)
        while q:
            a = q.popleft()
            for s0, s1 in NEIGH:
                nb = (a[0] + s0, a[1] + s1)
                if nb in blob and nb not in dist:
                    dist[nb] = dist[a] + 1
                    q.append(nb)

        hot = max(blob, key=lambda c: (dist.get(c, 0), mine[c]))
        col = keep & (x // ANCHOR_CELL == hot[0]) & (y // ANCHOR_CELL == hot[1])
        zz = float(np.median(z[col])) if col.any() else zs[i]["cz"]
        out[i + 1] = (float(hot[0] * ANCHOR_CELL + ANCHOR_CELL / 2),
                      float(hot[1] * ANCHOR_CELL + ANCHOR_CELL / 2), zz)
    return out


def store_anchors(map_name: str) -> int:
    """Work out and save this map's label positions."""
    from app import db

    anchors = label_anchors(map_name)
    for idx, (ax, ay, az) in anchors.items():
        db.execute("""UPDATE map_zones SET label_x=?, label_y=?, label_z=?
                       WHERE map_name=? AND zone_index=?""",
                   ax, ay, az, map_name, idx)
    return len(anchors)


def label_pos(zone: dict) -> tuple:
    """Where to draw this zone's name, falling back to the centroid."""
    if zone.get("label_x") is None:
        return zone["cx"], zone["cy"], zone["cz"]
    return zone["label_x"], zone["label_y"], zone["label_z"]



# Grid for testing whether a zone is one place or two. Thirty-two units is
# about two feet: fine enough that a thin wall shows as a gap between blobs,
# and the emptiness test below is what stops sparse sampling being mistaken
# for one.
SPLIT_CELL = 32

# A second piece has to be at least this share of a zone to be worth its own
# name, and the straight line between the two pieces has to be at least this
# empty before the gap counts as geometry rather than as a quiet corridor.
SPLIT_MIN_SHARE = 0.10
SPLIT_MIN_EMPTY = 0.40


def _blobs(x, y, z, cell=SPLIT_CELL):
    """Connected groups of occupied cells, largest first.

    Returns [(weight, [cells...]), ...] where weight is how many samples the
    group holds.
    """
    from collections import deque

    keys = np.column_stack([x // cell, y // cell, z // cell]).astype(np.int64)
    cells, counts = np.unique(keys, axis=0, return_counts=True)
    occ = {tuple(c): int(n) for c, n in zip(cells, counts)}
    seen, out = set(), []
    for c in occ:
        if c in seen:
            continue
        q, members, total = deque([c]), [], 0
        seen.add(c)
        while q:
            a = q.popleft()
            members.append(a)
            total += occ[a]
            for step in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                         (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nb = (a[0] + step[0], a[1] + step[1], a[2] + step[2])
                if nb in occ and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        out.append((total, members))
    out.sort(key=lambda t: -t[0])
    return out


def find_split_zones(map_name: str, only: list[int] | None = None) -> list[dict]:
    """Zones that are really two places with a wall between them.

    Clustering works on coordinates and knows nothing about walls, so a zone
    can cover ground on both sides of one. "Three of you are in Apps" is then
    a sentence about two different rooms.

    Two tests, and the second is the one that matters. First, does the zone
    break into separate blobs on a fine grid — a thin wall only shows at fine
    resolution, so a coarse grid would merge the very cases worth finding.
    Second, and this is what tells a wall from a thinly-sampled corridor: walk
    the straight line between the two pieces and ask whether ANYONE, in any
    round on this map, has ever stood along it. If nobody has, there is
    something solid in the way.
    """
    from app import db

    from . import zones as Z

    zs = load(map_name)
    if not zs:
        return []
    rows = db.query("""SELECT rp.data FROM round_positions rp
                         JOIN matches m ON m.match_key = rp.match_key
                        WHERE m.map_name = ?""", map_name)
    x, y, z = Z.collect([r["data"] for r in rows], thin=2, alive_only=False)
    if len(x) == 0:
        return []

    everywhere = set(map(tuple, np.column_stack(
        [x // SPLIT_CELL, y // SPLIT_CELL, z // SPLIT_CELL]).astype(np.int64)))

    C = np.array([[q["cx"], q["cy"], q["cz"]] for q in zs], dtype=np.float64)
    dz = (z[:, None] - C[None, :, 2]) * Z.Z_WEIGHT
    lab = np.argmin((x[:, None] - C[None, :, 0]) ** 2
                    + (y[:, None] - C[None, :, 1]) ** 2 + dz ** 2, axis=1)

    names = globals()["names"](map_name)
    # `only` names the zones a person has asked for. Someone who knows the map
    # beats a heuristic run over sparse samples: on Cache the emptiness test
    # said the two pieces were connected and the person who plays there said a
    # wall runs between them. When a zone is asked for by hand the tests still
    # have to find two pieces, but the emptiness threshold is not applied.
    asked = set(only or [])
    out = []
    for i in range(len(zs)):
        nm = names.get(i + 1, "")
        if only is not None and (i + 1) not in asked:
            continue
        # Spawn zones split constantly — two rows of spawn points — and never
        # appear in a pattern, so splitting them is work for nobody.
        if not asked and "spawn" in nm.lower():
            continue
        m = lab == i
        if m.sum() < 800:
            continue
        bl = _blobs(x[m], y[m], z[m])
        if len(bl) < 2:
            continue
        total = sum(b[0] for b in bl)
        if bl[1][0] / total < SPLIT_MIN_SHARE:
            continue
        a = np.array(bl[0][1], dtype=float).mean(0)
        b = np.array(bl[1][1], dtype=float).mean(0)
        steps = np.linspace(0, 1, 40)
        empty = sum(1 for t in steps if tuple(
            np.round(a + t * (b - a)).astype(np.int64)) not in everywhere)
        if empty / len(steps) < SPLIT_MIN_EMPTY and (i + 1) not in asked:
            continue
        out.append({"zone": i + 1, "name": nm or "(unnamed)",
                    "share": bl[1][0] / total, "empty": empty / len(steps),
                    "cells_a": bl[0][1], "cells_b": bl[1][1]})
    return out


def split_zones(map_name: str, only: list[int] | None = None) -> list[dict]:
    """Give each wall-separated piece its own zone. Names are preserved.

    The larger piece keeps the zone's index, and therefore its name — it is
    the part the name was written about. Each separated piece is appended as a
    NEW zone at the end of the numbering, so every existing name still points
    exactly where it did and only the new pieces need naming.

    Returns what was added, for the caller to report.
    """
    from app import db

    from . import zones as Z

    found = find_split_zones(map_name, only=only)
    if not found:
        return []

    zs = load(map_name)
    rows = db.query("""SELECT rp.data FROM round_positions rp
                         JOIN matches m ON m.match_key = rp.match_key
                        WHERE m.map_name = ?""", map_name)
    x, y, z = Z.collect([r["data"] for r in rows], thin=2, alive_only=False)
    total_samples = len(x)
    split = SPLIT_LEVELS.get(map_name)
    added = []
    next_index = len(zs) + 1

    for f in found:
        cells_a = set(map(tuple, f["cells_a"]))
        cells_b = set(map(tuple, f["cells_b"]))
        keys = np.column_stack([x // SPLIT_CELL, y // SPLIT_CELL,
                                z // SPLIT_CELL]).astype(np.int64)
        in_a = np.array([tuple(k) in cells_a for k in keys])
        in_b = np.array([tuple(k) in cells_b for k in keys])
        if in_a.sum() < 50 or in_b.sum() < 50:
            continue

        def describe(mask):
            return (float(x[mask].mean()), float(y[mask].mean()),
                    float(z[mask].mean()), float(mask.sum()) / max(total_samples, 1))

        ax, ay, az, ashare = describe(in_a)
        bx, by, bz, bshare = describe(in_b)

        # The larger piece keeps the index and the name.
        db.execute("""UPDATE map_zones SET cx=?, cy=?, cz=?, share=?
                       WHERE map_name=? AND zone_index=?""",
                   ax, ay, az, ashare, map_name, f["zone"])

        level = None
        if split is not None:
            level = "upper" if bz >= split else "lower"
        db.execute("""INSERT INTO map_zones (map_name, zone_index, cx, cy, cz,
                                             share, radius, level, built_at)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   map_name, next_index, bx, by, bz, bshare,
                   float(np.percentile(np.hypot(x[in_b] - bx, y[in_b] - by), 68)),
                   level, db.utcnow())
        added.append({"new_index": next_index, "from_zone": f["zone"],
                      "from_name": f["name"], "share": bshare,
                      "empty": f["empty"]})
        next_index += 1

    if added:
        store_anchors(map_name)
    return added


def store(map_name: str, zones: list[dict]) -> int:
    from app import db

    db.execute("DELETE FROM map_zones WHERE map_name = ?", map_name)
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO map_zones (map_name, zone_index, cx, cy, cz, share,
                                      radius, level, built_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(map_name, i + 1, z["cx"], z["cy"], z["cz"], z["share"],
              z["radius"], z["level"], db.utcnow())
             for i, z in enumerate(zones)])
        conn.commit()
    return len(zones)


def load(map_name: str) -> list[dict]:
    """The stored zones for a map, in index order. [] if never built."""
    from app import db
    return [dict(r) for r in db.query(
        "SELECT * FROM map_zones WHERE map_name = ? ORDER BY zone_index", map_name)]


def names(map_name: str) -> dict[int, str]:
    from app import db
    return {r["zone_index"]: r["name"] for r in db.query(
        "SELECT zone_index, name FROM zone_names WHERE map_name = ?", map_name)}


def zone_of(map_name: str, x, y, z=None, max_distance: float = 900.0):
    """Which stored zone a position falls in. None if it is nowhere near one.

    Nearest centre, with height counted the same way the clustering counted it,
    so a position in Nuke's lower level cannot be assigned to an upper zone
    directly above it.
    """
    zs = load(map_name)
    if not zs:
        return None
    cx = np.array([q["cx"] for q in zs]); cy = np.array([q["cy"] for q in zs])
    cz = np.array([q["cz"] for q in zs])
    dx, dy = np.asarray(x) - cx[:, None], np.asarray(y) - cy[:, None]
    if z is None:
        d = np.hypot(dx, dy)
    else:
        dz = (np.asarray(z) - cz[:, None]) * Z.Z_WEIGHT
        d = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    best = np.argmin(d, axis=0)
    far = d[best, np.arange(d.shape[1])] > max_distance
    out = best + 1
    return np.where(far, 0, out)


def main() -> int:
    import argparse
    from app import db

    ap = argparse.ArgumentParser(description="Build the stored zone model")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--map", action="append", default=[])
    ap.add_argument("--force", action="store_true",
                    help="rebuild even where names already exist")
    ap.add_argument("--split", action="store_true",
                    help="give each wall-separated piece of a zone its own "
                         "number, keeping every existing name")
    args = ap.parse_args()
    db.init()

    maps = args.map or [r["map_name"] for r in db.query(
        "SELECT map_name, COUNT(*) n FROM rounds GROUP BY map_name ORDER BY n DESC")]

    if args.split:
        total = 0
        for mp in maps:
            added = split_zones(mp)
            total += len(added)
            for a in added:
                print(f"  {mp.replace('de_', ''):<9} zone {a['new_index']:>2} split "
                      f"off {a['from_name']} (zone {a['from_zone']}) — "
                      f"{100*a['share']:.1f}% of the map, "
                      f"{100*a['empty']:.0f}% of the way between them is solid")
            if not added:
                print(f"  {mp.replace('de_', ''):<9} nothing to split")
        print(f"\n{total} new zones. Every existing name still points where it did; "
              f"only the new ones need naming.")
        return 0

    if not args.build:
        print(f"{'map':<12}{'zones':>7}{'named':>7}  built")
        for mp in maps:
            zs = load(mp)
            print(f"{mp.replace('de_',''):<12}{len(zs):>7}{len(names(mp)):>7}"
                  f"  {zs[0]['built_at'][:16] if zs else 'never'}")
        return 0

    for mp in maps:
        have_names = len(names(mp))
        if have_names and not args.force:
            print(f"  {mp.replace('de_',''):<12} SKIPPED — {have_names} names already "
                  f"point at the current zones. --force to rebuild and re-check them.")
            continue
        zones = build(mp)
        if not zones:
            print(f"  {mp.replace('de_',''):<12} not enough data")
            continue
        n = store(mp, zones)
        lv = {z["level"] for z in zones if z["level"]}
        print(f"  {mp.replace('de_',''):<12} {n} zones"
              + (f" across {len(lv)} floors" if lv else ""))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
