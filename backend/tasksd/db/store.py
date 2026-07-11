"""SQLite access layer — raw sqlite3, no ORM (the schema is small; the queries
are the interesting part). All timestamps are ISO-8601 UTC strings.

The cache functions are written so that starting from an empty DB and replaying
a full resync reproduces identical rows (invariant #1). Sidecar functions treat
UID as the join key and never cascade-delete on item removal (invariant #4 + the
delete-and-recreate survival requirement).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..dav.client import CollectionInfo, Item
from ..ical.read import TaskFields

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


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
    return conn.execute("SELECT 1 FROM collections WHERE href=?", (href,)).fetchone() is not None


def get_collections(conn: sqlite3.Connection, *, include_deleted: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM collections"
    if not include_deleted:
        q += " WHERE deleted=0"
    # Manual order (calendar-order) first; unordered collections trail, by name.
    return list(conn.execute(q + " ORDER BY ord IS NULL, ord, displayname"))


def mark_collection_deleted(conn: sqlite3.Connection, href: str) -> None:
    conn.execute("UPDATE collections SET deleted=1 WHERE href=?", (href,))


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

def upsert_item(
    conn: sqlite3.Connection, collection_href: str, item: Item, fields: TaskFields
) -> None:
    """Insert/replace the cache row for a resource, keyed on (collection, UID).
    A returning UID (delete-and-recreate) updates the same row and naturally
    rejoins its sidecar. Also refreshes categories + FTS. If the UID had a live
    sidecar orphan mark, clear it — it's back."""
    conn.execute(
        """INSERT INTO items (collection_href, uid, href, etag, raw_ics, component, summary,
             description, status, priority, percent_complete, completed, due,
             due_is_date, dtstart, dtstart_is_date, dtend, dtend_is_date, duration,
             related_parent, sequence, has_rrule, location, created, last_modified, synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
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
             has_rrule=excluded.has_rrule, location=excluded.location, created=excluded.created,
             last_modified=excluded.last_modified, synced_at=excluded.synced_at""",
        (
            collection_href, fields.uid, item.href, item.etag, item.data, fields.component,
            fields.summary, fields.description, fields.status, fields.priority,
            fields.percent_complete, fields.completed, fields.due,
            int(fields.due_is_date), fields.dtstart, int(fields.dtstart_is_date),
            fields.dtend, int(fields.dtend_is_date), fields.duration,
            fields.related_parent, fields.sequence, int(fields.has_rrule),
            fields.location, fields.created, fields.last_modified,
        ),
    )
    conn.execute(
        "DELETE FROM categories WHERE collection_href=? AND uid=?", (collection_href, fields.uid)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO categories (collection_href, uid, category) VALUES (?,?,?)",
        [(collection_href, fields.uid, c) for c in fields.categories],
    )
    _fts_replace(conn, collection_href, fields)
    # The UID is present on the wire again; if it was an orphan, un-orphan it.
    conn.execute(
        "UPDATE sidecar SET orphaned_at=NULL WHERE collection_href=? AND uid=? AND orphaned_at IS NOT NULL",
        (collection_href, fields.uid),
    )


def _fts_replace(conn: sqlite3.Connection, collection_href: str, f: TaskFields) -> None:
    conn.execute(
        "DELETE FROM items_fts WHERE collection_href=? AND uid=?", (collection_href, f.uid)
    )
    conn.execute(
        "INSERT INTO items_fts (uid, collection_href, summary, description, categories) "
        "VALUES (?,?,?,?,?)",
        (f.uid, collection_href, f.summary or "", f.description or "", " ".join(f.categories)),
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
    conn.execute("DELETE FROM items WHERE collection_href=? AND uid=?", (collection_href, uid))
    conn.execute("DELETE FROM items_fts WHERE collection_href=? AND uid=?", (collection_href, uid))
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


def gc_orphans(conn: sqlite3.Connection, *, keep_days: int = 7) -> int:
    """Drop sidecar rows orphaned longer than keep_days. Returns the count."""
    cur = conn.execute(
        "DELETE FROM sidecar WHERE orphaned_at IS NOT NULL "
        "AND orphaned_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)",
        (f"-{int(keep_days)} days",),
    )
    return cur.rowcount


def get_sidecar(conn: sqlite3.Connection, collection_href: str, uid: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sidecar WHERE collection_href=? AND uid=?", (collection_href, uid)
    ).fetchone()


def set_sidecar(conn: sqlite3.Connection, collection_href: str, uid: str, **fields: object) -> None:
    allowed = {"kanban_column", "sort_order", "pinned", "estimated_minutes", "repeat_from_completion"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown sidecar fields: {bad}")
    conn.execute(
        "INSERT OR IGNORE INTO sidecar (collection_href, uid) VALUES (?, ?)",
        (collection_href, uid),
    )
    for k, v in fields.items():
        conn.execute(
            f"UPDATE sidecar SET {k}=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE collection_href=? AND uid=?",
            (v, collection_href, uid),
        )


# ── search / queries ─────────────────────────────────────────────────────────

def search(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """FTS across summary/description/categories, joined back to live items."""
    return list(
        conn.execute(
            """SELECT i.* FROM items_fts f
               JOIN items i ON i.collection_href=f.collection_href AND i.uid=f.uid
               WHERE items_fts MATCH ? ORDER BY rank""",
            (query,),
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
    is dropped downstream. ISO strings order correctly on the leading date."""
    return list(
        conn.execute(
            "SELECT * FROM items WHERE collection_href=? AND component='VEVENT' "
            "AND dtstart <= ? AND (has_rrule=1 OR COALESCE(dtend, dtstart) >= ?) "
            "ORDER BY dtstart",
            (collection_href, end_iso, start_iso),
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


def count_items(conn: sqlite3.Connection, collection_href: str | None = None) -> int:
    if collection_href is None:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM items WHERE collection_href=?", (collection_href,)
    ).fetchone()[0]
