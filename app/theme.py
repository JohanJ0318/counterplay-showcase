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
  /* NO -webkit-font-smoothing:antialiased.
     It reads as a nicety and on Windows it is not: it turns OFF subpixel
     rendering, so every glyph loses two thirds of its horizontal resolution
     and thins out. Combined with any text sitting on a fractional pixel it is
     exactly what "is this blurry or am I imagining it" looks like. Left to
     the operating system, which knows what kind of screen this is. */
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

/* A dozen numbers do not need sixteen pixels either side of each of them.
   The roster and the scoreboard carry twelve columns and were scrolling
   sideways on an 800px window, which puts the last two columns off screen by
   default and makes a reader think they are not there. Narrower gutters on
   those two tables buy back about a hundred and seventy pixels; the first and
   last cells keep the full inset so the table still has edges. */
table.dense{font-size:.82rem}
table.dense th,table.dense td{padding-left:6px;padding-right:6px}
table.dense th{font-size:.64rem;letter-spacing:.02em}
/* One long nickname should not push the last two columns off the screen for
   every row. A max-width on the cell is advisory in an auto-layout table and
   a 1,200-unit Cyrillic handle sailed straight past it, so the ceiling goes
   on an inline-block INSIDE the cell, where it is obeyed. Hovering shows the
   name in full and the player's own page has it whole. */
table.dense td.name>a,table.dense td.name>span{display:inline-block;
  max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  vertical-align:bottom}
/* The role pill is a five-letter word in a box; in a twelve-column table the
   box is worth more than the air inside it. */
table.dense .role{padding-left:6px;padding-right:6px;letter-spacing:0}
table.dense th:first-child,table.dense td:first-child{padding-left:16px}
table.dense th:last-child,table.dense td:last-child{padding-right:16px}

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
/* A stat card past the first one is never far from the right edge of the page,
   and the balloon is up to 320px wide. Opening rightward from the last card of
   a four-card row put 175px of hidden balloon past the page edge, which is
   enough to give the whole document a horizontal scrollbar: `visibility:hidden`
   still occupies space. So every card but the first opens its balloon leftward
   from its own right edge, which cannot leave the page whatever the row wraps
   to. */
.stat-row .stat:not(:first-child) .info .tip{left:auto;right:0}
.stat-row .stat:not(:first-child) .info .tip::after{left:auto;right:5px}

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
/* Every figure is ink. There WAS a rule making the first card of any row
   purple, and it made one number in a strip of four coloured for no reason a
   reader could work out. An accent that cannot be explained is worse than no
   accent: it reads as a mistake, and the reader spends attention deciding
   whether it means something. Purple is for what you can click. */

/* ---- a rate is a shape, not just a numeral ----

   Two lines, centred on each other: the figure on top and the denominator
   under it, smaller. Side by side they read as one long string and the
   denominator competes with the number it is supporting. Stacked, the eye
   takes the percentage and the denominator is there the moment it is wanted,
   which is the right order even though the denominator is this product's
   whole argument.

   EVERY VARIANT IS THE SAME BOX. The thin one and the empty one keep the
   width, the two-line height and the bottom padding even though neither draws
   a bar, because a cell that lays itself out differently sits askew from the
   rows around it and makes a column look broken.

   The bar goes under the figure rather than behind it: a tinted cell
   background fights the row hover and turns a dense table into noise, while a
   rule reads at a glance and disappears while the number is being read. The
   track is the full width of the box, so 90% and 20% stay comparable down a
   column even though the text lengths differ. */
.rt{display:inline-flex;flex-direction:column;align-items:center;gap:1px;
  position:relative;min-width:82px;padding-bottom:8px;line-height:1.2;
  text-align:center}
/* Both lines are fixed line boxes, so every cell is exactly the same height
   whatever is in it. The thin variant sets its figure a size smaller and in
   mono, and without this that alone left its box six pixels shorter, which is
   invisible in one row and reads as a wobble down a column of nine. */
/* Line boxes, not flex centring. `align-items:center` on a fixed height puts
   the baseline at (box - text) / 2, which is a half pixel whenever those two
   do not divide evenly: every figure on the page was landing on x.469 and
   being resampled. A line box of the same height as the box lands on whole
   pixels and needs no centring. */
