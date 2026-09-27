"""Generate the zone-naming sheet.

    python -m counterplay.zonepage

A working tool rather than a product page: clustering finds where the map's
areas are, and this is where a person who recognises the map puts names to
them. Typed names save to the database, and also to the browser's own storage
on every keystroke so a mis-click never loses a page of typing.

Regenerate whenever the corpus grows enough to move the clusters. Names are
keyed on (map, zone index) and the clustering is seeded and ordered by traffic,
so the numbering is stable across regenerations and existing names survive.
"""
from __future__ import annotations

import html
import pathlib

import numpy as np

from . import zonemodel as ZM, zones as Z
from .positions import FLAG_ALIVE, unpack_round

ROUNDS_PER_MAP = 400
STACK_HORIZONTAL = 600      # how close two zones must be to count as stacked
STACK_VERTICAL = 110        # and how far apart in height


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _plant_marks(rows, limit=200):
    """(x, y, z) of each bomb plant trigger, to anchor the picture.

    Kept in a dict per zone id. An earlier version appended both zones to one
    list and then took every other element, which assumed both sites see
    traffic in every round — the moment a round only touches one site the
    alternation shifts and both markers become an average of a jumble. That is
    why they landed off-site on Mirage, Inferno and Cache.
    """
    per_zone: dict[int, list[tuple[float, float]]] = {1: [], 2: []}
    for r in rows[:limit]:
        got = unpack_round(r["data"])
        if got is None:
            continue
        _m, _s, sm = got
        zone = (sm["flags"] & 0b1100) >> 2
        alive = (sm["flags"] & FLAG_ALIVE).astype(bool)
        for zid in (1, 2):
            sel = (zone == zid) & alive
            if sel.sum() > 5:
                per_zone[zid].append(tuple(
                    float(np.median(sm[k][sel].astype(np.int32))) for k in "xyz"))
    px, py, pz = [], [], []
    for zid in (1, 2):
        pts = per_zone[zid]
        # A handful of sightings is someone clipping the corner of a trigger,
        # not a bombsite. Require enough rounds to be sure.
        if len(pts) >= 8:
            px.append(np.median([p[0] for p in pts]))
            py.append(np.median([p[1] for p in pts]))
            # Height, so a split map can show each floor its own trigger. On
            # Nuke the two sit 369 units apart and mark different sites.
            pz.append(np.median([p[2] for p in pts]))
    return px, py, pz


def _stacked(centres):
    """zone index -> 'upper'/'lower' for zones sharing an x,y at two heights."""
    out = {}
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            flat = np.hypot(centres[i][0] - centres[j][0],
                            centres[i][1] - centres[j][1])
            up = abs(centres[i][2] - centres[j][2])
            if flat < STACK_HORIZONTAL and up > STACK_VERTICAL:
                hi, lo = (i, j) if centres[i][2] > centres[j][2] else (j, i)
                out[hi], out[lo] = "upper", "lower"
    return out


CSS = """
body{margin:0;background:#F7F6FA;color:#191325;font-family:"Public Sans",sans-serif;
  font-size:15px;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 90px;display:flex;
  flex-direction:column;gap:32px}
h1,h2{font-family:"Space Grotesk",sans-serif;margin:0}
h1{font-size:2rem;letter-spacing:-.02em} h2{font-size:1.1rem}
.lede{color:#655D77;max-width:66ch}
.card{background:#fff;border:1px solid #E7E3F0;border-radius:8px;padding:22px 24px;
  display:grid;grid-template-columns:1fr 380px;gap:24px;align-items:start}
.mono{font-family:"JetBrains Mono",monospace;font-size:.76rem}
table{border-collapse:collapse;width:100%;font-size:.8rem}
th{text-align:left;font-size:.62rem;letter-spacing:.06em;text-transform:uppercase;
  color:#948CA6;padding:6px 5px;border-bottom:1px solid #E7E3F0}
td{padding:4px 5px;border-bottom:1px solid #F0EDF6}
td.z{font-weight:700;color:#5B21B6;width:1.4rem}
b{color:#A65B0B;font-weight:600}
input.zn{width:100%;font-family:inherit;font-size:.82rem;padding:5px 8px;
  border:1px solid #D6D0E4;border-radius:5px;background:#fff;color:#191325}
input.zn:focus{outline:none;border-color:#5B21B6;box-shadow:0 0 0 3px #F3EFFE}
input.zn.filled{background:#F3EFFE;border-color:#DCD1F7}
.bar{position:sticky;top:0;z-index:20;background:rgba(247,246,250,.94);
  backdrop-filter:blur(8px);border-bottom:1px solid #E7E3F0;padding:12px 0;
  display:flex;gap:14px;align-items:center;flex-wrap:wrap}
button{font-family:inherit;font-weight:600;font-size:.9rem;padding:9px 18px;
  background:#5B21B6;color:#fff;border:none;border-radius:6px;cursor:pointer}
button:hover{background:#3F1178}
button.ghost{background:#fff;color:#5B21B6;border:1px solid #D6D0E4}
#status{font-size:.85rem;color:#655D77}
.lvl{font-family:"Public Sans",sans-serif;font-size:.72rem;font-weight:600;
  text-transform:uppercase;letter-spacing:.06em;color:#5B21B6;background:#F3EFFE;
  border:1px solid #DCD1F7;border-radius:20px;padding:2px 9px;margin-left:6px;
  vertical-align:middle}
.legend{display:flex;gap:18px;font-size:.82rem;color:#655D77;flex-wrap:wrap}
.key{display:inline-flex;align-items:center;gap:6px}
.dot{width:12px;height:12px;border-radius:50%;background:#5B21B6;display:inline-block}
.ring{width:12px;height:12px;border-radius:50%;border:2px solid #A65B0B;display:inline-block}
@media(max-width:880px){.card{grid-template-columns:1fr}}
"""

