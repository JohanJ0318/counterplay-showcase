"""A map's places from the game's own callouts: where a position is, and the
drawing of every place.

    co = callouts.load("de_mirage")      # None for a map with no files
    co.assign(x, y, z)                   # callout number per sample, 0 nowhere
    callouts.svg("de_mirage", floor, ...)

Built on the PC by tools/nav_zones.py from Valve's navigation mesh, named by
the place name (last_place_name) the game showed the players standing there,
and shipped as two files per map in counterplay/navzones/:

  <map>.grid.npz   every radar pixel's stacked surfaces as (height, callout).
                   A position takes the surface nearest its height, so
                   Anubis's bridge and the canal under it stay two places.
  <map>.draw.json  one straight-edged outline per callout per floor, the
                   borders between them and where each label goes.

Both are made from one raster, with each border straightened into a line and
the ground along it re-sided to match, so a position is counted under the
place drawn under it. Replaced the k-means zones on 2026-10-23 (Johan: "zones
would look better if divided by straight lines"); counterplay/zonemodel.py
still serves any map with no files here.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent / "navzones"
# A position further than this above or below every surface at its pixel is
# nowhere: the jump peak is about 60 units, a fall off a ledge passes through.
MAX_DZ = 160.0
EMPTY_Z = -32768
# How far, in radar pixels (5 to 7 world units each), a position may look
# for ground at its own height. Ordered nearest first.
REACH_PX = 8
_RINGS = sorted(((dx, dy) for dx in range(-REACH_PX, REACH_PX + 1)
                 for dy in range(-REACH_PX, REACH_PX + 1)
                 if dx * dx + dy * dy <= REACH_PX * REACH_PX),
                key=lambda d: d[0] * d[0] + d[1] * d[1])

_LOADED: dict = {}


class Callouts:
    """One map's callouts. Movement and smokes hold it where they used to hold
    the zone model, and only ever ask it `assign`."""

    def __init__(self, map_name: str, grid, draw: dict):
        self.map_name = map_name
        self.z = grid["z"].astype(np.float32)
        self.z[grid["z"] == EMPTY_Z] = np.nan
        self.id = grid["id"]
        self.pos_x, self.pos_y, self.scale = (float(v) for v in grid["cal"])
        self.size = self.id.shape[-1]
        self.draw = draw
        self.callouts = {int(k): v for k, v in draw["callouts"].items()}

    def assign(self, x, y, z) -> np.ndarray:
        shape = np.shape(x)
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        z = np.asarray(z, dtype=float).ravel()
        px = np.floor((x - self.pos_x) / self.scale).astype(np.int64)
        py = np.floor((self.pos_y - y) / self.scale).astype(np.int64)
        ok = (px >= 0) & (px < self.size) & (py >= 0) & (py < self.size)
        out = np.zeros(len(x), dtype=np.int32)
        # Own pixel first, then outward ring by ring: the mesh stops short of
        # walls and crates, and on a stacked map the pixel next to an upper
        # floor's edge holds only the floor below, so "nearest surface at
        # this height a step away" is what a position there is standing on.
        todo = np.nonzero(ok)[0]
        for dx, dy in _RINGS:
            if not len(todo):
                break
            qx = np.clip(px[todo] + dx, 0, self.size - 1)
            qy = np.clip(py[todo] + dy, 0, self.size - 1)
            dz = np.abs(self.z[:, qy, qx] - z[todo][None, :])   # layers x samples
            dz = np.where(np.isnan(dz), np.inf, dz)
            best = np.argmin(dz, axis=0)
            col = np.arange(len(best))
            near = dz[best, col] <= MAX_DZ
            out[todo[near]] = self.id[best[near], qy[near], qx[near]]
            todo = todo[~near]
        return out.reshape(shape)


def load(map_name: str) -> Callouts | None:
    """This map's callouts, read once per process; None without its files."""
    if map_name in _LOADED:
        return _LOADED[map_name]
    got = None
    g, d = HERE / f"{map_name}.grid.npz", HERE / f"{map_name}.draw.json"
    if g.exists() and d.exists():
        try:
            with np.load(g) as grid:
                got = Callouts(map_name, dict(grid),
                               json.loads(d.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            got = None
    _LOADED[map_name] = got
    return got


def _esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# Rendered label sizes in CSS pixels, at a desk and on a phone, where the
# picture is the screen's width and a label keeps its own size through the
# --zfs-p variable (theme.py) instead of shrinking with the drawing.
LABEL_PX = 11.0
PHONE_LABEL_PX = 10.0
PHONE_WIDTH = 340.0


def _labels(floor, names, u_desk, u_phone, keep_ids, frame) -> list[str]:
    """One label per place at its deepest point, kept inside the frame at the
    larger of the desk and phone sizes (a spawn's deepest point is often at
    the map's edge, and "T Spawn" ran off it). Every label is hidden until
    its place is pointed at, so they never need to dodge each other."""
    out = []
    fx0, fy0, fx1, fy1 = frame
    for k, x, y, _depth in floor["labels"]:
        if k not in keep_ids or not names.get(k):
            continue
        text = names[k]
        hw = max(0.3 * LABEL_PX * u_desk, 0.3 * PHONE_LABEL_PX * u_phone) * len(text) + 2
        hh = max(0.6 * LABEL_PX * u_desk, 0.6 * PHONE_LABEL_PX * u_phone)
        x = min(max(x, fx0 + hw), fx1 - hw) if fx1 - fx0 > 2 * hw else (fx0 + fx1) / 2
        y = min(max(y, fy0 + hh), fy1 - hh)
        out.append(f'<text class="zlab" data-k="{k}" x="{x:.0f}" y="{y:.0f}">'
                   f'{_esc(text)}</text>')
    return out


def _reveal(scope: str, ids) -> str:
    """CSS that shows a place's name while its shape is hovered, or focused
    by a tap on a phone (Johan, 2026-10-23: names only on hover). One rule
    per place, scoped to this picture, since one page draws several maps."""
    sel = ",".join(
        f".{scope} .zfills:has([data-k=\"{k}\"]:is(:hover,:focus))~.zlabels [data-k=\"{k}\"]"
        for k in sorted(ids))
    return f"<style>{sel}{{opacity:1}}</style>" if sel else ""


def svg(map_name: str, floor: dict, radar: dict | None, height: int = 460,
        width: int = 620, title: str = "", stat_zones: bool = False,
        groups=None, pad: int = 12) -> str:
    """One floor of a map as the site draws it, in radar pixels.

    `height` is what theme.py draws the figure at on a desk and `width` caps
    it; together they set the label size. stat_zones: every place is a path
    class="zfill" data-z=<group>, neutral until the page's script colours it
    by its fights (ZONE_JS). Otherwise every place is the same grey. `groups` maps callout number to the group scan() counts it under
    (0 for a place never counted, a spawn); None keeps the callout number."""
    co = load(map_name)
    if co is None:
        return ""
    x0, y0, x1, y1 = floor["box"]
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    vb_w, vb_h = x1 - x0, y1 - y0
    u_desk = max(vb_h / height, vb_w / width)       # drawing units per CSS px
    u_phone = vb_w / PHONE_WIDTH
    size = co.size
    parts = []
    if radar is not None:
        parts.append(f'<image href="{radar["url"]}" x="0" y="0" width="{size}" '
                     f'height="{size}" preserveAspectRatio="none" opacity="0.85"/>')
    fills = []
    names, kept = {}, set()
    for k_s, d in floor["paths"].items():
        k = int(k_s)
        c = co.callouts.get(k, {})
        g = k if groups is None else int(groups[k]) if k < len(groups) else 0
        if stat_zones:
            if not g:
                fills.append(f'<path d="{d}" fill="var(--faint)" opacity=".12"/>')
                continue
            fills.append(f'<path class="zfill" data-z="{g}" data-k="{k}" tabindex="-1" '
                         f'd="{d}" fill="var(--faint)" opacity=".28"><title></title></path>')
        else:
            # Grey, like a place with no verdict on the Positions tab: one
            # match says nothing green or red about a place, and a colour per
            # place read as random (Johan, 2026-10-23).
            fills.append(f'<path class="zplace" data-k="{k}" tabindex="-1" d="{d}" '
                         f'fill="var(--zone-even)" opacity=".38"/>')
        names[k] = c.get("label", "")
        kept.add(k)
    parts.append(f'<g class="zfills" fill-rule="evenodd">{"".join(fills)}</g>')
    lines = "".join(f'M{a:g} {b:g}L{c:g} {d:g}' for a, b, c, d in floor["lines"])
    if lines:
        parts.append(f'<path class="zborder" d="{lines}" fill="none" stroke="#fff" '
                     f'stroke-width="{1.5 * u_desk:.2f}" stroke-linecap="round" '
                     f'opacity=".8" pointer-events="none"/>')
    labs = _labels(floor, names, u_desk, u_phone, kept, (x0, y0, x1, y1))
    if labs:
        parts.append(f'<g class="zlabels" font-size="{LABEL_PX * u_desk:.1f}" '
                     f'font-weight="700" text-anchor="middle" '
                     f'dominant-baseline="central" fill="#fff" pointer-events="none" '
                     f'style="paint-order:stroke;stroke:#000;stroke-opacity:.85;'
                     f'stroke-width:{2.6 * u_desk:.2f}px;stroke-linejoin:round">'
                     f'{"".join(labs)}</g>')
    scope = "zc" + secrets.token_hex(4)
    parts.insert(0, _reveal(scope, kept))
    named = f'role="img" aria-label="{_esc(title)}" ' if title else ""
    name_el = f"<title>{_esc(title)}</title>" if title else ""
    return (f'<svg class="{scope}" viewBox="{x0} {y0} {vb_w} {vb_h}" width="100%" '
            f'style="max-width:{width}px;--zfs-p:{PHONE_LABEL_PX * u_phone:.1f}px" '
            f'{named}xmlns="http://www.w3.org/2000/svg">{name_el}{"".join(parts)}</svg>')
