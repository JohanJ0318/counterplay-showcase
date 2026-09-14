"""Compute a team's season once, not once per section that needs it.

Team stats calls `advice.monday`, which walks every round's position samples to
find the team's habits. Then the page walks them again for its own three
tables, and again for the utility cards, because each of those asks the same
question of the same rounds and none of them knows the others exist. Measured
on an eleven-match season that was 0.9 seconds of a 2.4 second page, and the
expensive half of it grows with every demo uploaded: `movement.scan` unpacks
and zone-assigns every position sample in the season, so a team with thirty
matches pays three times what a team with eleven pays, twice.

WHY NOT A REQUEST-SCOPED CACHE. That fixes the duplication inside one render
and throws the work away the moment the response is sent, so the next coach to
open the page pays it again. A season's counts only change when a demo
finishes parsing or somebody names a zone, and both of those are visible in
two small queries. Keying on that instead means the second reader of the page
gets it for nothing, and the first reader after an upload gets fresh numbers.

WHAT IS SAFE TO CACHE HERE. Only functions of `team_id` alone, and only ones
whose result the callers treat as read-only. A cached value is SHARED: if a
caller mutated it the next reader would see the change, so anything that is
handed out and then modified must not be wrapped.

The cache is bounded and keyed by version, so a stale entry is never returned;
it is only ever missed.
"""
from __future__ import annotations

import sqlite3
import threading
from functools import wraps

from . import db

# Entries per wrapped function. One per (team, version), so a busy box holds
# the current version for each team and a couple of superseded ones.
MAX_ENTRIES = 48


def version(team_id: int):
    """What would make this team's counts different, or None if it cannot say.

    A demo arriving, a demo finishing its parse, or a zone being named. The
    first two are visible in the demos table without touching a round row; the
    third is global, because a zone model is per map rather than per team and
    naming one changes every team's positional tables.

    RETURNS None RATHER THAN RAISING when the schema is not there. A cache is
    an optimisation and must never be the reason a call fails: a database that
    has not been through `db.init()` yet, a test running against an empty
    file, a tool pointed at a partial copy. All of those used to work and then
    did not, because this function asks about a table they do not have. None
    means "cannot tell", and the caller computes without caching.
    """
    try:
        d = db.one("""SELECT COUNT(*) n, COALESCE(MAX(id), 0) mx,
                             COALESCE(SUM(status = 'parsed'), 0) ok
                        FROM demos WHERE team_id = ?""", team_id)
        z = db.one("SELECT COUNT(*) n, COALESCE(MAX(rowid), 0) mx "
                   "FROM zone_names")
    except sqlite3.Error:
        return None
    return (d["n"], d["mx"], d["ok"], z["n"], z["mx"])


def by_team(fn):
    """Cache `fn(team_id, ...)` until that team's data changes.

    Extra arguments join the key rather than defeating it, so
    `team_players(3, ours_only=True)` and `team_players(3, ours_only=False)`
    are two entries and not two cache misses. Only hashable extras: anything
    else goes straight through uncached, because a key that cannot be compared
    is a key that silently collides.
    """
    store: dict = {}
    locks: dict = {}
    guard = threading.Lock()

    @wraps(fn)
    def wrapper(team_id, *args, **kwargs):
        if not isinstance(team_id, int):
            return fn(team_id, *args, **kwargs)
        extra = (args, tuple(sorted(kwargs.items())))
        try:
            hash(extra)
        except TypeError:
            return fn(team_id, *args, **kwargs)
        stamp = version(team_id)
        if stamp is None:               # no schema to key on; do not cache
            return fn(team_id, *args, **kwargs)
        key = (team_id, extra, stamp)
        if key in store:
            return store[key]

        # ONE COMPUTE PER KEY, not one per caller.
        #
        # Without this, every request that arrives while the season is being
        # read computes it too: a coach uploading a demo and then opening the
        # page with their roster watching does the two-second walk once per
        # person. Twenty-four threads against a cold cache took thirty-seven
        # seconds for work that takes two.
        #
        # The lock is per key, so two different teams never wait on each
        # other, and it is taken only on a miss.
        with guard:
            lock = locks.setdefault(key, threading.Lock())
        with lock:
            if key in store:            # somebody else finished while we waited
                return store[key]
            out = fn(team_id, *args, **kwargs)
            if len(store) >= MAX_ENTRIES:
                store.pop(next(iter(store)))
            store[key] = out
        with guard:
            locks.pop(key, None)
        return out

    wrapper.cache_clear = store.clear
    return wrapper
