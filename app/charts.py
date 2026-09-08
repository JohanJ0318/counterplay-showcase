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


def _swatch(x, y, label, fill, hollow=False):
    box = (f'<rect x="{x:.1f}" y="{y - 7:.1f}" width="9" height="9" rx="2" '
           + (f'fill="none" stroke="{fill}" stroke-width="1.5"/>' if hollow
              else f'fill="{fill}" opacity=".88"/>'))
    return box + _text(x + 14, y, label, size=9.5, font=BODY)


def round_timeline(rows: list[dict], us_is_ct, width: int = 1040) -> str:
    """The shape of a match, in two stacked bands sharing one axis of rounds.

    The first attempt drew the economy bars and the score line on top of each
    other, which made the score a grey thread crossing twenty-nine bars and
    readable as neither. They are two different quantities, so they get two
    bands:

      SCORE      a stepped area — how far ahead or behind you were, filled, so
                 a comeback reads as a shape rather than as a line to trace
      ECONOMY    a bar per round, up if won and down if lost, as tall as the
                 equipment brought, coloured by the side you were on

    Sharing one x-axis is the point: "we lost three full buys in a row and the
    score fell away" should read as one sentence, not two charts.

    `us_is_ct` maps a round number to whether this team was CT, or is None when
    the side cannot be established — then it is drawn from the CT side.
    """
    if not rows:
        return ""

    pad_l, pad_r, pad_t = 48, 18, 20
    score_h, econ_h, gap, axis_h, legend_h = 76, 134, 20, 20, 26
    height = pad_t + score_h + gap + econ_h + axis_h + legend_h
    n = len(rows)
    inner = width - pad_l - pad_r
    step = inner / n
    bar_w = max(4.0, min(20.0, step * 0.6))

    score_top = pad_t
    score_bot = pad_t + score_h
    econ_mid = score_bot + gap + econ_h / 2
    econ_half = econ_h / 2 - 8
    axis_y = score_bot + gap + econ_h + 13

    peak = max((max(r["equip_ct"], r["equip_t"]) for r in rows), default=1) or 1
    grid_at = 10000 if peak > 22000 else 5000

    parts, bars_out, ticks = [], [], []
    us = them = 0
    diffs = []

    for i, r in enumerate(rows):
        ct = us_is_ct(r["round_num"]) if us_is_ct else True
        won = bool(r["ct_won"]) == ct
        equip = r["equip_ct"] if ct else r["equip_t"]
        buy = r["buy_ct"] if ct else r["buy_t"]

        h = max(5.0, (equip / peak) * econ_half)
        x = pad_l + i * step + (step - bar_w) / 2
        y = econ_mid - h if won else econ_mid
        fill = CT if ct else T_SIDE
        hollow = buy in ("eco", "pistol")
        style = (f'fill="none" stroke="{fill}" stroke-width="1.4" opacity=".9"'
                 if hollow else f'fill="{fill}" opacity=".85"')
        bars_out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                        f'height="{h:.1f}" rx="1.5" {style}></rect>')

        us += won
        them += not won
        diffs.append(us - them)

        every = 1 if n <= 15 else (2 if n <= 30 else 5)
        if r["round_num"] % every == 0 or i == 0:
            ticks.append(_text(pad_l + i * step + step / 2, axis_y,
                               r["round_num"], anchor="middle"))

    # ---- economy grid, so bar height means something in money
    for v in range(grid_at, int(peak) + 1, grid_at):
        dy = (v / peak) * econ_half
        for sign in (-1, 1):
            parts.append(f'<line x1="{pad_l}" y1="{econ_mid + sign * dy:.1f}" '
                         f'x2="{width - pad_r}" y2="{econ_mid + sign * dy:.1f}" '
                         f'stroke="{LINE}" stroke-width=".5" opacity=".7"/>')
        parts.append(_text(pad_l - 6, econ_mid - dy + 3, f"${v // 1000}k",
                           anchor="end"))
    parts.append(f'<line x1="{pad_l}" y1="{econ_mid:.1f}" x2="{width - pad_r}" '
                 f'y2="{econ_mid:.1f}" stroke="{INK}" stroke-width="1" '
                 f'opacity=".35"/>')
    parts.append(_text(pad_l - 6, econ_mid - econ_half - 3, "won", anchor="end"))
    parts.append(_text(pad_l - 6, econ_mid + econ_half + 9, "lost", anchor="end"))

    # ---- the score band, as a filled step
    span = max(3, max(abs(d) for d in diffs))

    def sy(d):
        return score_top + score_h / 2 - (d / span) * (score_h / 2 - 10)

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
    parts.append(_text(pad_l - 6, zero + 3, "level", anchor="end"))
    parts.append(_text(pad_l - 6, sy(span) + 3, f"+{span}", anchor="end"))
    parts.append(_text(pad_l - 6, sy(-span) + 3, f"-{span}", anchor="end"))
    parts.append(_text(width - pad_r, sy(final) - 8,
                       f'{"+" if final > 0 else ""}{final}',
                       size=11.5, fill=ACCENT, anchor="end", weight="700"))
    parts.append(_text(pad_l, score_top - 6, "SCORE — AHEAD OR BEHIND",
                       size=8.5, weight="600"))

    # ---- half and overtime
    for edge, label in ((12, "half"), (24, "OT"), (27, ""), (30, "")):
        if edge < n:
            bx = pad_l + edge * step
            parts.append(f'<line x1="{bx:.1f}" y1="{score_top}" x2="{bx:.1f}" '
                         f'y2="{score_bot + gap + econ_h}" stroke="{FAINT}" '
                         f'stroke-width="1" stroke-dasharray="3 4" opacity=".6"/>')
            if label:
                parts.append(_text(bx + 4, score_top + 9, label, size=8.5))

    parts.append(_text(pad_l, score_bot + gap - 6,
                       "EQUIPMENT BROUGHT, AND WHO TOOK THE ROUND",
                       size=8.5, weight="600"))

    # ---- the legend whose absence made the first version unreadable
    ly = height - 8
    legend = (_swatch(pad_l, ly, "you on CT", CT)
              + _swatch(pad_l + 100, ly, "you on T", T_SIDE)
              + _swatch(pad_l + 192, ly, "eco or pistol", CT, hollow=True)
              + _text(pad_l + 300, ly, "bar up = round won,  down = lost",
                      size=9.5, font=BODY))

    return (_open(width, height, "Round timeline",
                  "Top band: how far ahead or behind the score was. Bottom "
                  "band: one bar per round, up if won, height is equipment "
                  "brought, colour is the side you were on.")
            + "".join(parts) + "".join(bars_out) + "".join(ticks)
            + legend + "</svg>")


