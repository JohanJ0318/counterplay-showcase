"""Demo → parsed rounds in the database.

The one path everything downstream depends on. A demo arrives either because a
coach uploaded it or because the league pull found it, and this module takes it
from bytes to rows:

    download (if remote) → decompress → parse → validate → store

**Demos are kept, compressed, by default.** An earlier version of this deleted
the file after parsing to save disk. That was the wrong trade, for three
reasons, and the default is now RETAIN_ALL:

  * FACEIT deletes match demos after a few weeks. A demo dropped here is gone
    for good — you cannot re-download it.
  * `schema.py` defines ten features today. Adding an eleventh — utility usage,
    weapon class, positions at freeze-end — means re-parsing the whole corpus.
    Without the files, every future feature is limited to matches played after
    somebody thought of it.
  * A 2D replayer needs positional data this pipeline does not extract yet.
    Keeping the demos keeps that option open without having to guess now what
    to pull out of them.

Storage is the cheapest thing in this system: the whole NECC corpus is around
100-140GB compressed, a few euro a month. Parse time and RAM are the real costs,
and keeping the file does not affect either.

What is NOT kept is the decompressed `.dem`. FACEIT serves zstd, the expanded
file is 3-4x larger, and it is only needed for the seconds the parser is
reading it.

Validation is not optional. `validate.py` exists because parsing fails silently
far more often than it raises, and a demo that parses into nonsense would be
indistinguishable from one that worked — right up until the model trains on it.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import tempfile
import urllib.parse as _urlparse
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import db, faceit

# A demo that fails this many times is left alone. Almost always a genuinely
# broken file or an unsupported demo version, and retrying forever turns one
# bad file into a permanently busy worker. The FILE is still kept — a failed
# parse is exactly the demo you need when you fix parse.py.
MAX_ATTEMPTS = 3

DOWNLOAD_CHUNK = 1 << 20
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024

# Retention. "all" keeps every demo, "owned" keeps only demos belonging to a
# team that signed up (league-pull files are dropped after parsing), "none"
# keeps nothing. Default is all, because the files cannot be re-acquired and
# storage is the cheapest constraint here.
RETENTION = os.environ.get("COUNTERPLAY_RETAIN", "all").lower()
ZSTD_LEVEL = 10          # roughly 1.5x on demo data; they are already dense

# Copy demos that already live in a folder on this machine into the store?
# Off by default — see should_keep().
ARCHIVE_LOCAL = os.environ.get("COUNTERPLAY_ARCHIVE_LOCAL") == "1"


def path2url(path: Path) -> str:
    """An absolute local path as a file:// URL, Windows drive letters included."""
    return "file:///" + str(Path(path).resolve()).replace("\\", "/").lstrip("/")


def url2path(url: str) -> str:
    """The inverse. Handles the %20 that any path with a space arrives carrying."""
    return _urlparse.unquote(url[len("file:///"):])


class IngestError(Exception):
    """The demo itself is bad. Mark it failed and move on."""


class TransientError(IngestError):
    """The demo might be fine; we could not reach it.

    DNS failures, timeouts, 5xx. These must NOT mark a demo failed or burn an
    attempt: nothing was learned about the file, and treating "the network was
    down" the same as "this demo is corrupt" quietly writes off a whole queue
    over a bad afternoon. The row goes back to pending with the reason noted.
    """


# ---------------------------------------------------------------- paths

def stored_path(sha: str) -> Path | None:
    """Where this demo lives on disk, compressed or not, or None."""
    for name in (f"{sha}.dem.zst", f"{sha}.dem"):
        p = db.DEMO_DIR / name
        if p.exists():
            return p
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(DOWNLOAD_CHUNK):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- fetching

