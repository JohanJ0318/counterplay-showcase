"""The coach's read resource library: vetted links, retrieved by meaning.

    python tools/resources.py            # rebuild counterplay/resource_index.json
    python tools/resources.py --preview  # what every key would retrieve,
                                         # unvetted rows included, for vetting

Source: outreach/resource-candidates.md, where Johan marks each row KEEP or
CUT. Only KEEP rows ever reach the index the server reads, so an unvetted
link can never appear on a coach's page however well it matches.

Retrieval is hybrid: a resource's tags must match the key's map and side
(allowed() below), and among those, meaning decides. Every resource is
embedded once with an open-source sentence
embedding model from Hugging Face (MODEL below, run locally, nothing sent
anywhere), and so is one query per (map, side, topic) a coach's read can be
about. Each key keeps its closest resources above MIN_SIMILARITY. That table
is what ships: the server looks a key up (app/resources.py) and needs no
model, no torch and no network, and the coach's read may cite only what was
retrieved for the facts a point rests on (coach.check enforces it).

This is retrieval-augmented generation with the retrieval done ahead of
time, because the questions are a small fixed set and the box has 8GB and
no reason to load a language model to answer them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.resources import INDEX, KEYS, query_text  # noqa: E402

SOURCE = ROOT / "outreach" / "resource-candidates.md"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TOP_K = 3
# Cosine similarity below this is "about something else", read off the
# preview once the tag filter was in: same map and side, wrong topic, sits
# under it.
MIN_SIMILARITY = 0.45

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def parse(md: str) -> list[dict]:
    """Every linked row of every table: tags, title, url, why, KEEP."""
    out = []
    for line in md.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not LINK.search(" ".join(cells)):
            continue
        tags, keep = cells[0], cells[-1]
        links_cell = next(c for c in cells[1:] if LINK.search(c))
        why = " ".join(c for c in cells[1:-1] if c is not links_cell)
        for title, url in LINK.findall(links_cell):
            mp = tags.split("/")[0].strip()
            if (title.lower().startswith(("retake a", "retake b", "retake mid"))
                    and mp.lower() not in title.lower()):
                # "[Retake A] and [Retake B on Ancient - Coach v1dma]": the
                # first link's title alone does not name its map.
                title = f"{title} ({mp})"
            out.append({
                "id": f"R{len(out) + 1}",
                "title": LINK.sub(r"\1", title),
                "url": url,
                "kind": "video" if "youtube.com" in url else "article",
                "tags": tags,
                "text": f"{tags}. {title}. {LINK.sub(r'\1', why)}".strip(),
                "vetted": keep.strip().upper().startswith("KEEP"),
            })
    return out


def embed(texts):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, device="cpu")
    return model.encode(texts, normalize_embeddings=True)


def scope_of(tags: str) -> tuple[str, set]:
    """(map, sides) from a row's tags: "nuke / CT / outside" is ("nuke",
    {"ct"}); "any / trading" and "economy / force" are ("any", {"ct", "t"})."""
    parts = [t.strip().lower() for t in tags.split("/")]
    mp = parts[0] if parts and parts[0] not in ("economy",) else "any"
    sides = set()
    if len(parts) > 1:
        for s in re.split(r"[ ,]+", parts[1]):
            if s in ("ct", "t"):
                sides.add(s)
    return mp, sides or {"ct", "t"}


def allowed(resource: dict, key: tuple[str, str, str]) -> bool:
    """The metadata filter: a Nuke CT guide is never retrieved for Nuke T or
    for Train, however close the words are. Meaning alone did exactly that
    in the first preview (2026-10-14), so retrieval filters first and ranks
    second."""
    mp, sides = scope_of(resource["tags"])
    kmap, kside, _topic = key
    if kmap == "any":
        return mp == "any"
    return mp == kmap and kside in sides


def retrieve(resources, only_vetted=True):
    pool = [r for r in resources if r["vetted"] or not only_vetted]
    if not pool:
        return {}
    vecs = embed([r["text"] for r in pool])
    keys = list(KEYS())
    qs = embed([query_text(*k) for k in keys])
    sims = qs @ vecs.T
    out = {}
    for k, row in zip(keys, sims):
        ok = [i for i in range(len(pool)) if allowed(pool[i], k)]
        best = sorted(ok, key=lambda i: -row[i])[:TOP_K]
        hits = [(pool[i]["id"], round(float(row[i]), 3)) for i in best
                if row[i] >= MIN_SIMILARITY]
        if hits:
            out["|".join(k)] = hits
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()
    resources = parse(SOURCE.read_text(encoding="utf-8"))
    vetted = [r for r in resources if r["vetted"]]
    print(f"{len(resources)} resources in {SOURCE.name}, {len(vetted)} marked KEEP")
    if args.preview:
        by_id = {r["id"]: r for r in resources}
        for key, hits in retrieve(resources, only_vetted=False).items():
            print(f"\n{key}")
            for rid, sim in hits:
                r = by_id[rid]
                print(f"  {sim:.2f} {'KEEP ' if r['vetted'] else 'unvetted '}"
                      f"{r['title']}")
        return
    index = {"model": MODEL, "built": date.today().isoformat(),
             "min_similarity": MIN_SIMILARITY,
             "resources": {r["id"]: {k: r[k] for k in ("title", "url", "kind")}
                           for r in vetted},
             "keys": {k: [rid for rid, _ in v]
                      for k, v in retrieve(resources).items()}}
    INDEX.write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"wrote {INDEX.relative_to(ROOT)}: {len(index['resources'])} resources, "
          f"{len(index['keys'])} keys with a match")


if __name__ == "__main__":
    main()