.rt b{font-weight:600;font-size:13px;letter-spacing:-.01em;
  display:block;height:18px;line-height:18px}
.rt .den{font-size:10px}
.rt::before,.rt::after{content:"";position:absolute;left:0;bottom:0;
  height:3px;border-radius:2px}
.rt::before{right:0;background:var(--border)}
.rt::after{width:var(--f,0%);background:var(--purple);opacity:.85}
/* `few` and `nil`, not `thin` and `none`. `.thin` is already an amber badge
   class defined further down this sheet, and at equal specificity the later
   rule wins: `.rt.thin` was quietly inheriting its padding, background and
   border, which is what made those cells sit askew from every other row. */
/* No bar, same footprint. */
/* A match report's tally. Same box as every other rate cell so a column still
   lines up, but the figure IS the fraction: there is no percentage to show and
   no thinness to warn about, because the denominator is the whole match. */
.rt.tally{padding-bottom:0}
.rt.tally::after,.rt.tally::before{display:none}
.rt.tally b{font-family:var(--f-mono);font-weight:500;font-size:.92rem;
  color:var(--ink);letter-spacing:0}
.rt.few::after,.rt.nil::after{display:none}
.rt.few::before,.rt.nil::before{background:transparent}
.rt.few b{font-family:var(--f-mono);font-size:11px;color:var(--muted)}
/* The second line is one fixed line box whatever sits in it. The pill carries
   a border and the denominator does not, which left a thin row three pixels
   shorter than its neighbours: invisible on its own, and visible as a wobble
   down a column of nine. */
.rt .den,.rt .pill{height:14px;line-height:14px;display:block}
.rt.few .pill{padding:0 7px;font-size:8px;border:0;border-radius:20px;display:inline-block}
.rt.nil b{font-weight:400}

/* ---- maps look like maps ----
   Valve's radar, cropped to a circle, beside a map's name. A coach recognises
   Mirage from this faster than they read the word, and the images have been
   sitting in site/radars since the zone work.

   `contain`, not a crop: at 22px the whole silhouette is recognisable to
   anybody who plays the map, while a zoom into the middle is a grey smear
   that happens to be from Mirage. */
/* Off the screen, not display:none. A crawler that checks computed style
   skips anything hidden; this is a real, laid-out input that simply sits
   where nobody can see it. Nothing focuses it, because tabindex is -1. */
.hp-field{position:absolute;left:-9999px;top:auto;width:1px;height:1px;
  overflow:hidden}

/* Where you are inside a shared link. Same idea as the league site's
   subnav: a reader with no account still needs to know the roster exists. */
.sharenav{display:flex;gap:6px;flex-wrap:wrap;margin:26px 0 20px}
.sharenav a{font-size:.88rem;font-weight:500;color:var(--muted);
  padding:7px 13px;border-radius:var(--r);white-space:nowrap;
  text-decoration:none;border:1px solid var(--border)}
.sharenav a:hover{color:var(--ink);background:var(--surface)}
.sharenav a.on{color:var(--on-purple);background:var(--purple);
  border-color:var(--purple)}

.mapchip{display:inline-flex;align-items:center;gap:7px;white-space:nowrap}
.mapchip i{width:22px;height:22px;flex:none;border-radius:50%;
  background-size:contain;background-repeat:no-repeat;background-position:center;
  border:1px solid var(--border-strong);filter:var(--radar-dim);
  background-color:var(--surface-2)}
/* The silhouette. Same round frame, but the artwork is ours and the
   theme paints it: the file is a shape, the colour comes from here. */
.mapchip i.sil{filter:none;background-image:none;
  background-color:var(--purple-soft);border-color:var(--purple-line);
  display:flex;align-items:center;justify-content:center}
/* 22 of a 26px circle. The silhouette carries interior detail now, and the
   limit is cells per pixel: mapicons.py draws about 49 across, so 22px is
   roughly two cells a pixel, which holds an edge. Smaller than this and the
   detail is present but averaged into grey. */
/* A ROUNDED SQUARE, NOT A CIRCLE. A circular frame only suits content that
   is itself roughly circular, and these are not: ancient is 0.92 wide to
   tall, cache 1.23, and nuke 1.68, which in a circle drew a 22 by 13 bar
   with four pixels of nothing above and below it. A rounded rectangle takes
   any aspect without looking like the picture missed, and 8px is the radius
   every other surface on the site already uses. */
