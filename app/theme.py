"""The page shell for application pages.

White surfaces, dark purple, and nothing else. The layout follows the
conventions every match-analytics product shares — top nav, a row of stat
cards, dense tables, a round-by-round strip — because coaches already know how
to read that shape and a novel one would only cost them time.

Deliberately plain:

  * **One accent.** Purple carries every interactive and branded thing. Sides
    are the single exception — CT purple, T amber — because a report is
    unreadable if you cannot tell them apart at a glance.
  * **No decoration.** No gradients, no glass, no ornament. Borders are one
    hairline, corners are 6px, shadows are almost nothing. Everything on the
    page is either data or a control.
  * **Light only.** There is no dark palette to keep in step, which halves the
    surface area of any future change.

Mirrors the type scale in `league/gen/build.py`. The two copies are deliberate:
`build.py` stays a standalone stdlib script that runs without installing the
app. If you change a token here, change it there too.
"""
from __future__ import annotations

import html

CSS = """
:root{
  --bg:#F7F6FA;
  --surface:#FFFFFF;
  --surface-2:#FBFAFD;
  --border:#E7E3F0;
  --border-strong:#D6D0E4;

  --ink:#191325;
  --muted:#655D77;
  --faint:#948CA6;

  /* One accent, three weights. */
  --purple:#5B21B6;
  --purple-deep:#3F1178;
  --purple-bright:#7C3AED;
  --purple-soft:#F3EFFE;
  --purple-line:#DCD1F7;
  --on-purple:#FFFFFF;

  /* Sides. The one place a second hue is allowed. */
  --ct:#5B21B6;
  --ct-soft:#F3EFFE;
  --t:#A65B0B;
  --t-soft:#FDF3E4;

  --good:#046C4E;
  --bad:#A61B1B;
  --bad-soft:#FDF0F0;

  --f-display:"Space Grotesk","Helvetica Neue",Arial,sans-serif;
  --f-body:"Public Sans","Helvetica Neue",Arial,sans-serif;
  --f-mono:"JetBrains Mono",ui-monospace,Menlo,monospace;

  --r:6px;
  --shadow:0 1px 2px rgba(25,19,37,.05);
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;min-height:100vh;background:var(--bg);color:var(--ink);
  font-family:var(--f-body);font-size:15px;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}

.wrap{max-width:1160px;margin:0 auto;padding:0 24px 88px}
.wrap.narrow{max-width:460px}
h1,h2,h3{font-family:var(--f-display);margin:0;text-wrap:balance}
h1{font-size:clamp(1.7rem,3.6vw,2.25rem);line-height:1.12;letter-spacing:-.022em;
  font-weight:700}
h2{font-size:1.12rem;letter-spacing:-.012em;font-weight:700}
h3{font-size:.98rem;font-weight:600}
p{margin:0}
a{color:var(--purple);text-decoration:none}
a:hover{color:var(--purple-deep);text-decoration:underline}

.label{font-size:.7rem;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--faint)}
.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.den{font-family:var(--f-mono);font-size:.74rem;color:var(--faint)}

/* ---- top nav ---- */
nav.top{background:var(--surface);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:50}
.nav-in{max-width:1160px;margin:0 auto;padding:0 24px;height:58px;display:flex;
  gap:20px;align-items:center;justify-content:space-between}
.nav-links{display:flex;gap:6px;align-items:center;font-size:.9rem;
  flex-wrap:wrap;justify-content:flex-end;min-width:0}
.nav-links a{white-space:nowrap}
/* The account name is the one nav item of unbounded length, and on a phone it
   pushed everything else off the edge. It truncates; the links never do. */
.nav-links a.who{max-width:9rem;overflow:hidden;text-overflow:ellipsis}
/* The section you are in, marked in the nav rather than left to be inferred. */
.nav-links a.here{color:var(--purple);background:var(--purple-soft)}
/* Section navigation: where you are INSIDE a section, on its own row, so the
   primary nav never changes shape between one part of the product and another. */
.subnav{background:var(--surface);border-bottom:1px solid var(--border)}
.subnav-in{max-width:1160px;margin:0 auto;padding:0 24px;height:42px;
  display:flex;gap:4px;align-items:center;overflow-x:auto}
.subnav a{color:var(--muted);font-size:.86rem;font-weight:500;padding:6px 11px;
  border-radius:var(--r);white-space:nowrap}
.subnav a:hover{color:var(--ink);background:var(--bg);text-decoration:none}
.subnav a.here{color:var(--purple);background:var(--purple-soft)}
@media(max-width:640px){
  .nav-in{flex-wrap:wrap;gap:6px}
  .nav-links{font-size:.82rem;gap:2px;width:100%}
  .nav-links a{padding:6px 8px}
  .nav-links a.who{max-width:6rem}
}
.nav-links a{color:var(--muted);padding:7px 12px;border-radius:var(--r);
  font-weight:500}
.nav-links a:hover{color:var(--ink);background:var(--bg);text-decoration:none}
/* `.nav-links a` outranks `.btn`, so without this the call to action renders in
   muted grey on the purple fill, the lowest-contrast text on the page, on the
   one element that most needs reading. */
.nav-links a.btn{color:var(--on-purple);background:var(--purple);padding:8px 16px}
.nav-links a.btn:hover{color:var(--on-purple);background:var(--purple-deep)}
.mark{font-family:var(--f-display);font-weight:700;letter-spacing:-.03em;
  font-size:1.06rem;color:var(--ink)}
.mark em{font-style:normal;color:var(--purple)}

/* ---- page header ---- */
header.page{background:var(--surface);border-bottom:1px solid var(--border)}
.head-in{max-width:1160px;margin:0 auto;padding:30px 24px 26px;display:flex;
  flex-direction:column;gap:7px}
.crumb{font-size:.86rem;color:var(--muted)}

section{padding-top:34px;display:flex;flex-direction:column;gap:14px}
.sec-head{display:flex;flex-direction:column;gap:3px}
.lede{color:var(--muted);font-size:.9rem;max-width:70ch}

/* ---- surfaces ---- */
.card, .tbl-wrap, .stat, .note, .warn{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);box-shadow:var(--shadow);
}
.card{padding:22px 24px;display:flex;flex-direction:column;gap:14px}
.tbl-wrap{overflow-x:auto}

/* ---- tables ---- */
table{border-collapse:collapse;width:100%;font-size:.875rem}
th{font-size:.7rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faint);text-align:left;padding:11px 16px;background:var(--surface-2);
  border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:12px 16px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:var(--purple-soft)}
td.name{font-weight:600}
td.num,th.num{font-family:var(--f-mono);font-variant-numeric:tabular-nums;
  white-space:nowrap;text-align:right}

/* ---- explanations on demand ----
   Every recurring-pattern row carried a two-sentence paragraph underneath it.
   Nine rows of that is a page of prose wrapped around nine numbers, and the
   numbers are what a coach came for. The prose is still there, behind an "i".

   Hover shows it, and so does FOCUS: `:focus` rather than `:focus-visible`
   because tapping the button on a phone focuses it, which is the only way a
   touch device gets at a hover tooltip. Keyboard users get the same thing for
   free. */
.info{display:inline-flex;align-items:center;justify-content:center;
  width:15px;height:15px;flex:none;margin-left:7px;vertical-align:1px;
  border:1px solid var(--border-strong);border-radius:50%;
  background:var(--surface);color:var(--faint);
  font-family:var(--f-body);font-size:.6rem;font-weight:700;font-style:normal;
  line-height:1;cursor:help;position:relative;-webkit-user-select:none;
  user-select:none}
.info:hover,.info:focus{color:var(--purple);border-color:var(--purple);
  background:var(--purple-soft);outline:none}
/* Opens DOWNWARD. Upward reads better but is cut off whenever the row you are
   hovering happens to be at the top of the screen, and the top of the screen is
   exactly where you hover after scrolling to a section. */
.info .tip{position:absolute;left:0;top:calc(100% + 9px);
  width:max-content;max-width:min(320px,74vw);
  background:var(--ink);color:#fff;
  font-size:.78rem;font-weight:400;font-style:normal;line-height:1.5;
  letter-spacing:0;text-align:left;text-transform:none;
  padding:9px 11px;border-radius:var(--r);
  box-shadow:0 8px 22px rgba(25,19,37,.28);
  opacity:0;visibility:hidden;transition:opacity .12s ease;
  pointer-events:none;z-index:50}
.info .tip::after{content:"";position:absolute;bottom:100%;left:5px;
  border:5px solid transparent;border-bottom-color:var(--ink)}
.info:hover .tip,.info:focus .tip{opacity:1;visibility:visible}
/* Near the right edge the balloon would run off the page, so rows can flip it. */
.info.left .tip{left:auto;right:0}
.info.left .tip::after{left:auto;right:5px}

/* A table that hosts tooltips cannot also be a scroll container: `overflow-x`
   clips the balloon on every axis. These tables are two columns of short text
   and never needed to scroll. */
.tbl-plain{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);box-shadow:var(--shadow);overflow:visible}

/* ---- stat cards ---- */
.stat-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(152px,1fr));gap:12px}
.stat{padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.stat-n{font-family:var(--f-display);font-weight:700;font-size:1.6rem;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15;
  color:var(--purple-deep)}

/* ---- badges ---- */
.pill{display:inline-block;font-size:.68rem;font-weight:600;letter-spacing:.04em;
  text-transform:uppercase;padding:3px 9px;border-radius:20px;white-space:nowrap;
  background:var(--bg);color:var(--muted);border:1px solid var(--border-strong)}
.pill.on{background:var(--purple-soft);color:var(--purple);border-color:var(--purple-line)}
.pill.beta{background:var(--t-soft);color:var(--t);border-color:#F0DCBC}
.pill.off{background:transparent;color:var(--faint)}
/* Sides are the one place a second hue earns its keep. */
/* Win and loss, as a coach scans a season: the letter carries it, the colour
   only reinforces it, so it still reads without colour vision. */
.pager{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:12px 0;border-bottom:1px solid var(--line);font-size:.9rem;
  flex-wrap:wrap}
.pager span{min-width:0}
.formrow{display:flex;gap:10px;flex-wrap:wrap}
.formcard{display:flex;align-items:center;gap:8px;padding:10px 14px;
  background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  text-decoration:none;color:var(--ink)}
.formcard:hover{border-color:var(--purple-line);text-decoration:none}
/* A recommendation is the one card that should read as an instruction, so it
   carries a left rail: brass when something needs changing, purple when the
   advice is to keep doing what is already working. */
.card.advice{border-left:3px solid var(--t);border-radius:0 var(--r) var(--r) 0}
.card.advice.good{border-left-color:var(--purple)}
.chart{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r);box-shadow:var(--shadow);padding:16px 18px;
  overflow-x:auto}
.chart svg{color:var(--ink)}
/* Each chart sets its own min-width inline, at its natural size, so the
   container scrolls rather than the picture shrinking. See charts._open. */
.chart{-webkit-overflow-scrolling:touch}
@media(max-width:620px){
  .chart{padding:12px}
  /* Says out loud that the picture is wider than the screen, because a chart
     that scrolls with no hint looks like a chart that is cut off. */
  /* "the whole match" was written for the round timeline and then inherited by
     every other chart, where there is no match to see. */
  .chart::after{content:"scroll sideways to see the whole chart";
    display:block;font-family:var(--f-mono);font-size:.62rem;color:var(--faint);
    padding-top:8px}
}
.zonerow{display:flex;gap:18px;flex-wrap:wrap;margin-top:18px}
.zonefig{margin:0;flex:1 1 320px;min-width:0}
.zonefig svg{width:100%;height:auto;border:1px solid var(--line);
  border-radius:var(--r);background:var(--card)}
.zonefig figcaption{margin-top:6px}
details summary{cursor:pointer;font-weight:600;color:var(--purple);
  padding:8px 0;font-size:.9rem}
.res{display:inline-block;min-width:1.15rem;text-align:center;font-weight:700;
  font-size:.72rem;letter-spacing:.04em;padding:2px 6px;border-radius:5px;
  border:1px solid var(--line);color:var(--muted);margin-right:5px}
.res.win{background:var(--purple-soft);color:var(--purple);
  border-color:var(--purple-line)}
.res.loss{background:var(--t-soft);color:var(--t);border-color:#F0DCBC}
.pill.ct{background:var(--ct-soft);color:var(--ct);border-color:var(--purple-line)}
.pill.t{background:var(--t-soft);color:var(--t);border-color:#F0DCBC}
.role{font-size:.68rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  padding:3px 9px;border-radius:20px;background:var(--bg);color:var(--muted);
  border:1px solid var(--border-strong)}
.role.awp{background:var(--t-soft);color:var(--t);border-color:#F0DCBC}
.role.entry{background:var(--purple-soft);color:var(--purple);border-color:var(--purple-line)}
.thin{font-size:.66rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
  color:var(--t);background:var(--t-soft);border:1px solid #F0DCBC;
  border-radius:20px;padding:1px 8px}

/* ---- callouts ---- */
.note,.warn{padding:15px 18px;font-size:.89rem;max-width:76ch}
.note{background:var(--purple-soft);border-color:var(--purple-line)}
.warn{background:var(--bad-soft);border-color:#F3D2D2}

/* ---- forms ---- */
form.stack{display:flex;flex-direction:column;gap:15px}
label{display:flex;flex-direction:column;gap:6px;font-size:.82rem;font-weight:500;
  color:var(--muted)}
input,select,textarea{
  font-family:var(--f-body);font-size:.94rem;padding:10px 12px;width:100%;
  color:var(--ink);background:var(--surface);
  border:1px solid var(--border-strong);border-radius:var(--r);
}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--purple);
  box-shadow:0 0 0 3px var(--purple-soft)}
input[type=file]{padding:9px;cursor:pointer}

button,.btn{
  font-family:var(--f-body);font-weight:600;font-size:.92rem;padding:11px 20px;
  background:var(--purple);color:var(--on-purple);border:1px solid var(--purple);
  border-radius:var(--r);cursor:pointer;text-align:center;display:inline-block;
  transition:background .12s ease,border-color .12s ease;
}
button:hover,.btn:hover{background:var(--purple-deep);border-color:var(--purple-deep);
  text-decoration:none;color:var(--on-purple)}
.btn.ghost{background:var(--surface);color:var(--purple);border-color:var(--border-strong)}
.btn.ghost:hover{background:var(--purple-soft);border-color:var(--purple-line);
  color:var(--purple-deep)}
/* The selected filter. A ghost button that is currently applied should look
   applied, not merely hoverable. */
.btn.ghost.on{background:var(--purple);color:var(--on-purple);
  border-color:var(--purple)}
.btn.ghost.on .den{color:var(--on-purple);opacity:.75}
.btn.ghost{font-size:.84rem;padding:7px 13px}

.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
/* A table of short labels beside a chart.

   An even split gave the table more room than its two columns of text needed
   and left the chart 510px of a 540px picture, so the one thing on the page
   that is meant to be seen at a glance arrived with a scrollbar. The chart now
   takes the larger share.

   Two columns only above 1160px, which is where `.wrap` stops growing. Between
   the two the split would squeeze the chart again, so below that width the
   chart simply goes full width underneath, where it has more room than it
   ever had beside the table. */
.grid-chart{display:grid;grid-template-columns:1fr;gap:16px;align-items:start}
@media(min-width:1160px){
  .grid-chart{grid-template-columns:minmax(0,1fr) minmax(0,1.45fr)}
}
.maps{display:flex;flex-direction:column;gap:20px}

footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--border);
  font-size:.8rem;color:var(--faint);display:flex;flex-direction:column;gap:4px}
:focus-visible{outline:2px solid var(--purple);outline-offset:2px}

@media (max-width:620px){
  .nav-in{height:auto;padding:10px 20px;flex-wrap:wrap}
  .head-in{padding:24px 20px}
  th,td{padding:10px 12px}
  .card{padding:18px}
}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Space+Grotesk:wght@500;600;700&'
         'family=Public+Sans:wght@400;500;600&'
         'family=JetBrains+Mono:wght@400;500&display=swap">')


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


# THE PRIMARY NAVIGATION, DEFINED ONCE.
#
# The league site is generated separately, and it grew its own nav: clicking
# "League" swapped Dashboard for "Your team", dropped Players and Trends
# entirely, and reordered what was left. A person cannot learn a navigation
# that rearranges itself when they move between two halves of one product.
#
# So the primary nav is data, and `league/gen/build.py` imports this list
# rather than writing its own. Section-specific links (NECC standings, the
# leaderboards) become a second bar underneath, which is where "where am I
# inside this section" belongs — not mixed into "where can I go".
PRIMARY_NAV = [
    ("/dashboard", "Dashboard"),
    ("/matches", "Matches"),
    ("/players", "Players"),
    ("/stats", "Team stats"),
    ("/trends", "Trends"),
    ("/league/", "League"),
]


def nav_links(current: str = "", account: str = "") -> str:
    """The primary nav as HTML. `current` marks the section you are in."""
    out = []
    for href, label in PRIMARY_NAV:
        here = ' aria-current="page"' if href == current else ""
        cls = ' class="here"' if href == current else ""
        out.append(f'<a href="{href}"{cls}{here}>{esc(label)}</a>')
    if account:
        out.append(f'<a class="who" href="/account">{esc(account)}</a>')
    return "".join(out)


def page(title: str, head: str, body: str, user=None) -> str:
    """Wrap page content in the shell. `head` is the banner, `body` the content."""
    if user is None:
        links = ('<a href="/league/">League</a>'
                 '<a href="/login">Log in</a>'
                 '<a class="btn" href="/signup">Add your team</a>')
    else:
        links = nav_links(account=user["name"] or user["email"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>{FONTS}
<style>{CSS}</style></head><body>
<nav class="top"><div class="nav-in">
  <a class="mark" href="/">Counter<em>play</em></a>
  <span class="nav-links">{links}</span>
</div></nav>
<header class="page"><div class="head-in">{head}</div></header>
<div class="wrap">{body}
<footer>
  <span>Counterplay: match analysis for league Counter-Strike.</span>
  <span>Not affiliated with Valve, FACEIT, ESEA, or any collegiate association.</span>
</footer>
</div></body></html>"""


def banner(title: str, crumb: str = "", label: str = "") -> str:
    bits = []
    if label:
        bits.append(f'<span class="label">{esc(label)}</span>')
    if crumb:
        bits.append(f'<p class="crumb">{crumb}</p>')
    bits.append(f"<h1>{esc(title)}</h1>")
    return "".join(bits)