def download(url: str, dest: Path) -> int:
    """Stream a demo to disk. Returns bytes written.

    Raises TransientError for anything that says nothing about the file: the
    name did not resolve, the host timed out, the server had a bad minute.
    Raises IngestError only when the server actually told us the demo is not
    there (404/410).
    """
    req = urllib.request.Request(url, headers=faceit.UA)
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as out:
            while chunk := r.read(DOWNLOAD_CHUNK):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise IngestError("demo exceeds 600MB")
                out.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise IngestError(f"demo gone from the host (HTTP {e.code})") from e
        raise TransientError(f"HTTP {e.code} fetching demo") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if "getaddrinfo" in str(reason) or isinstance(reason, socket.gaierror):
            raise TransientError(
                f"cannot resolve {urllib.parse.urlparse(url).hostname} — DNS, "
                f"not expiry. The host name did not resolve at all, which is a "
                f"different problem from the demo being deleted.") from e
        raise TransientError(f"network error: {reason}") from e
    except (socket.timeout, TimeoutError) as e:
        raise TransientError("timed out fetching demo") from e
    if total == 0:
        raise TransientError("empty download")
    return total


def is_zstd(path: Path) -> bool:
    """Magic number check, rather than trusting the file extension."""
    with path.open("rb") as f:
        return f.read(4) == b"\x28\xb5\x2f\xfd"


def decompress(src: Path, dest: Path) -> int:
    """Expand a .dem.zst. Returns bytes written.

    Streaming, not in memory: a 70MB .zst expands to ~300MB.
    """
    import zstandard
    with src.open("rb") as fin, dest.open("wb") as fout:
        zstandard.ZstdDecompressor().copy_stream(
            fin, fout, write_size=DOWNLOAD_CHUNK)
    size = dest.stat().st_size
    if size == 0:
        raise IngestError("decompressed to nothing")
    return size


def compress(src: Path, dest: Path) -> int:
    """Shrink a raw .dem for long-term storage. Returns bytes written."""
    import zstandard
    cctx = zstandard.ZstdCompressor(level=ZSTD_LEVEL)
    with src.open("rb") as fin, dest.open("wb") as fout:
        cctx.copy_stream(fin, fout, write_size=DOWNLOAD_CHUNK)
    return dest.stat().st_size


# ---------------------------------------------------------------- parsing

def parse_to_frames(dem_path: Path, tier: str = "league"):
    """Run the parser. Returns (rounds, events, players, positions, utility, map)."""
    from counterplay.parse import parse_demo
    try:
        (rounds, events, players, position_blobs,
         util) = parse_demo(str(dem_path), tier=tier)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        # BaseException, not Exception, and this is not defensive padding.
        # demoparser2 is a Rust extension: a malformed demo makes it PANIC, and
        # pyo3 surfaces that as PanicException, which inherits from
        # BaseException. `except Exception` does not catch it, so one truncated
        # file takes the whole worker down mid-corpus.
        raise IngestError(f"parse failed: {type(e).__name__}: {e}") from e
    if rounds is None or len(rounds) == 0:
        raise IngestError("parsed zero rounds")
    return (rounds, events, players, position_blobs, util,
            str(rounds["map_name"].iloc[0]))


def check(rounds, events) -> tuple[bool, str]:
    """Run validate.py. Returns (ok, one-line summary of what failed)."""
    from counterplay.validate import validate
    checks = validate(rounds, events)
    failed = [c for c in checks if not c.ok]
    if not failed:
        return True, f"{len(checks)}/{len(checks)} checks passed"
    names = "; ".join(c.name for c in failed[:3])
    more = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
    return False, f"{len(failed)}/{len(checks)} checks failed: {names}{more}"


# ---------------------------------------------------------------- storing

