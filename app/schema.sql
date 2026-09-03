-- Counterplay application schema.
--
-- SQLite on purpose. The whole point of the event-based state reconstruction
-- upstream is that this runs on a $6 VPS, and a separate database server would
-- undo that for no benefit at the sizes involved: a league season is tens of
-- thousands of rows, not millions. Move to Postgres when concurrent writers
-- become the constraint, which is a good problem and not today's.
--
-- Every table here is written once and read often. Timestamps are stored as
-- ISO-8601 UTC strings so they sort correctly as text and stay readable in a
-- shell, which matters more than the bytes.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;


CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    email           TEXT    NOT NULL,
    -- Stored lowercase and compared through this column, so two people cannot
    -- register Coach@ and coach@ as different accounts.
    email_key       TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    name            TEXT    NOT NULL DEFAULT '',
    -- coach | igl | player | director | other. Free text from a fixed list;
    -- not a foreign key because the list is presentation, not structure.
    role            TEXT    NOT NULL DEFAULT 'other',
    plan            TEXT    NOT NULL DEFAULT 'free',
    email_verified  INTEGER NOT NULL DEFAULT 0,
    verify_token    TEXT,
    created_at      TEXT    NOT NULL,
    last_login_at   TEXT
);


CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    slug            TEXT    NOT NULL UNIQUE,
    league          TEXT    NOT NULL DEFAULT '',
    faceit_url      TEXT    NOT NULL DEFAULT '',
    plan            TEXT    NOT NULL DEFAULT 'team_t3',
    -- NULL means the plan has no end date set: a comped team, or a trial that
    -- nobody has put a date on yet. Read it as "do not expire", never as
    -- "expired", so a missing date can't silently switch a paying team off.
    plan_renews_at  TEXT,
    created_at      TEXT    NOT NULL,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL
);


CREATE TABLE IF NOT EXISTS team_members (
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- owner | coach | player. Owner is the only one that can change the plan
    -- or remove people; there is always exactly one, enforced in code.
    member_role TEXT    NOT NULL DEFAULT 'player',
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (team_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_members_user ON team_members(user_id);


-- Sessions store the SHA-256 of the cookie value, never the value itself. A
-- stolen database backup should not be a stolen set of live logins.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,
    user_agent  TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);


-- Failed logins, for rate limiting. Rows are pruned on read rather than by a
-- background job, because there is no background job on a box this size.
CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY,
    email_key   TEXT    NOT NULL,
    at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts ON login_attempts(email_key, at);


-- The landing-page form, for people who want to send demos before they want an
-- account. Kept separate from users so a lead is never half an account.
CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY,
    team        TEXT    NOT NULL DEFAULT '',
    league      TEXT    NOT NULL DEFAULT '',
    role        TEXT    NOT NULL DEFAULT '',
    name        TEXT    NOT NULL DEFAULT '',
    email       TEXT    NOT NULL DEFAULT '',
    faceit_url  TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    handled_at  TEXT
);


-- Uploaded demos. The file itself lives on disk under DEMO_DIR keyed by sha256;
-- this table is the index. sha256 is UNIQUE per team so re-uploading the same
-- match twice does not double-count a season.
CREATE TABLE IF NOT EXISTS demos (
    id           INTEGER PRIMARY KEY,
    team_id      INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    uploaded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    filename     TEXT    NOT NULL,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    sha256       TEXT    NOT NULL,
    tier         TEXT    NOT NULL DEFAULT 'league',
    -- pending | parsing | parsed | failed
    status       TEXT    NOT NULL DEFAULT 'pending',
    status_note  TEXT    NOT NULL DEFAULT '',
    rounds       INTEGER,
    created_at   TEXT    NOT NULL,
    parsed_at    TEXT,
    UNIQUE (team_id, sha256)
);

CREATE INDEX IF NOT EXISTS idx_demos_team ON demos(team_id, created_at);


-- Anything worth being able to answer "who did that, and when" about later.
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY,
    at       TEXT    NOT NULL,
    user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action   TEXT    NOT NULL,
    detail   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at);
