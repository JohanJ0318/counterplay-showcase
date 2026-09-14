#!/usr/bin/env python3
"""
Counterplay — static site builder.

Reads cache/league.json (written by fetch.py) and generates a browsable site:
league index, a page per team, a page per match. No server, no database.

    python build.py --out ../site/league

Upload the whole site folder to Cloudflare Pages and the league lives at /league/.

Every rate is printed with its denominator, and anything under --min-rounds shows
raw counts only. Nothing here is modelled or predicted — it is arithmetic over
FACEIT's own match statistics.
"""

from __future__ import annotations

import argparse
import html
import sys
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

# The app's primary navigation, imported rather than reimplemented. This site
# is generated separately and used to carry its own nav, so moving between the
# app and the league pages rearranged the menu under the reader.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from app.theme import PRIMARY_NAV
except Exception:                      # generated standalone, without the app
    PRIMARY_NAV = [("/dashboard", "Dashboard"), ("/matches", "Matches"),
                   ("/players", "Players"), ("/stats", "Team stats"),
                   ("/trends", "Trends"), ("/league/", "League")]

MIN_ROUNDS = 30          # below this a player's rates are marked thin

# NECC runs four divisions and they do not play each other, so one table
# ranking all 201 teams together compares sides that will never meet. The
# division is in the competition name, spelled two ways across seasons:
# "NECC SPRING 2026 Division 1" and "NECC FALL 2025 D1 PLAYOFFS".
DIVISION_RE = re.compile(r"\bD(?:ivision)?\s*([1-4])\b", re.I)

# Competitions with no division at all: placement, open qualifiers, the regular
# season before teams are seeded. Their results are real but they do not belong
# in a division table.
UNDIVIDED = "Cross-division"


def division_of(competition: str) -> str:
    """Which division a competition belongs to, or UNDIVIDED.

    Matched on the competition name because that is the only place it appears.
    "Fall Open Phase 1" deliberately does not match: the digit is a phase
    number, and there is no D in front of it.
    """
    m = DIVISION_RE.search(competition or "")
    return f"Division {m.group(1)}" if m else UNDIVIDED


def division_sort_key(name: str):
    """Divisions in order, then the undivided bucket last."""
    return (1, name) if name == UNDIVIDED else (0, name)


# ---------------------------------------------------------------- stat access

def num(d: dict, key: str, default=0.0) -> float:
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


class Agg:
    """Running totals for one player or one team."""

    FIELDS = ("kills deaths assists damage headshots rounds sniper entry_count entry_wins "
              "util_damage util_count flash_count enemies_flashed flash_succ mvps "
              "c1v1_win c1v1_cnt c1v2_win c1v2_cnt dbl trp quad penta maps").split()

    def __init__(self):
        for f in self.FIELDS:
            setattr(self, f, 0.0)

    def add_map(self, ps: dict, rounds: float):
        self.rounds += rounds
        self.maps += 1
        self.kills += num(ps, "Kills")
        self.deaths += num(ps, "Deaths")
        self.assists += num(ps, "Assists")
        self.damage += num(ps, "Damage")
        self.headshots += num(ps, "Headshots")
        self.sniper += num(ps, "Sniper Kills")
        self.entry_count += num(ps, "Entry Count")
        self.entry_wins += num(ps, "Entry Wins")
        self.util_damage += num(ps, "Utility Damage")
        self.util_count += num(ps, "Utility Count")
        self.flash_count += num(ps, "Flash Count")
        self.enemies_flashed += num(ps, "Enemies Flashed")
        self.flash_succ += num(ps, "Flash Successes")
        self.mvps += num(ps, "MVPs")
        self.c1v1_win += num(ps, "1v1Wins")
        self.c1v1_cnt += num(ps, "1v1Count")
        self.c1v2_win += num(ps, "1v2Wins")
        self.c1v2_cnt += num(ps, "1v2Count")
        self.dbl += num(ps, "Double Kills")
        self.trp += num(ps, "Triple Kills")
        self.quad += num(ps, "Quadro Kills")
        self.penta += num(ps, "Penta Kills")

    # derived — all of them are ratios of things counted above
    @property
    def adr(self):
        return self.damage / self.rounds if self.rounds else 0.0

    @property
    def kd(self):
        return self.kills / self.deaths if self.deaths else float(self.kills)

    @property
    def kr(self):
        return self.kills / self.rounds if self.rounds else 0.0

    @property
    def hs_pct(self):
        return 100.0 * self.headshots / self.kills if self.kills else 0.0

    @property
    def sniper_share(self):
        return self.sniper / self.kills if self.kills else 0.0

    @property
    def entry_rate(self):
        return self.entry_count / self.rounds if self.rounds else 0.0

    @property
    def entry_success(self):
        return self.entry_wins / self.entry_count if self.entry_count else 0.0

    @property
    def util_dmg_round(self):
        return self.util_damage / self.rounds if self.rounds else 0.0

    @property
    def thin(self):
        return self.rounds < MIN_ROUNDS


# ---------------------------------------------------------------- model