def store(demo_id: int, match_key: str, rounds, events, players=None,
          position_blobs=None, utility=None, *,
          faceit_match_id: str | None, competition: str, tier: str,
          played_at: str | None) -> int:
    """Write parsed frames. Replaces any previous parse of the same match_key."""
    map_name = str(rounds["map_name"].iloc[0])
    ct_wins = int(rounds["ct_won"].sum())
    n_rounds = int(len(rounds))
    # The demo's own scoreboard, carried on the frame by parse_demo. A demo
    # parsed before this existed has no attrs and stores NULL rather than a
    # guess.
    attrs = getattr(rounds, "attrs", {}) or {}

    with db.connect() as conn:
        # Re-parsing a match replaces it rather than appending. Without this a
        # retry doubles every round and the model trains on each of them twice.
        #
        # Cleared by DEMO as well as by key, so a demo parsed under an older
        # key scheme does not leave orphaned rounds behind when it is parsed
        # again. Clearing by key alone was what made the collision above
        # destructive.
        stale = [r["match_key"] for r in conn.execute(
            "SELECT match_key FROM matches WHERE demo_id = ?", (demo_id,))]
        for key in set(stale + [match_key]):
            for table in ("rounds", "events", "player_rounds", "round_positions",
                          "grenades", "blinds", "matches"):
                conn.execute(f"DELETE FROM {table} WHERE match_key = ?", (key,))

        conn.execute(
            """INSERT INTO matches (demo_id, match_key, faceit_match_id, map_name,
                                    tier, competition, played_at, rounds,
                                    score_ct, score_t, final_ct, final_t,
                                    finished, end_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (demo_id, match_key, faceit_match_id, map_name, tier, competition,
             played_at, n_rounds, ct_wins, n_rounds - ct_wins,
             attrs.get("final_ct"), attrs.get("final_t"),
             None if attrs.get("finished") is None else int(attrs["finished"]),
             attrs.get("end_reason"), db.utcnow()))

        conn.executemany(
            """INSERT INTO rounds (match_key, round_num, map_name, tier,
                                   equip_ct, equip_t, ct_won)
               VALUES (?,?,?,?,?,?,?)""",
            [(match_key, int(r.round_num), str(r.map_name), tier,
              float(r.equip_ct), float(r.equip_t), int(bool(r.ct_won)))
             for r in rounds.itertuples(index=False)])

        if events is not None and len(events):
            def txt(v):
                return None if v is None or v != v else str(v)
            conn.executemany(
                """INSERT INTO events (match_key, round_num, seconds, type,
                                       victim_side, victim_steamid, victim_name,
                                       attacker_steamid, attacker_name,
                                       headshot, weapon)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [(match_key, int(e.round_num), float(e.seconds), str(e.type),
                  txt(e.victim_side),
                  txt(getattr(e, "victim_steamid", None)),
                  txt(getattr(e, "victim_name", None)),
                  txt(getattr(e, "attacker_steamid", None)),
                  txt(getattr(e, "attacker_name", None)),
                  int(getattr(e, "headshot", 0) or 0),
                  txt(getattr(e, "weapon", None)))
                 for e in events.itertuples(index=False)])

        if players is not None and len(players):
            def col(r, name, cast=int, default=0):
                """A field a demo parsed before this column existed reads 0."""
                v = getattr(r, name, default)
                try:
                    return cast(v)
                except (TypeError, ValueError):
                    return cast(default)

            conn.executemany(
                """INSERT INTO player_rounds (match_key, round_num, steamid, name,
                       tier, side, kills, deaths, assists, headshots, damage,
                       opening_kill, opening_death, awp_kills,
                       util_damage, flashes_thrown, enemies_flashed,
                       trade_kills, traded_deaths,
                       clutch_tried, clutch_won, clutch_vs, multi_kills,
                       teammates_flashed, blind_enemy_secs, blind_team_secs,
                       flash_assists, flash_kills,
                       nades_thrown, nades_start, nades_unused,
                       nades_value, nades_wasted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                           ?,?,?,?,?,?,?,?,?,?)""",
                [(match_key, int(r.round_num), str(r.steamid), str(r.name),
                  tier, str(r.side), int(r.kills), int(r.deaths), int(r.assists),
                  int(r.headshots), float(r.damage), int(r.opening_kill),
                  int(r.opening_death), int(r.awp_kills),
                  col(r, "util_damage", float, 0.0), col(r, "flashes_thrown"),
                  col(r, "enemies_flashed"), col(r, "trade_kills"),
                  col(r, "traded_deaths"), col(r, "clutch_tried"),
                  col(r, "clutch_won"), col(r, "clutch_vs"), col(r, "multi_kills"),
                  col(r, "teammates_flashed"),
                  col(r, "blind_enemy_secs", float, 0.0),
                  col(r, "blind_team_secs", float, 0.0),
                  col(r, "flash_assists"), col(r, "flash_kills"),
                  col(r, "nades_thrown"), col(r, "nades_start"),
                  col(r, "nades_unused"), col(r, "nades_value"),
                  col(r, "nades_wasted"))
                 for r in players.itertuples(index=False)])

        # Utility rows. Written before positions only because they are cheap;
        # both are enrichments, and a match with neither is still a match.
        util = utility or {}
        if util.get("grenades"):
            conn.executemany(
                """INSERT INTO grenades (match_key, round_num, seconds, kind,
                       steamid, side, x, y, z, life,
                       hit_enemy, hit_own, damage, kills)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(match_key, int(g["round_num"]), float(g["seconds"]),
                  str(g["kind"]), g["steamid"], g["side"],
                  float(g["x"]), float(g["y"]), float(g["z"]),
                  None if g["life"] is None else float(g["life"]),
                  int(g.get("hit_enemy", 0)), int(g.get("hit_own", 0)),
                  float(g.get("damage", 0.0)), int(g.get("kills", 0)))
                 for g in util["grenades"]])
        if util.get("blinds"):
            conn.executemany(
                """INSERT INTO blinds (match_key, round_num, seconds,
                       victim_steamid, victim_side, thrower_steamid,
                       thrower_side, duration, own_side, died_blind)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(match_key, int(b["round_num"]), float(b["seconds"]),
                  b["victim_steamid"], b["victim_side"],
                  b["thrower_steamid"], b["thrower_side"],
                  float(b["duration"]), int(b["own_side"]), int(b["died_blind"]))
                 for b in util["blinds"]])

        if position_blobs:
            from counterplay.positions import HEADER
            rows = []
            for rn, blob in position_blobs.items():
                _v, tick_start, tick_step, n_s, n_p = HEADER.unpack_from(blob, 0)
                rows.append((match_key, int(rn), tick_start, tick_step,
                             n_s, n_p, blob))
            conn.executemany(
                """INSERT INTO round_positions (match_key, round_num, tick_start,
                       tick_step, n_samples, n_players, data)
                   VALUES (?,?,?,?,?,?,?)""", rows)
        conn.commit()
    return n_rounds


