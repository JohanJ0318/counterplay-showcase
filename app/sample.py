"""The sample report, rendered in the product's own components.

    /sample-report

This is the page a coach opens from "See a real report" before they trust
anything, so it has one job: look exactly like what they will get. It is built
from `theme.CSS` and the same helpers every real page uses - `report.pct` for
every figure, `theme.map_chip` for every map, `charts` for every picture, the
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
denominator behind every rate, the round counts - is the real format, because
the format is what is being previewed.
"""
from __future__ import annotations

from . import charts
from .movement import COMMIT_TO, SETUP_AT
from .report import (MIN_CHANCES, MIN_PATTERN_CHANCES, PATTERNS, buy_pattern,
                     pct)
from .theme import banner, esc, map_chip, page
from .utility import FLASH_ROUND_PATTERN, KILL_GRACE_SECONDS, MIN_BLIND_SECONDS

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
# facts it was drawn from, and the comparison the card draws as two bars.
# Grouped by map, because practice is planned one map at a time.
#
# (good, side, do, because, evidence, footer, versus, rounds at stake)
SEASON = ("All your rounds", 71, ROUNDS)
ADVICE = [
    ("", [
        (False, None, "Practice trading the opening duel",
         "Losing the first duel is normal. Losing the round almost every "
         "time is not: your second player is too far back to trade. Drill "
         "the spacing.",
         ["You win 19 of 71 rounds after losing the opening duel"], None,
         (("After losing the opening duel", 19, 71), SEASON), 15.0),
        (False, None, "Fix who your flashes land on",
         "63% of your flashes blind your own side. Drill the 24 that blinded "
         "a teammate and nobody else: your entry walks in blind to a site "
         "still held.",
         ["91 of 144 flashes blinded your own side: 48 also blinded an "
          "opponent, 24 a teammate only, 19 only the thrower"],
         f"Happens in 58 of your {ROUNDS} rounds", None, 5.0),
    ]),
    ("mirage", [
        (True, "ct", "Keep the A default setup",
         "You start only 8 of 32 CT rounds this way, and they win 34 points "
         "more often. A small sample, but a clear one.",
         ["Held in 8 of 32 CT rounds; you win 7 of those 8"], None,
         (("Held A default", 7, 8), ("Other CT rounds on mirage", 13, 24)),
         2.7),
        (False, "t", "Change how you take top mid",
         "When your first death is in top mid, the round is usually gone. "
         "This often, it is the same duel taken the same way.",
         ["First death in top mid in 8 of 31 T rounds; you win 2 of those 8"],
         None,
         (("First death in top mid", 2, 8), ("Other T rounds on mirage", 10, 23)),
         1.4),
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
     "Counted per flash, not per player blinded. A blind counts if it lasts "
     f"{MIN_BLIND_SECONDS} seconds or more."),
    ("9%", "of your flashes get somebody killed", "13 of 144 thrown",
     "An opponent it blinded died to one of you before the flash wore off, "
     f"or within {KILL_GRACE_SECONDS:.0f} second after. 14 opponents in all."),
    ("26%", "of your molotovs deny space", "34 of 131 thrown",
     "An opponent had to stand in it, walk out of it or go round it. 97 "
     "burned with nobody near them."),
    ("$780", "of utility a round, unused at death",
     "$115,400 of $402,000 bought",
     "Still in a player's hand when they died, priced at what it cost. "
     "Utility a survivor kept is not counted."),
]
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
# Setup and commit, already merged the way /stats merges them: one row per
# place, the commit reading folded into the sub-line as "also as far as the
# group got". `other` and `other_won` are the same map and side in the rounds
# it did not happen. Five rows, as /stats shows (POS_TOP_N): a place with
# fewer than MIN_CHANCES other rounds sorts last there, so it never makes the
# five and none appears here.
#
# (side, map, zone, rounds it happened in, rounds of that map and side,
#  rounds won of those, other, other won, sub-line)
EARLY = [
    ("t", "de_mirage", "A main", 17, 31, 7, 14, 8,
     "3.7 players on average &middot; also as far as the group got in 14 of 31"),
    ("ct", "de_mirage", "A default", 8, 32, 7, 24, 13,
     "2.4 players on average"),
    ("t", "de_nuke", "Trophy", 7, 16, 3, 9, 5,
     "3.0 players on average"),
    ("t", "de_nuke", "lobby", 7, 16, 2, 9, 6,
     "the furthest the group got together"),
    ("t", "de_mirage", "top mid", 5, 31, 1, 26, 11,
     "the furthest the group got together"),
]
EARLY_HIDDEN = 8

POS_SECTIONS = (
    ("death", "Where your first death happens",
     "Where the first of you dies, and whether it was traded. Untraded means "
     "playing 4 against 5. The bar is how often it happens, out of your rounds "
     "on that map and side.", 6),
)

# --------------------------------------------------------- map pool and buys
# (map, matches, rounds won, of rounds, CT won, of CT, T won, of T)
MAP_POOL = [
    ("de_mirage", 3, 34, 63, 20, 32, 14, 31),
    ("de_inferno", 2, 24, 51, 13, 26, 11, 25),
    ("de_nuke", 1, 13, 34, 8, 18, 5, 16),
]
# The place each positional card is about, for its label in the ranking,
# which names a place the way /stats does: "top mid, T on mirage".
PLACE_OF = {"Keep the A default setup": "A default",
            "Change how you take top mid": "top mid"}

# (name, role, opening duels won, of, ADR). Roles are the ones
# report.role_of() can observe: AWP, Entry, Support, Rifle. No "IGL": calling
# is not in a demo.
# No "where they stood at freeze-end" table: the product does not show one,
# and a preview must not promise what the real report lacks.
PLAYERS = [
    ("Player A", "Support", 21, 62, 71),
    ("Player B", "AWP", 34, 61, 84),
    ("Player C", "Entry", 29, 66, 91),
    ("Player D", "Rifle", 4, 12, 58),
]
ROLE_CLASS = {"AWP": "role awp", "Entry": "role entry"}

NOT_CLAIMED = [
    ("No predictions.",
     "Nothing here says what anyone will do next match. It says what happened, "
     "how often, and out of how many chances."),
    ("No comparison to other teams.",
     "You are not scored against professional or matchmaking players. Those "
     "baselines exist and they do not describe your league, so they are off."),
    ("Every rate knows its sample size.",
     "Hover a figure for the rounds behind it. A rate off four rounds is noise "
     "wearing a percent sign, and you can see when it is one."),
    ("Every figure is auditable.",
     "Hover a figure for its count. Every match report lists its rounds, so you "
     "can open the demo and check it yourself. If a line is wrong, it is wrong "
     "in a way you can see."),
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
    groups, ranked = [], []
    for mp, items in ADVICE:
        cards = []
        for good, side, do, because, evidence, foot, vs, stake in items:
            tag = "keep doing this" if good else "worth changing"
            ev = "".join(f"<li>{esc(e)}</li>" for e in evidence)
            pill = f'<span class="pill {side}">{side.upper()}</span>' if side else ""
            fig = charts.versus([(lab, pct(won, of), f"{won} of {of}")
                                 for lab, won, of in vs]) if vs else ""
            cards.append(
                f'<div class="card advice{" good" if good else ""}">'
                f'<div style="display:flex;gap:9px;align-items:center;'
                f'flex-wrap:wrap"><span class="pill {"on" if good else "t"}">'
                f'{tag}</span>{pill}</div><h3>{esc(do)}</h3>'
                f'<p class="lede">{esc(because)}</p>'
                f'<ul class="den" style="margin:0;padding-left:17px">{ev}</ul>'
                + fig
                + (f'<p class="den">{esc(foot)}</p>' if foot else "")
                + '</div>')
            label = (do if not side else
                     f"{PLACE_OF[do]}, {side.upper()} on {mp}")
            ranked.append((label, stake if good else -stake,
                           f"{stake:.0f} rounds"))
        head = (f'<div class="sec-head"><h3>'
                f'{"On " + esc(mp) if mp else "Across every map"}</h3></div>')
        groups.append(f'<div style="margin-bottom:22px">{head}'
                      f'<div class="grid2">{"".join(cards)}</div></div>')
    ranked.sort(key=lambda r: -abs(r[1]))
    ranking = charts.diverging(ranked)

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
    chart = charts.bars([(n, hit, of) for (n, _detail), hit, of in PATTERN_COUNTS],
                        notes=[d for (_n, d), _h, _o in PATTERN_COUNTS])

    # ---- utility
    ucards = "".join(
        f'<div class="stat"><span class="stat-n">{big}</span>'
        f'<span class="label">{esc(label)}{_info(f"ut{i}", tip)}</span>'
        f'<span class="den">{esc(den)}</span></div>'
        for i, (big, label, den, tip) in enumerate(UTILITY))

    # ---- positions: the maps once, then the tables that name them
    #
    # Section order is /stats' order, and the maps are drawn from the union of
    # every place named below, which is why this gathers the zones before it
    # renders anything.
    pos_blocks = []

    shown_zones: dict = {}
    for row in EARLY:
        shown_zones.setdefault(row[1], set()).add(row[2])
    for row in POSITIONS["death"]:
        shown_zones.setdefault(row[1], set()).add(row[2])

    figs = []
    if pictures:
        for mp, show in shown_zones.items():
            for pic in pictures(mp, show=show, width=300):
                floor = (f' <span class="pill">{esc(pic["level"])}</span>'
                         if pic["level"] else "")
                figs.append(
                    f'<figure class="zonefig">{pic["svg"]}'
                    f'<figcaption class="den"><strong>'
                    f'{esc(mp.replace("de_", ""))}</strong>{floor}'
                    f'</figcaption></figure>')
    if figs:
        pos_blocks.append(
            f'<section><div class="sec-head"><span class="label">From position '
            f'data</span><h2>The maps you play</h2></div>'
            f'<p class="lede">The places named below, drawn from your own '
            f'rounds.</p>'
            f'<div class="zonerow">{"".join(figs)}</div></section>')

    # One block per place, went there against didn't, as /stats draws it.
    # Under MIN_CHANCES the second bar declines to answer rather than drawing
    # a percentage off five rounds.
    erows = ""
    for side, mp, zone, hit, of, won, other, other_won, _extra in EARLY:
        erows += (
            f'<div class="op"><p class="op-head"><span class="pill {side}">'
            f'{side.upper()}</span> <strong>{esc(zone)}</strong> '
            f'<span class="den" title="{hit} of {of}">'
            f'{esc(mp.replace("de_", ""))} &middot; {pct(hit, of):.0f}% of your '
            f'{side.upper()} rounds there</span></p>'
            + charts.versus([
                ("Went there", pct(won, hit), f"won {won} of {hit}"),
                ("Didn't", pct(other_won, other) if other >= MIN_CHANCES
                 else None, f"won {other_won} of {other}")])
            + '</div>')
    # Held back: it renders after the first-death table, the way /stats
    # orders them. Where rounds are lost comes before where the group stands.
    early_block = (
        f'<section><div class="sec-head"><span class="label">From position '
        f'data</span><h2>Where you are in the opening</h2></div>'
        f'<p class="lede">Where two or more of you stand {int(SETUP_AT)} '
        f'seconds in, and how often you win from there. Each place is '
        f'compared with your other rounds on the same map and side.</p>'
        f'<div class="chart op-list">{erows}</div>'
        f'<p class="note">The {len(EARLY)} of {len(EARLY) + EARLY_HIDDEN} '
        f'places with the widest gap.</p></section>')

    for kind, title, lede, hidden in POS_SECTIONS:
        rows = POSITIONS[kind]
        fig = charts.first_deaths([{
            "side": side, "place": zone, "map": mp.replace("de_", ""),
            "share": pct(hit, of), "traded": pct(traded, hit),
            "won": pct(won, hit), "title": f"{hit} of {of} {side.upper()} rounds",
            "traded_title": f"{traded} of {hit}", "won_title": f"{won} of {hit}"}
            for side, mp, zone, hit, of, traded, won, _extra in rows])
        pos_blocks.append(
            f'<section><div class="sec-head"><span class="label">'
            f'From position data</span><h2>{esc(title)}</h2></div>'
            f'<p class="lede">{esc(lede)}</p>'
            f'<div class="chart">{fig}</div>'
            f'<p class="note">The top {len(rows)} of {len(rows) + hidden} '
            f'places.</p></section>')

    pos_blocks.append(early_block)

    # ---- map pool, as /stats draws it. Sides and buys are in the patterns.
    pool = charts.sides([{
        "chip": map_chip(mp), "matches": n,
        "all": pct(won, of), "all_title": f"{won} of {of}",
        "ct": pct(cw, cof), "ct_title": f"{cw} of {cof}",
        "t": pct(tw, tof), "t_title": f"{tw} of {tof}"}
        for mp, n, won, of, cw, cof, tw, tof in MAP_POOL])

    # ---- players
    ply = "".join(
        f'<div class="card">'
        f'<div style="display:flex;gap:10px;align-items:center">'
        f'<h3>{esc(name)}</h3>'
        f'<span class="{ROLE_CLASS.get(role, "role")}">{esc(role)}</span></div>'
        f'<div class="stat-row">'
        f'<div class="stat" title="{ow} of {od}">'
        f'<span class="stat-n">{pct(ow, od):.0f}%</span>'
        f'<span class="label">opening duels won</span></div>'
        f'<div class="stat"><span class="stat-n">{adr}</span>'
        f'<span class="label">ADR</span></div></div></div>'
        for name, role, ow, od, adr in PLAYERS)

    cov_rows = "".join(
        f'<tr><td class="mono">{esc(d)}</td><td class="name">{map_chip(m)}</td>'
        f'<td>{esc(ev)}</td><td>{esc(vs)}</td></tr>'
        for d, m, ev, vs in COVERAGE)

    claims = "".join(
        f'<div style="padding:13px 0;border-top:1px solid var(--border)">'
        f'<h3>{esc(h)}</h3><p class="lede" style="margin-top:3px">{esc(b)}</p>'
        f'</div>' for h, b in NOT_CLAIMED)

    n_items = sum(len(items) for _mp, items in ADVICE)

    body = f"""
  <section>
    <div class="warn">
      <strong>Format preview.</strong> A fictional team and invented numbers on
      real maps. What is real is the shape: every rate carries the number it came
      from, and every place named is one your own demos would put somebody in.
    </div>
  </section>

  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{DEMOS}</span>
        <span class="label">matches</span></div>
      <div class="stat" title="77 of {ROUNDS}"><span class="stat-n">{pct(77, ROUNDS):.0f}%</span>
        <span class="label">opening duels won</span></div>
      <div class="stat"><span class="stat-n">{MAPS}</span>
        <span class="label">maps played</span></div>
      <div class="stat"><span class="stat-n">{n_items}</span>
        <span class="label">to work on</span></div>
    </div>
  </section>

  <section class="lead">
    <div class="sec-head"><span class="label">Read this one first</span>
      <h2>What to work on</h2></div>
    <p class="lede">Biggest first: how far each one sits from your usual,
      times the rounds it covers.</p>
    <div class="chart">{ranking}<p class="den" style="margin:12px 0 0">Longer
      bar, more rounds at stake. Left costs you rounds, right wins them.</p></div>
    {"".join(groups)}
  </section>

  <section>
    <div class="sec-head"><span class="label">Newest first</span>
      <h2>Recent form</h2></div>
    <p class="lede">Your last {len(FORM)}. In your own report each one opens
      that match.</p>
    <div class="formrow">{form}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What repeats across your matches</span>
      <h2>Recurring patterns</h2></div>
    <p class="lede">Counted, never predicted. A line needs
      {MIN_PATTERN_CHANCES} chances to appear. The full bar is the chances and
      the fill is what came of them.</p>
    <div class="chart">{chart}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What your utility did</span>
      <h2>Utility</h2></div>
    <p class="lede">What your utility achieved, counted per throw.</p>
    <div class="stat-row">{ucards}</div>
  </section>

  {"".join(pos_blocks)}

  <section>
    <div class="sec-head"><span class="label">Where the rounds went</span>
      <h2>Map pool</h2></div>
    <p class="lede">Rounds won on each map, by side. The mark is 50%.</p>
    <div class="chart">{pool}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Who does what</span>
      <h2>Players</h2></div>
    <p class="lede">Roles as observed, not as labeled. Every player also gets a
      page of their own, match by match.</p>
    <div class="grid2">{ply}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What this is built from</span>
      <h2>Coverage</h2></div>
    <p class="lede">Everything above is counted from these {DEMOS} demos.</p>
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
        the season goes on. Free this season.</p>
      <a class="btn" href="/signup">Add your team</a>
    </div>
  </section>"""

    head = banner(f"{TEAM}: season report",
                  crumb=f'{esc(LEAGUE)} &middot; through week 4 &middot; '
                        f'{DEMOS} demos, {ROUNDS} rounds',
                  label="Sample report")
    return page("Sample report", head, body, user)
