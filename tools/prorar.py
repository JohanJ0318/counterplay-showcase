"""Parse the pro series that are still packed in .rar archives, one at a time.

    python tools/prorar.py --status           what is done, what is left
    python tools/prorar.py --next 1           parse the next series (a test)
    python tools/prorar.py --all              parse every one left

The 44 archives in counterplay-v1/demos/Pro are the ORIGINALS of the 104
parsed pro maps (and 2 that failed). On 2026-10-14 every .dem inside them
was found to be one of the 106 already unpacked beside them, so nothing in
them was new; the database's source_url for each map was pointed at
"<archive>#<file inside>" and the unpacked 34GB copies were deleted by
Johan. So this is now how a pro map gets back onto disk for a re-parse,
and how a NEW packed series would be parsed. One series at a time:

  1. 7-Zip extracts one archive into data/prorar/<series>/
  2. each .dem in it is queued at tier=pro and parsed (app.worker.drain)
  3. the extracted .dem files are removed: they are copies, and the .rar
     they came from stays where it is, untouched
  4. each parsed row's source_url is pointed at "<archive>#<file inside>",
     so the database says where the original lives

The cost of step 3: a future re-parse of these maps means extracting the
archive again. The archive is kept for exactly that.

A series counts as done when any demo row's source_url starts with its
archive's URL, so a stopped run picks up where it left off.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, ingest, pull, worker  # noqa: E402

SOURCE = Path.home() / "Downloads" / "counterplay-v1" / "demos" / "Pro"
WORK = ROOT / "data" / "prorar"
SEVEN_ZIP = Path(r"C:\Program Files\7-Zip\7z.exe")
# Free space to insist on before extracting: the largest series unpacks to
# a few GB, and the parser needs room of its own.
MIN_FREE_GB = 5.0


def archives() -> list[Path]:
    return sorted(SOURCE.glob("*.rar"))


def done(rar: Path) -> bool:
    url = ingest.path2url(rar)
    return db.one("SELECT 1 FROM demos WHERE source_url LIKE ?", url + "#%") is not None


def free_gb() -> float:
    return shutil.disk_usage(ROOT).free / 1e9


def parse_one(rar: Path) -> str:
    if free_gb() < MIN_FREE_GB:
        return f"stopped: only {free_gb():.1f}GB free, want {MIN_FREE_GB:.0f}GB"
    out = WORK / rar.stem[:80]
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(SEVEN_ZIP), "x", "-y", f"-o{out}", str(rar)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return f"7-Zip failed ({r.returncode}): {r.stderr.strip()[:200]}"
    # Some archives hold a folder; the queue reads one flat folder.
    for dem in list(out.rglob("*.dem")):
        if dem.parent != out:
            dem.rename(out / dem.name)
    dems = sorted(out.glob("*.dem"))
    if not dems:
        return "no .dem inside"
    queued = pull.from_directory(out, tier="pro")
    parsed, failed = worker.drain(verbose=False)
    archive_url = ingest.path2url(rar)
    for dem in dems:
        db.execute("UPDATE demos SET source_url = ? WHERE source_url = ?",
                   f"{archive_url}#{dem.name}", ingest.path2url(dem))
    # The extracted copies only; the archive is the original and stays.
    shutil.rmtree(out)
    return (f"{len(dems)} maps: {parsed} parsed, {failed} failed "
            f"({queued['already_queued']} were already queued)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--next", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    db.init()
    if not SEVEN_ZIP.exists():
        sys.exit(f"7-Zip not found at {SEVEN_ZIP}")
    todo = [r for r in archives() if not done(r)]
    print(f"{len(archives())} archives, {len(archives()) - len(todo)} parsed, "
          f"{len(todo)} left; {free_gb():.1f}GB free")
    if args.status:
        return
    n = len(todo) if args.all else args.next
    for i, rar in enumerate(todo[:n], 1):
        print(f"[{i}/{n}] {rar.name[:90]}", flush=True)
        msg = parse_one(rar)
        print(f"        {msg}", flush=True)
        if msg.startswith("stopped"):
            break


if __name__ == "__main__":
    main()
