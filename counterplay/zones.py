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


# Zone fills. One hue family, twelve steps of lightness and saturation, so a
# picture of twenty zones reads as one map rather than as a pie chart. Indices
# are walked with a stride that is coprime with the length, which spreads
# consecutive zone numbers across the whole palette and stops two adjacent
# zones sharing a shade.
ZONE_FILLS = [
    "#5B21B6", "#8B5CF6", "#6D28D9", "#A78BFA", "#4C1D95", "#7C3AED",
    "#9F7AEA", "#5D3FD3", "#B39DDB", "#6941C6", "#C4B5FD", "#7E5BEF",
]
ZONE_STRIDE = 5


def zone_fill(i: int) -> str:
    """A colour for zone index `i`, chosen so neighbours are not alike."""
    return ZONE_FILLS[(i * ZONE_STRIDE) % len(ZONE_FILLS)]


def picture_extent(x, y, radar):
    """The world rectangle a picture is drawn in: (x0, x1, y0, y1).

    Factored out of svg() because the radar mask has to be resampled onto
    exactly the box the drawing uses. Computed in two places they would drift,
    and a mask a few cells off the map it is meant to bound is worse than no
    mask at all.

    The 0.02 percentile is not a rounding error. A player who walks to the
    back wall once a match is a tenth of a percent of the samples, and on Nuke
    that tenth of a percent is the whole of the ground behind both spawns.
    0.02 keeps it while still discarding the genuine stray, a player clipped
    out of the world.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    rx0, rx1 = float(radar["x0"]), float(radar["x1"])
    ry0, ry1 = float(radar["y0"]), float(radar["y1"])
    dx0, dx1 = np.percentile(x, [0.02, 99.98])
    dy0, dy1 = np.percentile(y, [0.02, 99.98])
    # The percentile sizes the MARGIN, so one glitched sample cannot inflate
    # the padding. It does not decide the edges: the box has to contain every
    # sample the radar admits. Trimming to the percentile and padding from
    # there put nuke upper's frame at x = -2911 with players out to -2935, so
    # T spawn was drawn hard against a border it had already crossed. Anything
    # genuinely outside the world is outside the radar bounds and the clamp
    # below removes it.
    mx = max(120.0, (dx1 - dx0) * 0.06)
    my = max(120.0, (dy1 - dy0) * 0.06)
    return (max(rx0, float(x.min()) - mx), min(rx1, float(x.max()) + mx),
            max(ry0, float(y.min()) - my), min(ry1, float(y.max()) + my))


# How far the played area may grow into the map. Six cells of a 150 grid is
# roughly a corridor's width in world units: enough to finish a corner that
# people clip, not enough to walk through a building.
GROW_PASSES = 6


def svg(x, y, centres, counts, plant_x=None, plant_y=None,
        width: int = 620, pad: int = 26, first_number: int = 1,
        labels=None, geometry=None, radar=None, extent=None,
        anchors=None, mask=None, title: str = "", stat_zones: bool = False) -> str:
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
        # CROPPED TO WHAT IS THERE, not to the whole radar square.
        #
        # Valve's radar is a square covering the entire level including the
        # skybox, the out-of-bounds and the parts of the map this game mode
        # never uses. Drawing at its full extent puts the played area in the
        # middle of a large empty frame: on Nuke's lower floor the map used
        # about a fifth of the picture and the rest was blank, which reads as
        # a map that failed to load rather than as a map with margins.
        #
        # So the frame is the bounding box of the samples, padded, and clamped
        # to the radar so it can never ask for image that does not exist. The
        # radar itself is still positioned by its own world coordinates, so it
        # lines up and the viewport simply crops it.
        x0, x1, y0, y1 = picture_extent(x, y, radar)
    elif geometry is not None and len(geometry[0]):
        gx = np.asarray(geometry[0], dtype=float)
        gy = np.asarray(geometry[1], dtype=float)
        x0, x1 = float(gx.min()), float(gx.max())
        y0, y1 = float(gy.min()), float(gy.max())
    else:
        x0, x1 = np.percentile(x, [0.2, 99.8])
        y0, y1 = np.percentile(y, [0.2, 99.8])
    # One scale serves both axes, so the map is never stretched: the longer
    # side fills the frame and the shorter one is whatever it is. THE BOX IS
    # THEN CUT TO THE DRAWING on both axes rather than staying `width` wide.
    #
    # Centring was tried first and only balanced the problem. Nuke's lower
    # floor is 1860 by 3341 world units, so at a box 420 wide the map is 205
    # pixels of it, and centring left 107 pixels of nothing down each side
    # instead of 215 down one. The height was always computed from the
    # content; the width is now too.
    # `req` survives because `width` becomes the fitted box below, and the
    # style cap still has to mean "no bigger than the caller asked for"
    # rather than "no bigger than this particular map turned out".
    req = width
    span = max(x1 - x0, y1 - y0) or 1.0
    scale = (width - 2 * pad) / span
    height = int((y1 - y0) * scale + 2 * pad)
    width = int((x1 - x0) * scale + 2 * pad)
    off_x = pad

    # CS2's Y axis points the opposite way to SVG's, so it is flipped here
    # rather than in the data; the stored coordinates stay game-native.
    def px(vx, vy):
        return (off_x + (vx - x0) * scale, pad + (y1 - vy) * scale)

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

    # Bin to a grid, then paint each occupied cell in the colour of the zone it
    # belongs to. A density of translucent squares reads as a smear and never
    # says which zone anything is; a filled region is a picture of the zones.
    bins = 150
    h, xe, ye = np.histogram2d(x, y, bins=bins,
                              range=[[x0, x1], [y0, y1]])
    occupied = h > 0

    # Close pinholes. A cell nobody happened to stand in, surrounded by cells
    # they did, is a gap in the sampling rather than a hole in the map. Three
    # passes, and only where a cell has at least three occupied neighbours, so
    # this fills speckle without inventing corridors: a cell needs most of its
    # neighbours occupied before it joins them, which cannot bridge a wall.
    for _ in range(3):
        n = np.zeros(occupied.shape, dtype=np.int8)
        n[1:, :] += occupied[:-1, :]
        n[:-1, :] += occupied[1:, :]
        n[:, 1:] += occupied[:, :-1]
        n[:, :-1] += occupied[:, 1:]
        occupied = occupied | (n >= 3)

    # GROW INTO THE MAP, BOUNDED BY VALVE'S OWN ALPHA CHANNEL.
    #
    # A corner somebody crosses twice a match is one or two samples in twenty
    # thousand cells, and it came out as a hole: behind both spawns on Nuke,
    # suicide and T plat on Dust2, the ground before second mid on Inferno.
    # The map is there; the traffic is not.
    #
    # Valve's radar image already knows where the map is, so the played area
    # is grown outward and a cell may only be entered where the alpha channel
    # says there is map. That reaches into a corner attached to somewhere
    # people go and stops dead at the void.
    #
    # BOUNDED, NOT FLOOD FILLED. The alpha covers roofs and the tops of walls
    # as well as the floor, so an unbounded fill would paint zones across
    # solid geometry. GROW_PASSES cells is roughly a corridor's width: far
    # enough to finish a corner, not far enough to cross a building.
    if mask is not None and mask.shape == occupied.shape:
        for _ in range(GROW_PASSES):
            n = np.zeros(occupied.shape, dtype=np.int8)
            n[1:, :] += occupied[:-1, :]
            n[:-1, :] += occupied[1:, :]
            n[:, 1:] += occupied[:, :-1]
            n[:, :-1] += occupied[:, 1:]
            occupied = occupied | ((n >= 1) & mask)

    # Which zone each occupied cell belongs to: nearest centre in the plane.
    # The floor split has already separated stacked geometry, so two dimensions
    # is the right question here rather than a Z-weighted three.
    cx_mid = (xe[:-1] + xe[1:]) / 2.0
    cy_mid = (ye[:-1] + ye[1:]) / 2.0
    ii, jj = np.nonzero(occupied)
    dots = []
    cw = (xe[1] - xe[0]) * scale
    if len(ii):
        px_mid = cx_mid[ii]
        py_mid = cy_mid[jj]
        d2 = ((px_mid[:, None] - centres[None, :, 0]) ** 2
              + (py_mid[:, None] - centres[None, :, 1]) ** 2)
        owner = np.argmin(d2, axis=1)
        # ONE FLAT OPACITY. Shading means WHICH ZONE and nothing else.
        #
        # It used to also carry traffic, so a cell was darker where the team
        # spent more time. Two variables in one channel, and the result said
        # neither clearly. Worse, traffic in Counter-Strike is brutally skewed:
        # a handful of chokepoints and spawn positions take most of the samples,
        # so measured across five maps between 83% and 99% of drawn cells came
        # out under 0.30 opacity. Against map art that is very close to
        # invisible, and the corners a team crosses twice a match, behind T
        # spawn, suicide, second mid, looked like holes in the map. They were
        # never missing, only faint.
        #
        # Where the team actually lives is a question the tables answer with
        # numbers and denominators. This picture answers "which zone is where",
        # and one flat fill answers it.
        strength = np.full(len(ii), 0.62)
        if radar is not None:
            strength[:] = 0.5    # the map underneath should still read through

        # RUN-LENGTH ENCODED ALONG X.
        #
        # One rect per occupied cell is nine thousand rects per map, and five
        # maps on the team page is most of why that page weighs six megabytes.
        # Neighbouring cells in the same zone at the same opacity step are one
        # rectangle, which cuts it by an order of magnitude and draws exactly
        # the same picture. Opacity is quantised to sixteenths first, or almost
        # nothing would merge.
        grid_owner = np.full(occupied.shape, -1, dtype=np.int16)
        grid_step = np.zeros(occupied.shape, dtype=np.int16)
        grid_owner[ii, jj] = owner
        grid_step[ii, jj] = np.round(strength * 16).astype(np.int16)

        # In stat mode the runs are collected per zone and emitted as one
        # path each, so a filter can repaint a whole zone by touching a single
        # element. Otherwise they stay individual rects carrying the zone's
        # categorical colour, which is the "which zone is where" picture.
        by_zone: dict = {}
        for j in range(bins):                       # each row of constant y
            i = 0
            while i < bins:
                own = grid_owner[i, j]
                if own < 0:
                    i += 1
                    continue
                step = grid_step[i, j]
                run = i + 1
                while (run < bins and grid_owner[run, j] == own
                       and grid_step[run, j] == step):
                    run += 1
                bx, by = px(xe[i], ye[j])
                w, hh = cw * (run - i) + .6, cw + .6
                if stat_zones:
                    by_zone.setdefault(int(own), []).append(
                        "M%.1f %.1fh%.1fv%.1fh%.1fz"
                        % (bx, by - cw, w, hh, -w))
                else:
                    dots.append(
                        f'<rect x="{bx:.1f}" y="{by - cw:.1f}" '
                        f'width="{w:.1f}" height="{hh:.1f}" '
                        f'fill="{zone_fill(int(own))}" '
                        f'opacity="{step / 16:.2f}"/>')
                i = run

        if stat_zones:
            for own, segs in sorted(by_zone.items()):
                # Neutral until the page colours it. A zone the current filter
                # has no rounds for stays this colour, which is the honest
                # look for "nothing happened here" and not an opinion.
                dots.append(
                    f'<path class="zfill" data-z="{first_number + own}" '
                    f'd="{"".join(segs)}" fill="var(--faint)" opacity=".28">'
                    f'<title></title></path>')

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
    # WHAT THE ZONE IS WORTH, when the caller has a reading for it.
    #
    # Replaces the name pills entirely rather than sitting beside them: the
    # reader is looking at a map and can see where a place is, so the callout
    # is the one thing the picture already gives away, and two labels on one
    # shape is how the old drawing ended up with "A main" written across the
    # middle three times.
    #
    # `stats` is {zone number: {"top", "sub", "fill", "op", "title"}} and the
    # fill comes from charts.diverge, so the scale is defined once and not
    # here. A zone with no reading stays a faint dot: nothing to say is not
    # the same as zero.
    if False:
        out_stats = []
        for n, (key, stats) in enumerate([]):
            # Every zone in every layer. A zone with a reading here and none
            # in the next one has to change when the layer changes, and one
            # shared set of dots underneath would leave a dot inside a disc.
            parts = []
            for k, centre in enumerate(centres):
                at = (anchors[k] if anchors is not None and k < len(anchors)
                      else centre)
                cx, cy = px(at[0], at[1])
                st = stats.get(first_number + k)
                if not st:
                    parts.append(
                        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" '
                        f'fill="#5B21B6" opacity=".16"/>')
                    continue
                parts.append(
                    f'<g><title>{_esc(st.get("title", ""))}</title>'
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="23" '
                    f'fill="{st["fill"]}" opacity="{st["op"]:.2f}"/>'
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="23" fill="none" '
                    f'stroke="{st["fill"]}" stroke-width="1.5" opacity=".85"/>'
                    f'<text x="{cx:.1f}" y="{cy + 2:.1f}" text-anchor="middle" '
                    f'font-size="15" font-weight="700" fill="#fff" '
                    f'style="paint-order:stroke;stroke:#191325;stroke-width:2.5px">'
                    f'{_esc(st["top"])}</text>'
                    f'<text x="{cx:.1f}" y="{cy + 14:.1f}" text-anchor="middle" '
                    f'font-size="10.5" fill="#fff" '
                    f'style="paint-order:stroke;stroke:#191325;stroke-width:2.5px">'
                    f'{_esc(st["sub"])}</text></g>')
            # The first layer is the one that shows with JavaScript off, so a
            # reader who never presses anything still gets a whole answer
            # rather than an empty map.
            on = " on" if n == 0 else ""
            out_stats.append(f'<g class="zlayer{on}" data-layer="{_esc(key)}">'
                             f'{"".join(parts)}</g>')
        labels_final = out_stats
    else:
        # Stat mode says everything on hover, so nothing is drawn on top of
        # the map: no name pills, no numbered circles, no faint dots.
        labels_final = [] if stat_zones else None

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
    labels = labels_final if labels_final is not None else marks_out

    # An accessible name, the same way charts._open gives one. Without it a
    # screen reader announces "graphic" and stops; the figcaption beside the
    # picture names the map but a caption is a sibling, not a label. Untitled
    # when no title is passed, because a drawing with a made-up name is worse
    # than one that is plainly decorative.
    named = (f'role="img" aria-label="{_esc(title)}" ' if title else "")
    name_el = f"<title>{_esc(title)}</title>" if title else ""
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'style="max-width:{req}px;color:#5B21B6" '
            f'{named}xmlns="http://www.w3.org/2000/svg">{name_el}'
            f'{"".join(base)}{"".join(dots)}{"".join(marks)}'
            f'{"".join(labels)}</svg>')
