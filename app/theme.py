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

  --r:8px;
  --shadow:0 1px 2px rgba(25,19,37,.05);
  --radar-dim:none;
}

/* ---- dark ----
   Every colour in this product is already a custom property, so dark is a
   second set of values rather than a second stylesheet. Nothing below here
   restates a rule; it restates a palette.

   Counter-Strike players review demos at night and every tool they already
   use is dark, so this is closer to the expected state than the exception.
   The ground is warmed slightly toward purple rather than neutral grey,
   which is the same decision the light theme makes.

   The accent flips direction: on white, purple is the ink and white is the
   text on it; on near-black, purple is the light and the text on it is dark.
   --on-purple carries that so no rule has to know which theme it is in. */
:root[data-theme="dark"]{
  --bg:#141119;
  --surface:#1C1823;
  --surface-2:#221D2B;
  --border:#2E2739;
  --border-strong:#3E3549;

  --ink:#EDE9F3;
  --muted:#A79FB5;
  --faint:#7E7590;

  --purple:#A78BFA;
  --purple-deep:#C4B5FD;
  --purple-bright:#8B5CF6;
  --purple-soft:#241C38;
  --purple-line:#3B2E5C;
  --on-purple:#141119;

  --ct:#A78BFA;
  --ct-soft:#241C38;
  --t:#E0A458;
  --t-soft:#2E2415;

  --good:#4ADE80;
  --bad:#F87171;
  --bad-soft:#341D1F;

  --shadow:0 1px 2px rgba(0,0,0,.45);
  /* Valve's radar images are bright PNGs and cannot be recoloured, so they
     are dimmed instead of left glowing on a dark page. */
  --radar-dim:brightness(.72) contrast(1.05);
}
@media(prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#141119; --surface:#1C1823; --surface-2:#221D2B;
    --border:#2E2739; --border-strong:#3E3549;
    --ink:#EDE9F3; --muted:#A79FB5; --faint:#7E7590;
    --purple:#A78BFA; --purple-deep:#C4B5FD; --purple-bright:#8B5CF6;
    --purple-soft:#241C38; --purple-line:#3B2E5C; --on-purple:#141119;
    --ct:#A78BFA; --ct-soft:#241C38; --t:#E0A458; --t-soft:#2E2415;
    --good:#4ADE80; --bad:#F87171; --bad-soft:#341D1F;
    --shadow:0 1px 2px rgba(0,0,0,.45);
    --radar-dim:brightness(.72) contrast(1.05);
  }
}
html{color-scheme:light dark}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;min-height:100vh;background:var(--bg);color:var(--ink);
  font-family:var(--f-body);font-size:14px;line-height:1.5;
  -webkit-font-smoothing:antialiased;
}

.wrap{max-width:1160px;margin:0 auto;padding:0 24px 64px}
.wrap.narrow{max-width:460px}
h1,h2,h3{font-family:var(--f-display);margin:0;text-wrap:balance}
/* Big and light, not small and heavy. The weight comes DOWN as the size goes
   up, which is how display type is supposed to work and is the one thing
   every modern product page has in common. Measured off Relay: 72px at weight
   400 with -1.8px tracking. This is the same idea at a size that suits a page
   with a table under it. */
h1{font-size:clamp(2.1rem,4.6vw,3rem);line-height:1.04;letter-spacing:-.034em;
  font-weight:600}
/* The surface underneath says where a section starts, so the heading does not
   have to shout it. It does still have to sound like somebody wrote it.
   Tabler's answer is 16px at weight 500, and copying that exactly made this
   look like every other admin template. 19px at 700 keeps the structure and
   keeps the voice. */
h2{font-size:1.2rem;letter-spacing:-.014em;font-weight:700;line-height:1.22}
h3{font-size:1.02rem;font-weight:600}
p{margin:0}
a{color:var(--purple);text-decoration:none}
a:hover{color:var(--purple-deep);text-decoration:underline}

.label{font-size:.68rem;font-weight:700;letter-spacing:.09em;
  text-transform:uppercase;color:var(--purple)}