def should_keep(demo_row) -> bool:
    """Whether to hold a copy of this demo in the store after parsing.

    A demo already sitting in a folder on this machine is NOT copied by
    default. It is already kept — by you, where you put it — and duplicating
    36GB of your own matches onto a disk with 32GB free is not a trade worth
    making. The queue row points at the original, so `reparse_all` still
    replays it as long as the folder stays put.

    Set COUNTERPLAY_ARCHIVE_LOCAL=1 to archive those too, once there is room.
    """
    if RETENTION == "none":
        return False
    if demo_row["source"] == "local" and not ARCHIVE_LOCAL:
        return False
    if RETENTION == "owned":
        return demo_row["team_id"] is not None
    return True


# ---------------------------------------------------------------- the pipeline

def process(demo_row) -> tuple[bool, str]:
    """Take one demo row from pending to parsed or failed.

    Returns (ok, note). Never raises for an expected failure — a bad demo is a
    normal event and must not stop the worker.
    """
    demo_id = demo_row["id"]
    source_url = demo_row["source_url"]
    sha = demo_row["sha256"]
    tier = demo_row["tier"] or "league"

    db.execute("""UPDATE demos SET status='parsing', attempts = attempts + 1
                   WHERE id = ?""", demo_id)

    work = Path(tempfile.mkdtemp(prefix="cp-ingest-"))
    external: Path | None = None
    try:
        archive = stored_path(sha)

        # A demo already on this machine — a folder of your own matches — is read
        # WHERE IT SITS rather than copied in first. 36GB of demos does not fit
        # twice on a disk with 32GB free, and the compressed archive written
        # after a successful parse is a third of the size anyway.
        if archive is None and source_url.startswith("file://"):
            external = Path(url2path(source_url))
            if not external.exists():
                raise IngestError(f"file is gone: {external}")

        if archive is None and external is None:
            if not source_url:
                raise IngestError("no local file and no source url")
            tmp = work / "download.bin"
            size = download(source_url, tmp)

            # The queue row carried a placeholder sha derived from the URL,
            # because the real one is not knowable until the bytes arrive.
            # Replace it now so an upload of the same match is recognized as a
            # duplicate rather than parsed twice.
            real = sha256_of(tmp)
            suffix = ".dem.zst" if is_zstd(tmp) else ".dem"
            archive = db.DEMO_DIR / f"{real}{suffix}"
            if archive.exists():
                tmp.unlink(missing_ok=True)
            else:
                shutil.move(str(tmp), str(archive))
            db.execute("UPDATE demos SET sha256=?, size_bytes=? WHERE id=?",
                       real, size, demo_id)
            sha = real

        if external is not None:
            # The queue row carried a placeholder hash derived from the path,
            # because the real one is not knowable until the bytes are read.
            # Resolve it NOW, before match_key is derived from it: doing it
            # afterwards meant a re-parse computed a different key and inserted
            # a second match row instead of replacing the first.
            real = sha256_of(external)
            if real != sha:
                db.execute("UPDATE demos SET sha256=? WHERE id=?", real, demo_id)
                sha = real

        source_file = archive if external is None else external
        if is_zstd(source_file):
            playable = work / "demo.dem"
            decompress(source_file, playable)
        else:
            playable = source_file

        (rounds, events, players, position_blobs,
         util, map_name) = parse_to_frames(playable, tier=tier)
        ok, summary = check(rounds, events)
        if not ok:
            # Marked failed with the reason, and the FILE IS KEPT. A bad parse
            # in the corpus is worse than a missing one — the model trains on it
            # happily and comes out confidently wrong. But this is precisely the
            # demo you need when you fix the parser, so it does not get deleted.
            raise IngestError(summary)

        # The demo id is part of the key, not just the file hash.
        #
        # A key derived from content alone means two teams who played each
        # other and both upload the demo share one row — and `store()` clears
        # by match_key before writing, so re-parsing one team's copy deletes
        # the other team's match. That is not theoretical: it happened twice
        # during deployment and took out a real 5-1 both times.
        #
        # Content still leads the key, so the same match is recognisable
        # across teams by its prefix, but each team's parse owns its own rows.
        match_key = f"cp_{sha[:16]}_{demo_id}"
        n = store(demo_id, match_key, rounds, events, players, position_blobs,
                  util,
                  faceit_match_id=demo_row["faceit_match_id"],
                  competition=demo_row["competition"] or "",
                  tier=tier, played_at=demo_row["created_at"])

        note = summary
        if position_blobs:
            kb = sum(len(b) for b in position_blobs.values()) / 1024
            note += f"; positions {len(position_blobs)} rounds, {kb:.0f} KB"
        if util.get("grenades") or util.get("blinds"):
            note += (f"; utility {len(util.get('grenades', []))} nades, "
                     f"{len(util.get('blinds', []))} blinds")
        if external is not None:
            # Archive a compressed copy so `reparse_all` still works after the
            # original folder is cleared out. Off by default — see should_keep().
            packed = db.DEMO_DIR / f"{sha}.dem.zst"
            if should_keep(demo_row) and not packed.exists():
                after = compress(external, packed)
                note += f"; archived {external.stat().st_size/1e6:.0f}->{after/1e6:.0f} MB"
                db.execute("UPDATE demos SET size_bytes=? WHERE id=?", after, demo_id)
        elif should_keep(demo_row):
            # Keep it compressed. An uploaded raw .dem is 3-4x larger than the
            # zstd FACEIT would have given us, and nothing reads it directly.
            if archive.suffix == ".dem":
                packed = db.DEMO_DIR / f"{sha}.dem.zst"
                before = archive.stat().st_size
                after = compress(archive, packed)
                archive.unlink(missing_ok=True)
                db.execute("UPDATE demos SET size_bytes=? WHERE id=?", after, demo_id)
                note += f"; archived {before/1e6:.0f}->{after/1e6:.0f} MB"
        else:
            archive.unlink(missing_ok=True)
            db.execute("UPDATE demos SET size_bytes=0 WHERE id=?", demo_id)
            note += "; file dropped (retention)"

        db.execute("""UPDATE demos SET status='parsed', status_note=?, rounds=?,
                                       map_name=?, parsed_at=?
                       WHERE id = ?""",
                   note[:400], n, map_name, db.utcnow(), demo_id)
        return True, f"{n} rounds, {map_name}, {note}"

    except TransientError as e:
        # Back to the queue, and give the attempt back. Nothing was learned
        # about this demo, so it must not count against its retry budget.
        db.execute("""UPDATE demos SET status='pending', status_note=?,
                                       attempts = MAX(attempts - 1, 0)
                       WHERE id = ?""", str(e)[:400], demo_id)
        return False, f"[retryable] {e}"
    except IngestError as e:
        db.execute("UPDATE demos SET status='failed', status_note=? WHERE id=?",
                   str(e)[:400], demo_id)
        return False, str(e)
    except (KeyboardInterrupt, SystemExit):
        # Put the demo back so a ctrl-c does not consume an attempt.
        db.execute("UPDATE demos SET status='pending' WHERE id=?", demo_id)
        raise
    except BaseException as e:                # including Rust panics; see above
        db.execute("UPDATE demos SET status='failed', status_note=? WHERE id=?",
                   f"{type(e).__name__}: {e}"[:400], demo_id)
        return False, f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def next_pending(skip: set[int] | None = None):
    """The next demo to work on, oldest first, skipping ones that keep failing.

    `skip` holds demos already tried in this pass. A transient failure puts a
    row straight back to pending, so without it the worker picks the same
    unreachable demo forever and never reaches the ones it could have parsed.
    """
    if skip:
        marks = ",".join("?" * len(skip))
        return db.one(f"""SELECT * FROM demos
                           WHERE status = 'pending' AND attempts < ?
                             AND id NOT IN ({marks})
                        ORDER BY created_at LIMIT 1""", MAX_ATTEMPTS, *skip)
    return db.one("""SELECT * FROM demos
                      WHERE status = 'pending' AND attempts < ?
                   ORDER BY created_at LIMIT 1""", MAX_ATTEMPTS)


