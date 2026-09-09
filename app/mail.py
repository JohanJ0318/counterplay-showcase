"""Sending mail, on the standard library, configured entirely by environment.

The product sent no email at all. That was fine while the only account was the
one that built it and became the reason a coach could be permanently locked
out of their own team's data.

WHY SMTP AND NOT AN API
-----------------------
Every provider a small product would pick, Resend, Postmark, SES, Mailgun,
Fastmail, speaks SMTP. An API client would pin this to one of them and add a
dependency to install on the box. `smtplib` is already there and switching
provider becomes four environment variables rather than a rewrite.

NOTHING IS HARD-CODED
---------------------
No host, no key, no from-address in the repository. `configured()` is false
until the box has them, and every caller checks it, so a machine with no mail
set up fails visibly at the point of sending rather than pretending to send.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
No queue, no retries, no bounce handling. One send, in the request, with a
timeout. At the volume this product will do for a year that is the honest
amount of machinery, and a queue that nobody watches is worse than none.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

# The whole configuration surface.
HOST = os.environ.get("COUNTERPLAY_SMTP_HOST", "")
PORT = int(os.environ.get("COUNTERPLAY_SMTP_PORT", "587") or 587)
USER = os.environ.get("COUNTERPLAY_SMTP_USER", "")
PASSWORD = os.environ.get("COUNTERPLAY_SMTP_PASSWORD", "")
FROM_ADDR = os.environ.get("COUNTERPLAY_MAIL_FROM", "")
FROM_NAME = os.environ.get("COUNTERPLAY_MAIL_FROM_NAME", "Counterplay")

# Where links in an email point. Without this a reset link would have to be
# built from the request's Host header, which is attacker-controlled.
SITE_URL = os.environ.get("COUNTERPLAY_SITE_URL", "https://counterplaycs.com")

# Mail goes out as no-reply@, and people reply to no-reply addresses anyway.
# Without a Reply-To those replies bounce or vanish, and the person who most
# needs help, somebody stuck outside their own account, is exactly the person
# most likely to hit reply.
REPLY_TO = os.environ.get("COUNTERPLAY_MAIL_REPLY_TO", "")

TIMEOUT_SECONDS = 12


def configured() -> bool:
    """Whether this box can send mail at all."""
    return bool(HOST and FROM_ADDR)


def site_url(path: str = "") -> str:
    return SITE_URL.rstrip("/") + (path if path.startswith("/") else "/" + path)


def send(to: str, subject: str, body: str, *, reply_to: str = "",
         headers: dict | None = None) -> None:
    """Send one plain-text message. Raises if it could not be sent.

    Plain text only. A coach reading a password reset does not need a layout,
    and an HTML mail is one more thing to get wrong in a client nobody tests.
    """
    if not configured():
        raise RuntimeError("mail is not configured on this machine")

    msg = EmailMessage()
    msg["From"] = formataddr((FROM_NAME, FROM_ADDR))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    reply = reply_to or REPLY_TO
    if reply:
        msg["Reply-To"] = reply
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)

    context = ssl.create_default_context()
    if PORT == 465:
        with smtplib.SMTP_SSL(HOST, PORT, timeout=TIMEOUT_SECONDS,
                              context=context) as s:
            if USER:
                s.login(USER, PASSWORD)
            s.send_message(msg)
        return
    with smtplib.SMTP(HOST, PORT, timeout=TIMEOUT_SECONDS) as s:
        s.starttls(context=context)
        if USER:
            s.login(USER, PASSWORD)
        s.send_message(msg)


# ------------------------------------------------------------------ messages

def reset_email(name: str, link: str, hours: int) -> tuple[str, str]:
    """(subject, body) for a password reset.

    Says plainly that an unrequested one can be ignored, because the single
    most common reaction to an unexpected reset mail is to click the link to
    find out what it is.
    """
    who = f"{name}, " if name else ""
    return ("Reset your Counterplay password", f"""Hi {who}

Somebody asked to reset the password on this Counterplay account. If that
was you, open this link within {hours} hour{"s" if hours != 1 else ""}:

{link}

It works once. Using it also signs this account out everywhere, so if
somebody else has been in your account, they will be signed out too.

If you did not ask for this, you can ignore this email. Nothing has changed
and the link expires on its own.

Counterplay
{site_url()}
""")
