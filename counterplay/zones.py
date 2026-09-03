"""Working out where the map is, from the demos themselves.

The problem this solves: patterns like "A-site execute off a mid smoke" need
named areas — A site, mid, apartments, banana — and CS2 does not label them.
`which_bomb_zone` labels only the bomb PLANT TRIGGER, which on de_mirage covers
3.7% of where players actually stand: precise for "the bomb went down here",
useless for "they took A".

The alternative to hand-authoring polygons for eight maps is to let the demos
draw the map. Players walk the same routes thousands of times, so clustering
where they stand recovers the map's real geography without anyone typing a
coordinate. What clustering cannot do is know that a cluster is *called*
"banana" — so this produces numbered zones and a picture, and a human who
recognises the map names them once.

That split is deliberate: the machine does the part humans are bad at (finding
structure in 1.6 million samples) and the human does the part machines are bad
at (knowing what a place is called).
"""
from __future__ import annotations

import html as _html

import numpy as np


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)

# Zones per map.
#
# Twelve was too coarse and it took a concrete counter-example to notice: on
# Anubis the water channel runs directly under mid, about 150 units below it and
# only ~500 units away horizontally. At twelve zones each zone is over a
# thousand units across, so both were swallowed into one centred between them —
# and no amount of Z weighting fixes a zone that is simply bigger than the thing
# it is meant to distinguish. At twenty, water and mid separate cleanly.
#
# The cost is twenty names per map to write instead of twelve. Zones can be
# left unnamed; a nameless zone just never appears in a pattern.
DEFAULT_ZONES = 20

# Samples are heavily autocorrelated: a player standing still for ten seconds
# is 80 nearly identical points at 8 Hz. Thinning stops the clusterer being
# dragged toward wherever people idle longest, like spawn.
THIN = 6

# How much height counts, relative to a world unit on the ground.
#
# Raw (x, y, z) barely uses height at all: Z spans 7-13% of the X/Y range on
# every map measured, so a floor gap of ~190 units is swamped by horizontal
# distance and clusters end up straddling two levels. Weighting Z fixes that,
# and the weight matters:
#
#   nuke    w=0 -> clusters span 278 units of height;  w=3 -> 115
#   anubis  w=0 -> 128;  w=3 -> 120     (water sits ~190 units under mid)
#   mirage  w=0 -> 146;  w=3 -> 134
#
# Above about 5 the cost shows up: clusters stretch sideways to chase floors,
# and the median horizontal radius grows from ~430 to ~680 on nuke. Three keeps
# the floors apart without slicing flat maps into layers nobody talks about.
Z_WEIGHT = 3.0


def collect(rounds, thin: int = THIN, alive_only: bool = True):
    """(x, y, z) samples from packed rounds, thinned.

    `rounds` is an iterable of position blobs. Cast out of int16 on the way,
    because a coordinate difference of a few thousand units overflows it.
    """
    from .positions import FLAG_ALIVE, unpack_round

    xs, ys, zs = [], [], []
    for blob in rounds:
        got = unpack_round(blob)
        if got is None:
            continue
        _meta, _sids, samples = got
        s = samples[::thin]
        if alive_only:
            keep = (s["flags"] & FLAG_ALIVE).astype(bool)
            xs.append(s["x"][keep].astype(np.int32))
            ys.append(s["y"][keep].astype(np.int32))
            zs.append(s["z"][keep].astype(np.int32))
        else:
            xs.append(s["x"].ravel().astype(np.int32))
            ys.append(s["y"].ravel().astype(np.int32))
            zs.append(s["z"].ravel().astype(np.int32))
    if not xs:
        return np.empty(0), np.empty(0), np.empty(0)
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)


def find_zones(x, y, z=None, n_zones: int = DEFAULT_ZONES, seed: int = 7,
               z_weight: float = Z_WEIGHT):
    """Cluster positions into numbered zones. Returns (centres, labels, counts).

    Height counts, scaled by Z_WEIGHT. Stacked geometry is real and coaches
    name it — top and bottom banana, heaven, pit, and on Anubis the water
    channel that runs directly under mid, about 190 units below it. Clustering
    on (x, y) alone merges those into one zone and the resulting patterns would
    be wrong in exactly the places that matter most.

    Centres come back as (x, y, z) so a caller can tell two stacked zones apart.
    """
    from sklearn.cluster import KMeans

    if len(x) < n_zones * 10:
        return np.empty((0, 3)), np.empty(0, dtype=int), np.empty(0, dtype=int)
    if z is None:
        z = np.zeros_like(x)
    pts = np.column_stack([x, y, np.asarray(z, dtype=np.float64) * z_weight])
    km = KMeans(n_clusters=n_zones, random_state=seed, n_init=6).fit(pts)
    labels = km.labels_
    counts = np.bincount(labels, minlength=n_zones)
    # Order by traffic so zone 1 is always the busiest part of the map —
    # a stable numbering makes the labels worth writing down.
    order = np.argsort(-counts)
    remap = np.zeros(n_zones, dtype=int)
    remap[order] = np.arange(n_zones)
    centres = km.cluster_centers_[order].copy()
    centres[:, 2] /= z_weight          # undo the weighting so z reads as units
    return centres, remap[labels], counts[order]


