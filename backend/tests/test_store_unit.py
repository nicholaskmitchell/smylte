"""Cache-layer unit tests — pure sqlite via the `db` fixture, no Radicale.

Covers the two places the cache could diverge from the wire with no way back:
purging a deleted collection's projection, and the FTS query escaping.
"""
from __future__ import annotations

import pytest

from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import extract_from_raw

COL_A, COL_B = "/u/secret/", "/u/keep/"


def _vtodo(uid: str, summary: str, *, category: str | None = None) -> bytes:
    cat = f"CATEGORIES:{category}\r\n" if category else ""
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//x//EN\r\n"
        f"BEGIN:VTODO\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n{cat}"
        f"END:VTODO\r\nEND:VCALENDAR\r\n"
    ).encode()


def _seed(conn, col: str, uid: str, summary: str, category: str | None = None) -> None:
    raw = _vtodo(uid, summary, category=category)
    store.upsert_item(conn, col, Item(f"{col}{uid}.ics", '"1"', raw), extract_from_raw(raw))


@pytest.fixture
def seeded(db):
    """Two live collections, each with one tagged task and a sidecar row."""
    for href, name in ((COL_A, "Secret"), (COL_B, "Keep")):
        store.upsert_collection(
            db, CollectionInfo(href=href, displayname=name, components={"VTODO"}))
        store.set_sync_token(db, href, f"tok-{name}")
    _seed(db, COL_A, "a1@x", "confidential thing", "secrettag")
    _seed(db, COL_B, "b1@x", "confidential elsewhere", "keeptag")
    store.set_sidecar(db, COL_A, "a1@x", kanban_column="doing", pinned=1)
    store.set_sidecar(db, COL_B, "b1@x", kanban_column="doing")
    return db


# ── a deleted collection must stop being queryable ───────────────────────────
# The collections row is only soft-deleted, so the ON DELETE CASCADE from items
# never fires. Without an explicit purge a deleted list's tasks stayed in
# /api/search and their tags in /api/tags forever — carrying a list id that no
# longer resolves — and their raw_ics bodies stayed on disk for the life of the DB.

def test_deleting_a_collection_purges_its_cached_rows(seeded):
    store.mark_collection_deleted(seeded, COL_A)

    assert [r["href"] for r in store.get_collections(seeded)] == [COL_B]
    assert store.get_item(seeded, COL_A, "a1@x") is None
    assert store.count_items(seeded, COL_A) == 0
    assert seeded.execute(
        "SELECT COUNT(*) FROM categories WHERE collection_href=?", (COL_A,)
    ).fetchone()[0] == 0
    assert seeded.execute(
        "SELECT COUNT(*) FROM items_fts WHERE collection_href=?", (COL_A,)
    ).fetchone()[0] == 0


def test_a_deleted_collection_leaves_search_and_tags(seeded):
    store.mark_collection_deleted(seeded, COL_A)

    # The surviving list's own match still comes back — the purge is scoped.
    assert [r["uid"] for r in store.search(seeded, "confidential")] == ["b1@x"]
    assert store.distinct_categories(seeded) == ["keeptag"]


def test_deleting_a_collection_orphans_its_sidecar_rather_than_dropping_it(seeded):
    store.mark_collection_deleted(seeded, COL_A)

    # Sidecar is the one thing a resync cannot rebuild, so it gets the same
    # 7-day grace as any other orphan instead of going with the items.
    side = store.get_sidecar(seeded, COL_A, "a1@x")
    assert side is not None and side["orphaned_at"] is not None
    assert side["kanban_column"] == "doing" and side["pinned"] == 1
    # The live collection's sidecar is untouched.
    assert store.get_sidecar(seeded, COL_B, "b1@x")["orphaned_at"] is None


def test_deleting_a_collection_clears_its_sync_token(seeded):
    # Without this the collection would come back permanently empty: returning
    # clears `deleted` but leaves sync_state, so the next sync would resume
    # incrementally from a token whose changes we just purged.
    store.mark_collection_deleted(seeded, COL_A)
    assert store.get_sync_token(seeded, COL_A) is None
    assert store.get_sync_token(seeded, COL_B) == "tok-Keep"


def test_deleting_a_collection_leaves_the_others_alone(seeded):
    store.mark_collection_deleted(seeded, COL_A)
    assert store.get_item(seeded, COL_B, "b1@x") is not None
    assert store.count_items(seeded) == 1


# ── FTS query escaping ───────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "\x00", "\x00hi", "hi\x00there", "hi\x00", "\x00\x00\x00",
    "tab\there", "bell\x07x", "\x7f", "ok\x1fnope",
])
def test_control_bytes_in_a_query_do_not_crash(seeded, q):
    """Quoting each term guards the FTS5 operators, but a NUL truncates the C
    string FTS5 parses — the closing quote was never seen and the query raised
    OperationalError, surfacing as a 500 on `?q=%00`."""
    assert isinstance(store.search(seeded, q), list)