def requeue_stuck(minutes: int = 30) -> int:
    """Return demos abandoned mid-parse to the queue.

    A worker killed while parsing leaves a row in 'parsing' forever. Anything
    that has sat there beyond any plausible parse time gets another go, up to
    the attempt limit.
    """
    cutoff = db.minutes_ago(minutes)
    rows = db.query("""SELECT id FROM demos WHERE status='parsing'
                        AND created_at < ? AND attempts < ?""",
                    cutoff, MAX_ATTEMPTS)
    for r in rows:
        db.execute("UPDATE demos SET status='pending' WHERE id=?", r["id"])
    return len(rows)


def reparse_all(tier: str | None = None) -> int:
    """Queue every kept demo for parsing again.

    The reason the files are retained. When `schema.py` gains a feature or
    `parse.py` gains a fix, this replays the whole corpus through the new code.
    Returns how many were queued.
    """
    rows = db.query("SELECT id, sha256, source_url FROM demos" +
                    (" WHERE tier = ?" if tier else ""), *([tier] if tier else []))
    n = 0
    for r in rows:
        # Reachable means either an archived copy in the store OR a local file
        # still sitting where it was queued from. Checking only the store
        # silently skipped every demo read in place.
        reachable = stored_path(r["sha256"]) is not None
        if not reachable and str(r["source_url"]).startswith("file://"):
            reachable = Path(url2path(r["source_url"])).exists()
        if not reachable:
            continue
        db.execute("UPDATE demos SET status='pending', attempts=0 WHERE id=?",
                   r["id"])
        n += 1
    return n


