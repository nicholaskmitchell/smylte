"""SQLite access layer — raw sqlite3, no ORM (the schema is small; the queries
are the interesting part). All timestamps are ISO-8601 UTC strings.

The cache functions are written so that starting from an empty DB and replaying
a full resync reproduces identical rows (invariant #1). Sidecar functions treat
UID as the join key and never cascade-delete on item removal (invariant #4 + the
delete-and-recreate survival requirement).
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..dav.client import CollectionInfo, Item
from ..ical.read import TaskFields

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

# C0 control bytes, stripped from search terms (see `search`).
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


@contextmanager
def tx(conn: sqlite3.Connection):
    """An explicit all-or-nothing transaction.

    Needed because `connect` sets `isolation_level=None` (autocommit): sqlite3's
    own `with conn:` only manages a transaction it started ITSELF, so under
    autocommit it commits nothing and rolls back nothing. A write that looked
    atomic — and was documented as atomic — was in fact one commit per statement,
    leaving half a change behind when a later statement raised.

    Lives here rather than in the sync engine (where it started) because it is a
    database concern that every writer needs, not a sync one.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            # SQLite rolls back by itself for some error classes — SQLITE_FULL
            # and SQLITE_IOERR being the realistic ones on a box whose disk
            # fills up — so by the time this runs there is no transaction left
            # and the ROLLBACK itself raises "cannot rollback - no transaction
            # is active". Unguarded, THAT exception propagated in place of the
            # real one and the `raise` below never ran. The data was safe, but
            # the diagnosis was destroyed at the moment it was needed: sync_all
            # logs the escaping exception and persists it as
            # `sync_state.last_error`, so both the log and the operator-facing
            # error read "cannot rollback" when the condition was "database or
            # disk is full".
            pass
        raise
    else:
        conn.execute("COMMIT")


def connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: the service owns ONE connection and serializes all
    # access behind a lock, so it is safe to touch from FastAPI's threadpool.
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Migrations for DBs created before a column existed (executescript's
    # IF NOT EXISTS won't touch an existing table).
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(collections)")}
    if "ord" not in cols:
        conn.execute("ALTER TABLE collections ADD COLUMN ord INTEGER")
    tok_cols = {r["name"] for r in conn.execute("PRAGMA table_info(oauth_tokens)")}
    if "cv" not in tok_cols:
        # Grants issued before this column read '' and are refused on first use,
        # so an upgrade costs every MCP client one re-authorization. That is the
        # conservative direction and the same cost the session `cv` already
        # documents: a token whose provenance cannot be established is not one
        # to trust for the next 30 days.
        conn.execute("ALTER TABLE oauth_tokens ADD COLUMN cv TEXT NOT NULL DEFAULT ''")
    item_cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    if "min_instant" not in item_cols:
        # NULL until the row is next upserted, and the candidate query admits a
        # NULL rather than filtering on it — the conservative direction, since a
        # missing lower bound must not hide an occurrence. A resync fills it in.
        conn.execute("ALTER TABLE items ADD COLUMN min_instant TEXT")
    if "transp" not in item_cols:
        # NULL on every row written before this column, which reads as OPAQUE —
        # the RFC's own default for an absent property, and the same answer a
        # genuinely opaque event gives. So an un-resynced cache blocks booking
        # slots exactly as it did before, and the only rows it is wrong about
        # are ones the owner had marked FREE, which it reports as busy until
        # their next sync: over-blocking, never over-offering, which is the only
        # direction a public booking page may be wrong in.
        #
        # Same one-change rule as `habit_id` on `day_plan`: `service._event_dto`
        # reads `row["transp"]`, and sqlite3.Row answers IndexError for a column
        # the query did not return — outside the taxonomy app.py maps, so a 500
        # on every read of every event. The reverse order is inert.
        conn.execute("ALTER TABLE items ADD COLUMN transp TEXT")
    if "fts_rowid" not in item_cols:
        # Rows written before this column keep NULL and fall back to the old
        # scoped delete, so no rebuild is needed; they pick up a rowid the next
        # time they are upserted.
        conn.execute("ALTER TABLE items ADD COLUMN fts_rowid INTEGER")
    day_cols = {r["name"] for r in conn.execute("PRAGMA table_info(day_plan)")}
    if "habit_id" not in day_cols:
        # Every entry written before habits existed keeps NULL, which is exactly
        # what "no rule minted this" means — nothing to backfill.
        #
        # This ALTER and `service._day_entry_dto`'s `row["habit_id"]` are ONE
        # change and must ship together. sqlite3.Row raises IndexError for a
        # column the query did not return, and IndexError is outside the whole
        # error taxonomy app.py maps — so a build carrying the DTO line without
        # this block answers 500 to every read of every day, not just the days
        # holding a habit. Upgrading in the other order is merely inert.
        conn.execute("ALTER TABLE day_plan ADD COLUMN habit_id TEXT")
    if "estimate_minutes" not in day_cols:
        # Every entry written before estimates existed keeps NULL, which is
        # exactly what "nobody said how long this would take" means — and the
        # day's total is over the rows that HAVE one, so an un-upgraded plan
        # simply totals what it can rather than reading as a day of zero-length
        # work. Nothing to backfill, and no sensible value to backfill with.
        #
        # Same one-change rule as `habit_id` above, for the same mechanical
        # reason: `service._day_entry_dto` reads `row["estimate_minutes"]`, and
        # sqlite3.Row answers IndexError for a column the query did not return.
        # IndexError is outside the taxonomy app.py maps, so the DTO line
        # without this block is a 500 on every read of every day. The reverse
        # order is inert.
        conn.execute("ALTER TABLE day_plan ADD COLUMN estimate_minutes INTEGER")
    if "rolled_to" not in day_cols:
        # NULL on every entry written before the shutdown ritual, which is
        # exactly what "nobody moved this" means — nothing to backfill. Same
        # one-change rule as the two above: `_day_entry_dto` reads this key.
        conn.execute("ALTER TABLE day_plan ADD COLUMN rolled_to TEXT")
    habit_cols = {r["name"] for r in conn.execute("PRAGMA table_info(habits)")}
    if "estimate_minutes" not in habit_cols:
        # Habits written before estimates keep NULL, and their occurrences are
        # minted unestimated — which is what "nobody has said how long this
        # takes" means. One answer on the rule fixes every future day of it.
        conn.execute("ALTER TABLE habits ADD COLUMN estimate_minutes INTEGER")


# ── collections ──────────────────────────────────────────────────────────────

def upsert_collection(conn: sqlite3.Connection, ci: CollectionInfo) -> None:
    conn.execute(
        """INSERT INTO collections (href, displayname, components, color, ord, deleted, updated_at)
           VALUES (?, ?, ?, ?, ?, 0, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(href) DO UPDATE SET
             displayname=excluded.displayname,
             components=excluded.components,
             color=excluded.color,
             ord=excluded.ord,
             deleted=0,
             updated_at=excluded.updated_at""",
        (ci.href, ci.displayname, ",".join(sorted(ci.components)) or "VTODO",
         ci.color, ci.order),
    )
    conn.execute(
        "INSERT OR IGNORE INTO sync_state (collection_href) VALUES (?)", (ci.href,)
    )


def has_collection(conn: sqlite3.Connection, href: str) -> bool:
    """Is this collection present AND live? A deleted collection keeps its row
    (sync marks `deleted`, it is not dropped), so answering on existence alone
    let writes and booking links target a calendar that is gone from the server —
    every attempt failing at the DAV layer as an opaque 502."""
    return conn.execute(
        "SELECT 1 FROM collections WHERE href=? AND deleted=0", (href,)
    ).fetchone() is not None


def disable_links_for_collection(conn: sqlite3.Connection, href: str) -> int:
    """Disable every booking link aimed at a collection that has gone away.
    Disabled rather than deleted: the link keeps its history and settings so it
    can be pointed at another calendar."""
    cur = conn.execute(
        "UPDATE booking_links SET enabled=0 WHERE calendar_href=? AND enabled=1", (href,)
    )
    conn.commit()
    return cur.rowcount


def get_collections(conn: sqlite3.Connection, *, include_deleted: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM collections"
    if not include_deleted:
        q += " WHERE deleted=0"
    # Manual order (calendar-order) first; unordered collections trail, by name.
    return list(conn.execute(q + " ORDER BY ord IS NULL, ord, displayname"))


def mark_collection_deleted(conn: sqlite3.Connection, href: str) -> None:
    """The collection is gone from the server: soft-delete its row and purge the
    cache it projected.

    The collections row itself stays (the deleted flag is what stops it being
    listed or written to), which is exactly why the purge has to be explicit:
    `items.collection_href REFERENCES collections(href) ON DELETE CASCADE` only
    fires on a real DELETE, so a soft delete left every item, FTS row and
    category behind. `search` and `distinct_categories` do not filter on the
    collection, so a deleted list's tasks stayed queryable through /api/search
    and their tags kept showing in /api/tags — carrying a list id that no longer
    resolves — and their full raw_ics bodies stayed on disk for the life of the
    DB. Purging is the right answer rather than filtering: the cache is a
    disposable projection (invariant #1), and a resync rebuilds it if the
    collection ever comes back."""
    conn.execute("UPDATE collections SET deleted=1 WHERE href=?", (href,))
    # Sidecar first — it is app-only state no resync can rebuild, so it is
    # orphaned for the 7-day grace period rather than deleted, and it has no FK
    # to items (invariant #4) so nothing below would touch it anyway.
    conn.execute(
        "UPDATE sidecar SET orphaned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE collection_href=? AND orphaned_at IS NULL",
        (href,),
    )
    conn.execute("DELETE FROM items WHERE collection_href=?", (href,))   # cascades categories
    conn.execute("DELETE FROM items_fts WHERE collection_href=?", (href,))  # virtual: no FK
    # Forget the sync token. If the collection returns, `upsert_collection`
    # clears `deleted` but leaves sync_state alone, so the next sync would resume
    # *incrementally* from this token and never re-fetch the bodies just purged —
    # the collection would come back permanently empty. A null token forces the
    # full resync that rebuilds them.
    conn.execute(
        "UPDATE sync_state SET sync_token=NULL WHERE collection_href=?", (href,)
    )


# ── sync state ───────────────────────────────────────────────────────────────

def get_sync_token(conn: sqlite3.Connection, collection_href: str) -> str | None:
    row = conn.execute(
        "SELECT sync_token FROM sync_state WHERE collection_href=?", (collection_href,)
    ).fetchone()
    return row["sync_token"] if row else None


def set_sync_token(
    conn: sqlite3.Connection,
    collection_href: str,
    token: str,
    *,
    full: bool = False,
    error: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO sync_state (collection_href, sync_token, last_sync_at,
                                   last_full_resync_at, last_error)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                   CASE WHEN ? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') END, ?)
           ON CONFLICT(collection_href) DO UPDATE SET
             sync_token=excluded.sync_token,
             last_sync_at=excluded.last_sync_at,
             last_full_resync_at=COALESCE(excluded.last_full_resync_at,
                                          sync_state.last_full_resync_at),
             last_error=excluded.last_error""",
        (collection_href, token, 1 if full else 0, error),
    )


def set_sync_error(conn: sqlite3.Connection, collection_href: str, error: str) -> None:
    conn.execute(
        "UPDATE sync_state SET last_error=? WHERE collection_href=?", (error, collection_href)
    )


# ── items ────────────────────────────────────────────────────────────────────

def _evict_uid(conn: sqlite3.Connection, collection_href: str, uid: str) -> None:
    """Drop a UID's derived cache rows and mark its sidecar orphaned. Used when a
    href starts carrying a different UID: the old UID is gone from that resource,
    so its cache state must go with it, but the sidecar is only *marked* (never
    deleted here) — gc_orphans owns that, and only off a complete enumeration."""
    # FTS first: the rowid it deletes by lives on the items row.
    _fts_delete(conn, collection_href, uid)
    conn.execute("DELETE FROM items WHERE collection_href=? AND uid=?", (collection_href, uid))
    conn.execute("DELETE FROM categories WHERE collection_href=? AND uid=?", (collection_href, uid))
    orphan_sidecar(conn, collection_href, uid)


def upsert_item(
    conn: sqlite3.Connection, collection_href: str, item: Item, fields: TaskFields
) -> None:
    """Insert/replace the cache row for a resource, keyed on (collection, UID).
    A returning UID (delete-and-recreate) updates the same row and naturally
    rejoins its sidecar. Also refreshes categories + FTS. If the UID had a live
    sidecar orphan mark, clear it — it's back.

    Rows are keyed on UID but a resource is addressed by href, so a href that
    starts carrying a *different* UID (a foreign client rewriting the body in
    place, or a restored .ics landing at an existing path) would otherwise leave
    the old UID's row behind at that same href. Nothing could then reach it: the
    resync sweep iterates ``href_uid_map``, a dict keyed on href, so one of the
    two rows is invisible to it, and the href is still on the wire so it is never
    swept. The ghost survives every resync and restart — and because it hands out
    the live resource's href, deleting or editing the ghost operates on the live
    resource. One row per href, enforced here."""
    for stale in conn.execute(
        "SELECT uid FROM items WHERE collection_href=? AND href=? AND uid<>?",
        (collection_href, item.href, fields.uid),
    ).fetchall():
        _evict_uid(conn, collection_href, stale["uid"])
    # Read the FTS bookkeeping BEFORE the upsert: afterwards the row always
    # exists, so "was this item already cached?" is no longer answerable — and
    # that answer is what lets a first sync skip the delete entirely.
    prior = _fts_rowid(conn, collection_href, fields.uid)
    conn.execute(
        """INSERT INTO items (collection_href, uid, href, etag, raw_ics, component, summary,
             description, status, priority, percent_complete, completed, due,
             due_is_date, dtstart, dtstart_is_date, dtend, dtend_is_date, duration,
             related_parent, sequence, has_rrule, min_instant, location, transp,
             created, last_modified, synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                   strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(collection_href, uid) DO UPDATE SET
             href=excluded.href, etag=excluded.etag, raw_ics=excluded.raw_ics,
             component=excluded.component, summary=excluded.summary,
             description=excluded.description, status=excluded.status, priority=excluded.priority,
             percent_complete=excluded.percent_complete, completed=excluded.completed,
             due=excluded.due, due_is_date=excluded.due_is_date, dtstart=excluded.dtstart,
             dtstart_is_date=excluded.dtstart_is_date, dtend=excluded.dtend,
             dtend_is_date=excluded.dtend_is_date, duration=excluded.duration,
             related_parent=excluded.related_parent, sequence=excluded.sequence,
             has_rrule=excluded.has_rrule, min_instant=excluded.min_instant,
             location=excluded.location, transp=excluded.transp,
             created=excluded.created,
             last_modified=excluded.last_modified, synced_at=excluded.synced_at""",
        (
            collection_href, fields.uid, item.href, item.etag, item.data, fields.component,
            fields.summary, fields.description, fields.status, fields.priority,
            fields.percent_complete, fields.completed, fields.due,
            int(fields.due_is_date), fields.dtstart, int(fields.dtstart_is_date),
            fields.dtend, int(fields.dtend_is_date), fields.duration,
            fields.related_parent, fields.sequence, int(fields.has_rrule),
            fields.min_instant, fields.location, fields.transp,
            fields.created, fields.last_modified,
        ),
    )
    conn.execute(
        "DELETE FROM categories WHERE collection_href=? AND uid=?", (collection_href, fields.uid)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO categories (collection_href, uid, category) VALUES (?,?,?)",
        [(collection_href, fields.uid, c) for c in fields.categories],
    )
    _fts_replace(conn, collection_href, fields, prior)
    # The UID is present on the wire again; if it was an orphan, un-orphan it.
    conn.execute(
        "UPDATE sidecar SET orphaned_at=NULL WHERE collection_href=? AND uid=? AND orphaned_at IS NOT NULL",
        (collection_href, fields.uid),
    )


def _fts_rowid(conn: sqlite3.Connection, collection_href: str, uid: str):
    """`(existed, fts_rowid)` for a cached item: whether the items row is there
    at all, and the FTS rowid it recorded (None for a row written before that
    column existed)."""
    row = conn.execute(
        "SELECT fts_rowid FROM items WHERE collection_href=? AND uid=?",
        (collection_href, uid),
    ).fetchone()
    return (row is not None, row["fts_rowid"] if row is not None else None)


def _fts_delete(conn: sqlite3.Connection, collection_href: str, uid: str) -> None:
    """Remove a UID's FTS entry, by rowid where we know it.

    `uid` and `collection_href` are UNINDEXED columns of an fts5 table, which
    means fts5 keeps no index over them and SQLite plans a predicate on them as
    `SCAN items_fts VIRTUAL TABLE` — a full scan of the ENTIRE FTS table, across
    every collection, per row touched. `upsert_item` does one of these per item,
    so a full resync cost (items upserted) × (items in the whole DB), inside one
    BEGIN IMMEDIATE, under the service lock every API route shares. Measured at
    2.23 ms per delete against an 8000-row table: a few thousand items froze the
    whole API — no task list, no calendar, no booking page, no login — for tens
    of seconds, on an operation that happens routinely.

    `items.fts_rowid` is written alongside each insert so the delete is a rowid
    lookup. A row cached before that column existed has NULL and falls back to
    the scan, which is correct if slow, and picks up a rowid on its next upsert.
    """
    existed, rowid = _fts_rowid(conn, collection_href, uid)
    _fts_delete_known(conn, collection_href, uid, existed, rowid)


def _fts_delete_known(
    conn: sqlite3.Connection, collection_href: str, uid: str, existed: bool, rowid
) -> None:
    if not existed:
        # No items row means no FTS entry: the two are only ever written and
        # dropped together, inside one transaction, by this module. Skipping the
        # lookup matters most on a FIRST sync, where every upsert is an insert
        # and the fallback below would scan the whole table for nothing.
        return
    if rowid is not None:
        conn.execute("DELETE FROM items_fts WHERE rowid=?", (rowid,))
        return
    conn.execute(
        "DELETE FROM items_fts WHERE collection_href=? AND uid=?", (collection_href, uid)
    )


def _fts_replace(
    conn: sqlite3.Connection, collection_href: str, f: TaskFields, prior=None
) -> None:
    """Replace a UID's FTS entry. `prior` is the `(existed, rowid)` pair read
    BEFORE the items row was upserted — the caller has to take it then, because
    afterwards every row looks like it existed."""
    existed, rowid = prior if prior is not None else _fts_rowid(conn, collection_href, f.uid)
    _fts_delete_known(conn, collection_href, f.uid, existed, rowid)
    cur = conn.execute(
        "INSERT INTO items_fts (uid, collection_href, summary, description, categories) "
        "VALUES (?,?,?,?,?)",
        (f.uid, collection_href, f.summary or "", f.description or "", " ".join(f.categories)),
    )
    conn.execute(
        "UPDATE items SET fts_rowid=? WHERE collection_href=? AND uid=?",
        (cur.lastrowid, collection_href, f.uid),
    )


def delete_item_by_href(conn: sqlite3.Connection, collection_href: str, href: str) -> str | None:
    """Delete the cache row matching this href. Returns its UID (so the caller can
    orphan the sidecar), or None if no row matched — which is the correct no-op
    when the href was already rewritten by a delete-and-recreate."""
    row = conn.execute(
        "SELECT uid FROM items WHERE collection_href=? AND href=?", (collection_href, href)
    ).fetchone()
    if row is None:
        return None
    uid = row["uid"]
    _fts_delete(conn, collection_href, uid)          # before the items row goes
    conn.execute("DELETE FROM items WHERE collection_href=? AND uid=?", (collection_href, uid))
    return uid


def get_item(conn: sqlite3.Connection, collection_href: str, uid: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM items WHERE collection_href=? AND uid=?", (collection_href, uid)
    ).fetchone()


def href_uid_map(conn: sqlite3.Connection, collection_href: str) -> dict[str, str]:
    return {
        r["href"]: r["uid"]
        for r in conn.execute(
            "SELECT href, uid FROM items WHERE collection_href=?", (collection_href,)
        )
    }


def known_etags(conn: sqlite3.Connection, collection_href: str) -> dict[str, str]:
    """{href: etag} for a full-resync diff (skip re-fetching unchanged bodies)."""
    return {
        r["href"]: r["etag"]
        for r in conn.execute(
            "SELECT href, etag FROM items WHERE collection_href=?", (collection_href,)
        )
    }


# ── sidecar + orphan GC ──────────────────────────────────────────────────────

def orphan_sidecar(conn: sqlite3.Connection, collection_href: str, uid: str) -> None:
    """Mark a UID's sidecar orphaned (its item left the wire). Only rows that
    exist are touched — a UID with no sidecar has nothing to keep."""
    conn.execute(
        "UPDATE sidecar SET orphaned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE collection_href=? AND uid=? AND orphaned_at IS NULL",
        (collection_href, uid),
    )


# ── revoked sessions (explicit logout) ───────────────────────────────────────

def revoke_session(conn: sqlite3.Connection, jti: str, expires_at: float) -> None:
    """Remember a logged-out token id until its own exp passes."""
    conn.execute(
        "INSERT OR IGNORE INTO revoked_sessions (jti, expires_at) VALUES (?, ?)",
        (jti, float(expires_at)),
    )
    conn.commit()


def live_revocations(conn: sqlite3.Connection, *, now: float) -> dict[str, float]:
    """Revocations that still matter, sweeping the ones that no longer do: past
    its own exp a token is refused anyway, so the row stops earning its keep."""
    conn.execute("DELETE FROM revoked_sessions WHERE expires_at <= ?", (now,))
    conn.commit()
    return {
        r["jti"]: r["expires_at"]
        for r in conn.execute("SELECT jti, expires_at FROM revoked_sessions")
    }


def gc_orphans(
    conn: sqlite3.Connection, collection_href: str | None = None, *, keep_days: int = 7
) -> int:
    """Drop sidecar rows orphaned longer than keep_days. Returns the count.

    `collection_href` scopes the sweep, and the caller that matters passes it.
    This is the only irreversible deletion in the cache layer — sidecar rows
    hold kanban column, manual sort order, pins and estimated minutes, the one
    part of the DB no resync can rebuild — and `full_resync` gates it behind
    "the enumeration was complete". That guard is per-collection, so an
    unscoped sweep here was defeated by any OTHER collection resyncing cleanly:
    a collection whose enumeration is permanently incomplete never GCs its own
    orphans, exactly as designed, and then lost them anyway the first time an
    unrelated calendar full-resynced."""
    sql = ("DELETE FROM sidecar WHERE orphaned_at IS NOT NULL "
           "AND orphaned_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)")
    params: tuple = (f"-{int(keep_days)} days",)
    if collection_href is not None:
        sql += " AND collection_href=?"
        params += (collection_href,)
    return conn.execute(sql, params).rowcount


def get_sidecar(conn: sqlite3.Connection, collection_href: str, uid: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sidecar WHERE collection_href=? AND uid=?", (collection_href, uid)
    ).fetchone()


def set_sidecar(conn: sqlite3.Connection, collection_href: str, uid: str, **fields: object) -> None:
    """Write app-only fields for a task — but only for a uid that actually names a
    live item in that collection.

    The guard is the same one `set_sort_orders` carries below, moved here for the
    reason its docstring gives: *the guard belongs where every door passes.* This
    was a bare ``INSERT OR IGNORE``, and three doors reach it. Two were hardened
    one at a time — `PUT …/tasks/{uid}/sidecar` got a `has_task` check, and the
    reorder path got the `EXISTS` clause written into `set_sort_orders` — and the
    third, the day-plan estimate write-through added later
    (`service.patch_day_entry`), passed unguarded.

    That third door is not an edge case: a day entry is a POINTER with no foreign
    key, *designed* to outlive the task it names (schema.sql, and `_carry_into`'s
    docstring says so in as many words), so `row["uid"]` routinely names a uid
    `items` no longer holds. Plan "Buy milk" onto tomorrow, tick it off in
    Tasks.org that evening so the VTODO leaves the wire, then type an estimate on
    the row that is still there — and a sidecar row appears for a task that does
    not exist. `orphan_sidecar` only ever stamps rows that exist at the moment a
    KNOWN item is removed, and `gc_orphans` deletes only `orphaned_at IS NOT
    NULL`, so a row minted after that moment has `orphaned_at IS NULL` forever.
    Permanent, in the one table a resync cannot rebuild.

    The UPDATEs carry the guard too, not just the INSERT. `set_sort_orders`'
    `ON CONFLICT … DO UPDATE` never fires when its `WHERE EXISTS` produced no
    row, so mirroring it means an absent item writes NOTHING — including to a row
    that is already there and already orphaned. Quietly doing nothing rather than
    raising: refusing loudly is defensible too, but no caller here is in a
    position to do anything about it, and a 500 on an estimate the user typed is
    worse than the estimate not being remembered for next time.
    """
    allowed = {"kanban_column", "sort_order", "pinned", "estimated_minutes", "repeat_from_completion"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown sidecar fields: {bad}")
    conn.execute(
        "INSERT INTO sidecar (collection_href, uid) SELECT ?, ? WHERE EXISTS "
        "(SELECT 1 FROM items WHERE collection_href=? AND uid=?) "
        "ON CONFLICT(collection_href, uid) DO NOTHING",
        (collection_href, uid, collection_href, uid),
    )
    for k, v in fields.items():
        conn.execute(
            # {k} is vetted against the `allowed` set above — not attacker input.
            f"UPDATE sidecar SET {k}=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "  # nosec B608
            "WHERE collection_href=? AND uid=? AND EXISTS "
            "(SELECT 1 FROM items WHERE collection_href=? AND uid=?)",
            (v, collection_href, uid, collection_href, uid),
        )


def set_sort_orders(conn: sqlite3.Connection, placed: list[tuple[str, str]]) -> None:
    """Write a manual order: `placed` is (collection_href, uid) in the new order,
    and each gets its 1-based index as its ``sort_order``.

    One statement per row inside the caller's transaction, so a reorder is all
    or nothing — a partial write would leave two tasks sharing a position and
    the order would depend on whatever broke the tie.

    Rows are created on demand: a task that has never had a sidecar (which is
    every task until something is dragged) gets one here rather than being
    skipped, which is what makes the whole sequence explicit afterwards.

    …but only for a uid that actually names a live item in that collection. A
    sidecar row is the one thing a cache rebuild cannot reconstruct, so
    `orphan_sidecar` marks a row when its item goes and `gc_orphans` sweeps only
    rows already marked — a row minted for a uid that never existed has
    `orphaned_at IS NULL` forever and can never be reclaimed. `PUT
    …/tasks/{uid}/sidecar` was given a `has_task` guard and a nine-line comment
    about exactly this in the 2026-08-07 sweep; `POST /api/tasks/reorder` writes
    to the same table through a different door, validated only that the LIST
    resolves, with `uid` an unbounded free-text string and 20 000 entries allowed
    per request. The guard belongs here, where every door passes.
    """
    for i, (href, uid) in enumerate(placed, start=1):
        conn.execute(
            "INSERT INTO sidecar (collection_href, uid, sort_order) "
            "SELECT ?, ?, ? WHERE EXISTS "
            "(SELECT 1 FROM items WHERE collection_href=? AND uid=?) "
            "ON CONFLICT(collection_href, uid) DO UPDATE SET "
            "sort_order=excluded.sort_order, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (href, uid, float(i), href, uid),
        )


# ── scheduling (booking links + booking ledger; sidecar-class) ──────────────

_LINK_FIELDS = {
    "title", "description", "calendar_href", "duration_minutes", "timezone",
    "availability", "show_busy", "buffer_minutes", "min_notice_hours",
    "horizon_days", "enabled",
}


def create_booking_link(conn: sqlite3.Connection, token: str, fields: dict) -> sqlite3.Row:
    bad = set(fields) - _LINK_FIELDS
    if bad:
        raise ValueError(f"unknown booking link fields: {bad}")
    cols = ["token", *fields.keys()]
    conn.execute(
        # cols are vetted against _LINK_FIELDS above — not attacker input.
        f"INSERT INTO booking_links ({', '.join(cols)}) "  # nosec B608
        f"VALUES ({', '.join('?' * len(cols))})",
        (token, *fields.values()),
    )
    return get_booking_link(conn, token)


def get_booking_link(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM booking_links WHERE token=?", (token,)
    ).fetchone()


def list_booking_links(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM booking_links ORDER BY created_at"))


def update_booking_link(
    conn: sqlite3.Connection, token: str, fields: dict
) -> sqlite3.Row | None:
    bad = set(fields) - _LINK_FIELDS
    if bad:
        raise ValueError(f"unknown booking link fields: {bad}")
    if get_booking_link(conn, token) is None:
        return None
    # One statement per field on an autocommit connection is one COMMIT per
    # field, so a value the schema rejects part-way through left the earlier
    # fields permanently applied — the caller saw a 500 and a half-changed link.
    # Same repair, and the same reason, as reorder_tasks: `with conn:` is not a
    # transaction under isolation_level=None.
    with tx(conn):
        for k, v in fields.items():
            conn.execute(
                # {k} is vetted against _LINK_FIELDS above — not attacker input.
                f"UPDATE booking_links SET {k}=?, "  # nosec B608
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE token=?",
                (v, token),
            )
    return get_booking_link(conn, token)


def delete_booking_link(conn: sqlite3.Connection, token: str) -> bool:
    return conn.execute(
        "DELETE FROM booking_links WHERE token=?", (token,)
    ).rowcount > 0


def insert_booking(
    conn: sqlite3.Connection, *, id: str, link_token: str, calendar_href: str,
    event_uid: str, client_name: str, client_email: str, notes: str | None,
    start_at: str, end_at: str,
) -> None:
    conn.execute(
        """INSERT INTO bookings (id, link_token, calendar_href, event_uid,
             client_name, client_email, notes, start_at, end_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (id, link_token, calendar_href, event_uid, client_name, client_email,
         notes, start_at, end_at),
    )


def get_booking_by_event(conn: sqlite3.Connection, event_uid: str) -> sqlite3.Row | None:
    """A booking by the VEVENT it created — the idempotency hook for replayed
    booking POSTs (the client_id determines the event UID)."""
    return conn.execute(
        "SELECT * FROM bookings WHERE event_uid=?", (event_uid,)
    ).fetchone()


def list_bookings(
    conn: sqlite3.Connection, link_token: str | None = None, *, after: str | None = None
) -> list[sqlite3.Row]:
    q = "SELECT * FROM bookings"
    where, params = [], []
    if link_token is not None:
        where.append("link_token=?")
        params.append(link_token)
    if after is not None:
        where.append("start_at>=?")
        params.append(after)
    if where:
        q += " WHERE " + " AND ".join(where)
    return list(conn.execute(q + " ORDER BY start_at", params))


def bookings_count_by_link(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        r["link_token"]: r["n"]
        for r in conn.execute("SELECT link_token, COUNT(*) AS n FROM bookings GROUP BY link_token")
    }


# ── day plan (sidecar-class; see schema.sql) ─────────────────────────────────
#
# Two tables, one idea: `day_plan` holds the entries and `day_plan_opened`
# records that a day was snapshotted at all, so "opened and emptied" is
# distinguishable from "never opened". Nothing here commits: like the cache
# helpers above, these run inside whatever transaction the caller opened (the
# service wraps a snapshot build in `tx`, because a half-written plan with no
# marker would be re-snapshotted on the next open and end up duplicated).

# The day's reading order. `position IS NULL` first in the key so unpositioned
# rows TRAIL rather than lead — the same trick as get_collections' `ord IS NULL`
# — then created_at, then entry_id. All three are needed for a stable read:
# created_at is only millisecond-resolution, so the rows of one snapshot can
# share a value, and without the final tie-break two entries would be free to
# swap places between two reads of the same unchanged day.
_DAY_ORDER = "position IS NULL, position, created_at, entry_id"


def get_day_entries(conn: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    """Every entry on a day, in reading order — dropped ones included.

    A dropped entry is part of the day's record (it says the owner decided NOT
    to do this), so filtering happens in the caller that has a reason to, never
    here."""
    return list(
        conn.execute(
            # _DAY_ORDER is a module constant — not caller input.
            f"SELECT * FROM day_plan WHERE day=? ORDER BY {_DAY_ORDER}",  # nosec B608
            (day,),
        )
    )


_DAY_RITUAL_FIELDS = {
    "capacity_minutes", "committed_at", "shutdown_at", "reflection",
}


def get_day_ritual(conn: sqlite3.Connection, day: str) -> sqlite3.Row | None:
    """What the owner said about this day, or None if they never said anything.

    None and a row of nulls are the same thing to every reader — the table is
    written lazily on the first statement about a day, so most days have no row
    at all and that is not a state anything needs to distinguish.
    """
    return conn.execute("SELECT * FROM day_ritual WHERE day=?", (day,)).fetchone()


def get_day_rituals(
    conn: sqlite3.Connection, from_day: str, to_day: str
) -> dict[str, sqlite3.Row]:
    """Every day in [from_day, to_day) that has a ritual row, keyed by day.

    `to_day` EXCLUSIVE, matching `get_day_range` beside it — a range read of the
    plan and a range read of what was said about it have to agree about their
    bounds or a caller zipping them together is off by a day at one end.
    """
    rows = conn.execute(
        "SELECT * FROM day_ritual WHERE day >= ? AND day < ? ORDER BY day",
        (from_day, to_day),
    ).fetchall()
    return {r["day"]: r for r in rows}


def set_day_ritual(
    conn: sqlite3.Connection, day: str, **fields: object,
) -> sqlite3.Row | None:
    """Write what the owner said about a day, and return the whole row.

    An explicit None VALUE clears the column, exactly as `update_day_entry` has
    it — that is how a capacity is un-stated and how a day is re-opened after a
    shutdown. So the caller must pass only the fields it means to change, which
    is what a PATCH's unsent fields already give it.

    Upsert rather than update: most days have no row until the first thing is
    said about them, so "create it" and "change it" are the same call and there
    is nothing for a caller to check first.
    """
    bad = set(fields) - _DAY_RITUAL_FIELDS
    if bad:
        raise ValueError(f"unknown day ritual fields: {bad}")
    # NOTHING TO SAY IS NOT A WRITE. `service.set_day_ritual` calls a PATCH with
    # an empty body "a read" and publishes no event for one — and a read that
    # minted the row holding the nulls it had just reported would make that
    # false, and would put a row in a SIDECAR-CLASS table (one no resync
    # rebuilds and every backup has to carry) for a day nobody ever spoke about.
    # None here means exactly what `get_day_ritual` means by it: nothing has been
    # said about this day.
    if not fields:
        return get_day_ritual(conn, day)
    conn.execute("INSERT OR IGNORE INTO day_ritual (day) VALUES (?)", (day,))
    # The column names are vetted against _DAY_RITUAL_FIELDS above — not
    # attacker input; the values are bound.
    assignments = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE day_ritual SET {assignments}, "  # nosec B608
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE day=?",
        (*fields.values(), day),
    )
    return get_day_ritual(conn, day)


def day_is_opened(conn: sqlite3.Connection, day: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM day_plan_opened WHERE day=?", (day,)
    ).fetchone() is not None


def mark_day_opened(conn: sqlite3.Connection, day: str) -> None:
    """Record that this day has been planned. INSERT OR IGNORE, so re-opening a
    day keeps the ORIGINAL opened_at: the column answers "when was this day
    first planned", and a re-open overwriting it would erase that."""
    conn.execute("INSERT OR IGNORE INTO day_plan_opened (day) VALUES (?)", (day,))


def insert_day_entry(
    conn: sqlite3.Connection,
    *,
    day: str,
    entry_id: str,
    kind: str,
    source: str,
    collection_href: str | None = None,
    uid: str | None = None,
    title: str | None = None,
    position: float | None = None,
    habit_id: str | None = None,
    estimate_minutes: int | None = None,
) -> sqlite3.Row:
    """Add one entry to a day and return the stored row.

    Returned rather than echoed back from the arguments, so the caller's DTO
    carries the DB's own `created_at` (the schema default) instead of a second,
    slightly different, idea of now.

    `habit_id` names the rule that minted a kind='habit' occurrence, and is NULL
    for everything else. The occurrence also gets its own `title` — a copy of the
    habit's, taken at insert time — because the row has to keep reading correctly
    after the rule is renamed or deleted.

    `estimate_minutes` is likewise a COPY taken at insert time, not a join. For a
    task the caller reads it off `sidecar` (the estimate that task remembers) and
    hands it in here; from then on it belongs to this day and this row. That is
    what stops re-estimating a task in March from rewriting what January's plan
    said it would take — the same reasoning that gives a habit occurrence its own
    title rather than resolving one.
    """
    conn.execute(
        """INSERT INTO day_plan (day, entry_id, kind, collection_href, uid, title,
                                 source, position, habit_id, estimate_minutes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (day, entry_id, kind, collection_href, uid, title, source, position,
         habit_id, estimate_minutes),
    )
    return find_day_entry(conn, day, entry_id=entry_id)


_DAY_ENTRY_FIELDS = {
    "done_at", "dropped_at", "position", "estimate_minutes", "rolled_to",
}


def update_day_entry(
    conn: sqlite3.Connection, day: str, entry_id: str, **fields: object
) -> sqlite3.Row | None:
    """Patch an entry's mutable columns; None for an entry_id this day doesn't
    have (the route turns that into a 404).

    An explicit None VALUE clears the column — that is how "done" is undone —
    so unlike `set_sidecar`'s caller the route must pass only the fields it
    actually means to change, and PATCH's unsent fields never arrive here.

    One UPDATE for all of them rather than the statement-per-field loop
    `set_sidecar` and `update_booking_link` use. Those need a transaction to be
    atomic (the connection is in autocommit — see `tx`); a single statement is
    atomic on its own, and this one runs on the PATCH path where there is no
    other reason to open one.

    `rowcount` is what distinguishes "no such entry" from a patch that changed
    nothing: SQLite counts the rows the statement PROCESSED, not the ones whose
    values differed, so re-ticking an already-ticked entry still reports 1 and
    only a missing row reports 0. Were it the other way round, a client sending
    the state it already believes in — which is exactly what a retry does —
    would be told its entry is gone.
    """
    bad = set(fields) - _DAY_ENTRY_FIELDS
    if bad:
        raise ValueError(f"unknown day entry fields: {bad}")
    if fields:
        # The column names are vetted against _DAY_ENTRY_FIELDS above — not
        # attacker input; the values are bound.
        assignments = ", ".join(f"{k}=?" for k in fields)
        cur = conn.execute(
            f"UPDATE day_plan SET {assignments} WHERE day=? AND entry_id=?",  # nosec B608
            (*fields.values(), day, entry_id),
        )
        if not cur.rowcount:
            return None
    return find_day_entry(conn, day, entry_id=entry_id)


def get_day_range(
    conn: sqlite3.Connection, from_day: str, to_day: str
) -> dict[str, list[sqlite3.Row]]:
    """Every planned day in [from_day, to_day) → its entries, oldest day first.

    `to_day` is EXCLUSIVE, matching the calendar-window convention the rest of
    the app uses. Days that were never opened are absent rather than present and
    empty: absence is exactly what a caller renders as "not planned yet", and
    materialising a row per unplanned day would make a six-month query mostly
    padding. ISO day keys compare correctly as strings, so the window is a plain
    range predicate over an indexed column in both tables (day is the marker's
    primary key, and idx_day_plan_day covers the entries).

    A day carrying entries but NO marker row cannot be produced by this module —
    every writer marks the day — but it is still listed if the DB somehow holds
    one (a hand edit, a partial restore). Dropping those entries from the read
    would make real rows invisible while they went on occupying their day.
    """
    out: dict[str, list[sqlite3.Row]] = {
        r["day"]: []
        for r in conn.execute(
            "SELECT day FROM day_plan_opened WHERE day >= ? AND day < ? ORDER BY day",
            (from_day, to_day),
        )
    }
    for row in conn.execute(
        # `day` leads the key here so the rows arrive grouped by day, each
        # group already in reading order.
        f"SELECT * FROM day_plan WHERE day >= ? AND day < ? "  # nosec B608
        f"ORDER BY day, {_DAY_ORDER}",
        (from_day, to_day),
    ):
        out.setdefault(row["day"], []).append(row)
    return dict(sorted(out.items()))


def find_day_entry(
    conn: sqlite3.Connection,
    day: str,
    *,
    entry_id: str | None = None,
    collection_href: str | None = None,
    uid: str | None = None,
    title: str | None = None,
) -> sqlite3.Row | None:
    """One entry on a day, looked up three ways: by its own `entry_id`, by the
    task it names (`collection_href` + `uid`), or by a note's exact `title`.
    Exactly one of the three has to be supplied.

    The task and title lookups are what make adding an entry idempotent, and
    they skip DROPPED rows: a task the owner dropped this morning has to be
    addable again this afternoon, and answering with the dropped row would look
    to the client like the add silently did nothing. The `entry_id` lookup does
    not filter — it is identity, and the primary key already guarantees at most
    one row, dropped or not.

    There is deliberately NO habit arm, and the title arm deliberately keeps its
    `kind='note'` filter. A habit OCCURRENCE is minted by a rule, never handed in
    by a client (`service.add_day_entry` refuses kind='habit' and says why), so
    nothing needs to look one up here — and the top-up that does need to know
    which habits already have a row on a day reads `habit_id` off the day's rows
    it is already holding, where a DROPPED row correctly counts as present.
    Dropping the `kind='note'` filter to make the title arm serve habits too
    would break the note path instead: an occurrence copies its habit's title
    onto the row, so adding a note whose text matches one would be answered with
    the habit occurrence, and the note would silently never be created.
    """
    where = ["day=?"]
    params: list[object] = [day]
    if entry_id is not None:
        where.append("entry_id=?")
        params.append(entry_id)
    elif uid is not None and collection_href is not None:
        where.append("collection_href=? AND uid=?")
        params += [collection_href, uid]
    elif title is not None:
        where.append("kind='note' AND title=?")
        params.append(title)
    else:
        raise ValueError("find_day_entry needs entry_id, collection_href+uid, or title")
    if entry_id is None:
        where.append("dropped_at IS NULL")
    return conn.execute(
        # Every fragment above is a literal in this function — not caller input.
        f"SELECT * FROM day_plan WHERE {' AND '.join(where)} "  # nosec B608
        f"ORDER BY {_DAY_ORDER} LIMIT 1",
        params,
    ).fetchone()


# ── habits (SIDECAR: the rules that put entries on a day; see schema.sql) ────
#
# A habit is a RULE. It owns no occurrences: those are ordinary `day_plan` rows
# written by `insert_day_entry` like any other entry, which is why nothing in
# this section reads or writes day_plan at all. Deleting a habit therefore
# CANNOT touch a past day — there is no cascade to write, and no sweep of
# "orphaned" occurrences to be tempted into writing, because a dangling
# habit_id beside a copied title is a complete record on its own.

_HABIT_FIELDS = {"title", "days", "paused_at", "position", "estimate_minutes"}

# Position first, NULLs last, then created_at — the same "unpositioned rows
# TRAIL" shape as _DAY_ORDER, and for the same reason: a habit that has never
# been dragged must not jump ahead of the ones that have. created_at breaks the
# tie so two habits made in the same millisecond still read in a fixed order.
_HABIT_ORDER = "position IS NULL, position, created_at, id"


def create_habit(conn: sqlite3.Connection, id: str, fields: dict) -> sqlite3.Row:
    bad = set(fields) - _HABIT_FIELDS
    if bad:
        raise ValueError(f"unknown habit fields: {bad}")
    cols = ["id", *fields.keys()]
    conn.execute(
        # cols are vetted against _HABIT_FIELDS above — not attacker input.
        f"INSERT INTO habits ({', '.join(cols)}) "  # nosec B608
        f"VALUES ({', '.join('?' * len(cols))})",
        (id, *fields.values()),
    )
    return get_habit(conn, id)


def get_habit(conn: sqlite3.Connection, id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM habits WHERE id=?", (id,)).fetchone()


def list_habits(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every habit in display order, PAUSED ONES INCLUDED.

    Filtering paused rows out here would hide them from the screen that exists
    to un-pause them. The one caller that must skip them — the snapshot — says
    so itself, next to the rest of its scheduling rule."""
    # _HABIT_ORDER is a module constant — not caller input.
    return list(conn.execute(f"SELECT * FROM habits ORDER BY {_HABIT_ORDER}"))  # nosec B608


def update_habit(
    conn: sqlite3.Connection, id: str, fields: dict
) -> sqlite3.Row | None:
    """Patch a habit's columns; None for an id that does not exist (the route
    turns that into a 404).

    One UPDATE for all the fields rather than the statement-per-field loop
    `update_booking_link` uses, for the reason `update_day_entry` gives: a single
    statement is atomic on its own, so an autocommit connection needs no
    transaction around it and a rejected value cannot leave earlier fields
    applied."""
    bad = set(fields) - _HABIT_FIELDS
    if bad:
        raise ValueError(f"unknown habit fields: {bad}")
    if fields:
        # The column names are vetted against _HABIT_FIELDS above — not attacker
        # input; the values are bound.
        assignments = ", ".join(f"{k}=?" for k in fields)
        cur = conn.execute(
            f"UPDATE habits SET {assignments} WHERE id=?",  # nosec B608
            (*fields.values(), id),
        )
        if not cur.rowcount:
            return None
    return get_habit(conn, id)


def delete_habit(conn: sqlite3.Connection, id: str) -> bool:
    """Remove the RULE. One statement, and it names one table on purpose.

    The occurrences this habit already put on past days stay exactly where they
    are, with the title they copied at the time and a now-dangling `habit_id`.
    That is the record of what the owner planned, and no "tidy up orphaned
    occurrences" sweep may ever be added here: it would erase precisely the
    history this design keeps. Nothing in this app DELETEs from day_plan at all
    (dropping an entry stamps `dropped_at`), and that must stay true."""
    return conn.execute("DELETE FROM habits WHERE id=?", (id,)).rowcount > 0


# ── search / queries ─────────────────────────────────────────────────────────

def search(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """FTS across summary/description/categories, joined back to live items.

    User text is never passed to MATCH raw — FTS5 operator characters ('"',
    parentheses, NEAR/AND) would raise. Each whitespace token becomes a quoted
    prefix phrase, so 'proj mee' matches "project meeting".

    Quoting alone was not enough. A NUL byte inside a token truncates the C
    string FTS5 parses, so the closing quote was never seen and `?q=%00` came
    back as an unhandled OperationalError — a 500 on the one input the quoting
    scheme was supposed to make safe. Control bytes are never meaningful search
    text, so they are dropped, and a term that was nothing but control bytes
    drops with them (leaving no terms at all is an empty result, not a malformed
    MATCH)."""
    terms = [t for t in (_CTRL.sub("", t) for t in query.split()) if t]
    if not terms:
        return []
    match = " ".join('"{}"*'.format(t.replace('"', '""')) for t in terms)
    return list(
        conn.execute(
            """SELECT i.* FROM items_fts f
               JOIN items i ON i.collection_href=f.collection_href AND i.uid=f.uid
               WHERE items_fts MATCH ? ORDER BY rank""",
            (match,),
        )
    )


def get_items(conn: sqlite3.Connection, collection_href: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM items WHERE collection_href=? "
            "ORDER BY COALESCE(due, '9999') , COALESCE(summary,'')",
            (collection_href,),
        )
    )


def get_events_in_range(
    conn: sqlite3.Connection, collection_href: str, start_iso: str, end_iso: str
) -> list[sqlite3.Row]:
    """Candidate VEVENTs for the window [start, end).

    Non-recurring events use the precise interval-overlap test
    (event_start <= end AND event_end >= start). A recurring master, however,
    projects occurrences *forward* past its own DTEND, so the lower bound would
    wrongly drop a weekly series whose first instance is months in the past —
    hence recurring rows (has_rrule=1) are admitted on the upper bound alone and
    then precisely filtered in Python by recur.expand_occurrences. A series whose
    UNTIL is already past still passes here but expands to zero occurrences, so it
    is dropped downstream. ISO strings order correctly on the leading date.

    An event whose length is a DURATION rather than a DTEND has dtend NULL, so
    COALESCE would collapse its effective end onto its start and drop it from
    every window that does not contain its first day. That shape is ordinary
    foreign-client output (DAVx5/phone clients — see test_scheduling.py), and the
    row feeds the booking conflict check, so losing it let an anonymous visitor
    book straight over a multi-day block. Admit it on the upper bound alone, like
    a recurring master, and let scheduling.busy_intervals — which already parses
    `duration` — do the precise interval math.

    The upper bound is not a valid gate for a recurring row either, and the
    docstring above was half right for the same reason it was half wrong: a
    recurrence set projects BACKWARDS as well as forwards. `has_rrule` is set for
    RDATE too, and `recurring_ical_events` applies RECURRENCE-ID overrides, so a
    resource can hold an instant EARLIER than its cached master DTSTART — which
    is `items.dtstart`, because `read.extract` caches the master row. Any window
    ending before that dropped the whole resource, occurrence and all.

    This app creates the shape itself: `apply_occurrence_override` writes an
    override with a new DTSTART and deliberately leaves the master rule alone, so
    dragging the FIRST occurrence of a series earlier is enough. Thunderbird's
    and Apple's "move this occurrence" produce it too. `_link_busy` queries only
    +/-1 day around the requested day, so the moved meeting contributed no busy
    interval and an anonymous visitor could book straight over it.

    So a recurring row is gated on `min_instant` — the earliest instant the whole
    RESOURCE can produce, across its overrides and RDATEs — rather than on the
    master's DTSTART. Admitting them unconditionally instead was the first
    attempt and it is not affordable: the stage-2 search budget bounds ONE
    expansion, `_link_busy` runs one per recurring row while holding the global
    lock, and both public booking routes reach it unauthenticated. Measured, 50
    far-future never-matching series (ordinary foreign-client output) went from 0
    candidate rows to 50, and a two-day booking window from ~0 s to 9.13 s.

    A NULL `min_instant` — a row cached before the column existed — is admitted,
    so an incomplete upgrade cannot hide an occurrence."""
    return list(
        conn.execute(
            "SELECT * FROM items WHERE collection_href=? AND component='VEVENT' "
            "AND CASE WHEN has_rrule=1 "
            "         THEN COALESCE(min_instant, dtstart) IS NULL "
            "              OR COALESCE(min_instant, dtstart) <= ? "
            "         ELSE dtstart <= ? AND (duration IS NOT NULL "
            "              OR COALESCE(dtend, dtstart) >= ?) END "
            "ORDER BY dtstart",
            (collection_href, end_iso, end_iso, start_iso),
        )
    )


def get_events(conn: sqlite3.Connection, collection_href: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM items WHERE collection_href=? AND component='VEVENT' ORDER BY dtstart",
            (collection_href,),
        )
    )


def get_all_categories(conn: sqlite3.Connection, collection_href: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT uid, category FROM categories WHERE collection_href=? ORDER BY category",
        (collection_href,),
    ):
        out.setdefault(r["uid"], []).append(r["category"])
    return out


def get_all_sidecar(conn: sqlite3.Connection, collection_href: str) -> dict[str, sqlite3.Row]:
    return {
        r["uid"]: r
        for r in conn.execute(
            "SELECT * FROM sidecar WHERE collection_href=?", (collection_href,)
        )
    }


def distinct_categories(conn: sqlite3.Connection, collection_href: str | None = None) -> list[str]:
    if collection_href is None:
        rows = conn.execute("SELECT DISTINCT category FROM categories ORDER BY category")
    else:
        rows = conn.execute(
            "SELECT DISTINCT category FROM categories WHERE collection_href=? ORDER BY category",
            (collection_href,),
        )
    return [r["category"] for r in rows]


# ── app settings (server-side, account-synced) ───────────────────────────────
#
# UI preferences (e.g. theme) live server-side so they follow the user across
# browsers/devices instead of being trapped in one browser's localStorage. The
# app is single-user (one auth account, one DB), so a single global blob in the
# `meta` table is the account's settings; key by user here if it ever goes
# multi-user.

_SETTINGS_KEY = "app_settings"


def get_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (_SETTINGS_KEY,)).fetchone()
    if row is None or not row["value"]:
        return {}
    try:
        data = json.loads(row["value"])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def update_settings(conn: sqlite3.Connection, patch: dict) -> dict:
    """Merge `patch` into the stored settings (keys with None are ignored) and
    return the full settings dict."""
    current = get_settings(conn)
    current.update({k: v for k, v in patch.items() if v is not None})
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_SETTINGS_KEY, json.dumps(current)),
    )
    return current


# ── notifications (SIDECAR: the record of what has already been said) ────────
#
# The scheduler re-evaluates the same window on every wake, so "have I already
# said this?" is not answerable from the data that triggered the notification —
# it is answered here. `dedupe_key` names the OCCASION (uid + day, uid + start
# instant, a day key for a digest), never the wording.
#
# The claim/settle split is the whole point. `claim_notification` writes the row
# BEFORE the message is sent and reports whether this caller is the one that got
# it; the send then happens OUTSIDE the service lock (network I/O under the
# process-wide RLock would block every API route for the length of an HTTP
# timeout), and `settle_notification` stamps the outcome back. A crash between
# the two leaves a claimed-but-unsettled row, which is deliberately treated as
# SENT: a duplicate 3am alert costs more trust than a missed one.

_NOTIFY_CHANNEL = "telegram"


def claim_notification(
    conn: sqlite3.Connection,
    trigger: str,
    dedupe_key: str,
    *,
    channel: str = _NOTIFY_CHANNEL,
) -> bool:
    """Reserve the right to send one notification. True when this caller won it.

    False means the occasion has already been claimed — by an earlier sweep, or
    by a concurrent one — and the caller must not send. Atomic on its own (one
    statement), so it needs no surrounding transaction.
    """
    cur = conn.execute(
        "INSERT INTO notification_deliveries (trigger, dedupe_key, channel) "
        "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        (trigger, dedupe_key, channel),
    )
    return bool(cur.rowcount)


def settle_notification(
    conn: sqlite3.Connection,
    trigger: str,
    dedupe_key: str,
    *,
    channel: str = _NOTIFY_CHANNEL,
    ok: bool,
    silent: bool = False,
    error: str | None = None,
) -> None:
    """Record how a claimed send turned out.

    `error` must already be redacted — the bot token travels in the request path
    and httpx puts the URL in its exception text, so an unredacted string here is
    a plaintext credential in every backup of this file. `notify.telegram`
    redacts on the way out; this function is not the place to start trusting it.
    """
    conn.execute(
        "UPDATE notification_deliveries SET "
        "settled_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'), ok=?, silent=?, error=? "
        "WHERE trigger=? AND dedupe_key=? AND channel=?",
        (1 if ok else 0, 1 if silent else 0, error, trigger, dedupe_key, channel),
    )


def release_notification(
    conn: sqlite3.Connection,
    trigger: str,
    dedupe_key: str,
    *,
    channel: str = _NOTIFY_CHANNEL,
) -> None:
    """Hand a claim back, for when the send was abandoned before it was attempted.

    Only for the case where nothing left the process — the channel turned out to
    be unconfigured, quiet hours swallowed the message, the batch it belonged to
    was dropped. Never call this after the transport has been reached: if the API
    call happened, the message may well have arrived, and re-arming it is exactly
    the duplicate this table exists to prevent.
    """
    conn.execute(
        "DELETE FROM notification_deliveries "
        "WHERE trigger=? AND dedupe_key=? AND channel=?",
        (trigger, dedupe_key, channel),
    )


def notification_already_sent(
    conn: sqlite3.Connection,
    trigger: str,
    dedupe_key: str,
    *,
    channel: str = _NOTIFY_CHANNEL,
) -> bool:
    """Read-only companion to `claim_notification`, for previewing a sweep."""
    row = conn.execute(
        "SELECT 1 FROM notification_deliveries "
        "WHERE trigger=? AND dedupe_key=? AND channel=?",
        (trigger, dedupe_key, channel),
    ).fetchone()
    return row is not None


def recent_notifications(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    """The last `limit` deliveries, newest first — what Settings shows so the
    owner can see what the bot has been saying without opening Telegram."""
    rows = conn.execute(
        "SELECT * FROM notification_deliveries ORDER BY claimed_at DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    )
    return [dict(r) for r in rows]


def gc_notifications(conn: sqlite3.Connection, *, before: str) -> int:
    """Drop delivery rows claimed before `before` (an ISO stamp).

    Called from the send path rather than a timer of its own, like `gc_oauth`.
    The retention only has to outlive the longest dedupe window any trigger uses
    — once the occasion can no longer recur, the row is answering a question
    nobody will ask again.
    """
    cur = conn.execute(
        "DELETE FROM notification_deliveries WHERE claimed_at < ?", (before,)
    )
    return cur.rowcount or 0


def count_items(conn: sqlite3.Connection, collection_href: str | None = None) -> int:
    if collection_href is None:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM items WHERE collection_href=?", (collection_href,)
    ).fetchone()[0]


# The four numbers a list/calendar row shows. Counted in SQL rather than by
# reading the rows: the caller only ever wanted these integers, but got there by
# materialising every column of every item — `raw_ics` BLOBs included — for every
# collection, inside the global service lock, on every sidebar render.
_COUNT_COLUMNS = """
    COUNT(*) AS total,
    SUM(component = 'VTODO') AS task_count,
    SUM(component = 'VEVENT') AS event_count,
    SUM(component = 'VTODO'
        AND (status IS NULL OR status NOT IN ('COMPLETED', 'CANCELLED'))) AS open_count
"""


_COUNT_KEYS = ("total", "task_count", "event_count", "open_count")
ZERO_COUNTS: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)


def _counts_row(row) -> dict[str, int]:
    # SUM over no rows is NULL, and an empty collection must read as 0, not None.
    return {k: int(row[k] or 0) for k in _COUNT_KEYS}


def collection_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Per-collection item counts for every collection, in one pass.

    One query for the whole sidebar rather than one per collection, because the
    caller renders them all together and holds the lock while it does."""
    return {
        r["collection_href"]: _counts_row(r)
        for r in conn.execute(
            # _COUNT_COLUMNS is a module constant — not attacker input. Shared
            # with counts_for_collection so the bulk and single-collection paths
            # cannot drift into disagreeing about what "open" means.
            f"SELECT collection_href, {_COUNT_COLUMNS} "  # nosec B608
            "FROM items GROUP BY collection_href"
        )
    }


def counts_for_collection(conn: sqlite3.Connection, collection_href: str) -> dict[str, int]:
    """The same four numbers for one collection, for the single-row callers."""
    row = conn.execute(
        # _COUNT_COLUMNS is a module constant — not attacker input.
        f"SELECT {_COUNT_COLUMNS} FROM items WHERE collection_href=?",  # nosec B608
        (collection_href,),
    ).fetchone()
    return _counts_row(row)


# ── OAuth 2.1 authorization server (remote MCP connectors) ───────────────────
#
# Every function here takes and returns *hashes* of secrets, never the secrets
# themselves — hashing is the caller's job (mcp/oauth.py), so a mistake there is
# visible at the call site rather than buried in SQL. The only plaintext that
# reaches this module is the client_id, which is a public identifier.


def create_oauth_client(
    conn: sqlite3.Connection,
    *,
    client_id: str,
    client_secret_hash: str | None,
    client_name: str | None,
    redirect_uris: list[str],
    scope: str,
    now: float,
) -> None:
    conn.execute(
        "INSERT INTO oauth_clients (client_id, client_secret_hash, client_name, "
        "redirect_uris, scope, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (client_id, client_secret_hash, client_name,
         json.dumps(list(redirect_uris)), scope, now, now),
    )
    conn.commit()


def get_oauth_client(conn: sqlite3.Connection, client_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["redirect_uris"] = json.loads(d["redirect_uris"])
    except (TypeError, ValueError):
        d["redirect_uris"] = []
    if not isinstance(d["redirect_uris"], list):
        d["redirect_uris"] = []
    return d


def touch_oauth_client(conn: sqlite3.Connection, client_id: str, now: float) -> None:
    """Mark a client as still in use, so the sweep below spares it."""
    conn.execute(
        "UPDATE oauth_clients SET last_used_at=? WHERE client_id=?", (now, client_id)
    )
    conn.commit()


def count_oauth_clients(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0]


def gc_oauth(conn: sqlite3.Connection, *, now: float, client_idle_s: float) -> int:
    """Sweep expired codes and tokens, and clients that never got used.

    Registration is open by design, so this is what keeps an unauthenticated
    caller from growing the tables without bound. A client is spared as long as
    it keeps completing flows; one that registered and then went quiet is junk.
    Returns the number of client rows dropped.
    """
    conn.execute("DELETE FROM oauth_codes WHERE expires_at <= ?", (now,))
    # A used refresh token is kept until it expires, not dropped on use: the
    # replay check needs the row to still be there to notice the second attempt.
    conn.execute("DELETE FROM oauth_tokens WHERE expires_at <= ?", (now,))
    cur = conn.execute(
        "DELETE FROM oauth_clients WHERE last_used_at <= ? AND client_id NOT IN "
        "(SELECT DISTINCT client_id FROM oauth_tokens)",
        (now - client_idle_s,),
    )
    conn.commit()
    return cur.rowcount or 0


def evict_oauth_clients(conn: sqlite3.Connection, *, limit: int) -> int:
    """Drop up to `limit` least-recently-used clients that hold NOTHING.

    The companion to `gc_oauth`, for when the table is at its cap and the sweep
    freed nothing: `gc_oauth` spares a client until it has been idle, and idle
    time is exactly what a registration flood does not give you. Registration is
    unauthenticated, so without this the cap protected the table by locking the
    OWNER out of it — a denial of service performed by the defence.

    Two exclusions, and both matter:

    * a client holding a TOKEN is a working grant. Evicting it signs a real
      client out, which is the thing the cap was supposed to prevent.
    * a client holding a live CODE is mid-consent — the owner is on the screen
      right now. Eviction has no idleness requirement (that is the point), so
      without this a registration burst timed against a consent would break it.

    `last_used_at` is seeded from `created_at` (see `create_oauth_client`), so a
    never-used client orders by when it registered and a flood evicts itself
    oldest-first.

    What this does NOT protect is the gap between a legitimate client's
    registration and its authorize call, where it holds neither a token nor a
    code and is evictable like any junk row. That window is a few seconds of a
    flow the user is actively driving, and the client re-registers on a failure;
    closing it would need a grace period, which is the idleness requirement this
    function exists to do without.
    """
    cur = conn.execute(
        "DELETE FROM oauth_clients WHERE client_id IN ("
        "  SELECT client_id FROM oauth_clients"
        "   WHERE client_id NOT IN (SELECT DISTINCT client_id FROM oauth_tokens)"
        "     AND client_id NOT IN (SELECT DISTINCT client_id FROM oauth_codes)"
        "   ORDER BY last_used_at ASC, created_at ASC"
        "   LIMIT ?"
        ")",
        (limit,),
    )
    conn.commit()
    return cur.rowcount or 0


def create_oauth_code(
    conn: sqlite3.Connection,
    *,
    code_hash: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    resource: str,
    code_challenge: str,
    expires_at: float,
    now: float,
) -> None:
    conn.execute(
        "INSERT INTO oauth_codes (code_hash, client_id, redirect_uri, scope, resource, "
        "code_challenge, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (code_hash, client_id, redirect_uri, scope, resource,
         code_challenge, expires_at, now),
    )
    conn.commit()


def take_oauth_code(conn: sqlite3.Connection, code_hash: str, *, now: float) -> dict | None:
    """Consume an authorization code: read it and delete it in one transaction.

    Single-use is enforced by the delete, not by a flag — two concurrent
    exchanges race on the same row and SQLite serialises them, so exactly one
    sees a rowcount of 1. Returns None for unknown, already-used or expired.
    """
    with conn:
        row = conn.execute(
            "SELECT * FROM oauth_codes WHERE code_hash=?", (code_hash,)
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute("DELETE FROM oauth_codes WHERE code_hash=?", (code_hash,))
        if not cur.rowcount:
            return None                      # lost the race; the winner has it
    return dict(row) if row["expires_at"] > now else None


def create_oauth_token(
    conn: sqlite3.Connection,
    *,
    token_hash: str,
    kind: str,
    client_id: str,
    scope: str,
    resource: str,
    family_id: str,
    expires_at: float,
    now: float,
    cv: str = "",
) -> None:
    # `cv` defaults to '' so a direct caller predating it still compiles — and
    # gets a token refused on first use rather than one silently exempt from the
    # check. Failing closed is the only safe default for a field whose whole job
    # is revocation.
    conn.execute(
        "INSERT INTO oauth_tokens (token_hash, kind, client_id, scope, resource, "
        "family_id, used_at, expires_at, created_at, cv) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
        (token_hash, kind, client_id, scope, resource, family_id, expires_at, now, cv),
    )
    conn.commit()


def get_oauth_token(conn: sqlite3.Connection, token_hash: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM oauth_tokens WHERE token_hash=?", (token_hash,)
    ).fetchone()
    return dict(row) if row else None


def use_refresh_token(conn: sqlite3.Connection, token_hash: str, *, now: float) -> str:
    """Claim a refresh token for rotation.

    Returns "ok" when this call is the one that claimed it, "replayed" when it
    had already been used (the caller must then kill the family — a second
    presentation means a copy is loose), and "invalid" for unknown/expired.

    The claim is a conditional UPDATE, so two concurrent redemptions cannot both
    succeed: SQLite serialises them and the loser sees rowcount 0, which is the
    same signal as a genuine replay. Treating that as a stolen token is the
    conservative reading and costs an honest client one reconnect.
    """
    with conn:
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE token_hash=? AND kind='refresh'",
            (token_hash,),
        ).fetchone()
        if row is None or row["expires_at"] <= now:
            return "invalid"
        cur = conn.execute(
            "UPDATE oauth_tokens SET used_at=? WHERE token_hash=? AND used_at IS NULL",
            (now, token_hash),
        )
        return "ok" if cur.rowcount else "replayed"


def revoke_oauth_family(conn: sqlite3.Connection, family_id: str) -> int:
    """Drop every token in a rotation family. Used on replay, and on an explicit
    disconnect — one row per issued token, so this ends the whole grant."""
    cur = conn.execute("DELETE FROM oauth_tokens WHERE family_id=?", (family_id,))
    conn.commit()
    return cur.rowcount or 0


def list_oauth_grants(conn: sqlite3.Connection, *, now: float) -> list[dict]:
    """One row per live grant (family), for the connections screen: which client,
    what it may do, when it was granted and when it was last refreshed.

    `scope` is the UNION of the family's live tokens' scopes, because the question
    the screen answers is "what can this connection still do" and the answer is
    what ANY live token permits.

    Scope is not constant within a family: `_grant_refresh` implements RFC 6749
    §6 narrowing and reissues into the SAME family_id, while the previous
    wide-scoped ACCESS token stays live for the rest of its hour. Reading a bare
    column out of the GROUP BY took it from an arbitrary row (SQLite pins one
    only when the query holds exactly one min()/max() aggregate, and this has
    three); reading the newest live token's scope was deterministic but
    systematically wrong in the UNSAFE direction — after a narrowing refresh the
    screen read "read-only" while the connector kept writing with a token that
    had another hour to run. A scoped MCP token can trigger that deliberately by
    refreshing with `scope=mcp:read` straight after the code exchange. Revocation
    always worked, so this was deception rather than escalation, but the screen
    exists to be acted on.

    The union is taken in Python rather than SQL: scopes are space-separated
    strings and SQLite has no set type, so a SQL version would mean a recursive
    CTE to split them. First-seen order (oldest token first) is preserved so the
    chips read stably rather than reshuffling on every poll.
    """
    # Plain `?` placeholders, one per query. The single-query version used `?1`
    # twice — a NUMBERED placeholder, which CPython's sqlite3 classifies as NAMED
    # (its name is the literal "?1"), so binding a sequence to it was a
    # DeprecationWarning on 3.12 and an sqlite3.ProgrammingError from 3.14.
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT t.family_id, t.client_id, t.resource, "
            "       MIN(t.created_at) AS granted_at, MAX(t.created_at) AS refreshed_at, "
            "       MAX(t.expires_at) AS expires_at, c.client_name "
            "FROM oauth_tokens t LEFT JOIN oauth_clients c ON c.client_id = t.client_id "
            "WHERE t.expires_at > ? GROUP BY t.family_id ORDER BY granted_at DESC",
            (now,),
        )
    ]
    # `used_at IS NULL` matters as much as `expires_at`. `use_refresh_token`
    # marks a rotated-out refresh row used and leaves its expiry alone, so a
    # spent one stays "live" for the whole REFRESH_TTL_S — thirty days. Without
    # this clause a grant narrowed to read-only went on reporting write for a
    # month, which is the same deception the union was introduced to end, just
    # 720x longer than the one hour the docstring above describes. Access tokens
    # are never marked used, so this only excludes what it should.
    live: dict[str, list[str]] = {}
    for family_id, scope in conn.execute(
        "SELECT family_id, scope FROM oauth_tokens "
        "WHERE expires_at > ? AND used_at IS NULL "
        "ORDER BY created_at ASC, rowid ASC",
        (now,),
    ):
        seen = live.setdefault(family_id, [])
        for word in (scope or "").split():
            if word not in seen:
                seen.append(word)
    for row in rows:
        row["scope"] = " ".join(live.get(row["family_id"], []))
    return rows