def test_a_query_of_only_control_bytes_finds_nothing(seeded):
    assert store.search(seeded, "\x00\x01\x02") == []


def test_stripping_control_bytes_keeps_the_rest_of_the_term_searchable(seeded):
    # The bytes are dropped, not the term: "confid\x00ential" still matches.
    assert [r["uid"] for r in store.search(seeded, "confid\x00ential")] == ["a1@x", "b1@x"]


# ── one cache row per href ───────────────────────────────────────────────────

def test_a_href_that_starts_carrying_a_new_uid_leaves_no_ghost_row(db):
    """Rows are keyed on UID, but a resource is addressed by href. When a href
    starts carrying a different UID — a foreign client rewriting the body in
    place, or a restored .ics landing at an existing path — the old UID's row
    used to survive at that same href, and nothing could reach it: the resync
    sweep iterates `href_uid_map`, a dict keyed on href, so one of the two rows
    is invisible to it, and the href is still on the wire so it is never swept.
    Worse, `get_item(old_uid)` kept handing out the *live* resource's href, so
    deleting the ghost deleted the live resource off the server."""
    store.upsert_collection(
        db, CollectionInfo(href=COL_A, displayname="C", components={"VTODO"}))
    href = f"{COL_A}resource.ics"
    for uid, etag in (("UID-A", '"v1"'), ("UID-B", '"v2"')):
        raw = _vtodo(uid, uid)
        store.upsert_item(db, COL_A, Item(href, etag, raw), extract_from_raw(raw))

    rows = db.execute(
        "SELECT uid FROM items WHERE collection_href=? AND href=?", (COL_A, href)
    ).fetchall()
    assert [r["uid"] for r in rows] == ["UID-B"], "one row per href"
    assert store.get_item(db, COL_A, "UID-A") is None, "the ghost must not resolve"
    # href_uid_map is the sweep's view; it must agree with the table.
    assert store.href_uid_map(db, COL_A) == {href: "UID-B"}


def test_evicting_a_ghost_uid_also_clears_its_derived_rows(db):
    """The eviction has to take the UID's FTS and category rows with it, or a
    search keeps returning a task that no longer exists anywhere."""
    store.upsert_collection(
        db, CollectionInfo(href=COL_A, displayname="C", components={"VTODO"}))
    href = f"{COL_A}resource.ics"
    raw_a = _vtodo("UID-A", "findmeplease", category="alpha")
    store.upsert_item(db, COL_A, Item(href, '"v1"', raw_a), extract_from_raw(raw_a))
    assert [r["uid"] for r in store.search(db, "findmeplease")] == ["UID-A"]

    raw_b = _vtodo("UID-B", "somethingelse")
    store.upsert_item(db, COL_A, Item(href, '"v2"', raw_b), extract_from_raw(raw_b))

    assert store.search(db, "findmeplease") == []
    assert db.execute(
        "SELECT COUNT(*) c FROM categories WHERE collection_href=? AND uid=?", (COL_A, "UID-A")
    ).fetchone()["c"] == 0


def test_a_duration_only_event_is_visible_in_windows_after_its_start_day(db):
    """A VEVENT whose length is a DURATION has dtend NULL, so the old
    COALESCE(dtend, dtstart) upper bound collapsed its end onto its start and hid
    it from every window that did not contain its first day. That row feeds
    `_link_busy`, which widens the query by only +/-1 day, so a multi-day block
    written by a phone client stopped blocking booking slots on its later days —
    an anonymous visitor could book straight over the owner's calendar."""
    store.upsert_collection(
        db, CollectionInfo(href=COL_A, displayname="C", components={"VEVENT"}))

    def _vevent(uid: str, tail: str) -> bytes:
        return (
            f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\n"
            f"SUMMARY:{uid}\r\nDTSTART:20260710T100000\r\n{tail}\r\n"
            f"END:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()

    for uid, tail in (("dur", "DURATION:P3D"), ("dtend", "DTEND:20260713T100000")):
        raw = _vevent(uid, tail)
        store.upsert_item(db, COL_A, Item(f"{COL_A}{uid}.ics", '"1"', raw),
                          extract_from_raw(raw))

    # A window over the block's *second* day contains neither event's DTSTART.
    found = store.get_events_in_range(db, COL_A, "2026-07-12T00:00:00", "2026-07-13T00:00:00")
    assert sorted(r["uid"] for r in found) == ["dtend", "dur"], \
        "the DURATION-only block must be a booking-conflict candidate like its DTEND twin"
