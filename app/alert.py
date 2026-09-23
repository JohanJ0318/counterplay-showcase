"""Tell Johan when something actually happens, so he does not have to watch.

WHY THIS EXISTS
---------------
Six cold emails went out on 2026-09-23 and every one of them ends with
"make a team, drop the demo in". The first NECC match night is 30
September, a Wednesday, and matches finish late. A coach who signs up at
23:00 and uploads a demo is the single result this whole season is being
measured on, and until now nothing told us it had happened. It would have
been found whenever `/admin/traffic` was next opened, which might be days.

The plan says to read that first report before the coach does and to reply
the same day. That is only possible if we know.

WHAT IT IS NOT
--------------
Not analytics, not a queue, not a dashboard. Two events, one line each, to
one address. `traffic.py` already answers "how many people came"; this
answers "is someone standing at the door right now".

THE ONE HARD RULE: NEVER BREAK THE CALLER
-----------------------------------------
This sits in the signup request path. A coach's account must be created
whether or not the mail provider is reachable, so:

  * every failure is swallowed, including import-time misconfiguration;
  * the send happens on a daemon thread, because `mail.send` allows itself
    a 12 second timeout and no signup should ever wait that long for a
    notification the person signing up will never see;
  * nothing here touches the database. `db.py` hands out thread-local
    connections, so a background thread doing its own queries would open a
    second connection nobody closes. Callers pass in finished strings.

If the alert fails, the thing that mattered still happened, and the audit
table still recorded it.
"""
from __future__ import annotations

import os
import threading

from . import mail

# Where alerts go. Falls back to the legal contact, which is already set on
# the box, so this works without a deploy-time environment change.
TO = (os.environ.get("COUNTERPLAY_ALERT_TO", "").strip()
      or os.environ.get("COUNTERPLAY_LEGAL_EMAIL", "").strip())

TIMEOUT_SECONDS = 20


def configured() -> bool:
    return bool(TO and mail.configured())


def _deliver(subject: str, body: str) -> None:
    try:
        mail.send(TO, subject, body)
    except Exception:
        # Deliberately bare. This runs on a thread with nobody to catch it,
        # and an alert that fails must never be louder than the event it was
        # reporting.
        pass


def fire(subject: str, body: str) -> bool:
    """Send an alert without making the caller wait or care.

    Returns whether a thread was started, which is what the tests assert on.
    A False here means "not configured", never "failed to send": delivery is
    not knowable from the request that triggered it.
    """
    if not configured():
        return False
    try:
        t = threading.Thread(target=_deliver, args=(subject, body),
                             daemon=True, name="alert")
        t.start()
        return True
    except Exception:
        return False


# ------------------------------------------------------------- the two events

def signup(team: str, email: str, league: str, role: str) -> bool:
    """A new account. The only number in the outreach plan that counts."""
    return fire(
        "Counterplay: new signup, %s" % (team or "unnamed team"),
        "Someone made a team.\n\n"
        "  team    %s\n"
        "  league  %s\n"
        "  role    %s\n"
        "  email   %s\n\n"
        "They have not uploaded anything yet. If a demo follows, read the "
        "report before they do.\n\n"
        "https://counterplaycs.com/admin/traffic\n"
        % (team, league or "(none given)", role, email))


def parsed(team: str, filename: str, rounds: int, map_name: str) -> bool:
    """A demo finished parsing. Same day turnaround starts here."""
    return fire(
        "Counterplay: demo parsed for %s" % (team or "unknown team"),
        "A demo finished parsing.\n\n"
        "  team    %s\n"
        "  file    %s\n"
        "  map     %s\n"
        "  rounds  %s\n\n"
        "Read it yourself before they do. If something in it is wrong, say "
        "so first.\n" % (team, filename, map_name or "unknown", rounds))
