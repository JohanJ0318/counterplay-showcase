"""Charts, drawn as inline SVG.

There was not a single chart in this product. A round timeline is a time series
— a score diverging, an economy climbing and collapsing, a 12-12 becoming
16-13 — and it was twenty-nine rows of `full v force  26,600  16,150`. Every
coach reading that had to build the shape in their head, for every match.

WHY SVG BY HAND, AND NO LIBRARY
-------------------------------
Every page here is server-rendered HTML with no build step and no client-side
framework, and a charting library would be the first thing to break that. These
are also not general charts: they are three specific pictures of
Counter-Strike, and a general library would need as much configuring as this
takes to write.

Drawn with the theme's own custom properties, so a chart inherits the palette
rather than repeating it.

WHAT EVERY CHART HERE OWES THE READER
-------------------------------------
The first versions of these were bad in ways worth writing down, because they
are the ways hand-drawn charts are usually bad:

  * NO LEGEND. Colour meant the side and hollow meant an eco, and nothing on
    the page said so. A chart that needs its caption read twice has failed.
  * NO SCALE. Bar height was equipment value with no axis, so "tall" meant
    nothing in particular.
  * AN AXIS THAT LIED. The trend chart padded its range symmetrically and drew
    a deaths-traded percentage down to -6%, which is not a number that can
    exist.
  * TRUNCATED LABELS. "First blood inside the op", and three separate matches
    all reading "mir".

So: every chart carries a legend or a labeled axis, percentage scales stop at
zero, and no label is ever cut mid-word.
"""
from __future__ import annotations

import html
import math

INK = "var(--ink)"
FAINT = "var(--faint)"
LINE = "var(--border)"
CT = "var(--ct)"
T_SIDE = "var(--t)"
ACCENT = "var(--purple)"
MONO = "var(--f-mono)"
BODY = "var(--f-body)"


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _open(width: int, height: int, title: str, desc: str = "",
          max_w: int | None = None) -> str:
    # No min-width. A chart that scrolled sideways on a phone hid most of its
    # own picture: the timeline showed 8 of 24 rounds and cut off the losing
    # streak its report was about. A phone gets its own narrow drawing instead
    # (see `both`), sized so its labels land at a readable size when scaled.
    cap = f"max-width:{max_w}px;" if max_w else ""
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'style="{cap}height:auto;display:block" '
            f'role="img" aria-label="{esc(title)}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<title>{esc(title)}</title>'
            + (f'<desc>{esc(desc)}</desc>' if desc else ''))


def _text(x, y, s, size=9, fill=FAINT, anchor="start", font=MONO, weight=None):
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{size:.4g}" fill="{fill}" font-family="{font}"{w}>'
            f'{esc(s)}</text>')


def _nice_step(span: float, target: int = 4) -> float:
    """A gridline interval a person would have chosen.

    An axis divided into exactly four equal parts gives 9%, 31%, 53%, 76%,
    98%: arithmetically fine and unreadable, because the reader has to do
    subtraction to place a point. Rounding the interval up to the nearest
    1, 2, 2.5 or 5 times a power of ten costs a little whitespace at the top
    and buys an axis that reads at a glance.
    """
    if span <= 0:
        return 1.0
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _axis(lo: float, hi: float, clamp_pct: bool) -> tuple:
    """(bottom, top, [ticks]) for a range that contains the data."""
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    step = _nice_step(hi - lo)
    bot = math.floor(lo / step) * step
    top = math.ceil(hi / step) * step
    if clamp_pct:
        bot = max(0.0, bot)
        top = min(100.0, top) if top - step >= hi else top
        top = min(100.0, top)
        if top <= bot:
            top = bot + step
    ticks = []
    v = bot
    while v <= top + 1e-9:
        ticks.append(round(v, 6))
        v += step
    return bot, top, ticks


def _swatch(x, y, label, fill, hollow=False, size=9.5):
    box = (f'<rect x="{x:.1f}" y="{y - 7:.1f}" width="9" height="9" rx="2" '
           + (f'fill="none" stroke="{fill}" stroke-width="1.5"/>' if hollow
              else f'fill="{fill}" opacity=".88"/>'))
    return box + _text(x + 14, y, label, size=size, font=BODY)