.mapchip i.sil{width:26px;height:26px;border-radius:var(--r)}
.mapchip i.sil::after{content:"";width:22px;height:22px;
  background-color:var(--purple);
  -webkit-mask:var(--sil) center/contain no-repeat;
  mask:var(--sil) center/contain no-repeat}
.mapchip.big i.sil{width:32px;height:32px}
.mapchip.big i.sil::after{width:27px;height:27px}
.mapchip.big i{width:28px;height:28px}

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
/* The round numbers a finding is about, set apart from the reasoning above
   them because they are the thing a coach copies onto a whiteboard. */
.rounds{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;
  padding-top:9px;border-top:1px solid var(--border)}
.rounds .mono{font-size:.86rem;color:var(--ink);letter-spacing:.02em}
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
/* The long page's own table of contents. Sticky, because a list that
   scrolls away is a list you have to scroll back for. */
.pagenav{position:sticky;top:0;z-index:5;display:flex;gap:4px;flex-wrap:wrap;
  padding:10px 0;margin-bottom:4px;background:var(--bg);
  border-bottom:1px solid var(--border)}
.pagenav a{font-size:.83rem;font-weight:500;color:var(--muted);
  padding:6px 10px;border-radius:var(--r);white-space:nowrap;
  text-decoration:none}
.pagenav a:hover{color:var(--ink);background:var(--surface)}
.pagenav a.on{color:var(--purple);background:var(--purple-soft)}
@media (max-width:640px){.pagenav{overflow-x:auto;flex-wrap:nowrap}}

/* A ROW OF MAPS IS LEVELLED BY HEIGHT, NOT BY WIDTH. Four maps of four
   shapes given equal widths cannot look like a set; whichever axis you
   equalise, the odd shape is the wrong one. Fix the height and every width
   falls out of its own aspect, which is how a row of pictures is laid out. */
.zonerow{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start;
  margin-top:18px}
/* flex-basis 0, not 320px, so the grow factor each figure carries (its
   own aspect ratio) decides the widths in proportion rather than merely in
   order. Two floors of one map then come out the same height instead of the
   taller one rendering three times the size of the wider one. */
.zonefig{margin:0;flex:0 1 auto;min-width:0;max-width:100%}
.zonefig svg image{filter:var(--radar-dim)}
.zonefig svg{display:block;height:250px;width:auto;max-width:100%;
  border:1px solid var(--border);
  border-radius:var(--r);background:var(--card)}
.zonefig figcaption{margin-top:6px}
/* One map per row on a phone, at the full width, rather than four small
   ones sharing it. */
@media (max-width:640px){
  .zonefig{flex:1 1 100%}
  .zonefig svg{height:auto;width:100%}
}
details summary{cursor:pointer;font-weight:600;color:var(--purple);
  padding:8px 0;font-size:.9rem}
/* The how-do-I-get-a-demo help sits inside the upload card, so it needs a
   line above it to separate it from the form rather than reading as one more
   note under the button. `code` here is a filename, and a filename that wraps
   mid-path is unreadable. */
details.howto{border-top:1px solid var(--border);margin-top:4px}
details.howto p{margin:0 0 10px}
details.howto code{font-family:var(--f-mono);font-size:.82em;
  background:var(--surface-2);border:1px solid var(--border);
  border-radius:4px;padding:1px 5px;white-space:nowrap}
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

/* A TABLE THAT SCROLLS SIDEWAYS SAYS SO.

   The charts already do this and the tables, which are wider and matter
   more, said nothing: the roster carries twelve columns, and on a phone the
   last four of them are off the right edge with no indication they exist. A
   table that is cut off and a table that scrolls look identical standing
   still.

   The class is set by script from the element's real overflow rather than by
   a breakpoint, for the same reason `rate()` refuses to print a percentage
   off four rounds. A hint under a table that fits is a hint a reader learns
   to ignore, and then it is not there when it is true. It also clears itself
   once you reach the right edge, because by then it is describing something
   you have already done. */