def build_model(league: dict) -> dict:
    teams: dict = {}
    players: dict = {}
    matches: list = []

    def team(tid, name=None):
        t = teams.setdefault(tid, {
            "id": tid, "name": name or tid, "maps": 0, "map_wins": 0,
            "rounds_won": 0.0, "rounds_lost": 0.0, "matches": 0,
            "match_ids": [], "roster": {}, "map_record": defaultdict(lambda: [0, 0]),
            # Standings are computed per division, from that division's matches
            # only. A team promoted from D2 to D1 should not carry its D2 round
            # difference into the D1 table.
            "divisions": defaultdict(lambda: {
                "maps": 0, "map_wins": 0, "rounds_won": 0.0,
                "rounds_lost": 0.0, "matches": set()}),
        })
        if name and (t["name"] == tid or len(name) > len(t["name"] or "")):
            t["name"] = name
        return t

    for champ in league.get("championships", []):
        division = division_of(champ.get("name", ""))
        for rec in champ.get("matches", []):
            detail = rec.get("detail") or {}
            stats = rec.get("stats") or {}
            mid = rec.get("match_id")

            # team_id -> display name, from the match detail
            names = {}
            for fac in (detail.get("teams") or {}).values():
                if isinstance(fac, dict):
                    tid = fac.get("faction_id") or fac.get("team_id")
                    if tid:
                        names[tid] = fac.get("name") or tid

            maps = []
            seen_teams = set()
            for rnd in stats.get("rounds") or []:
                rs = rnd.get("round_stats") or {}
                rounds_played = num(rs, "Rounds")
                winner = rs.get("Winner")
                map_name = rs.get("Map", "?")
                score = rs.get("Score", "")
                sides = []

                for tm in rnd.get("teams") or []:
                    tid = tm.get("team_id")
                    if not tid:
                        continue
                    tname = names.get(tid) or (tm.get("team_stats") or {}).get("Team") or tid
                    t = team(tid, tname)
                    seen_teams.add(tid)
                    ts = tm.get("team_stats") or {}
                    won = 1 if tid == winner else 0
                    fr = num(ts, "Final Score")
                    t["maps"] += 1
                    t["map_wins"] += won
                    t["rounds_won"] += fr
                    dv = t["divisions"][division]
                    dv["maps"] += 1
                    dv["map_wins"] += won
                    dv["rounds_won"] += fr
                    dv["matches"].add(mid)
                    t["map_record"][map_name][1] += 1
                    t["map_record"][map_name][0] += won

                    roster = []
                    for p in tm.get("players") or []:
                        pid = p.get("player_id")
                        nick = p.get("nickname") or pid
                        ps = p.get("player_stats") or {}
                        if not pid:
                            continue
                        # Count every team a player turns out for rather than
                        # keeping whichever one happened to be parsed first.
                        # Rosters change mid-season and stand-ins are common;
                        # first-seen puts a transferred player on their old
                        # team's page for the rest of the year.
                        rec_p = players.setdefault(pid, {
                            "id": pid, "nick": nick, "teams": Counter(),
                            "agg": Agg()})
                        rec_p["nick"] = nick
                        rec_p["teams"][tid] += 1
                        rec_p["agg"].add_map(ps, rounds_played)
                        t["roster"][pid] = nick
                        roster.append({"id": pid, "nick": nick, "stats": ps})
                    sides.append({"id": tid, "name": tname, "won": won,
                                  "score": fr, "roster": roster})

                # rounds lost = the other side's score
                if len(sides) == 2:
                    teams[sides[0]["id"]]["rounds_lost"] += sides[1]["score"]
                    teams[sides[1]["id"]]["rounds_lost"] += sides[0]["score"]
                    teams[sides[0]["id"]]["divisions"][division]["rounds_lost"] += sides[1]["score"]
                    teams[sides[1]["id"]]["divisions"][division]["rounds_lost"] += sides[0]["score"]

                maps.append({"map": map_name, "score": score, "rounds": rounds_played,
                             "winner": winner, "sides": sides})

            if not maps:
                continue
            for tid in seen_teams:
                teams[tid]["matches"] += 1
                teams[tid]["match_ids"].append(mid)

            matches.append({
                "id": mid,
                "championship": champ.get("name", ""),
                "division": division,
                "finished_at": detail.get("finished_at"),
                "best_of": detail.get("best_of"),
                "faceit_url": (detail.get("faceit_url") or "").replace("{lang}", "en"),
                "maps": maps,
                "team_ids": sorted(seen_teams),
                "names": names,
            })

    # A player's team is the one they played the most maps for. Ties go to the
    # team they played most recently, which is the more useful guess mid-season.
    for p in players.values():
        ranked = p["teams"].most_common()
        p["team"] = ranked[0][0] if ranked else None
        p["maps_for"] = dict(p["teams"])
        p["multi_team"] = len(ranked) > 1

    for t in teams.values():
        ranked = sorted(t["divisions"].items(), key=lambda kv: -kv[1]["maps"])
        t["home_division"] = ranked[0][0] if ranked else UNDIVIDED
        t["multi_division"] = sum(
            1 for _, v in ranked if v["maps"] > 0 and _ != UNDIVIDED) > 1

    matches.sort(key=lambda m: m.get("finished_at") or 0, reverse=True)
    return {"teams": teams, "players": players, "matches": matches,
            "league": league.get("organizer", "League")}


