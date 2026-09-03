"""Finding league demos.

Two sources, and the difference matters:

  * `cache/league.json` and `cache/match/*.json`, written by `league/gen/fetch.py`
    against the authenticated Data API. Already on disk, 780 matches deep.
  * `api.faceit.com/match/v2/match/{id}`, which returns `demoURLs` with **no API
    key and no login**. The Data API returns 403 for a match you did not
    organize; this endpoint does not. It is undocumented, so treat a shape
    change as expected rather than as a bug, and keep the cached URLs as the
    fallback.

Demo links expire. The cached ones are worth trying first because they cost
nothing, but a miss is normal and means re-resolving through the live endpoint.

What this module does NOT do: decide who a demo belongs to. League demos are
pulled to build aggregate baselines. Attributing one to a team happens only when
that team has signed up and claimed its FACEIT id.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PUBLIC_MATCH = "https://api.faceit.com/match/v2/match/{mid}"

# A browser UA. The public endpoint is inconsistent about serving default
# Python agents, and this is a plain GET of a page anyone can open.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Accept": "application/json"}

SLEEP = 0.4          # unauthenticated and undocumented: do not hammer it


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}"}
    except Exception as e:                       # DNS, TLS, timeouts
        return {"_error": f"{type(e).__name__}: {e}"}


def resolve_demo_urls(match_id: str) -> list[str]:
    """Live demo URLs for a match, via the public endpoint. [] if unavailable."""
    data = _get_json(PUBLIC_MATCH.format(mid=urllib.parse.quote(match_id)))
    if "_error" in data:
        return []
    payload = data.get("payload", data)
    urls = payload.get("demoURLs") or payload.get("demo_url") or []
    time.sleep(SLEEP)
    return [u for u in urls if isinstance(u, str) and u.startswith("http")]


def iter_cached_matches(cache_dir: Path):
    """Every match in a fetch.py cache, newest first.

    Yields dicts with the fields the pull needs. `demo_url` here is whatever the
    Data API recorded at fetch time — possibly expired, worth trying anyway.
    """
    match_dir = Path(cache_dir) / "match"
    if not match_dir.is_dir():
        return
    rows = []
    for f in match_dir.glob("*"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("status") != "FINISHED":
            continue
        rows.append({
            "match_id": d.get("match_id") or f.stem,
            "competition": d.get("competition_name") or "",
            "finished_at": d.get("finished_at") or 0,
            "demo_urls": [u for u in (d.get("demo_url") or [])
                          if isinstance(u, str) and u.startswith("http")],
            "faceit_url": (d.get("faceit_url") or "").replace("{lang}", "en"),
        })
    rows.sort(key=lambda r: r["finished_at"], reverse=True)
    yield from rows


def head(url: str, timeout: int = 30) -> tuple[int | None, int]:
    """(status, content_length) for a demo URL, without downloading it.

    Used to tell an expired link from a live one before committing to a
    150MB transfer.
    """
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, int(r.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception:
        return None, 0
