"""Which vetted resources fit a fact. The server side of tools/resources.py.

The retrieval (embedding every resource and every question) runs on the PC
and writes counterplay/resource_index.json; this only reads that table, so
the box needs no model and no torch. A fact maps to one or more keys,
(map, side, topic), and each key to the resources retrieved for it.

The file ships with no resources until Johan marks some KEEP in
outreach/resource-candidates.md, and then the coach's read can link them.
"""
from __future__ import annotations

import json
from pathlib import Path

from counterplay.schema import MAPS

INDEX = Path(__file__).resolve().parent.parent / "counterplay" / "resource_index.json"

SIDES = ("ct", "t")
# What a coach's read point can be about. A map and side for the first two,
# any map for the rest.
MAP_TOPICS = ("default", "retake")
ANY_TOPICS = ("trading", "utility", "economy")

QUERY = {
    "default": "how to play {map} {side} side: a default setup and positions",
    "retake": "how to retake a bombsite on {map} as CT",
    "trading": "trading the opening duel: spacing so a teammate can trade the entry",
    "utility": "throwing flashbangs that blind enemies and not your own teammates",
    "economy": "when to force buy and when to save in CS2 economy",
}


def KEYS():
    """Every (map, side, topic) the index answers."""
    for mp in MAPS:
        name = mp.replace("de_", "")
        for side in SIDES:
            for topic in MAP_TOPICS:
                if topic == "retake" and side != "ct":
                    continue
                yield (name, side, topic)
    for topic in ANY_TOPICS:
        yield ("any", "any", topic)


def query_text(mp: str, side: str, topic: str) -> str:
    return QUERY[topic].format(map=mp.title(), side=side.upper())


_cache: dict | None = None


def index() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(INDEX.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {"resources": {}, "keys": {}}
    return _cache


def keys_for(fact: dict) -> list[tuple[str, str, str]]:
    """The (map, side, topic) keys a fact is about."""
    text = fact.get("text", "").lower()
    kind = fact.get("kind")
    scope = fact.get("scope", "").lower().split()
    out = []
    if kind in ("map_side", "finding") and len(scope) >= 2 and scope[1] in SIDES:
        mp, side = scope[0], scope[1]
        out.append((mp, side, "default"))
        if side == "ct":
            out.append((mp, side, "retake"))
    if "trade" in text or "opening duel" in text:
        out.append(("any", "any", "trading"))
    if "flash" in text:
        out.append(("any", "any", "utility"))
    if any(w in text for w in ("force", "eco round", "full buy", "save")):
        out.append(("any", "any", "economy"))
    return out


def for_fact(fact: dict) -> list[str]:
    """Resource ids retrieved for this fact, closest first, no repeats."""
    ix = index()
    seen: list[str] = []
    for k in keys_for(fact):
        for rid in ix["keys"].get("|".join(k), []):
            if rid in ix["resources"] and rid not in seen:
                seen.append(rid)
    return seen


def get(rid: str) -> dict | None:
    return index()["resources"].get(rid)
