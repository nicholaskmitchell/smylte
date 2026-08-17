"""Sync-engine unit tests with a stubbed DAV client — no Radicale required.

Integration coverage lives in test_sync.py; these cover failure paths that are
hard to provoke through a real server (e.g. malformed foreign resources).
"""
from __future__ import annotations

from datetime import date

import pytest
from helpers import foreign_event_raw

from tasksd import ical
from tasksd.dav.client import CollectionInfo, Item, SyncResult
from tasksd.db import store
from tasksd.sync import SyncEngine
from tasksd.sync.engine import ConflictError

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
    # Backdate as a real ISO string. `orphaned_at - 8*86400` coerced the string
    # to a number and left '-689174' in the column, which reads as older only
    # because SQLite sorts INTEGER below TEXT — so the date comparison this is
    # meant to drive was never actually performed.
    conn.execute(
        "UPDATE sidecar SET orphaned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','-8 days') "
        "WHERE uid='gone-1'")
    conn.commit()
    engine2.full_resync(COL)

    assert conn.execute("SELECT 1 FROM sidecar WHERE uid='gone-1'").fetchone() is not None

    # Once the collection reads cleanly, the orphan ages out as before.
    engine3 = SyncEngine(_FakeDav([]), conn)
    engine3.full_resync(COL)
    assert conn.execute("SELECT 1 FROM sidecar WHERE uid='gone-1'").fetchone() is None


def test_one_clean_collection_does_not_gc_another_collections_protected_orphans():
    """The guard above is per-collection; the sweep it gated was global.

    So a collection whose enumeration is permanently incomplete — a resource
    `extract_from_raw` cannot handle — correctly never GC'd its own orphans, and
    then lost them anyway the first time an unrelated calendar full-resynced.
    The state destroyed is the one thing in the DB no resync can rebuild."""
    other = "/u/other/"
    conn = _db()
    store.upsert_collection(
        conn, CollectionInfo(href=other, displayname="Other", components={"VTODO"})
    )

    # A sidecar row in COL, orphaned and long overdue for collection…
    SyncEngine(_FakeDav([Item(f"{COL}A.ics", '"e1"', _vtodo("gone-1", "Old"))]), conn).sync(COL)
    store.set_sidecar(conn, COL, "gone-1", kanban_column="doing")
    SyncEngine(_FakeDav([Item(f"{COL}B.ics", '"e2"', _POISON)]), conn).full_resync(COL)
    conn.execute(
        "UPDATE sidecar SET orphaned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','-8 days') "
        "WHERE uid='gone-1'")
    conn.commit()

    # …but COL cannot be enumerated cleanly, so it is protected. Now resync a
    # different, perfectly healthy collection.
    SyncEngine(_FakeDav([Item(f"{other}C.ics", '"e3"', _vtodo("live-1", "Fine"))]), conn) \
        .full_resync(other)

    assert conn.execute("SELECT 1 FROM sidecar WHERE uid='gone-1'").fetchone() is not None, \
        "another collection's clean pass swept a protected orphan"


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


# ── a body that stops being readable must not leave a ghost row ──────────────
# A resource that is already cached and is then rewritten *in place* into
# something we cannot extract used to leave its row wholly untouched: old
# summary, old raw_ics, old etag. Its href is still on the wire, so the resync
# sweep never removed it either — permanent divergence, and the stale etag made
# every write on it fail with an opaque 500.

_VJOURNAL = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//jtx//EN\r\n"
             b"BEGIN:VJOURNAL\r\nUID:u-1\r\nSUMMARY:a note\r\n"
             b"END:VJOURNAL\r\nEND:VCALENDAR\r\n")


def _cached_then_rewritten(new_body: bytes):
    """Cache one VTODO with a sidecar, then rewrite it at the SAME href."""
    conn = _db()
    engine = SyncEngine(_FakeDav([Item(f"{COL}x.ics", '"e1"', _vtodo("u-1", "Pay rent"))]), conn)
    engine.sync(COL)
    store.set_sidecar(conn, COL, "u-1", kanban_column="doing", pinned=1)
    engine.dav = _FakeDav([Item(f"{COL}x.ics", '"e2"', new_body)])
    return conn, engine


@pytest.mark.parametrize("body, label", [
    (_VJOURNAL, "no longer a task"),
    (b"this is not an icalendar resource at all", "unparseable"),
])
def test_a_body_that_stops_being_readable_drops_its_cache_row(body, label):
    conn, engine = _cached_then_rewritten(body)

    engine.sync(COL)

    assert store.get_item(conn, COL, "u-1") is None, f"ghost row survived ({label})"
    # The sidecar is orphaned, not dropped: nothing can rebuild it, and the UID
    # may come back within the 7-day grace.
    side = store.get_sidecar(conn, COL, "u-1")
    assert side is not None and side["orphaned_at"] is not None
    assert side["kanban_column"] == "doing" and side["pinned"] == 1


