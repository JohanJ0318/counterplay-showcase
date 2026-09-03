"""Queue league demos for parsing.

    python -m app.pull --cache ../Downloads/counterplay-league/gen/cache --check
    python -m app.pull --cache <dir> --limit 50
    python -m app.pull --match 1-4cfc1e19-5a34-4b79-9b00-772c4d9d794a

Reads a `fetch.py` cache, works out which matches still have downloadable
demos, and inserts a queue row for each. It does not download anything — the
worker does that, one at a time, so a pull of 780 matches is a fast database
write rather than a 150GB transfer that has to survive being interrupted.

**These demos build aggregate baselines. They do not build team profiles.**
Every row is inserted with `team_id = NULL` and `source = 'league'`. A team that
never signed up never gets a page, a report, or a profile out of this. When a
team does sign up and claims its FACEIT id, its own matches are attributed to it
— which means a coach gets a full season without uploading anything.

--check is worth running first. Demo links expire, and it HEADs a sample so you
find out whether a season is still reachable before queueing 1,700 downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import db, faceit, ingest


def queue_url(url: str, *, match_id: str | None, competition: str,
              tier: str, filename: str) -> bool:
    """Insert one demo queue row. False if it was already there."""
    if db.one("SELECT id FROM demos WHERE source_url = ?", url):
        return False
    # The real sha256 is not known until the bytes arrive. Key the placeholder
    # on the URL so the row is unique and the file lands under a stable name;
    # ingest replaces nothing about it, and dedupe on this path is by URL.
    placeholder = hashlib.sha256(url.encode("utf-8")).hexdigest()
    db.execute(
        """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes, sha256,
                              tier, status, created_at, source, faceit_match_id,
                              source_url, competition)
           VALUES (NULL, NULL, ?, 0, ?, ?, 'pending', ?, 'league', ?, ?, ?)""",
        filename[:200], placeholder, tier, db.utcnow(), match_id, url,
        competition[:200])
    return True


def from_cache(cache_dir: Path, *, limit: int | None, tier: str,
               resolve: bool, verbose: bool = True) -> dict:
    """Queue every cached match that has a demo. Returns a summary."""
    seen = queued = skipped = no_demo = 0
    for m in faceit.iter_cached_matches(cache_dir):
        if limit is not None and queued >= limit:
            break
        seen += 1
        urls = m["demo_urls"]
        if not urls and resolve:
            # The cached link is missing or the fetch predates demo capture.
            # The public endpoint still knows, and needs no API key.
            urls = faceit.resolve_demo_urls(m["match_id"])
        if not urls:
            no_demo += 1
            continue
        for i, url in enumerate(urls, 1):
            if limit is not None and queued >= limit:
                break                      # a multi-map match must not overshoot
            name = f"{m['match_id']}-map{i}.dem.zst"
            if queue_url(url, match_id=m["match_id"], competition=m["competition"],
                         tier=tier, filename=name):
                queued += 1
                if verbose and queued % 50 == 0:
                    print(f"  queued {queued} ...", flush=True)
            else:
                skipped += 1
    return {"matches_seen": seen, "queued": queued,
            "already_queued": skipped, "no_demo": no_demo}


def from_directory(directory: Path, tier: str, limit: int | None = None) -> dict:
    """Queue every .dem / .dem.zst in a folder, tagged with its tier.

    One tier per folder, deliberately. Mislabeling a professional match as
    Premier teaches the model that Premier players retake like professionals,
    and every number a coach later sees inherits it.

    Nothing is copied here. The queue row points at the file where it already
    lives; the worker reads it there and writes a compressed archive only once
    the parse has succeeded.
    """
    queued = skipped = 0
    files = sorted(p for p in directory.iterdir()
                   if p.suffix.lower() == ".dem"
                   or p.name.lower().endswith(".dem.zst"))
    for f in files:
        if limit is not None and queued >= limit:
            break
        url = ingest.path2url(f)
        if db.one("SELECT id FROM demos WHERE source_url = ?", url):
            skipped += 1
            continue
        # The real hash is not known until the bytes are read. Key the
        # placeholder on the path so the row is unique; ingest replaces it with
        # the true sha256 once it has parsed the file.
        placeholder = hashlib.sha256(url.encode("utf-8")).hexdigest()
        db.execute(
            """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes,
                                  sha256, tier, status, created_at, source,
                                  source_url)
               VALUES (NULL, NULL, ?, ?, ?, ?, 'pending', ?, 'local', ?)""",
            f.name[:200], f.stat().st_size, placeholder, tier, db.utcnow(), url)
        queued += 1
    return {"seen": len(files), "queued": queued, "already_queued": skipped}


def check_sample(cache_dir: Path, n: int = 8) -> None:
    """HEAD a few demo URLs, newest first, to see whether links still resolve.

    Worth doing before a bulk pull: an expired season fails 1,700 times slowly,
    and this tells you in twenty seconds.
    """
    rows = [m for m in faceit.iter_cached_matches(cache_dir) if m["demo_urls"]]
    print(f"{len(rows)} cached matches carry a demo URL. "
          f"Checking the {min(n, len(rows))} most recent:\n")
    live = dead = 0
    for m in rows[:n]:
        url = m["demo_urls"][0]
        status, size = faceit.head(url)
        if status == 200:
            live += 1
            print(f"  LIVE  {size/1e6:7.1f} MB  {m['competition'][:38]}")
        else:
            dead += 1
            print(f"  {str(status or 'unreachable'):>9}  "
                  f"{'':10} {m['competition'][:38]}")
    print(f"\n{live} live, {dead} not.")
    if live == 0:
        print("\nNo cached link resolved. Either the links have expired, or this\n"
              "machine cannot reach the demo CDN. Try the URL in a browser before\n"
              "concluding the season is gone — and re-run fetch.py, since a fresh\n"
              "fetch gets fresh links for anything still hosted.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Queue league demos for parsing")
    ap.add_argument("--cache", type=str, help="a fetch.py cache directory")
    ap.add_argument("--dir", type=str,
                    help="a folder of .dem files already on this machine")
    ap.add_argument("--match", action="append", default=[],
                    help="a single FACEIT match id (repeatable)")
    ap.add_argument("--tier", default="league",
                    choices=["pro", "collegiate", "league", "premier"])
    ap.add_argument("--limit", type=int, help="queue at most this many")
    ap.add_argument("--check", action="store_true",
                    help="HEAD a sample of demo URLs and stop")
    ap.add_argument("--resolve", action="store_true",
                    help="ask the public endpoint for matches with no cached URL")
    ap.add_argument("--forget-unreachable", action="store_true",
                    help="drop queued league demos whose host does not resolve")
    args = ap.parse_args()

    # --forget-unreachable is a maintenance command; it operates on the queue
    # already in the database and needs neither a cache nor a match id.
    if not (args.forget_unreachable or args.cache or args.match or args.dir):
        ap.error("pass --dir <folder>, --cache <dir>, --match <id>, "
                 "or --forget-unreachable")

    db.init()

    if args.check:
        if not args.cache:
            ap.error("--check needs --cache")
        check_sample(Path(args.cache))
        return 0

    if args.forget_unreachable:
        # As of August 2026 every demos-*.faceit-cdn.net hostname resolves to
        # no address at all, while other subdomains of the same zone are
        # healthy. The API still returns those URLs. Nothing can fetch them, so
        # queued rows pointing there are not "pending", they are impossible.
        rows = db.query("""SELECT id FROM demos WHERE source='league'
                            AND status='pending' AND source_url <> ''""")
        for r in rows:
            db.execute("DELETE FROM demos WHERE id = ?", r["id"])
        print(f"dropped {len(rows)} unreachable league demo(s) from the queue")
        print("Uploads and any demo already on disk are untouched.")
        return 0

    if args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            ap.error(f"not a folder: {d}")
        s = from_directory(d, args.tier, args.limit)
        print(f"{s['seen']} demo file(s) in {d.name}")
        print(f"{s['queued']} queued as tier '{args.tier}'")
        print(f"{s['already_queued']} already in the queue")

    total = 0
    for mid in args.match:
        urls = faceit.resolve_demo_urls(mid)
        if not urls:
            print(f"  no demo available for {mid}")
            continue
        for i, url in enumerate(urls, 1):
            if queue_url(url, match_id=mid, competition="", tier=args.tier,
                         filename=f"{mid}-map{i}.dem.zst"):
                total += 1
                print(f"  queued {mid} map {i}")
    if args.match:
        print(f"\n{total} queued")

    if args.cache:
        s = from_cache(Path(args.cache), limit=args.limit, tier=args.tier,
                       resolve=args.resolve)
        print(f"\n{s['matches_seen']} matches seen")
        print(f"{s['queued']} demos queued")
        print(f"{s['already_queued']} already in the queue")
        print(f"{s['no_demo']} matches with no demo link")

    pending = db.one("SELECT COUNT(*) n FROM demos WHERE status='pending'")["n"]
    print(f"\n{pending} demos pending. Run:  python -m app.worker --once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
