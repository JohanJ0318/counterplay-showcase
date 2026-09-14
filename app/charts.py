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


def _open(width: int, height: int, title: str, desc: str = "") -> str:
    # min-width is the chart's own width, so a narrow screen scrolls the
    # container instead of shrinking the picture. Without it the SVG obeys
    # width:100%, renders at 289px on a phone, and takes 8.5px labels down to
    # 2.4 — legible to nobody, on the device coaches actually use.
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'style="max-width:{width}px;min-width:{width}px;height:auto;'
            f'display:block" '
            f'role="img" aria-label="{esc(title)}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<title>{esc(title)}</title>'
            + (f'<desc>{esc(desc)}</desc>' if desc else ''))


def _text(x, y, s, size=9, fill=FAINT, anchor="start", font=MONO, weight=None):
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{size}" fill="{fill}" font-family="{font}"{w}>'
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


def _swatch(x, y, label, fill, hollow=False):
    box = (f'<rect x="{x:.1f}" y="{y - 7:.1f}" width="9" height="9" rx="2" '
           + (f'fill="none" stroke="{fill}" stroke-width="1.5"/>' if hollow
              else f'fill="{fill}" opacity=".88"/>'))
    return box + _text(x + 14, y, label, size=9.5, font=BODY)


def round_timeline(rows: list[dict], us_is_ct, width: int = 680) -> str:
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
    """
    if not rows:
        return ""

    pad_l, pad_r, pad_t = 44, 14, 22
    score_h, gap, econ_h = 84, 16, 132
    ribbon_h, axis_h, legend_h = 15, 20, 26
    height = (pad_t + score_h + gap + econ_h + ribbon_h + axis_h + legend_h)
    n = len(rows)
    inner = width - pad_l - pad_r
    step = inner / n
    bar_w = max(3.5, min(18.0, step * 0.62))

    score_top = pad_t
    score_bot = pad_t + score_h
    econ_top = score_bot + gap
    econ_mid = econ_top + econ_h / 2
    econ_half = econ_h / 2 - 9
    ribbon_y = econ_top + econ_h + 4
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

    parts, bars_out, ticks = [], [], []
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

        us += won
        them += not won
        diffs.append(us - them)

        if r["round_num"] in want:
            ticks.append(_text(pad_l + i * step + step / 2, axis_y,
                               r["round_num"], anchor="middle", size=9))

    # ---- money grid, so a bar's height is a number and not an impression
    v = grid_at
    while v <= peak:
        dy = (v / peak) * econ_half
        for sign in (-1, 1):
            parts.append(f'<line x1="{pad_l}" y1="{econ_mid + sign * dy:.1f}" '
                         f'x2="{width - pad_r}" y2="{econ_mid + sign * dy:.1f}" '
                         f'stroke="{LINE}" stroke-width=".5" opacity=".7"/>')
        parts.append(_text(pad_l - 6, econ_mid - dy + 3,
                           f"${v / 1000:.0f}k", anchor="end", size=8.5))
        v += grid_at
    parts.append(f'<line x1="{pad_l}" y1="{econ_mid:.1f}" x2="{width - pad_r}" '
                 f'y2="{econ_mid:.1f}" stroke="{INK}" stroke-width="1" '
                 f'opacity=".35"/>')
    parts.append(_text(pad_l, econ_top - 6, "EQUIPMENT BROUGHT",
                       size=8.5, weight="600"))

    # ---- the side ribbon: one block per stretch, so the swap is a boundary
    if us_is_ct:
        i = 0
        while i < n:
            j = i
            while j + 1 < n and sides[j + 1] == sides[i]:
                j += 1
            x0 = pad_l + i * step
            x1 = pad_l + (j + 1) * step
            col = CT if sides[i] else T_SIDE
            parts.append(f'<rect x="{x0:.1f}" y="{ribbon_y:.1f}" '
                         f'width="{x1 - x0:.1f}" height="{ribbon_h}" rx="2.5" '
                         f'fill="{col}" opacity=".16"/>')
            if x1 - x0 > 34:
                parts.append(_text((x0 + x1) / 2, ribbon_y + 11,
                                   "you on CT" if sides[i] else "you on T",
                                   size=8.5, fill=col, anchor="middle",
                                   weight="700"))
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
    parts.append(_text(pad_l - 6, zero + 3, "level", anchor="end", size=8.5))
    parts.append(_text(pad_l - 6, sy(span) + 3, f"+{span}", anchor="end",
                       size=8.5))
    parts.append(_text(pad_l - 6, sy(-span) + 3, f"-{span}", anchor="end",
                       size=8.5))
    parts.append(_text(width - pad_r, sy(final) - 9,
                       f'{"+" if final > 0 else ""}{final}',
                       size=12, fill=ACCENT if final >= 0 else T_SIDE,
                       anchor="end", weight="700"))
    parts.append(_text(pad_l, score_top - 6, "ROUNDS AHEAD OR BEHIND",
                       size=8.5, weight="600"))

    # ---- overtime only. The half is in the ribbon, where it is a change of
    #      colour rather than a dashed line that needs a word to explain it.
    for edge, label in ((24, "OT"), (27, ""), (30, "")):
        if edge < n:
            bx = pad_l + edge * step
            parts.append(f'<line x1="{bx:.1f}" y1="{score_top}" x2="{bx:.1f}" '
                         f'y2="{econ_top + econ_h:.1f}" stroke="{FAINT}" '
                         f'stroke-width="1" stroke-dasharray="3 4" opacity=".6"/>')
            if label:
                parts.append(_text(bx + 4, score_top + 9, label, size=8.5))

    ly = height - 8
    legend = (_swatch(pad_l, ly, "round won", ACCENT)
              + _swatch(pad_l + 108, ly, "round lost", T_SIDE)
              + _swatch(pad_l + 220, ly, "eco or pistol", ACCENT, hollow=True)
              + _text(pad_l + 330, ly, "bar height = equipment brought",
                      size=9.5, font=BODY))

    return (_open(width, height, "Round timeline",
                  "Top band: rounds ahead or behind. Bottom band: one bar per "
                  "round, up if you won it, height is the equipment you "
                  "brought, purple won and orange lost. The ribbon under the "
                  "axis is the side you were on.")
            + "".join(parts) + "".join(bars_out) + "".join(ticks)
            + legend + "</svg>")


def trend(points: list[tuple[str, float, str]], width: int = 680,
          height: int = 248, unit: str = "", is_pct: bool = True,
          avg: float | None = None) -> str:
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
    pad_l, pad_r, pad_t, pad_b = 46, 18, 30, 58
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
                           size=9))

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
    every = max(1, int(round(30.0 / max(1.0, inner_w / (len(points) - 1)))))
    for i, (label, v, res) in enumerate(points):
        last = i == len(points) - 1
        col = ACCENT if res == "W" else (T_SIDE if res == "L" else FAINT)
        parts.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" '
                     f'r="{5.5 if last else 4.5}" fill="{col}" '
                     f'stroke="var(--surface)" stroke-width="1.8"/>')
        if last or i == 0 or i % every == 0:
            # The end labels are pulled inside the plot: centred on the first
            # point, a three-character number hangs over the y-axis numbers.
            anchor = "start" if i == 0 else ("end" if last else "middle")
            dx = 6 if i == 0 else (-6 if last else 0)
            parts.append(_text(px(i) + dx, py(v) - 12, f"{v:.0f}{unit}",
                               size=10, fill=INK, anchor=anchor,
                               weight="700"))
        parts.append(_text(px(i), height - 34, label, size=9,
                           anchor="middle"))
        if res:
            parts.append(_text(px(i), height - 22, res, size=10, fill=col,
                               anchor="middle", weight="700"))

    parts.append(_text(pad_l, 14, "OLDEST", size=8.5, weight="600"))
    parts.append(_text(width - pad_r, 14, "NEWEST", size=8.5, anchor="end",
                       weight="600"))

    ly = height - 6
    legend = (f'<line x1="{pad_l}" y1="{ly - 4:.1f}" x2="{pad_l + 20}" '
              f'y2="{ly - 4:.1f}" stroke="{ACCENT}" stroke-width="1.4" '
              f'stroke-dasharray="4 4" opacity=".7"/>'
              + _text(pad_l + 26, ly, f"your average, {avg:.0f}{unit}",
                      size=9.5, font=BODY)
              + _swatch(pad_l + 170, ly, "match won", ACCENT)
              + _swatch(pad_l + 272, ly, "match lost", T_SIDE))

    return (_open(width, height, "Across matches, oldest to newest")
            + "".join(parts) + legend + "</svg>")


def bars(items: list[tuple[str, int, int]], width: int = 560,
         row_h: int = 36) -> str:
    """Rates, with the weight of evidence behind them drawn.

    The bar's full length is the CHANCES and the filled part is what came of
    them, so 5-of-6 and 40-of-48 are visibly different weights of evidence even
    where the percentages are close. That is the point the printed denominator
    makes, made visible.

    Labels sit above their bars rather than beside them. Beside them, at any
    sane label-column width, "You win the round after winning the opening duel"
    became "You win the round after w" — and a chart that cuts its own labels
    in half is worse than the table it replaced.
    """
    if not items:
        return ""
    right = 74
    height = len(items) * row_h + 12
    inner = width - right
    most = max((of for _, _, of in items), default=1) or 1
    out = []
    for i, (label, hit, of) in enumerate(items):
        y = 8 + i * row_h
        full = (of / most) * inner
        got = (hit / most) * inner if of else 0
        pct = (100 * hit / of) if of else 0
        out.append(
            _text(0, y + 8, label, size=10.5, fill=INK, font=BODY)
            + f'<rect x="0" y="{y + 15}" width="{full:.1f}" height="10" '
              f'rx="2" fill="{LINE}"></rect>'
              f'<rect x="0" y="{y + 15}" width="{got:.1f}" height="10" '
              f'rx="2" fill="{ACCENT}" opacity=".9"></rect>'
            + _text(full + 8, y + 24, f"{pct:.0f}%  {hit}/{of}", size=9.5))
    return (_open(width, height, "Rates, with the chances behind them")
            + "".join(out) + "</svg>")
