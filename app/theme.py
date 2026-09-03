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
   muted grey on the purple fill — the lowest-contrast text on the page, on the
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


def page(title: str, head: str, body: str, user=None) -> str:
    """Wrap page content in the shell. `head` is the banner, `body` the content."""
    if user is None:
        links = ('<a href="/league/">League</a>'
                 '<a href="/login">Log in</a>'
                 '<a class="btn" href="/signup">Add your team</a>')
    else:
        # Matches earns a nav slot because match reports are the headline
        # feature and there was no link to one anywhere: the only route in was
        # clicking the small grey team name in a page crumb.
        links = ('<a href="/dashboard">Dashboard</a>'
                 '<a href="/matches">Matches</a>'
                 '<a href="/players">Players</a>'
                 '<a href="/stats">Team stats</a>'
                 '<a href="/trends">Trends</a>'
                 '<a href="/league/">League</a>'
                 f'<a class="who" href="/account">'
                 f'{esc(user["name"] or user["email"])}</a>')
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
  <span>Counterplay &mdash; match analysis for league Counter-Strike.</span>
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
