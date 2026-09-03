#!/usr/bin/env python3
"""
Counterplay — FACEIT league fetcher.

Pulls a league's championships, matches and per-map stats from the FACEIT Data API
and caches everything to disk as JSON. No demo files involved.

    set FACEIT_API_KEY=...            (Windows)  /  export FACEIT_API_KEY=...
    python fetch.py --org NECC
    python fetch.py --championship 849f3f08-0eab-47de-9089-8d2d26487e03

Everything lands in ./cache/. Re-running only fetches what's missing, so it is safe
to run daily during a season — that is the intended use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://open.faceit.com/data/v4"
CACHE = Path("cache")
SLEEP = 0.35          # be polite; the API returns 429 if you hammer it


def get(path: str, key: str, **params):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(SLEEP)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # forfeits and byes have no stats
            if e.code == 429:
                wait = 2 ** attempt
                print(f"    rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"    HTTP {e.code} on {path}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"    failed {path}: {e}", file=sys.stderr)
            return None
    return None


def cached(name: str, fn):
    """Fetch once, keep forever. Match data never changes after a match finishes."""
    p = CACHE / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    data = fn()
    if data is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    return data


def find_championships(key: str, org_name: str, game: str):
    res = get("/search/organizers", key, name=org_name, offset=0, limit=5) or {}
    items = res.get("items") or []
    if not items:
        print(f"No organizer found for {org_name!r}", file=sys.stderr)
        return []
    org = items[0]
    oid = org.get("organizer_id")
    print(f"organizer: {org.get('name')} ({oid})")

    out, offset = [], 0
    while True:
        page = get(f"/organizers/{oid}/championships", key, offset=offset, limit=50) or {}
        chunk = page.get("items") or []
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 50:
            break
        offset += 50

    champs = []
    for c in out:
        cid = c.get("championship_id") or c.get("competition_id") or c.get("id")
        g = c.get("game_id") or c.get("game")
        if not cid or (game and g != game):
            continue
        if str(c.get("status", "")).lower() == "cancelled":
            continue
        champs.append({"id": cid, "name": c.get("name", "?"), "status": c.get("status")})
    return champs


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a FACEIT league into ./cache")
    ap.add_argument("--key", default=os.environ.get("FACEIT_API_KEY"))
    ap.add_argument("--org", help="Organizer name, e.g. NECC")
    ap.add_argument("--championship", action="append", default=[],
                    help="Championship id (repeatable). Skips organizer lookup.")
    ap.add_argument("--game", default="cs2")
    ap.add_argument("--max-matches", type=int, default=400,
                    help="Safety cap per championship")
    args = ap.parse_args()

    if not args.key:
        print("Set FACEIT_API_KEY or pass --key", file=sys.stderr)
        return 2
    if not (args.org or args.championship):
        print("Give --org NECC or --championship <id>", file=sys.stderr)
        return 2

    CACHE.mkdir(exist_ok=True)

    if args.championship:
        champs = [{"id": c, "name": c, "status": "?"} for c in args.championship]
    else:
        champs = find_championships(args.key, args.org, args.game)
        print(f"{len(champs)} {args.game} championship(s)\n")

    league = {"organizer": args.org or "league", "championships": []}
    total_matches = total_stats = 0

    for ch in champs:
        cid = ch["id"]
        print(f"-> {ch['name']}")
        matches, offset = [], 0
        while offset < args.max_matches:
            page = get(f"/championships/{cid}/matches", args.key,
                       type="past", offset=offset, limit=50) or {}
            chunk = page.get("items") or []
            if not chunk:
                break
            matches.extend(chunk)
            if len(chunk) < 50:
                break
            offset += 50

        recorded = []
        for stub in matches:
            mid = stub.get("match_id")
            if not mid:
                continue
            detail = cached(f"match/{mid}", lambda: get(f"/matches/{mid}", args.key))
            stats = cached(f"stats/{mid}", lambda: get(f"/matches/{mid}/stats", args.key))
            total_matches += 1
            if stats and stats.get("rounds"):
                total_stats += 1
                recorded.append({"match_id": mid, "detail": detail, "stats": stats})

        print(f"   {len(matches)} matches, {len(recorded)} with stats")
        if recorded:
            league["championships"].append(
                {"id": cid, "name": ch["name"], "matches": recorded})

    out = CACHE / "league.json"
    out.write_text(json.dumps(league), encoding="utf-8")
    print(f"\n{total_matches} matches seen, {total_stats} with stats "
          f"(the rest are forfeits or byes)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
