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
