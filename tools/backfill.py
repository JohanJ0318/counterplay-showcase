"""Fill plant_site for rounds that were parsed before the column existed.

    python tools/backfill.py --dry     count what would change, touch nothing
    python tools/backfill.py           do it

Migration 19 added rounds.plant_site and every existing row defaulted to 0.
No re-parse is needed to fill them: round_positions already holds the bombsite
bits CS2 sets itself, which is the whole reason positions.py needs no
hand-authored map geometry, so every round already in the database can answer.

Uses ingest.fill_plant_sites, the same function the ingest path calls, so
there is exactly one definition of how a site is decided and a backfilled
round is indistinguishable from a freshly parsed one.

A round can legitimately end at 0. It has no plant, or it has a plant but no
stored positions, or nobody on T was standing in a bombsite in the sampled
window. 0 means unknown and the model reads it as its own category, which is
the honest handling: guessing a site would be inventing the one fact this is
supposed to supply.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    os.chdir(ROOT)
    from app import db, ingest
    db.init()

    plants = db.one("""SELECT COUNT(*) n FROM (
                         SELECT DISTINCT match_key, round_num
                           FROM events WHERE type = 'plant')""")["n"]
    before = db.one("SELECT COUNT(*) n FROM rounds WHERE plant_site > 0")["n"]
    keys = [r["match_key"] for r in
            db.query("SELECT DISTINCT match_key FROM rounds ORDER BY match_key")]
    print("%d matches, %d rounds with a plant, %d already have a site"
          % (len(keys), plants, before))

    if args.dry:
        print("\n--dry, nothing written.")
        return 0

    filled = 0
    with db.connect() as conn:
        for i, key in enumerate(keys, 1):
            filled += ingest.fill_plant_sites(conn, key)
            if i % 25 == 0 or i == len(keys):
                print("  %4d/%4d matches, %d rounds filled" % (i, len(keys), filled))
        conn.commit()

    after = db.one("SELECT COUNT(*) n FROM rounds WHERE plant_site > 0")["n"]
    print("\nplant_site set on %d rounds (was %d)" % (after, before))
    if plants:
        print("that is %.0f%% of rounds with a plant." % (100.0 * after / plants))
    for r in db.query("""SELECT plant_site, COUNT(*) n FROM rounds
                          GROUP BY plant_site ORDER BY plant_site"""):
        label = {0: "unknown / no plant"}.get(r["plant_site"],
                                              "site %d" % r["plant_site"])
        print("  %-20s %5d rounds" % (label, r["n"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
