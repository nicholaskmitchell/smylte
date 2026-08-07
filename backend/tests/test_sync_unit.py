"""Sync-engine unit tests with a stubbed DAV client — no Radicale required.

Integration coverage lives in test_sync.py; these cover failure paths that are
hard to provoke through a real server (e.g. malformed foreign resources).
"""
from __future__ import annotations

from tasksd.dav.client import CollectionInfo, Item, SyncResult
from tasksd.db import store
from tasksd.sync import SyncEngine

COL = "/u/cal/"


class _FakeDav:
    """Just enough of DavClient for the read path: one static collection state."""

    def __init__(self, items: list[Item]):
        self.items = items

    def sync_collection(self, href: str, token: str | None) -> SyncResult:
        return SyncResult(
            token="tok-1",
            changed=[Item(i.href, i.etag) for i in self.items],
            removed=[],
        )

    def multiget(self, href: str, hrefs: list[str]) -> list[Item]:
        return [i for i in self.items if i.href in hrefs]


def _db():
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.upsert_collection(
        conn, CollectionInfo(href=COL, displayname="Cal", components={"VTODO"})
    )
    return conn


def _vtodo(uid: str, summary: str) -> bytes:
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
        f"BEGIN:VTODO\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n"
        f"END:VTODO\r\nEND:VCALENDAR\r\n"
    ).encode()


def test_malformed_resource_is_skipped_not_wedging_sync():
    """One poison resource must not roll back the pass or freeze the token:
    the rest of the collection still caches, the token advances, and the
    failure is recorded in sync_state.last_error."""
    conn = _db()
    items = [
        Item(f"{COL}good.ics", '"e1"', _vtodo("good-1", "Fine")),
        Item(f"{COL}bad.ics", '"e2"', b"this is not an icalendar resource"),
        # Field-level garbage a foreign client can produce: parses as a
        # calendar but a cached column blows up during extraction.
        Item(f"{COL}ugly.ics", '"e3"',
             b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//x//EN\r\n"
             b"BEGIN:VTODO\r\nUID:ugly-1\r\nPRIORITY:HIGH\r\n"
             b"END:VTODO\r\nEND:VCALENDAR\r\n"),
        Item(f"{COL}good2.ics", '"e4"', _vtodo("good-2", "Also fine")),
    ]
    engine = SyncEngine(_FakeDav(items), conn)

    stats = engine.sync(COL)   # no token yet → full resync path

    assert stats.upserted == 2 and stats.skipped == 2
    assert store.get_item(conn, COL, "good-1") is not None
    assert store.get_item(conn, COL, "good-2") is not None
    assert store.get_sync_token(conn, COL) == "tok-1"
    err = conn.execute(
        "SELECT last_error FROM sync_state WHERE collection_href=?", (COL,)
    ).fetchone()["last_error"]
    assert ".ics" in err

    # The incremental path takes the same guard.
    stats2 = engine.sync(COL)
    assert stats2.full_resync is False and stats2.skipped == 2

    # A clean pass clears the recorded error.
    engine.dav = _FakeDav([Item(f"{COL}good.ics", '"e1"', _vtodo("good-1", "Fine"))])
    engine.sync(COL)
    err = conn.execute(
        "SELECT last_error FROM sync_state WHERE collection_href=?", (COL,)
    ).fetchone()["last_error"]
    assert err is None


_POISON = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//x//EN\r\n"
           b"BEGIN:VTODO\r\nUID:u-1\r\nPRIORITY:HIGH\r\n"
           b"END:VTODO\r\nEND:VCALENDAR\r\n")


def test_resync_keeps_a_recreated_item_whose_new_body_is_malformed():
    """full_resync sweeps cached hrefs absent from the wire, on the assumption
    that a delete-and-recreated UID already moved to its new href. That only
    holds if the move landed: a body we cannot extract leaves the row at the OLD
    href, so sweeping on href alone deleted a UID that is alive on the server —
    and orphaned the sidecar, which no resync can rebuild."""
    conn = _db()
    engine = SyncEngine(_FakeDav([Item(f"{COL}A.ics", '"e1"', _vtodo("u-1", "Ship it"))]), conn)
    engine.sync(COL)
    store.set_sidecar(conn, COL, "u-1", kanban_column="doing", sort_order=2.5)

    # Another client delete-and-recreates u-1 at a new href, with a poison body.
    engine2 = SyncEngine(_FakeDav([Item(f"{COL}B.ics", '"e2"', _POISON)]), conn)
    stats = engine2.full_resync(COL)

    assert stats.skipped == 1
    assert stats.removed == 0, "a live item was swept out of the cache"
    assert store.get_item(conn, COL, "u-1") is not None
    sidecar = store.get_sidecar(conn, COL, "u-1")
    assert sidecar is not None and sidecar["orphaned_at"] is None


def test_resync_does_not_gc_sidecars_off_an_incomplete_pass():
    """gc_orphans is the only permanent deletion of state nothing can rebuild,
    so it must not run on a pass that skipped resources."""
    conn = _db()
    engine = SyncEngine(_FakeDav([Item(f"{COL}A.ics", '"e1"', _vtodo("gone-1", "Old"))]), conn)
    engine.sync(COL)
    store.set_sidecar(conn, COL, "gone-1", kanban_column="doing")

    # gone-1 really is deleted, and a *different* resource is malformed.
    engine2 = SyncEngine(_FakeDav([Item(f"{COL}B.ics", '"e2"', _POISON)]), conn)
    engine2.full_resync(COL)
    conn.execute("UPDATE sidecar SET orphaned_at = orphaned_at - 8*86400 WHERE uid='gone-1'")
    conn.commit()
    engine2.full_resync(COL)

    assert conn.execute("SELECT 1 FROM sidecar WHERE uid='gone-1'").fetchone() is not None

    # Once the collection reads cleanly, the orphan ages out as before.
    engine3 = SyncEngine(_FakeDav([]), conn)
    engine3.full_resync(COL)
    assert conn.execute("SELECT 1 FROM sidecar WHERE uid='gone-1'").fetchone() is None


def test_a_collection_that_comes_back_rebuilds_its_items():
    """Deleting a collection purges its cached rows, so the token it was synced
    to must go with them: `upsert_collection` clears `deleted` when the
    collection returns but leaves sync_state alone, and an incremental resume
    from the old token reports no changes — the list would come back
    permanently empty."""
    conn = _db()
    items = [Item(f"{COL}A.ics", '"e1"', _vtodo("u-1", "Ship it"))]
    engine = SyncEngine(_FakeDav(items), conn)
    engine.sync(COL)
    store.set_sidecar(conn, COL, "u-1", kanban_column="doing")

    # The collection disappears from the server, then comes back with the same
    # contents (a restore, or a transient discovery blip).
    store.mark_collection_deleted(conn, COL)
    assert store.get_item(conn, COL, "u-1") is None
    assert store.get_sidecar(conn, COL, "u-1")["orphaned_at"] is not None
    store.upsert_collection(
        conn, CollectionInfo(href=COL, displayname="Cal", components={"VTODO"}))

    stats = engine.sync(COL)
    assert stats.full_resync is True, "resumed incrementally from a stale token"
    assert store.get_item(conn, COL, "u-1")["summary"] == "Ship it"
    # The purge orphaned the sidecar rather than dropping it, so the returning
    # UID rejoins its kanban column instead of losing it.
    side = store.get_sidecar(conn, COL, "u-1")
    assert side["kanban_column"] == "doing" and side["orphaned_at"] is None
