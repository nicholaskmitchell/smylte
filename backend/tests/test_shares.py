"""Shares: read-only views of chosen lists and calendars, for a person.

This file starts at the storage layer, which is where the properties the rest of
the feature leans on are decided: an allowlist column that reads as NOTHING when
it cannot be read, a token column that cannot hold a short credential, a prune
that rides on the caller's transaction, and a task reader that answers exactly
as `list_tasks` would without loading what `list_tasks` loads.

Nothing here touches Radicale. A share is app-only state over the cache, so the
store is driven directly and `items` is seeded the way test_day_plan seeds it.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from helpers import foreign_raw
from test_day_plan import LIST_A, LIST_B, _seed_task, _settings
from test_displays import CAL_A, _seed_event

from smylted.dav.client import CollectionInfo
from smylted.db import store
from smylted.service import SmylteService

TOKEN = "t" * 43


@pytest.fixture
def svc():
    s = SmylteService(_settings())
    for href, name in ((LIST_A, "Work"), (LIST_B, "Home")):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components={"VTODO"}))
    store.upsert_collection(
        s._conn, CollectionInfo(href=CAL_A, displayname="Personal", components={"VEVENT"}))
    yield s
    s.close()


def _share(conn, share_id: str = "s1", token: str = TOKEN, **fields) -> sqlite3.Row:
    return store.create_share(conn, share_id, token, {"name": "Sam", **fields})


# ── fields and the token column ─────────────────────────────────────────────

def test_store_refuses_unknown_share_fields(svc):
    with pytest.raises(ValueError, match="unknown share fields"):
        store.create_share(svc._conn, "s1", TOKEN, {"name": "Sam", "token": "x" * 43})
    row = _share(svc._conn)
    with pytest.raises(ValueError, match="unknown share fields"):
        store.update_share(svc._conn, row["id"], {"id": "other"})
    with pytest.raises(ValueError, match="unknown share fields"):
        store.update_share(svc._conn, row["id"], {"last_seen_at": "2026-01-01"})
    # Refused before anything was written.
    assert store.get_share(svc._conn, "s1")["id"] == "s1"
    assert store.get_share(svc._conn, "other") is None


def test_the_service_owned_columns_are_accepted(svc):
    row = _share(svc._conn, horizon_days=14, cv="gen-1")
    assert row["horizon_days"] == 14 and row["cv"] == "gen-1"
    again = store.update_share(svc._conn, "s1", {"cv": "gen-2", "horizon_days": 28})
    assert again["cv"] == "gen-2" and again["horizon_days"] == 28


def test_a_new_share_row_shares_nothing(svc):
    row = _share(svc._conn)
    assert store.share_id_list(row["lists"]) == []
    assert store.share_id_list(row["calendars"]) == []
    assert row["show_focus"] == 0 and row["enabled"] == 1
    assert row["horizon_days"] == 7 and row["cv"] == ""
    assert row["last_seen_at"] is None


def test_the_token_column_refuses_a_short_token(svc):
    for bad in ("a" * 42, "a" * 44, ""):
        with pytest.raises(sqlite3.IntegrityError):
            _share(svc._conn, share_id="short", token=bad)
    assert store.get_share(svc._conn, "short") is None
    # Rotation goes through the same column.
    _share(svc._conn)
    with pytest.raises(sqlite3.IntegrityError):
        store.rotate_share_token(svc._conn, "s1", "a" * 42)
    assert store.get_share(svc._conn, "s1")["token"] == TOKEN


def test_a_token_is_unique(svc):
    _share(svc._conn)
    with pytest.raises(sqlite3.IntegrityError):
        _share(svc._conn, share_id="s2")


def test_the_token_read_finds_only_the_current_token(svc):
    _share(svc._conn)
    assert store.get_share_by_token(svc._conn, TOKEN)["id"] == "s1"
    assert store.get_share_by_token(svc._conn, "u" * 43) is None
    new = "n" * 43
    assert store.rotate_share_token(svc._conn, "s1", new)["id"] == "s1"
    assert store.get_share_by_token(svc._conn, TOKEN) is None
    assert store.get_share_by_token(svc._conn, new)["id"] == "s1"
    assert store.rotate_share_token(svc._conn, "nope", "m" * 43) is None


def test_rotation_clears_last_seen_and_delete_reports_whether_it_deleted(svc):
    _share(svc._conn)
    store.touch_share(svc._conn, "s1", now="2026-08-21T10:00:00.000Z",
                      not_before="2026-08-21T09:59:00.000Z")
    assert store.get_share(svc._conn, "s1")["last_seen_at"] == "2026-08-21T10:00:00.000Z"
    assert store.rotate_share_token(svc._conn, "s1", "n" * 43)["last_seen_at"] is None
    assert store.delete_share(svc._conn, "s1") is True
    assert store.delete_share(svc._conn, "s1") is False
    assert store.list_shares(svc._conn) == []


def test_touch_share_is_throttled_by_the_callers_stamps(svc):
    _share(svc._conn)
    def stamp():
        return store.get_share(svc._conn, "s1")["last_seen_at"]

    store.touch_share(svc._conn, "s1", now="2026-08-21T10:00:00.000Z",
                      not_before="2026-08-21T09:59:00.000Z")
    # Thirty seconds on: inside the minute, so not rewritten.
    store.touch_share(svc._conn, "s1", now="2026-08-21T10:00:30.000Z",
                      not_before="2026-08-21T09:59:30.000Z")
    assert stamp() == "2026-08-21T10:00:00.000Z"
    store.touch_share(svc._conn, "s1", now="2026-08-21T10:01:01.000Z",
                      not_before="2026-08-21T10:00:01.000Z")
    assert stamp() == "2026-08-21T10:01:01.000Z"


# ── the allowlist columns ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ('["a", "b"]', ["a", "b"]),
    ('["a", "a", "b", "a"]', ["a", "b"]),
    ('[1, null, "a", ["x"], {"k": 1}]', ["a"]),
    ("[]", []),
    ("{}", []),
    ('"a"', []),
    ("null", []),
    ("not json", []),
    ("", []),
    (None, []),
    (b"\xff\xfe", []),
])
def test_an_unreadable_allowlist_is_the_empty_one(raw, expected):
    assert store.share_id_list(raw) == expected


# ── pruning a deleted collection ────────────────────────────────────────────

def test_prune_drops_the_slug_from_both_lists_and_only_changed_rows(svc):
    c = svc._conn
    _share(c, "s1", "a" * 43, lists=json.dumps(["work", "home"]),
           calendars=json.dumps(["cal-a"]))
    _share(c, "s2", "b" * 43, lists=json.dumps(["home"]), calendars=json.dumps(["work"]))
    _share(c, "s3", "c" * 43, lists=json.dumps(["home"]))
    before = store.get_share(c, "s3")
    c.execute("UPDATE shares SET updated_at='2000-01-01T00:00:00.000Z' WHERE id='s3'")

    assert store.prune_share_collection(c, "work") == 2

    s1, s2, s3 = (store.get_share(c, i) for i in ("s1", "s2", "s3"))
    assert store.share_id_list(s1["lists"]) == ["home"]
    assert store.share_id_list(s1["calendars"]) == ["cal-a"]
    assert store.share_id_list(s2["lists"]) == ["home"]
    assert store.share_id_list(s2["calendars"]) == []
    # Untouched: same lists, and not even its updated_at moved.
    assert s3["lists"] == before["lists"]
    assert s3["updated_at"] == "2000-01-01T00:00:00.000Z"
    assert store.prune_share_collection(c, "work") == 0
    assert store.prune_share_collection(c, "never-shared") == 0


def test_prune_does_not_commit(svc):
    c = svc._conn
    _share(c, lists=json.dumps(["work"]))
    c.execute("BEGIN IMMEDIATE")
    assert store.prune_share_collection(c, "work") == 1
    assert store.share_id_list(store.get_share(c, "s1")["lists"]) == []
    c.execute("ROLLBACK")
    # It rode on the caller's transaction, so the caller's rollback undid it.
    assert store.share_id_list(store.get_share(c, "s1")["lists"]) == ["work"]


def test_prune_is_unreadable_safe(svc):
    c = svc._conn
    _share(c)
    c.execute("UPDATE shares SET lists='not json', calendars='{}'")
    assert store.prune_share_collection(c, "work") == 0


def test_deleting_a_collection_prunes_it_from_shares_in_the_same_transaction(svc):
    c = svc._conn
    _share(c, lists=json.dumps(["work", "home"]))
    store.mark_collection_deleted(c, LIST_A)
    assert store.share_id_list(store.get_share(c, "s1")["lists"]) == ["home"]

    # And it is part of the caller's transaction, not a commit of its own.
    c.execute("BEGIN IMMEDIATE")
    store.mark_collection_deleted(c, LIST_B)
    c.execute("ROLLBACK")
    assert store.share_id_list(store.get_share(c, "s1")["lists"]) == ["home"]
    assert c.execute("SELECT deleted FROM collections WHERE href=?",
                     (LIST_B,)).fetchone()["deleted"] == 0


def test_a_recreated_collection_is_not_shared_again(svc):
    c = svc._conn
    _share(c, lists=json.dumps(["work"]))
    store.mark_collection_deleted(c, LIST_A)
    store.upsert_collection(
        c, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"}))
    assert store.share_id_list(store.get_share(c, "s1")["lists"]) == []


# ── the task reader ─────────────────────────────────────────────────────────

def _seed_list(svc) -> None:
    c = svc._conn
    _seed_task(c, LIST_A, "dated-late", "Zebra", due="2026-08-25")
    _seed_task(c, LIST_A, "dated-early", "Yak", due="2026-08-19")
    _seed_task(c, LIST_A, "dated-early-a", "Aardvark", due="2026-08-19")
    _seed_task(c, LIST_A, "timed", "Timed", due_utc="20260820T090000Z")
    _seed_task(c, LIST_A, "undated-b", "Bee")
    _seed_task(c, LIST_A, "undated-a", "Ant")
    _seed_task(c, LIST_A, "undated-none", "")
    _seed_task(c, LIST_A, "ordered-2", "Second by hand", due="2026-09-30")
    _seed_task(c, LIST_A, "ordered-1", "First by hand")
    _seed_task(c, LIST_A, "sub", "A subtask", due="2026-08-19", parent="dated-late")
    _seed_task(c, LIST_A, "done", "Finished", status="COMPLETED")
    _seed_task(c, LIST_A, "cancelled", "Won't do", status="CANCELLED")
    _seed_task(c, LIST_A, "parked", "Set aside")
    _seed_task(c, LIST_A, "in-process", "Underway", status="IN-PROCESS")
    _seed_task(c, LIST_B, "elsewhere", "Another list")
    store.set_sidecar(c, LIST_A, "ordered-1", sort_order=1.0)
    store.set_sidecar(c, LIST_A, "ordered-2", sort_order=2.0)
    store.set_sidecar(c, LIST_A, "parked", parked_at="2026-08-20T08:00:00.000Z")
    store.set_sidecar(c, LIST_A, "done", sort_order=0.5)
    store.set_sidecar(c, LIST_A, "undated-a", pinned=1, estimated_minutes=30)


def test_share_open_tasks_matches_list_tasks_open_and_unparked(svc):
    _seed_list(svc)
    expected = svc.list_tasks(LIST_A, include_done=False, include_parked=False)
    got = store.share_open_tasks(svc._conn, LIST_A)

    assert [r["uid"] for r in got] == [t["uid"] for t in expected]
    # The filter really did something: the closed, cancelled and parked are out.
    uids = {r["uid"] for r in got}
    assert not uids & {"done", "cancelled", "parked", "elsewhere"}
    assert {"in-process", "sub", "timed"} <= uids
    # And the columns it hands over are the ones the DTO has.
    for row, task in zip(got, expected, strict=True):
        assert row["summary"] == task["summary"]
        assert row["due"] == task["due"]
        assert bool(row["due_is_date"]) == task["due_is_date"]
        assert row["related_parent"] == task["parent"]


def test_share_open_tasks_orders_by_hand_then_due_then_summary(svc):
    _seed_list(svc)
    order = [r["uid"] for r in store.share_open_tasks(svc._conn, LIST_A)]
    # Manual positions first, whatever they are keyed on.
    placed = [u for u in order if u in {"ordered-1", "ordered-2", "undated-a"}]
    assert placed[:2] == ["ordered-1", "ordered-2"]
    unplaced = [u for u in order if u not in {"ordered-1", "ordered-2"}]
    # Dated before undated; equal dates by summary; undated by summary.
    assert unplaced.index("dated-early-a") < unplaced.index("dated-early")
    assert unplaced.index("dated-early") < unplaced.index("timed")
    assert unplaced.index("timed") < unplaced.index("dated-late")
    assert unplaced.index("dated-late") < unplaced.index("undated-none")
    assert unplaced.index("undated-none") < unplaced.index("undated-a")
    assert unplaced.index("undated-a") < unplaced.index("undated-b")


def test_share_open_tasks_is_narrow_and_scoped_to_its_collection(svc):
    _seed_list(svc)
    store.upsert_collection(
        svc._conn, CollectionInfo(href=CAL_A, displayname="Personal", components={"VEVENT"}))
    _seed_event(svc._conn, CAL_A, "ev", "An event", start="20260821T090000Z")
    rows = store.share_open_tasks(svc._conn, LIST_A)
    assert set(rows[0].keys()) == {"uid", "summary", "due", "due_is_date", "related_parent"}
    assert [r["uid"] for r in store.share_open_tasks(svc._conn, LIST_B)] == ["elsewhere"]
    # An event is not a task, and an unknown collection is empty.
    assert store.share_open_tasks(svc._conn, CAL_A) == []
    assert store.share_open_tasks(svc._conn, "/u/nope/") == []


# ── private marks ───────────────────────────────────────────────────────────

def test_share_class_ics_prefilters_to_resources_that_mention_class(svc):
    c = svc._conn
    _seed_task(c, LIST_A, "plain", "Plain")
    _seed_task(c, LIST_A, "private", "Hidden")
    _seed_task(c, LIST_A, "lower", "Lower")
    _seed_task(c, LIST_A, "elsewhere", "Not here")
    _seed_task(c, LIST_B, "other-list", "Other list")
    # `foreign_raw` has no CLASS to offer, so the bodies are rewritten in place.
    def stamp(href: str, uid: str, line: bytes) -> None:
        raw = foreign_raw(uid, "x").replace(b"END:VTODO", line + b"\r\nEND:VTODO")
        c.execute("UPDATE items SET raw_ics=? WHERE collection_href=? AND uid=?",
                  (raw, href, uid))
    stamp(LIST_A, "private", b"CLASS:PRIVATE")
    stamp(LIST_A, "lower", b"class:confidential")
    stamp(LIST_B, "other-list", b"CLASS:PRIVATE")
    c.execute("UPDATE items SET raw_ics=? WHERE collection_href=? AND uid='elsewhere'",
              (foreign_raw("elsewhere", "x", extra=("DESCRIPTION:a class act",)), LIST_A))

    got = store.share_class_ics(c, LIST_A)

    # Every candidate comes back, including the one that only SAYS "class": the
    # prefilter may over-select, and share.is_private decides properly.
    assert set(got) == {"private", "lower", "elsewhere"}
    assert b"CLASS:PRIVATE" in got["private"]
    assert store.share_class_ics(c, "/u/nope/") == {}


# ── the booking ledger ──────────────────────────────────────────────────────

def _book(conn, link_token: str, uid: str, calendar_href: str = CAL_A) -> None:
    store.insert_booking(
        conn, id=f"b-{uid}", link_token=link_token, calendar_href=calendar_href,
        event_uid=uid, client_name="Visitor Vera", client_email="vera@example.com",
        notes=None, start_at="2026-08-21T10:00:00+00:00", end_at="2026-08-21T10:30:00+00:00")


def _link(conn, token: str, title: str) -> None:
    store.create_booking_link(
        conn, token, {"title": title, "calendar_href": CAL_A, "timezone": "UTC"})


def test_booking_titles_are_keyed_by_event_uid(svc):
    c = svc._conn
    _link(c, "link-one", "Intro call")
    _link(c, "link-two", "Office hours")
    _book(c, "link-one", "ev-1")
    _book(c, "link-two", "ev-2")
    _book(c, "gone-link", "ev-3")

    got = store.booking_titles(c, ["ev-1", "ev-2", "ev-3", "ev-unbooked"])

    # Keyed by UID alone; a deleted link is "" and an unbooked event is absent.
    assert got == {"ev-1": "Intro call", "ev-2": "Office hours", "ev-3": ""}
    assert store.booking_titles(c, ["ev-2"]) == {"ev-2": "Office hours"}
    assert store.booking_titles(c, []) == {}
    assert "Vera" not in json.dumps(got)


def test_booking_titles_survive_a_moved_booking(svc):
    c = svc._conn
    _link(c, "link-one", "Intro call")
    # The ledger still names the calendar the booking was made in, which
    # `move_event` never updates: the lookup must not depend on it.
    _book(c, "link-one", "ev-1", calendar_href="/u/old-calendar/")
    assert store.booking_titles(c, ["ev-1"]) == {"ev-1": "Intro call"}


def test_booking_titles_bind_every_uid(svc):
    c = svc._conn
    _link(c, "link-one", "Intro call")
    _book(c, "link-one", "ev-1")
    hostile = "x') OR 1=1 --"
    assert store.booking_titles(c, [hostile]) == {}
    assert store.booking_titles(c, [hostile, "ev-1"]) == {"ev-1": "Intro call"}


def test_booking_link_titles_are_non_empty_and_longest_first(svc):
    c = svc._conn
    assert store.booking_link_titles(c) == []
    _link(c, "l1", "Call")
    _link(c, "l2", "Call with the team")
    _link(c, "l3", "")
    _link(c, "l4", "Zed")
    assert store.booking_link_titles(c) == ["Call with the team", "Call", "Zed"]
