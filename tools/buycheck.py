"""Does the buy check tell the truth? Measured on the collegiate corpus.

    python tools/buycheck.py

The check says "saving was worth 0.15 of a round more over two rounds". That
is only worth printing if its two-round numbers come true, so:

  1. CALIBRATION of the call the team actually made: predicted rounds won
     over this round and the next, against what happened, binned. If the
     predictions run high or low anywhere, every comparison built on them
     is off too.
  2. The same, on FLAGGED rounds only. A check that is right on average and
     wrong exactly where it speaks up would be worse than none.
  3. How often it speaks: flagged rounds per team per match, and which way.
     A coach reads a handful of calls a match, not a dozen.
  4. How many player notes a match produces, by kind.
  5. What an eco actually spends, so the "save" option is a real save.
"""
from __future__ import annotations

import os
import pathlib
import statistics as st
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    os.environ.setdefault("COUNTERPLAY_DB", str(ROOT / "data" / "counterplay.db"))
    from app import buys, db

    keys = [r["match_key"] for r in db.query(
        "SELECT m.match_key FROM matches m JOIN demos d ON d.id = m.demo_id "
        "WHERE d.tier = 'league' AND d.status = 'parsed'")]
    rows, flagged, notes, eco_spend = [], [], Counter(), []
    per_team = []
    for mk in keys:
        calls = buys.match_calls(mk)
        won = {(c["round"], c["side"]): c["won"] for c in calls}
        by_side = defaultdict(int)
        for c in calls:
            nxt = won.get((c["round"] + 1, c["side"]))
            if c["made"] == "eco":
                eco_spend.append(c["spent"])
            for n in c["notes"]:
                notes[n["kind"]] += 1
            if c["flag"]:
                by_side[c["side"]] += 1
                flagged.append(c)
            if nxt is None:
                continue           # last of a half, or the next round unjudged
            real = c["won"] + nxt
            rows.append((c["v"], real, c))
        per_team += [by_side.get("ct", 0) + by_side.get("t", 0)]
    print(f"{len(keys)} collegiate matches, {len(rows)} judged rounds with a "
          f"next round to check against\n")

    def table(sample, title):
        print(title)
        print(f"  {'predicted':>12s} {'happened':>9s} {'rounds':>7s}")
        edges = [0, 0.4, 0.8, 1.2, 1.6, 2.01]
        for lo, hi in zip(edges, edges[1:]):
            got = [(v, r) for v, r, _ in sample if lo <= v < hi]
            if got:
                print(f"  {st.mean(v for v, _ in got):12.2f} "
                      f"{st.mean(r for _, r in got):9.2f} {len(got):7d}")
        if sample:
            print(f"  {'all':>12s}: predicted {st.mean(v for v, _, _ in sample):.3f}, "
                  f"happened {st.mean(r for _, r, _ in sample):.3f}\n")

    table(rows, "1. rounds won over this round and the next, the call they made")
    table([x for x in rows if x[2]["flag"]], "2. the same, flagged rounds only")

    print("3. flagged rounds")
    print(f"  per match (both teams): median {st.median(per_team) * 1.0:.1f}, "
          f"mean {st.mean(per_team):.2f}, max {max(per_team)}")
    print("  made -> better:", dict(Counter(
        f"{c['made']} -> {c['options'][c['best']]['kind']}" for c in flagged)))
    if flagged:
        print(f"  gain: median {st.median(c['gain'] for c in flagged):.2f} "
              f"of a round over two rounds")
    print()
    print("4. player notes per match:",
          {k: round(v / len(keys), 2) for k, v in notes.most_common()})
    if eco_spend:
        print(f"\n5. a team's spend on an eco: median ${st.median(eco_spend):,.0f}, "
              f"quartiles {[round(q) for q in st.quantiles(eco_spend, n=4)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
