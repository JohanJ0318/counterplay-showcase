"""What will the other side hold, given what they can afford? The table the
buy check reads instead of the other side's actual buy.

    python tools/econenemy.py

Judging a call against what the other team ACTUALLY bought is hindsight: a
save looks wrong because the other side happened to force, which nobody
knew at buy time. What a team does know is roughly what the other side can
afford: their money (the scoreboard) plus what they carried in (who
survived with what). So the check asks: of real teams with that much
available, on that side, what did they end up holding? Five points across
that spread, and the win chance is averaged over them.

Prints the table as Python for counterplay/economy.py, and how far the
median lands from the real buy.
"""
from __future__ import annotations

import os
import pathlib
import statistics as st
import sys
from collections import defaultdict

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STEP = 4000          # dollars available per bucket
TOP = 40000          # everything above goes in the last bucket
QS = (10, 30, 50, 70, 90)


def main() -> int:
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from app import buys, db
    keys = [r["match_key"] for r in db.query(
        "SELECT m.match_key FROM corpus_matches m JOIN demos d ON d.id = m.demo_id "
        "WHERE d.tier = 'league' AND d.status = 'parsed'")]
    got = defaultdict(list)
    for mk in keys:
        for c in buys.match_calls(mk):
            avail = c["equip"] - c["spent"] + c["money"]
            b = min(int(avail // STEP), TOP // STEP)
            got[(c["side"], b)].append(c["equip"])
    table, err = {}, []
    for side in ("ct", "t"):
        for b in range(TOP // STEP + 1):
            v = got.get((side, b), [])
            if len(v) < 20:
                # thin bucket: borrow the neighbours
                v = got.get((side, b - 1), []) + v + got.get((side, b + 1), [])
            if not v:
                continue
            q = [int(round(float(np.percentile(v, p)), -1)) for p in QS]
            table[(side, b)] = q
            med = q[2]
            err += [abs(x - med) for x in got.get((side, b), [])]
    print(f"median miss against the real buy: ${st.median(err):,.0f} "
          f"(mean ${st.mean(err):,.0f}) over {len(err)} team-rounds\n")
    print("ENEMY_BUY = {    # (side, $ available // STEP): equipment at "
          f"percentiles {QS}")
    for (side, b), q in sorted(table.items()):
        print(f'    ("{side}", {b:2d}): {q},')
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
