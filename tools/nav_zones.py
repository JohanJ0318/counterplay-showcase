"""Map zones from Valve's own navigation mesh, named by the game's callouts.

    python tools/nav_zones.py de_mirage          # one map
    python tools/nav_zones.py all                # every map in the corpus

For each map:
  1. reads maps/<map>.nav out of the CS2 install's <map>.vpk (VPK v2), and
     its areas with counterplay/navmesh.py: Valve's convex, straight-edged
     polygons, the shapes the game's callouts are made of;
  2. names every area by the callout (last_place_name) most players standing
     in it carried, from N_DEMOS college demos of that map;
  3. gives an area nobody stood in the name of the nearest named area at a
     similar height, so the map has no holes;
  4. straightens every border between two callouts into one line per
     doorway and re-sides the pixels along it;
  5. writes, in counterplay/navzones/:
       <map>.json       each area's polygon and name, and each callout's
                        samples by side (--redraw reuses these, no demos read)
       <map>.grid.npz   the counting lookup (counterplay/callouts.py)
       <map>.draw.json  the outlines, borders and labels the site draws
     and a review picture, data/view/navzones_<map>[_floor].png.

    python tools/nav_zones.py all --redraw       # redraw from stored names

Successor to the square-grid prototype tools/callout_zones.py, whose
borders stepped wherever a 48-unit square crossed an edge (Johan,
2026-10-22: "prototype is better but needs EXTREME fine tuning").
"""
from __future__ import annotations

import colorsys
import io
import json
import re
import struct
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import zstandard
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, ingest  # noqa: E402
from counterplay import navmesh, radar  # noqa: E402

CS2_MAPS = Path(r"C:\Program Files (x86)\Steam\steamapps\common"
                r"\Counter-Strike Global Offensive\game\csgo\maps")
OUT_JSON = ROOT / "counterplay" / "navzones"
OUT_PNG = ROOT / "data" / "view"
N_DEMOS = 10
BUCKET = 128.0          # spatial index cell, world units
Z_SLACK = 72.0          # a position stands on an area within this height
SURE_VOTES = 8          # an area named from fewer samples defers to its neighbours
SMOOTH_PASSES = 3
SIZE = 1024             # radar pixels
STRAIGHT_PX = 6.0       # a border may bend only where it strays this far
BAND_PX = 8.0           # pixels either side of a border re-sided to match it
GAP_PX = 14.0           # border points further apart belong to separate doorways
FILL_ALPHA = 125
GRID_LAYERS = 8         # stacked surfaces one radar pixel can hold (Nuke uses 6+)
SAME_SURFACE = 40.0     # two areas this close in height at a pixel are one surface
EDGE_PX = 6             # ground this near the mesh (a wall's inset) takes its surface
TRACE_TOL = 1.2         # an outline may bend only where it strays this far, pixels


def nav_bytes(map_name: str) -> bytes:
    """maps/<map>.nav out of the map's VPK v2 pack."""
    pak = CS2_MAPS / f"{map_name}.vpk"
    raw = pak.read_bytes()
    sig, ver, tree_size = struct.unpack_from("<III", raw, 0)
    if sig != 0x55AA1234:
        raise ValueError(f"{pak.name} is not a VPK")
    header = 12 + (16 if ver == 2 else 0)
    tree = raw[header:header + tree_size]
    pos = 0

    def cstr():
        nonlocal pos
        end = tree.index(b"\0", pos)
        s = tree[pos:end].decode("utf-8", "replace")
        pos = end + 1
        return s

    while (ext := cstr()):
        while (d := cstr()):
            while (name := cstr()):
                _crc, preload, arch, off, length, _t = struct.unpack_from("<IHHIIH", tree, pos)
                pos += 18
                pre = tree[pos:pos + preload]
                pos += preload
                if ext == "nav" and name == map_name:
                    start = header + tree_size + off if arch == 0x7FFF else off
                    return pre + raw[start:start + length]
    raise FileNotFoundError(f"no nav in {pak.name}")


