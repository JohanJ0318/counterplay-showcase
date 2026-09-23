"""Who came, read out of the access log instead of out of the browser.

WHY THERE IS NO SCRIPT ON THE PAGE
----------------------------------
Every hosted analytics product works by putting a beacon in the visitor's
browser. This one does not, because the landing page tells athletics
departments in plain language what happens to their data, and a third-party
script quietly disagreeing with that section is not a trade worth making for
a visitor count. Caddy already writes down every request; that is the same
information, gathered by the server that was answering anyway.

So: no beacon, no cookie, no third party, no change to the CSP, and nothing
new for a coach to consent to.

WHAT LEAVES THIS MODULE
-----------------------
Counts. Addresses are hashed before they are stored in any structure here,
`/r/<token>` is normalised to `/r/*` before anything is counted, and no raw
line is ever returned. CLAUDE.md is explicit that the log holds share tokens
in plain text and that excerpts of it do not get pasted anywhere; that rule
is enforced in `_norm` rather than remembered.

COUNTING PEOPLE IS AN ESTIMATE AND IS LABELLED AS ONE
-----------------------------------------------------
Three quarters of what reaches this server is not a person. Two filters do
most of the work:

  * An address that has ever asked for /wp-admin, /.env or /.git is a
    scanner, and it is dropped ENTIRELY, including its hits on the homepage.
    Filtering on the user agent instead leaves them all in, because they
    send a Chrome one.
  * The homepage inlines its CSS and JS, so the only sub-resources a browser
    fetches are the poster frame and the icons. An address that asked for
    the page and never for those was not rendering it.

Neither is exact. An address is not a person: a phone on a carrier NAT
shares one with thousands, and the same reader on wifi and then on data
counts twice. The numbers are a floor with a consistent method, which makes
them worth comparing against each other over time, and not worth quoting to
anybody as a headcount.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import Counter, defaultdict

LOG = "/var/log/caddy/counterplay.log"

# Paths that only exist on somebody else's software. Asking for one is a probe.
PROBE = re.compile(
    r"^/(wp-|wordpress|wp/|blog/|index\.php|xmlrpc|\.env|\.git|\.aws|\.ssh|"
    r"phpmyadmin|pma|admin\.|administrator|shell|cgi-bin|vendor|config\.|"
    r"backup|autodiscover|owa|ecp|boaform|hudson|jenkins|solr|actuator|"
    r"telescope|debug|phpinfo|info\.php|test\.php|login\.action|struts|"
    r"\.aspx|\.asp$|\.jsp|credentials|secrets)", re.I)

# Loaded by a browser rendering the landing page, by nothing else.
BROWSER_ASSET = re.compile(r"^/(media/loop-poster\.jpg|favicon\.|apple-touch|"
                           r"icon-\d+\.png)", re.I)

DECLARED_BOT = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|headless|curl|wget|"
    r"python-requests|httpx|scrapy|monitor|uptime|censys|zgrab|masscan|"
    r"nuclei|semrush|ahrefs|dotbot|petalbot|yandex|applebot|discord|slack|"
    r"twitter|whatsapp|telegram|linkedin|preview|scanner|probe|"
    r"UnifiedPaths", re.I)

# The pages a person could be reading, after normalising.
READABLE = {"/", "/signup", "/login", "/forgot", "/privacy", "/terms",
            "/unsubscribe", "/sample-report", "/sample-report.html",
            "/dashboard", "/account", "/matches", "/players", "/trends",
            "/stats", "/upload", "/r/*", "/match/*", "/player/*", "/team/*"}

_LOCK = threading.Lock()
_CACHE: dict = {}


def _norm(path: str) -> str:
    """Strip the query and collapse anything that carries an identifier.

    The share token collapse is the one that matters: it happens before the
    path is counted, stored or returned, so no token can reach a page.
    """
    path = path.split("?")[0]
    for prefix in ("/r/", "/reset/", "/match/", "/player/", "/team/"):
        if path.startswith(prefix):
            return prefix + "*"
    return path


def _anon(ip: str) -> str:
    return hashlib.sha256(("counterplay" + ip).encode()).hexdigest()[:10]


def _rows():
    """One compact tuple per request. Caddy writes a text prefix then JSON."""
    with open(LOG, "r", errors="replace") as fh:
        for line in fh:
            brace = line.find("{")
            if brace < 0:
                continue
            try:
                rec = json.loads(line[brace:])
            except ValueError:
                continue
            req = rec.get("request") or {}
            uri = req.get("uri")
            if not uri:
                continue
            headers = req.get("headers") or {}
            agent = " ".join(headers.get("User-Agent") or [""])
            ref = " ".join(headers.get("Referer") or [""])
            yield (line[:10].replace("/", "-"),
                   _anon(req.get("client_ip") or req.get("remote_ip") or "?"),
                   _norm(uri), req.get("method", ""), rec.get("status", 0),
                   agent, ref)


def read(force: bool = False) -> dict:
    """Aggregate the whole log. Cached until the file grows.

    Re-reading 55MB on every page view would make the page the most
    expensive thing on the box. The cache key is the file's size and mtime,
    so it re-reads exactly when there is something new and never otherwise.
    """
    try:
        st = os.stat(LOG)
    except OSError as exc:
        return {"error": "no access log at %s (%s)" % (LOG, exc.__class__.__name__)}

    key = (st.st_size, int(st.st_mtime))
    with _LOCK:
        if not force and _CACHE.get("key") == key:
            return _CACHE["value"]

    records = list(_rows())

    scanners, asset_fetchers = set(), set()
    for _day, ip, path, _m, _s, _ua, _ref in records:
        if PROBE.search(path):
            scanners.add(ip)
        elif BROWSER_ASSET.search(path):
            asset_fetchers.add(ip)

    total = len(records)
    scanner_hits = declared = 0
    pages = Counter()
    signup = Counter()
    referrers = Counter()
    per_day_views = Counter()
    per_day_people = defaultdict(set)
    per_day_real = defaultdict(set)
    seen_days = defaultdict(set)
    people, home, deeper = set(), set(), set()
    first = last = None

    for day, ip, path, method, status, agent, ref in records:
        if day:
            first = day if first is None else min(first, day)
            last = day if last is None else max(last, day)
        if method == "POST" and path == "/signup":
            signup[status] += 1
        if ip in scanners:
            scanner_hits += 1
            continue
        if DECLARED_BOT.search(agent) or not agent.strip():
            declared += 1
            continue
        if path not in READABLE:
            continue
        pages[path] += 1
        people.add(ip)
        per_day_views[day] += 1
        per_day_people[day].add(ip)
        seen_days[ip].add(day)
        if ip in asset_fetchers:
            per_day_real[day].add(ip)
        if path == "/":
            home.add(ip)
            if ref and "counterplaycs.com" not in ref:
                referrers[re.sub(r"^https?://", "", ref).split("/")[0][:40]] += 1
        else:
            deeper.add(ip)

    real = people & asset_fetchers
    days = sorted(per_day_views)
    value = {
        "covers": (first, last),
        "days_counted": len(days),
        "requests": total,
        "scanner_hits": scanner_hits,
        "scanner_addresses": len(scanners),
        "declared_bots": declared,
        "real_views": sum(pages.values()),
        "saw_any": len(people),
        "saw_home": len(home),
        "real_browsers": len(real),
        "went_deeper": len(deeper),
        "came_back": sum(1 for i in seen_days if len(seen_days[i]) > 1),
        "pages": pages.most_common(16),
        "referrers": referrers.most_common(10),
        "signup": dict(signup),
        "series": [(d, per_day_views[d], len(per_day_people[d]),
                    len(per_day_real[d])) for d in days],
        "log_bytes": st.st_size,
    }
    with _LOCK:
        _CACHE["key"] = key
        _CACHE["value"] = value
    return value
