"""Password resets: issuing a token, checking one, and spending it.

Kept out of `main.py` because the rules are the whole feature and they should
be readable in one screen without any HTML around them.

THE RULES
---------
  * The token is random from `secrets`, and only its SHA-256 is stored. The
    same rule as session cookies: a leaked backup must not be a set of live
    password resets.
  * One hour. Long enough to find the email, short enough that a link sitting
    in an inbox is not a standing key to the account.
  * One use. Spending it marks it used, and every other outstanding token for
    that account is spent at the same time.
  * Spending one ends every session that account has open. "I forgot my
    password" and "somebody else is in my account" arrive looking identical,
    and only one of them is safe to assume.
  * Requesting one NEVER says whether the address has an account. The reset
    form is otherwise an account enumerator that anyone can query.
"""
from __future__ import annotations

import hashlib
import secrets

from . import auth, db

TOKEN_HOURS = 1

# Requests per address per window. Lower than the login limit because the cost
# of a reset request falls on somebody's inbox, not on this server.
MAX_REQUESTS = 5
WINDOW_MINUTES = 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def too_many(email: str) -> bool:
    """Whether this address has asked too often lately.

    Counted against the account rather than the caller, because the harm being
    prevented is mailing one person repeatedly.
    """
    row = db.one("SELECT id FROM users WHERE email_key = ?", auth.email_key(email))
    if row is None:
        return False
    cutoff = db.minutes_ago(WINDOW_MINUTES)
    n = db.one("""SELECT COUNT(*) AS n FROM password_resets
                   WHERE user_id = ? AND created_at >= ?""", row["id"], cutoff)
    return bool(n and n["n"] >= MAX_REQUESTS)


def issue(email: str, ip: str = "") -> tuple[str, dict] | None:
    """Create a reset token. Returns (token, user row), or None if no account.

    The caller must not tell the browser which of those it got.
    """
    row = db.one("SELECT * FROM users WHERE email_key = ?", auth.email_key(email))
    if row is None:
        return None
    token = secrets.token_urlsafe(32)
    db.execute(
        """INSERT INTO password_resets (token_hash, user_id, created_at,
                                        expires_at, requested_ip)
           VALUES (?,?,?,?,?)""",
        _hash(token), row["id"], db.utcnow(), db.in_hours(TOKEN_HOURS),
        (ip or "")[:64])
    return token, dict(row)


def holder(token: str):
    """The user a live token belongs to, or None.

    None covers every failure the same way: unknown, expired, already spent.
    A reset page that distinguishes them tells an attacker which guesses were
    close.
    """
    if not token:
        return None
    row = db.one(
        """SELECT r.id AS reset_id, r.expires_at, r.used_at, u.*
             FROM password_resets r JOIN users u ON u.id = r.user_id
            WHERE r.token_hash = ?""", _hash(token))
    if row is None or row["used_at"] is not None:
        return None
    if row["expires_at"] <= db.utcnow():
        return None
    return row


def spend(token: str, new_password: str) -> bool:
    """Set the password and burn every outstanding token and session.

    Returns False if the token was not live, so the caller does not have to
    check twice and cannot forget to.
    """
    row = holder(token)
    if row is None:
        return False
    user_id = row["id"]
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               auth.hash_password(new_password), user_id)
    now = db.utcnow()
    # Every outstanding token, not just this one. Two requests in a row must
    # not leave a spare key behind.
    db.execute("""UPDATE password_resets SET used_at = ?
                   WHERE user_id = ? AND used_at IS NULL""", now, user_id)
    auth.end_all_sessions(user_id)
    auth.clear_attempts(row["email"])
    db.audit(user_id, "password_reset", "via emailed token")
    return True
