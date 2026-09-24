"""How competitive was each NECC division, by its own scorelines.

The live argument in #cs2-general is whether seeding on a roster's FACEIT
average works. one captain said it is gameable by padding subs; another said
they check for egregious differences. Nobody brought a number.

A blowout rate is one. If seeding put teams where they belong, most maps
should be close. The share of maps decided by 10 or more rounds is a
direct, checkable measure of how often it did not.

MIN_CHANCES = 8 applies as report.rate() applies it.
"""
import json
import re
from collections import defaultdict

MIN_CHANCES = 8
d = json.load(open("C:/Users/Johan/counterplay/league/gen/cache/league.json",
                   encoding="utf-8"))


def num(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def bucket(name: str) -> str:
    """Group the 32 championships into things worth comparing."""
    n = name.upper()
    if "PLACEMENT" in n:
        return "Placement tournament"
    if "NATIONALS" in n or "LCQ" in n or "GRAND FINALS" in n:
        return "Nationals"
    if "PLAYOFF" in n:
        return "Playoffs"
    if "OPEN" in n:
        return "Fall Open"
    m = re.search(r"DIVISION (\d)|(?<!\w)D(\d)(?!\w)", n)
    if m:
        return "Division %s" % (m.group(1) or m.group(2))
    return name


stats = defaultdict(lambda: {"maps": 0, "blowout": 0, "close": 0,
                             "ot": 0, "diffs": []})

for champ in d["championships"]:
    key = bucket(champ.get("name", "?"))
    for match in champ.get("matches", []):
        for rnd in (match.get("stats") or {}).get("rounds", []):
            teams = rnd.get("teams") or []
            if len(teams) != 2:
                continue
            sa = teams[0].get("team_stats") or {}
            sb = teams[1].get("team_stats") or {}
            la, lb = num(sa.get("Final Score")), num(sb.get("Final Score"))
            if la is None or lb is None:
                continue
            ota = (num(sa.get("Overtime score")) or 0) + \
                  (num(sb.get("Overtime score")) or 0)
            diff = abs(la - lb)
            s = stats[key]
            s["maps"] += 1
            s["diffs"].append(diff)
            if diff >= 10:
                s["blowout"] += 1
            if diff <= 2 or ota:
                s["close"] += 1
            if ota:
                s["ot"] += 1


def rate(hit, of):
    if of < MIN_CHANCES:
        return "%d of %d (thin)" % (hit, of)
    return "%3.0f%%" % (100.0 * hit / of)


print("NECC 2025-26, every map with a usable scoreline")
print("=" * 72)
print("%-24s %6s %9s %9s %9s %8s" %
      ("", "maps", "blowout", "close", "overtime", "avg gap"))
print("-" * 72)

order = sorted(stats, key=lambda k: -stats[k]["maps"])
for key in order:
    s = stats[key]
    if s["maps"] < MIN_CHANCES:
        continue
    avg = sum(s["diffs"]) / len(s["diffs"])
    print("%-24s %6d %9s %9s %9s %8.1f" %
          (key, s["maps"], rate(s["blowout"], s["maps"]),
           rate(s["close"], s["maps"]), rate(s["ot"], s["maps"]), avg))

tot_maps = sum(s["maps"] for s in stats.values())
tot_blow = sum(s["blowout"] for s in stats.values())
tot_close = sum(s["close"] for s in stats.values())
print("-" * 72)
print("%-24s %6d %9s %9s" % ("ALL", tot_maps, rate(tot_blow, tot_maps),
                             rate(tot_close, tot_maps)))
print()
print("blowout = decided by 10+ rounds.  close = within 2, or went to OT.")