def assign_roles(model: dict):
    """Rules, not clustering — every label carries the number that produced it."""
    by_team = defaultdict(list)
    for p in model["players"].values():
        by_team[p["team"]].append(p)

    for tid, roster in by_team.items():
        eligible = [p for p in roster if not p["agg"].thin]
        best_entry = max((p["agg"].entry_rate for p in eligible), default=0)
        best_util = max((p["agg"].util_dmg_round for p in eligible), default=0)
        for p in roster:
            a = p["agg"]
            if a.thin:
                p["role"], p["role_why"] = "–", f"only {int(a.rounds)} rounds"
                continue
            if a.sniper >= 8 and a.sniper_share >= 0.15:
                p["role"] = "AWP"
                p["role_why"] = f"{int(a.sniper)} of {int(a.kills)} kills with the AWP"
            elif abs(a.entry_rate - best_entry) < 1e-9 and a.entry_rate >= 0.12:
                p["role"] = "Entry"
                p["role_why"] = f"took the opening duel {int(a.entry_count)} of {int(a.rounds)} rounds"
            elif abs(a.util_dmg_round - best_util) < 1e-9 and best_util > 0:
                p["role"] = "Support"
                p["role_why"] = f"{int(a.util_damage)} utility damage over {int(a.rounds)} rounds"
            else:
                p["role"] = "Rifle"
                p["role_why"] = f"{a.adr:.0f} ADR over {int(a.rounds)} rounds"


# ---------------------------------------------------------------- rendering