def trend(points: list[tuple[str, float, str]], width: int = 760,
          height: int = 236, unit: str = "", is_pct: bool = True) -> str:
    """One measure across matches, oldest to newest.

    Two things the first version got wrong. It padded its range symmetrically
    and drew a deaths-traded axis down to -6%, a number that cannot exist — a
    percentage now floors at zero and caps at a hundred. And it cut each label
    to three characters, so three separate Mirages all read "mir"; the caller
    now passes a label that distinguishes them.

    Point colour is the match result, so a run of losses is visible without
    reading the axis.
    """
    if len(points) < 2:
        return ""
    pad_l, pad_r, pad_t, pad_b = 46, 22, 28, 46
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    vals = [v for _, v, _ in points]
    avg = sum(vals) / len(vals)

    hi, lo = max(vals), min(vals)
    headroom = max(4.0, (hi - lo) * 0.25)
    hi = min(100.0, hi + headroom) if is_pct else hi + headroom
    lo = max(0.0, lo - headroom) if is_pct else lo - headroom
    if hi - lo < 1:
        hi, lo = hi + 1, max(0.0, lo - 1)
    rng = hi - lo

    def px(i):
        return pad_l + (i / (len(points) - 1)) * inner_w

    def py(v):
        return pad_t + inner_h - ((v - lo) / rng) * inner_h

    parts = []
    for k in range(5):
        v = lo + (rng * k / 4)
        y = py(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" stroke="{LINE}" stroke-width=".5"/>')
        parts.append(_text(pad_l - 8, y + 3, f"{v:.0f}{unit}", anchor="end"))

    ay = py(avg)
    parts.append(f'<line x1="{pad_l}" y1="{ay:.1f}" x2="{width - pad_r}" '
                 f'y2="{ay:.1f}" stroke="{ACCENT}" stroke-width="1" '
                 f'stroke-dasharray="4 4" opacity=".6"/>')
    parts.append(_text(width - pad_r, ay - 6, f"average {avg:.0f}{unit}",
                       size=9, fill=ACCENT, anchor="end"))

    path = " ".join(f'{"M" if i == 0 else "L"}{px(i):.1f},{py(v):.1f}'
                    for i, (_, v, _) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{ACCENT}" '
                 f'stroke-width="2.2" stroke-linejoin="round" '
                 f'stroke-linecap="round"/>')

    show_every = 1 if len(points) <= 8 else 2
    for i, (label, v, res) in enumerate(points):
        last = i == len(points) - 1
        col = CT if res == "W" else (T_SIDE if res == "L" else ACCENT)
        parts.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" '
                     f'r="{5 if last else 4}" fill="{col}" '
                     f'stroke="var(--surface)" stroke-width="1.8"/>')
        if last or i % show_every == 0:
            parts.append(_text(px(i), py(v) - 12, f"{v:.0f}{unit}",
                               size=9.5, fill=INK, anchor="middle",
                               weight="700"))
        parts.append(_text(px(i), height - 24, label, size=8.5,
                           anchor="middle"))
        if res:
            parts.append(_text(px(i), height - 11, res, size=9.5, fill=col,
                               anchor="middle", weight="700"))

    parts.append(_text(pad_l, 13, "OLDEST", size=8.5, weight="600"))
    parts.append(_text(width - pad_r, 13, "NEWEST", size=8.5, anchor="end",
                       weight="600"))

    return (_open(width, height, "Across matches, oldest to newest")
            + "".join(parts) + "</svg>")


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
