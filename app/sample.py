"""The sample report, rendered in the product's own components.

    /sample-report

This is the page a coach opens from "See a real report" before they trust
anything, so it has one job: look exactly like what they will get. It is built
from `theme.CSS` and the same helpers every real page uses - `report.rate` for
every figure, `theme.map_chip` for every map, `charts.bars` for the chart, the
`info`/`tip` disclosure for every explanation - so changing the product's look
changes this with it.

It still drifted, because looking right is not the same as showing the right
things. The product grew a "What to work on" section that now opens the team
stats page, a utility section counted per grenade, three positional tables read
out of the position samples with the map drawn beside them, and a traded column
on first deaths. None of that was here. Meanwhile this page was still
advertising a same-server comparison table and a decision-scoring section, and
neither exists: the first was never built, and the second is the thing the
landing page stopped promising for exactly this reason.

So the sections below are the sections of `/stats`, in the order `/stats` puts
them, and the two fictions are gone.

The numbers are invented and the page says so at the top. Everything else - the
denominator under every rate, the round counts, the refusal to print a
percentage under `report.MIN_CHANCES` chances - is the real format, because the
format is what is being previewed.
"""
from __future__ import annotations

from . import charts
from .movement import COMMIT_TO, SETUP_AT
from .report import MIN_CHANCES, MIN_PATTERN_CHANCES, PATTERNS, buy_pattern, rate
from .theme import banner, esc, map_chip, page
from .utility import FLASH_ROUND_PATTERN

# The fictional team. Named so nobody mistakes it for a real program.
TEAM = "Northlake University"
LEAGUE = "NECC Fall 2026"
DEMOS, ROUNDS, MAPS = 6, 148, 3
BASELINE = 48

# The maps are real ones and the places named in the positional tables are real
# zone names, so the drawings beside those tables label the same spots the rows
# are talking about. The team is the only invention.
COVERAGE = [
    ("2026-09-09", "de_mirage", "NECC wk1", "Lakeshore College"),
    ("2026-09-16", "de_inferno", "NECC wk2", "Ashford University"),
    ("2026-09-16", "de_mirage", "NECC wk2", "Ashford University"),
    ("2026-09-23", "de_nuke", "NECC wk3", "Pinebluff State"),
    ("2026-09-30", "de_inferno", "NECC wk4", "Granite Valley"),
    ("2026-09-30", "de_mirage", "NECC wk4", "Granite Valley"),
]

# ------------------------------------------------------------ what to work on
#
# The shape `advice.monday` produces: a conclusion, the reasoning, the counted
# facts it was drawn from, and a closing line putting it against the team's own
# average. Grouped by map, because practice is planned one map at a time.
#
# (good, side, do, because, evidence, closing line)
ADVICE = [
    ("", [
        (False, None, "Practice trading the opening duel",
         "Losing the first duel is normal. Losing the round almost every time "
         "you lose it is not. It means the second player is too far away to "
         "punish the trade, which is a spacing problem you can run in practice "
         "rather than an aim problem you cannot.",
         ["You win 19 of 71 rounds after losing the opening duel"],
         "27% against your 48% overall, a gap of 21 points across 71 rounds"),
        (False, None, "Fix who your flashes land on",
         "63% of the flashes you throw blind someone on your own side. A flash "
         "that blinds your entry is worse than no flash: the site is still "
         "held and the man going in cannot see it. This is a pop-flash and a "
         "timing problem, and it is fixed in practice rather than in a match.",
         ["91 of 144 flashes blinded a teammate or the thrower, for 249 "
          "seconds against 383 seconds of the opposition"],
         "You win 27 of the 58 rounds it happens in (47%), against 48% overall"),
    ]),
    ("mirage", [
        (True, "ct", "Keep the A default setup",
         "The strongest position you have on this map, and you use it in 8 "
         "rounds of 32. A 30-point edge you take that rarely is worth a "
         "conversation about why it is the exception.",
         ["Held in 8 of 32 CT rounds; you win 7 of those 8"], None),
        (False, "t", "Change how you take top mid",
         "When the first of you dies in top mid as T, the round is usually "
         "already gone. At that rate it is not bad luck. It is the same duel "
         "taken the same way.",
         ["First death in top mid in 8 of 31 T rounds; you win 2 of those 8"],
         None),
    ]),
]