CSS = """
:root{
  --bg:#F7F6FA; --surface:#FFFFFF; --sunk:#F1EFF7;
  --ink:#191325; --muted:#655D77; --faint:#948CA6;
  --border:#E7E3F0; --border-strong:#D6D0E4;
  --purple:#5B21B6; --purple-soft:#F3EFFE;
  --t:#A65B0B; --t-soft:#FDF3E4; --on-purple:#FFFFFF;
  --f-display:"Space Grotesk","Helvetica Neue",Arial,sans-serif;
  --f-body:"Public Sans","Helvetica Neue",Arial,sans-serif;
  --f-mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
}
/* ---- dark ----
   A second palette, not a second stylesheet: every colour on this page comes
   from the block above, so restating the values is the whole job.

   Follows the operating system, and `data-theme` on the root element beats it
   in both directions. That attribute is set by the script in the head from
   the same localStorage key the app uses, so a reader who picked dark inside
   the product does not get flashbanged on the way back out to this page. */
:root[data-theme="dark"]{
  --bg:#141119; --surface:#1C1823; --sunk:#221D2B;
  --ink:#EDE9F3; --muted:#A79FB5; --faint:#7E7590;
  --border:#2E2739; --border-strong:#3E3549;
  --purple:#A78BFA; --purple-soft:#241C38;
  --t:#E0A458; --t-soft:#2E2415; --on-purple:#141119;
}
@media(prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
  --bg:#141119; --surface:#1C1823; --sunk:#221D2B;
    --ink:#EDE9F3; --muted:#A79FB5; --faint:#7E7590;
    --border:#2E2739; --border-strong:#3E3549;
    --purple:#A78BFA; --purple-soft:#241C38;
    --t:#E0A458; --t-soft:#2E2415; --on-purple:#141119;
  }
}
html{color-scheme:light dark}
.themebtn{appearance:none;border:1px solid var(--border-strong);
  background:transparent;color:var(--muted);font:inherit;font-size:.9rem;
  line-height:1;width:30px;height:30px;border-radius:6px;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.themebtn:hover{color:var(--ink);border-color:var(--purple);
  background:var(--purple-soft)}

*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-body);
  font-size:16px;line-height:1.6}
/* No -webkit-font-smoothing here. On Windows it turns OFF subpixel
     rendering, costing every glyph two thirds of its horizontal resolution
     and thinning the text out. Left to the operating system. */

.wrap{max-width:1060px;margin:0 auto;padding:0 20px 80px}
h1,h2,h3{font-family:var(--f-display);margin:0;text-wrap:balance}
/* Same type decisions as the app. Big and light for display, and a section
   heading with enough voice to sound written rather than generated. Kept in
   step by hand because this site carries its own copy of the stylesheet. */
h1{font-size:clamp(2.1rem,4.6vw,3rem);line-height:1.04;letter-spacing:-.034em;
  font-weight:600}
h2{font-size:1.2rem;letter-spacing:-.014em;font-weight:700;line-height:1.22}
h3{font-size:1rem;font-weight:600}
p{margin:0}
a{color:var(--purple);text-decoration:none}
a:hover{text-decoration:underline}
.label{font-family:var(--f-mono);font-size:.66rem;font-weight:600;letter-spacing:.13em;
  text-transform:uppercase;color:var(--purple)}
.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
nav.top{background:var(--surface);border-bottom:1px solid var(--border)}
.nav-in{max-width:1060px;margin:0 auto;padding:14px 20px;display:flex;gap:16px;
  align-items:center;justify-content:space-between}
.nav-links{display:flex;gap:4px;align-items:center;flex-wrap:wrap;
  justify-content:flex-end;font-size:.85rem;min-width:0}
.nav-side{display:flex;align-items:center;flex:none;padding-left:14px;
  margin-left:4px;border-left:1px solid var(--border)}
.nav-links a.here{color:var(--purple);background:var(--purple-soft)}
.subnav{background:var(--surface);border-bottom:1px solid var(--border)}
.subnav-in{max-width:1160px;margin:0 auto;padding:0 24px;height:42px;
  display:flex;gap:4px;align-items:center;overflow-x:auto}
.subnav a{color:var(--muted);font-size:.86rem;font-weight:500;padding:6px 11px;
  border-radius:6px;white-space:nowrap;text-decoration:none}
.subnav a:hover{color:var(--ink);background:var(--bg)}
.nav-links a{color:var(--muted);padding:6px 10px;border-radius:6px;
  white-space:nowrap;text-decoration:none}
.nav-links a:hover{color:var(--ink);background:var(--bg)}
@media(max-width:640px){.nav-in{flex-wrap:wrap;gap:6px}
  .nav-links{width:100%;font-size:.78rem;gap:2px}}
.mark{font-family:var(--f-display);font-weight:800;letter-spacing:-.035em;font-size:1.06rem;
  color:var(--ink)}
.mark em{font-style:normal;color:var(--purple)}
header.page{background:
  linear-gradient(180deg,var(--purple-soft) 0%,var(--surface) 100%);
  border-bottom:1px solid var(--border)}
.head-in{max-width:1060px;margin:0 auto;padding:34px 20px 28px;display:flex;
  flex-direction:column;gap:11px}
.crumb{font-size:.86rem;color:var(--muted)}
section{padding-top:38px;display:flex;flex-direction:column;gap:14px}
.sec-head{border-top:1px solid var(--border-strong);padding-top:11px;display:flex;
  flex-direction:column;gap:5px}
.lede{color:var(--muted);font-size:.92rem;max-width:70ch}
.tbl-wrap{overflow-x:auto;border:1px solid var(--border);background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th{font-family:var(--f-mono);font-size:.63rem;font-weight:500;letter-spacing:.1em;
  text-transform:uppercase;color:var(--faint);text-align:left;padding:10px 13px;
  border-bottom:1px solid var(--border-strong);white-space:nowrap}
td{padding:10px 13px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
td.name{font-weight:600;font-family:var(--f-display);white-space:nowrap}
td.num,th.num{font-family:var(--f-mono);font-variant-numeric:tabular-nums;
  white-space:nowrap;text-align:right}
th.num{text-align:right}
.den{font-family:var(--f-mono);font-size:.72rem;color:var(--faint)}
.thin{font-family:var(--f-mono);font-size:.58rem;letter-spacing:.09em;text-transform:uppercase;
  color:var(--t);border:1px solid var(--t);padding:1px 5px}
.role{font-family:var(--f-mono);font-size:.6rem;letter-spacing:.08em;text-transform:uppercase;
  padding:2px 7px;background:var(--sunk);color:var(--muted);white-space:nowrap}
.role.awp{background:var(--t-soft);color:var(--t)}
.role.entry{background:var(--purple-soft);color:var(--purple)}
.stat-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
  background:var(--border);border:1px solid var(--border)}
.stat{background:var(--surface);padding:15px 17px;display:flex;flex-direction:column;gap:2px}
.stat-n{font-family:var(--f-display);font-weight:800;font-size:1.5rem;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.maps{display:flex;flex-direction:column;gap:22px}
.mapblock{border:1px solid var(--border);background:var(--surface)}
.maphead{display:flex;align-items:baseline;gap:12px;padding:14px 16px;
  border-bottom:1px solid var(--border-strong);flex-wrap:wrap}
.maphead .score{font-family:var(--f-display);font-weight:800;font-size:1.1rem;
  font-variant-numeric:tabular-nums}
.win{color:var(--purple);font-weight:600}
.note{border-left:3px solid var(--purple);background:var(--purple-soft);padding:14px 18px;
  font-size:.9rem;max-width:72ch}
footer{margin-top:52px;padding-top:18px;border-top:1px solid var(--border);font-size:.8rem;
  color:var(--faint);display:flex;flex-direction:column;gap:5px}
:focus-visible{outline:2px solid var(--purple);outline-offset:2px}
"""

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Public+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>@@CSS@@</style><script>
(function(){try{var t=localStorage.getItem('cp-theme');
if(t){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();
function cpTheme(){var h=document.documentElement,c=h.getAttribute('data-theme'),
n=c?(c==='dark'?'light':'dark'):(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches?'light':'dark');
h.setAttribute('data-theme',n);try{localStorage.setItem('cp-theme',n)}catch(e){}}
</script></head><body>
<nav class="top"><div class="nav-in">
  <!-- The site root, not the league index. The mark is the one control every
       visitor expects to take them home, and here it took them to the page
       they were already on. A signed-in coach following it lands on their own
       dashboard; a visitor lands on the front page. -->
  <a class="mark" href="/">Counter<em>play</em></a>
  <span class="nav-links">@@NAV@@</span>
  <span class="nav-side"><button class="themebtn" type="button" onclick="cpTheme()" title="Switch between light and dark" aria-label="Switch between light and dark">&#9681;</button></span>
</div></nav>
<!-- Section navigation. The row above never changes between the app and here;
     this row says where you are inside the league pages. -->
<nav class="subnav"><div class="subnav-in">@@SUBNAV@@</div></nav>
<header class="page"><div class="head-in">@@HEAD@@</div></header>
<div class="wrap">@@BODY@@
<footer>
  <span>Built from FACEIT match statistics. Every rate shows the number it came from.</span>
  <span>Rates are hidden for players under @@MINR@@ rounds and shown as raw counts instead.</span>
</footer>
</div></body></html>"""


def page(path: Path, title: str, league: str, head: str, body: str):
    # Which section page this is, so the section bar marks it. Team and match
    # pages belong to the standings, which is where a reader came from.
    here = ("/league/leaderboards" if path.name == "leaderboards.html"
            else "/league/")
    subnav = "".join(
        f'<a href="{h}"{" class='here'" if h == here else ""}>{esc(l)}</a>'
        for h, l in (("/league/", f"{league} standings"),
                     ("/league/leaderboards", "Leaderboards")))
    out = SHELL
    # The public nav, not the app's. These pages are static and cannot know
    # whether the reader is signed in, and rendering Dashboard, Matches,
    # Players, Team stats and Trends at a visitor who has never had an account
    # is five links to a login screen. Where you are INSIDE the league pages
    # is the row underneath; this row is how you get in.
    nav = ('<a href="/sample-report">See a real report</a>'
           '<a href="/login">Log in</a>'
           '<a class="btn" href="/signup">Add your team</a>')
    for token, value in (("@@CSS@@", CSS), ("@@NAV@@", nav),
                         ("@@SUBNAV@@", subnav), ("@@TITLE@@", esc(title)),
                         ("@@LEAGUE@@", esc(league)), ("@@HEAD@@", head),
                         ("@@BODY@@", body), ("@@MINR@@", str(MIN_ROUNDS))):
        out = out.replace(token, value)
    path.write_text(out, encoding="utf-8")


def fig(value: str, den: str, thin=False) -> str:
    if thin:
        return f'<span class="den">{den}</span> <span class="thin">thin</span>'
    return f'{value} <span class="den">{den}</span>'


def player_row(p: dict, link=True) -> str:
    a = p["agg"]
    role = p.get("role", "–")
    cls = {"AWP": "role awp", "Entry": "role entry"}.get(role, "role")
    nick = esc(p["nick"])
    if p.get("multi_team"):
        others = len(p.get("maps_for", {})) - 1
        nick += (' <span class="thin" title="also played for %d other team(s) '
                 'this season">stand-in</span>' % others)
    return (
        f'<tr><td class="name">{nick}</td>'
        f'<td><span class="{cls}" title="{esc(p.get("role_why",""))}">{esc(role)}</span></td>'
        f'<td class="num">{fig(f"{a.adr:.0f}", f"{int(a.damage)}dmg / {int(a.rounds)}r", a.thin)}</td>'
        f'<td class="num">{fig(f"{a.kd:.2f}", f"{int(a.kills)}-{int(a.deaths)}", a.thin)}</td>'
        f'<td class="num">{fig(f"{a.kr:.2f}", f"{int(a.kills)} / {int(a.rounds)}r", a.thin)}</td>'
        f'<td class="num">{fig(f"{a.hs_pct:.0f}%", f"{int(a.headshots)} / {int(a.kills)}", a.thin)}</td>'
        f'<td class="num">{fig(f"{a.entry_rate:.2f}", f"{int(a.entry_count)} / {int(a.rounds)}r", a.thin)}</td>'
        f'<td class="num">{fig(f"{a.entry_success*100:.0f}%", f"{int(a.entry_wins)} / {int(a.entry_count)}", a.entry_count < 8)}</td>'
        f'<td class="num">{fig(f"{a.util_dmg_round:.1f}", f"{int(a.util_damage)} / {int(a.rounds)}r", a.thin)}</td>'
        f'<td class="num mono">{int(a.sniper)}</td>'
        f'<td class="num mono">{int(a.maps)}</td></tr>'
    )


PLAYER_HEAD = ('<thead><tr><th>Player</th><th>Role</th><th class="num">ADR</th>'
               '<th class="num">K/D</th><th class="num">K/R</th><th class="num">HS</th>'
               '<th class="num">Entry rate</th><th class="num">Entry won</th>'
               '<th class="num">Util dmg/r</th><th class="num">AWP kills</th>'
               '<th class="num">Maps</th></tr></thead>')


def render(model: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    league = model["league"]
    teams = model["teams"]
    matches = model["matches"]
    players = model["players"]

    # Standings are built per division. Teams in different divisions never play
    # each other, so ranking them in one table compares records built against
    # entirely different opposition.
    by_division = defaultdict(list)
    for t in teams.values():
        for dname, dv in t["divisions"].items():
            if dv["maps"]:
                by_division[dname].append((t, dv))

    division_blocks = []
    for dname in sorted(by_division, key=division_sort_key):
        entries = sorted(by_division[dname],
                         key=lambda pair: (pair[1]["rounds_won"] - pair[1]["rounds_lost"]),
                         reverse=True)
        rows = []
        for t, dv in entries:
            diff = dv["rounds_won"] - dv["rounds_lost"]
            rw, rl = int(dv["rounds_won"]), int(dv["rounds_lost"])
            maps_fig = fig(str(dv["map_wins"]), "of %d" % dv["maps"], dv["maps"] < 2)
            elsewhere = (' <span class="thin" title="also played in another division">'
                         'also elsewhere</span>' if t["multi_division"] else "")
            rows.append(
                '<tr><td class="name"><a href="/league/t-%s">%s</a>%s</td>'
                '<td class="num mono">%d</td><td class="num">%s</td>'
                '<td class="num mono">%d</td><td class="num mono">%d</td>'
                '<td class="num mono" style="color:var(--purple)">%s%d</td></tr>'
                % (esc(t["id"]), esc(t["name"]), elsewhere, len(dv["matches"]),
                   maps_fig, rw, rl, "+" if diff >= 0 else "", int(diff)))
        note = ("" if dname != UNDIVIDED else
                '<p class="lede">Placement, open qualifiers and regular-season play, '
                'where teams from different divisions do meet. Kept separate because a '
                'record built here is not a record built inside a division.</p>')
        division_blocks.append(
            '<section><div class="sec-head"><span class="label">%d teams</span>'
            '<h2>%s</h2></div>%s'
            '<div class="tbl-wrap"><table>'
            '<thead><tr><th>Team</th><th class="num">Matches</th>'
            '<th class="num">Maps won</th><th class="num">RW</th>'
            '<th class="num">RL</th><th class="num">Diff</th></tr></thead>'
            '<tbody>%s</tbody></table></div></section>'
            % (len(entries), esc(dname), note, "".join(rows)))

    recent = []
    for m in matches[:25]:
        names = [m["names"].get(t, t) for t in m["team_ids"]]
        maps = ", ".join(x["map"].replace("de_", "") for x in m["maps"])
        recent.append(
            '<tr><td class="name"><a href="/league/m-%s">%s</a></td>'
            '<td class="mono">%s</td><td class="mono den">%s</td>'
            '<td class="mono den">%s</td></tr>'
            % (esc(m["id"]), esc(" vs ".join(names)), esc(maps),
               esc(m.get("division", UNDIVIDED)), esc(m["championship"])))

    head = (f'<span class="label">League</span><h1>{esc(league)}</h1>'
            f'<p class="crumb">{len(teams)} teams · {len(matches)} matches with statistics · '
            f'{len(players)} players</p>')
    body = f"""
  <section>
    <div class="sec-head"><span class="label">Standings by round difference</span>
      <h2>Divisions</h2></div>
    <p class="lede">One table per division, because teams in different divisions never
      play each other: a round difference built in Division 4 says nothing about a
      Division 1 side. Within a division, ranked by rounds won minus rounds lost, which
      says more than a match record does: a 13&ndash;11 loss and a 13&ndash;2 loss are the
      same line in a win column.</p>
  </section>
  {''.join(division_blocks)}
  <section>
    <div class="sec-head"><span class="label">Best in each division</span>
      <h2>Leaderboards</h2></div>
    <p class="lede">Top ten on ADR, K/D, kills per round, headshot share, opening-duel
      success and utility damage, ranked inside each division.
      <a href="/league/leaderboards">Open the leaderboards &rarr;</a></p>
  </section>
  <section>
    <div class="sec-head"><span class="label">Most recent first</span><h2>Matches</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Match</th><th>Maps</th><th>Division</th><th>Competition</th></tr></thead>
      <tbody>{''.join(recent)}</tbody></table></div>
  </section>"""
    page(out / "index.html", f"{league} | Counterplay", league, head, body)

    # ---- leaderboards
    # Split by division for the same reason the standings are: a Division 4
    # player and a Division 1 player never share a server, so one table ranking
    # them together is comparing numbers built against different opposition.
    # Players below MIN_ROUNDS are left out entirely rather than shown with a
    # "thin" badge — a leaderboard is a ranking, and a ranking with unrankable
    # rows in it is just a list.
    boards = []
    by_div_players = defaultdict(list)
    for pl in players.values():
        team = teams.get(pl["team"])
        if team is None or pl["agg"].thin:
            continue
        by_div_players[team["home_division"]].append((pl, team))

    # Each board carries ITS OWN denominator and its own eligibility bar.
    #
    # Every board used to print "N rounds" as the sample and gate only on
    # rounds >= MIN_ROUNDS. That is the right denominator for ADR and K/R and
    # the wrong one for everything else, and it put a player who went 2-for-2
    # on opening duels top of Division 1 at "100%, 60 rounds" — a number the
    # team page itself marks thin. A page whose whole claim is that every rate
    # shows what it is a rate OF cannot be the page that gets this wrong.
    #
    #   getter  -> the rate
    #   sample  -> (count, noun) the rate is actually over
    #   floor   -> how many of those it takes to be rankable
    LEADER_COLUMNS = [
        ("ADR", lambda a: a.adr, "{:.0f}", "damage per round",
         lambda a: (a.rounds, "rounds"), MIN_ROUNDS),
        ("K/D", lambda a: a.kd, "{:.2f}", "kills per death",
         lambda a: (a.deaths, "deaths"), 20),
        ("K/R", lambda a: a.kr, "{:.2f}", "kills per round",
         lambda a: (a.rounds, "rounds"), MIN_ROUNDS),
        ("HS", lambda a: a.hs_pct, "{:.0f}%", "share of kills that were headshots",
         lambda a: (a.kills, "kills"), 30),
        ("Entry won", lambda a: a.entry_success * 100, "{:.0f}%",
         "opening duels won, of those taken",
         lambda a: (a.entry_count, "duels"), 15),
        ("Util dmg/r", lambda a: a.util_dmg_round, "{:.1f}", "utility damage per round",
         lambda a: (a.rounds, "rounds"), MIN_ROUNDS),
    ]

    for dname in sorted(by_div_players, key=division_sort_key):
        entries = by_div_players[dname]
        if len(entries) < 5:
            continue
        tables = []
        for label, getter, fmt, blurb, sample, floor in LEADER_COLUMNS:
            # Rank only players who clear THIS board's own floor, on THIS
            # board's own denominator. Dropping someone is honest; ranking them
            # off four events and printing an unrelated round count is not.
            pool = [pt for pt in entries if sample(pt[0]["agg"])[0] >= floor]
            if len(pool) < 5:
                continue
            ranked = sorted(pool, key=lambda pt: -getter(pt[0]["agg"]))[:10]
            rows = []
            for i, (pl, team) in enumerate(ranked, 1):
                a = pl["agg"]
                n, noun = sample(a)
                rows.append(
                    '<tr><td class="num mono den">%d</td>'
                    '<td class="name">%s</td>'
                    '<td class="den"><a href="/league/t-%s">%s</a></td>'
                    '<td class="num mono">%s</td>'
                    '<td class="num den">%d %s</td></tr>'
                    % (i, esc(pl["nick"]), esc(team["id"]), esc(team["name"]),
                       fmt.format(getter(a)), int(n), esc(noun)))
            tables.append(
                '<div><div class="sec-head" style="border:none;padding-top:0">'
                '<span class="label">%s</span><h3>%s</h3></div>'
                '<div class="tbl-wrap"><table><thead><tr>'
                '<th class="num">#</th><th>Player</th><th>Team</th>'
                '<th class="num">%s</th><th class="num">Sample</th>'
                '</tr></thead><tbody>%s</tbody></table></div></div>'
                % (esc(blurb), esc(label), esc(label), "".join(rows)))
        boards.append(
            '<section><div class="sec-head"><span class="label">%d ranked players</span>'
            '<h2>%s</h2></div>'
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));'
            'gap:24px">%s</div></section>'
            % (len(entries), esc(dname), "".join(tables)))

    lb_head = (f'<p class="crumb"><a href="/league/">{esc(league)}</a></p>'
               f'<span class="label">Ranked within each division</span>'
               f'<h1>Leaderboards</h1>')
    lb_body = f"""
  <section>
    <p class="lede">Top ten in each division, on each measure. Split by division because
      a Division 4 player and a Division 1 player never share a server. Ranking them
      in one table compares numbers built against different opposition, which is the
      thing this project exists not to do.</p>
    <p class="lede">Each board is ranked on its own denominator, and the Sample column
      says which one. A headshot share is a share of kills, not of rounds; an opening-duel
      rate is out of duels actually taken. Ranking those against a round count would put a
      player who went 2-for-2 on entries above one who went 40-for-60, so a player has to
      clear a floor on the thing the board is actually measuring: {MIN_ROUNDS} rounds
      for the per-round measures, 20 deaths for K/D, 30 kills for headshots, 15 duels for
      entries. Anything under that is left out.</p>
    <p class="lede">Left out rather than shown with a warning label: a ranking with
      unrankable rows in it is just a list.</p>
  </section>
  {''.join(boards)}"""
    page(out / "leaderboards.html", f"Leaderboards | {league} | Counterplay",
         league, lb_head, lb_body)

    # ---- team pages
    for t in teams.values():
        roster = sorted([p for p in players.values() if p["team"] == t["id"]],
                        key=lambda p: -p["agg"].adr)
        prows = "".join(player_row(p) for p in roster)

        maprows = []
        for mp, (w, played) in sorted(t["map_record"].items(),
                                      key=lambda kv: -kv[1][1]):
            badge = ' <span class="thin">thin</span>' if played < 3 else ""
            maprows.append('<tr><td class="name">%s</td>'
                           '<td class="num">%d <span class="den">of %d</span>%s</td></tr>'
                           % (esc(mp.replace("de_", "")), w, played, badge))

        tmatches = [m for m in matches if t["id"] in m["team_ids"]][:40]
        mrows = []
        for m in tmatches:
            opp = [m["names"].get(x, x) for x in m["team_ids"] if x != t["id"]]
            won = sum(1 for mp in m["maps"]
                      for s in mp["sides"] if s["id"] == t["id"] and s["won"])
            mrows.append(
                '<tr><td class="name"><a href="/league/m-%s">%s</a></td>'
                '<td class="num mono">%d / %d</td><td class="mono den">%s</td></tr>'
                % (esc(m["id"]), esc(opp[0] if opp else "?"), won, len(m["maps"]),
                   esc(m["championship"])))

        diff = t["rounds_won"] - t["rounds_lost"]
        div_line = esc(t["home_division"])
        if t["multi_division"]:
            others = ", ".join(sorted(d for d, v in t["divisions"].items()
                                      if v["maps"] and d != t["home_division"]))
            div_line += f' &middot; also played {esc(others)}'
        head = (f'<p class="crumb"><a href="/league/">{esc(league)}</a> '
                f'&middot; {div_line}</p>'
                f'<h1>{esc(t["name"])}</h1>')
        body = f"""
  <section>
    <div class="stat-row">
      <div class="stat"><span class="stat-n">{t["matches"]}</span><span class="label">matches</span></div>
      <div class="stat"><span class="stat-n">{t["map_wins"]}/{t["maps"]}</span><span class="label">maps won</span></div>
      <div class="stat"><span class="stat-n">{int(t["rounds_won"])}</span><span class="label">rounds won</span></div>
      <div class="stat"><span class="stat-n">{"+" if diff>=0 else ""}{int(diff)}</span><span class="label">round difference</span></div>
    </div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Roles are observed, not declared</span>
      <h2>Roster</h2></div>
    <p class="lede">Roles come from what players actually did: AWP kills, who takes the
      opening duel, who throws the utility. Hover a role to see the numbers behind it.
      In-game leader can't be seen in match data, so it isn't guessed at.
      A player is listed with the team they played the most maps for; anyone who
      also turned out elsewhere this season is marked.</p>
    <div class="tbl-wrap"><table>{PLAYER_HEAD}<tbody>{prows}</tbody></table></div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Where they play well</span><h2>Maps</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Map</th><th class="num">Won</th></tr></thead>
      <tbody>{''.join(maprows)}</tbody></table></div>
  </section>
  <section>
    <div class="sec-head"><span class="label">Match history</span><h2>Matches</h2></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Opponent</th><th class="num">Maps won</th><th>Competition</th></tr></thead>
      <tbody>{''.join(mrows)}</tbody></table></div>
  </section>"""
        page(out / f"t-{t['id']}.html", f"{t['name']} | Counterplay", league, head, body)

    # ---- match pages
    for m in matches:
        blocks = []
        for mp in m["maps"]:
            sides = mp["sides"]
            head_bits = []
            for s in sides:
                cls = "win" if s["won"] else ""
                head_bits.append('<span class="%s">%s <span class="score">%d</span></span>'
                                 % (cls, esc(s["name"]), int(s["score"])))
            tables = []
            for s in sides:
                rows_ = []
                for pl in sorted(s["roster"], key=lambda x: -num(x["stats"], "ADR")):
                    ps = pl["stats"]
                    rows_.append(
                        '<tr><td class="name"><a href="/league/t-%s">%s</a></td>'
                        '<td class="num mono">%d-%d-%d</td><td class="num mono">%.0f</td>'
                        '<td class="num mono">%d%%</td><td class="num mono">%d/%d</td>'
                        '<td class="num mono">%d</td><td class="num mono">%d</td>'
                        '<td class="num mono">%d</td></tr>'
                        % (esc(s["id"]), esc(pl["nick"]),
                           int(num(ps, "Kills")), int(num(ps, "Deaths")), int(num(ps, "Assists")),
                           num(ps, "ADR"), int(num(ps, "Headshots %")),
                           int(num(ps, "Entry Wins")), int(num(ps, "Entry Count")),
                           int(num(ps, "Utility Damage")), int(num(ps, "Sniper Kills")),
                           int(num(ps, "MVPs"))))
                tables.append(
                    '<div class="tbl-wrap" style="border:none;border-top:1px solid var(--border)">'
                    '<table><thead><tr><th>%s</th><th class="num">K-D-A</th>'
                    '<th class="num">ADR</th><th class="num">HS</th><th class="num">Entry</th>'
                    '<th class="num">Util dmg</th><th class="num">AWP</th><th class="num">MVP</th>'
                    '</tr></thead><tbody>%s</tbody></table></div>'
                    % (esc(s["name"]), "".join(rows_)))
            blocks.append(
                '<div class="mapblock"><div class="maphead">'
                '<span class="label">%s</span>%s'
                '<span class="den">%d rounds</span></div>%s</div>'
                % (esc(mp["map"].replace("de_", "")), " &middot; ".join(head_bits),
                   int(mp["rounds"]), "".join(tables)))

        names = [m["names"].get(t, t) for t in m["team_ids"]]
        links = " · ".join('<a href="/league/t-%s">%s</a>' % (esc(t), esc(m["names"].get(t, t)))
                           for t in m["team_ids"])
        head = (f'<p class="crumb"><a href="/league/">{esc(league)}</a> · {esc(m["championship"])}</p>'
                f'<h1>{esc(" vs ".join(names))}</h1><p class="crumb">{links}</p>')
        body = f"""
  <section>
    <div class="sec-head"><span class="label">Every map, both teams</span><h2>Scoreboards</h2></div>
    <div class="maps">{''.join(blocks)}</div>
  </section>
  <section>
    <p class="note">These are FACEIT's own match statistics, not estimates. Round-by-round
      detail, economy and positioning need the match demo, which is a separate step.</p>
  </section>"""
        page(out / f"m-{m['id']}.html", f"{' vs '.join(names)} | Counterplay", league, head, body)

    return len(teams), len(matches), len(players)


def main() -> int:
    global MIN_ROUNDS
    ap = argparse.ArgumentParser(description="Build the Counterplay league site")
    ap.add_argument("--cache", default="cache/league.json")
    ap.add_argument("--out", default="../site/league")
    ap.add_argument("--min-rounds", type=int, default=MIN_ROUNDS)
    args = ap.parse_args()
    MIN_ROUNDS = args.min_rounds

    src = Path(args.cache)
    if not src.exists():
        print(f"No {src} - run fetch.py first.")
        return 2

    league = json.loads(src.read_text(encoding="utf-8"))
    model = build_model(league)
    assign_roles(model)
    t, m, p = render(model, Path(args.out))
    print(f"built {t} team pages, {m} match pages, {p} players -> {args.out}")
    print(f"open {Path(args.out) / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
