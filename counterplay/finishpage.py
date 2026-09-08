"""Generate the sheet for zones that still have no name.

    python -m counterplay.finishpage

The full naming sheet (`zonepage.py`) shows every zone on every map, which is
right the first time and wrong afterwards: once most of a map is named, the
work left is a handful of boxes buried in a page of finished ones.

This shows only what is missing, on the real map, with the rest of that map
labelled around it for bearings — and, where a zone was split off another,
says which one it came out of. "The other side of the wall from Apps" is most
of the answer to what a place is called.
"""
from __future__ import annotations

import pathlib

import numpy as np

from . import radar as RD, zonemodel as ZM, zones as Z, zonepage as ZP

# How much map to show around the zone being named.
ZOOM_PAD = 1100


def _cards(team_id: int | None = None) -> list[str]:
    from app import db

    cards = []
    maps = [r["map_name"] for r in db.query(
        "SELECT map_name, COUNT(*) n FROM rounds GROUP BY map_name ORDER BY n DESC")]

    for mp in maps:
        zs = ZM.load(mp)
        names = ZM.names(mp)
        if not zs:
            continue
        missing = [i for i in range(1, len(zs) + 1) if i not in names]
        if not missing:
            continue

        rows = db.query("""SELECT rp.data FROM round_positions rp
                             JOIN matches m ON m.match_key = rp.match_key
                            WHERE m.map_name = ?""", mp)
        x, y, z = Z.collect([r["data"] for r in rows], thin=2, alive_only=False)
        if len(x) == 0:
            continue

        played = 0
        if team_id is not None:
            played = db.one("""SELECT COUNT(*) n FROM rounds r
                                 JOIN matches m ON m.match_key = r.match_key
                                 JOIN demos d ON d.id = m.demo_id
                                WHERE d.team_id = ? AND r.map_name = ?""",
                            team_id, mp)["n"]

        split = ZM.SPLIT_LEVELS.get(mp)
        for idx in missing:
            target = zs[idx - 1]
            tx, ty, tz = ZM.label_pos(target)

            # Neighbours worth drawing, on the same floor as the target.
            near = []
            for j, q in enumerate(zs):
                if abs(q["cx"] - tx) > ZOOM_PAD * 1.25:
                    continue
                if abs(q["cy"] - ty) > ZOOM_PAD * 1.25:
                    continue
                if split is not None and q["level"] != target["level"]:
                    continue
                near.append(j)
            if idx - 1 not in near:
                near.append(idx - 1)
            near.sort()

            ext = (tx - ZOOM_PAD, tx + ZOOM_PAD, ty - ZOOM_PAD, ty + ZOOM_PAD)
            keep = (x >= ext[0]) & (x <= ext[1]) & (y >= ext[2]) & (y <= ext[3])
            if split is not None:
                keep &= (z >= split) if target["level"] == "upper" else (z < split)
            if keep.sum() < 50:
                keep = (x >= ext[0]) & (x <= ext[1]) & (y >= ext[2]) & (y <= ext[3])

            centres = np.array([[zs[j]["cx"], zs[j]["cy"], zs[j]["cz"]] for j in near])
            anchors = np.array([ZM.label_pos(zs[j]) for j in near])
            counts = np.array([zs[j]["share"] for j in near])
            labels = [names.get(j + 1) or f"THIS ONE" for j in near]
            svg = Z.svg(x[keep], y[keep], centres, counts, width=470,
                        first_number=near[0] + 1, labels=labels,
                        radar=RD.available(mp, target["level"]),
                        extent=ext, anchors=anchors)

            floor = (f' <span class="lvl">{target["level"]} floor</span>'
                     if target["level"] else "")
            where = (f'{played} of your rounds have been played here'
                     if played else 'you have not played this map yet')
            cards.append(
                f'<div class="card"><div>{svg}</div><div>'
                f'<h2>{ZP.esc(mp.replace("de_", ""))} '
                f'<span class="cnt">zone {idx}</span>{floor}</h2>'
                f'<p class="mono" style="color:#948CA6">'
                f'{100 * target["share"]:.1f}% of all movement on this map &middot; '
                f'{where}<br>Everything else nearby is labelled; the one needing a '
                f'name is marked <b>THIS ONE</b>.</p>'
                f'<p><input class="zn" data-key="{ZP.esc(mp)}:{idx}" '
                f'placeholder="what is this called?" autocomplete="off"></p>'
                f'</div></div>')
    return cards


def build(out_path: str = "site/finish-zones.html", team_id: int | None = None) -> str:
    cards = _cards(team_id)
    n = len(cards)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Counterplay: name the last zones</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?\
family=Space+Grotesk:wght@600;700&family=Public+Sans:wght@400;600&\
family=JetBrains+Mono:wght@400;700&display=swap">
<style>{ZP.CSS}
.cnt{{font-family:"Public Sans",sans-serif;font-size:.72rem;font-weight:600;
  text-transform:uppercase;letter-spacing:.06em;color:#A65B0B;background:#FDF4E7;
  border:1px solid #F0DCBC;border-radius:20px;padding:2px 9px;margin-left:6px;
  vertical-align:middle}}
.card{{grid-template-columns:1fr 340px}}
</style></head><body><div class="wrap">
<h1>{n} zone{"s" if n != 1 else ""} left to name</h1>
<div class="bar">
  <button onclick="save()">Save names</button>
  <button class="ghost" onclick="copyJson()">Copy as JSON</button>
  <span id="status">loading&hellip;</span>
</div>
<p class="lede">Most of these are new. A zone that covered ground on both sides of
a wall has been split in two, because "three of you are in Apps" is not one
sentence when Apps is two rooms. The larger piece kept its name; the piece that
was separated from it is here, needing one of its own.</p>
<p class="lede">Each picture is zoomed to the zone in question with the real map
underneath. Everything around it is already named, so use those for bearings;
the one to name is the label reading <b>THIS ONE</b>.</p>
<p class="lede">Leave anything you cannot place blank. A nameless zone is skipped
rather than guessed at, and skipping one costs nothing but the rounds that pass
through it.</p>
{"".join(cards)}
</div><script>{ZP.SCRIPT}</script></body></html>"""
    path = pathlib.Path(out_path)
    path.write_text(page, encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from app import db

    db.init()
    team = db.one("SELECT id FROM teams WHERE slug = 'cvs'")
    print("wrote", build(team_id=team["id"] if team else None))
