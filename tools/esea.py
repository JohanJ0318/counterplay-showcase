"""ESEA League matches for the training corpus: list, open, ingest.

    python tools/esea.py --list               write the match list (needs the key)
    python tools/esea.py --status             how many are downloaded and parsed
    python tools/esea.py --open 10            open the next 10 rooms in a browser
    python tools/esea.py --ingest "C:/demos"  parse a folder at tier=esea

WHY ESEA
--------
ESEA Open, Intermediate and Main are the closest public level to NECC
college play, closer than pro (ml/README.md: the network gains from more
data, and pro is the wrong population). They go in as tier "esea", never
"league": the college reference files, league.judge and every collegiate
test read tier='league' only, and an ESEA match counted there would be a
non-college team measured as a college one.

WHERE THEY ARE
--------------
ESEA runs on FACEIT. Each season is a tree of "championships", one per
region, division and conference (found 2026-10-14 through the season page's
own team-leagues API, which FACEIT's public Data API does not expose). The
IDs below are Season 58 North America regular seasons, which finished on
2026-09-28, so every match in them is complete.

DOWNLOADING
-----------
Same as the college corpus (CLAUDE.md, "FACEIT is behind Cloudflare"):
nothing scripted can fetch a demo. --open opens room pages; in each, Watch
demo downloads it. Keep ESEA files in their OWN folder.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIST = ROOT / "data" / "esea-s58-na.csv"
DEFAULT_FOLDER = Path.home() / "Downloads" / "ESEA demos"

# Season 58, North America, regular seasons. Open1-8 is the closest to most
# NECC teams, Intermediate and Main to the top of NECC Division 1.
DIVISIONS = {
    "Main A": "2173e911-8a3c-45d8-a929-f803fee740ba",
    "Main B": "33c94aa7-6909-4b03-a8d8-cac136e7274e",
    "Intermediate A": "f03afa24-ad7f-47a1-8f54-9c2fa1c10ff7",
    "Intermediate B": "be8ec630-aceb-4f51-8ba6-636376ad337f",
    "Open1-8 East": "9588d514-014c-431d-aba4-5d0763d16aa6",
    "Open1-8 West": "94057a72-b64e-4461-a8f1-c1fb9d95e091",
}
# Interleave the divisions in the download order, so a first batch of 30 is
# a mix of levels and not 30 Main matches.
ORDER = ["Intermediate A", "Open1-8 East", "Main A", "Intermediate B",
         "Open1-8 West", "Main B"]


def api_key() -> str:
    """FACEIT_API_KEY from the environment or the Windows user environment.
    Read, never printed."""
    k = os.environ.get("FACEIT_API_KEY", "")
    if not k and os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = winreg.QueryValueEx(h, "FACEIT_API_KEY")[0]
        except OSError:
            pass
    return k


def get(path: str, **q):
    url = "https://open.faceit.com/data/v4" + path + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + api_key(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_matches() -> list[dict]:
    rows = []
    for div in ORDER:
        cid = DIVISIONS[div]
        for off in range(0, 2000, 100):
            try:
                items = get(f"/championships/{cid}/matches", type="past",
                            offset=off, limit=100).get("items", [])
            except urllib.error.HTTPError as e:
                if e.code == 400:      # the Data API refuses offsets past 1,000
                    break
                raise
            for m in items:
                if m.get("status") != "FINISHED":
                    continue
                teams = [t.get("name", "?") for t in (m.get("teams") or {}).values()]
                if any(t.strip().lower() == "bye" for t in teams):
                    continue                    # a bye was never played
                rows.append({"division": div, "match_id": m["match_id"],
                             "teams": " vs ".join(teams),
                             "room": f"https://www.faceit.com/en/cs2/room/{m['match_id']}"})
            if len(items) < 100:
                break
        print(f"  {div}: {sum(r['division'] == div for r in rows)} finished",
              file=sys.stderr)
    # Interleave so the list reads one of each division in turn.
    by = {d: [r for r in rows if r["division"] == d] for d in ORDER}
    mixed = []
    for i in range(max(len(v) for v in by.values())):
        mixed += [by[d][i] for d in ORDER if i < len(by[d])]
    return mixed


def read_list() -> list[dict]:
    if not LIST.exists():
        sys.exit(f"no {LIST.name}: run python tools/esea.py --list first")
    with LIST.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def have() -> set[str]:
    """Match ids already queued or parsed, from demo filenames."""
    from app import db
    db.init()
    out = set()
    for r in db.query("SELECT filename FROM demos WHERE tier = 'esea'"):
        name = r["filename"] or ""
        if name.startswith("1-") and len(name) > 38:
            out.add(name[:38])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--open", type=int, default=0)
    ap.add_argument("--ingest", metavar="FOLDER", nargs="?",
                    const=str(DEFAULT_FOLDER))
    args = ap.parse_args()
    if args.list:
        if not api_key():
            sys.exit("FACEIT_API_KEY is not set")
        rows = list_matches()
        LIST.parent.mkdir(parents=True, exist_ok=True)
        with LIST.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["division", "match_id", "teams", "room"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {LIST.relative_to(ROOT)}: {len(rows)} matches")
    if args.status or args.open:
        rows, got = read_list(), have()
        todo = [r for r in rows if r["match_id"] not in got]
        print(f"{len(rows)} listed, {len(rows) - len(todo)} in the corpus, "
              f"{len(todo)} to go")
        for r in todo[:args.open]:
            print(f"  opening {r['division']}: {r['teams']}")
            webbrowser.open(r["room"])
    if args.ingest:
        from app import db, pull
        db.init()
        folder = Path(args.ingest)
        if not folder.is_dir():
            sys.exit(f"no folder {folder}")
        # tier=esea is the whole point: see the docstring.
        print(pull.from_directory(folder, tier="esea"))
        print("now run: python -m app.worker --once")


if __name__ == "__main__":
    main()
