-- SQLite cache + sidecar schema.
--
-- Two kinds of table live here and they are NOT the same philosophically:
--   * CACHE tables (collections, sync_state, items, categories, items_fts) are a
--     derived projection of what is on the wire. Delete them, full-resync, and
--     you get byte-identical application state back (invariant #1).
--   * SIDECAR tables (sidecar, list_settings, completions, attachments,
--     day_plan, day_plan_opened, day_ritual, habits, focus_session,
--     notification_deliveries)
--     hold app-only state that
--     exists NOWHERE on the wire (kanban column, manual sort, pins, per-list
--     settings, the day's plan, which days were opened at all, what the owner
--     SAID about each day — its capacity, its stamps and the line they wrote
--     about how it went — and the habits that put entries on it). This list is
--     the same one docs/DEPLOY.md's backup section names, and the two have to
--     stay in step: a table missing from either is a table nobody backs up.
--     These are the one thing in this file
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
    -- VEVENT TRANSP: 'OPAQUE' (blocks time) or 'TRANSPARENT' (does not) — what
    -- Apple Calendar calls Busy/Free. NULL is the property being ABSENT, which
    -- RFC 5545 defines as OPAQUE; every reader goes through `read.blocks_time`
    -- rather than testing this column, so the default is stated once.
    transp           TEXT,
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
    -- "Notify me this many minutes before." Set per ITEM, on a task's due
    -- instant or an event's start, and NULL on almost everything — which is what
    -- "I did not ask to be told about this one" means.
    --
    -- Here rather than as a VALARM on the wire, and that is a decision rather
    -- than a shortcut. A VALARM is the interoperable answer and would be the
    -- right one if Smylte were the only client — but it is not: Tasks.org,
    -- Thunderbird and Apple Calendar share these collections and would each
    -- fire their own alarm off the same property, so writing one would buy
    -- interop by notifying the owner three times. `ical/read.py` also skips
    -- subcomponents whole, so honouring VALARM properly is a read/write change
    -- against the fidelity invariants rather than a column.
    --
    -- Sidecar-class for the ordinary reason too: it survives the
    -- delete-and-recreate a foreign client's edit can look like, so a reminder
    -- the owner set does not evaporate because their phone rewrote the resource.
    notify_minutes_before  INTEGER,
    -- When the owner PARKED this task, or NULL for the overwhelming majority,
    -- which is what "still live" means. A parked task is set aside rather than
    -- finished or abandoned: it leaves the default views, the day's derivation
    -- and the open counts, and it comes back the moment it is un-parked.
    --
    -- Here rather than as a STATUS on the wire, and that is forced rather than
    -- chosen. RFC 5545 gives VTODO four values and none of them is neutral —
    -- CANCELLED is the only exit the spec offers and it reads as a verdict, so
    -- it never gets used and nothing ever leaves the list, which is the whole
    -- reason this column exists. An invented STATUS or an X- property would be
    -- written verbatim onto collections Tasks.org, jtx Board and Thunderbird
    -- share (see app.py's `_TASK_STATUS`, which rejects exactly that at the
    -- edge), and they would each render it as unknown or ignore it — so parked
    -- work would still look open over there while looking gone over here.
    --
    -- Sidecar-class is also the honest classification of what this IS. Parking
    -- is a statement about which of the OWNER'S views a task appears in, not a
    -- fact about the task, and `notify_minutes_before` above made the same call
    -- for the same reason. The cost is stated rather than hidden: a task parked
    -- in Smylte still sits in the other clients' lists.
    --
    -- A TIMESTAMP rather than a flag, matching `orphaned_at` here and
    -- `done_at` / `dropped_at` / `rolled_to` on day_plan: WHEN something was set
    -- aside is the question a parking file eventually gets asked, and a boolean
    -- cannot answer it later. Nothing clears it automatically — see
    -- service.park_task.
    parked_at              TEXT,
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
    -- Seconds actually WORKED on this row by focus intervals, credited by the
    -- server from a session's phase anchors as it moves — never from a
    -- client's own count. NULL is "never worked in a session", which is a
    -- different fact from 0 and is kept: a look-back that showed "0m worked"
    -- on a row nobody ever started would be inventing a measurement. Seconds
    -- rather than minutes because a capped row advances at exactly its
    -- estimate, and a minute-rounded figure would fire up to thirty seconds
    -- early or late. A column added by store.init_db on existing DBs.
    worked_seconds  INTEGER,
    -- Whether a focus session stops crediting this row at its estimate (1),
    -- keeps it until it is ticked (0), or follows the account's default (NULL,
    -- "not said" — the same tri-state `day_ritual.capacity_minutes` keeps). On
    -- the ENTRY because it is a statement about how this row will be worked on
    -- this day. A column added by store.init_db on existing DBs.
    capped          INTEGER,
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
    -- How far OVER the stated capacity the plan ran at the moment it was
    -- committed, in minutes, or NULL — which covers three different days and
    -- means the same thing on all of them: never committed, committed with no
    -- capacity stated, or committed inside it. In every one of those there is
    -- no over-commitment to record.
    --
    -- Recorded because the app's position is that the plan NEVER BLOCKS: it
    -- records a decision rather than enforcing one. That sentence is only true
    -- if the decision is actually recorded somewhere. The tab names the act at
    -- the moment it is taken — an overfull day commits under a button that says
    -- "Commit anyway" rather than "Start" — and this is the other half, the
    -- record that outlives the press.
    --
    -- Computed SERVER-SIDE from the entries it already holds rather than sent
    -- by the client, so it cannot be a number the client made up, and by the
    -- same sum the tab shows (`TodayView`'s `planned`, which counts done rows)
    -- so it is the figure the owner was actually looking at. That differs from
    -- `notify/rules.py::_eval_capacity_overcommitted`, which excludes done rows
    -- — a legitimate difference, since one asks "how full is the day" and the
    -- other "how much is still ahead of you".
    --
    -- Nothing scores anything with it. The look-back states it once, in words,
    -- with no colour and no comparison to another day.
    committed_over_minutes INTEGER,
    shutdown_at      TEXT,               -- the shutdown ritual was finished
    reflection       TEXT,               -- a sentence or two on how it went
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- A focus session: the day being worked against a clock, one row per day.
--
-- ANCHORS, NOT COUNTERS. The server never ticks. What it keeps is when the
-- current run of the phase started and how much of the phase had already been
-- settled before that run, and every transition settles first — credits the
-- clamped time since the anchor, then does whatever it was asked. That is the
-- whole reason a clock in two windows agrees to the second, and the reason a
-- laptop closed overnight cannot record eight hours on one row: a phase can
-- credit at most its own length, however long nobody was there.
--
-- Sidecar-class like day_plan and for the same reason — the wire has no
-- vocabulary for "I am twelve minutes into the memo" — and listed in the file
-- header and in docs/DEPLOY.md's backup section. Losing it loses a running
-- clock, never the time already credited, which lives on day_plan.
CREATE TABLE IF NOT EXISTS focus_session (
    day              TEXT PRIMARY KEY,   -- YYYY-MM-DD, the day being worked
    phase            TEXT NOT NULL,      -- focus | break | long_break
    phase_length_s   INTEGER NOT NULL,   -- frozen at phase start from settings
    phase_elapsed_s  INTEGER NOT NULL DEFAULT 0,  -- settled seconds in this phase
    running_since    TEXT,               -- the anchor; NULL = paused, halted or ended
    intervals_done   INTEGER NOT NULL DEFAULT 0,  -- completed focus phases (long-break cadence)
    entry_id         TEXT,               -- the day_plan row being credited; NULL = queue empty
    passed           TEXT NOT NULL DEFAULT '[]',  -- JSON list of entry_ids set aside this session
    started_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ended_at         TEXT,               -- stamped by End; the row stays
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

-- ── notifications (SIDECAR: what has already been said out loud) ─────────────
--
-- One row per notification that has been SENT, keyed by what it was about. The
-- table exists for one reason: a notification must never arrive twice. The
-- scheduler wakes on a timer and re-evaluates the same window repeatedly — the
-- 09:00 sweep on a day the process restarted at 09:02 sees exactly what the
-- 09:00 sweep saw — so "have I already said this?" cannot be answered from the
-- data that triggered it. It is answered here.
--
-- `dedupe_key` is the identity of the OCCASION, not of the message: the task
-- uid plus the day, the event uid plus its start instant, the day key for a
-- once-a-day digest. Two different wordings of the same occasion share a key
-- and the second one is not sent.
--
-- A row is written BEFORE the send (see store.claim_notification), not after.
-- Writing it after leaves a window in which a crash between the API call and
-- the INSERT re-arms a message that already reached the phone, and a duplicate
-- 3am alert costs more trust than a missed one. The outcome is stamped back
-- onto the claimed row afterwards, so a failed send is recorded rather than
-- retried: the transport has already retried it (notify/telegram.py), and a
-- "starting in 10 minutes" redelivered half an hour later is worse than
-- silence.
--
-- Sidecar-class, and listed as such above and in docs/DEPLOY.md: nothing here
-- is on the wire and no resync rebuilds it. Losing it is not corruption, but a
-- restored machine will re-send whatever still falls inside the scheduler's
-- catch-up window — which is the one visible cost, and the reason it is in the
-- backup list rather than treated as scratch.
--
-- Deliberately NO foreign key to `items`, for the same reason `day_plan` has
-- none: `mark_collection_deleted` hard-deletes an entire collection's rows and
-- a completed task leaves the wire routinely. A cascade here would silently
-- re-arm a notification that has already been delivered.
CREATE TABLE IF NOT EXISTS notification_deliveries (
    trigger     TEXT NOT NULL,            -- which rule fired, e.g. 'event_starting'
    dedupe_key  TEXT NOT NULL,            -- the occasion it fired about
    channel     TEXT NOT NULL DEFAULT 'telegram',
    -- When the row was CLAIMED. The send happens after, outside the service
    -- lock, so this is within a few seconds of delivery and never after it.
    claimed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- NULL until the transport has answered: a row in that state is a send that
    -- was claimed and never resolved, which is what a crash mid-send looks like.
    settled_at  TEXT,
    ok          INTEGER NOT NULL DEFAULT 0,
    silent      INTEGER NOT NULL DEFAULT 0,   -- sent with disable_notification
    -- The transport's error, ALREADY REDACTED (notify/telegram.py::_redact).
    -- The bot token travels in the request path, so an unredacted httpx error
    -- string here would be a plaintext credential in every backup of this file.
    error       TEXT,
    -- Which DELIVERY carried this occasion: Telegram's message_id, NULL for a
    -- row that never settled as sent or whose transport returned none. One
    -- batched message settles one row per occasion, and the daily loud ceiling
    -- counts BUZZES, not rows — so the ceiling counts distinct values here
    -- (scheduler.loud_deliveries_since), and a row without one counts alone.
    message_id  INTEGER,
    PRIMARY KEY (trigger, dedupe_key, channel)
);
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_claimed
    ON notification_deliveries(claimed_at);

-- ── displays (SIDECAR: the passive screens on the wall) ─────────────────────
--
-- One row per DEVICE, not one row of settings. A display is a screen in a
-- place — the calendar in the hallway, the habit list in the kitchen — and the
-- two want different modes, different palettes and different geometry. Shaped
-- after `booking_links` deliberately: both are a token in a URL that reaches
-- data without a session, both are revoked by deleting the row, and one shape
-- for both means one thing to reason about when either is audited.
--
-- The token is the ONLY credential. It is `secrets.token_urlsafe(32)` rather
-- than the booking link's 16, because the two are not exposed to the same
-- degree of risk: a booking link is meant to be published and shows a redacted
-- busy grid to a stranger, while this one shows the owner's actual events and
-- actual habits in full. It is a bearer credential for private data sitting in
-- a Raspberry Pi's autostart file, and the mitigations are that it grants
-- READ of one frame and nothing else, that it can be rotated without deleting
-- the display, and that `last_seen_at` makes an unused one visible.
--
-- Sidecar-class, like every table below `items`: nothing here is on the wire
-- and no resync rebuilds it. Losing it does not lose data — it un-pairs every
-- panel, which is recoverable by pairing them again — so it belongs in
-- docs/DEPLOY.md's backup list beside the day plan and the habits.
CREATE TABLE IF NOT EXISTS displays (
    token       TEXT PRIMARY KEY,          -- secrets.token_urlsafe(32); the URL key
    name        TEXT NOT NULL,             -- "Hallway", "Kitchen" — for the owner only
    -- calendar | habits | now. What the screen is FOR, and the only three the
    -- app claims to draw well. A TEXT rather than an INTEGER enum so the DB
    -- reads like the API; unknown values are refused at the service, never
    -- here — which is also why adding `now` needed no migration, and why a row
    -- holding a mode this build does not know falls through to the default it
    -- is already declared with.
    mode        TEXT NOT NULL DEFAULT 'calendar',
    -- color | eink. NOT a theme: it decides whether the frame may use colour at
    -- all, and an eink frame is authored in pure black and white with no alpha,
    -- because every intermediate value on a 1-bit panel becomes a dither
    -- pattern that shimmers between refreshes. See display/frame.py.
    palette     TEXT NOT NULL DEFAULT 'color',
    -- JSON arrays of collection SLUGS. Empty is "everything", the same denylist
    -- default `hidden_calendars` takes, because a display added before a
    -- calendar exists should still show that calendar's events.
    calendars   TEXT NOT NULL DEFAULT '[]',
    lists       TEXT NOT NULL DEFAULT '[]',
    -- Whether a ticked habit leaves the screen. DEFAULT ON, which is the
    -- feature as asked for: a wall habit tracker earns its place by getting
    -- shorter as the day goes, and a list that only ever grows is a list of
    -- reproaches. Off keeps the occurrence visible with its tick, for someone
    -- who wants the day's whole shape.
    hide_done_habits INTEGER NOT NULL DEFAULT 1,
    hide_done_tasks  INTEGER NOT NULL DEFAULT 1,
    -- How often the panel is told to come back, in seconds. Advisory: it is
    -- reported in the frame and honoured by the browser page, and a firmware
    -- polling on its own schedule is neither helped nor hindered by it. Floored
    -- at 60 by the service — an eink panel that repaints faster than that is
    -- wearing itself out for a screen nobody is looking at that closely.
    refresh_seconds  INTEGER NOT NULL DEFAULT 300,
    -- The panel's pixels, for the server-rendered image. NULL means the request
    -- has to say (`?w=&h=`), which is what a browser page never needs. Rotation
    -- is degrees clockwise applied AFTER layout, so a portrait panel is laid
    -- out portrait rather than being drawn landscape and turned.
    panel_width  INTEGER,
    panel_height INTEGER,
    rotation     INTEGER NOT NULL DEFAULT 0,   -- 0 | 90 | 180 | 270
    enabled     INTEGER NOT NULL DEFAULT 1,
    -- Stamped on every fetch that answered with a frame. The ONLY thing
    -- recorded about the device: no address, no user agent, no request log.
    -- It exists to answer one question the owner cannot otherwise answer —
    -- "is that screen still talking to me, or has it been dark for a week" —
    -- and anything more would be a surveillance log of a household kept in a
    -- file that gets backed up.
    last_seen_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
