"""What is happening in a FACEIT championship, and where the demos are.

    python tools/tonight.py                      # every team, match state
    python tools/tonight.py --team "Fisher"      # just one
    python tools/tonight.py --ready              # only finished, with demos

WHY THIS STOPS SHORT OF DOWNLOADING
-----------------------------------
It prints demo URLs. It does not fetch them, because it cannot: the demo
host is behind Cloudflare bot protection and refuses every scripted client,
from every address tried, browser headers included. Only a real browser gets
through. So the last step is yours: click the link.

That is not a workaround waiting to be written. See "FACEIT is behind
Cloudflare" in CLAUDE.md. Everything else here works from a home
connection and nothing works from the Hetzner box.

No API key needed. These are the endpoints the website itself calls.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

CHAMPIONSHIP = "d36e9c78-22a9-4862-bb29-dac8ebb93e77"  # Fall 2026 Placements
BASE = "https://www.faceit.com/api"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TEAMS_CSV = pathlib.Path(__file__).resolve().parent.parent / \
    "outreach" / "fall-2026-teams.csv"


def get(url: str):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("\n403 from FACEIT. If you are on the server, that is "
                  "Cloudflare blocking the datacenter range; run this from "
                  "your own machine.", file=sys.stderr)
        return None
    except Exception:
        return None


def load_teams() -> dict[str, str]:
    """{faceit_team_id: name} from the CSV, so output reads in English."""
    if not TEAMS_CSV.is_file():
        return {}
    with TEAMS_CSV.open(encoding="utf-8") as fh:
        return {r["faceit_team_id"]: r["team"] for r in csv.DictReader(fh)}


def matches_for(team_id: str, championship: str):
    url = (f"{BASE}/championships/v1/matches?championshipId={championship}"
           f"&participantType=TEAM&participantId={team_id}&limit=20&offset=0")
    d = get(url)
    if not d:
        return []
    payload = d.get("payload") or {}
    return payload.get("items") or payload if isinstance(payload, dict) else []


def demo_urls(match_id: str) -> list[str]:
    """The public match endpoint. No key, no login, works from home."""
    d = get(f"https://api.faceit.com/match/v2/match/{match_id}")
    if not d:
        return []
    p = d.get("payload") or {}
    for key in ("demoURLs", "demo_urls", "demoUrls"):
        if p.get(key):
            return list(p[key])
    return []


def resolves(url: str) -> bool:
    """Does the demo host exist in DNS at all?

    FACEIT hands out URLs on hosts that sometimes do not resolve, which is
    the other half of the "dead links" story in TODO.md: some of those were
    NXDOMAIN rather than 403. On the night of 2026-09-23 every demo for the
    placements tournament pointed at demos-us-east.backblaze.faceit-cdn.net,
    which answered NXDOMAIN on four separate resolvers while the older
    demos-us-central1 host resolved fine. Probably processing lag on their
    side. Worth saying out loud rather than handing over a link that cannot
    be clicked.
    """
    import socket
    import urllib.parse
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def when(ms) -> str:
    if not ms:
        return "?"
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return t.astimezone(dt.timezone(dt.timedelta(hours=-4))).strftime(
        "%a %H:%M EDT")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--championship", default=CHAMPIONSHIP)
    ap.add_argument("--team", default="", help="substring of a team name")
    ap.add_argument("--ready", action="store_true",
                    help="only matches that are finished and have a demo")
    args = ap.parse_args()

    names = load_teams()
    if not names:
        print("no outreach/fall-2026-teams.csv, so team ids stay as ids\n")

    wanted = [(tid, nm) for tid, nm in names.items()
              if args.team.lower() in nm.lower()] or \
             ([(args.team, args.team)] if args.team else [])
    if not wanted:
        wanted = list(names.items())
    if not wanted:
        print("nothing to look up: pass --team with a FACEIT team id")
        return 2

    print("%d team(s), championship %s\n" % (len(wanted), args.championship))
    found = 0
    for tid, nm in wanted:
        rows = matches_for(tid, args.championship)
        if not rows:
            continue
        for m in rows:
            origin = m.get("origin") or {}
            mid, state = origin.get("id", "?"), origin.get("state", "?")
            other = [f["id"] for f in (m.get("factions") or [])
                     if f.get("id") != tid]
            opp = names.get(other[0], other[0][:8] if other else "?")
            urls = demo_urls(mid) if state not in ("SCHEDULED",) else []

            if args.ready and not urls:
                continue
            found += 1
            print("%-26s r%s vs %-24s %-10s %s"
                  % (nm, m.get("round", "?"), opp, state,
                     when(origin.get("schedule"))))
            print("    https://www.faceit.com/en/cs2/room/%s" % mid)
            for u in urls:
                if resolves(u):
                    print("    DEMO: %s" % u)
                else:
                    print("    DEMO: %s" % u)
                    print("          ^ host does not resolve yet (NXDOMAIN).")
                    print("            FACEIT is still processing it. Try later.")
            print()

    if not found:
        print("No matches to show yet."
              if not args.ready else
              "No finished matches with demos yet. Try again after games end.")
    else:
        print("Open a DEMO link in your browser to download it. curl will not\n"
              "work: Cloudflare refuses scripted clients. Then:\n"
              "    python tools/parse1.py <the file you downloaded>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
