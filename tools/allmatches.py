"""Every match in the championship, deduplicated, with room links.

tonight.py walks one team at a time, so a match between two teams in the
field shows up twice. This collects them by match id first.
"""
import csv
import datetime as dt
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, r"C:/Users/Johan/counterplay")

CH = "d36e9c78-22a9-4862-bb29-dac8ebb93e77"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CSV = pathlib.Path(r"C:/Users/Johan/counterplay/outreach/fall-2026-teams.csv")


def get(url):
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except Exception:
        return None


names = {}
with CSV.open(encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        names[row["faceit_team_id"]] = row["team"]

seen = {}
for i, (tid, nm) in enumerate(names.items(), 1):
    d = get("https://www.faceit.com/api/championships/v1/matches"
            "?championshipId=%s&participantType=TEAM&participantId=%s"
            "&limit=20&offset=0" % (CH, tid))
    if not d:
        continue
    for m in ((d.get("payload") or {}).get("items") or []):
        o = m.get("origin") or {}
        mid = o.get("id")
        if not mid or mid in seen:
            continue
        sides = [names.get(f.get("id"), f.get("id", "?")[:8])
                 for f in (m.get("factions") or [])]
        seen[mid] = {
            "state": o.get("state", "?"),
            "round": m.get("round", "?"),
            "group": m.get("group", "?"),
            "when": o.get("schedule"),
            "sides": sides,
        }
    if i % 25 == 0:
        print("  ...%d/%d teams, %d matches so far"
              % (i, len(names), len(seen)), file=sys.stderr)

done = {k: v for k, v in seen.items() if v["state"] == "FINISHED"}
print("%d matches total, %d finished\n" % (len(seen), len(done)))


def when(ms):
    if not ms:
        return "?"
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return t.astimezone(dt.timezone(dt.timedelta(hours=-4))).strftime("%H:%M")


rows = sorted(done.items(), key=lambda kv: (kv[1]["round"], kv[1]["group"]))
for mid, v in rows:
    a = v["sides"][0] if v["sides"] else "?"
    b = v["sides"][1] if len(v["sides"]) > 1 else "bye"
    print("r%s g%-3s %s  %-26s vs %-26s"
          % (v["round"], v["group"], when(v["when"]), a, b))
    print("        https://www.faceit.com/en/cs2/room/%s" % mid)

out = pathlib.Path(r"C:/Users/Johan/counterplay/outreach/fall-2026-matches.csv")
with out.open("w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["round", "group", "time_edt", "team_a", "team_b", "state",
                "room_url"])
    for mid, v in sorted(seen.items(), key=lambda kv: (kv[1]["round"],
                                                       kv[1]["group"])):
        w.writerow([v["round"], v["group"], when(v["when"]),
                    v["sides"][0] if v["sides"] else "",
                    v["sides"][1] if len(v["sides"]) > 1 else "bye",
                    v["state"],
                    "https://www.faceit.com/en/cs2/room/%s" % mid])
print("\nwrote %s (%d rows)" % (out.name, len(seen)))
