"""How often does the team losing at half come back to win, across NECC?

Nobody has published this about this league, every coach and player has a
belief about it, and it is checkable by anyone who was there. That makes it
the right thing to say in a channel: useful on its own, with no product
attached.

MIN_CHANCES = 8 is applied here exactly as report.rate() applies it, because
posting a percentage off four matches in public would contradict the one
thing the product promises.
"""
import json
from collections import Counter, defaultdict

MIN_CHANCES = 8

d = json.load(open("C:/Users/Johan/counterplay/league/gen/cache/league.json",
                   encoding="utf-8"))


def num(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


maps_seen = Counter()
total = tied = 0
comeback = defaultdict(lambda: [0, 0])      # deficit -> [won, of]
by_map = defaultdict(lambda: [0, 0])        # map -> [comebacks, chances]
overtime = 0
blowout = 0

for champ in d["championships"]:
    for match in champ.get("matches", []):
        for rnd in (match.get("stats") or {}).get("rounds", []):
            teams = rnd.get("teams") or []
            if len(teams) != 2:
                continue
            rs = rnd.get("round_stats") or {}
            mp = (rs.get("Map") or "").replace("de_", "")

            a, b = teams
            sa, sb = a.get("team_stats") or {}, b.get("team_stats") or {}
            fa, fb = num(sa.get("First Half Score")), num(sb.get("First Half Score"))
            wa, wb = num(sa.get("Team Win")), num(sb.get("Team Win"))
            ota = num(sa.get("Overtime score")) or 0
            otb = num(sb.get("Overtime score")) or 0
            la, lb = num(sa.get("Final Score")), num(sb.get("Final Score"))
            if None in (fa, fb, wa, wb, la, lb):
                continue
            if wa + wb != 1:                 # no winner recorded, or both
                continue

            total += 1
            maps_seen[mp] += 1
            if ota or otb:
                overtime += 1
            if abs(la - lb) >= 10:
                blowout += 1

            if fa == fb:
                tied += 1
                continue

            # The side that was behind at the break, and whether it won.
            deficit = abs(fa - fb)
            behind_won = (wa == 1) if fa < fb else (wb == 1)
            comeback[deficit][1] += 1
            comeback[deficit][0] += behind_won
            by_map[mp][1] += 1
            by_map[mp][0] += behind_won


def rate(hit, of):
    """report.rate()'s rule: below MIN_CHANCES, counts and no percentage."""
    if of < MIN_CHANCES:
        return "%d of %d (thin)" % (hit, of)
    return "%.0f%% (%d of %d)" % (100.0 * hit / of, hit, of)


won = sum(v[0] for v in comeback.values())
of = sum(v[1] for v in comeback.values())

print("NECC 2025-26, from the FACEIT record")
print("=" * 58)
print("maps with a usable record   %d" % total)
print("tied at the half            %d" % tied)
print("went to overtime            %s" % rate(overtime, total))
print("decided by 10+ rounds       %s" % rate(blowout, total))
print()
print("THE HEADLINE")
print("  behind at half, won anyway  %s" % rate(won, of))
print()
print("by how far behind at the break")
for dfc in sorted(comeback):
    hit, n = comeback[dfc]
    if n >= MIN_CHANCES:
        print("  down %-2d  %s" % (dfc, rate(hit, n)))
buckets = defaultdict(lambda: [0, 0])
for dfc, (hit, n) in comeback.items():
    key = "1-2" if dfc <= 2 else "3-5" if dfc <= 5 else "6-8" if dfc <= 8 else "9+"
    buckets[key][0] += hit
    buckets[key][1] += n
print()
print("bucketed")
for key in ("1-2", "3-5", "6-8", "9+"):
    hit, n = buckets[key]
    if n:
        print("  down %-4s %s" % (key, rate(hit, n)))
print()
print("by map (comeback rate from behind at half)")
for mp, (hit, n) in sorted(by_map.items(), key=lambda kv: -kv[1][1]):
    if n >= MIN_CHANCES:
        print("  %-12s %s" % (mp, rate(hit, n)))
print()
print("most played")
for mp, n in maps_seen.most_common(8):
    print("  %-12s %d" % (mp, n))
