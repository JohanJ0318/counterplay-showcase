"""A coach's uploaded demo is always kept after it is parsed.

The file is what lets a match gain anything new. When migration 23 added
per-player money, only matches whose files still existed could be parsed
again; everything else stayed without it. A retention setting quietly
turned down would make the next such change reach nobody's past matches.
tools/pull-backup.ps1 copies the kept files to Johan's PC as well.
"""
import importlib
import os


def _ingest(monkeypatch, retain=None):
    if retain is None:
        monkeypatch.delenv("COUNTERPLAY_RETAIN", raising=False)
    else:
        monkeypatch.setenv("COUNTERPLAY_RETAIN", retain)
    from app import ingest
    return importlib.reload(ingest)


def test_the_default_keeps_everything(monkeypatch):
    ingest = _ingest(monkeypatch)
    assert ingest.RETENTION == "all"


def test_a_coach_upload_is_kept(monkeypatch):
    ingest = _ingest(monkeypatch)
    row = {"source": "upload", "team_id": 5}
    assert ingest.should_keep(row)


def test_owned_still_keeps_a_coach_upload(monkeypatch):
    ingest = _ingest(monkeypatch, "owned")
    assert ingest.should_keep({"source": "upload", "team_id": 5})
    _ingest(monkeypatch)            # leave the module as the other tests expect