FORM = [("W", "13&ndash;9", "mirage"), ("L", "8&ndash;13", "mirage"),
        ("W", "13&ndash;11", "inferno"), ("L", "6&ndash;13", "nuke"),
        ("L", "10&ndash;13", "inferno")]

# ---------------------------------------------------------------- patterns
#
# Names and explanations come from the product's own constants rather than
# being retyped here, so a reworded pattern reaches this page on the same
# deploy it reaches the real one.
PATTERN_COUNTS = [
    (FLASH_ROUND_PATTERN, 48, 84),
    (buy_pattern("full"), 45, 79),
    (PATTERNS["opening_won"], 52, 77),
    (PATTERNS["ct"], 41, 76),
    (PATTERNS["t"], 30, 72),
    (PATTERNS["opening_lost"], 19, 71),
    (buy_pattern("force"), 14, 41),
    (buy_pattern("pistol"), 5, 12),
    (buy_pattern("eco"), 1, 8),
]

# ---------------------------------------------------------------- utility
#
# Outcome, not activity: what the grenades achieved, counted per grenade. A
# coach cannot act on "you threw 144 flashes".
UTILITY = [
    ("61%", "of your flashes blind an opponent", "88 of 144 thrown",
     "Counted per flash, not per player blinded: one flashbang blinds everyone "
     "who can see it. Those 88 flashes took 383 seconds of sight off the "
     "opposition. 91 of your flashes also blinded your own side, for 249 "
     "seconds."),
    ("9%", "of your flashes get somebody killed", "13 of 144 thrown",
     "An opponent this flash blinded, who then died before it wore off. 14 "
     "opponents in all. This is the only reason to throw one, and it is a long "
     "way below the share that merely land."),
    ("26%", "of your molotovs deny space", "34 of 131 thrown",
     "A molotov an opponent had to stand in, walk out of, or go round, read "
     "from the position samples. Between them they took 71 seconds of ground "
     "away, and 17 pushed somebody back out of it. The other 97 burned with "
     "nobody near them at any point."),
    ("$780", "of utility wasted per round", "$115,400 of $402,000 bought",
     "Grenades still in a hand at the moment its owner died, priced at what "
     "they cost. Grenades a survivor kept are not counted: carrying a smoke "
     "into the next round is not waste. Across 148 rounds that is 402 grenades "
     "that bought nothing."),
]
SMOKE_LINE = ("An opponent walked through 52 of your 161 smokes. The other 109 "
              "nobody crossed while they were up &ndash; which is not the same "
              "as nobody wanting to.")

# ---------------------------------------------------------------- positions
#
# (side, map, zone, rounds it happened in, rounds of that map and side,
#  traded or None, rounds won of those it happened in, sub-line)
POSITIONS = {
    "commit": [
        ("t", "de_mirage", "A main", 14, 31, None, 4, "usually by 5s"),
        ("t", "de_inferno", "T ramp", 11, 25, None, 5, "usually by 7s"),
        ("ct", "de_nuke", "Ramp", 9, 18, None, 6, "usually by 6s"),
        ("t", "de_nuke", "lobby", 7, 16, None, 2, "usually by 5s"),
        ("t", "de_mirage", "top mid", 5, 31, None, 1, "usually by 8s"),
    ],
    "setup": [
        ("t", "de_inferno", "T ramp", 19, 25, None, 11, "2.9 players on average"),
        ("t", "de_mirage", "A main", 17, 31, None, 7, "3.7 players on average"),
        ("ct", "de_nuke", "Ramp", 12, 18, None, 9, "2.1 players on average"),
        ("ct", "de_mirage", "A default", 8, 32, None, 7, "2.4 players on average"),
        ("t", "de_nuke", "Trophy", 7, 16, None, 3, "3.0 players on average"),
    ],
    "death": [
        ("t", "de_mirage", "A main", 10, 31, 3, 3, ""),
        ("ct", "de_inferno", "Banana", 8, 26, 5, 4, ""),
        ("t", "de_mirage", "top mid", 8, 31, 2, 2, ""),
        ("ct", "de_nuke", "Ramp", 6, 18, 4, 4, ""),
        ("t", "de_inferno", "T ramp", 6, 25, 1, 1, ""),
    ],
}
POS_SECTIONS = (
    ("commit", "Where your group ends up",
     "The furthest three of you get together and hold, inside the first "
     f"{int(COMMIT_TO)} seconds. Corridors everyone walks through are not "
     "destinations, so they only appear here when the group never got past "
     "them, which is itself worth seeing.", 3),
    ("setup", "Your default setup",
     f"Where two or more of you are standing {int(SETUP_AT)} seconds in: after "
     "the round has taken shape, before contact decides it.", 4),
    ("death", "Where your first death happens",
     "The first of you to die, where, and whether anybody got him back. The "
     "same death traded leaves a 4v4 and untraded leaves a 4v5, which is the "
     "difference between a place you lose men and a place you lose rounds.", 6),
)

