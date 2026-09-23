"""A demo arrives packed, and there is more than one way it can be packed.

FACEIT serves .dem.gz. Every demo this system has ingested so far was a
local .dem, so the compressed branch had only ever met zstd, and a gzip
file answered False to is_zstd(), fell through to "must be raw", and went
to the parser as gzip bytes.

That path is about to matter: the emails sent on 2026-09-23 tell a coach to
download their demo and upload it, and what FACEIT hands them is gzip.
"""
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


def test_a_raw_demo_is_not_packed(raw):
    assert ingest.packing_of(raw) == ""
    assert ingest.is_gzip(raw) is False
    assert ingest.is_zstd(raw) is False


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
