"""Parse every reachable demo again, in this process, against the local DB.

    python tools/reparse.py                 every kept demo
    python tools/reparse.py --tier league   one tier

For when parse.py learns something new (migration 23, per-player money) and
the corpus should carry it. The worker does the same job one demo at a time
on the box; this is for the local database, where there is no worker. Back
the database up first: a parse replaces a match's rows.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier")
    args = ap.parse_args()
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    os.chdir(ROOT)
    from app import db, ingest
    db.init()

    queued = ingest.reparse_all(args.tier)
    pending = db.query("SELECT * FROM demos WHERE status = 'pending' ORDER BY id")
    print(f"queued {queued}, parsing {len(pending)}", flush=True)
    ok = bad = 0
    t0 = time.time()
    for i, row in enumerate(pending, 1):
        good, note = ingest.process(row)
        ok, bad = ok + bool(good), bad + (not good)
        print(f"  [{i:3d}/{len(pending)}] {(row['filename'] or '')[:46]:46s} "
              f"{note[:60]}  ({time.time() - t0:.0f}s)", flush=True)
    print(f"\nparsed {ok}, failed {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