class Index:
    """Which area a position stands on: the polygon containing it in XY whose
    height is closest, within Z_SLACK."""

    def __init__(self, areas):
        self.areas = areas
        self.grid = defaultdict(list)
        for i, a in enumerate(areas):
            xs = [c[0] for c in a.corners]
            ys = [c[1] for c in a.corners]
            for gx in range(int(min(xs) // BUCKET), int(max(xs) // BUCKET) + 1):
                for gy in range(int(min(ys) // BUCKET), int(max(ys) // BUCKET) + 1):
                    self.grid[(gx, gy)].append(i)

    def find(self, x, y, z):
        best, best_dz = None, Z_SLACK
        for i in self.grid.get((int(x // BUCKET), int(y // BUCKET)), ()):
            a = self.areas[i]
            if a.contains(x, y):
                dz = abs(z - a.centre()[2])
                if dz < best_dz:
                    best, best_dz = i, dz
        return best


def callout_votes(map_name: str, index: Index) -> dict:
    db.init()
    rows = db.query("""SELECT d.source_url FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
                        WHERE m.tier = 'league' AND m.map_name = ?""", map_name)
    votes = defaultdict(Counter)
    sides = defaultdict(Counter)        # callout -> samples by team (2 T, 3 CT)
    used = 0
    from demoparser2 import DemoParser
    for r in rows:
        if used >= N_DEMOS:
            break
        if not (r["source_url"] or "").startswith("file://"):
            continue
        path = Path(ingest.url2path(r["source_url"]))
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if raw[:4] == b"\x28\xb5\x2f\xfd":
            raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
        tmp = Path(tempfile.gettempdir()) / "navzones.dem"
        tmp.write_bytes(raw)
        df = DemoParser(str(tmp)).parse_ticks(["X", "Y", "Z", "last_place_name", "is_alive",
                                               "team_num"],
                                              ticks=list(range(2000, 200000, 16)))
        tmp.unlink()
        df = df[df.is_alive & df.last_place_name.fillna("").ne("")]
        for x, y, z, p, t in zip(df.X, df.Y, df.Z, df.last_place_name, df.team_num):
            sides[p][int(t)] += 1
            i = index.find(x, y, z)
            if i is not None:
                votes[i][p] += 1
        used += 1
    print(f"  {used} demos read", flush=True)
    return votes, sides


def neighbours(areas, index) -> list:
    """For each area, the areas just across its edges (probed a few units
    outside each edge's midpoint, at the edge's height)."""
    out = []
    for i, a in enumerate(areas):
        cx, cy, _ = a.centre()
        found = set()
        cs = a.corners
        for k in range(len(cs)):
            p, q = cs[k], cs[(k + 1) % len(cs)]
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            ox, oy = mx - cx, my - cy
            n = (ox * ox + oy * oy) ** 0.5 or 1.0
            j = index.find(mx + 6 * ox / n, my + 6 * oy / n, (p[2] + q[2]) / 2)
            if j is not None and j != i:
                found.add(j)
        out.append(found)
    return out


def smooth(names, votes, nbrs) -> list:
    """An area named from fewer than SURE_VOTES samples takes the callout most
    of its neighbours have: near a boundary a handful of samples flip
    triangle by triangle, which drew zigzag borders on Anubis (2026-10-22).
    Areas with enough samples keep their own name."""
    names = list(names)
    for _ in range(SMOOTH_PASSES):
        new = list(names)
        for i, n in enumerate(names):
            if sum(votes.get(i, Counter()).values()) >= SURE_VOTES or not nbrs[i]:
                continue
            c = Counter(names[j] for j in nbrs[i])
            top, k = c.most_common(1)[0]
            if top != n and k > len(nbrs[i]) / 2:
                new[i] = top
        names = new
    return names


def name_areas(areas, votes) -> list:
    names = [votes[i].most_common(1)[0][0] if votes.get(i) else None
             for i in range(len(areas))]
    named = [i for i, n in enumerate(names) if n]
    if not named:
        return names
    cen = np.array([areas[i].centre() for i in range(len(areas))])
    ncen = cen[named]
    for i, n in enumerate(names):
        if n is None:
            d = np.linalg.norm((ncen - cen[i]) * np.array([1, 1, 3]), axis=1)
            names[i] = names[named[int(np.argmin(d))]]
    return names


def pretty(name: str) -> str:
    """The game's place name as a person writes it: 'TopofMid' -> 'Top of Mid',
    'CTSpawn' -> 'CT Spawn', 'BombsiteA' -> 'A Site'."""
    if name in PRETTY:
        return PRETTY[name]
    # "of" only when a capital follows it: TopofMid, never Roof.
    s = re.sub(r"(?<=[a-z])of(?=[A-Z])", " of ", name)
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


PRETTY = {"BombsiteA": "A Site", "BombsiteB": "B Site", "TopofMid": "Top of Mid",
          "BackofB": "Back of B", "TopofStairs": "Top of Stairs"}


def scheme(callouts, sides) -> dict:
    """Colours that carry meaning: the two bombsites fixed (A gold, B red),
    ground the Ts mostly stand on warm, CT ground cool, contested ground
    neutral. Inside a group hues are spread and lightness alternates, so
    neighbours of the same group still differ."""
    groups = {"t": [], "ct": [], "mid": []}
    fixed = {"BombsiteA": (226, 168, 48), "BombsiteB": (214, 72, 72)}
    for n in callouts:
        if n in fixed:
            continue
        c = sides.get(n, {})
        t, ct = c.get(2, 0), c.get(3, 0)
        share = t / (t + ct) if t + ct else 0.5
        groups["t" if share > 0.65 else "ct" if share < 0.35 else "mid"].append(n)
    ranges = {"t": (12, 48), "ct": (190, 250), "mid": (85, 165)}
    out = dict((k, v) for k, v in fixed.items() if k in callouts)
    for g, names in groups.items():
        lo, hi = ranges[g]
        for k, n in enumerate(sorted(names)):
            hue = lo + (hi - lo) * (k / max(1, len(names) - 1))
            light = 0.62 if k % 2 == 0 else 0.48
            r, gg, b = colorsys.hls_to_rgb(hue / 360, light, 0.55)
            out[n] = (int(r * 255), int(gg * 255), int(b * 255))
    return out


def _rdp(pts, tol):
    """Ramer-Douglas-Peucker: the fewest straight segments within tol."""
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    n = np.hypot(*ab) or 1.0
    d = [abs(ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])) / n for p in pts[1:-1]]
    k = int(np.argmax(d)) + 1
    if d[k - 1] <= tol:
        return [pts[0], pts[-1]]
    return _rdp(pts[:k + 1], tol)[:-1] + _rdp(pts[k:], tol)


def _chains(segments):
    """Join segments sharing endpoints into polylines."""
    key = lambda p: (round(p[0], 1), round(p[1], 1))
    adj = defaultdict(list)
    for s in segments:
        adj[key(s[0])].append(s)
        adj[key(s[1])].append(s)
    used = set()
    out = []
    for s in segments:
        if id(s) in used:
            continue
        used.add(id(s))
        line = [s[0], s[1]]
        for end in (1, 0):
            while True:
                tip = line[-1] if end else line[0]
                nxt = next((t for t in adj[key(tip)] if id(t) not in used), None)
                if nxt is None:
                    break
                used.add(id(nxt))
                far = nxt[1] if key(nxt[0]) == key(tip) else nxt[0]
                if end:
                    line.append(far)
                else:
                    line.insert(0, far)
        out.append(line)
    return out


def _borders(segs):
    """One clean line per doorway between two callouts, from border points.

    Joining Valve's edges end to end left fragments wherever triangles met
    at a T, and each fragment straightened on its own drew V and Z shapes
    (Anubis, 2026-10-22). Instead every edge point of the pair is gathered,
    split into separate borders where they lie apart (two doors between the
    same two places), ordered along each one's main direction and reduced
    to the fewest straight segments within STRAIGHT_PX."""
    from sklearn.cluster import DBSCAN
    pts = np.array(segs, dtype=float)
    if len(pts) < 2:
        return []
    groups = DBSCAN(eps=GAP_PX, min_samples=1).fit_predict(pts)
    out = []
    for g in set(groups):
        q = np.unique(np.round(pts[groups == g], 1), axis=0)
        if len(q) < 2:
            continue
        # One vertical or horizontal line per doorway (Johan, 2026-10-23:
        # "splitting map zones by vertical and horizontal lines"), whichever
        # the doorway's points run closer to, at their median across it.
        # A best-fit line at any angle was the version before; connecting
        # the points in order before that zigzagged and drew fans on Anubis.
        c = q.mean(axis=0)
        u, sv, vt = np.linalg.svd(q - c, full_matrices=False)
        vertical = abs(vt[0][1]) >= abs(vt[0][0])
        run, across = (1, 0) if vertical else (0, 1)
        at = float(np.median(q[:, across]))
        lo, hi = float(q[:, run].min()), float(q[:, run].max())
        if hi - lo < 2:
            continue
        a, b = [0.0, 0.0], [0.0, 0.0]
        a[across] = b[across] = at
        a[run], b[run] = lo, hi
        # The band re-sided around the line reaches every border pixel of
        # this doorway, however slanted the doorway was.
        band = max(BAND_PX, float(np.abs(q[:, across] - at).max()) + 2)
        out.append(([tuple(a), tuple(b)], band))
    return out


def _floors(split):
    return ["upper", "lower"] if split is not None else [None]


def _on_floor(z, split, floor):
    return floor is None or (z < split) == (floor == "lower")


def _px(cal):
    def px(x, y):
        return ((x - cal["pos_x"]) / cal["scale"], (cal["pos_y"] - y) / cal["scale"])
    return px


def sheet(map_name, areas, names, cid, floor, split):
    """One floor's callout raster, before and after its borders are
    straightened, and the straight border lines, all in radar pixels.

    The preview, the drawing and the counting grid are all made from this, so
    the place a position is counted under is the place drawn under it."""
    px = _px(radar.calibration(map_name))
    keep = [i for i, a in enumerate(areas) if _on_floor(a.centre()[2], split, floor)]

    # 1. Every pixel's callout, lower areas first so the upper floor wins.
    lab = Image.new("I", (SIZE, SIZE), 0)
    ld = ImageDraw.Draw(lab)
    for i in sorted(keep, key=lambda i: areas[i].centre()[2]):
        ld.polygon([px(c[0], c[1]) for c in areas[i].corners], fill=cid[names[i]])
    raster = np.array(lab, dtype=np.int32)
    before = raster.copy()

    # 2. Border points between two callouts, from the pixel map: every pixel
    #    whose right or lower neighbour is another callout. Taken from Valve's
    #    edges instead, borders came out partial wherever triangles met at a T.
    by_pair = defaultdict(list)
    for dy, dx in ((0, 1), (1, 0)):
        a = raster[: SIZE - dy, : SIZE - dx]
        b = raster[dy:, dx:]
        m = (a > 0) & (b > 0) & (a != b)
        yy, xx = np.nonzero(m)
        for y, x, la, lb in zip(yy, xx, a[m], b[m]):
            pair = (int(min(la, lb)), int(max(la, lb)))
            by_pair[pair].append((x + dx / 2, y + dy / 2))

    # 3. Straighten each border and re-side the pixels along it to match.
    lines = []
    ys, xs = np.mgrid[0:SIZE, 0:SIZE]
    for (ca, cb), segs in by_pair.items():
        for simple, band_px in _borders(segs):
            lines.append(simple)
            p = np.array(simple)
            x0, y0 = np.floor(p.min(axis=0) - band_px).astype(int)
            x1, y1 = np.ceil(p.max(axis=0) + band_px).astype(int)
            x0, y0 = max(x0, 0), max(y0, 0)
            x1, y1 = min(x1, SIZE - 1), min(y1, SIZE - 1)
            if x1 <= x0 or y1 <= y0:
                continue
            gx = xs[y0:y1 + 1, x0:x1 + 1].astype(float)
            gy = ys[y0:y1 + 1, x0:x1 + 1].astype(float)
            sub = raster[y0:y1 + 1, x0:x1 + 1]
            best_d = np.full(gx.shape, np.inf)
            side = np.zeros(gx.shape)
            for (ax, ay), (bx, by) in zip(simple[:-1], simple[1:]):
                vx, vy = bx - ax, by - ay
                ll = vx * vx + vy * vy or 1.0
                t = np.clip(((gx - ax) * vx + (gy - ay) * vy) / ll, 0, 1)
                dist = np.hypot(gx - (ax + t * vx), gy - (ay + t * vy))
                cross = vx * (gy - ay) - vy * (gx - ax)
                closer = dist < best_d
                best_d = np.where(closer, dist, best_d)
                side = np.where(closer, np.sign(cross), side)
            band = (best_d <= band_px) & np.isin(sub, (ca, cb))
            if not band.any():
                continue
            pos_a = np.sum(band & (side > 0) & (sub == ca)) + np.sum(band & (side < 0) & (sub == cb))
            pos_b = np.sum(band & (side > 0) & (sub == cb)) + np.sum(band & (side < 0) & (sub == ca))
            left, right = (ca, cb) if pos_a >= pos_b else (cb, ca)
            sub[band & (side > 0)] = left
            sub[band & (side < 0)] = right
    return {"floor": floor, "before": before, "after": raster, "lines": lines}


def label_spots(raster) -> list:
    """[cid, x, y, depth] per callout at its deepest point, so a label sits
    inside its zone; biggest zones first, since they are labelled first."""
    from scipy.ndimage import distance_transform_edt
    out = []
    ids, counts = np.unique(raster[raster > 0], return_counts=True)
    for k, n in sorted(zip(ids, counts), key=lambda kn: -kn[1]):
        if n < 30:
            continue
        depth = distance_transform_edt(raster == k)
        y, x = np.unravel_index(int(np.argmax(depth)), depth.shape)
        out.append([int(k), int(x), int(y), round(float(depth[y, x]), 1)])
    return out


def preview(map_name, sh, cid, colours, split):
    """data/view/navzones_<map>[_floor].png, for review."""
    floor = sh["floor"]
    radar_img = Image.open(radar.path_for(map_name, "lower" if floor == "lower" else None)) \
        .convert("RGBA").resize((SIZE, SIZE))
    # The radar's transparent margin hides junk colour; ignoring the alpha
    # drew it as streaks ("screen tearing", Johan 2026-10-22). Composite it.
    base = Image.alpha_composite(Image.new("RGBA", (SIZE, SIZE), (18, 18, 22, 255)), radar_img)
    raster = sh["after"]
    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    for n, k in cid.items():
        m = raster == k
        rgba[m, :3] = colours[n]
        rgba[m, 3] = FILL_ALPHA
    img = Image.alpha_composite(base, Image.fromarray(rgba, "RGBA"))
    d = ImageDraw.Draw(img)
    for line in sh["lines"]:
        d.line([tuple(p) for p in line], fill=(255, 255, 255, 235), width=2, joint="curve")

    def font(size):
        try:
            return ImageFont.truetype("arialbd.ttf", size)
        except OSError:
            return ImageFont.load_default()

    # A label that would cover another tries a smaller size, then is left
    # off rather than drawn over one (Nuke's A site stacked Hut, Roof,
    # Rafters and Trophy on each other, 2026-10-22).
    name_of = {k: n for n, k in cid.items()}
    placed = []
    for k, x, y, _depth in label_spots(raster):
        text = pretty(name_of[k])
        for size in (12, 10):
            f = font(size)
            l, t, r, b = d.textbbox((0, 0), text, font=f, stroke_width=2)
            box = (x - (r - l) / 2, y - (b - t) / 2, x + (r - l) / 2, y + (b - t) / 2)
            if not any(box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3]
                       for q in placed):
                d.text((box[0], box[1]), text, fill=(255, 255, 255, 255), font=f,
                       stroke_width=2, stroke_fill=(0, 0, 0, 255))
                placed.append(box)
                break
    suffix = "" if split is None else f"_{floor}"
    out = OUT_PNG / f"navzones_{map_name}{suffix}.png"
    img.convert("RGB").save(out)
    return out


def counting_grid(map_name, areas, names, cid, sheets, split):
    """The lookup counting uses: for every radar pixel, up to K stacked
    surfaces as (height, callout).

    A position takes the surface nearest its height, so a bridge and the
    canal under it stay two places. Ground the nav mesh leaves a few pixels
    short of a wall takes its nearest surface. Then every pixel a border's
    straightening re-sided on the drawing is re-sided here too, for the
    surface the drawing showed, so the count and the picture agree."""
    from scipy.ndimage import distance_transform_edt
    cal = radar.calibration(map_name)
    px = _px(cal)
    zg = np.full((GRID_LAYERS, SIZE, SIZE), np.nan, dtype=np.float32)
    ig = np.zeros((GRID_LAYERS, SIZE, SIZE), dtype=np.uint8)
    for i, a in enumerate(areas):
        P = np.array([px(c[0], c[1]) for c in a.corners])
        x0, y0 = np.maximum(np.floor(P.min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(P.max(axis=0)).astype(int), SIZE - 1)
        if x1 < x0 or y1 < y0:
            continue
        gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        cx, cy = gx + 0.5, gy + 0.5
        # Even-odd, not a same-side test: CS2's areas need not be convex, and
        # a convex test kept one pixel of a big area on Nuke's A floor.
        inside = np.zeros(cx.shape, dtype=bool)
        for k in range(len(P)):
            (ax, ay), (bx, by) = P[k], P[(k + 1) % len(P)]
            if ay == by:
                continue
            crosses = (ay > cy) != (by > cy)
            inside ^= crosses & (cx < (bx - ax) * (cy - ay) / (by - ay) + ax)
        if not inside.any():
            mx, my = P.mean(axis=0)
            inside = (gx == int(mx)) & (gy == int(my))
            if not inside.any():
                continue
        # The area's own plane, so a ramp is at its height pixel by pixel.
        C = np.array(a.corners)
        A = np.column_stack([C[:, 0], C[:, 1], np.ones(len(C))])
        coef = np.linalg.lstsq(A, C[:, 2], rcond=None)[0]
        wx = cal["pos_x"] + cx[inside] * cal["scale"]
        wy = cal["pos_y"] - cy[inside] * cal["scale"]
        zz = (coef[0] * wx + coef[1] * wy + coef[2]).astype(np.float32)
        yy, xx = gy[inside], gx[inside]
        todo = np.ones(len(zz), dtype=bool)
        for k in range(GRID_LAYERS):
            zk = zg[k, yy, xx]
            free = np.isnan(zk)
            same = ~free & (np.abs(zk - zz) < SAME_SURFACE)
            put = todo & free
            zg[k, yy[put], xx[put]] = zz[put]
            ig[k, yy[put], xx[put]] = cid[names[i]]
            todo &= ~(free | same)
            if not todo.any():
                break

    # Floor by floor: on Nuke every pixel along the upper floor's edge
    # already held the lower floor, so filling only empty pixels left the
    # upper edge (and every crate's inset on A) unplaced, 9% of positions.
    for floor in _floors(split):
        mine = ~np.isnan(zg) & (True if split is None else
                                 (np.nan_to_num(zg, nan=1e9) < split) == (floor == "lower"))
        k_top = np.argmax(mine, axis=0)                 # first layer on this floor
        has = mine.any(axis=0)
        fz = np.where(has, np.take_along_axis(zg, k_top[None], 0)[0], np.nan)
        fi = np.where(has, np.take_along_axis(ig, k_top[None], 0)[0], 0)
        dist, (ny, nx) = distance_transform_edt(~has, return_indices=True)
        fill = ~has & (dist <= EDGE_PX)
        yy, xx = np.nonzero(fill)
        add_z, add_i = fz[ny[fill], nx[fill]], fi[ny[fill], nx[fill]]
        todo = np.ones(len(yy), dtype=bool)
        for k in range(GRID_LAYERS):
            free = todo & np.isnan(zg[k, yy, xx])
            zg[k, yy[free], xx[free]] = add_z[free]
            ig[k, yy[free], xx[free]] = add_i[free]
            todo &= ~free

    for sh in sheets:
        moved = (sh["before"] != sh["after"]) & (sh["before"] > 0) & (sh["after"] > 0)
        for k in range(GRID_LAYERS):
            here = moved & (ig[k] == sh["before"])
            if split is not None:
                here &= ~np.isnan(zg[k]) & ((zg[k] < split) == (sh["floor"] == "lower"))
            ig[k][here] = sh["after"][here]

    used = int(max(k + 1 for k in range(GRID_LAYERS) if (ig[k] > 0).any()))
    z16 = np.where(np.isnan(zg[:used]), -32768, np.round(zg[:used])).astype(np.int16)
    out = OUT_JSON / f"{map_name}.grid.npz"
    np.savez_compressed(out, z=z16, id=ig[:used],
                        cal=np.array([cal["pos_x"], cal["pos_y"], cal["scale"]]))
    return out, used


def _rdp_closed(pts, tol):
    """The fewest straight segments within tol around a closed loop."""
    pts = np.asarray(pts, dtype=float)
    if len(pts) < 4:
        return pts
    far = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    keep = np.zeros(len(pts), dtype=bool)
    keep[[0, far]] = True
    for lo, hi in ((0, far), (far, len(pts))):
        stack = [(lo, hi)]
        while stack:
            a, b = stack.pop()
            if b - a < 2:
                continue
            pa, pb = pts[a], pts[b % len(pts)]
            ab = pb - pa
            n = np.hypot(*ab) or 1.0
            mid = pts[a + 1:b]
            d = np.abs(ab[0] * (mid[:, 1] - pa[1]) - ab[1] * (mid[:, 0] - pa[0])) / n
            k = int(np.argmax(d))
            if d[k] > tol:
                keep[a + 1 + k] = True
                stack += [(a, a + 1 + k), (a + 1 + k, b)]
    return pts[keep]


def trace(mask) -> list:
    """The outline of a pixel mask as closed loops of pixel corners, each
    reduced to straight segments within TRACE_TOL."""
    m = np.pad(mask, 1)
    inside = m[1:-1, 1:-1]
    nxt = defaultdict(list)
    for out_of, (s0, s1) in (
            (m[:-2, 1:-1], ((0, 0), (1, 0))),     # top edge, left to right
            (m[1:-1, 2:], ((1, 0), (1, 1))),      # right edge, downwards
            (m[2:, 1:-1], ((1, 1), (0, 1))),      # bottom edge, right to left
            (m[1:-1, :-2], ((0, 1), (0, 0)))):    # left edge, upwards
        rr, cc = np.nonzero(inside & ~out_of)
        for r, c in zip(rr.tolist(), cc.tolist()):
            nxt[(c + s0[0], r + s0[1])].append((c + s1[0], r + s1[1]))
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, cur = [start], start
        while True:
            ends = nxt.get(cur)
            if not ends:
                break
            nx_ = ends.pop()
            if not ends:
                del nxt[cur]
            cur = nx_
            if cur == start:
                break
            loop.append(cur)
        if len(loop) < 4:
            continue
        pts = np.array(loop, dtype=float)
        # Drop points in the middle of a straight run before simplifying.
        prev, after = np.roll(pts, 1, axis=0), np.roll(pts, -1, axis=0)
        turn = ((pts - prev)[:, 0] * (after - pts)[:, 1]
                - (pts - prev)[:, 1] * (after - pts)[:, 0]) != 0
        pts = pts[turn]
        if len(pts) < 3:
            continue
        pts = _rdp_closed(pts, TRACE_TOL)
        x, y = pts[:, 0], pts[:, 1]
        if len(pts) >= 3 and abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2 >= 6:
            loops.append(pts)
    return loops


def _path(loops) -> str:
    out = []
    for pts in loops:
        out.append("M" + "L".join(f"{x:g} {y:g}" for x, y in pts) + "Z")
    return "".join(out)


def drawing(map_name, areas, names, cid, sheets, colours, sides) -> Path:
    """counterplay/navzones/<map>.draw.json: what the site draws. Per callout
    its label, colour and centre; per floor one straight-edged outline per
    callout, the straight borders and where each label goes. Radar pixels."""
    callouts = {}
    for n, k in cid.items():
        mine = [a for a, nm in zip(areas, names) if nm == n]
        w = np.array([abs(_area2d(a)) + 1 for a in mine])
        c = np.array([a.centre() for a in mine])
        t, ct = sides.get(n, {}).get(2, 0), sides.get(n, {}).get(3, 0)
        callouts[str(k)] = {
            "name": n, "label": pretty(n),
            "colour": "#%02x%02x%02x" % tuple(colours[n]),
            "centre": [round(float(v), 1) for v in (c * w[:, None]).sum(0) / w.sum()],
            "t_share": round(t / (t + ct), 3) if t + ct else None}
    floors = []
    for sh in sheets:
        raster = sh["after"]
        paths = {}
        for k in np.unique(raster[raster > 0]).tolist():
            p = _path(trace(raster == k))
            if p:
                paths[str(k)] = p
        ys, xs = np.nonzero(raster > 0)
        floors.append({
            "level": sh["floor"],
            "box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "paths": paths,
            "lines": [[round(float(v), 1) for v in (*a, *b)] for a, b in sh["lines"]],
            "labels": label_spots(raster)})
    out = OUT_JSON / f"{map_name}.draw.json"
    out.write_text(json.dumps({"map": map_name, "size": SIZE, "callouts": callouts,
                               "floors": floors}, separators=(",", ":")), encoding="utf-8")
    return out


def _area2d(a):
    s = 0.0
    cs = a.corners
    for k in range(len(cs)):
        x1, y1 = cs[k][:2]
        x2, y2 = cs[(k + 1) % len(cs)][:2]
        s += x1 * y2 - x2 * y1
    return s / 2


def build(map_name: str, redraw: bool = False):
    print(map_name, flush=True)
    areas = navmesh.read(nav_bytes(map_name))
    index = Index(areas)
    src = OUT_JSON / f"{map_name}.json"
    if redraw and src.exists():
        # Names and sides as last measured: no demos read.
        stored = json.loads(src.read_text(encoding="utf-8"))
        by_id = {q["id"]: q["name"] for q in stored["areas"]}
        names = [by_id[a.area_id] for a in areas]
        sides = {n: {int(t): v for t, v in c.items()}
                 for n, c in stored.get("sides", {}).items()}
    else:
        votes, sides = callout_votes(map_name, index)
        names = smooth(name_areas(areas, votes), votes, neighbours(areas, index))
    OUT_JSON.mkdir(parents=True, exist_ok=True)
    src.write_text(json.dumps({
        "map": map_name, "source": "CS2 navigation mesh, named by demo last_place_name",
        "sides": {n: dict(c) for n, c in sides.items()},
        "areas": [{"id": a.area_id, "name": n,
                   "corners": [[round(v, 1) for v in c] for c in a.corners]}
                  for a, n in zip(areas, names)]}), encoding="utf-8")
    split = (radar.calibration(map_name) or {}).get("floor_split")
    callouts = sorted(set(names))
    cid = {n: k + 1 for k, n in enumerate(callouts)}
    colours = scheme(callouts, sides)
    sheets = [sheet(map_name, areas, names, cid, f, split) for f in _floors(split)]
    for sh in sheets:
        out = preview(map_name, sh, cid, colours, split)
        print(f"  {len(areas)} areas, {len(callouts)} callouts -> {out.name}", flush=True)
    g, layers = counting_grid(map_name, areas, names, cid, sheets, split)
    d = drawing(map_name, areas, names, cid, sheets, colours, sides)
    print(f"  {g.name} ({layers} layers, {g.stat().st_size // 1024} KB), "
          f"{d.name} ({d.stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    maps = (["de_mirage", "de_inferno", "de_dust2", "de_ancient", "de_anubis",
             "de_nuke", "de_cache"] if args == ["all"] else args)
    for m in maps:
        build(m, redraw="--redraw" in sys.argv)