def disk_usage() -> tuple[int, int]:
    """(file count, total bytes) held in the demo store."""
    files = list(db.DEMO_DIR.glob("*.dem*"))
    return len(files), sum(f.stat().st_size for f in files)


def forget_team(team_id: int, actor_id: int | None = None) -> dict:
    """Delete everything belonging to one team. Files included.

    The landing page says "ask us to delete your team's data and we delete it,
    no conversation required." This is that, and it has to remove the demo files
    as well as the rows or the promise is not kept.
    """
    demos = db.query("SELECT id, sha256 FROM demos WHERE team_id = ?", team_id)
    removed = 0
    for d in demos:
        p = stored_path(d["sha256"])
        if p is not None:
            p.unlink(missing_ok=True)
            removed += 1
        keys = db.query("SELECT match_key FROM matches WHERE demo_id = ?", d["id"])
        for k in keys:
            db.execute("DELETE FROM rounds WHERE match_key = ?", k["match_key"])
            db.execute("DELETE FROM events WHERE match_key = ?", k["match_key"])
        db.execute("DELETE FROM matches WHERE demo_id = ?", d["id"])
    db.execute("DELETE FROM demos WHERE team_id = ?", team_id)
    db.audit(actor_id, "forget_team", f"team={team_id} demos={len(demos)}")
    return {"demos": len(demos), "files_removed": removed}