.head-in .label{color:var(--purple)}
.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.den{font-family:var(--f-mono);font-size:.74rem;color:var(--faint)}

/* ---- top nav ---- */
/* ---- navigation ----
   One row, fixed height, and it never wraps. The old bar let the account name
   push the links onto a second line, which changed the height of the page
   header depending on how long somebody's name was.

   Sections sit left, next to the mark, because that is where a person looks
   for them. Everything about the ACCOUNT rather than the product sits right,
   behind a divider, so "where can I go" and "who am I" are not one list.

   Below 720px the links go behind a menu instead of wrapping. It is a
   <details> element: a real disclosure with no JavaScript, keyboard
   accessible for free, and on desktop the summary is simply not displayed. */
nav.top{background:var(--surface);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:50}
.nav-in{max-width:1160px;margin:0 auto;padding:0 24px;height:56px;
  display:flex;gap:16px;align-items:center}
.nav-menu{flex:1 1 auto;min-width:0;position:relative}
/* The checkbox is the menu's open state, so the disclosure needs no script.
   A <details> cannot do this job: browsers hide the content of a closed
   details through the internal slot, so CSS cannot show it again on a wide
   screen, and the links vanished on desktop. The input is moved out of sight
   rather than `hidden` so it keeps keyboard focus. */
