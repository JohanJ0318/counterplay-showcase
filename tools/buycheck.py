"""Does the buy check tell the truth? Measured on the collegiate corpus.

    python tools/buycheck.py

The check says "saving was worth 0.15 of a round more over two rounds". That
is only worth printing if its two-round numbers come true, so:

  1. CALIBRATION of the call the team actually made: predicted share of
     rounds won from this round to the end of the half (the window the
     check judges over), against what happened, binned. If the
     predictions run high or low anywhere, every comparison built on them
     is off too.
  2. The same, on FLAGGED rounds only. A check that is right on average and
     wrong exactly where it speaks up would be worse than none.
  3. How often it speaks: flagged rounds per team per match, and which way.
     A coach reads a handful of calls a match, not a dozen.
  4. How many player notes a match produces, by kind.
  5. What an eco actually spends, so the "save" option is a real save.
  6. THE EVIDENCE the match report shows beside a flag: what real teams in
     that spot went on to win from there to the end of the half, with no
     model in it. Copy these into economy.EVIDENCE when they move.
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
    ev = defaultdict(lambda: [0, 0])          # (spot, call) -> [won, rounds]
    per_team = []
    for mk in keys:
        calls = buys.match_calls(mk)
        won = {(c["round"], c["side"]): c["won"] for c in calls}
        by_side = defaultdict(int)
        equip = {(c["round"], c["side"]): c["equip"] for c in calls}
        for c in calls:
            # every round the call was judged over, this one included
            window = [won.get((c["round"] + k, c["side"]))
                      for k in range(c["rounds"])]
            whole = all(w is not None for w in window)
            other = "t" if c["side"] == "ct" else "ct"
            reach = c["equip"] - c["spent"] + c["money"]
            if whole and equip.get((c["round"], other), 0) >= 20000:
                spot = None
                if reach >= 22000 and c["made"] in ("force", "full"):
                    spot = ("underbuy", c["made"])
                elif 12000 <= reach < 20000 and c["made"] in ("eco", "force"):
                    spot = ("save_or_force", c["made"])
                if spot:
                    ev[spot][0] += sum(window)
                    ev[spot][1] += len(window)
            if c["made"] == "eco":
                eco_spend.append(c["spent"])
            for n in c["notes"]:
                notes[n["kind"]] += 1
            if c["flag"]:
                by_side[c["side"]] += 1
                flagged.append(c)
            if whole:
                rows.append((c["v"] / c["rounds"], sum(window) / c["rounds"], c))
        per_team += [by_side.get("ct", 0) + by_side.get("t", 0)]
    print(f"{len(keys)} collegiate matches, {len(rows)} judged calls with every "
          f"round of their window to check against\n")

    def table(sample, title):
        print(title)
        print(f"  {'predicted':>12s} {'happened':>9s} {'rounds':>7s}")
        edges = [0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.01]
        for lo, hi in zip(edges, edges[1:]):
            got = [(v, r) for v, r, _ in sample if lo <= v < hi]
            if got:
                print(f"  {st.mean(v for v, _ in got):12.2f} "
                      f"{st.mean(r for _, r in got):9.2f} {len(got):7d}")
        if sample:
            print(f"  {'all':>12s}: predicted {st.mean(v for v, _, _ in sample):.3f}, "
                  f"happened {st.mean(r for _, r, _ in sample):.3f}\n")

    table(rows, "1. share of the judged rounds won (this one to the end of the "
                "half), the call they made")
    table([x for x in rows if x[2]["flag"]], "2. the same, flagged rounds only")

    print("3. flagged rounds")
    print(f"  per match (both teams): median {st.median(per_team) * 1.0:.1f}, "
          f"mean {st.mean(per_team):.2f}, max {max(per_team)}")
    print("  made -> better:", dict(Counter(
        f"{c['made']} -> {c['options'][c['best']]['kind']}" for c in flagged)))
    if flagged:
        print(f"  gain: median {st.median(c['gain'] for c in flagged):.2f} "
              f"rounds over the rest of the half")
    print()
    print("4. player notes per match:",
          {k: round(v / len(keys), 2) for k, v in notes.most_common()})
    if eco_spend:
        print(f"\n5. a team's spend on an eco: median ${st.median(eco_spend):,.0f}, "
              f"quartiles {[round(q) for q in st.quantiles(eco_spend, n=4)]}")
    print()
    print("6. EVIDENCE = {   # (spot, call): (rounds won, rounds), from that "
          "round to the end of the half")
    for k in sorted(ev):
        print(f"    {k!r}: ({ev[k][0]}, {ev[k][1]}),   # "
              f"{ev[k][0] / ev[k][1]:.0%}")
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
