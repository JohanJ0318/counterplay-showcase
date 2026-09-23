"""Run ONE demo file through the parser and print what came out.

    python tools/parse1.py "C:/path/to/match.dem.bz2"

Why this exists: `run.py --demos` wants a directory and is about training.
This is for the other question, the one you ask when a coach says "it did not
work": does this specific file parse, and what does it contain.

It accepts whatever the file actually is, by magic number and not extension:
zstd (FACEIT, historically), gzip (FACEIT today), bzip2 (Valve matchmaking),
or a raw .dem. Nothing is written to the database and nothing is uploaded;
the expanded copy goes to a temp directory and is deleted on the way out.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import ingest  # noqa: E402


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.0f%s" % (n, unit)
        n /= 1024
    return "%.1fTB" % n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("demo", help="path to a .dem, .dem.zst, .dem.gz or .dem.bz2")
    ap.add_argument("--tier", default="league")
    ap.add_argument("--keep", action="store_true",
                    help="leave the expanded .dem behind, for the parser people")
    args = ap.parse_args()

    src = pathlib.Path(args.demo)
    if not src.is_file():
        print("no such file: %s" % src)
        return 2

    packing = ingest.packing_of(src)
    print("file     %s" % src.name)
    print("size     %s" % human(src.stat().st_size))
    print("packing  %s" % (packing or "none, already a raw .dem"))

    work = pathlib.Path(tempfile.mkdtemp(prefix="parse1-"))
    try:
        if packing:
            playable = work / "demo.dem"
            t0 = time.time()
            n = ingest.decompress(src, playable)
            print("expanded %s in %.1fs" % (human(n), time.time() - t0))
        else:
            playable = src

        t0 = time.time()
        rounds, events, players, positions, util, map_name = \
            ingest.parse_to_frames(playable, tier=args.tier)
        print("parsed   %.1fs" % (time.time() - t0))
        print()
        print("map      %s" % (map_name or "unknown"))
        print("rounds   %d" % len(rounds))
        print("events   %d" % len(events))
        print("players  %d" % (len(players) if players is not None else 0))

        ok, summary = ingest.check(rounds, events)
        print()
        print("validate %s" % ("PASS" if ok else "FAIL"))
        print("         %s" % summary)

        if args.keep:
            kept = src.parent / (src.stem.replace(".dem", "") + ".expanded.dem")
            shutil.copy2(playable, kept)
            print("\nkept     %s" % kept)
        return 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
