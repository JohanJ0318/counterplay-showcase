"""Where each map's two bombsites are, from where players stood on them.

    python tools/site_centres.py      # writes counterplay/site_centres.json

Centres are 3D: Nuke's sites are one above the other.

The game marks a player "in bombsite 1 or 2" only inside the small plant
area, so "three CTs at the other site" almost never shows in those flags:
counterplay/decisions.py's stacked detector fired on 0.0% of college deaths
on its first version. A site's centre (the median of every living sample
the game marked as in it) and a radius around it describe the area a
setup actually holds.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from counterplay import positions as P  # noqa: E402

OUT = ROOT / "counterplay" / "site_centres.json"


def main():
    db.init()
    pts = defaultdict(list)
    for r in db.query("""SELECT m.map_name, p.data FROM round_positions p
                           JOIN corpus_matches m ON m.match_key = p.match_key
                          WHERE m.tier IN ('league', 'esea', 'pro')"""):
        got = P.unpack_round(r["data"])
        if got is None:
            continue
        s = got[2][::8].ravel()                      # one sample a second
        live = (s["flags"] & P.FLAG_ALIVE) != 0
        zone = (s["flags"] & P.ZONE_MASK) >> P.ZONE_SHIFT
        for site in (1, 2):
            m = live & (zone == site)
            if m.any():
                pts[(r["map_name"], site)].append(
                    np.column_stack([s["x"][m], s["y"][m], s["z"][m]]))
    out: dict = {}
    for (mp, site), chunks in sorted(pts.items()):
        a = np.concatenate(chunks).astype(float)
        c = np.median(a, axis=0)
        out.setdefault(mp, {})[str(site)] = {
            "x": round(float(c[0])), "y": round(float(c[1])), "z": round(float(c[2])),
            "radius": round(float(np.percentile(np.linalg.norm(a - c, axis=1), 90))),
            "samples": int(len(a))}
        print(f"{mp:12s} site {site}: centre ({c[0]:.0f}, {c[1]:.0f}), "
              f"radius {out[mp][str(site)]['radius']}")
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