.navchk{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.navbtn{display:none}
.nav-links{display:flex;gap:2px;align-items:center;font-size:.9rem;min-width:0}
.nav-links a{white-space:nowrap;color:var(--muted);padding:7px 11px;
  border-radius:var(--r);font-weight:500}
.nav-links a:hover{color:var(--ink);background:var(--bg);text-decoration:none}
/* The section you are in, marked rather than left to be inferred. */
.nav-links a.here{color:var(--purple);background:var(--purple-soft)}
/* `.nav-links a` outranks `.btn`, so without this the call to action renders in
   muted grey on the purple fill, the lowest-contrast text on the page, on the
   one element that most needs reading. */
.nav-links a.btn{color:var(--on-purple);background:var(--purple);padding:8px 15px}
.nav-links a.btn:hover{color:var(--on-purple);background:var(--purple-deep)}

.nav-side{display:flex;gap:8px;align-items:center;flex:none;
  padding-left:16px;border-left:1px solid var(--border)}
.nav-side a.who{color:var(--muted);font-size:.86rem;font-weight:500;
  max-width:9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  padding:6px 9px;border-radius:var(--r)}
.nav-side a.who:hover{color:var(--ink);background:var(--bg);text-decoration:none}
.themebtn{appearance:none;border:1px solid var(--border-strong);
  background:transparent;color:var(--muted);font:inherit;font-size:.9rem;
  line-height:1;width:30px;height:30px;border-radius:var(--r);cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.themebtn:hover{color:var(--ink);border-color:var(--purple);
  background:var(--purple-soft)}

/* Section navigation: where you are INSIDE a section, on its own row, so the
   primary nav never changes shape between one part of the product and another. */
.subnav{background:var(--surface);border-bottom:1px solid var(--border)}
.subnav-in{max-width:1160px;margin:0 auto;padding:0 24px;height:40px;
  display:flex;gap:4px;align-items:center;overflow-x:auto}
.subnav a{color:var(--muted);font-size:.86rem;font-weight:500;padding:6px 11px;
  border-radius:var(--r);white-space:nowrap}
.subnav a:hover{color:var(--ink);background:var(--bg);text-decoration:none}
.subnav a.here{color:var(--purple);background:var(--purple-soft)}

/* Six links, a divider, an account name and the theme switch need about
   820px. Below that they do not shrink, they overlap: link text is nowrap,
   so the row overflows rather than reflowing, and the account name drew on
   top of "League". The menu therefore appears at 880px rather than at a
   phone width. */
@media(min-width:881px){
  /* Backstop. If a longer account name ever arrives, the links clip rather
     than draw over the top of it. */
  .nav-menu{overflow:hidden}
}
@media(max-width:880px){
  .nav-in{gap:10px;padding:0 16px}
  .nav-menu{flex:none;margin-left:auto}
  .navbtn{display:inline-flex;align-items:center;gap:7px;cursor:pointer;
    color:var(--muted);font-size:.86rem;font-weight:600;padding:6px 10px;
    border-radius:var(--r);border:1px solid var(--border-strong);
    user-select:none;-webkit-user-select:none}
  .navchk:focus-visible+.navbtn{outline:2px solid var(--purple);
    outline-offset:2px}
  .navchk:checked+.navbtn{color:var(--purple);border-color:var(--purple);
    background:var(--purple-soft)}
  .nav-menu .nav-links{display:none}
  .navchk:checked~.nav-links{display:flex;flex-direction:column;
    align-items:stretch;position:absolute;right:0;top:calc(100% + 8px);
    min-width:190px;background:var(--surface);border:1px solid var(--border);
    border-radius:var(--r);box-shadow:0 10px 26px rgba(25,19,37,.16);
    padding:6px;z-index:60}
  .nav-side{padding-left:10px}
  .nav-side a.who{max-width:6.5rem}
}

.mark{font-family:var(--f-display);font-weight:700;letter-spacing:-.03em;
  font-size:1.06rem;color:var(--ink)}
.mark em{font-style:normal;color:var(--purple)}

/* ---- page header ---- */
/* The page header was a white band with a title in it, which is the most
   anonymous thing on the site and the first thing anybody sees. A wash of the
   brand colour costs nothing, cannot fail to load, and is the difference
   between a page and a product. */
header.page{background:
  linear-gradient(180deg,var(--purple-soft) 0%,var(--surface) 100%);
  border-bottom:1px solid var(--border)}
.head-in{max-width:1160px;margin:0 auto;padding:22px 24px 20px;display:flex;
  flex-direction:column;gap:5px}
.crumb{font-size:.86rem;color:var(--muted)}

/* A coach reads this between matches on a laptop. Tighter than a marketing
   page on purpose: the same content now fits about a third more per screen
   without any of it getting smaller. */
section{background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:15px 17px 17px;margin-top:14px;
  display:flex;flex-direction:column;gap:11px}
/* No double chrome. A table or a card that is a section's own content should
   not draw a second border inside the first one. */
section>.tbl-wrap,section>.tbl-plain,section>.card,section>.note{
  background:transparent;border:0;border-radius:0;box-shadow:none;padding:0}
section>.grid2>div>.tbl-wrap,section>.grid-chart>div>.tbl-plain{
  background:transparent;border:0;box-shadow:none}
.sec-head{display:flex;flex-direction:column;gap:2px}
.lede{color:var(--muted);font-size:.875rem;max-width:70ch}

/* ---- one section per page leads ----
   Every section used to be label, heading, paragraph, card, which meant
   nothing on the page said "read this one first". The one that matters gets
   a rule, a tint and a bigger heading; everything else steps back a little
   so that it can. */
section.lead{border-left:3px solid var(--purple);
  padding:17px 19px 19px;margin-top:22px}
section.lead>.sec-head h2{font-size:1.3rem;font-weight:700}
section.lead>.sec-head .label{color:var(--purple)}

/* ---- surfaces ---- */
.card, .tbl-wrap, .stat, .note, .warn{
  background:var(--surface);border:1px solid var(--border);
  border-radius:8px;box-shadow:none;
}
.card{padding:16px 18px;display:flex;flex-direction:column;gap:11px}
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
.stat{padding:13px 16px;display:flex;flex-direction:column;gap:1px;
  background:var(--surface-2)}
/* Numbers are ink. Purple was on every figure on the page, which made none
   of them the important one. It is now the lead number of a row and the
   things you can click, and nothing else. */
.stat-n{font-family:var(--f-display);font-weight:700;font-size:1.6rem;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15;
  color:var(--ink)}
.stat-row>.stat:first-child .stat-n,.stat.key .stat-n{color:var(--purple-deep)}

/* ---- a rate is a shape, not just a numeral ----
   Drawn under the figure rather than behind it: a tinted cell background
   fights the row hover and turns a dense table into noise, while a rule under
   the number reads at a glance and vanishes while you read the number.

   The track is always the full width of the figure, so a 90% and a 20% are
   comparable down a column even though the text lengths differ. */
.rt{display:inline-block;position:relative;padding-bottom:7px;min-width:74px}
.rt::before,.rt::after{content:"";position:absolute;left:0;bottom:0;
  height:3px;border-radius:2px}
.rt::before{right:0;background:var(--border)}
.rt::after{width:var(--f,0%);background:var(--purple);opacity:.85}
/* A thin sample gets no bar. Drawing 5 of 7 as a 71% fill is exactly the
   overstatement the "thin" label exists to prevent. */
.rt.thin::before,.rt.thin::after{display:none}
.rt.thin{padding-bottom:0;min-width:0}

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
.zonefig svg image{filter:var(--radar-dim)}
.zonefig svg{width:100%;height:auto;border:1px solid var(--border);
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

/* Pills. A 6px box is what a form control looked like in 2015; a full radius
   is what a call to action looks like now, and it costs one value. */
button,.btn{
  font-family:var(--f-body);font-weight:600;font-size:.92rem;padding:11px 22px;
  background:var(--purple);color:var(--on-purple);border:1px solid var(--purple);
  border-radius:99px;cursor:pointer;text-align:center;display:inline-block;
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


def nav_links(current: str = "") -> str:
    """The primary nav as HTML. `current` marks the section you are in.

    The account no longer belongs in this list. "Where can I go in the
    product" and "who am I signed in as" are different questions, and mixing
    them put an item of unbounded length in the middle of a fixed row.
    """
    out = []
    for href, label in PRIMARY_NAV:
        here = ' aria-current="page"' if href == current else ""
        cls = ' class="here"' if href == current else ""
        out.append(f'<a href="{href}"{cls}{here}>{esc(label)}</a>')
    return "".join(out)


# Set before first paint so a dark-mode reader never sees a white flash, and
# read back from localStorage so the choice survives a reload. No preference
# stored means no attribute, which leaves the OS setting in charge.
THEME_SCRIPT = """<script>
(function(){try{var t=localStorage.getItem('cp-theme');
if(t){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();
function cpTheme(){var h=document.documentElement,c=h.getAttribute('data-theme'),
n=c?(c==='dark'?'light':'dark'):(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches?'light':'dark');
h.setAttribute('data-theme',n);try{localStorage.setItem('cp-theme',n)}catch(e){}}
</script>"""

THEME_BUTTON = ('<button class="themebtn" type="button" onclick="cpTheme()" '
                'title="Switch between light and dark" '
                'aria-label="Switch between light and dark">&#9681;</button>')


def page(title: str, head: str, body: str, user=None) -> str:
    """Wrap page content in the shell. `head` is the banner, `body` the content."""
    if user is None:
        links = ('<a href="/league/">League</a>'
                 '<a href="/login">Log in</a>'
                 '<a class="btn" href="/signup">Add your team</a>')
        side = THEME_BUTTON
    else:
        links = nav_links()
        who = esc(user["name"] or user["email"])
        side = f'<a class="who" href="/account" title="{who}">{who}</a>{THEME_BUTTON}'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>{FONTS}
<style>{CSS}</style>{THEME_SCRIPT}</head><body>
<nav class="top"><div class="nav-in">
  <a class="mark" href="/">Counter<em>play</em></a>
  <span class="nav-menu">
    <input class="navchk" id="navchk" type="checkbox" aria-label="Menu">
    <label class="navbtn" for="navchk">Menu</label>
    <span class="nav-links">{links}</span>
  </span>
  <span class="nav-side">{side}</span>
</div></nav>
<header class="page"><div class="head-in">{head}</div></header>
<div class="wrap">{body}
<footer>
  <span>Counterplay: match analysis for league Counter-Strike.</span>
  <span>Not affiliated with Valve, FACEIT, ESEA, or any collegiate association.</span>
  <span><a href="/privacy">Privacy</a> &middot; <a href="/terms">Terms</a>
    &middot; <a href="/unsubscribe">Unsubscribe</a></span>
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