SCRIPT = """
const KEY = 'counterplay.zonenames';
function local(){ try { return JSON.parse(localStorage.getItem(KEY) || '{}'); }
                  catch(e){ return {}; } }
function say(msg){ document.getElementById('status').textContent = msg; }
function collect(){
  const out = {};
  document.querySelectorAll('input.zn').forEach(i => {
    if (i.value.trim()) out[i.dataset.key] = i.value.trim();
  });
  return out;
}
function mark(i){ i.classList.toggle('filled', !!i.value.trim()); }

// Names already saved on the server win; anything typed since and not yet saved
// is kept from local storage so a reload never loses work.
async function boot(){
  let saved = {};
  try { saved = await (await fetch('/api/zones')).json(); } catch(e){}
  const pending = local();
  document.querySelectorAll('input.zn').forEach(i => {
    const k = i.dataset.key;
    if (pending[k] !== undefined) i.value = pending[k];
    else if (saved[k] !== undefined) i.value = saved[k];
    mark(i);
    i.addEventListener('input', () => {
      mark(i);
      const cur = local();
      if (i.value.trim()) cur[k] = i.value.trim(); else delete cur[k];
      try { localStorage.setItem(KEY, JSON.stringify(cur)); } catch(e){}
      say('unsaved changes');
    });
  });
  const n = Object.keys(collect()).length;
  say(n ? n + ' named' : 'nothing named yet');
}

async function save(){
  const names = collect();
  say('saving...');
  try {
    const r = await fetch('/api/zones', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({names})
    });
    const j = await r.json();
    if (j.ok) { try { localStorage.removeItem(KEY); } catch(e){}
                say('saved ' + Object.keys(names).length + ' names'); }
    else say('not saved: ' + (j.error || 'unknown error'));
  } catch(e){ say('not saved: ' + e.message); }
}

function copyJson(){
  const t = JSON.stringify(collect(), null, 2);
  navigator.clipboard.writeText(t).then(
    () => say('copied to clipboard'), () => say('could not copy'));
}
document.addEventListener('DOMContentLoaded', boot);
"""