def _legend(items: list, x0: float, y0: float, max_w: float,
            size: float) -> tuple[str, int]:
    """Legend entries laid out left to right, wrapping to a new line when the
    next one would run past `max_w`. Returns (svg, lines used).

    Each item is (kind, label, fill, hollow): kind "swatch" draws a box,
    "dash" a dashed line, "text" just the words. Widths are estimated from the
    character count, which is close enough for a legend and needs no font
    metrics.
    """
    out, x, line = [], x0, 0
    lh = size + 8
    for kind, label, fill, hollow in items:
        w = (0 if kind == "text" else 22) + len(label) * size * 0.56 + 16
        if x > x0 and x + w > x0 + max_w:
            x, line = x0, line + 1
        y = y0 + line * lh
        if kind == "swatch":
            out.append(_swatch(x, y, label, fill, hollow, size=size))
        elif kind == "tick":
            out.append(f'<line x1="{x:.1f}" y1="{y - 3:.1f}" x2="{x + 12:.1f}" '
                       f'y2="{y - 3:.1f}" stroke="{fill}" stroke-width="1.6" '
                       f'opacity=".6"/>' + _text(x + 18, y, label, size=size,
                                                 font=BODY))
        elif kind == "ghost":
            out.append(f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="11" '
                       f'height="11" rx="2" fill="{fill}" opacity=".3"/>'
                       + _text(x + 17, y, label, size=size, font=BODY))
        elif kind == "mark":
            out.append(f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="12" '
                       f'height="11" fill="{fill}" opacity=".16"/>'
                       + _text(x + 18, y, label, size=size, font=BODY))
        elif kind == "dash":
            out.append(f'<line x1="{x:.1f}" y1="{y - 4:.1f}" x2="{x + 20:.1f}" '
                       f'y2="{y - 4:.1f}" stroke="{fill}" stroke-width="1.4" '
                       f'stroke-dasharray="4 4" opacity=".7"/>'
                       + _text(x + 26, y, label, size=size, font=BODY))
        else:
            out.append(_text(x, y, label, size=size, font=BODY))
        x += w
    return "".join(out), line + 1


def both(wide: str, narrow: str) -> str:
    """One chart drawn twice: a wide drawing for a desk, a narrow one for a
    phone, and CSS showing whichever fits (theme.py, .fig-wide/.fig-narrow).
    Scaling one drawing to both widths either shrinks a phone's labels to
    nothing or makes a desk's enormous."""
    if not wide:
        return ""
    return (f'<div class="fig-wide">{wide}</div>'
            f'<div class="fig-narrow">{narrow}</div>')