# --------------------------------------------------------- map pool and buys
# (map, matches, rounds won, of rounds, CT won, of CT, T won, of T)
MAP_POOL = [
    ("de_mirage", 3, 34, 63, 20, 32, 14, 31),
    ("de_inferno", 2, 24, 51, 13, 26, 11, 25),
    ("de_nuke", 1, 13, 34, 8, 18, 5, 16),
]
SIDES = [("ct", 41, 76), ("t", 30, 72)]
BUYS = [("full", 45, 79), ("force", 14, 41), ("pistol", 5, 12), ("eco", 1, 8)]

# (name, role, opening duels won, of, rounds with an AWP, of, spots)
PLAYERS = [
    ("Player A", "IGL", 21, 62, 2, 148,
     [("mirage &middot; CT", "B bench", "19 / 32"),
      ("mirage &middot; T", "Second through palace", "16 / 31")]),
    ("Player B", "AWP", 34, 61, 96, 148,
     [("mirage &middot; CT", "A ramp angle from CT", "22 / 32"),
      ("inferno &middot; CT", "Banana from car", "17 / 26")]),
    ("Player C", "Entry", 29, 66, 1, 148,
     [("mirage &middot; T", "First through palace", "20 / 31")]),
    ("Player D", "Rifle", 4, 12, 0, 148,
     [("nuke &middot; CT", "Heaven", "6 / 18")]),
]
ROLE_CLASS = {"AWP": "role awp", "Entry": "role entry"}

NOT_CLAIMED = [
    ("No predictions.",
     "Nothing here says what anyone will do next match. It says what happened, "
     "how often, and out of how many chances."),
    ("No comparison to other teams.",
     "You are not scored against professional or matchmaking players. Those "
     "baselines exist and they do not describe your league, so they are off."),
    (f"Anything under {MIN_CHANCES} chances shows its raw count.",
     "No percentage, and the row says so. A rate off four rounds is noise "
     "wearing a percent sign."),
    ("Every figure is auditable.",
     "The rounds behind a claim are printed so you can open the demo and check "
     "it yourself. If a line is wrong, it is wrong in a way you can see."),
]


def _info(tid: str, text: str) -> str:
    """The hover disclosure the product puts behind every explanation."""
    return (f'<span class="info" tabindex="0" role="button"'
            f' aria-describedby="{tid}" aria-label="What this means">i'
            f'<span class="tip" role="tooltip" id="{tid}">{esc(text)}</span>'
            f'</span>')


