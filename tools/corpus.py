"""Build the collegiate corpus out of a championship, one download at a time.

    python tools/corpus.py --status              what is in, what is missing
    python tools/corpus.py --todo                room links still to download
    python tools/corpus.py --todo --open 10      ...and open the next 10 in a browser
    python tools/corpus.py --ingest "C:/demos"   queue and parse a folder

WHY THIS IS A GRIND AND WILL STAY ONE
-------------------------------------
The demo host is behind Cloudflare bot protection, so nothing scripted can
fetch a file: not curl, not urllib, not from any address tried. A person in
a browser walks through. See "FACEIT is behind Cloudflare" in CLAUDE.md.

So the download cannot be automated and this does not pretend otherwise. It
does the two parts that can be: working out what is still missing, and
turning a folder of downloads into parsed rows.

WHY THE CORPUS IS NOT ACCOUNTS
------------------------------
Every row goes in with `team_id = NULL` and `tier = 'league'`, which is the
path pull.py was built for. That matters beyond tidiness: the privacy page
promises league numbers are "situation rates by map, side and tier, not
profiles of individual players who never signed up". Aggregate baselines keep
that promise. A team row per school would break it.

WHY THE TIER MATTERS MORE THAN THE COUNT
----------------------------------------
The corpus is currently 104 pro, 11 premier, 4 league. A decision engine
trained on that is a model of how professionals play, and the product's one
real claim is that it never measures a college roster against professionals.
Collegiate matches at tier=league are the only training data that does not
contradict the homepage.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MATCHES_CSV = ROOT / "outreach" / "fall-2026-matches.csv"

# Where the downloads land. Everything in here is treated as tier=league, so
# keep professional demos out of it: pull.py is blunt that mislabelling one
# teaches the model that college players retake like professionals.
DEFAULT_FOLDER = pathlib.Path.home() / "Downloads" / "Collegiate demos"
MATCH_ID = re.compile(r"/room/(1-[0-9a-f-]+)", re.I)


def wanted() -> list[dict]:
    """Every finished match in the championship, from the saved CSV."""
    if not MATCHES_CSV.is_file():
        sys.exit("no %s: run tools/allmatches.py first" % MATCHES_CSV.name)
    with MATCHES_CSV.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["state"] == "FINISHED"]
    out = []
    for r in rows:
        m = MATCH_ID.search(r["room_url"] or "")
        if m and (r["team_b"] or "").lower() != "bye":
            r["match_id"] = m.group(1)
            out.append(r)
    return out


def have(db) -> dict[str, int]:
    """{match id: how many of its maps are parsed}.

    Keyed off the filename, because that is the only link between bytes in the
    database and the room they came from: FACEIT names a download
    1-<uuid>-<series>-<map>.dem.zst.

    Counting MAPS rather than matches matters. A match that goes to two maps
    arrives as two files, and an earlier version keyed on the match id alone,
    so downloading map 1 marked the whole match done and map 2 fell out of
    --todo for good. A tool whose only job is saying what is missing must not
    quietly stop mentioning something.
    """
    got: dict[str, int] = {}
    for row in db.query("SELECT filename FROM demos WHERE status = 'parsed'"):
        m = re.match(r"(1-[0-9a-f-]{36})", row["filename"] or "", re.I)
        if m:
            got[m.group(1).lower()] = got.get(m.group(1).lower(), 0) + 1
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--todo", action="store_true")
    ap.add_argument("--open", type=int, default=0,
                    help="open the next N room links in your browser")
    ap.add_argument("--ingest", metavar="FOLDER", nargs="?", const=str(DEFAULT_FOLDER),
                    help="queue and parse every demo in a folder at tier=league "
                         "(defaults to %s)" % DEFAULT_FOLDER)
    args = ap.parse_args()

    import os
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    os.chdir(ROOT)
    from app import db, ingest, pull
    db.init()

    if args.ingest:
        folder = pathlib.Path(args.ingest)
        if not folder.is_dir():
            return print("no such folder: %s" % folder) or 2
        print("ingesting from %s" % folder)
        # tier=league is the whole point. A pro demo in this folder would
        # teach the model that college players retake like professionals.
        res = pull.from_directory(folder, tier="league")
        print("saw %(seen)d file(s), queued %(queued)d, already known %(already_queued)d"
              % res)
        pending = db.query("SELECT * FROM demos WHERE status = 'pending' "
                           "AND tier = 'league' ORDER BY id")
        print("parsing %d..." % len(pending))
        ok = bad = 0
        for i, row in enumerate(pending, 1):
            good, note = ingest.process(row)
            ok, bad = ok + bool(good), bad + (not good)
            print("  [%3d/%3d] %-46s %s" % (i, len(pending),
                                            (row["filename"] or "")[:46],
                                            note[:70]))
        print("\nparsed %d, failed %d" % (ok, bad))

    rows, got = wanted(), have(db)
    missing = [r for r in rows if r["match_id"].lower() not in got]
    maps_in = sum(got.get(r["match_id"].lower(), 0) for r in rows)
    multi = sorted(r for r in rows if got.get(r["match_id"].lower(), 0) > 1)  # noqa

    if args.status or not (args.todo or args.ingest):
        by_tier = {r["tier"]: r["n"] for r in db.query(
            "SELECT tier, COUNT(*) n FROM demos WHERE status='parsed' GROUP BY tier")}
        extra = maps_in - (len(rows) - len(missing))
        print("championship matches with a demo to get   %d" % len(rows))
        print("  at least one map parsed                 %d" % (len(rows) - len(missing)))
        print("  still to download                       %d" % len(missing))
        print("  maps parsed in total                    %d%s"
              % (maps_in,
                 "  (%d of them second maps of a match)" % extra if extra else ""))
        if extra:
            print()
            print("  A match can go to more than one map, and the championship")
            print("  CSV has no map column, so this cannot tell you in advance")
            print("  which ones did. Check a room for a second demo before")
            print("  ticking it off.")
        print()
        print("whole corpus by tier: %s" % (by_tier or "empty"))
        league = by_tier.get("league", 0)
        print()
        if league < 40:
            print("tier=league is %d. The calibration gate needs matches, not code;" % league)
            print("README is explicit that a failing gate means more matches.")
        else:
            print("tier=league is %d. Worth trying:  python run.py --db --tier league" % league)

    if args.todo:
        print("\n%d still to download. Open the ROOM link, not the raw demo url:\n"
              % len(missing))
        for r in missing[:200]:
            print("r%s g%-3s %-24s vs %-24s" % (r["round"], r["group"],
                                                r["team_a"], r["team_b"]))
            print("    %s" % r["room_url"])
        if args.open:
            for r in missing[:args.open]:
                webbrowser.open(r["room_url"])
            print("\nopened %d in your browser." % min(args.open, len(missing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
