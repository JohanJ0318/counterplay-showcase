"""The real map underneath the data.

    python -m counterplay.radar --fetch

WHY
---
Every drawing here is built from where players have stood, which finds the busy
areas honestly and draws the map with holes in it. A corner nobody walked
through comes out blank, and more matches never fully fix that because some
corners are never contested. The map is still there.

CS2 ships an overhead image per map for exactly this purpose, plus the numbers
needed to line it up with world coordinates:

    "pos_x" "-3230"   // world coordinate of the image's top-left corner
    "pos_y" "1713"
    "scale" "5.0"     // world units per pixel

    world_px = (x - pos_x) / scale
    world_py = (pos_y - y) / scale

Checked against this corpus: Mirage's two bomb plant triggers, measured from
demos, land 7 and 3 pixels (of 1024) from where the game's own overview file
says the bombsites are. The transform is exact; the residual is the size of the
trigger volume.

WHERE THE IMAGES COME FROM
--------------------------
The images are Valve's, extracted from the game depot. They are fetched rather
than committed, so this repository carries none of Valve's artwork, and a
deployment that would rather not serve them simply never runs --fetch: the
drawings fall back to the position-density picture on their own.

Nuke and Vertigo ship a second image for their lower floor, which is why the
floor split matters here as well as in the clustering.
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request

# Automated mirror of the game depot: PNGs plus the overview text, refreshed
# when Valve ships a map change. The assets remain Valve's property.
SOURCE = ("https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/"
          "main/images/radars/{name}.png")
CREDIT = "Map overview images &copy; Valve Corporation"

RADAR_DIR = pathlib.Path(__file__).resolve().parent.parent / "site" / "radars"
CAL_PATH = pathlib.Path(__file__).resolve().parent / "overviews.json"

# Every radar Valve ships is square at this resolution.
IMAGE_PX = 1024


def calibration(map_name: str) -> dict | None:
    """pos_x, pos_y, scale and any floor split for one map."""
    try:
        cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cal.get(map_name)


def _asset(map_name: str, level: str | None) -> str:
    lower = "_lower" if level == "lower" else ""
    return f"{map_name}{lower}_radar_psd"


def path_for(map_name: str, level: str | None = None) -> pathlib.Path:
    return RADAR_DIR / f"{_asset(map_name, level)}.png"


def fetch(map_name: str, level: str | None = None, timeout: int = 30) -> bool:
    """Download one radar image. True if it is now on disk."""
    out = path_for(map_name, level)
    if out.exists() and out.stat().st_size > 1000:
        return True
    RADAR_DIR.mkdir(parents=True, exist_ok=True)
    url = SOURCE.format(name=_asset(map_name, level))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return False
            data = r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if len(data) < 1000 or not data.startswith(b"\x89PNG"):
        return False
    out.write_bytes(data)
    return True


def available(map_name: str, level: str | None = None) -> dict | None:
    """What the renderer needs, or None when this map has no usable radar.

    Returns the web path and the WORLD rectangle the image covers, so the
    caller can place it without knowing anything about radar files.
    """
    cal = calibration(map_name)
    if not cal or cal.get("scale") in (None, 0):
        return None
    p = path_for(map_name, level)
    if not p.exists():
        return None
    span = IMAGE_PX * cal["scale"]
    return {
        "url": f"/radars/{p.name}",
        "x0": cal["pos_x"], "x1": cal["pos_x"] + span,
        "y0": cal["pos_y"] - span, "y1": cal["pos_y"],
        "credit": CREDIT,
    }


def main() -> int:
    import argparse

    from app import db

    ap = argparse.ArgumentParser(description="Fetch CS2 map overview images")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--map", action="append", default=[])
    args = ap.parse_args()
    db.init()

    maps = args.map or [r["map_name"] for r in db.query(
        "SELECT map_name, COUNT(*) n FROM rounds GROUP BY map_name ORDER BY n DESC")]

    if not args.fetch:
        print(f"{'map':<12}{'radar':>8}{'lower':>8}  covers")
        for mp in maps:
            a = available(mp)
            lo = available(mp, "lower")
            cov = (f"x {a['x0']:.0f}..{a['x1']:.0f}  y {a['y0']:.0f}..{a['y1']:.0f}"
                   if a else "—")
            print(f"{mp.replace('de_', ''):<12}{'yes' if a else 'no':>8}"
                  f"{'yes' if lo else '—':>8}  {cov}")
        print(f"\n{CREDIT.replace('&copy;', '(c)')}. Run --fetch to download.")
        return 0

    for mp in maps:
        cal = calibration(mp)
        if not cal:
            print(f"  {mp.replace('de_', ''):<12} no calibration — skipped")
            continue
        got = fetch(mp)
        note = "ok" if got else "not available"
        if "floor_split" in cal and fetch(mp, "lower"):
            note += " + lower floor"
        print(f"  {mp.replace('de_', ''):<12} {note}")
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
