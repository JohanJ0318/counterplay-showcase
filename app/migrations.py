"""Schema migrations.

`schema.sql` is all IF NOT EXISTS, which creates a fresh database correctly but
does nothing to one that already exists. That was fine while nothing had been
deployed. It stops being fine the moment there is a row worth keeping, so
changes from here on go in the list below and run in order.

SQLite tracks the version in `PRAGMA user_version`, so this needs no table of
its own and cannot get out of step with the file it describes.

Rules for adding one:

  * Append only. Never edit a migration that has run somewhere.
  * ALTER TABLE ADD COLUMN is the only safe alteration SQLite does cheaply.
    Anything else means create-copy-drop-rename, which belongs in its own step.
  * A migration must be safe to run against a database that is already correct,
    because that is exactly what happens on the box you tested on.
"""
from __future__ import annotations

import sqlite3

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "parsed demo storage", """
        -- One row per map actually played. A best-of-three is three of these,
        -- all pointing at the same faceit_match_id.
        CREATE TABLE IF NOT EXISTS matches (
            id                INTEGER PRIMARY KEY,
            demo_id           INTEGER REFERENCES demos(id) ON DELETE CASCADE,
            -- The engine's match_id: stable, derived from the demo, and what
            -- rounds/events join on. Unique so re-parsing replaces rather than
            -- duplicates.
            match_key         TEXT    NOT NULL UNIQUE,
            faceit_match_id   TEXT,
            map_name          TEXT    NOT NULL DEFAULT 'unknown',
            tier              TEXT    NOT NULL DEFAULT 'league',
            competition       TEXT    NOT NULL DEFAULT '',
            played_at         TEXT,
            rounds            INTEGER NOT NULL DEFAULT 0,
            score_ct          INTEGER,
            score_t           INTEGER,
            created_at        TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_matches_faceit ON matches(faceit_match_id);

        -- One row per round. Mirrors the `rounds` frame parse.py returns.
        CREATE TABLE IF NOT EXISTS rounds (
            match_key   TEXT    NOT NULL,
            round_num   INTEGER NOT NULL,
            map_name    TEXT    NOT NULL,
            tier        TEXT    NOT NULL DEFAULT 'league',
            equip_ct    REAL    NOT NULL DEFAULT 0,
            equip_t     REAL    NOT NULL DEFAULT 0,
            ct_won      INTEGER NOT NULL,
            PRIMARY KEY (match_key, round_num)
        );

        -- One row per death or plant. Mirrors the `events` frame.
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY,
            match_key   TEXT    NOT NULL,
            round_num   INTEGER NOT NULL,
            seconds     REAL    NOT NULL,
            type        TEXT    NOT NULL,
            victim_side TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_round ON events(match_key, round_num);
    """),

    (2, "demo provenance", """
        -- Where a demo came from. 'upload' is a coach sending one in; 'league'
        -- is one this project pulled from the league's own match pages.
        ALTER TABLE demos ADD COLUMN source TEXT NOT NULL DEFAULT 'upload';
        ALTER TABLE demos ADD COLUMN faceit_match_id TEXT;
        ALTER TABLE demos ADD COLUMN source_url TEXT NOT NULL DEFAULT '';
        ALTER TABLE demos ADD COLUMN map_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE demos ADD COLUMN competition TEXT NOT NULL DEFAULT '';
        -- Attempt counter, so a demo that crashes the parser is retried a
        -- couple of times and then left alone rather than spinning forever.
        ALTER TABLE demos ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    """),

    (3, "league demos have no owning team", """
        -- demos.team_id was NOT NULL, which assumed every demo belongs to a
        -- team that signed up. League-pulled demos belong to nobody: they exist
        -- to build aggregate baselines, and a team that never signed up must
        -- never get a profile built from them. SQLite cannot drop NOT NULL in
        -- place, so this is the create-copy-drop-rename dance.
        CREATE TABLE demos_new (
            id           INTEGER PRIMARY KEY,
            team_id      INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            uploaded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
            filename     TEXT    NOT NULL,
            size_bytes   INTEGER NOT NULL DEFAULT 0,
            sha256       TEXT    NOT NULL,
            tier         TEXT    NOT NULL DEFAULT 'league',
            status       TEXT    NOT NULL DEFAULT 'pending',
            status_note  TEXT    NOT NULL DEFAULT '',
            rounds       INTEGER,
            created_at   TEXT    NOT NULL,
            parsed_at    TEXT,
            source       TEXT    NOT NULL DEFAULT 'upload',
            faceit_match_id TEXT,
            source_url   TEXT    NOT NULL DEFAULT '',
            map_name     TEXT    NOT NULL DEFAULT '',
            competition  TEXT    NOT NULL DEFAULT '',
            attempts     INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO demos_new
            SELECT id, team_id, uploaded_by, filename, size_bytes, sha256, tier,
                   status, status_note, rounds, created_at, parsed_at, source,
                   faceit_match_id, source_url, map_name, competition, attempts
              FROM demos;
        DROP TABLE demos;
        ALTER TABLE demos_new RENAME TO demos;

        -- A team may not upload the same match twice. League demos have a NULL
        -- team_id, and SQLite treats NULLs as distinct in a UNIQUE index, so
        -- this constraint does not apply to them — which is why the pull path
        -- checks faceit_match_id instead.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_demos_team_sha
            ON demos(team_id, sha256);
        CREATE INDEX IF NOT EXISTS idx_demos_team ON demos(team_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_demos_status ON demos(status, attempts);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_demos_source_url
            ON demos(source_url) WHERE source_url <> '';
    """),
    (4, "per-round player stats", """
        -- One row per player per round. Round-level rather than match-level
        -- because sides swap at half, so a match-level row cannot answer "how
        -- do they play as CT" -- which is most of what a coach wants.
        -- Everything else (a scoreboard, a leaderboard, role detection)
        -- aggregates up from this.
        CREATE TABLE IF NOT EXISTS player_rounds (
            match_key     TEXT    NOT NULL,
            round_num     INTEGER NOT NULL,
            steamid       TEXT    NOT NULL,
            name          TEXT    NOT NULL DEFAULT '',
            tier          TEXT    NOT NULL DEFAULT 'league',
            side          TEXT    NOT NULL,
            kills         INTEGER NOT NULL DEFAULT 0,
            deaths        INTEGER NOT NULL DEFAULT 0,
            assists       INTEGER NOT NULL DEFAULT 0,
            headshots     INTEGER NOT NULL DEFAULT 0,
            damage        REAL    NOT NULL DEFAULT 0,
            opening_kill  INTEGER NOT NULL DEFAULT 0,
            opening_death INTEGER NOT NULL DEFAULT 0,
            awp_kills     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (match_key, round_num, steamid)
        );
        CREATE INDEX IF NOT EXISTS idx_pr_player ON player_rounds(steamid);
        CREATE INDEX IF NOT EXISTS idx_pr_match ON player_rounds(match_key);
        CREATE INDEX IF NOT EXISTS idx_pr_tier ON player_rounds(tier);
    """),

    (5, "event identity", """
        -- Who died and who killed them. Without these the parse could never
        -- support player stats, role detection or leaderboards at all.
        ALTER TABLE events ADD COLUMN victim_steamid TEXT;
        ALTER TABLE events ADD COLUMN victim_name TEXT;
        ALTER TABLE events ADD COLUMN attacker_steamid TEXT;
        ALTER TABLE events ADD COLUMN attacker_name TEXT;
        ALTER TABLE events ADD COLUMN headshot INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE events ADD COLUMN weapon TEXT;
    """),
    (6, "positional data", """
        -- One packed blob per ROUND, not one row per player per tick. A round
        -- at 8 Hz is ~1,400 player-samples and a season is millions; those
        -- samples are only ever read a whole round at a time, so a blob is both
        -- the right shape and far smaller than the rows would be.
        -- The format is documented in counterplay/positions.py.
        CREATE TABLE IF NOT EXISTS round_positions (
            match_key  TEXT    NOT NULL,
            round_num  INTEGER NOT NULL,
            -- Denormalised out of the blob header so "how much do we have"
            -- can be answered without unpacking anything.
            tick_start INTEGER NOT NULL,
            tick_step  INTEGER NOT NULL,
            n_samples  INTEGER NOT NULL,
            n_players  INTEGER NOT NULL,
            data       BLOB    NOT NULL,
            PRIMARY KEY (match_key, round_num)
        );
    """),
    (7, "zone names", """
        -- What a human calls each clustered zone. Clustering finds the map's
        -- real geography; only a person knows that a place is called "banana".
        -- Keyed on (map, index) because the clustering is seeded and ordered by
        -- traffic, so zone 4 on Mirage is stable across regenerations.
        CREATE TABLE IF NOT EXISTS zone_names (
            map_name   TEXT    NOT NULL,
            zone_index INTEGER NOT NULL,
            name       TEXT    NOT NULL,
            updated_at TEXT    NOT NULL,
            PRIMARY KEY (map_name, zone_index)
        );
    """),
    (8, "stored zone model", """
        -- The clustered zones themselves, not just their names.
        --
        -- Zones were being recomputed from the corpus on every call. K-means is
        -- seeded so that is deterministic for a FIXED corpus, but the moment
        -- another demo is parsed the clusters move — and the names, which are
        -- keyed on zone index, would silently point somewhere else. Storing the
        -- model pins them: naming, patterns and pictures all read the same
        -- centres, and rebuilding is a deliberate act that warns about names.
        CREATE TABLE IF NOT EXISTS map_zones (
            map_name   TEXT    NOT NULL,
            zone_index INTEGER NOT NULL,
            cx         REAL    NOT NULL,
            cy         REAL    NOT NULL,
            cz         REAL    NOT NULL,
            share      REAL    NOT NULL DEFAULT 0,
            radius     REAL    NOT NULL DEFAULT 0,
            -- 'upper'/'lower' on maps split by floor, NULL elsewhere. Nuke's
            -- bombsites sit 369 units above each other, so one top-down model
            -- merges them.
            level      TEXT,
            built_at   TEXT    NOT NULL,
            PRIMARY KEY (map_name, zone_index)
        );
    """),
    (9, "utility, trades, clutches, multi-kills and the real match score", """
        -- What a coach asks about that a kill/death line cannot answer.
        --
        -- The league page already showed utility damage for strangers pulled
        -- from an API while a team's own uploaded demos showed none of it, so
        -- the product knew more about a player nobody here coaches than about
        -- the five in the room. These come off the same demo everything else
        -- does; they were simply never read.
        ALTER TABLE player_rounds ADD COLUMN util_damage    REAL    NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN flashes_thrown INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN enemies_flashed INTEGER NOT NULL DEFAULT 0;
        -- A trade is the difference between losing a player and losing a round.
        ALTER TABLE player_rounds ADD COLUMN trade_kills    INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN traded_deaths  INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN clutch_tried   INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN clutch_won     INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN clutch_vs      INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE player_rounds ADD COLUMN multi_kills    INTEGER NOT NULL DEFAULT 0;

        -- The demo's own scoreboard.
        --
        -- score_ct/score_t on matches are rounds won BY SIDE summed over the
        -- whole match, which is not a score: sides swap, so neither number
        -- belongs to a team. On a 28-round Inferno that read "16-12" while the
        -- demo's own team_rounds_total said 15-13. These two columns are what
        -- the scoreboard in the game actually read at the last round, taken
        -- from the demo rather than derived.
        ALTER TABLE matches ADD COLUMN final_ct INTEGER;
        ALTER TABLE matches ADD COLUMN final_t  INTEGER;
        -- Whether the recording covers a finished match. The Inferno demo above
        -- stops 3 OT rounds to 1, before anyone reached 16.
        ALTER TABLE matches ADD COLUMN finished INTEGER;
    """),
    (10, "why a match ended", """
        -- A match that stops before anyone reaches the win target has not
        -- necessarily been cut off: in Premier a losing team can vote to
        -- surrender, and the match really is over at 5-1.
        --
        -- The demo says which. `cs_win_panel_match` fires when the game shows
        -- its end-of-match panel, so a short match WITH that event ended on
        -- purpose and one without it is a truncated recording. Calling both
        -- "recording ends early" was wrong about the common case.
        ALTER TABLE matches ADD COLUMN end_reason TEXT;
    """),
    (11, "imported map geometry", """
        -- Where the map IS, as opposed to where players have stood.
        --
        -- Every drawing so far came from position samples, which finds the busy
        -- areas correctly and draws the map with holes in it: a corner nobody
        -- walked through is missing, and more matches never fully fix it
        -- because some corners are never contested. One walk-through demo per
        -- map settles it. See counterplay/mapwalk.py.
        CREATE TABLE IF NOT EXISTS map_geometry (
            map_name TEXT PRIMARY KEY,
            cells    BLOB    NOT NULL,
            n_cells  INTEGER NOT NULL,
            source   TEXT,
            built_at TEXT    NOT NULL
        );
    """),
    (12, "where to draw a zone's label", """
        -- A cluster centre is the AVERAGE of its members, and an average is not
        -- always a place. Where a zone wraps a corner or straddles a wall, the
        -- centroid lands inside the geometry: on Anubis one sat 123 units from
        -- anywhere a player has ever stood, in a part of the map nobody can
        -- enter, and on Cache one sat between two areas a wall keeps apart.
        --
        -- The centroid still does the assigning — moving it would repartition
        -- the map and silently re-point names that were written against the
        -- current partition. What moves is only where the LABEL is drawn: onto
        -- the busiest spot a player has actually occupied inside that zone.
        ALTER TABLE map_zones ADD COLUMN label_x REAL;
        ALTER TABLE map_zones ADD COLUMN label_y REAL;
        ALTER TABLE map_zones ADD COLUMN label_z REAL;
    """),
]


def run(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration newer than the file's version. Returns what ran."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied = []
    for version, name, sql in MIGRATIONS:
        if version <= current:
            continue
        # Foreign keys must be off for the create-copy-drop-rename in step 3;
        # with them on, DROP TABLE would cascade rows out of the children.
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            applied.append(f"{version}: {name}")
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
    return applied