def test_dropping_a_ghost_row_leaves_the_next_resync_stable():
    # Before, every full resync re-fetched (etag mismatch) and re-skipped
    # forever, and the row never went.
    conn, engine = _cached_then_rewritten(_VJOURNAL)
    engine.sync(COL)

    stats = engine.full_resync(COL)
    assert (stats.upserted, stats.removed, stats.skipped) == (0, 0, 0)
    assert store.get_item(conn, COL, "u-1") is None


def test_a_resource_that_is_not_a_task_does_not_block_the_orphan_gc():
    """`fields is None` is a complete, understood enumeration — this simply is
    not a task any more — so it must not set `skipped`, which exists to stop
    gc_orphans running off a pass that failed to read something."""
    conn, engine = _cached_then_rewritten(_VJOURNAL)
    stats = engine.full_resync(COL)
    assert stats.skipped == 0 and stats.removed == 1


def test_an_unreadable_body_still_blocks_the_orphan_gc():
    # The parse-error path is a genuinely incomplete read, so it keeps counting.
    conn, engine = _cached_then_rewritten(b"not an icalendar resource")
    assert engine.full_resync(COL).skipped == 1


def test_editing_a_resource_with_nothing_to_edit_is_a_conflict_not_a_500():
    """Reachable in the race where the body is rewritten between our sync and
    our write: the 412 merge path re-GETs and re-applies onto a body that has no
    component left. The ValueError had no handler and escaped as a 500."""
    conn = _db()
    store.upsert_item(
        conn, COL, Item(f"{COL}x.ics", '"e1"', _VJOURNAL),
        # Seed the row directly: the sync path would (correctly) refuse to cache
        # this body at all, and the point is what `_edit` does when it meets one.
        ical.extract_from_raw(_vtodo("u-1", "Pay rent")),
    )
    engine = SyncEngine(_FakeDav([]), conn)
    with pytest.raises(ConflictError):
        engine.edit_task(COL, "u-1", ical.TaskEdit(status="COMPLETED"))


def test_a_bad_request_on_a_readable_resource_is_still_a_ValueError():
    """Only "nothing here to edit" becomes a conflict. A series shift that would
    switch all-day <-> timed is about the *request*, and the API answers it 422."""
    raw = foreign_event_raw("e-1", "Standup", rrule="FREQ=WEEKLY")
    with pytest.raises(ValueError) as exc:
        ical.shift_series(raw, "2026-01-06T09:00:00+00:00",
                          ical.EventEdit(dtstart=date(2026, 1, 7)))
    assert not isinstance(exc.value, ical.NotEditable)


# ── gc_orphans: the only irreversible deletion in the cache layer ────────────
# It permanently drops sidecar rows — pins, kanban column, manual sort,
# estimated minutes — none of which a resync can rebuild, and nothing called it.

def _orphan_aged(conn, uid: str, days: int) -> None:
    """Orphan `uid` and backdate it by `days`, as a real ISO string.

    Deliberately not `orphaned_at - N*86400`: SQLite coerces the ISO string to a
    number, leaving something like '-689174' in the column. That compares older
    than any timestamp only because INTEGER sorts below TEXT, so the ISO
    comparison gc_orphans actually performs is never exercised — which is the
    exact format drift the retention test needs to be able to catch."""
    store.set_sidecar(conn, COL, uid, kanban_column="doing")
    conn.execute(
        "UPDATE sidecar SET orphaned_at=strftime('%Y-%m-%dT%H:%M:%fZ','now',?) "
        "WHERE collection_href=? AND uid=?",
        (f"-{days} days", COL, uid),
    )


def _sidecar_uids(conn) -> list[str]:
    return sorted(r["uid"] for r in conn.execute("SELECT uid FROM sidecar"))


def test_gc_orphans_deletes_only_past_the_retention_window():
    conn = _db()
    _orphan_aged(conn, "old-1", 8)          # past the 7-day window
    _orphan_aged(conn, "recent-1", 6)       # inside it

    assert store.gc_orphans(conn) == 1
    assert _sidecar_uids(conn) == ["recent-1"]


def test_gc_orphans_honours_a_custom_retention_window():
    conn = _db()
    _orphan_aged(conn, "old-1", 8)
    _orphan_aged(conn, "recent-1", 6)

    assert store.gc_orphans(conn, keep_days=3) == 2
    assert _sidecar_uids(conn) == []


def test_gc_orphans_never_touches_a_live_row():
    conn = _db()
    store.set_sidecar(conn, COL, "live-1", kanban_column="doing", pinned=1)
    conn.execute(
        "UPDATE sidecar SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','-400 days')")

    assert store.gc_orphans(conn) == 0
    assert _sidecar_uids(conn) == ["live-1"]


