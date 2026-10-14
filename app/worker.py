"""The parse worker.

    python -m app.worker              # drain the queue, then keep watching
    python -m app.worker --once       # parse everything pending and stop
    python -m app.worker --limit 20   # useful for a first run

Runs as a separate process from the web app on purpose. Parsing a 250MB demo
takes minutes and gigabytes; doing it inside a request would hold a worker
thread, blow the memory budget, and time out the coach's browser anyway.

One demo at a time, deliberately. The constraint is RAM, not CPU — two parallel
parses on a 4GB box is how you meet the OOM killer.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import coach, db, ingest


# Consecutive retryable failures before giving up on this pass. When the demo
# host is unreachable, every row in the queue will fail the same way, and
# grinding through 780 of them to learn that once is pointless.
TRANSIENT_GIVE_UP = 5


def drain(limit: int | None = None, verbose: bool = True) -> tuple[int, int]:
    """Parse pending demos. Returns (parsed, failed)."""
    done = failed = 0
    transient_streak = 0
    seen: set[int] = set()          # tried this pass; a retryable row returns
                                    # to pending immediately and would loop
    while limit is None or done + failed < limit:
        row = ingest.next_pending(seen)
        if row is None:
            break
        seen.add(row["id"])
        label = row["filename"] or row["faceit_match_id"] or row["sha256"][:12]
        if verbose:
            print(f"  parsing {label} ...", flush=True)
        started = time.time()
        ok, note = ingest.process(row)
        took = time.time() - started
        retryable = note.startswith("[retryable]")
        if ok:
            done += 1
            transient_streak = 0
        elif retryable:
            transient_streak += 1
        else:
            failed += 1
            transient_streak = 0
        if verbose:
            tag = "OK  " if ok else ("WAIT" if retryable else "FAIL")
            print(f"    {tag} {note}  ({took:.0f}s)", flush=True)
        if transient_streak >= TRANSIENT_GIVE_UP:
            if verbose:
                print(f"\n  Stopping: {transient_streak} demos in a row could "
                      f"not be reached.\n  The queue is intact and nothing was "
                      f"marked failed — fix the connection\n  and run this "
                      f"again.", flush=True)
            break
    return done, failed


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse pending demos")
    ap.add_argument("--once", action="store_true",
                    help="drain the queue and exit instead of watching")
    ap.add_argument("--limit", type=int, help="stop after this many demos")
    ap.add_argument("--interval", type=int, default=30,
                    help="seconds between polls when watching")
    args = ap.parse_args()

    db.init()
    requeued = ingest.requeue_stuck()
    if requeued:
        print(f"requeued {requeued} demo(s) abandoned mid-parse")

    if args.once or args.limit:
        done, failed = drain(args.limit)
        print(f"\n{done} parsed, {failed} failed")
        if done:
            coach.refresh()
        return 0

    print("watching for demos (ctrl-c to stop)")
    while True:
        done, failed = drain()
        if done or failed:
            print(f"  {done} parsed, {failed} failed", flush=True)
        # The coach's read for every team with a newly parsed demo. After the
        # pass, not per demo, so a coach uploading five maps gets one note
        # from all five. refresh() never raises and does nothing without a key.
        if done:
            made = coach.refresh()
            if made:
                print(f"  coach's read: {len(made)} note(s) written", flush=True)
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0


if __name__ == "__main__":
    sys.exit(main())