def round_timeline(rows: list[dict], us_is_ct, width: int = 680,
                   compact: bool = False, marks=None) -> str:
    """The shape of a match, in two bands over one axis of rounds.

      SCORE     how far ahead or behind you were, as a filled step, so a
                collapse reads as a shape rather than as a line to trace
      ROUNDS    one bar per round, up if you won it, as tall as the equipment
                you brought, PURPLE IF YOU WON IT AND ORANGE IF YOU LOST
      SIDE      a ribbon under the axis saying which side you were on, which
                is also where the half swap becomes visible

    Colour used to mean the side and direction used to mean the result, so a
    reader had to decode two things at once and the two colours meant
    something else again in the W/L pills three inches up the page. Now colour
    means exactly what it means everywhere else on the site, and the side --
    which is a property of a STRETCH of rounds, not of one -- is drawn as a
    stretch.

    `us_is_ct` maps a round number to whether this team was CT, or is None
    when the side cannot be established; then it is drawn from the CT side and
    the ribbon is left off, because it would be a guess.

    Purple and orange mean good and bad for you, and nothing else: won and
    lost on the bars, your first kill and theirs on the strip. The side ribbon
    was CT purple and T orange, so a T half looked like a losing streak before
    anything was read; it is grey now, two shades, with its words.

    Three more things, added when the timeline moved to the top of the report:

      THEIR SPEND  a grey block behind each bar, from the line to what the
                   other team brought, so a "force v full" loss reads off the
                   picture. It was a floating dash, which read as a stray
                   mark whenever it sat past the end of your bar
      FIRST KILL   a strip of squares under the bars: purple where you got
                   the round's first kill, amber where they did. It replaced
                   a one-row table of the same thing.
      MARKS        `marks` is a set of round numbers the report's cards name.
                   Those rounds get a faint column, so "rounds 14 to 20" is
                   a place on the picture.
    """
    if not rows:
        return ""

    # `compact` is the phone drawing: a narrower picture with larger type, so
    # that scaled down to a phone's width every round is still on screen and
    # every label is still readable.
    fs = 1.45 if compact else 1.15
    pad_l, pad_r, pad_t = (58 if compact else 50), 14, 24
    score_h, gap, econ_h = 84, 18, 132
    ribbon_h, axis_h = 15, 22
    strip_h = 14 if us_is_ct else 0
    marks = set(marks or ())
    # Four entries. The shaded column is explained by the card that names
    # it, and the first-kill strip and the side ribbon carry their own words.
    legend_items = [("swatch", "round won", ACCENT, False),
                    ("swatch", "round lost", T_SIDE, False),
                    ("swatch", "eco or pistol", ACCENT, True),
                    ("ghost", "their spend", FAINT, False)]
    probe, lines = _legend(legend_items, pad_l, 0, width - pad_l - pad_r,
                           9.5 * fs)
    legend_h = 10 + lines * (9.5 * fs + 8)
    height = (pad_t + score_h + gap + econ_h + strip_h + ribbon_h + axis_h
              + legend_h)
    n = len(rows)
    inner = width - pad_l - pad_r
    step = inner / n
    bar_w = max(3.5, min(18.0, step * (0.74 if compact else 0.62)))

    score_top = pad_t
    score_bot = pad_t + score_h
    econ_top = score_bot + gap
    econ_mid = econ_top + econ_h / 2
    econ_half = econ_h / 2 - 9
    strip_y = econ_top + econ_h + 3
    ribbon_y = econ_top + econ_h + 4 + strip_h
    axis_y = ribbon_y + ribbon_h + 13

    peak = max((max(r["equip_ct"], r["equip_t"]) for r in rows), default=1) or 1
    # Three lines, not one. At target=3 a thirty-thousand-dollar peak rounds
    # its interval up to twenty thousand and the grid becomes a single line,
    # which is a scale nobody can read a height against.
    grid_at = _nice_step(peak, 4)

    # Which round numbers get a tick: the first, the last, and every fifth in
    # between, minus any that would land on top of the first or the last.
    # Marking every second round gave "1 2 4 6", where the first two sit a
    # column apart and read as a misprint.
    every = 1 if n <= 12 else (2 if n <= 16 else 5)
    first_rn, last_rn = rows[0]["round_num"], rows[-1]["round_num"]
    want = {first_rn, last_rn}
    want |= {r["round_num"] for r in rows if r["round_num"] % every == 0}
    want = {v for v in want if v in (first_rn, last_rn)
            or (abs(v - first_rn) > every // 2
                and abs(v - last_rn) > every // 2)}

    parts, ghosts, bars_out, ticks = [], [], [], []
    us = them = 0
    diffs, sides = [], []

    for i, r in enumerate(rows):
        ct = us_is_ct(r["round_num"]) if us_is_ct else True
        won = bool(r["ct_won"]) == ct
        equip = r["equip_ct"] if ct else r["equip_t"]
        buy = r["buy_ct"] if ct else r["buy_t"]
        sides.append(ct)

        h = max(4.0, (equip / peak) * econ_half)
        x = pad_l + i * step + (step - bar_w) / 2
        y = econ_mid - h if won else econ_mid
        fill = ACCENT if won else T_SIDE
        hollow = buy in ("eco", "pistol")
        style = (f'fill="none" stroke="{fill}" stroke-width="1.4"'
                 if hollow else f'fill="{fill}" opacity=".88"')
        bars_out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                        f'height="{h:.1f}" rx="1.5" {style}></rect>')

        if r["round_num"] in marks:
            parts.append(f'<rect x="{pad_l + i * step:.1f}" y="{score_top:.1f}" '
                         f'width="{step:.1f}" height="{econ_top + econ_h - score_top:.1f}" '
                         f'fill="{ACCENT}" opacity=".09"/>')

        # Their spend, drawn on your bar's side of the line so the two
        # heights compare directly.
        theirs = r["equip_t"] if ct else r["equip_ct"]
        th = max(2.0, (theirs / peak) * econ_half)
        gw = min(step - 1, bar_w + 5)
        ghosts.append(f'<rect x="{x - (gw - bar_w) / 2:.1f}" '
                      f'y="{econ_mid - th if won else econ_mid:.1f}" '
                      f'width="{gw:.1f}" height="{th:.1f}" rx="1.5" '
                      f'fill="{FAINT}" opacity=".3"></rect>')

        if strip_h and r.get("opening_loser"):
            ours = r["opening_loser"] != ("ct" if ct else "t")
            sq = min(bar_w, 8.0)
            bars_out.append(f'<rect x="{x + (bar_w - sq) / 2:.1f}" '
                            f'y="{strip_y + (strip_h - sq) / 2 - 1:.1f}" '
                            f'width="{sq:.1f}" height="{sq:.1f}" rx="1.5" '
                            f'fill="{ACCENT if ours else T_SIDE}" opacity=".85"/>')

        us += won
        them += not won
        diffs.append(us - them)

        if r["round_num"] in want:
            ticks.append(_text(pad_l + i * step + step / 2, axis_y,
                               r["round_num"], anchor="middle", size=9 * fs,
                               font=BODY))

    # ---- money grid, so a bar's height is a number and not an impression
    v = grid_at
    while v <= peak:
        dy = (v / peak) * econ_half
        for sign in (-1, 1):
            parts.append(f'<line x1="{pad_l}" y1="{econ_mid + sign * dy:.1f}" '
                         f'x2="{width - pad_r}" y2="{econ_mid + sign * dy:.1f}" '
                         f'stroke="{LINE}" stroke-width=".5" opacity=".7"/>')
        for sign in (-1, 1):
            parts.append(_text(pad_l - 6, econ_mid + sign * dy + 3,
                               f"${v / 1000:.0f}k", anchor="end",
                               size=8.5 * fs, font=BODY))
        v += grid_at
    parts.append(f'<line x1="{pad_l}" y1="{econ_mid:.1f}" x2="{width - pad_r}" '
                 f'y2="{econ_mid:.1f}" stroke="{INK}" stroke-width="1" '
                 f'opacity=".35"/>')
    if strip_h:
        parts.append(_text(pad_l - 6, strip_y + strip_h / 2 + 2, "1st kill",
                           anchor="end", size=8.5 * fs, font=BODY))
    parts.append(_text(pad_l, econ_top - 6, "Equipment brought", size=9 * fs, fill=INK,
                       weight="600", font=BODY))

    # ---- the side ribbon: one block per stretch, so the swap is a boundary
    if us_is_ct:
        i = 0
        while i < n:
            j = i
            while j + 1 < n and sides[j + 1] == sides[i]:
                j += 1
            x0 = pad_l + i * step
            x1 = pad_l + (j + 1) * step
            parts.append(f'<rect x="{x0 + 1:.1f}" y="{ribbon_y:.1f}" '
                         f'width="{x1 - x0 - 2:.1f}" height="{ribbon_h}" '
                         f'rx="2.5" fill="{FAINT}" '
                         f'opacity="{".14" if sides[i] else ".26"}"/>')
            if x1 - x0 > 34:
                parts.append(_text((x0 + x1) / 2, ribbon_y + 11,
                                   "you on CT" if sides[i] else "you on T",
                                   size=8.5 * fs, fill="var(--muted)",
                                   anchor="middle", weight="600", font=BODY))
            i = j + 1

    # ---- the score band
    span = max(3, max(abs(d) for d in diffs))

    def sy(d):
        return score_top + score_h / 2 - (d / span) * (score_h / 2 - 12)

    pts = []
    for i, d in enumerate(diffs):
        x0 = pad_l + i * step
        pts.append((x0, sy(d)))
        pts.append((x0 + step, sy(d)))
    zero = sy(0)
    area = (f'M{pts[0][0]:.1f},{zero:.1f} '
            + " ".join(f'L{x:.1f},{y:.1f}' for x, y in pts)
            + f' L{pts[-1][0]:.1f},{zero:.1f} Z')
    parts.append(f'<line x1="{pad_l}" y1="{zero:.1f}" x2="{width - pad_r}" '
                 f'y2="{zero:.1f}" stroke="{LINE}" stroke-width="1"/>')
    parts.append(f'<path d="{area}" fill="{ACCENT}" opacity=".14"/>')
    parts.append('<path d="M' + " L".join(f'{x:.1f},{y:.1f}' for x, y in pts)
                 + f'" fill="none" stroke="{ACCENT}" stroke-width="1.8" '
                   f'stroke-linejoin="round"/>')
    final = diffs[-1]
    parts.append(_text(pad_l - 6, zero + 3, "tied", anchor="end",
                       size=8.5 * fs, font=BODY))
    parts.append(_text(pad_l - 6, sy(span) + 3, f"+{span}", anchor="end",
                       size=8.5 * fs, font=BODY))
    parts.append(_text(pad_l - 6, sy(-span) + 3, f"-{span}", anchor="end",
                       size=8.5 * fs, font=BODY))
    # A halo in the card's own colour, so the final gap reads over the
    # shaded column and over the line itself. Above the line when ahead,
    # below it when behind, so it never sits on the step it labels.
    fy = sy(final) + (-8 if final >= 0 else 8 + 12 * fs * 0.7)
    parts.append(
        f'<text x="{width - pad_r:.1f}" y="{fy:.1f}" text-anchor="end" '
        f'font-size="{12 * fs:.4g}" font-family="{BODY}" font-weight="700" '
        f'fill="{ACCENT if final >= 0 else T_SIDE}" stroke="var(--surface)" '
        f'stroke-width="4" stroke-linejoin="round" paint-order="stroke">'
        f'{"+" if final > 0 else ""}{final}</text>')
    parts.append(_text(pad_l, score_top - 6, "Rounds ahead or behind",
                       size=9 * fs, fill=INK, weight="600", font=BODY))

    # ---- overtime only. The half is in the ribbon, where it is a change of
    #      colour rather than a dashed line that needs a word to explain it.
    for edge, label in ((24, "OT"), (27, ""), (30, "")):
        if edge < n:
            bx = pad_l + edge * step
            parts.append(f'<line x1="{bx:.1f}" y1="{score_top}" x2="{bx:.1f}" '
                         f'y2="{econ_top + econ_h:.1f}" stroke="{FAINT}" '
                         f'stroke-width="1" stroke-dasharray="3 4" opacity=".6"/>')
            if label:
                parts.append(_text(bx + 4, score_top + 9, label,
                                   size=8.5 * fs, font=BODY))

    legend, _ = _legend(legend_items, pad_l, axis_y + 10 + 9.5 * fs + 6,
                        width - pad_l - pad_r, 9.5 * fs)

    return (_open(width, height, "Round timeline",
                  "Top band: rounds ahead or behind. Bottom band: one bar per "
                  "round, up if you won it, height is the equipment you "
                  "brought, purple won and orange lost, with what they "
                  "brought as a grey block behind it. The grey ribbon under "
                  "the axis is the side you were on.",
                  max_w=420 if compact else None)
            + "".join(parts) + "".join(ghosts) + "".join(bars_out)
            + "".join(ticks)
            + legend + "</svg>")


def trend(points: list[tuple[str, float, str]], width: int = 680,
          height: int = 248, unit: str = "", is_pct: bool = True,
          avg: float | None = None, compact: bool = False,
          hollow=None, title: str = "Across matches, oldest to newest") -> str:
    """One measure across matches, oldest to newest.

    THE AXIS IS NUMBERS A PERSON WOULD CHOOSE. Dividing the data's own range
    into four gave 9%, 31%, 53%, 76%, 98%, which is correct and useless: the
    reader has to subtract to place a point. The range is rounded out to a
    1/2/2.5/5 interval instead, and a percentage still floors at zero.

    EVERY POINT CARRIES ITS VALUE. Labelling every other one, plus the last,
    reads from outside as a chart that lost some labels. Eleven short numbers
    fit; if a season ever gets long enough that they do not, they thin out
    evenly and the first and last are always there.

    THE AVERAGE'S LABEL IS IN THE LEGEND, not on the plot. It used to sit at
    the right-hand end of its own dashed line, which is exactly where the most
    recent match's value goes, so the two most important numbers on the chart
    printed on top of each other.

    Point colour is the result, purple won and orange lost, the same two
    colours as the W/L pills and the timeline's bars.
    """
    if len(points) < 2:
        return ""
    fs = 1.45 if compact else 1.15
    pad_l, pad_r, pad_t = (48 if compact else 46), 18, 30

    # X labels lie flat when they fit between their neighbours and turn to a
    # slant when they do not, so a label is never cut to three letters: that
    # made three Mirages read "mir" and a Nuke read "nuk".
    step = (width - pad_l - pad_r) / (len(points) - 1)
    lab_size = 9 * fs
    longest = max(len(lab) for lab, _, _ in points) * lab_size * 0.6
    slant = longest > step - 6
    drop = longest * 0.72 + 8 if slant else lab_size + 6
    legend_items = [("dash", "your average", ACCENT, False),
                    ("swatch", "match won", ACCENT, False),
                    ("swatch", "match lost", T_SIDE, False)]
    _probe, lines = _legend(legend_items, pad_l, 0, width - pad_l - pad_r,
                            9.5 * fs)
    pad_b = drop + 18 * fs + lines * (9.5 * fs + 8) + 8
    height = max(height, int(pad_t + 150 + pad_b))
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    vals = [v for _, v, _ in points]
    # The caller passes the season's own average, weighted by the rounds
    # behind each point. Falling back to the mean of the points is only for a
    # caller that has no totals to give.
    if avg is None:
        avg = sum(vals) / len(vals)

    # Headroom for the value labels that sit above each point, then rounded
    # out to a readable interval.
    pad = max(3.0, (max(vals) - min(vals)) * 0.18)
    lo, hi, ticks = _axis(min(vals) - pad, max(vals) + pad, is_pct)
    rng = hi - lo or 1

    def px(i):
        return pad_l + (i / (len(points) - 1)) * inner_w

    def py(v):
        return pad_t + inner_h - ((v - lo) / rng) * inner_h

    parts = []
    for v in ticks:
        y = py(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" stroke="{LINE}" stroke-width=".5"/>')
        parts.append(_text(pad_l - 8, y + 3, f"{v:.0f}{unit}", anchor="end",
                           size=9 * fs))

    ay = py(avg)
    parts.append(f'<line x1="{pad_l}" y1="{ay:.1f}" x2="{width - pad_r}" '
                 f'y2="{ay:.1f}" stroke="{ACCENT}" stroke-width="1" '
                 f'stroke-dasharray="4 4" opacity=".55"/>')

    path = " ".join(f'{"M" if i == 0 else "L"}{px(i):.1f},{py(v):.1f}'
                    for i, (_, v, _) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{ACCENT}" '
                 f'stroke-width="2.2" stroke-linejoin="round" '
                 f'stroke-linecap="round" opacity=".55"/>')

    # Labels thin out only if there is genuinely no room for them: about
    # thirty pixels each at this size.
    # A value label is about four characters of the bold 10pt face.
    need = 4 * 10 * fs * 0.62 + 4
    every = max(1, math.ceil(need / max(1.0, inner_w / (len(points) - 1))))
    for i, (label, v, res) in enumerate(points):
        last = i == len(points) - 1
        col = ACCENT if res == "W" else (T_SIDE if res == "L" else FAINT)
        # Hollow is a match too short to read much into, such as a
        # six-round surrender: drawn, but not as a full point.
        if hollow and i in hollow:
            parts.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="4" '
                         f'fill="var(--surface)" stroke="{col}" '
                         f'stroke-width="1.6"/>')
        else:
            parts.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" '
                         f'r="{5.5 if last else 4.5}" fill="{col}" '
                         f'stroke="var(--surface)" stroke-width="1.8"/>')
        # With labels thinned, the one before the last would sit on top of
        # the last, which is always labelled, so it gives way.
        # The highest and lowest points always keep theirs: a dip is usually
        # the match somebody is looking for.
        crowd = every > 1 and i == len(points) - 2
        extreme = v in (max(vals), min(vals))
        if last or i == 0 or extreme or (i % every == 0 and not crowd):
            # The end labels are pulled inside the plot: centred on the first
            # point, a three-character number hangs over the y-axis numbers.
            anchor = "start" if i == 0 else ("end" if last else "middle")
            dx = 6 if i == 0 else (-6 if last else 0)
            parts.append(_text(px(i) + dx, py(v) - 12, f"{v:.0f}{unit}",
                               size=10 * fs, fill=INK, anchor=anchor,
                               weight="700"))
        base = pad_t + inner_h
        if slant:
            lx, ly_ = px(i) + 3, base + 12
            parts.append(f'<text x="{lx:.1f}" y="{ly_:.1f}" text-anchor="end" '
                         f'font-size="{lab_size:.1f}" fill="{FAINT}" '
                         f'font-family="{MONO}" transform="rotate(-45 '
                         f'{lx:.1f} {ly_:.1f})">{esc(label)}</text>')
        else:
            # The first and last lean inward, or a centred label at either
            # end of the axis hangs off the drawing ("2 dust" for "2 dust2").
            end = "start" if i == 0 else ("end" if last else "middle")
            parts.append(_text(px(i), base + lab_size + 6, label,
                               size=lab_size, anchor=end))
        if res:
            parts.append(_text(px(i), base + drop + 14 * fs, res,
                               size=10 * fs, fill=col, anchor="middle",
                               weight="700"))

    parts.append(_text(pad_l, 14, "OLDEST", size=8.5 * fs, weight="600"))
    parts.append(_text(width - pad_r, 14, "NEWEST", size=8.5 * fs, anchor="end",
                       weight="600"))

    legend_items[0] = ("dash", f"your average, {avg:.0f}{unit}", ACCENT, False)
    legend, _ = _legend(legend_items, pad_l,
                        pad_t + inner_h + drop + 18 * fs + 9.5 * fs + 6,
                        width - pad_l - pad_r, 9.5 * fs)

    return (_open(width, height, title,
                  max_w=420 if compact else None)
            + "".join(parts) + legend + "</svg>")