def test_a_uid_that_came_back_is_spared_by_the_gc():
    """`upsert_item` clears `orphaned_at` when a UID reappears. Without that the
    row would still be swept on its original clock, silently losing kanban/sort
    state for an item that is alive — the half of the contract
    test_delete_and_recreate_same_uid_keeps_sidecar does not assert."""
    conn = _db()
    _orphan_aged(conn, "u-1", 8)

    engine = SyncEngine(_FakeDav([Item(f"{COL}A.ics", '"e1"', _vtodo("u-1", "Back"))]), conn)
    engine.sync(COL)

    assert store.get_sidecar(conn, COL, "u-1")["orphaned_at"] is None
    assert store.gc_orphans(conn) == 0
    assert _sidecar_uids(conn) == ["u-1"]


# ── discovery tolerates an unusable collection property ─────────────────────
# `calendar-order` is an Apple dead property any sharing CalDAV client can
# PROPPATCH, and it is read straight off the wire. Python ints are unbounded but
# SQLite's INTEGER is not, so a large one raised OverflowError at bind time —
# not a ValueError, so nothing caught it. discover() upserts every collection in
# ONE transaction, so a single poisoned collection rolled back the enumeration
# of all of them, on every retry (the value lives on the server) and at every
# restart, taking bootstrap() and therefore startup with it.

class _DiscoveryDav:
    def __init__(self, cols: list[CollectionInfo]):
        self.cols = cols

    def list_collections(self) -> list[CollectionInfo]:
        return self.cols


HUGE_ORDER = 10 ** 25          # past 2**63-1; any value out of range does it


def test_an_unparseable_calendar_order_is_dropped_at_the_parser():
    """The wire value is clamped where it enters, so it never reaches the bind."""
    import types

    from tasksd.dav.client import DavClient

    wire = b"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"
               xmlns:A="http://apple.com/ns/ical/">
  <D:response><D:href>/u/shared/</D:href><D:propstat><D:prop>
    <D:displayname>Shared</D:displayname>
    <D:resourcetype><D:collection/><C:calendar/></D:resourcetype>
    <C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
    <A:calendar-order>99999999999999999999999</A:calendar-order>
  </D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
</D:multistatus>"""

    c = DavClient.__new__(DavClient)
    type(c).principal_path = property(lambda self: "/u/")
    c._request = lambda *a, **kw: types.SimpleNamespace(
        content=wire, status_code=207, headers={})

    (info,) = c.list_collections()
    assert info.order is None, f"out-of-range order survived the parser: {info.order}"


def test_one_uncacheable_collection_does_not_abort_discovery():
    """Defence in depth for any other unusable property: the healthy collection
    must still be cached, discovery must not raise, and the poisoned one must
    NOT be marked deleted — the server says it exists, and marking it deleted
    would discard sidecar state that is not derivable from anywhere."""
    conn = store.connect(":memory:")
    store.init_db(conn)

    engine = SyncEngine(_DiscoveryDav([
        CollectionInfo(href="/u/work/", displayname="Work", components={"VTODO"}, order=0),
        CollectionInfo(href="/u/poison/", displayname="Bad", components={"VTODO"},
                       order=HUGE_ORDER),
    ]), conn)

    kept = engine.discover()                      # must not raise
    assert [c.href for c in kept] == ["/u/work/"]

    rows = {r["href"]: r for r in store.get_collections(conn)}
    assert "/u/work/" in rows, "a healthy collection was rolled back with the bad one"
    assert not any(r["deleted"] for r in rows.values())

    # Deterministic: the property lives on the server, so it recurs every pass.
    assert [c.href for c in engine.discover()] == ["/u/work/"]


# ── a collection appearing or leaving has to reach the SPA ──────────────────

def test_discover_reports_whether_the_collection_set_moved():
    """`sync_all` publishes on this. Collection-set changes are found by
    discover(), never by the per-collection item counters, and discover()'s
    result was thrown away — so a list the owner deleted on their phone was
    correctly purged from the projection while the open tab kept rendering it
    in the sidebar, until some unrelated write happened to bump `rev`. Clicking
    it 404'd. A new *empty* collection was equally invisible."""
    conn = _db()
    a = CollectionInfo(href="/u/a/", displayname="A", components={"VTODO"})
    b = CollectionInfo(href="/u/b/", displayname="B", components={"VTODO"})

    engine = SyncEngine(_DiscoveryDav([a]), conn)
    engine.discover()
    assert engine.last_discovery_changed is True          # /u/a/ arrived

    engine.discover()
    assert engine.last_discovery_changed is False         # nothing moved

    # A brand-new, still-empty collection counts.
    engine.dav = _DiscoveryDav([a, b])
    engine.discover()
    assert engine.last_discovery_changed is True

    # And one that vanished.
    engine.dav = _DiscoveryDav([a])
    engine.discover()
    assert engine.last_discovery_changed is True

    engine.discover()
    assert engine.last_discovery_changed is False
