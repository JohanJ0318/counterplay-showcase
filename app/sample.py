"""The sample report, rendered in the product's own components.

    /sample-report.html

This page is the one a coach opens from "See a real report" before they trust
anything, so it has one job: look exactly like what they will get. It used to
be a hand-maintained HTML file with its own typeface, its own dark-green
palette and its own stylesheet — a third design system, left over from an
earlier direction, that had drifted so far from the product that the preview no
longer previewed anything.

So it is built from `theme.CSS` and the same classes every real page uses:
`stat-row`, `tbl-wrap`, `sec-head`, `pill`, `thin`. Change the product's look
and this follows, because there is nothing here to keep in sync.

The numbers are invented and the page says so at the top, twice. Everything
else — the denominators beside every rate, the round numbers, the "thin" label
under eight chances — is the real format, because the format is what is being
previewed.
"""
from __future__ import annotations

from .theme import banner, esc, page

# The fictional team. Named so nobody mistakes it for a real program.
TEAM = "Northlake University"
LEAGUE = "NECC Fall 2026"
DEMOS, ROUNDS, MAPS, MIN_CHANCES = 4, 96, 3, 8

COVERAGE = [
    ("2026-09-09", "de_mirage", "NECC wk1", "Lakeshore College"),
    ("2026-09-16", "de_inferno", "NECC wk2", "Ashford University"),
    ("2026-09-16", "de_mirage", "NECC wk2", "Ashford University"),
    ("2026-09-23", "de_anubis", "NECC wk3", "Pinebluff State"),
]

MAP_POOL = [
    ("mirage", "2 / 2", 63, "32 / 51", 56, "14 / 25", 69, "18 / 26", "2 / 0"),
    ("inferno", "0 / 1", 41, "11 / 27", 31, "4 / 13", 50, "7 / 14", "0 / 1"),
    ("anubis", "0 / 1", 39, "7 / 18", 56, "5 / 9", 22, "2 / 9", "0 / 2"),
]

TENDENCIES = [
    ("mirage", [
        ("t", "A-site execute off a mid smoke", 61, "11 / 18",
         "Mid smoke lands between 1:38 and 1:33 every time, then four players "
         "commit through palace and ramp. Nobody stays mid to trade.",
         "3, 5, 8, 9, 12, 14, 17, 19, 22, 24, 27"),
        ("ct", "Double-AWP A on gun rounds", 64, "9 / 14",
         "Two AWPs hold A together from palace and CT. Leaves B to a lone rifle "
         "plus the rotator.",
         "4, 6, 10, 13, 16, 18, 21, 23, 26"),
        ("t", "Never took B on a full buy", 0, "0 / 13",
         "Every full-buy round on this map went A or mid-to-A. You only hit B "
         "on force buys.", ""),
    ]),
    ("inferno", [
        ("t", "Banana control before any A look", 77, "10 / 13",
         "Three players to banana in the first 20 seconds regardless of buy. "
         "You enter A apartments only after banana is lost or won.",
         "2, 4, 5, 7, 9, 11, 14, 16, 19, 21"),
        ("ct", "Aggressive banana push at freeze-end", 36, "5 / 14",
         "Molotov plus a two-player push into banana within the first 15 "
         "seconds. Costly when it fails.", "3, 8, 12, 17, 20"),
    ]),
    ("anubis", [
        ("t", "B-site split through water", 44, "4 / 9",
         "Thin sample. Noted because it happened twice in a row in the closing "
         "rounds.", "12, 14, 16, 17"),
    ]),
]

ECONOMY = [
    ("Force-buy the round after losing pistol", 75, "6 / 8",
     "Armour plus SMGs. Twice you saved instead, both times after a "
     "three-player pistol loss."),
    ("Full save under $2,000 team economy", 92, "12 / 13",
     "Disciplined &mdash; you rarely throw a round away on an eco rush."),
    ("AWP on the second gun round", 82, "9 / 11",
     "Even when the first gun round was lost."),
    ("Utility carried forward from a lost round", 20, "3 / 15",
     "Rarely. You spend everything in the round you are in."),
]

PLAYERS = [
    ("Player A", "IGL", 33, "9 / 27", 2, "2 / 96",
     [("mirage &middot; CT", "B bench / market window", "19 / 26"),
      ("mirage &middot; T", "Second through palace", "16 / 25")]),
    ("Player B", "AWP", 55, "21 / 38", 64, "61 / 96",
     [("mirage &middot; CT", "A ramp angle from CT", "22 / 26"),
      ("inferno &middot; CT", "Banana from car", "11 / 14")]),
    ("Player C", "Entry", 44, "18 / 41", 1, "1 / 96",
     [("mirage &middot; T", "First through palace", "20 / 25")]),
    ("Player D", "Rifle", 33, "4 / 12", 0, "0 / 96",
     [("anubis &middot; CT", "B site heaven", "6 / 9")]),
]