def svg(x, y, centres, counts, plant_x=None, plant_y=None,
        width: int = 620, pad: int = 26, first_number: int = 1,
        labels=None, geometry=None, radar=None, extent=None,
        anchors=None) -> str:
    """A top-down picture of one map, drawn from its own position samples.

    Density as a dot field, numbered zone centres on top, and the bomb plant
    triggers marked separately — those are the one thing the game tells us for
    certain, so they anchor the picture.
    """
    if len(x) == 0:
        return "<p>no samples</p>"
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    # Imported geometry sets the extent. Where a map has been walked, the
    # picture should be the size of the MAP, not the size of the part of it
    # anyone has played — otherwise importing the corners would crop them off.
    # A radar image is the whole map, so it sets the extent: with it, the
    # picture is the size of the MAP rather than the size of the part of it
    # anyone has played, which is the entire point of having one.
    gx = gy = None
    if extent is not None:
        # An explicit world rectangle, for zooming in on one part of a map.
        # The radar image is still placed at its own full-map position and the
        # SVG viewport crops it.
        x0, x1, y0, y1 = (float(v) for v in extent)
    elif radar is not None:
        x0, x1 = float(radar["x0"]), float(radar["x1"])
        y0, y1 = float(radar["y0"]), float(radar["y1"])
    elif geometry is not None and len(geometry[0]):
        gx = np.asarray(geometry[0], dtype=float)
        gy = np.asarray(geometry[1], dtype=float)
        x0, x1 = float(gx.min()), float(gx.max())
        y0, y1 = float(gy.min()), float(gy.max())
    else:
        x0, x1 = np.percentile(x, [0.2, 99.8])
        y0, y1 = np.percentile(y, [0.2, 99.8])
    span = max(x1 - x0, y1 - y0) or 1.0
    scale = (width - 2 * pad) / span
    height = int((y1 - y0) * scale + 2 * pad)

    # CS2's Y axis points the opposite way to SVG's, so it is flipped here
    # rather than in the data; the stored coordinates stay game-native.
    def px(vx, vy):
        return (pad + (vx - x0) * scale, pad + (y1 - vy) * scale)

    # The map itself, under everything.
    base = []
    if radar is not None:
        rx0, ry0 = px(float(radar["x0"]), float(radar["y1"]))
        rx1, ry1 = px(float(radar["x1"]), float(radar["y0"]))
        base.append(f'<image href="{radar["url"]}" x="{rx0:.1f}" y="{ry0:.1f}" '
                    f'width="{rx1 - rx0:.1f}" height="{ry1 - ry0:.1f}" '
                    f'opacity="0.85" preserveAspectRatio="none"/>')

    if gx is not None:
        bg, xe_b, ye_b = np.histogram2d(gx, gy, bins=200,
                                        range=[[x0, x1], [y0, y1]])
        cwb = (xe_b[1] - xe_b[0]) * scale
        for i in range(200):
            for j in range(200):
                if bg[i, j] <= 0:
                    continue
                bx, by = px(xe_b[i], ye_b[j])
                base.append(f'<rect x="{bx:.1f}" y="{by - cwb:.1f}" '
                            f'width="{cwb:.1f}" height="{cwb:.1f}" '
                            f'fill="currentColor" opacity="0.10"/>')

    # Bin to a grid so the dot field is a density, not 1.6 million circles.
    bins = 150
    h, xe, ye = np.histogram2d(x, y, bins=bins,
                              range=[[x0, x1], [y0, y1]])
    hot = h.max() or 1
    dots = []
    cw = (xe[1] - xe[0]) * scale
    for i in range(bins):
        for j in range(bins):
            v = h[i, j]
            if v <= 0:
                continue
            a = min(0.85, 0.10 + 0.75 * (v / hot) ** 0.42)
            if radar is not None:
                a *= 0.55        # the map is underneath; this is traffic on it
            cx, cy = px(xe[i], ye[j])
            dots.append(f'<rect x="{cx:.1f}" y="{cy - cw:.1f}" width="{cw:.1f}" '
                        f'height="{cw:.1f}" fill="currentColor" opacity="{a:.2f}"/>')

    marks = []
    if plant_x is not None and len(plant_x):
        for bx, by in zip(np.atleast_1d(plant_x), np.atleast_1d(plant_y)):
            cx, cy = px(bx, by)
            marks.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="13" fill="none" '
                         f'stroke="#A65B0B" stroke-width="2" opacity=".9"/>')

    # Named zones are drawn with their names. A number is only useful to
    # someone filling the names in; everyone else needs the word.
    #
    # When `labels` is given, a zone with no label is a faint dot rather than a
    # numbered one. On a coaching page a purple circle reading "15" is a zone
    # nobody named yet, which is noise; on the naming sheet (labels=None) the
    # number is the whole point, so that path is unchanged.
    marks_out = []
    for k, (centre, n) in enumerate(zip(centres, counts)):
        i = first_number + k
        name = labels[k] if labels and k < len(labels) else None
        # Names are drawn at the zone's ANCHOR — the busiest spot a player has
        # actually stood in it — not at its centroid. A centroid is an average,
        # and an average of two areas a wall keeps apart is inside the wall.
        at = anchors[k] if anchors is not None and k < len(anchors) else centre
        cx, cy = px(at[0], at[1])
        if labels is not None and not name:
            marks_out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="#5B21B6" '
                f'opacity=".22"/>')
        elif name:
            w = max(30.0, 6.4 * len(name) + 12)
            marks_out.append(
                f'<rect x="{cx - w / 2:.1f}" y="{cy - 9:.1f}" width="{w:.1f}" '
                f'height="18" rx="9" fill="#5B21B6" opacity=".92"/>'
                f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" '
                f'font-size="10" font-weight="700" fill="#fff">'
                f'{_esc(name)}</text>')
        else:
            marks_out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" fill="#5B21B6" '
                f'opacity=".92"/>'
                f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" '
                f'font-size="11" font-weight="700" fill="#fff">{i}</text>')
    labels = marks_out

    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'style="max-width:{width}px;color:#5B21B6" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(base)}{"".join(dots)}{"".join(marks)}'
            f'{"".join(labels)}</svg>')