.tbl-wrap.over::after{content:"scroll sideways for the rest of the table";
  display:block;font-family:var(--f-mono);font-size:.62rem;color:var(--faint);
  padding:9px 16px 11px;border-top:1px solid var(--border)}

/* ---- print ----

   Coaches print this for a team meeting, and until now what came out of the
   printer was the screen: a dark page if the reader had picked dark, the
   sticky table of contents stamped across the top, an upload button nobody
   can press on paper, and every table wider than the sheet cut off at the
   margin with its last columns gone.

   Naming `[data-theme="dark"]` is not belt and braces. It is one point more
   specific than `:root`, so a print rule that only said `:root` would lose to
   a reader's own choice of dark mode and print a black page. */
@media print{
  :root[data-theme="dark"], :root{
    --bg:#FFFFFF; --surface:#FFFFFF; --surface-2:#FFFFFF;
    --border:#C9C4D4; --border-strong:#A8A1B8;
    --ink:#000000; --muted:#333042; --faint:#55506A;
    --purple:#3F1178; --purple-deep:#2A0B50; --purple-bright:#3F1178;
    --purple-soft:#F2EEFA; --purple-line:#C9BCE8; --on-purple:#FFFFFF;
    --ct:#3F1178; --ct-soft:#F2EEFA; --t:#7A4208; --t-soft:#FBF3E6;
    --good:#04543C; --bad:#8B1616; --bad-soft:#FBF0F0;
    --shadow:none;
  }
  @page{margin:14mm}
  html{color-scheme:light}
  body{background:#FFFFFF}
  .wrap{max-width:none;padding-left:0;padding-right:0}

  /* The parts of the page that only work under a cursor. The hints go too:
     nothing scrolls on paper, so both of them would be instructions to do
     something impossible. */
  nav.top, .pagenav, .themebtn, .navbtn, .navchk, button, .btn,
  input, select, textarea, .howto,
  .tbl-wrap.over::after, .chart::after{display:none !important}

  /* A container that scrolls on screen has to grow on paper. A printer has
     no scrollbar, so whatever sits past the edge is not clipped, it is lost. */
  .tbl-wrap, .chart{overflow:visible !important}
  .chart svg{max-width:100%;height:auto}

  /* Letting it overflow is not the same as making it fit. A sheet is about
     680 pixels wide at these margins and the roster is 683 at screen size,
     so without this the last columns do not scroll away, they fall off the
     paper, which is the bug this section exists to fix. Smaller type and
     tighter gutters is the only lever a table of `white-space:nowrap`
     columns leaves. */
  table{font-size:.72rem}
  table.dense{font-size:.66rem}
  th,td{padding:6px 8px}
  table.dense th:first-child,table.dense td:first-child{padding-left:8px}
  table.dense th:last-child,table.dense td:last-child{padding-right:8px}

  /* A header row printed once leaves every sheet after the first as a grid of
     unlabelled numbers. */
  thead{display:table-header-group}
  tr, .card, .stat, .formcard, .note, .chart{break-inside:avoid}
  h1,h2,h3{break-after:avoid}

  /* Purple in greyscale is just a paler word, and an underline under every
     link in a dense table is noise. */
  a{color:inherit;text-decoration:none}
  tbody tr:hover td{background:transparent}
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

# Which tables actually scroll, measured rather than assumed.
#
# Whether a twelve-column table overflows depends on the window, the font that
# loaded and the longest nickname in it, so no breakpoint gets this right. It
# runs at the end of the body, where the tables exist, and again on resize.
# The listener is attached once per container and guarded by a data attribute
# because a resize fires many times and this is called on each one.
TABLE_SCRIPT = """<script>
function cpOver(e){e.classList.toggle('over',
  e.scrollWidth-e.clientWidth-e.scrollLeft>2)}
function cpTables(){var w=document.querySelectorAll('.tbl-wrap'),i,e;
  for(i=0;i<w.length;i++){e=w[i];
    if(!e.dataset.cpo){e.dataset.cpo='1';
      e.addEventListener('scroll',function(){cpOver(this)},{passive:true})}
    cpOver(e)}}
cpTables();addEventListener('resize',cpTables,{passive:true});
</script>"""

THEME_BUTTON = ('<button class="themebtn" type="button" onclick="cpTheme()" '
                'title="Switch between light and dark" '
                'aria-label="Switch between light and dark">&#9681;</button>')


SOCIAL_BLURB = ("Match analysis for league Counter-Strike teams. Player stats, "
                "team stats, a report per match, and the patterns a team "
                "repeats without noticing, each one printed with the rounds "
                "it came from.")


def page(title: str, head: str, body: str, user=None,
         noindex: bool = False) -> str:
    """Wrap page content in the shell. `head` is the banner, `body` the content.

    `noindex` is for pages reached by holding a secret URL rather than by
    signing in. A capability link that a search engine has crawled is not a
    capability link any more.
    """
    # The link-preview card, on the pages a stranger is allowed to see.
    #
    # Deliberately not on a `noindex` page. Those are the share links, and the
    # whole point of one is that holding the URL is the only permission there
    # is. A team name unfurling into a Discord channel because somebody pasted
    # their link is exactly the leak the noindex is there to prevent, so the
    # rule is the same rule: if it is not for crawlers, it is not for
    # unfurlers either.
    social_title = title if "Counterplay" in title else f"{title} | Counterplay"
    social = "" if noindex else f"""
<meta property="og:type" content="website">
<meta property="og:site_name" content="Counterplay">
<meta property="og:title" content="{esc(social_title)}">
<meta property="og:description" content="{esc(SOCIAL_BLURB)}">
<meta property="og:image" content="https://counterplaycs.com/media/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">"""
    if user is None:
        links = ('<a href="/login">Log in</a>'
                 '<a class="btn" href="/signup">Add your team</a>')
        side = THEME_BUTTON
    else:
        links = nav_links()
        who = esc(user["name"] or user["email"])
        side = f'<a class="who" href="/account" title="{who}">{who}</a>{THEME_BUTTON}'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{'<meta name="robots" content="noindex, nofollow">' if noindex else ''}
<title>{esc(title)}</title>
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">{social}{FONTS}
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
</div>{TABLE_SCRIPT}</body></html>"""


def banner(title: str, crumb: str = "", label: str = "") -> str:
    bits = []
    if label:
        bits.append(f'<span class="label">{esc(label)}</span>')
    if crumb:
        bits.append(f'<p class="crumb">{crumb}</p>')
    bits.append(f"<h1>{esc(title)}</h1>")
    return "".join(bits)


# Valve ships one radar per map, plus a second image for Nuke's lower floor.
# The base one is the recognisable one, so a chip always uses that.
RADAR_FOR = {
    "de_ancient": "de_ancient", "de_anubis": "de_anubis",
    "de_cache": "de_cache", "de_dust2": "de_dust2",
    "de_inferno": "de_inferno", "de_mirage": "de_mirage",
    "de_nuke": "de_nuke", "de_overpass": "de_overpass",
    "de_train": "de_train",
}


# The maps mapicons.py has produced a silhouette for. Overpass and Train
# have no stored radar mask, so they fall through to the radar image below;
# anything with neither renders as a bare name.
ICON_FOR = {"de_ancient", "de_anubis", "de_cache", "de_dust2", "de_inferno",
            "de_mirage", "de_nuke"}


def map_chip(map_name: str, big: bool = False, label: str = "") -> str:
    """A map's outline as a small round chip, with its name beside it.

    The silhouette is this site's own drawing, built once by mapicons.py from
    the alpha channel of the radar. At the size a chip renders, an actual
    radar is a grey smudge: shape is the only thing that reads at twenty
    pixels, and shape is what tells one map from another.

    Falls back to the radar image for a map without a silhouette, and to the
    name alone for one with neither, because a missing picture should read as
    a plain label rather than as a broken one.
    """
    key = (map_name or "").strip()
    short = label or key.replace("de_", "")
    size = " big" if big else ""
    if key in ICON_FOR:
        return (f'<span class="mapchip{size}">'
                f'<i class="sil" style="--sil:url(/icons/maps/{key}.svg)"></i>'
                f'{esc(short)}</span>')
    art = RADAR_FOR.get(key)
    if not art:
        return esc(short)
    return (f'<span class="mapchip{size}">'
            f'<i style="background-image:url(/radars/{art}_radar_psd.png)"></i>'
            f'{esc(short)}</span>')
