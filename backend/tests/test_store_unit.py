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
