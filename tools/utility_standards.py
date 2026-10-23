"""Each map's standard utility, learned from where good teams land it.

    python tools/utility_standards.py     # writes counterplay/utility_standards.json

"Where an ideal smoke would land" is not written down anywhere this project
can use, and lineup sites are someone else's work. It does not need to be:
pro and ESEA teams throw the same smokes, molotovs and flashes onto the
same spots round after round, and their landing points are in the grenades
table. Clustering them per map finds the spots; a spot is STANDARD when it
turns up in at least MIN_MATCH_SHARE of that map's matches.

Each spot is then tied to the bombsite it serves, from the data again: of
the rounds where it was thrown and the bomb went down within PLANT_WINDOW
seconds, which site took the plant most often. A spot with no clear site
(mid smokes, early info flashes) is kept but marked site 0.

counterplay/decisions.py uses these for "you went in without the usual
smokes": an execute or a retake on a site whose standard utility the team
did not throw.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

OUT = ROOT / "counterplay" / "utility_standards.json"
KINDS = ("smoke", "molotov", "flash")
# HDBSCAN, not DBSCAN: with one fixed radius, dense execute areas chained
# into blobs half a site wide (Inferno T smokes came out as two spots of
# radius 900 and 1,250). HDBSCAN finds spots of different density.
MIN_CLUSTER = 12            # throws that make a spot
MERGE = 150.0               # units: closer centres are one spot
MIN_MATCH_SHARE = 0.15      # a spot used in at least this share of matches
PLANT_WINDOW = 25.0         # seconds from landing to plant
SITE_SHARE = 0.65           # a site must take this share of plants to own a spot


def main():
    db.init()
    rows = db.query("""SELECT g.match_key, g.round_num, g.seconds, g.kind, g.side,
                              g.x, g.y, g.z, m.map_name
                         FROM grenades g JOIN corpus_matches m ON m.match_key = g.match_key
                        WHERE m.tier IN ('pro', 'esea') AND g.kind IN ('smoke', 'molotov',
                              'incendiary', 'flash')""")
    plants = {(r["match_key"], r["round_num"]): (float(r["seconds"]), r["plant_site"])
              for r in db.query("""SELECT e.match_key, e.round_num, e.seconds, r.plant_site
                                     FROM events e JOIN rounds r USING (match_key, round_num)
                                    WHERE e.type = 'plant'""")}
    groups = defaultdict(list)
    for r in rows:
        kind = "molotov" if r["kind"] in ("molotov", "incendiary") else r["kind"]
        groups[(r["map_name"], kind, r["side"])].append(r)

    out: dict = {}
    for (mp, kind, side), rs in sorted(groups.items()):
        xyz = np.array([[r["x"], r["y"], r["z"]] for r in rs], dtype=float)
        if len(xyz) < MIN_CLUSTER:
            continue
        labels = HDBSCAN(min_cluster_size=MIN_CLUSTER).fit_predict(xyz)
        n_matches = len({r["match_key"] for r in rs})
        # Clusters first, then merge any whose centres sit within MERGE of
        # each other: HDBSCAN splits one lineup thrown precisely by
        # different teams into several tight clusters (Mirage T smokes came
        # out as 52 spots of median radius 13 before this).
        groups_ = [[r for r, l in zip(rs, labels) if l == lab]
                   for lab in sorted(set(labels) - {-1})]
        groups_.sort(key=len, reverse=True)
        merged: list[list] = []
        for g in groups_:
            c = np.median([[r["x"], r["y"]] for r in g], axis=0)
            for m in merged:
                mc = np.median([[r["x"], r["y"]] for r in m], axis=0)
                if np.linalg.norm(c - mc) <= MERGE:
                    m.extend(g)
                    break
            else:
                merged.append(list(g))
        spots = []
        for members in merged:
            share = len({r["match_key"] for r in members}) / n_matches
            if share < MIN_MATCH_SHARE:
                continue
            sites = Counter()
            for r in members:
                p = plants.get((r["match_key"], r["round_num"]))
                if p and 0 <= p[0] - float(r["seconds"]) <= PLANT_WINDOW and p[1]:
                    sites[int(p[1])] += 1
            site, n = sites.most_common(1)[0] if sites else (0, 0)
            if not sites or n / sum(sites.values()) < SITE_SHARE:
                site = 0
            c = np.array([[r["x"], r["y"], r["z"]] for r in members], dtype=float)
            med = np.median(c, axis=0)
            spots.append({"x": round(float(med[0])), "y": round(float(med[1])),
                          "z": round(float(med[2])),
                          "radius": round(float(np.percentile(
                              np.linalg.norm(c[:, :2] - med[:2], axis=1), 90))),
                          "match_share": round(share, 2), "throws": len(members),
                          "site": site})
        if spots:
            out.setdefault(mp, {}).setdefault(side, {})[kind] = sorted(
                spots, key=lambda s: -s["match_share"])
            print(f"{mp:12s} {side:2s} {kind:8s} {len(spots):2d} standard spots "
                  f"({sum(s['site'] > 0 for s in spots)} tied to a site)")
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
