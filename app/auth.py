"""Passwords, sessions and CSRF.

All of it on the standard library. `hashlib.scrypt` is a memory-hard KDF built
into Python, which is the part that matters; bcrypt and argon2 are fine too but
they are a compiled dependency to install and pin on every box, and this buys
nothing over scrypt at these parameters.

Three rules this module exists to keep:

  * A password is never stored, and never logged. Only the scrypt output is.
  * A session cookie is never stored. Only its SHA-256 is, so a leaked database
    backup is not a set of live logins.
  * Comparisons of secrets go through `hmac.compare_digest`, never `==`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets

from . import db

# scrypt cost. n=2**15 with r=8 is roughly 100ms and 32MB per hash on a small
# VPS — slow enough to matter to an attacker, fast enough that a login does not
# feel broken. If logins get sluggish under load, raise the box before lowering
# these.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
MAX_PASSWORD_BYTES = 1024      # scrypt on unbounded input is a free DoS

# scrypt needs roughly 128 * n * r bytes, which at these parameters is 33.5MB —
# just over OpenSSL's 32MB default, so it refuses with "memory limit exceeded"
# unless maxmem is raised explicitly. Derived rather than hard-coded so tuning
# the cost above cannot silently break every login.
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2

SESSION_DAYS = 30
SESSION_COOKIE = "cp_session"

# Login rate limit: this many failures for one address inside the window before
# it stops accepting attempts. Keyed on the email rather than the IP because
# the attack worth stopping is a password guess against one known account.
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW_MINUTES = 15

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32,
                            maxmem=SCRYPT_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, want_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return False
        # maxmem is derived from the parameters IN THE STORED HASH, not from
        # the current constants, so raising the cost later does not lock out
        # everyone who registered before the change.
        got = hashlib.scrypt(password.encode("utf-8"),
                             salt=base64.b64decode(salt_b64),
                             n=int(n), r=int(r), p=int(p), dklen=32,
                             maxmem=128 * int(n) * int(r) * 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(want_b64))


def password_problem(password: str) -> str | None:
    """Why this password is not acceptable, or None.

    Length only. Composition rules ("one number, one symbol") measurably push
    people toward Passw0rd! and are not worth the friction.
    """
    if len(password) < 10:
        return "Password needs to be at least 10 characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "That password is too long."
    return None


def email_problem(email: str) -> str | None:
    if not EMAIL_RE.match(email or ""):
        return "That does not look like an email address."
    if len(email) > 254:
        return "That email address is too long."
    return None


def email_key(email: str) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------- sessions

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(user_id: int, user_agent: str = "") -> tuple[str, str]:
    """Create a session. Returns (cookie_value, csrf_token)."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.execute(
        """INSERT INTO sessions (token_hash, user_id, csrf, created_at,
                                 expires_at, user_agent)
           VALUES (?,?,?,?,?,?)""",
        _token_hash(token), user_id, csrf, db.utcnow(),
        db.in_days(SESSION_DAYS), (user_agent or "")[:300])
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
               db.utcnow(), user_id)
    return token, csrf


def session_user(token: str | None):
    """The user for a cookie, or None. Expired sessions are deleted on sight."""
    if not token:
        return None
    row = db.one(
        """SELECT s.csrf, s.expires_at, u.*
             FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?""", _token_hash(token))
    if row is None:
        return None
    if row["expires_at"] <= db.utcnow():
        end_session(token)
        return None
    return row


def end_session(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", _token_hash(token))


def end_all_sessions(user_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = ?", user_id)


def check_csrf(session_row, submitted: str | None) -> bool:
    if session_row is None or not submitted:
        return False
    return hmac.compare_digest(str(session_row["csrf"]), submitted)


# ---------------------------------------------------------------- throttling

def too_many_attempts(email: str) -> bool:
    key = email_key(email)
    cutoff = db.minutes_ago(ATTEMPT_WINDOW_MINUTES)
    # Prune on read. There is no cron on a box this size, and the table is only
    # ever scanned by this query, so old rows cost nothing until they are here.
    db.execute("DELETE FROM login_attempts WHERE at < ?", cutoff)
    row = db.one("""SELECT COUNT(*) AS n FROM login_attempts
                     WHERE email_key = ? AND at >= ?""", key, cutoff)
    return bool(row and row["n"] >= MAX_ATTEMPTS)


def record_failure(email: str) -> None:
    db.execute("INSERT INTO login_attempts (email_key, at) VALUES (?,?)",
               email_key(email), db.utcnow())


def clear_attempts(email: str) -> None:
    db.execute("DELETE FROM login_attempts WHERE email_key = ?", email_key(email))