# Read against the team's own baseline, never a global one. See the module
# note: the benchmark is always something this team did.
GOOD = "var(--good)"
BAD = "var(--bad)"

# Below this share of the spread, a value is "the same as normal" and draws
# neutral. Without a dead band every rounding wobble gets a colour and the
# page looks like it has an opinion about noise.
NEUTRAL_BAND = 0.08


def diverge(value: float, benchmark: float, spread: float,
            good_high: bool = True) -> tuple[str, float]:
    """(fill, opacity) for one value read against a benchmark.

    `spread` is the distance at which the colour saturates. Passing the
    largest gap on the page makes the strongest bar the most intense one and
    everything else proportional to it, so intensity is comparable within a
    picture and never between two pictures.
    """
    if spread <= 0:
        return FAINT, 0.30
    d = (value - benchmark) if good_high else (benchmark - value)
    t = max(-1.0, min(1.0, d / spread))
    if abs(t) < NEUTRAL_BAND:
        return FAINT, 0.30
    return (GOOD if t > 0 else BAD), 0.35 + 0.5 * abs(t)


def diverging(items: list[tuple[str, float, str]], width: int = 600,
              row_h: int = 34, unit: str = "") -> str:
    """What is gaining and what is costing, on one axis through zero.

    Leetify's "Rating Gained & Lost" is the form: categories either side of a
    baseline, so the things helping and the things hurting are one picture
    instead of two lists.

    `items` is (label, signed value, note). Positive is gaining.

    ORDERED BY SIZE, not by sign. Sorting the good ones above the bad ones
    makes two blocks and hides the ranking, and the ranking is the reading:
    the top bar is what matters most whichever way it points.

    HTML, NOT SVG. As a fixed-width SVG its labels were cut at thirty
    characters ("Practice trading the opening d...") and a phone saw one bar
    out of eight. As rows, a label wraps and every bar is on screen.
    `width` and `row_h` are accepted and ignored so old callers still work.
    """
    if not items:
        return ""
    most = max((abs(v) for _, v, _ in items), default=1) or 1
    rows = []
    for label, value, note in items:
        w = abs(value) / most * 100
        fill, op = diverge(value, 0.0, most)
        side = "gain" if value >= 0 else "cost"
        rows.append(
            f'<li><span class="dv-label">{esc(label)}</span>'
            f'<span class="dv-track {side}"><span class="dv-bar" '
            f'style="width:{max(w, 1.5):.1f}%;background:{fill};'
            f'opacity:{op:.2f}"></span></span>'
            f'<span class="dv-note">{esc(note)}</span></li>')
    return ('<div class="dv" role="figure" aria-label="What is gaining and '
            'costing you rounds, each against your own rate without it">'
            '<div class="dv-head"><span></span><span class="dv-axis">'
            '<span>costing you</span><span>earning you</span></span>'
            '<span></span></div>'
            f'<ul>{"".join(rows)}</ul></div>')


