"""A demo arrives packed, and there is more than one way it can be packed.

FACEIT serves .dem.gz. Every demo this system has ingested so far was a
local .dem, so the compressed branch had only ever met zstd, and a gzip
file answered False to is_zstd(), fell through to "must be raw", and went
to the parser as gzip bytes.

That path is about to matter: the emails sent on 2026-09-23 tell a coach to
download their demo and upload it, and what FACEIT hands them is gzip.
"""
import bz2
import gzip
import shutil

import pytest

from app import ingest

DEMO_BYTES = b"PBDEMS2\x00" + b"fake demo payload " * 500


@pytest.fixture
def raw(tmp_path):
    p = tmp_path / "match.dem"
    p.write_bytes(DEMO_BYTES)
    return p


def test_gzip_is_detected(tmp_path, raw):
    packed = tmp_path / "match.dem.gz"
    with raw.open("rb") as fin, gzip.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    assert ingest.is_gzip(packed) is True
    assert ingest.is_zstd(packed) is False
    assert ingest.packing_of(packed) == "gzip"


def test_zstd_still_detected(tmp_path, raw):
    zstandard = pytest.importorskip("zstandard")
    packed = tmp_path / "match.dem.zst"
    with raw.open("rb") as fin, packed.open("wb") as fout:
        zstandard.ZstdCompressor().copy_stream(fin, fout)

    assert ingest.is_zstd(packed) is True
    assert ingest.is_gzip(packed) is False
    assert ingest.packing_of(packed) == "zstd"


def test_bzip2_is_detected(tmp_path, raw):
    """Valve matchmaking demos. What a team's own scrims arrive as."""
    packed = tmp_path / "match.dem.bz2"
    with raw.open("rb") as fin, bz2.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    assert ingest.is_bzip2(packed) is True
    assert ingest.is_zstd(packed) is False
    assert ingest.is_gzip(packed) is False
    assert ingest.packing_of(packed) == "bzip2"


def test_bzip2_round_trips_through_decompress(tmp_path, raw):
    packed = tmp_path / "match.dem.bz2"
    with raw.open("rb") as fin, bz2.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    out = tmp_path / "expanded.dem"
    assert ingest.decompress(packed, out) == len(DEMO_BYTES)
    assert out.read_bytes() == DEMO_BYTES


def test_a_raw_demo_is_not_packed(raw):
    assert ingest.packing_of(raw) == ""
    assert ingest.is_gzip(raw) is False
    assert ingest.is_zstd(raw) is False
    assert ingest.is_bzip2(raw) is False


def test_gzip_round_trips_through_decompress(tmp_path, raw):
    """The whole point: the parser must receive the real demo bytes."""
    packed = tmp_path / "match.dem.gz"
    with raw.open("rb") as fin, gzip.open(packed, "wb") as fout:
        shutil.copyfileobj(fin, fout)

    out = tmp_path / "expanded.dem"
    written = ingest.decompress(packed, out)

    assert out.read_bytes() == DEMO_BYTES
    assert written == len(DEMO_BYTES)


def test_zstd_round_trips_through_decompress(tmp_path, raw):
    pytest.importorskip("zstandard")
    packed = tmp_path / "match.dem.zst"
    ingest.compress(raw, packed)

    out = tmp_path / "expanded.dem"
    ingest.decompress(packed, out)
    assert out.read_bytes() == DEMO_BYTES


def test_something_that_is_neither_says_so(tmp_path, raw):
    """A clear error beats handing junk to the parser."""
    out = tmp_path / "expanded.dem"
    with pytest.raises(ingest.IngestError) as e:
        ingest.decompress(raw, out)
    assert "magic number" in str(e.value)


def test_stored_path_finds_a_gz_archive(tmp_path, monkeypatch):
    """An archived .dem.gz has to be findable, or a re-parse re-downloads."""
    monkeypatch.setattr(ingest.db, "DEMO_DIR", tmp_path)
    sha = "a" * 64
    (tmp_path / f"{sha}.dem.gz").write_bytes(b"\x1f\x8b\x08\x00")
    assert ingest.stored_path(sha) == tmp_path / f"{sha}.dem.gz"


# ---------------------------------------------------------------- duplicates
#
# The same match arrives by several routes: a coach uploads it, pull.py
# queues it off a FACEIT url, and the corpus tool points at a folder it was
# copied into. from_directory() dedupes on source_url, which is the path,
# so all three look different and the demo gets parsed once per route.
#
# That is not clutter. match_key is derived per demo row, so the same match
# lands under two keys, and README is explicit that splits are by match
# "because rows within a round are correlated and a random split leaks". A
# match in the corpus twice can sit in train and in test at once.

def test_the_guard_keys_on_content_not_on_path(tmp_path, monkeypatch):
    """Two rows, same bytes, different source_url: the second must not parse."""
    import importlib
    import os
    was = os.environ.get("COUNTERPLAY_DB")
    os.environ["COUNTERPLAY_DB"] = str(tmp_path / "d.db")
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init()
    try:
        sha = "f" * 64
        first = db_mod.execute(
            """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes,
                                  sha256, tier, status, created_at, source,
                                  source_url)
               VALUES (NULL,NULL,?,?,?,?,'parsed',?, 'upload', ?)""",
            "a.dem", 10, sha, "league", db_mod.utcnow(), "file:///a.dem")
        second = db_mod.execute(
            """INSERT INTO demos (team_id, uploaded_by, filename, size_bytes,
                                  sha256, tier, status, created_at, source,
                                  source_url)
               VALUES (NULL,NULL,?,?,?,?,'pending',?, 'local', ?)""",
            "b.dem", 10, sha, "league", db_mod.utcnow(), "file:///elsewhere/b.dem")

        # The query ingest.process runs once it knows the real hash.
        twin = db_mod.one("""SELECT id FROM demos
                              WHERE sha256 = ? AND id != ? AND status = 'parsed'
                              LIMIT 1""", sha, second)
        assert twin is not None and twin["id"] == first

        # And the first row does not find itself.
        alone = db_mod.one("""SELECT id FROM demos
                               WHERE sha256 = ? AND id != ? AND status = 'parsed'
                               LIMIT 1""", sha, first)
        assert alone is None
    finally:
        if was is None:
            os.environ.pop("COUNTERPLAY_DB", None)
        else:
            os.environ["COUNTERPLAY_DB"] = was
        importlib.reload(db_mod)