def render(user=None, pictures=None) -> str:
    """`pictures` is main.zone_pictures, handed in rather than imported.

    It reads the stored zone models, which live behind the app, and importing
    it here would make this module and main.py import each other. The page
    renders without it, which is also what a fresh install does before anybody
    has named that map's zones.
    """
    # ---- what to work on
    groups = []
    for mp, items in ADVICE:
        cards = []
        for good, side, do, because, evidence, foot in items:
            tag = "keep doing this" if good else "worth changing"
            ev = "".join(f"<li>{esc(e)}</li>" for e in evidence)
            pill = f'<span class="pill {side}">{side.upper()}</span>' if side else ""
            cards.append(
                f'<div class="card advice{" good" if good else ""}">'
                f'<div style="display:flex;gap:9px;align-items:center;'
                f'flex-wrap:wrap"><span class="pill {"on" if good else "t"}">'
                f'{tag}</span>{pill}</div><h3>{esc(do)}</h3>'
                f'<p class="lede">{esc(because)}</p>'
                f'<ul class="den" style="margin:0;padding-left:17px">{ev}</ul>'
                f'<p class="den">{esc(foot) if foot else ""}</p></div>')
        head = (f'<div class="sec-head"><span class="label">'
                f'{"On " + esc(mp) if mp else "Across every map"}</span>'
                f'<h3>{len(items)} things to work on</h3></div>')
        groups.append(f'<div style="margin-bottom:22px">{head}'
                      f'<div class="grid2">{"".join(cards)}</div></div>')

    # ---- recent form
    #
    # Spans, not links: in a real report each of these opens that match. There
    # is nothing behind them here, and a link that goes nowhere is worse than
    # no link.
    form = "".join(
        f'<span class="formcard">'
        f'<span class="res {"win" if r == "W" else "loss"}">{r}</span>'
        f'<span class="mono">{sc}</span>'
        f'<span class="den">{esc(mp)}</span></span>'
        for r, sc, mp in FORM)

    # ---- recurring patterns
    prows = "".join(
        f'<tr><td class="name">{esc(name)}{_info(f"pt{i}", detail)}</td>'
        f'<td class="num">{rate(hit, of)}</td></tr>'
        for i, ((name, detail), hit, of) in enumerate(PATTERN_COUNTS))
    chart = charts.bars([(n, hit, of) for (n, _detail), hit, of in PATTERN_COUNTS],
                        width=600)

    # ---- utility
    ucards = "".join(
        f'<div class="stat"><span class="stat-n">{big}</span>'
        f'<span class="label">{esc(label)}{_info(f"ut{i}", tip)}</span>'
        f'<span class="den">{esc(den)}</span></div>'
        for i, (big, label, den, tip) in enumerate(UTILITY))

    # ---- positions, with the map drawn beside the table that names it
    pos_blocks = []
    for kind, title, lede, hidden in POS_SECTIONS:
        rows = POSITIONS[kind]
        # Only a first death can be traded, so the column exists in that one
        # section rather than sitting empty in the other two.
        trades = kind == "death"
        rws = ""
        for side, mp, zone, hit, of, traded, won, extra in rows:
            sub = f' &middot; {esc(extra)}' if extra and not trades else ""
            traded_cell = (f'<td class="num">{rate(traded, hit)}</td>'
                           if trades else "")
            rws += (f'<tr><td class="name"><span class="pill {side}">'
                    f'{side.upper()}</span> {esc(zone)}'
                    f'<span class="den" style="font-weight:400;margin-left:7px">'
                    f'{esc(mp.replace("de_", ""))}{sub}</span></td>'
                    f'<td class="num">{rate(hit, of)}</td>{traded_cell}'
                    f'<td class="num">{rate(won, hit)}</td></tr>')

        figs = []
        if pictures:
            for mp in dict.fromkeys(r[1] for r in rows):
                show = {r[2] for r in rows if r[1] == mp}
                for pic in pictures(mp, show=show, width=300):
                    floor = (f' <span class="pill">{esc(pic["level"])}</span>'
                             if pic["level"] else "")
                    figs.append(
                        f'<figure class="zonefig">{pic["svg"]}'
                        f'<figcaption class="den"><strong>'
                        f'{esc(mp.replace("de_", ""))}</strong>{floor}'
                        f'</figcaption></figure>')
        maps_here = f'<div class="zonerow">{"".join(figs)}</div>' if figs else ""

        pos_blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'From position data</span><h2>{esc(title)}</h2></div>'
            f'<p class="lede">{esc(lede)}</p>'
            f'<div class="tbl-wrap"><table><thead><tr><th>Place</th>'
            f'<th class="num">Rounds</th>'
            + ('<th class="num" title="First deaths here that a teammate '
               'traded back">Traded</th>' if trades else "")
            + f'<th class="num">Of those, won</th></tr></thead>'
            f'<tbody>{rws}</tbody></table></div>'
            f'<p class="note">{hidden} more places showed the same pattern less '
            f'often; the top {len(rows)} are the ones worth practice time.</p>'
            f'{maps_here}</section>')

    # ---- map pool, sides, buys
    map_rows = "".join(
        f'<tr><td class="name">{map_chip(mp)}</td>'
        f'<td class="num mono">{n}</td>'
        f'<td class="num">{rate(won, of)}</td>'
        f'<td class="num">{rate(cw, cof)}</td>'
        f'<td class="num">{rate(tw, tof)}</td></tr>'
        for mp, n, won, of, cw, cof, tw, tof in MAP_POOL)
    side_rows = "".join(
        f'<tr><td class="name"><span class="pill {sd}">{sd.upper()}</span></td>'
        f'<td class="num mono">{of}</td>'
        f'<td class="num">{rate(won, of)}</td></tr>'
        for sd, won, of in SIDES)
    buy_rows = "".join(
        f'<tr><td class="name">{esc(kind)}</td><td class="num mono">{of}</td>'
        f'<td class="num">{rate(won, of)}</td></tr>'
        for kind, won, of in BUYS)

    # ---- players
    ply = "".join(
        f'<div class="card">'
        f'<div style="display:flex;gap:10px;align-items:center">'
        f'<h3>{esc(name)}</h3>'
        f'<span class="{ROLE_CLASS.get(role, "role")}">{esc(role)}</span></div>'
        f'<div class="stat-row">'
        f'<div class="stat"><span class="stat-n">{100 * ow // od}%</span>'
        f'<span class="label">opening duels won</span>'
        f'<span class="den">{ow} / {od}</span></div>'
        f'<div class="stat"><span class="stat-n">{100 * aw // ad}%</span>'
        f'<span class="label">rounds with an AWP</span>'
        f'<span class="den">{aw} / {ad}</span></div></div>'
        f'<div class="tbl-wrap"><table><thead><tr>'
        f'<th>Map and side</th><th>Where they stood at freeze-end</th>'
        f'<th class="num">Rounds</th></tr></thead><tbody>'
        + "".join(f'<tr><td class="den">{where}</td>'
                  f'<td class="name">{esc(spot)}</td>'
                  f'<td class="num den">{esc(n)}</td></tr>'
                  for where, spot, n in spots)
        + "</tbody></table></div></div>"
        for name, role, ow, od, aw, ad, spots in PLAYERS)

    cov_rows = "".join(
        f'<tr><td class="mono">{esc(d)}</td><td class="name">{map_chip(m)}</td>'
        f'<td>{esc(ev)}</td><td>{esc(vs)}</td></tr>'
        for d, m, ev, vs in COVERAGE)

    claims = "".join(
        f'<div style="padding:13px 0;border-top:1px solid var(--border)">'
        f'<h3>{esc(h)}</h3><p class="lede" style="margin-top:3px">{esc(b)}</p>'
        f'</div>' for h, b in NOT_CLAIMED)

    n_patterns = len(PATTERN_COUNTS) + sum(len(v) for v in POSITIONS.values())

    body = f"""
  <section>
    <div class="warn">
      <strong>Format preview.</strong> A fictional team and invented numbers on
      real maps. What is real is the shape: every rate carries the number it came
      from, every place named is one your own demos would put somebody in, and
      anything under {MIN_CHANCES} chances refuses to show a percentage.
    </div>
  </section>

  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{DEMOS}</span>
        <span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{BASELINE}%</span>
        <span class="label">rounds you won</span>
        <span class="den">71 / {ROUNDS}</span></div>
      <div class="stat"><span class="stat-n">{MAPS}</span>
        <span class="label">maps played</span></div>
      <div class="stat"><span class="stat-n">{n_patterns}</span>
        <span class="label">patterns found</span></div>
    </div>
  </section>

  <section class="lead">
    <div class="sec-head"><span class="label">Read this one first</span>
      <h2>What to work on</h2></div>
    <p class="lede">Every line below is a conclusion drawn from something counted
      further down this page, ranked by how many rounds it covers and how far it
      sits from your own average of {BASELINE}%. Nothing here is predicted. The
      evidence is printed under each one, so you can disagree with the reasoning
      rather than having to take it on trust.</p>
    {"".join(groups)}
  </section>

  <section>
    <div class="sec-head"><span class="label">Newest first</span>
      <h2>Recent form</h2></div>
    <p class="lede">Your last {len(FORM)} matches, with the real result. In your
      own report each of these opens that match.</p>
    <div class="formrow">{form}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What repeats across your matches</span>
      <h2>Recurring patterns</h2></div>
    <p class="lede">Counted, never predicted. A line appears once it has
      {MIN_PATTERN_CHANCES} chances behind it; under {MIN_CHANCES} it shows raw
      counts rather than a percentage. In the chart the bar's full length is the
      chances and the fill is what came of them, so a 5-of-12 and a 45-of-79 read
      as different weights of evidence even where the percentages are close.</p>
    <div class="grid-chart">
      <div><div class="tbl-plain"><table>
        <thead><tr><th>Pattern</th>
          <th class="num">Observed / chances</th></tr></thead>
        <tbody>{prows}</tbody></table></div></div>
      <div class="chart">{chart}</div>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What your grenades did</span>
      <h2>Utility</h2></div>
    <p class="lede">What the utility achieved, counted per grenade from the demo,
      not how much of it was thrown.</p>
    <div class="stat-row">{ucards}</div>
    <p class="den" style="margin-top:2px">{SMOKE_LINE}</p>
  </section>

  {"".join(pos_blocks)}

  <section>
    <div class="sec-head"><span class="label">Where the rounds went</span>
      <h2>Map pool</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Map</th><th class="num">Matches</th>
        <th class="num">Rounds won</th><th class="num">As CT</th>
        <th class="num">As T</th></tr></thead>
      <tbody>{map_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Side by side</span><h2>Sides</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Your side</th><th class="num">Rounds</th>
        <th class="num">Rounds won</th></tr></thead>
      <tbody>{side_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">By what they could afford</span>
      <h2>Buys</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Your buy</th><th class="num">Rounds</th>
        <th class="num">Rounds won</th></tr></thead>
      <tbody>{buy_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Who does what</span>
      <h2>Players</h2></div>
    <p class="lede">Roles as observed, not as labeled. Positions are the spots
      each player actually occupied at freeze-end, with the rounds counted. Every
      player also gets a page of their own, match by match.</p>
    <div class="grid2">{ply}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What this is built from</span>
      <h2>Coverage</h2></div>
    <p class="lede">Everything above is counted from these {DEMOS} demos. Nothing
      is estimated, predicted, or compared against teams outside this list.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Date</th><th>Map</th><th>Event</th><th>Versus</th></tr></thead>
      <tbody>{cov_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head">
      <span class="label">Read this before you trust anything above</span>
      <h2>What this report does not claim</h2></div>
    <div class="card" style="gap:0">{claims}</div>
    <p class="lede">This report is built from six demos. Six is enough to see
      habits and not enough to see a whole team, so treat it as a starting point
      for your own review, not a substitute for it.</p>
  </section>

  <section>
    <div class="card" style="align-items:flex-start;gap:10px">
      <span class="label">Next match</span>
      <h2>Get this after every match, for free</h2>
      <p class="lede">Send in your league matches and this page rebuilds itself as
        the season goes on. Free while the collegiate baselines are being built:
        your demos are what make them exist, and league teams are the only ones
        who get measured against them.</p>
      <a class="btn" href="/signup">Add your team</a>
    </div>
  </section>"""

    head = banner(f"{TEAM}: season report",
                  crumb=f'{esc(LEAGUE)} &middot; through week 4 &middot; '
                        f'{DEMOS} demos, {ROUNDS} rounds',
                  label="Sample report")
    return page("Sample report", head, body, user)