def bars(items: list[tuple[str, int, int]], width: int = 560,
         row_h: int = 36, notes: list[str] | None = None) -> str:
    """Rates, with the weight of evidence behind them drawn.

    The bar's full length is the CHANCES and the filled part is what came of
    them, so 5-of-6 and 40-of-48 are visibly different weights of evidence even
    where the percentages are close. That is the point the printed denominator
    makes, made visible.

    Labels sit above their bars, so no label is ever cut. HTML rows rather
    than a fixed-width SVG: on a phone the SVG scrolled sideways and pushed
    the "59% 78/133" off the screen, which was the only place a phone could
    see a count at all. The value now has a column of its own that is always
    in view. `width` and `row_h` are accepted and ignored.
    """
    if not items:
        return ""
    most = max((of for _, _, of in items), default=1) or 1
    rows = []
    for i, (label, hit, of) in enumerate(items):
        note = (notes[i] if notes and i < len(notes) else "") or ""
        info = (f'<span class="info" tabindex="0" role="button" '
                f'aria-describedby="hbn{i}" aria-label="What this means">i'
                f'<span class="tip" role="tooltip" id="hbn{i}">{esc(note)}'
                f'</span></span>') if note else ""
        full = of / most * 100
        got = (hit / of * 100) if of else 0
        pct = (100 * hit / of) if of else 0
        rows.append(
            f'<li><span class="hb-label">{esc(label)}{info}</span>'
            f'<span class="hb-track"><span class="hb-full" '
            f'style="width:{full:.1f}%"><span class="hb-got" '
            f'style="width:{got:.1f}%"></span></span></span>'
            f'<span class="hb-val">{pct:.0f}% <span class="hb-den">'
            f'{hit}/{of}</span></span></li>')
    return ('<ul class="hb" role="figure" aria-label="Rates, with the chances '
            f'behind them">{"".join(rows)}</ul>')