COMPARISON = [
    ("5v4 pre-plant, full buy", "50%", "7 / 14", "85%", "11 / 13", "-35 pts", False),
    ("4v5 pre-plant, full buy", "25%", "3 / 12", "27%", "4 / 15", "-2 pts", False),
    ("Post-plant, man advantage", "67%", "6 / 9", "80%", "8 / 10", "-13 pts", False),
    ("Pistol rounds", "", "1 / 4", "", "3 / 4", "&mdash;", True),
    ("Opening duel taken", "41%", "19 / 46", "59%", "27 / 46", "-17 pts", False),
    ("Rounds won after losing the opener", "30%", "8 / 27", "47%", "9 / 19",
     "-18 pts", False),
]

NOT_CLAIMED = [
    ("No predictions.",
     "Nothing here says what anyone will do next match. It says what happened, "
     "how often, and out of how many chances."),
    ("No comparison to other teams.",
     "You are not scored against professional or matchmaking players. Those "
     "baselines exist and they do not describe your league, so they are off."),
    (f"Anything under {MIN_CHANCES} chances is marked thin.",
     "It shows raw counts only. A rate off four rounds is noise wearing a "
     "percent sign."),
    ("Every figure is auditable.",
     "Round numbers are printed so you can open the demo and check the claim "
     "yourself. If a line is wrong, it is wrong in a way you can see."),
]


def _rate(pct: int | str, den: str, thin: bool = False) -> str:
    """A figure the way the product prints one: rate, then what it is out of."""
    if thin or pct == "":
        return f'<span class="den">{den}</span> <span class="thin">thin</span>'
    return f'{pct}% <span class="den">{den}</span>'


