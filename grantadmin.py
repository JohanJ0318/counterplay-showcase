#!/usr/bin/env python3
"""Grant or revoke the admin flag. Run on the box, never through a browser.

Admin is one power today: naming the map zones, which are shared across every
team on the platform. There is no admin UI and there should not be one until
there is a second thing to administer.

    python grantadmin.py --list
    python grantadmin.py you@example.com
    python grantadmin.py you@example.com --revoke

Migration 16 gives the flag to the lowest user id, which is the founder on a
box with one account and a leftover test account on a development machine.
This is how you correct that rather than editing the database by hand.
"""
from __future__ import annotations

import argparse
import sys

from app import auth, db


def main() -> int:
    ap = argparse.ArgumentParser(description="Grant or revoke admin")
    ap.add_argument("email", nargs="?", help="the account to change")
    ap.add_argument("--revoke", action="store_true", help="take the flag away")
    ap.add_argument("--list", action="store_true", help="show who has it")
    a = ap.parse_args()

    if a.list or not a.email:
        rows = db.query("SELECT id, email, is_admin FROM users ORDER BY id")
        if not rows:
            print("no accounts")
            return 0
        for r in rows:
            print(f"  {r['id']:>3}  {'ADMIN' if r['is_admin'] else '     '}  "
                  f"{r['email']}")
        return 0

    key = auth.email_key(a.email)
    row = db.one("SELECT id, email, is_admin FROM users WHERE email_key = ?", key)
    if row is None:
        print(f"no account for {a.email}", file=sys.stderr)
        return 1
    want = 0 if a.revoke else 1
    if row["is_admin"] == want:
        print(f"{row['email']} is already "
              f"{'an admin' if want else 'not an admin'}")
        return 0
    db.execute("UPDATE users SET is_admin = ? WHERE id = ?", want, row["id"])
    db.audit(None, "grant_admin" if want else "revoke_admin", row["email"])
    print(f"{row['email']} is now {'an admin' if want else 'not an admin'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