# ---- small HTML figures
#
# These take percentages already worked out by report.pct() and never compute
# one themselves. The count behind each bar is in its title, one hover away,
# like every rate() on the site.

def versus(rows: list[tuple], muted_second=True) -> str:
    """Two (or more) rates as bars on one 0-100 scale: this against that.

    Each row is (label, percentage or None, title), or with a fourth item,
    the value to print in place of the percentage, for a bar whose number is
    not a rate (the buy calls print "0.62 of 2"). The first row is the
    finding and draws in the accent; the rest are what it is read against and
    draw neutral, so the eye goes to the gap.
    """
    if not rows:
        return ""
    out = []
    for i, row in enumerate(rows):
        label, pct, title = row[:3]
        shown = row[3] if len(row) > 3 else None
        cls = "vs-row" + (" base" if i and muted_second else "")
        if pct is None:
            bar, val = "", "&ndash;"
        else:
            bar = f'<span class="vs-fill" style="width:{pct:.1f}%"></span>'
            val = esc(shown) if shown is not None else f"{pct:.0f}%"
        out.append(f'<div class="{cls}" title="{esc(title)}">'
                   f'<span class="vs-lab">{esc(label)}</span>'
                   f'<span class="vs-track">{bar}</span>'
                   f'<span class="vs-val">{val}</span></div>')
    return f'<div class="vs" role="figure">{"".join(out)}</div>'


