"""SQLite access.

Deliberately no ORM. The queries here are a dozen statements over eight tables,
all of them written once; an ORM would add a dependency, a migration tool and a
layer of indirection to save nothing. If the schema ever gets complicated
enough to want one, that is the signal to move to Postgres anyway.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

DB_PATH = Path(os.environ.get("COUNTERPLAY_DB", ROOT / "data" / "counterplay.db"))
DEMO_DIR = Path(os.environ.get("COUNTERPLAY_DEMOS", ROOT / "data" / "demos"))


def utcnow() -> str:
    """ISO-8601 UTC to the second. Sorts as text, reads as English."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        microsecond=0).isoformat()


def in_hours(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(
        microsecond=0).isoformat()


def minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).replace(
        microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Foreign keys are OFF by default in SQLite and are per-connection, not per
    # database. Forgetting this is how ON DELETE CASCADE quietly does nothing.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init() -> None:
    """Create the schema, then bring it up to date. Safe on every boot."""
    from . import migrations
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    sql = (APP_DIR / "schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(sql)
        applied = migrations.run(conn)
    for line in applied:
        print(f"  migrated {line}")


def query(sql: str, *args) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def one(sql: str, *args) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(sql, args).fetchone()


def execute(sql: str, *args) -> int:
    """Run a write and return lastrowid."""
    with connect() as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid


def audit(user_id: int | None, action: str, detail: str = "") -> None:
    execute("INSERT INTO audit (at, user_id, action, detail) VALUES (?,?,?,?)",
            utcnow(), user_id, action, detail)


# ---------------------------------------------------------------- teams

def team_for_user(user_id: int) -> sqlite3.Row | None:
    """The team this user belongs to, with their role in it.

    v1 assumes one team per user. That is true of every coach and player in a
    college league, and the schema is a join table rather than a column so the
    day it stops being true is a query change and not a migration.
    """
    return one(
        """SELECT t.*, m.member_role
             FROM teams t
             JOIN team_members m ON m.team_id = t.id
            WHERE m.user_id = ?
         ORDER BY m.created_at
            LIMIT 1""", user_id)


def team_by_slug(slug: str) -> sqlite3.Row | None:
    return one("SELECT * FROM teams WHERE slug = ?", slug)


def team_roster(team_id: int) -> list[sqlite3.Row]:
    return query(
        """SELECT u.id, u.name, u.email, u.role, u.plan, m.member_role, m.created_at
             FROM users u
             JOIN team_members m ON m.user_id = u.id
            WHERE m.team_id = ?
         ORDER BY CASE m.member_role WHEN 'owner' THEN 0 WHEN 'coach' THEN 1
                                     ELSE 2 END, u.name""", team_id)


def slugify(name: str, taken=None) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    base = "-".join(p for p in base.split("-") if p) or "team"
    slug, n = base, 2
    while team_by_slug(slug) is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


# ---------------------------------------------------------------- demos

def claim_demo(demo_id: int, team_id: int, *, actor_id: int | None = None) -> bool:
    """Attribute a league-pulled demo to a team that signed up.

    This is the ONLY sanctioned way a demo gains a team_id after the fact, and
    it exists so the rule is written down somewhere rather than living in a
    stray UPDATE:

      * A demo may only be claimed by a team that has an account. Pulled demos
        exist to build aggregate baselines; a team that never signed up never
        gets a profile, a page, or a report out of them.
      * A claim is recorded in the audit log, because "why does this team have
        that match" needs an answer that is not a guess.

    What this does NOT verify is that the team actually played in the match —
    that needs the FACEIT team ids off the match detail, which are not stored
    yet. Until they are, only call this from a path where the claim has been
    checked against the match roster.
    """
    if one("SELECT id FROM teams WHERE id = ?", team_id) is None:
        return False
    row = one("SELECT id, team_id FROM demos WHERE id = ?", demo_id)
    if row is None or row["team_id"] is not None:
        return False
    execute("UPDATE demos SET team_id = ? WHERE id = ?", team_id, demo_id)
    audit(actor_id, "claim_demo", f"demo={demo_id} team={team_id}")
    return True



def team_demos(team_id: int, limit: int = 50) -> list[sqlite3.Row]:
    return query("""SELECT * FROM demos WHERE team_id = ?
                 ORDER BY created_at DESC LIMIT ?""", team_id, limit)


def demo_counts(team_id: int) -> dict[str, int]:
    rows = query("""SELECT status, COUNT(*) AS n, COALESCE(SUM(rounds),0) AS r
                      FROM demos WHERE team_id = ? GROUP BY status""", team_id)
    out = {"total": 0, "parsed": 0, "pending": 0, "failed": 0, "rounds": 0}
    for r in rows:
        out["total"] += r["n"]
        out["rounds"] += r["r"] or 0
        if r["status"] in out:
            out[r["status"]] += r["n"]
        elif r["status"] == "parsing":
            out["pending"] += r["n"]
    return out
