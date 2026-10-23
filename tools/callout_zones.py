"""A map's zones from the game's own callouts, drawn on the radar (prototype).

    python tools/callout_zones.py de_mirage data/view/callouts_de_mirage.png

For Johan's review on 2026-10-22 ("zones would look better if divided by
straight lines"); the current zones are k-means clusters named by hand.

Each living player sample carries last_place_name, the official callout from
the map's navigation mesh. Every 48-unit square takes the callout most of its
samples had, then one 3x3 smoothing pass; a map with a radar floor_split
(Nuke) gets one image per floor. Borders are drawn where neighbouring squares
differ, so every edge is a straight line.
"""
import io
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import zstandard
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from app import db, ingest  # noqa: E402
from counterplay import radar  # noqa: E402
from demoparser2 import DemoParser  # noqa: E402

MAP = sys.argv[1] if len(sys.argv) > 1 else "de_mirage"
N_DEMOS = 8
CELL = 48.0
OUT = Path(sys.argv[2])

db.init()
rows = db.query("""SELECT d.source_url FROM corpus_matches m JOIN demos d ON d.id = m.demo_id
                    WHERE m.tier = 'league' AND m.map_name = ? LIMIT ?""", MAP, N_DEMOS)
votes = defaultdict(Counter)
for r in rows:
    if not (r["source_url"] or "").startswith("file://"):
        continue
    path = Path(ingest.url2path(r["source_url"]))
    if not path.is_file():
        continue
    raw = path.read_bytes()
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
    tmp = Path(tempfile.gettempdir()) / "proto.dem"
    tmp.write_bytes(raw)
    df = DemoParser(str(tmp)).parse_ticks(["X", "Y", "Z", "last_place_name", "is_alive"],
                                          ticks=list(range(2000, 200000, 16)))
    tmp.unlink()
    df = df[df.is_alive & df.last_place_name.fillna("").ne("")]
    split = (radar.calibration(MAP) or {}).get("floor_split")
    for x, y, z, p in zip(df.X, df.Y, df.Z, df.last_place_name):
        floor = "lower" if split is not None and z < split else "upper"
        votes[(floor, int(x // CELL), int(y // CELL))][p] += 1
    print("parsed", path.name[:30], len(df), "samples", flush=True)

raw_cells = {k: c.most_common(1)[0][0] for k, c in votes.items() if sum(c.values()) >= 3}
# One smoothing pass: a square takes the callout most of its 3x3 neighbourhood
# has, which removes single-square spikes along borders.
cells = {}
for (fl, cx, cy), n in raw_cells.items():
    around = Counter(raw_cells[(fl, cx + dx, cy + dy)] for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                     if (fl, cx + dx, cy + dy) in raw_cells)
    cells[(fl, cx, cy)] = around.most_common(1)[0][0]
cal = radar.calibration(MAP)
floors = sorted({k[0] for k in cells}, reverse=True)
for fl in floors:
    out = OUT if len(floors) == 1 else OUT.with_name(OUT.stem + f"_{fl}" + OUT.suffix)
    sub_cells = {(cx, cy): n for (f, cx, cy), n in cells.items() if f == fl}
    img = Image.open(radar.path_for(MAP, "lower" if fl == "lower" else None)).convert("RGBA").resize((1024, 1024))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    names = sorted(set(sub_cells.values()))
    colour = {n: tuple(int(v) for v in np.random.default_rng(abs(hash(n)) % 2**32).integers(60, 230, 3))
              for n in names}

    def px(x, y):
        return ((x - cal["pos_x"]) / cal["scale"], (cal["pos_y"] - y) / cal["scale"])

    for (cx, cy), n in sub_cells.items():
        x0, y1 = px(cx * CELL, cy * CELL)
        x1, y0 = px((cx + 1) * CELL, (cy + 1) * CELL)
        d.rectangle([x0, y0, x1, y1], fill=colour[n] + (110,))
    for (cx, cy), n in sub_cells.items():
        for dx, dy in ((1, 0), (0, 1)):
            m = sub_cells.get((cx + dx, cy + dy))
            if m is not None and m != n:
                if dx:
                    a = px((cx + 1) * CELL, cy * CELL); b = px((cx + 1) * CELL, (cy + 1) * CELL)
                else:
                    a = px(cx * CELL, (cy + 1) * CELL); b = px((cx + 1) * CELL, (cy + 1) * CELL)
                d.line([a, b], fill=(255, 255, 255, 230), width=2)
    font = ImageFont.load_default()
    for n in names:
        pts = np.array([px((cx + 0.5) * CELL, (cy + 0.5) * CELL)
                        for (cx, cy), m in sub_cells.items() if m == n])
        c = np.median(pts, axis=0)
        d.text((c[0] - 3 * len(n), c[1] - 5), n, fill=(255, 255, 255, 255), font=font,
               stroke_width=2, stroke_fill=(0, 0, 0, 255))
    Image.alpha_composite(img, over).convert("RGB").save(out)
    print(f"{MAP} {fl}: {len(names)} callouts, {len(sub_cells)} squares -> {out.name}")