def first_deaths(rows: list[dict]) -> str:
    """Where the first of you dies, and how much of it gets traded.

    Each row: {"side", "place", "map", "share", "traded", "won", "title",
    "traded_title", "won_title"}. `share` is the percentage of your rounds on
    that map and side where the first death was here; the bar is drawn to
    the largest share on the list so the places can be told apart. Inside
    it, the traded part is the accent and the untraded part is the warning
    colour, because untraded is the 4 against 5.
    """
    if not rows:
        return ""
    most = max((r["share"] or 0) for r in rows) or 1
    out = []
    for r in rows:
        w = (r["share"] or 0) / most * 100
        tr = r["traded"] or 0
        out.append(
            f'<li><span class="fd-place"><span class="pill {r["side"]}">'
            f'{r["side"].upper()}</span> {esc(r["place"])} '
            f'<span class="den">{esc(r["map"])}</span></span>'
            f'<span class="fd-track" title="{esc(r["title"])}">'
            f'<span class="fd-bar" style="width:{w:.1f}%">'
            f'<span class="fd-traded" style="width:{tr:.1f}%"></span></span></span>'
            f'<span class="fd-val" title="{esc(r["title"])}">{r["share"]:.0f}%</span>'
            f'<span class="fd-sub den"><span title="{esc(r["traded_title"])}">'
            f'{tr:.0f}% traded</span> &middot; <span title="{esc(r["won_title"])}">'
            f'{(r["won"] or 0):.0f}% of those rounds won</span></span></li>')
    return ('<div class="fd"><ul>' + "".join(out) + '</ul>'
            '<p class="fd-key den"><span class="sw traded"></span>traded '
            '<span class="sw untraded"></span>not traded</p></div>')


