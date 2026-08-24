-- SQLite cache + sidecar schema.
--
-- Two kinds of table live here and they are NOT the same philosophically:
--   * CACHE tables (collections, sync_state, items, categories, items_fts) are a
--     derived projection of what is on the wire. Delete them, full-resync, and
--     you get byte-identical application state back (invariant #1).
--   * SIDECAR tables (sidecar, list_settings, completions, attachments,
--     day_plan, habits) hold app-only state that exists NOWHERE on the wire
--     (kanban column, manual sort, pins, per-list settings, the day's plan, and
--     the habits that put entries on it). These are the one thing in this file
--     that a resync cannot rebuild — so they are decoupled from the cache (no
--     FK to items) and survive an item briefly disappearing
--     (delete-and-recreate).
--
-- journal_mode=WAL and foreign_keys=ON are set per-connection in store.connect().

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ── cache ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS collections (
    href        TEXT PRIMARY KEY,          -- server-absolute path /user/<id>/
    displayname TEXT NOT NULL,
    components  TEXT NOT NULL DEFAULT 'VTODO',
    color       TEXT,                       -- wire calendar-color, if advertised
    ord         INTEGER,                    -- wire calendar-order (manual sort)
    deleted     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    collection_href     TEXT PRIMARY KEY REFERENCES collections(href) ON DELETE CASCADE,
    sync_token          TEXT,               -- last good RFC 6578 token
    last_sync_at        TEXT,
    last_full_resync_at TEXT,
    last_error          TEXT
);

CREATE TABLE IF NOT EXISTS items (
    collection_href  TEXT NOT NULL REFERENCES collections(href) ON DELETE CASCADE,
    uid              TEXT NOT NULL,          -- the join key (invariant #4)
    href             TEXT NOT NULL,          -- resource href; clients may rewrite it
    etag             TEXT NOT NULL,
    raw_ics          BLOB NOT NULL,          -- full-fidelity source for edits (invariant #2)
    component        TEXT NOT NULL DEFAULT 'VTODO',  -- VTODO (task) | VEVENT (calendar event)
    summary          TEXT,
    description      TEXT,
    status           TEXT,                   -- task: NEEDS-ACTION/…; event: CONFIRMED/TENTATIVE/CANCELLED
    priority         INTEGER,
    percent_complete INTEGER,
    completed        TEXT,
    due              TEXT,                    -- VTODO
    due_is_date      INTEGER NOT NULL DEFAULT 0,
    dtstart          TEXT,                    -- both
    dtstart_is_date  INTEGER NOT NULL DEFAULT 0,
    dtend            TEXT,                    -- VEVENT
    dtend_is_date    INTEGER NOT NULL DEFAULT 0,
    duration         TEXT,                    -- VEVENT (exclusive with dtend)
    related_parent   TEXT,                   -- parent UID (subtasks/checklist)
    sequence         INTEGER,
    has_rrule        INTEGER NOT NULL DEFAULT 0,
    -- The earliest instant this RESOURCE can produce (read._min_instant): the
    -- master DTSTART, or earlier if an RDATE or a RECURRENCE-ID override starts
    -- before it. `dtstart` is the master's alone, and gating a window on it drops
    -- an occurrence dragged earlier than its own series start; gating on nothing
    -- makes every recurring row a candidate for every window, which is a cost an
    -- anonymous booking-page request can choose. NULL on rows written before this
    -- column, which the query treats as "unknown, admit it".
    min_instant      TEXT,
    location         TEXT,
    created          TEXT,
    last_modified    TEXT,
    synced_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- The rowid of this item's row in items_fts. fts5 declares uid and
    -- collection_href UNINDEXED and builds no index over them, so deleting an
    -- entry by those columns is a full SCAN of the whole FTS table (every
    -- collection) — once per upsert, which makes a full resync O(n^2) under the
    -- single global service lock. Deleting by rowid is O(1).
    fts_rowid        INTEGER,
    PRIMARY KEY (collection_href, uid)       -- keyed on UID, never href
);
CREATE INDEX IF NOT EXISTS idx_items_href   ON items(collection_href, href);
CREATE INDEX IF NOT EXISTS idx_items_uid    ON items(uid);
CREATE INDEX IF NOT EXISTS idx_items_due    ON items(due);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_parent ON items(collection_href, related_parent);
CREATE INDEX IF NOT EXISTS idx_items_comp   ON items(collection_href, component);
CREATE INDEX IF NOT EXISTS idx_items_range  ON items(collection_href, component, dtstart);

CREATE TABLE IF NOT EXISTS categories (
    collection_href TEXT NOT NULL,
    uid             TEXT NOT NULL,
    category        TEXT NOT NULL,
    PRIMARY KEY (collection_href, uid, category),
    FOREIGN KEY (collection_href, uid)
        REFERENCES items(collection_href, uid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_categories_cat ON categories(category);

-- Full-text search. Contentless-style: maintained explicitly by store.upsert_item.
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    uid UNINDEXED,
    collection_href UNINDEXED,
    summary,
    description,
    categories,
    tokenize = 'unicode61'
);

-- ── sidecar (app-only; NOT derivable from the wire) ──────────────────────────

CREATE TABLE IF NOT EXISTS sidecar (
    collection_href        TEXT NOT NULL,
    uid                    TEXT NOT NULL,    -- keyed on UID (invariant #4)
    kanban_column          TEXT,
    sort_order             REAL,             -- fractional index for manual ordering
    pinned                 INTEGER NOT NULL DEFAULT 0,
    estimated_minutes      INTEGER,          -- DURATION is exclusive with DUE; keep it here
    repeat_from_completion INTEGER NOT NULL DEFAULT 0,
    orphaned_at            TEXT,             -- set when UID leaves the wire; GC after 7 days
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (collection_href, uid)
    -- deliberately NO foreign key to items: sidecar must outlive a
    -- delete-and-recreate so a returning UID rejoins its kanban/sort state.
);
CREATE INDEX IF NOT EXISTS idx_sidecar_orphan ON sidecar(orphaned_at);

CREATE TABLE IF NOT EXISTS list_settings (
    collection_href TEXT PRIMARY KEY,
    folder          TEXT,                    -- grouping (Radicale collections are flat)
    color           TEXT,                    -- app override color
    sort_mode       TEXT,                    -- manual|due|priority|alpha
    pinned          INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Recurrence completions ledger (spec §6 — GATED; table exists, unused until
-- the recurrence design is approved).
CREATE TABLE IF NOT EXISTS completions (
    collection_href TEXT NOT NULL,
    uid             TEXT NOT NULL,
    completed_at    TEXT NOT NULL,
    occurrence      TEXT,                    -- RECURRENCE-ID / occurrence anchor
    PRIMARY KEY (collection_href, uid, completed_at)
);

-- ── scheduling (SIDECAR: app-only booking links + booking ledger) ────────────
--
-- Booking links exist nowhere on the wire; the events they create do (they are
-- ordinary VEVENTs on the target calendar). The bookings table is a ledger of
-- who booked what — it survives link deletion (no FK) so history is kept.

CREATE TABLE IF NOT EXISTS booking_links (
    token            TEXT PRIMARY KEY,           -- secrets.token_urlsafe(16); the public URL key
    title            TEXT NOT NULL,
    description      TEXT,
    calendar_href    TEXT NOT NULL,              -- target VEVENT collection for bookings
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    timezone         TEXT NOT NULL,              -- IANA name; slot math happens in this zone
    availability     TEXT NOT NULL DEFAULT '{}', -- JSON {"0":["09:00-12:00","13:00-17:00"],...}, keys "0"(Mon).."6"(Sun)
    show_busy        INTEGER NOT NULL DEFAULT 0, -- public page shows redacted busy blocks
    buffer_minutes   INTEGER NOT NULL DEFAULT 0, -- padding around busy events
    min_notice_hours INTEGER NOT NULL DEFAULT 24,
    horizon_days     INTEGER NOT NULL DEFAULT 30,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id            TEXT PRIMARY KEY,              -- uuid4 hex
    link_token    TEXT NOT NULL,                 -- no FK: ledger survives link deletion
    calendar_href TEXT NOT NULL,
    event_uid     TEXT NOT NULL,                 -- the VEVENT this booking created
    client_name   TEXT NOT NULL,
    client_email  TEXT NOT NULL,
    notes         TEXT,
    start_at      TEXT NOT NULL,                 -- ISO datetime WITH offset (link tz)
    end_at        TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_bookings_link ON bookings(link_token, start_at);

-- Local blob store index (Phase 5). ATTACH on the wire is a URI, never base64.
CREATE TABLE IF NOT EXISTS attachments (
    id              TEXT PRIMARY KEY,
    collection_href TEXT NOT NULL,
    uid             TEXT NOT NULL,
    filename        TEXT NOT NULL,
    content_type    TEXT,
    size            INTEGER,
    local_path      TEXT NOT NULL,
    url             TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Sessions withdrawn by an explicit logout. A JWT is self-contained and cannot be
-- recalled, so the only way to make "log out" mean something is to remember the
-- token id until its own exp passes — after that the token is refused on its own
-- merits and the row is swept. Persisted rather than held in memory: a restart
-- would otherwise resurrect every logged-out session.
CREATE TABLE IF NOT EXISTS revoked_sessions (
    jti        TEXT PRIMARY KEY,
    expires_at REAL NOT NULL           -- the token's own exp, as a UNIX timestamp
);
CREATE INDEX IF NOT EXISTS idx_revoked_sessions_exp ON revoked_sessions(expires_at);

-- ── OAuth 2.1 authorization server (remote MCP; sidecar-class) ───────────────
-- State for the connector flow. Sidecar-class: none of it exists on the wire
-- and a resync cannot rebuild it — dropping these tables signs every connected
-- client out, which is the correct failure mode, not a lost cache.
--
-- Secrets are stored as SHA-256 hex, never in the clear. A read of this file
-- (backup, disk image, a stray SELECT) must not yield a working credential; the
-- app only ever needs to *recognise* a presented secret, never to reproduce it.
-- Booking-link tokens are the deliberate exception — they are capability URLs
-- the owner must be able to re-read and re-share.

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id            TEXT PRIMARY KEY,       -- secrets.token_urlsafe(24)
    client_secret_hash   TEXT,                   -- NULL for a public client (Claude registers as one)
    client_name          TEXT,
    redirect_uris        TEXT NOT NULL,          -- JSON array; matched exactly (loopback: port ignored)
    scope                TEXT,                   -- space-delimited, what this client may ask for
    created_at           REAL NOT NULL,
    -- Registration is open (the MCP spec wants DCR so a client can connect with
    -- no setup), so rows are swept: one never used to complete a flow is junk,
    -- and without this an unauthenticated caller could grow the table forever.
    last_used_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_clients_used ON oauth_clients(last_used_at);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash            TEXT PRIMARY KEY,
    client_id            TEXT NOT NULL,
    redirect_uri         TEXT NOT NULL,          -- pinned: the exchange must present the same one
    scope                TEXT NOT NULL,
    resource             TEXT NOT NULL,          -- RFC 8707 audience this code may mint a token for
    code_challenge       TEXT NOT NULL,          -- PKCE S256 challenge; no plain, no omission
    expires_at           REAL NOT NULL,          -- seconds, not minutes: a code is used immediately
    created_at           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_exp ON oauth_codes(expires_at);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash           TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL,          -- 'access' | 'refresh'
    client_id            TEXT NOT NULL,
    scope                TEXT NOT NULL,
    resource             TEXT NOT NULL,          -- validated against the endpoint the token is used at
    -- Rotation chain. A refresh token is single-use: redeeming it issues a
    -- successor and marks this row used. A *second* redemption of an already-used
    -- token is the signature of a stolen copy, so it kills the whole family
    -- rather than just failing — OAuth 2.1 §4.3.1 for public clients.
    family_id            TEXT NOT NULL,
    used_at              REAL,
    expires_at           REAL NOT NULL,
    created_at           REAL NOT NULL,
    -- Which credentials this grant was minted under (Authenticator.
    -- credential_version). Checked on every bearer AND before a refresh is
    -- consumed, so rotating the password -- or TASKS_SESSION_SECRET -- ends the
    -- MCP grants the same way it ends the browser sessions. Without it,
    -- docs/DEPLOY.md's "sign out everywhere" left a 30-day backdoor.
    cv                   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_exp ON oauth_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_family ON oauth_tokens(family_id);

-- ── day plan (SIDECAR: what the owner decided to do on a given day) ──────────
--
-- A day plan is a DECISION, and the wire has no vocabulary for one. CalDAV can
-- say a task is due Tuesday and that it is done; it cannot say "on Tuesday I
-- chose to pick this up, put it third, and dropped that other one unfinished".
-- So these two tables are sidecar-class in the strongest sense: not a slow
-- projection of the wire but the only copy that exists. A resync rebuilds
-- nothing here. Dropping them loses every past day permanently — the order the
-- owner arranged, the notes they wrote (which live nowhere else at all), the
-- carried-over history, and the record of what was dropped rather than
-- finished. Today's plan would rebuild itself on the next open, but only as the
-- automatic snapshot: due-today plus overdue, in due order, with every hand
-- edit gone. That is the cost, and it is why docs/DEPLOY.md's backup section
-- enumerates the sidecar-class tables by name: these two belong in that list,
-- and nothing about a resync makes up for their absence.
--
-- Deliberately NO foreign key to items, exactly like `sidecar` and for a
-- stronger reason: the day's log must stay true even after the task it names is
-- completed-and-deleted, moved between lists by another client, or
-- delete-and-recreated by a sync. An entry whose task has left the wire is not
-- corruption — it is the honest record that the work was planned that day.
CREATE TABLE IF NOT EXISTS day_plan (
    day             TEXT NOT NULL,           -- YYYY-MM-DD, the local calendar day
    entry_id        TEXT NOT NULL,           -- client-generated; unique within the day
    kind            TEXT NOT NULL,           -- task | note | habit
    collection_href TEXT,                    -- task entries: which list the uid is in
    uid             TEXT,                    -- task entries: the VTODO UID (invariant #4)
    title           TEXT,                    -- note + habit entries: the text itself
    source          TEXT NOT NULL,           -- auto (snapshot) | carried (yesterday) | user | habit
    -- habit entries: which rule minted this occurrence. No foreign key to
    -- `habits`, for the same reason day_plan has none to `items`: deleting a
    -- habit removes the RULE, and the days it already ran on keep saying so.
    -- The occurrence carries its own copy of the title (above), so a dangling
    -- habit_id costs the row nothing — it still reads exactly as it did on the
    -- day it was planned. A column added by store.init_db on existing DBs;
    -- see the ALTER there for why it must not be split from the DTO that reads it.
    habit_id        TEXT,
    position        REAL,                    -- manual order within the day
    -- What this entry is expected to take, in minutes, ON THIS DAY. NULL is
    -- "not estimated", which is a real and common answer: the day's total is
    -- over the rows that have one, and a half-estimated plan is still a plan.
    --
    -- On the ENTRY rather than on the task, because a note and a habit
    -- occurrence exist nowhere but here and would otherwise carry none at all.
    -- A task additionally REMEMBERS its last estimate in `sidecar`, which
    -- pre-fills this at entry-creation time — copied, never joined, so
    -- re-estimating a task in March cannot rewrite what January's plan said it
    -- would take. A column added by store.init_db on existing DBs; see the
    -- ALTER there for why it must not be split from the DTO that reads it.
    estimate_minutes INTEGER,
    done_at         TEXT,
    dropped_at      TEXT,                    -- stamped, never DELETEd: the day keeps its record
    -- The day key this row was deliberately MOVED to, or NULL. Set by the
    -- shutdown ritual, and distinct from `dropped_at` on purpose: "I decided
    -- against this" and "I am doing this on Thursday" are different things for a
    -- day to remember, and a look-back that told them apart is worth more than
    -- one that files both under abandoned.
    --
    -- The row stays HERE. Rolling forward creates a new entry on the target day
    -- and stamps this one; it never moves or deletes anything, because the day
    -- that planned the work is still the day that planned it.
    --
    -- `_carry_into` skips a stamped row, and that is load-bearing rather than
    -- tidy: without it a row rolled to Thursday would ALSO be carried into
    -- tomorrow by the automatic rule, and the owner would find two of it.
    -- A column added by store.init_db on existing DBs.
    rolled_to       TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (day, entry_id)
);
CREATE INDEX IF NOT EXISTS idx_day_plan_day ON day_plan(day);

-- "Opened but empty" and "never opened" are different days, and only this table
-- can tell them apart: day_plan alone answers both with zero rows. The
-- difference is load-bearing, because opening a day with create=true BUILDS the
-- snapshot — so a day the owner deliberately emptied would be re-snapshotted on
-- the next visit, resurrecting the very entries they dropped. The marker is
-- what makes the snapshot happen exactly once per day.
CREATE TABLE IF NOT EXISTS day_plan_opened (
    day        TEXT PRIMARY KEY,
    opened_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- What the owner SAID about a day, as opposed to what is on it.
--
-- Sidecar-class in the same strong sense as day_plan: the wire has no vocabulary
-- for "I am stopping at six", and no resync rebuilds any of this. It belongs in
-- docs/DEPLOY.md's backup list beside the two tables above.
--
-- Deliberately NOT columns on day_plan_opened. That table has exactly one job —
-- telling "opened but emptied" from "never opened", which is what makes the
-- snapshot happen once — and its name is that job. A day can also be PLANNED
-- without being OPENED, because a hand-add leaves the marker alone on purpose,
-- so a capacity hung there would have nowhere to live on such a day.
--
-- Every column is nullable and every one means something by being null:
-- no capacity stated, the day not begun, the day not closed, nothing written
-- down. In particular a NULL capacity is not zero — it is "never said", and the
-- difference decides whether the tab is entitled to tell anyone they have
-- overcommitted. See service.effective_capacity.
CREATE TABLE IF NOT EXISTS day_ritual (
    day              TEXT PRIMARY KEY,   -- YYYY-MM-DD, the local calendar day
    capacity_minutes INTEGER,            -- what the owner said they would work
    committed_at     TEXT,               -- the planning ritual was finished
    shutdown_at      TEXT,               -- the shutdown ritual was finished
    reflection       TEXT,               -- a sentence or two on how it went
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- A habit is a RULE THAT INSERTS ENTRIES, not a second ledger of its own. Its
-- occurrences are ordinary `day_plan` rows with kind='habit' and source='habit',
-- carrying a COPY of the title and the id of the rule that minted them — so
-- every question about a past day is still answered by day_plan alone, and
-- deleting the rule cannot rewrite what a day says. (The `completions` table
-- above is NOT this: it is gated groundwork for VTODO recurrence — see
-- docs/recurrence-findings.md — and habits never touch it.)
--
-- App-only in the strongest sense: nothing here is ever PUT to Radicale and no
-- RRULE is written for it, so a resync rebuilds none of it. Sidecar-class, and
-- listed as such in the file header and in docs/DEPLOY.md's backup section.
CREATE TABLE IF NOT EXISTS habits (
    id         TEXT PRIMARY KEY,          -- uuid4 hex
    title      TEXT NOT NULL,
    -- '' = every day, else a comma list from mon,tue,wed,thu,fri,sat,sun in
    -- that order. Deliberately NOT an RRULE and deliberately not a bitmask: the
    -- names are what the API takes and what a human reading the DB sees, and
    -- service._WEEKDAYS is the one place they are mapped to Python's weekday()
    -- numbering (0=Monday).
    days       TEXT NOT NULL DEFAULT '',
    -- Set to hide the habit from FUTURE snapshots. Past occurrences are rows in
    -- day_plan and are untouched by it: pausing means "stop scheduling this",
    -- never "pretend the last three weeks did not happen".
    paused_at  TEXT,
    position   REAL,                      -- manual order in the habits list
    -- How long an occurrence of this habit is expected to take. The RULE
    -- remembers it and every occurrence is minted with a COPY, exactly as the
    -- title is — so a habit is estimated once rather than every morning, and
    -- changing the rule leaves past days saying what they said. A task
    -- remembers its estimate in `sidecar` and a note is remembered by the
    -- carry; this is the third of those three, and habits need their own
    -- because an occurrence has no wire object and never carries.
    -- A column added by store.init_db on existing DBs.
    estimate_minutes INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