def build(out_path: str = "site/zones.html", rounds_per_map: int = ROUNDS_PER_MAP) -> str:
    """Render the naming sheet from the STORED zone model.

    Reading the stored model rather than re-clustering is the whole point: a
    name is keyed on a zone number, so the picture beside the box has to be the
    same clustering the number came from. Re-clustering here would drift away
    from it as the corpus grows and quietly show the wrong picture.

    Maps split by floor get one card per floor, because a top-down drawing of
    two stacked bombsites is unreadable — which is exactly why Nuke is split.
    """
    from app import db

    saved = {r["map_name"] + ":" + str(r["zone_index"]): r["name"]
             for r in db.query("SELECT map_name, zone_index, name FROM zone_names")}

    maps = [r["map_name"] for r in db.query(
        "SELECT map_name, COUNT(*) n FROM rounds GROUP BY map_name ORDER BY n DESC")]

    cards = []
    for mp in maps:
        zs = ZM.load(mp)
        if not zs:
            continue
        rows = db.query("""SELECT rp.data FROM round_positions rp
                             JOIN corpus_matches m ON m.match_key = rp.match_key
                            WHERE m.map_name = ? LIMIT ?""", mp, rounds_per_map)
        if len(rows) < 20:
            continue
        x, y, z = Z.collect([r["data"] for r in rows])
        if len(x) == 0:
            continue
        px, py, pz = _plant_marks(rows)
        split = ZM.SPLIT_LEVELS.get(mp)

        # One card per floor where the map is split, otherwise one for the map.
        if split is None:
            groups = [(None, np.ones(len(x), dtype=bool), list(range(len(zs))),
                       np.ones(len(px), dtype=bool) if len(px) else np.zeros(0, bool))]
        else:
            groups = []
            for level, above in (("upper", True), ("lower", False)):
                idx = [i for i, q in enumerate(zs) if q["level"] == level]
                if not idx:
                    continue
                sel = (z >= split) if above else (z < split)
                keep = (np.asarray(pz) >= split) == above if len(px) else np.zeros(0, bool)
                groups.append((level, sel, idx, keep))

        for level, sel, idx, keep in groups:
            centres = np.array([[zs[i]["cx"], zs[i]["cy"], zs[i]["cz"]] for i in idx])
            counts = np.array([zs[i]["share"] for i in idx])
            gx = [b for b, k in zip(px, keep) if k] if len(px) else []
            gy = [b for b, k in zip(py, keep) if k] if len(py) else []
            # Numbered by their real index in the model, not by position in the
            # card, so the number beside a box is the number a name is keyed on.
            svg = Z.svg(x[sel], y[sel], centres, counts, gx, gy,
                        first_number=idx[0] + 1)

            trs = []
            for i in idx:
                key = f"{mp}:{i + 1}"
                trs.append(
                    f'<tr><td class="z">{i + 1}</td>'
                    f'<td class="mono">{int(zs[i]["cx"])}, {int(zs[i]["cy"])}</td>'
                    f'<td class="mono">{int(zs[i]["cz"]):+}</td>'
                    f'<td class="mono">{100 * zs[i]["share"]:.1f}%</td>'
                    f'<td><input class="zn" data-key="{esc(key)}" '
                    f'value="{esc(saved.get(key, ""))}" '
                    f'placeholder="name this" autocomplete="off"></td></tr>')

            title = esc(mp.replace("de_", ""))
            if level:
                title += f' <span class="lvl">{level} floor</span>'
            cards.append(
                f'<div class="card"><div>{svg}</div><div>'
                f'<h2>{title}</h2>'
                f'<p class="mono" style="color:#948CA6">{len(rows)} rounds &middot; '
                f'{int(sel.sum()):,} samples'
                f'{" &middot; bomb trigger shown" if gx else ""}</p>'
                f'<table><thead><tr><th>#</th><th>x, y</th><th>z</th>'
                f'<th>share</th><th>your name</th></tr></thead>'
                f'<tbody>{"".join(trs)}</tbody></table></div></div>')

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Counterplay: name the zones</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?\
family=Space+Grotesk:wght@600;700&family=Public+Sans:wght@400;600&\
family=JetBrains+Mono:wght@400;700&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
<h1>Name the zones</h1>
<div class="bar">
  <button onclick="save()">Save names</button>
  <button class="ghost" onclick="copyJson()">Copy as JSON</button>
  <span id="status">loading…</span>
</div>
<p class="lede">Each picture is drawn from your own demos: every dot is somewhere a player
actually stood, so the shape is the real map. Numbered circles are the twenty busiest
areas, found by clustering rather than by anyone typing coordinates. Amber rings are the
bomb plant triggers, the one thing CS2 tells us for certain.</p>
<p class="lede"><strong>Height counts.</strong> Two zones can share an x and y and still be
different places. Where that happens the level column says <b>upper</b> or <b>lower</b>, meaning
two floors of one location, like water under mid on Anubis.</p>
<p class="lede">Type a name beside any number you recognise and press Save. Typing is kept
in your browser as you go, so a reload will not lose it. Leave the rest blank; a nameless
zone simply never appears in a pattern.</p>
<div class="legend"><span class="key"><span class="dot"></span>zone centre</span>
<span class="key"><span class="ring"></span>bomb plant trigger</span>
<span class="key">darker = more time spent there</span></div>
{"".join(cards)}
</div><script>{SCRIPT}</script></body></html>"""

    path = pathlib.Path(out_path)
    path.write_text(page, encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    print("wrote", build())