def sides(rows: list[dict]) -> str:
    """Rounds won by map, CT and T side by side.

    Each row: {"map", "chip", "matches", "all", "all_title", "ct", "ct_title",
    "t", "t_title"}; percentages from report.pct(). A faint mark at 50% so a
    side above or below even reads without a number.
    """
    if not rows:
        return ""
    out = []
    for r in rows:
        bars = []
        for sd in ("ct", "t"):
            v = r[sd]
            fill = (f'<span class="sd-fill {sd}" style="width:{v:.1f}%"></span>'
                    if v is not None else "")
            val = f"{v:.0f}%" if v is not None else "&ndash;"
            bars.append(f'<span class="sd-side" title="{esc(r[sd + "_title"])}">'
                        f'<span class="sd-lab">{sd.upper()}</span>'
                        f'<span class="sd-track">{fill}</span>'
                        f'<span class="sd-val">{val}</span></span>')
        tot = f'{r["all"]:.0f}%' if r["all"] is not None else "&ndash;"
        out.append(
            f'<li><span class="sd-map">{r["chip"]}'
            f'<span class="den">{r["matches"]} match'
            f'{"es" if r["matches"] != 1 else ""} &middot; '
            f'<span title="{esc(r["all_title"])}">{tot} won</span></span></span>'
            f'<span class="sd-bars">{"".join(bars)}</span></li>')
    return f'<ul class="sd">{"".join(out)}</ul>'
