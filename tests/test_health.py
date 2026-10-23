"""/health says whether the worker is alive, and nothing else.

The uptime monitor (infra/monitor/check.py) reads it. The worker can die while
every page still loads, so the page alone cannot say it. The address is
public, so the body is two fields and must stay that way.
"""
import json
import os
import time

from app import db, main


def _health(monkeypatch, tmp_path, age=None):
    beat = tmp_path / "worker.heartbeat"
    monkeypatch.setattr(db, "HEARTBEAT", beat)
    monkeypatch.setattr(db, "one", lambda *a: None)
    if age is not None:
        db.beat()
        then = time.time() - age
        os.utime(beat, (then, then))
    r = main.health()
    return r.status_code, json.loads(r.body)


def test_a_recent_beat_is_ok(monkeypatch, tmp_path):
    status, body = _health(monkeypatch, tmp_path, age=60)
    assert status == 200 and body["status"] == "ok"


def test_an_old_beat_is_stale(monkeypatch, tmp_path):
    status, body = _health(monkeypatch, tmp_path, age=main.STALE_AFTER + 60)
    assert status == 503 and body["status"] == "stale"


def test_no_beat_ever_is_stale(monkeypatch, tmp_path):
    status, body = _health(monkeypatch, tmp_path)
    assert status == 503 and body == {"status": "stale", "worker_seen": None}


def test_it_says_nothing_else(monkeypatch, tmp_path):
    _, body = _health(monkeypatch, tmp_path, age=60)
    assert set(body) == {"status", "worker_seen"}


def test_the_monitor_is_not_counted_as_a_visitor():
    from app.traffic import DECLARED_BOT
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check", os.path.join(os.path.dirname(__file__), "..", "infra",
                              "monitor", "check.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    assert DECLARED_BOT.search(check.USER_AGENT)
