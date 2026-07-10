-- SQLite cache + sidecar schema.
--
-- Two kinds of table live here and they are NOT the same philosophically:
--   * CACHE tables (collections, sync_state, items, categories, items_fts) are a
--     derived projection of what is on the wire. Delete them, full-resync, and
--     you get byte-identical application state back (invariant #1).
--   * SIDECAR tables (sidecar, list_settings, completions, attachments) hold
--     app-only state that exists NOWHERE on the wire (kanban column, manual sort,
--     pins, per-list settings). These are the one thing in this file that a
--     resync cannot rebuild — so they are decoupled from the cache (no FK to
--     items) and survive an item briefly disappearing (delete-and-recreate).
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
    location         TEXT,
    created          TEXT,
    last_modified    TEXT,
    synced_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
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
