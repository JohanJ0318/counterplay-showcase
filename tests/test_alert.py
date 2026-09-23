"""The alert must never be able to break the thing it is reporting.

app/alert.py sits inside the signup request. A coach's account has to be
created whether or not Resend is reachable, so every one of these asserts
the same property from a different angle: nothing in here raises, and
nothing in here blocks.
"""
import time

from app import alert


def test_unconfigured_is_silent_and_false(monkeypatch):
    """No address set is the normal state on a dev box, not an error."""
    monkeypatch.setattr(alert, "TO", "")
    assert alert.configured() is False
    assert alert.fire("subject", "body") is False
    assert alert.signup("Team", "a@b.edu", "NECC", "coach") is False
    assert alert.parsed("Team", "x.dem", 24, "de_mirage") is False


def test_mail_not_configured_is_also_silent(monkeypatch):
    """An address with no SMTP behind it must not raise either."""
    monkeypatch.setattr(alert, "TO", "johan@example.com")
    monkeypatch.setattr(alert.mail, "configured", lambda: False)
    assert alert.configured() is False
    assert alert.fire("subject", "body") is False


def test_a_raising_provider_does_not_reach_the_caller(monkeypatch):
    """The whole point. mail.send explodes; fire() still returns normally."""
    calls = []

    def boom(*a, **kw):
        calls.append(a)
        raise RuntimeError("smtp is down")

    monkeypatch.setattr(alert, "TO", "johan@example.com")
    monkeypatch.setattr(alert.mail, "configured", lambda: True)
    monkeypatch.setattr(alert.mail, "send", boom)

    assert alert.fire("subject", "body") is True  # thread started
    for _ in range(100):                          # let the daemon run
        if calls:
            break
        time.sleep(0.01)
    assert calls, "mail.send should have been attempted"


def test_a_slow_provider_does_not_hold_the_request(monkeypatch):
    """mail.send allows itself 12 seconds. A signup must not wait for it."""
    monkeypatch.setattr(alert, "TO", "johan@example.com")
    monkeypatch.setattr(alert.mail, "configured", lambda: True)
    monkeypatch.setattr(alert.mail, "send",
                        lambda *a, **kw: time.sleep(3))

    start = time.monotonic()
    assert alert.fire("subject", "body") is True
    assert time.monotonic() - start < 0.5, "fire() blocked on the send"


def test_both_events_carry_what_they_need(monkeypatch):
    """The message has to be readable on a phone at 23:00 without context."""
    sent = []
    monkeypatch.setattr(alert, "TO", "johan@example.com")
    monkeypatch.setattr(alert.mail, "configured", lambda: True)
    monkeypatch.setattr(alert, "_deliver",
                        lambda subj, body: sent.append((subj, body)))
    monkeypatch.setattr(alert.threading, "Thread",
                        lambda target, args, daemon, name: type(
                            "T", (), {"start": lambda self: target(*args)})())

    alert.signup("Ashland Eagles", "coach@example.edu", "NECC", "coach")
    subj, body = sent[-1]
    assert "Ashland Eagles" in subj
    assert "coach@example.edu" in body

    alert.parsed("Ashland Eagles", "match1.dem", 24, "de_mirage")
    subj, body = sent[-1]
    assert "Ashland Eagles" in subj
    assert "match1.dem" in body and "de_mirage" in body and "24" in body