def render(user=None) -> str:
    # ---- coverage
    cov_rows = "".join(
        f'<tr><td class="mono">{esc(d)}</td>'
        f'<td class="name">{esc(m.replace("de_", ""))}</td>'
        f'<td>{esc(ev)}</td><td>{esc(vs)}</td></tr>'
        for d, m, ev, vs in COVERAGE)

    # ---- map pool
    map_rows = "".join(
        f'<tr><td class="name">{esc(mp)}</td>'
        f'<td class="num">{esc(rec)}</td>'
        f'<td class="num">{_rate(rw, rd)}</td>'
        f'<td class="num">{_rate(tw, td_)}</td>'
        f'<td class="num">{_rate(cw, cd)}</td>'
        f'<td class="num">{esc(pb)}</td></tr>'
        for mp, rec, rw, rd, tw, td_, cw, cd, pb in MAP_POOL)

    # ---- tendencies, one card per map
    tend = []
    for mp, lines in TENDENCIES:
        items = []
        for side, title, pct, den, why, rounds in lines:
            rn = (f'<p class="den" style="margin-top:6px">rounds {esc(rounds)}</p>'
                  if rounds else "")
            items.append(
                f'<div style="display:flex;flex-direction:column;gap:4px;'
                f'padding:14px 0;border-top:1px solid var(--border)">'
                f'<div style="display:flex;gap:10px;align-items:baseline;'
                f'justify-content:space-between;flex-wrap:wrap">'
                f'<div style="display:flex;gap:9px;align-items:center">'
                f'<span class="pill {side}">{side.upper()}</span>'
                f'<h3>{esc(title)}</h3></div>'
                f'<span class="mono">{_rate(pct, den)}</span></div>'
                f'<p class="lede">{why}</p>{rn}</div>')
        tend.append(
            f'<div class="card"><div class="sec-head">'
            f'<span class="label">Map</span><h2>{esc(mp)}</h2></div>'
            f'{"".join(items)}</div>')

    # ---- economy
    eco_rows = "".join(
        f'<tr><td class="name">{esc(h)}<div class="lede" '
        f'style="font-weight:400;margin-top:3px">{why}</div></td>'
        f'<td class="num">{_rate(pct, den)}</td></tr>'
        for h, pct, den, why in ECONOMY)

    # ---- players
    ply = []
    for name, role, ow, od, aw, ad, spots in PLAYERS:
        cls = {"AWP": "role awp", "Entry": "role entry"}.get(role, "role")
        rows = "".join(
            f'<tr><td class="den">{where}</td>'
            f'<td class="name">{esc(spot)}</td>'
            f'<td class="num den">{esc(n)}</td></tr>'
            for where, spot, n in spots)
        ply.append(
            f'<div class="card">'
            f'<div style="display:flex;gap:10px;align-items:center">'
            f'<h3>{esc(name)}</h3><span class="{cls}">{esc(role)}</span></div>'
            f'<div class="stat-row">'
            f'<div class="stat"><span class="stat-n">{ow}%</span>'
            f'<span class="label">opening duels won</span>'
            f'<span class="den">{esc(od)}</span></div>'
            f'<div class="stat"><span class="stat-n">{aw}%</span>'
            f'<span class="label">rounds with an AWP</span>'
            f'<span class="den">{esc(ad)}</span></div></div>'
            f'<div class="tbl-wrap"><table><thead><tr>'
            f'<th>Map and side</th><th>Where they stood at freeze-end</th>'
            f'<th class="num">Rounds</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>')

    # ---- comparison
    cmp_rows = "".join(
        f'<tr><td class="name">{esc(sit)}</td>'
        f'<td class="num">{_rate(yp, yd, thin)}</td>'
        f'<td class="num">{_rate(op, od_, thin)}</td>'
        f'<td class="num">{gap}</td></tr>'
        for sit, yp, yd, op, od_, gap, thin in COMPARISON)

    # ---- what it does not claim
    claims = "".join(
        f'<div style="padding:13px 0;border-top:1px solid var(--border)">'
        f'<h3>{esc(h)}</h3><p class="lede" style="margin-top:3px">{b}</p></div>'
        for h, b in NOT_CLAIMED)

    body = f"""
  <section>
    <div class="warn">
      <strong>Format preview.</strong> Synthetic matches, invented numbers, a
      fictional team. What is real is the shape: every rate carries the number it
      came from, every claim carries the rounds you can check it against, and
      anything under {MIN_CHANCES} chances refuses to show a percentage.
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What this is built from</span>
      <h2>Coverage</h2></div>
    <p class="lede">Everything below is counted from these {DEMOS} demos. Nothing is
      estimated, predicted, or compared against teams outside this list.</p>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{DEMOS}</span>
        <span class="label">demos parsed</span></div>
      <div class="stat"><span class="stat-n">{ROUNDS}</span>
        <span class="label">rounds</span></div>
      <div class="stat"><span class="stat-n">{MAPS}</span>
        <span class="label">maps seen</span></div>
      <div class="stat"><span class="stat-n">{MIN_CHANCES}</span>
        <span class="label">min rounds to state a rate</span></div>
    </div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Date</th><th>Map</th><th>Event</th><th>Versus</th></tr></thead>
      <tbody>{cov_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Where the rounds went</span>
      <h2>Map pool</h2></div>
    <p class="lede">Match record, then round record. The round record is the more
      honest of the two &mdash; a 16&ndash;14 loss and a 16&ndash;2 loss are the same
      line in a match record.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Map</th><th class="num">Matches won</th>
        <th class="num">Rounds won</th><th class="num">As T</th>
        <th class="num">As CT</th><th class="num">Picked / banned</th></tr></thead>
      <tbody>{map_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">What you do every time</span>
      <h2>Tendencies</h2></div>
    <p class="lede">Counted, not inferred. Each line is a thing that happened in a
      stated number of rounds out of a stated number of chances, with the round
      numbers printed so you can open the demo and watch it.</p>
    <div class="maps">{"".join(tend)}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">How you spend</span>
      <h2>Economy habits</h2></div>
    <p class="lede">Buy behavior is the most predictable thing a team does, and the
      cheapest thing an opponent can punish.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Habit</th><th class="num">Frequency</th></tr></thead>
      <tbody>{eco_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Who does what</span>
      <h2>Players</h2></div>
    <p class="lede">Roles as observed, not as labeled. Positions are the spots each
      player actually occupied at freeze-end, with the rounds counted.</p>
    <div class="grid2">{"".join(ply)}</div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Against the teams you played</span>
      <h2>Same-server comparison</h2></div>
    <p class="lede">Your numbers next to the teams you actually played, from the same
      servers and the same matches. That is the only reason these two columns can sit
      beside each other: whatever bias exists in the parsing applies to both sides
      equally and cancels. This is context for your own figures, not a dossier on
      anyone &mdash; no opponent gets a page here, and no league-wide average is used.</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Situation</th><th class="num">You</th>
        <th class="num">Opponents</th><th class="num">Gap</th></tr></thead>
      <tbody>{cmp_rows}</tbody></table></div>
  </section>

  <section>
    <div class="sec-head">
      <span class="label">Not switched on yet</span>
      <h2>Decisions that cost rounds <span class="pill beta">Beta</span></h2></div>
    <div class="note">
      <p><strong>This section does not appear in a report today.</strong> It is the one
      part of the product that would be modeled rather than counted, and the model
      needs a corpus of collegiate matches that does not exist yet &mdash; the demos
      teams send in this season are what would build it.</p>
      <p style="margin-top:9px">It stays switched off rather than showing a number
      that came out of a simulator. When it does arrive it will carry its sample size
      on every row, the way everything else here carries its denominator.</p>
    </div>
  </section>

  <section>
    <div class="sec-head"><span class="label">Read this before you trust anything above</span>
      <h2>What this report does not claim</h2></div>
    <div class="card" style="gap:0">{claims}</div>
    <p class="lede">This report is built from four demos. Four is enough to see habits
      and not enough to see a whole team &mdash; treat it as a starting point for your
      own review, not a substitute for it.</p>
  </section>

  <section>
    <div class="card" style="align-items:flex-start;gap:10px">
      <span class="label">Next match</span>
      <h2>Get this after every match, for free</h2>
      <p class="lede">Send in your league matches and this page rebuilds itself as the
        season goes on. Free while the collegiate baselines are being built &mdash;
        your demos are what make them exist, and league teams are the only ones who
        get measured against them.</p>
      <a class="btn" href="/signup">Add your team</a>
    </div>
  </section>"""

    head = banner(f"{TEAM} — season report",
                  crumb=f'{esc(LEAGUE)} &middot; through week 4 &middot; '
                        f'{DEMOS} demos, {ROUNDS} rounds',
                  label="Sample report")
    return page("Sample report", head, body, user)
