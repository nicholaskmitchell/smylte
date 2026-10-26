"""Shares: read-only views of chosen lists and calendars, for a person.

This file starts at the storage layer, which is where the properties the rest of
the feature leans on are decided: an allowlist column that reads as NOTHING when
it cannot be read, a token column that cannot hold a short credential, a prune
that rides on the caller's transaction, and a task reader that answers exactly
as `list_tasks` would without loading what `list_tasks` loads.

The service is the security boundary: `share_view` is the one call a token
reaches, and the tests there pin what a stranger can and cannot be sent — the
exact key set, the canary that nothing private gets out, the day that is never
opened, and the one answer for every refusal.

It ends at HTTP, where that one answer has to stay one answer: the same 404
body and headers for every refusal, the privacy headers on everything a stranger
can be sent, the limiters, a 500 that says nothing, and no connector tool that
could mint a link.

Nothing here touches Radicale. A share is app-only state over the cache, so the
store is driven directly and `items` is seeded the way test_day_plan seeds it;
the app is built against a DAV URL on a closed port.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from helpers import foreign_event_raw, foreign_raw
from test_day_plan import DAY, LIST_A, LIST_B, _seed_task, _settings
from test_displays import CAL_A, CAL_B, _seed_event
from test_focus import clock  # noqa: F401

from smylted import service as service_mod
from smylted import share as share_mod
from smylted.app import create_app
from smylted.config import Settings
from smylted.dav.client import CollectionInfo, Item
from smylted.db import store
from smylted.ical import extract_from_raw
from smylted.mcp.api import McpApi
from smylted.mcp.tools import build_tools
from smylted.service import SmylteService

TOKEN = "t" * 43
# A collection that holds both tasks and events, as some servers' default does.
MIXED = "/u/mixed/"


@pytest.fixture
def svc(monkeypatch):
    s = SmylteService(_settings())
    for href, name in ((LIST_A, "Work"), (LIST_B, "Home")):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components={"VTODO"}))
    for href, name in ((CAL_A, "Personal"), (CAL_B, "Shared")):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components={"VEVENT"}))
    store.upsert_collection(
        s._conn, CollectionInfo(href=MIXED, displayname="Both",
                                components={"VTODO", "VEVENT"}))
    # Pinned for the reason test_day_plan gives: a suite whose expectations
    # move at midnight is a suite that fails at midnight.
    monkeypatch.setattr(SmylteService, "_today", lambda self: DAY)
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


# ── the pure payload helpers (smylted/share.py) ─────────────────────────────

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: int) -> str:
    return share_mod.stamp(NOW - timedelta(seconds=seconds))


def _session(*, phase="focus", length=1500, elapsed=0, since=None, updated=None) -> dict:
    """A live `focus_session` row as the service hands it over. `updated_at` is
    set explicitly: in the database it comes from SQLite's own clock, which the
    `_focus_now` seam does not move."""
    return {"phase": phase, "phase_length_s": length, "phase_elapsed_s": elapsed,
            "running_since": since, "updated_at": updated or share_mod.stamp(NOW)}


@pytest.mark.parametrize("session, expected", [
    # No session at all reads as idle.
    (None, {"state": "idle", "phase": None, "phase_length_s": None,
            "ends_at": None, "remaining_s": None}),
    # Running: the end is fixed, so it is the only thing that carries the clock.
    (_session(since=_ago(300), elapsed=100),
     {"state": "focusing", "phase": "focus", "phase_length_s": 1500,
      "ends_at": share_mod.stamp(NOW - timedelta(seconds=300) + timedelta(seconds=1400)),
      "remaining_s": None}),
    (_session(phase="break", length=300, since=_ago(10)),
     {"state": "break", "phase": "break", "phase_length_s": 300,
      "ends_at": share_mod.stamp(NOW - timedelta(seconds=10) + timedelta(seconds=300)),
      "remaining_s": None}),
    (_session(phase="long_break", length=900, since=_ago(10)),
     {"state": "break", "phase": "long_break", "phase_length_s": 900,
      "ends_at": share_mod.stamp(NOW - timedelta(seconds=10) + timedelta(seconds=900)),
      "remaining_s": None}),
    # Paused: the time left is frozen, not an end.
    (_session(elapsed=600, updated=_ago(60)),
     {"state": "paused", "phase": "focus", "phase_length_s": 1500,
      "ends_at": None, "remaining_s": 900}),
    # Paused for 31 minutes is a timer somebody walked away from.
    (_session(elapsed=600, updated=_ago(31 * 60)),
     {"state": "idle", "phase": None, "phase_length_s": None,
      "ends_at": None, "remaining_s": None}),
    # A running_since that cannot be read is no anchor: paused, not an error.
    (_session(elapsed=600, since="not a time", updated=_ago(60)),
     {"state": "paused", "phase": "focus", "phase_length_s": 1500,
      "ends_at": None, "remaining_s": 900}),
    # Ran out 10 minutes ago and nobody continued: between. 16 minutes: idle.
    (_session(since=_ago(1500 + 10 * 60)),
     {"state": "between", "phase": "focus", "phase_length_s": 1500,
      "ends_at": None, "remaining_s": None}),
    (_session(since=_ago(1500 + 16 * 60)),
     {"state": "idle", "phase": None, "phase_length_s": None,
      "ends_at": None, "remaining_s": None}),
    # Halted with nothing left, by the row's own updated_at.
    (_session(elapsed=1500, updated=_ago(10 * 60)),
     {"state": "between", "phase": "focus", "phase_length_s": 1500,
      "ends_at": None, "remaining_s": None}),
    (_session(elapsed=1500, updated=_ago(16 * 60)),
     {"state": "idle", "phase": None, "phase_length_s": None,
      "ends_at": None, "remaining_s": None}),
    # An unknown phase is drawn as a focus phase.
    (_session(phase="nonsense", since=_ago(10)),
     {"state": "focusing", "phase": "focus", "phase_length_s": 1500,
      "ends_at": share_mod.stamp(NOW - timedelta(seconds=10) + timedelta(seconds=1500)),
      "remaining_s": None}),
])
def test_focus_block_states(session, expected):
    assert share_mod.focus_block(session, NOW) == expected


def test_focus_block_is_a_new_dict_with_exactly_the_clock_keys():
    idle = share_mod.focus_block(None, NOW)
    idle["today"] = {"rows": []}
    assert "today" not in share_mod.IDLE and "today" not in share_mod.focus_block(None, NOW)
    for session in (None, _session(since=_ago(10)), _session(elapsed=5)):
        assert set(share_mod.focus_block(session, NOW)) == {
            "state", "phase", "phase_length_s", "ends_at", "remaining_s"}


def test_focus_block_never_moves_between_polls():
    running = _session(since=_ago(30))
    assert (share_mod.focus_block(running, NOW)
            == share_mod.focus_block(running, NOW + timedelta(seconds=10)))
    paused = _session(elapsed=600, updated=_ago(60))
    assert (share_mod.focus_block(paused, NOW)
            == share_mod.focus_block(paused, NOW + timedelta(seconds=10)))


def _t(uid, parent=None, summary=None):
    return {"uid": uid, "related_parent": parent, "summary": summary or uid}


def _walk(rows):
    return [(t["uid"], d) for t, d in share_mod.tree(rows)]


def test_tree_nests_children_under_their_parent_in_list_order():
    rows = [_t("a"), _t("b"), _t("a1", "a"), _t("a2", "a"), _t("a1x", "a1")]
    assert _walk(rows) == [("a", 0), ("a1", 1), ("a1x", 2), ("a2", 1), ("b", 0)]


def test_tree_treats_an_open_subtask_of_a_missing_parent_as_a_root():
    # The parent is closed, parked or in another collection, so it is not in the
    # input: the subtask stays visible, flat, and nothing about the parent is read.
    rows = [_t("child", "closed-parent"), _t("other")]
    assert _walk(rows) == [("child", 0), ("other", 0)]


def test_tree_treats_a_self_parent_as_a_root():
    assert _walk([_t("a", "a")]) == [("a", 0)]


def test_tree_terminates_on_a_cycle_and_keeps_every_row():
    rows = [_t("x"), _t("a", "b"), _t("b", "a")]
    assert _walk(rows) == [("x", 0), ("a", 0), ("b", 0)]


def test_tree_caps_the_depth():
    rows = [_t("l0")] + [_t(f"l{i}", f"l{i - 1}") for i in range(1, 7)]
    assert [d for _, d in _walk(rows)] == [0, 1, 2, 3, 3, 3, 3]


def test_tree_does_not_modify_or_drop_its_input():
    rows = [_t("a"), _t("b", "a")]
    assert [t for t, _ in share_mod.tree(rows)] == rows
    assert share_mod.tree([]) == []


def test_instant_dates_pass_through_as_dates():
    berlin = ZoneInfo("Europe/Berlin")
    assert share_mod.instant("2026-10-28", is_date=True, zone=berlin) == "2026-10-28"
    assert share_mod.instant("2026-10-28T09:00:00", is_date=True, zone=berlin) == "2026-10-28"
    assert share_mod.instant("2026-10-28", is_date=False, zone=berlin) == "2026-10-28"


def test_instant_resolves_floating_times_in_the_owners_zone():
    berlin = ZoneInfo("Europe/Berlin")
    # 2026-10-26 is still CET (UTC+1) — summer time ended on the 25th.
    assert (share_mod.instant("2026-10-26T09:00:00", is_date=False, zone=berlin)
            == "2026-10-26T08:00:00.000Z")
    assert (share_mod.instant("2026-07-01T09:00:00", is_date=False, zone=berlin)
            == "2026-07-01T07:00:00.000Z")


def test_instant_sends_offsets_as_utc_and_never_an_offset():
    kiritimati = ZoneInfo("Pacific/Kiritimati")
    got = share_mod.instant("2026-10-26T09:00:00+14:00", is_date=False, zone=kiritimati)
    assert got == "2026-10-25T19:00:00.000Z"
    assert share_mod.instant("2026-10-26T09:00:00Z", is_date=False, zone=None) == (
        "2026-10-26T09:00:00.000Z")
    for value in ("2026-10-26T09:00:00+02:00", "2026-10-26T09:00:00-05:30"):
        assert "+" not in share_mod.instant(value, is_date=False, zone=None)
        assert share_mod.instant(value, is_date=False, zone=None).endswith("Z")


def test_instant_without_a_home_zone_falls_back_to_the_servers():
    got = share_mod.instant("2026-10-26T09:00:00", is_date=False, zone=None)
    expected = datetime(2026, 10, 26, 9).astimezone().astimezone(timezone.utc)
    assert got == share_mod.stamp(expected)


def test_instant_refuses_nothing_and_garbage():
    assert share_mod.instant(None, is_date=False, zone=None) is None
    assert share_mod.instant("", is_date=False, zone=None) is None
    assert share_mod.instant("yesterdayTnoon", is_date=False, zone=None) is None
    assert share_mod.instant("9999-12-31T23:59:59-14:00", is_date=False, zone=None) is None


def test_color_is_a_hex_literal_or_nothing():
    assert share_mod.color("#3A7BD5") == "#3A7BD5"
    assert share_mod.color("#3a7bd5cc") == "#3a7bd5cc"
    for bad in (None, "", "red", "#fff", "#12345", "url(x)", "#3A7BD5;x:y",
                '#3A7BD5" onload="x', "#3A7BD5\n", "#GGGGGG"):
        assert share_mod.color(bad) is None


def test_title_is_bounded_and_flattened():
    assert len(share_mod.title("x" * 4000)) == share_mod.TITLE_CHARS
    assert share_mod.title("two\nlines\tand   gaps") == "two lines and gaps"
    assert share_mod.title(None) == "" and share_mod.title("") == ""
    assert share_mod.title("  padded  ") == "padded"


def test_row_key_is_opaque_stable_and_per_share():
    key = share_mod.row_key("share-1", "entry-1")
    assert key == share_mod.row_key("share-1", "entry-1")
    assert len(key) == 16 and set(key) <= set("0123456789abcdef")
    assert key != share_mod.row_key("share-2", "entry-1")
    assert key != share_mod.row_key("share-1", "entry-2")
    assert "entry-1" not in key and "share-1" not in key


def test_the_token_pattern_is_exactly_43_urlsafe_characters():
    assert share_mod.TOKEN_RE.fullmatch("a" * 43)
    assert share_mod.TOKEN_RE.fullmatch("A-_" * 14 + "z")
    for bad in ("a" * 42, "a" * 44, "a" * 42 + "/", "a" * 42 + "\n", "../x", ""):
        assert share_mod.TOKEN_RE.fullmatch(bad) is None


def test_the_horizons_include_the_default():
    assert share_mod.HORIZONS == (1, 7, 14, 28)
    assert share_mod.DEFAULT_HORIZON in share_mod.HORIZONS
    assert not hasattr(share_mod, "HORIZON_DAYS")


# ── private marks ───────────────────────────────────────────────────────────

def _ics(*lines: str) -> str:
    return "\r\n".join(("BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:u", *lines,
                         "END:VEVENT", "END:VCALENDAR", ""))


@pytest.mark.parametrize("lines", [
    ("CLASS:PRIVATE",),
    ("CLASS:CONFIDENTIAL",),
    ("CLASS:private",),
    ("CLASS:X-SECRET",),
    ("CLASS;X-A=b:PRIVATE",),
    ("CLASS:",),
    # Folded: the value continues on the next physical line.
    ("CLASS:PRI", " VATE"),
    ("SUMMARY:Lunch", "CLASS:PRIVATE"),
    # One non-PUBLIC mark anywhere marks the whole resource.
    ("CLASS:PUBLIC", "CLASS:PRIVATE"),
])
def test_is_private_flags_any_class_other_than_public(lines):
    assert share_mod.is_private(_ics(*lines)) is True


@pytest.mark.parametrize("lines", [
    (),
    ("CLASS:PUBLIC",),
    ("CLASS:public",),
    ("CLASS: PUBLIC ",),
    ("CLASS;X-A=b:PUBLIC",),
    # The word in free text is not the property.
    ("DESCRIPTION:this class is private",),
    ("DESCRIPTION:class", " CLASS:PRIVATE"),
    ("X-CLASS:PRIVATE",),
    ("CLASSIFICATION:PRIVATE",),
])
def test_is_private_ignores_everything_else(lines):
    assert share_mod.is_private(_ics(*lines)) is False


def test_is_private_reads_bytes_and_nothing():
    assert share_mod.is_private(_ics("CLASS:PRIVATE").encode()) is True
    assert share_mod.is_private(_ics("CLASS:PUBLIC").encode()) is False
    assert share_mod.is_private(b"\xff\xfeCLASS:PRIVATE") is False
    assert share_mod.is_private(b"\xffX\r\nCLASS:PRIVATE\r\n") is True
    assert share_mod.is_private(None) is False
    assert share_mod.is_private("") is False and share_mod.is_private(b"") is False


def test_is_private_reads_lf_and_crlf_line_ends_alike():
    assert share_mod.is_private("CLASS:PRIVATE\n") is True
    assert share_mod.is_private("CLASS:PRIVATE\r\n") is True
    assert share_mod.is_private("CLASS:PRIVATE") is True
    assert share_mod.is_private("CLASS:PUBLIC\r\nSUMMARY:x\r\n") is False


# ── the service: owning a share ─────────────────────────────────────────────

def _d(offset: int, sep: str = "") -> str:
    """DAY moved by `offset` days, compact for an ICS value or dashed for a key."""
    return (date.fromisoformat(DAY) + timedelta(days=offset)).strftime(
        f"%Y{sep}%m{sep}%d")


def _event(conn, href: str, uid: str, summary: str, **kw) -> None:
    """Cache one VEVENT through the real extractor, as the sync engine would."""
    raw = foreign_event_raw(uid, summary, **kw)
    store.upsert_item(conn, href, Item(f"{href}{uid}.ics", '"1"', raw), extract_from_raw(raw))


def _task(conn, href: str, uid: str, summary: str, *extra: str) -> None:
    raw = foreign_raw(uid, summary, extra=extra)
    store.upsert_item(conn, href, Item(f"{href}{uid}.ics", '"1"', raw), extract_from_raw(raw))


def _make(svc_, **fields) -> dict:
    return svc_.create_share({"name": "Sam", **fields})


def _view(svc_, made: dict) -> dict | None:
    return svc_.share_view(made["token"])


def _empty(view: dict) -> dict:
    """The whole payload of a share that shows nothing, for this view's clock."""
    return {"v": 1, "generated_at": view["generated_at"], "poll_seconds": 30,
            "day": DAY, "days": 7, "focus": None, "lists": [], "calendars": [],
            "events": [], "events_more": 0}


@pytest.fixture
def published(monkeypatch, svc):
    events: list[dict] = []
    monkeypatch.setattr(svc, "_publish", events.append)
    return events


def test_share_crud_round_trips_with_a_256_bit_token(svc):
    made = _make(svc)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", made["token"])
    assert re.fullmatch(r"[0-9a-f]{32}", made["id"]) and made["id"] != made["token"]
    assert made["lists"] == [] and made["calendars"] == []
    assert made["show_focus"] is False and made["enabled"] is True
    assert made["switched_off_by_password"] is False
    assert made["horizon_days"] == 7
    # No configured origin, so no absolute URL rather than one built off a guess.
    assert made["url"] is None
    assert svc.get_share(made["id"]) == made
    assert svc.list_shares() == [made]

    edited = svc.update_share(made["id"], {"name": "  Alex  ", "show_focus": True,
                                           "horizon_days": 14})
    assert edited["name"] == "Alex" and edited["show_focus"] is True
    assert edited["horizon_days"] == 14 and edited["token"] == made["token"]
    assert svc.update_share("nope", {"name": "x"}) is None

    assert svc.delete_share(made["id"]) is True
    assert svc.delete_share(made["id"]) is False
    assert svc.get_share(made["id"]) is None and svc.list_shares() == []


def test_share_fields_are_validated(svc):
    made = _make(svc)
    for bad in ({"name": "   "}, {"lists": "work"}, {"calendars": [1]},
                {"horizon_days": 3}, {"horizon_days": True}, {"horizon_days": "7"},
                {"horizon_days": 7.0}, {"horizon_days": None}):
        with pytest.raises(ValueError):
            svc.update_share(made["id"], bad)
    with pytest.raises(ValueError, match="needs a name"):
        svc.create_share({"name": ""})
    for days in share_mod.HORIZONS:
        assert svc.update_share(made["id"], {"horizon_days": days})["horizon_days"] == days
    # The credential stamp is the service's own: a caller's value never lands.
    svc.update_share(made["id"], {"cv": "forged"})
    assert store.get_share(svc._conn, made["id"])["cv"] == ""


def test_a_share_url_is_absolute_when_the_origin_is_configured(svc, monkeypatch):
    monkeypatch.setattr(
        svc, "settings", dataclasses.replace(svc.settings, public_url="https://smylte.example"))
    made = _make(svc)
    assert made["url"] == f"https://smylte.example/share/{made['token']}"


def test_writes_keep_only_live_slugs_of_the_right_component(svc):
    made = _make(svc, lists=["/u/work/", "nope", "cal-a", "work", "work"],
                 calendars=["work", "cal-a", "mixed", "cal-a"])
    assert made["lists"] == ["work"]
    assert made["calendars"] == ["cal-a", "mixed"]
    assert svc.update_share(made["id"], {"lists": ["mixed", "home"]})["lists"] == \
        ["mixed", "home"]
    store.mark_collection_deleted(svc._conn, LIST_B)
    assert svc.update_share(made["id"], {"lists": ["home", "work"]})["lists"] == ["work"]


def test_share_events_on_the_bus_carry_the_id_never_the_token(svc, published):
    made = _make(svc)
    svc.update_share(made["id"], {"name": "Alex"})
    rotated = svc.rotate_share_token(made["id"])
    svc.delete_share(made["id"])
    svc.delete_share(made["id"])                  # a miss publishes nothing
    assert published == [
        {"type": "share_created", "share": made["id"]},
        {"type": "share_updated", "share": made["id"]},
        {"type": "share_updated", "share": made["id"]},
        {"type": "share_deleted", "share": made["id"]},
    ]
    sent = json.dumps(published)
    assert made["token"] not in sent and rotated["token"] not in sent


# ── the service: what a share shows ─────────────────────────────────────────

def _seed_everything(svc_) -> None:
    """Something in every collection, a planned day and a running session, so
    a share that shows nothing is showing nothing for a reason."""
    c = svc_._conn
    _seed_task(c, LIST_A, "ta", "Draft the memo")
    _seed_task(c, LIST_B, "tb", "Fix the shelf")
    _seed_task(c, MIXED, "tm", "Mixed task")
    _event(c, CAL_A, "ea", "Standup", dtstart=f"{_d(0)}T090000Z", dtend=f"{_d(0)}T093000Z")
    _event(c, CAL_B, "eb", "Lunch", dtstart=f"{_d(0)}T120000Z", dtend=f"{_d(0)}T130000Z")
    _event(c, MIXED, "em", "Mixed event", dtstart=f"{_d(1)}T120000Z",
           dtend=f"{_d(1)}T130000Z")
    svc_.open_day(DAY, create=True)
    svc_.add_day_entry(DAY, entry_id="e-a", kind="task", list_id="work", uid="ta")
    store.put_focus_session(
        c, DAY, phase="focus", phase_length_s=1500, phase_elapsed_s=0,
        running_since=_stamp_now(), intervals_done=0, entry_id="e-a", passed="[]",
        started_at=_stamp_now(), ended_at=None)


def _stamp_now() -> str:
    return share_mod.stamp(service_mod._focus_now())


def test_a_new_share_shows_nothing(svc, clock):
    _seed_everything(svc)
    made = _make(svc)
    view = _view(svc, made)
    assert view == _empty(view)


def test_an_emptied_allowlist_is_nothing_not_everything(svc):
    _seed_everything(svc)
    made = _make(svc, lists=["work"], calendars=["cal-a"])
    assert [t["title"] for t in _view(svc, made)["lists"][0]["tasks"]] == ["Draft the memo"]
    svc.update_share(made["id"], {"lists": [], "calendars": []})
    view = _view(svc, made)
    assert view == _empty(view)

    # The same data on a display: there, an empty allowlist is EVERYTHING. The
    # two rules side by side are the inversion this feature rests on.
    shown = svc.create_display({"name": "Hallway", "mode": "calendar"})
    frame = svc.display_frame(shown["token"])
    assert {s["id"] for s in frame["sources"]} == {"cal-a", "cal-b", "mixed"}


@pytest.mark.parametrize("raw", ["{}", "not json", "[1, null]", '"work"', ""])
def test_unreadable_allowlist_json_reads_as_nothing(svc, raw):
    _seed_everything(svc)
    made = _make(svc, lists=["work"], calendars=["cal-a"])
    svc._conn.execute("UPDATE shares SET lists=?, calendars=? WHERE id=?",
                      (raw, raw, made["id"]))
    view = _view(svc, made)
    assert view == _empty(view)


def test_only_selected_lists_and_calendars_reach_the_view(svc):
    _seed_everything(svc)
    made = _make(svc, lists=["work"], calendars=["cal-a"])
    view = _view(svc, made)
    assert [lst["name"] for lst in view["lists"]] == ["Work"]
    assert [cal["name"] for cal in view["calendars"]] == ["Personal"]
    assert [e["title"] for e in view["events"]] == ["Standup"]
    sent = json.dumps(view)
    for absent in ("Fix the shelf", "Lunch", "Home", "Shared", "Mixed", "Both"):
        assert absent not in sent


def test_a_mixed_collection_is_gated_by_component(svc):
    _seed_everything(svc)
    as_list = _view(svc, _make(svc, lists=["mixed"]))
    assert [t["title"] for t in as_list["lists"][0]["tasks"]] == ["Mixed task"]
    assert as_list["calendars"] == [] and as_list["events"] == []
    assert "Mixed event" not in json.dumps(as_list)

    as_calendar = _view(svc, _make(svc, calendars=["mixed"]))
    assert [e["title"] for e in as_calendar["events"]] == ["Mixed event"]
    assert as_calendar["lists"] == []
    assert "Mixed task" not in json.dumps(as_calendar)


def test_ambiguous_slugs_reach_nothing(svc):
    _seed_everything(svc)
    made = _make(svc, lists=["work"], calendars=["cal-a"])
    # A second live collection whose last segment is also "work", and one that
    # is also "cal-a": which one the owner picked cannot be told from the slug.
    store.upsert_collection(
        svc._conn, CollectionInfo(href="/v/work/", displayname="Other work",
                                  components={"VTODO"}))
    store.upsert_collection(
        svc._conn, CollectionInfo(href="/v/cal-a/", displayname="Other cal",
                                  components={"VEVENT"}))
    view = _view(svc, made)
    assert view == _empty(view)


def test_a_deleted_collection_is_pruned_and_not_revived(svc):
    _seed_everything(svc)
    made = _make(svc, lists=["work", "home"])
    store.mark_collection_deleted(svc._conn, LIST_A)
    assert svc.get_share(made["id"])["lists"] == ["home"]
    # The same href comes back, as a new collection of the same name would.
    store.upsert_collection(
        svc._conn, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"}))
    _seed_task(svc._conn, LIST_A, "tnew", "Brand new")
    view = _view(svc, made)
    assert [lst["name"] for lst in view["lists"]] == ["Home"]
    assert "Brand new" not in json.dumps(view)


def test_archived_calendars_are_never_shared_even_when_selected(svc):
    _seed_everything(svc)
    made = _make(svc, calendars=["cal-a", "cal-b"])
    store.update_settings(svc._conn, {"archived_calendars": ["cal-b"]})
    view = _view(svc, made)
    assert [cal["name"] for cal in view["calendars"]] == ["Personal"]
    assert [e["title"] for e in view["events"]] == ["Standup"]
    # Still selected: un-archiving brings it back without an edit.
    assert svc.get_share(made["id"])["calendars"] == ["cal-a", "cal-b"]


def test_private_fields_never_reach_the_view(svc, clock):
    """THE CANARY. Every field a share must not send carries a distinct marker,
    and none of them, nor anything that names the share or a collection, is
    anywhere in the payload."""
    c = svc._conn
    store.update_settings(c, {"home_timezone": "Pacific/Kiritimati"})
    _task(c, LIST_A, "uid-canary-task", "Shared task",
          "DESCRIPTION:CANARY-TASK-DESCRIPTION", "CATEGORIES:CANARY-TASK-TAG")
    _task(c, LIST_B, "t-unshared", "CANARY-UNSHARED-TASK")
    _event(c, CAL_A, "uid-canary-event", "Shared event",
           dtstart=f"{_d(0)}T090000Z", dtend=f"{_d(0)}T100000Z",
           extra=("DESCRIPTION:CANARY-EVENT-DESCRIPTION", "LOCATION:CANARY-LOCATION",
                  "CATEGORIES:CANARY-EVENT-TAG"))
    _event(c, CAL_A, "e-kiritimati", "Island call",
           dtstart=f"TZID=Pacific/Kiritimati:{_d(1)}T090000",
           dtend=f"TZID=Pacific/Kiritimati:{_d(1)}T100000")
    _event(c, CAL_B, "e-archived", "CANARY-ARCHIVED-EVENT",
           dtstart=f"{_d(0)}T110000Z", dtend=f"{_d(0)}T120000Z")
    _event(c, MIXED, "e-unshared", "CANARY-UNSHARED-EVENT",
           dtstart=f"{_d(0)}T110000Z", dtend=f"{_d(0)}T120000Z")
    store.upsert_collection(
        c, CollectionInfo(href=LIST_B, displayname="CANARY-UNSHARED-LIST",
                          components={"VTODO"}))
    store.update_settings(c, {"archived_calendars": ["cal-b"]})
    store.set_sidecar(c, CAL_A, "uid-canary-event", notify_minutes_before=4321)
    svc.create_habit(title="CANARY-HABIT")
    svc.open_day(DAY, create=True)
    svc.add_day_entry(DAY, entry_id="e-task", kind="task", list_id="work",
                      uid="uid-canary-task", estimate_minutes=99999)
    svc.add_day_entry(DAY, entry_id="e-note", kind="note", title="CANARY-NOTE")
    svc.set_day_ritual(DAY, reflection="CANARY-REFLECTION")
    store.put_focus_session(
        c, DAY, phase="focus", phase_length_s=1500, phase_elapsed_s=0,
        running_since=_stamp_now(), intervals_done=0, entry_id="e-task",
        passed=json.dumps(["e-note"]), started_at=_stamp_now(), ended_at=None)
    made = svc.create_share({"name": "CANARY-SHARE-NAME", "lists": ["work"],
                             "calendars": ["cal-a", "cal-b"], "show_focus": True})

    view = _view(svc, made)
    sent = json.dumps(view)

    # The view really is populated, so the absences below mean something.
    assert [t["title"] for t in view["lists"][0]["tasks"]] == ["Shared task"]
    assert {e["title"] for e in view["events"]} == {"Shared event", "Island call"}
    assert [r["title"] for r in view["focus"]["today"]["rows"]] == ["Shared task"]
    for canary in ("CANARY", "4321", "99999", "uid-canary", "e-task", "e-note",
                   made["token"], made["id"], LIST_A, CAL_A, "/u/", '"work"',
                   '"cal-a"', '"cal-b"', "Kiritimati", "+14:00"):
        assert canary not in sent, canary
    island = next(e for e in view["events"] if e["title"] == "Island call")
    assert island["start"] == f"{_d(0, '-')}T19:00:00.000Z"


def test_private_marked_items_are_sent_without_a_title(svc, clock):
    """CLASS:PRIVATE in another app reads as Busy here: the time is shared, the
    words are not, and nothing about the booking ledger can put them back."""
    c = svc._conn
    _task(c, LIST_A, "t-private", "CANARY-PRIVATE-TASK", "CLASS:PRIVATE")
    _task(c, LIST_A, "t-public", "Public task", "CLASS:PUBLIC")
    _event(c, CAL_A, "e-private", "CANARY-PRIVATE-EVENT",
           dtstart=f"{_d(0)}T090000Z", dtend=f"{_d(0)}T100000Z",
           extra=("CLASS:CONFIDENTIAL",))
    _event(c, CAL_A, "e-series", "CANARY-PRIVATE-SERIES",
           dtstart=f"{_d(0)}T150000Z", dtend=f"{_d(0)}T160000Z",
           rrule="FREQ=DAILY;COUNT=3",
           overrides=(("RECURRENCE-ID:" + f"{_d(1)}T150000Z", f"DTSTART:{_d(1)}T150000Z",
                       f"DTEND:{_d(1)}T160000Z", "SUMMARY:CANARY-OVERRIDE",
                       "CLASS:PRIVATE"),))
    _event(c, CAL_A, "e-booked", "Intro call — CANARY-VISITOR",
           dtstart=f"{_d(0)}T110000Z", dtend=f"{_d(0)}T113000Z",
           extra=("CLASS:PRIVATE",))
    _link(c, "link-one", "Intro call")
    _book(c, "link-one", "e-booked")
    svc.open_day(DAY, create=True)
    svc.add_day_entry(DAY, entry_id="e-p", kind="task", list_id="work", uid="t-private")
    made = _make(svc, lists=["work"], calendars=["cal-a"], show_focus=True)

    view = _view(svc, made)

    assert "CANARY" not in json.dumps(view)
    tasks = {t["title"]: t["private"] for t in view["lists"][0]["tasks"]}
    assert tasks == {"": True, "Public task": False}
    assert [(e["title"], e["private"]) for e in view["events"]] == [("", True)] * 5
    [row] = view["focus"]["today"]["rows"]
    assert row["title"] == "" and row["private"] is True


def test_view_keys_are_exactly_the_documented_set(svc, clock):
    _seed_everything(svc)
    c = svc._conn
    _event(c, CAL_A, "trip", "Trip", dtstart=_d(1), dtend=_d(3), all_day=True)
    _seed_task(c, LIST_A, "dated", "Dated", due=DAY)
    made = _make(svc, lists=["work"], calendars=["cal-a"], show_focus=True)
    view = _view(svc, made)

    assert set(view) == {"v", "generated_at", "poll_seconds", "day", "days", "focus",
                         "lists", "calendars", "events", "events_more"}
    focus = view["focus"]
    assert set(focus) == {"state", "phase", "phase_length_s", "ends_at",
                          "remaining_s", "today"}
    assert set(focus["today"]) == {"rows", "now", "next"}
    assert focus["today"]["rows"]
    for row in focus["today"]["rows"]:
        assert set(row) == {"key", "title", "done", "list", "due", "all_day", "private"}
    assert view["lists"]
    for lst in view["lists"]:
        assert set(lst) == {"name", "color", "tasks", "more"}
        assert lst["tasks"]
        for task in lst["tasks"]:
            assert set(task) == {"title", "due", "all_day", "depth", "private"}
    assert view["calendars"]
    for cal in view["calendars"]:
        assert set(cal) == {"name", "color"}
    assert len(view["events"]) == 2
    for ev in view["events"]:
        assert set(ev) == {"title", "start", "end", "all_day", "calendar", "private"}


def test_due_values_reach_the_view_in_the_viewers_terms(svc, clock):
    c = svc._conn
    store.update_settings(c, {"home_timezone": "Europe/Berlin"})
    _seed_task(c, LIST_A, "by-date", "By date", due=_d(1, "-"))
    _seed_task(c, LIST_A, "utc", "UTC", due_utc=f"{_d(0)}T150000Z")
    _task(c, LIST_A, "floating", "Floating", f"DUE:{_d(0)}T090000")
    svc.open_day(DAY, create=True)
    for uid in ("by-date", "utc", "floating"):
        svc.add_day_entry(DAY, entry_id=f"e-{uid}", kind="task", list_id="work", uid=uid)
    made = _make(svc, lists=["work"], show_focus=True)

    view = _view(svc, made)

    # A floating time is the owner's wall clock, sent as the instant it names.
    berlin_nine = (datetime.fromisoformat(f"{DAY}T09:00:00").replace(
        tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    expected = {
        "By date": (_d(1, "-"), True),
        "UTC": (f"{DAY}T15:00:00.000Z", False),
        "Floating": (berlin_nine, False),
    }
    listed = {t["title"]: (t["due"], t["all_day"]) for t in view["lists"][0]["tasks"]}
    planned = {r["title"]: (r["due"], r["all_day"])
               for r in view["focus"]["today"]["rows"]}
    assert listed == expected
    assert planned == expected


def test_open_tasks_only_nested_within_their_list(svc):
    c = svc._conn
    _seed_task(c, LIST_A, "parent", "Parent")
    _seed_task(c, LIST_A, "child", "Child", parent="parent")
    _seed_task(c, LIST_A, "closed-parent", "Closed parent", status="COMPLETED")
    _seed_task(c, LIST_A, "orphan", "Open under a closed parent", parent="closed-parent")
    _seed_task(c, LIST_A, "foreign-child", "Child of a foreign parent", parent="foreign")
    _seed_task(c, LIST_B, "foreign", "CANARY-FOREIGN-PARENT")
    _seed_task(c, LIST_A, "cancelled", "CANARY-CANCELLED", status="CANCELLED")
    _seed_task(c, LIST_A, "parked", "CANARY-PARKED")
    store.set_sidecar(c, LIST_A, "parked", parked_at="2026-08-20T08:00:00.000Z")
    _seed_task(c, LIST_A, "loop-a", "Loop A", parent="loop-b")
    _seed_task(c, LIST_A, "loop-b", "Loop B", parent="loop-a")
    for i, uid in enumerate(("d0", "d1", "d2", "d3", "d4")):
        _seed_task(c, LIST_A, uid, f"Depth {i}", parent=f"d{i - 1}" if i else None)
    made = _make(svc, lists=["work"])

    [work] = _view(svc, made)["lists"]
    depth = {t["title"]: t["depth"] for t in work["tasks"]}
    assert "CANARY" not in json.dumps(work) and "Closed parent" not in depth
    assert depth["Parent"] == 0 and depth["Child"] == 1
    assert depth["Open under a closed parent"] == 0
    assert depth["Child of a foreign parent"] == 0
    assert depth["Loop A"] == 0 and depth["Loop B"] == 0
    assert [depth[f"Depth {i}"] for i in range(5)] == [0, 1, 2, 3, 3]
    assert work["more"] == 0

    for i in range(share_mod.MAX_TASKS_PER_LIST):
        _seed_task(c, LIST_B, f"many-{i:03d}", f"Task {i:03d}")
    [home] = _view(svc, _make(svc, lists=["home"]))["lists"]
    assert len(home["tasks"]) == share_mod.MAX_TASKS_PER_LIST
    assert home["more"] == 1


def test_titles_bounded_and_colours_validated(svc):
    c = svc._conn
    _seed_task(c, LIST_A, "long", "x")
    _seed_task(c, LIST_B, "lines", "x")
    c.execute("UPDATE items SET summary=? WHERE uid='long'", ("y" * 4000,))
    c.execute("UPDATE items SET summary=? WHERE uid='lines'", ("Line one\nLine two",))
    store.upsert_collection(
        c, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"},
                          color="url(x)"))
    store.upsert_collection(
        c, CollectionInfo(href=LIST_B, displayname="Home", components={"VTODO"},
                          color="#112233"))
    c.execute("INSERT INTO list_settings (collection_href, color) VALUES (?, ?)",
              (LIST_B, "#AABBCC"))
    # In the owner's order, which with no manual order is by name.
    home, work = _view(svc, _make(svc, lists=["work", "home"]))["lists"]
    assert work["tasks"][0]["title"] == "y" * share_mod.TITLE_CHARS
    assert home["tasks"][0]["title"] == "Line one Line two"
    assert work["color"] is None
    # The owner's own choice wins over the one the server reports.
    assert home["color"] == "#AABBCC"


# ── the service: the presence card ──────────────────────────────────────────

def _plan_today(svc_) -> dict[str, str]:
    """Today's plan: a habit, a note, a task from an unshared list, then the
    shared tasks A and B, in that order. Returns the entry ids by role."""
    c = svc_._conn
    _seed_task(c, LIST_A, "ta", "Task A")
    _seed_task(c, LIST_A, "tb", "Task B")
    _seed_task(c, LIST_B, "tc", "CANARY-UNSHARED-ROW")
    svc_.create_habit(title="CANARY-HABIT")
    svc_.open_day(DAY, create=True)
    svc_.add_day_entry(DAY, entry_id="e-note", kind="note", title="CANARY-NOTE")
    svc_.add_day_entry(DAY, entry_id="e-c", kind="task", list_id="home", uid="tc")
    svc_.add_day_entry(DAY, entry_id="e-a", kind="task", list_id="work", uid="ta")
    svc_.add_day_entry(DAY, entry_id="e-b", kind="task", list_id="work", uid="tb")
    [habit] = [r["entry_id"] for r in store.get_day_entries(c, DAY) if r["kind"] == "habit"]
    return {"habit": habit, "note": "e-note", "c": "e-c", "a": "e-a", "b": "e-b"}


def _session_on(svc_, entry_id: str | None, *, passed=(), running: bool = True,
                elapsed: int = 0) -> None:
    now = _stamp_now()
    store.put_focus_session(
        svc_._conn, DAY, phase="focus", phase_length_s=1500, phase_elapsed_s=elapsed,
        running_since=now if running else None, intervals_done=0, entry_id=entry_id,
        passed=json.dumps(list(passed)), started_at=now, ended_at=None)
    # SQLite's clock, which the `_focus_now` seam does not move, so it is set.
    svc_._conn.execute("UPDATE focus_session SET updated_at=? WHERE day=?", (now, DAY))


def _key(made: dict, entry_id: str) -> str:
    return share_mod.row_key(made["id"], entry_id)


def test_today_rows_carry_only_shared_task_rows(svc, clock):
    ids = _plan_today(svc)
    _seed_task(svc._conn, LIST_A, "tp", "CANARY-PARKED-ROW")
    svc.add_day_entry(DAY, entry_id="e-p", kind="task", list_id="work", uid="tp")
    store.set_sidecar(svc._conn, LIST_A, "tp", parked_at="2026-08-20T08:00:00.000Z")
    made = _make(svc, lists=["work"], show_focus=True)

    first, second = _view(svc, made), _view(svc, made)

    rows = first["focus"]["today"]["rows"]
    assert [r["title"] for r in rows] == ["Task A", "Task B"]
    assert [r["key"] for r in rows] == [_key(made, ids["a"]), _key(made, ids["b"])]
    assert all(re.fullmatch(r"[0-9a-f]{16}", r["key"]) for r in rows)
    assert second["focus"]["today"]["rows"] == rows
    assert {r["list"] for r in rows} == {0} and not any(r["done"] for r in rows)
    assert "CANARY" not in json.dumps(first)


def test_now_and_next_follow_the_owners_queue_within_shared_rows(svc, clock):
    ids = _plan_today(svc)
    made = _make(svc, lists=["work"], show_focus=True)
    a, b = _key(made, ids["a"]), _key(made, ids["b"])

    def today() -> dict:
        focus = _view(svc, made)["focus"]
        return {"state": focus["state"], "now": focus["today"]["now"],
                "next": focus["today"]["next"]}

    # No session: the plan's open shared rows, in plan order.
    assert today() == {"state": "idle", "now": None, "next": [a, b]}
    # On an unshared row the clock shows and nothing names the row.
    _session_on(svc, ids["c"])
    assert today() == {"state": "focusing", "now": None, "next": [a, b]}
    _session_on(svc, ids["a"])
    assert today() == {"state": "focusing", "now": a, "next": [b]}
    # FocusView's wrap: after B comes A, which is still open.
    _session_on(svc, ids["b"])
    assert today() == {"state": "focusing", "now": b, "next": [a]}
    # Set-aside rows are skipped.
    _session_on(svc, ids["c"], passed=[ids["a"]])
    assert today() == {"state": "focusing", "now": None, "next": [b]}
    # A cursor that names nothing open is not replaced by the head of the
    # queue: `now` is only ever the row the session stored.
    _session_on(svc, None, passed=[ids["habit"], ids["note"], ids["c"]])
    assert today() == {"state": "focusing", "now": None, "next": [a, b]}
    _session_on(svc, ids["habit"])
    assert today() == {"state": "focusing", "now": None, "next": [a, b]}
    # A done row stays on Today, ticked, and leaves the queue.
    svc._conn.execute("UPDATE items SET status='COMPLETED' WHERE uid='ta'")
    _session_on(svc, ids["c"])
    assert today() == {"state": "focusing", "now": None, "next": [b]}
    assert [r["done"] for r in _view(svc, made)["focus"]["today"]["rows"]] == [True, False]


def test_the_view_is_stable_between_polls(svc, clock):
    ids = _plan_today(svc)
    made = _make(svc, lists=["work"], show_focus=True)
    for running in (True, False):
        _session_on(svc, ids["a"], running=running, elapsed=0 if running else 300)
        first = _view(svc, made)
        clock.tick(10)
        second = _view(svc, made)
        assert first["generated_at"] != second["generated_at"]
        assert {**first, "generated_at": None} == {**second, "generated_at": None}
        assert first["focus"]["state"] == ("focusing" if running else "paused")


def test_poll_seconds_follows_focus(svc, clock):
    ids = _plan_today(svc)
    made = _make(svc, lists=["work"], show_focus=True)
    assert _view(svc, made)["poll_seconds"] == share_mod.POLL_IDLE_S
    _session_on(svc, ids["a"])
    assert _view(svc, made)["poll_seconds"] == share_mod.POLL_LIVE_S
    svc.update_share(made["id"], {"show_focus": False})
    assert _view(svc, made)["poll_seconds"] == share_mod.POLL_IDLE_S
    svc.update_share(made["id"], {"show_focus": True})
    svc._conn.execute("UPDATE focus_session SET ended_at=? WHERE day=?", (_stamp_now(), DAY))
    assert _view(svc, made)["poll_seconds"] == share_mod.POLL_IDLE_S


def test_show_focus_off_sends_no_focus_and_no_plan(svc, clock):
    ids = _plan_today(svc)
    _session_on(svc, ids["a"])
    made = _make(svc, lists=["work"])
    view = _view(svc, made)
    assert view["focus"] is None
    assert _key(made, ids["a"]) not in json.dumps(view)
    # The list itself is still shared.
    assert [t["title"] for t in view["lists"][0]["tasks"]] == ["Task A", "Task B"]


# ── the service: a share READS ──────────────────────────────────────────────

def test_a_share_never_opens_or_previews_a_day(svc, monkeypatch):
    _seed_task(svc._conn, LIST_A, "due", "Due today", due=DAY)
    made = _make(svc, lists=["work"], show_focus=True)
    real_open = svc.open_day

    def open_day(day, *, create):
        assert not create, "a share opened a day"
        return real_open(day, create=create)

    def preview_day(*_a, **_k):
        raise AssertionError("a share previewed a day")

    monkeypatch.setattr(svc, "open_day", open_day)
    monkeypatch.setattr(svc, "preview_day", preview_day)
    view = _view(svc, made)
    # A preview would have put the task on Today; there is no plan, so nothing.
    assert view["focus"]["today"]["rows"] == []
    assert [t["title"] for t in view["lists"][0]["tasks"]] == ["Due today"]
    assert store.day_is_opened(svc._conn, DAY) is False
    assert store.get_day_entries(svc._conn, DAY) == []


def _snapshot(conn) -> dict[str, list[tuple]]:
    out = {}
    for table in ("day_plan", "day_plan_opened", "day_ritual", "focus_session",
                  "habits", "sidecar", "items"):
        # The table names are literals in this file, never input.
        out[table] = [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")]  # nosec B608
    out["shares"] = [tuple(r) for r in conn.execute(
        "SELECT id, token, name, lists, calendars, show_focus, enabled, horizon_days, "
        "cv, created_at, updated_at FROM shares")]
    return out


def test_a_share_view_writes_nothing_but_last_seen(svc, clock):
    ids = _plan_today(svc)
    _session_on(svc, ids["a"])
    made = _make(svc, lists=["work", "home"], calendars=["cal-a"], show_focus=True)
    before = _snapshot(svc._conn)
    for _ in range(3):
        _view(svc, made)
        clock.tick(90)
    assert _snapshot(svc._conn) == before
    assert svc.get_share(made["id"])["last_seen_at"] is not None


def test_last_seen_is_stamped_at_most_once_a_minute(svc, clock):
    made = _make(svc)

    def seen() -> str | None:
        return svc.get_share(made["id"])["last_seen_at"]

    first = _stamp_now()
    _view(svc, made)
    assert seen() == first
    clock.tick(30)
    _view(svc, made)
    assert seen() == first
    clock.tick(31)
    later = _stamp_now()
    _view(svc, made)
    assert seen() == later


def test_a_failed_last_seen_stamp_does_not_cost_the_view(svc, monkeypatch):
    """The one write on the path is bookkeeping: a locked database must not turn
    a built view into an error for the person reading it."""
    made = _make(svc, lists=["work"])
    _seed_task(svc._conn, LIST_A, "ta", "Task A")

    class Locked:
        """A connection whose every write fails, wrapping a real one."""

        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    real = store.touch_share
    monkeypatch.setattr(store, "touch_share",
                        lambda conn, share_id, **kw: real(Locked(conn), share_id, **kw))
    view = _view(svc, made)
    assert [t["title"] for t in view["lists"][0]["tasks"]] == ["Task A"]
    assert svc.get_share(made["id"])["last_seen_at"] is None


# ── the service: one answer for every refusal ───────────────────────────────

def test_unknown_disabled_rotated_deleted_and_malformed_tokens_read_as_none(
        svc, monkeypatch):
    on = _make(svc)
    off = _make(svc, enabled=False)
    rotated = _make(svc)
    deleted = _make(svc)
    svc.rotate_share_token(rotated["id"])
    svc.delete_share(deleted["id"])
    assert _view(svc, on) is not None

    looked_up: list[str] = []
    real = store.get_share_by_token
    monkeypatch.setattr(store, "get_share_by_token",
                        lambda conn, token: looked_up.append(token) or real(conn, token))
    for made in (off, rotated, deleted):
        assert _view(svc, made) is None
    assert svc.share_view("u" * 43) is None
    assert len(looked_up) == 4

    looked_up.clear()
    for bad in ("a" * 42, "a" * 44, "a" * 42 + "/", "../x", "", on["token"] + " ",
                None, 43):
        assert svc.share_view(bad) is None
    # Refused on its shape, before the database was asked.
    assert looked_up == []

    # Switching off is a 404 on the next read, and switching on brings it back.
    svc.update_share(on["id"], {"enabled": False})
    assert _view(svc, on) is None
    svc.update_share(on["id"], {"enabled": True})
    assert _view(svc, on) is not None


def test_rotation_keeps_the_share_and_clears_last_seen(svc):
    made = _make(svc, lists=["work"])
    _view(svc, made)
    assert svc.get_share(made["id"])["last_seen_at"] is not None
    rotated = svc.rotate_share_token(made["id"])
    assert rotated["id"] == made["id"] and rotated["token"] != made["token"]
    assert rotated["lists"] == ["work"] and rotated["last_seen_at"] is None
    assert _view(svc, made) is None
    assert _view(svc, rotated) is not None
    assert svc.rotate_share_token("nope") is None


def test_preview_ignores_enabled_and_writes_nothing(svc):
    _seed_task(svc._conn, LIST_A, "ta", "Task A")
    made = _make(svc, lists=["work"], enabled=False)
    assert _view(svc, made) is None
    preview = svc.preview_share(made["id"])
    assert [t["title"] for t in preview["lists"][0]["tasks"]] == ["Task A"]
    assert svc.get_share(made["id"])["last_seen_at"] is None
    # The same builder: switched on, the person sees exactly the preview.
    svc.update_share(made["id"], {"enabled": True})
    assert {**_view(svc, made), "generated_at": None} == \
        {**svc.preview_share(made["id"]), "generated_at": None}
    assert svc.preview_share("nope") is None


# ── the service: a password change switches every share off ─────────────────

def test_a_password_change_switches_a_share_off(svc):
    svc.credential_version = lambda: "gen-1"
    made = _make(svc, lists=["work"])
    assert store.get_share(svc._conn, made["id"])["cv"] == "gen-1"
    assert _view(svc, made) is not None

    svc.credential_version = lambda: "gen-2"
    assert _view(svc, made) is None
    dto = svc.get_share(made["id"])
    assert dto["enabled"] is False and dto["switched_off_by_password"] is True
    # The owner can still look.
    assert svc.preview_share(made["id"]) is not None

    # A new link is not the owner switching it on.
    rotated = svc.rotate_share_token(made["id"])
    assert rotated["enabled"] is False and rotated["switched_off_by_password"] is True
    assert _view(svc, rotated) is None
    # Nor is any other edit.
    assert svc.update_share(made["id"], {"name": "Alex"})["switched_off_by_password"]

    revived = svc.update_share(made["id"], {"enabled": True})
    assert revived["enabled"] is True and revived["switched_off_by_password"] is False
    assert store.get_share(svc._conn, made["id"])["cv"] == "gen-2"
    assert _view(svc, revived) is not None


def test_a_share_switched_off_by_hand_is_not_off_by_password(svc):
    svc.credential_version = lambda: "gen-1"
    made = _make(svc)
    svc.update_share(made["id"], {"enabled": False})
    svc.credential_version = lambda: "gen-2"
    dto = svc.get_share(made["id"])
    assert dto["enabled"] is False and dto["switched_off_by_password"] is False
    # Switching off does not restamp, and switching on does.
    assert store.get_share(svc._conn, made["id"])["cv"] == "gen-1"
    assert svc.update_share(made["id"], {"enabled": True})["enabled"] is True


def test_with_authentication_off_a_share_works(svc):
    # The service's own default: no credentials, so nothing to rotate away from.
    assert svc.credential_version() == ""
    made = _make(svc)
    assert store.get_share(svc._conn, made["id"])["cv"] == ""
    assert _view(svc, made) is not None
    assert svc.get_share(made["id"])["enabled"] is True


# ── the service: events ─────────────────────────────────────────────────────

def test_events_window_times_and_cancellations(svc):
    c = svc._conn
    store.update_settings(c, {"home_timezone": "Europe/Berlin"})
    # Noon floating on each day: inside the widened horizon, DAY-1 .. DAY+7.
    for offset in (-2, -1, 0, 6, 7, 8):
        _event(c, CAL_A, f"d{offset}", f"Day {offset}",
               dtstart=f"{_d(offset)}T120000", dtend=f"{_d(offset)}T130000")
    _event(c, CAL_A, "cancelled", "CANARY-CANCELLED", dtstart=f"{_d(0)}T150000",
           dtend=f"{_d(0)}T160000", extra=("STATUS:CANCELLED",))
    _event(c, CAL_A, "floating", "Floating", dtstart=f"{_d(1)}T090000",
           dtend=f"{_d(1)}T100000")
    _event(c, CAL_A, "offset", "Offset", dtstart=f"TZID=Pacific/Kiritimati:{_d(2)}T090000",
           dtend=f"TZID=Pacific/Kiritimati:{_d(2)}T100000")
    _event(c, CAL_A, "span", "Span", dtstart=_d(3), dtend=_d(5), all_day=True)
    _event(c, CAL_A, "duration", "Duration", dtstart=f"{_d(4)}T080000Z", dtend=None,
           extra=("DURATION:PT1H30M",))
    made = _make(svc, calendars=["cal-a"])

    view = _view(svc, made)
    by = {e["title"]: e for e in view["events"]}

    assert {"Day -1", "Day 0", "Day 6", "Day 7"} <= set(by)
    assert not {"Day -2", "Day 8", "CANARY-CANCELLED"} & set(by)
    assert by["Floating"]["start"] == f"{_d(1, '-')}T07:00:00.000Z"
    assert by["Floating"]["end"] == f"{_d(1, '-')}T08:00:00.000Z"
    assert by["Offset"]["start"] == f"{_d(1, '-')}T19:00:00.000Z"
    assert by["Span"] == {"title": "Span", "start": _d(3, "-"), "end": _d(5, "-"),
                          "all_day": True, "calendar": 0, "private": False}
    assert by["Duration"]["end"] == f"{_d(4, '-')}T09:30:00.000Z"
    assert not re.search(r"[+-]\d\d:\d\d", json.dumps(view))
    # In time order, and the day's all-day events ahead of its timed ones.
    assert [e["title"] for e in view["events"]][:3] == ["Day -1", "Day 0", "Floating"]
    assert view["events_more"] == 0


def test_an_all_day_duration_event_covers_its_days(svc):
    c = svc._conn
    # An all-day DTSTART with DURATION and no DTEND: the duration is the span.
    _event(c, CAL_A, "starts-tomorrow", "Starts tomorrow", dtstart=_d(-1), dtend=None,
           all_day=True, extra=("DURATION:P3D",))
    _event(c, CAL_A, "under-way", "Under way", dtstart=_d(-3), dtend=None,
           all_day=True, extra=("DURATION:P5D",))
    _event(c, CAL_A, "zero", "Zero", dtstart=_d(0), dtend=None,
           all_day=True, extra=("DURATION:PT0S",))
    made = _make(svc, calendars=["cal-a"])

    by = {e["title"]: e for e in _view(svc, made)["events"]}

    # The END is the EXCLUSIVE date, as for an event with a DTEND.
    assert by["Starts tomorrow"]["start"] == _d(-1, "-")
    assert by["Starts tomorrow"]["end"] == _d(2, "-")
    # DAY-3 .. DAY+1 is still on the agenda today.
    assert by["Under way"]["start"] == _d(-3, "-")
    assert by["Under way"]["end"] == _d(2, "-")
    assert by["Zero"]["all_day"] is True and by["Zero"]["end"] is None


def test_the_horizon_is_the_shares_own(svc):
    c = svc._conn
    for offset in (-2, -1, 0, 1, 2, 13, 14, 15, 27, 28, 29):
        _event(c, CAL_A, f"d{offset}", f"Day {offset}",
               dtstart=f"{_d(offset)}T120000Z", dtend=f"{_d(offset)}T130000Z")
    made = _make(svc, calendars=["cal-a"])
    shown = {}
    for days in share_mod.HORIZONS:
        svc.update_share(made["id"], {"horizon_days": days})
        view = _view(svc, made)
        assert view["days"] == days
        shown[days] = [e["title"] for e in view["events"]]
    assert shown[1] == ["Day -1", "Day 0", "Day 1"]
    assert shown[14][-1] == "Day 14" and "Day 15" not in shown[14]
    assert shown[28][0] == "Day -1" and shown[28][-1] == "Day 28"
    # A row edited by hand to a horizon nobody offers reads as the default.
    c.execute("UPDATE shares SET horizon_days=3650 WHERE id=?", (made["id"],))
    assert _view(svc, made)["days"] == share_mod.DEFAULT_HORIZON


def test_the_event_cap_counts_the_rest(svc):
    for i in range(share_mod.MAX_EVENTS + 2):
        _seed_event(svc._conn, CAL_A, f"e{i:04d}", f"Event {i:04d}",
                    start=f"{DAY}T{9 + i // 600:02d}:{(i // 10) % 60:02d}:{i % 10:02d}")
    view = _view(svc, _make(svc, calendars=["cal-a"]))
    assert len(view["events"]) == share_mod.MAX_EVENTS
    assert view["events_more"] == 2


def test_recurrence_overrides_and_unexpandable_series(svc, monkeypatch):
    c = svc._conn
    _event(c, CAL_A, "series", "Standup", dtstart=f"{_d(0)}T090000Z",
           dtend=f"{_d(0)}T093000Z", rrule="FREQ=DAILY;COUNT=3",
           overrides=((f"RECURRENCE-ID:{_d(1)}T090000Z", f"DTSTART:{_d(1)}T100000Z",
                       f"DTEND:{_d(1)}T103000Z", "SUMMARY:Standup, moved"),
                      (f"RECURRENCE-ID:{_d(2)}T090000Z", f"DTSTART:{_d(2)}T090000Z",
                       f"DTEND:{_d(2)}T093000Z", "STATUS:CANCELLED")))
    made = _make(svc, calendars=["cal-a"])
    assert [(e["title"], e["start"]) for e in _view(svc, made)["events"]] == [
        ("Standup", f"{_d(0, '-')}T09:00:00.000Z"),
        ("Standup, moved", f"{_d(1, '-')}T10:00:00.000Z"),
    ]

    def boom(*_a, **_k):
        raise ValueError("unexpandable")

    monkeypatch.setattr(service_mod.recur, "expand_occurrences", boom)
    # The calendar tab falls back to the master row; an agenda would put it on
    # the wrong day, so a share shows nothing for the series instead.
    assert _view(svc, made)["events"] == []


def test_booked_events_show_the_link_title_not_the_visitor(svc):
    c = svc._conn
    _link(c, "link-one", "Intro call")
    _link(c, "link-two", "Office hours")
    _event(c, CAL_A, "booked", "Intro call — Visitor Vera",
           dtstart=f"{_d(0)}T100000Z", dtend=f"{_d(0)}T103000Z")
    _book(c, "link-one", "booked")
    _event(c, CAL_A, "orphaned", "Old link — Visitor Vera",
           dtstart=f"{_d(0)}T110000Z", dtend=f"{_d(0)}T113000Z")
    _book(c, "deleted-link", "orphaned")
    # No ledger row at all, but the summary is still a booking's.
    _event(c, CAL_A, "unledgered", "Office hours — Visitor Vera",
           dtstart=f"{_d(0)}T120000Z", dtend=f"{_d(0)}T123000Z")
    _event(c, CAL_A, "plain", "Office party",
           dtstart=f"{_d(0)}T130000Z", dtend=f"{_d(0)}T140000Z")
    view = _view(svc, _make(svc, calendars=["cal-a"]))
    assert [e["title"] for e in view["events"]] == \
        ["Intro call", "", "Office hours", "Office party"]
    assert "Vera" not in json.dumps(view)


def test_a_booking_moved_into_a_shared_calendar_still_hides_the_visitor(svc):
    c = svc._conn
    _link(c, "link-one", "Intro call")
    # Booked into CAL_B, then moved to CAL_A: the ledger still names CAL_B,
    # because `move_event` never updates it.
    _book(c, "link-one", "moved", calendar_href=CAL_B)
    _event(c, CAL_A, "moved", "Consultation — Visitor Vera",
           dtstart=f"{_d(0)}T100000Z", dtend=f"{_d(0)}T103000Z")
    view = _view(svc, _make(svc, calendars=["cal-a"]))
    assert [e["title"] for e in view["events"]] == ["Intro call"]
    assert "Vera" not in json.dumps(view)


# ── HTTP: the owner's routes and the stranger's ─────────────────────────────

PASSWORD = "testpass123"


def _api_settings(tmp_path, **over) -> Settings:
    # The DAV URL points at a closed port: no share route may reach the wire.
    return dataclasses.replace(Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=str(tmp_path / "shares.db"), sync_interval_s=3600,
        request_timeout_s=1, static_dir="/nonexistent", hook_secret="h",
        auth_enabled=True, auth_user="admin", auth_password_hash="",
        auth_password=PASSWORD, session_secret="s" * 40, session_ttl_s=3600,
        cookie_secure=False, access_required=False, access_team_domain="",
        access_aud="",
    ), **over)


def _login(c: TestClient, password: str = PASSWORD) -> None:
    assert c.post("/api/login", json={"username": "admin", "password": password}
                  ).status_code == 200


def _seed_app(c: TestClient) -> None:
    """The collections and a little data, written straight into the cache the
    app's own service reads, since there is no Radicale to sync them from."""
    conn = c.app.state.service._conn
    store.upsert_collection(
        conn, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"}))
    store.upsert_collection(
        conn, CollectionInfo(href=CAL_A, displayname="Personal", components={"VEVENT"}))
    _seed_task(conn, LIST_A, "ta", "Draft the memo")
    _event(conn, CAL_A, "ea", "Standup", dtstart=f"{_d(0)}T090000Z",
           dtend=f"{_d(0)}T093000Z")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(SmylteService, "_today", lambda self: DAY)
    with TestClient(create_app(_api_settings(tmp_path))) as c:
        _login(c)
        _seed_app(c)
        yield c


@pytest.fixture
def built(tmp_path, monkeypatch):
    """The `api` app with a frontend build in place, so the page shell is a
    file rather than the "frontend not built" 404."""
    monkeypatch.setattr(SmylteService, "_today", lambda self: DAY)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        "<!doctype html><html><body><div id=root></div></body></html>", encoding="utf-8")
    with TestClient(create_app(_api_settings(tmp_path, static_dir=str(static)))) as c:
        _login(c)
        yield c


def _public(c: TestClient, token: str, **kw):
    return c.get(f"/api/public/share/{token}", **kw)


def _privacy_headers(r) -> None:
    assert r.headers["cache-control"] == "no-store, private, max-age=0"
    assert r.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_share_routes_need_a_session_and_the_view_does_not(api):
    made = api.post("/api/shares", json={"name": "Sam", "lists": ["work"]})
    assert made.status_code == 201
    made = made.json()
    share_id, token = made["id"], made["token"]
    assert api.get("/api/shares").json() == [made]
    preview = api.get(f"/api/shares/{share_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store, private"
    assert [t["title"] for t in preview.json()["lists"][0]["tasks"]] == ["Draft the memo"]

    api.cookies.clear()
    # The owner's routes are behind the session like everything else...
    for method, path in (("GET", "/api/shares"), ("POST", "/api/shares"),
                         ("GET", f"/api/shares/{share_id}/preview"),
                         ("PATCH", f"/api/shares/{share_id}"),
                         ("POST", f"/api/shares/{share_id}/rotate"),
                         ("DELETE", f"/api/shares/{share_id}")):
        assert api.request(method, path).status_code == 401, (method, path)
    # ...and the view is not: the person it is for has no session.
    view = _public(api, token)
    assert view.status_code == 200
    assert [t["title"] for t in view.json()["lists"][0]["tasks"]] == ["Draft the memo"]


def test_the_owners_routes_edit_rotate_and_delete_by_id(api):
    made = api.post("/api/shares", json={"name": "Sam"}).json()
    share_id = made["id"]
    edited = api.patch(f"/api/shares/{share_id}",
                       json={"calendars": ["cal-a"], "horizon_days": 14})
    assert edited.status_code == 200
    assert edited.json()["calendars"] == ["cal-a"] and edited.json()["horizon_days"] == 14
    assert _public(api, made["token"]).json()["days"] == 14

    rotated = api.post(f"/api/shares/{share_id}/rotate").json()
    assert rotated["id"] == share_id and rotated["token"] != made["token"]
    assert _public(api, made["token"]).status_code == 404
    assert _public(api, rotated["token"]).status_code == 200

    assert api.delete(f"/api/shares/{share_id}").status_code == 204
    assert _public(api, rotated["token"]).status_code == 404
    for r in (api.delete(f"/api/shares/{share_id}"),
              api.patch(f"/api/shares/{share_id}", json={"name": "X"}),
              api.post(f"/api/shares/{share_id}/rotate"),
              api.get(f"/api/shares/{share_id}/preview")):
        assert r.status_code == 404 and r.json() == {"detail": f"unknown share {share_id}"}


def test_patch_share_refuses_explicit_nulls(api):
    share_id = api.post("/api/shares", json={"name": "Sam"}).json()["id"]
    r = api.patch(f"/api/shares/{share_id}", json={"lists": None, "horizon_days": None})
    assert r.status_code == 422
    assert r.json()["detail"] == "these fields cannot be null: horizon_days, lists"
    # Refused whole: nothing that came with the nulls landed.
    r = api.patch(f"/api/shares/{share_id}", json={"name": "Alex", "enabled": None})
    assert r.status_code == 422
    assert api.get("/api/shares").json()[0]["name"] == "Sam"


@pytest.mark.parametrize("body", [
    {"name": ""},
    {"name": "   "},
    {"lists": ["work"]},
    {"name": "Sam", "lists": [f"l{i}" for i in range(65)]},
    {"name": "Sam", "calendars": [f"c{i}" for i in range(65)]},
    {"name": "Sam", "lists": "work"},
    {"name": "Sam", "calendars": {"cal-a": True}},
    {"name": "Sam", "horizon_days": 3},
    {"name": "Sam", "horizon_days": True},
    {"name": "Sam", "horizon_days": "7"},
    {"name": "x" * 101},
])
def test_create_share_validates(api, body):
    assert api.post("/api/shares", json=body).status_code == 422
    assert api.get("/api/shares").json() == []


def test_every_refusal_is_one_identical_404(api):
    def make(**fields):
        return api.post("/api/shares", json={"name": "Sam", **fields}).json()

    off = make(enabled=False)
    rotated = make()
    deleted = make()
    api.post(f"/api/shares/{rotated['id']}/rotate")
    api.delete(f"/api/shares/{deleted['id']}")
    api.cookies.clear()

    answers = [_public(api, t) for t in (
        "u" * 43, off["token"], rotated["token"], deleted["token"],
        "a" * 42, "a" * 44, "nope")]

    def shape(r):
        headers = {k: v for k, v in r.headers.items()
                   if k not in ("date", "content-length")}
        return r.status_code, r.content, headers

    first = shape(answers[0])
    assert first[0] == 404 and json.loads(first[1]) == {"detail": "unknown share"}
    for r in answers[1:]:
        assert shape(r) == first, r.url


def test_public_share_responses_carry_the_privacy_headers(built, monkeypatch):
    token = built.post("/api/shares", json={"name": "Sam"}).json()["token"]
    built.cookies.clear()

    ok = _public(built, token)
    assert ok.status_code == 200
    unchanged = _public(built, token, headers={"If-None-Match": ok.headers["etag"]})
    assert unchanged.status_code == 304
    missing = _public(built, "u" * 43)
    assert missing.status_code == 404
    for r in (ok, unchanged, missing):
        _privacy_headers(r)

    # The page shell, both spellings and both methods, with no token lookup:
    # an unknown link gets the same page as a live one.
    for path in (f"/share/{token}", f"/share/{token}/", "/share/" + "u" * 43):
        for method in ("GET", "HEAD"):
            r = built.request(method, path)
            assert r.status_code == 200, (method, path)
            _privacy_headers(r)
    assert "<div id=root>" in built.get(f"/share/{token}").text

    # No other method on the JSON route answers differently, or without the
    # headers, for a real token than for an unknown one.
    for method in ("HEAD", "POST", "OPTIONS"):
        for t in (token, "u" * 43):
            r = built.request(method, f"/api/public/share/{t}")
            assert r.status_code == 404, (method, t)
            _privacy_headers(r)
            if method != "HEAD":
                assert r.content == b'{"detail":"unknown share"}', (method, t)

    def boom(self, row, *, now):
        raise RuntimeError("nope")

    with monkeypatch.context() as m:
        m.setattr(SmylteService, "_build_share_view", boom)
        failed = _public(built, token)
    assert failed.status_code == 500
    _privacy_headers(failed)

    for _ in range(40):
        limited = _public(built, "u" * 43)
        if limited.status_code == 429:
            break
    assert limited.status_code == 429
    _privacy_headers(limited)
    assert int(limited.headers["retry-after"]) > 0


def test_the_page_shell_carries_the_privacy_headers_with_no_built_index(api):
    # The `api` fixture points static_dir at nothing, so the shell is a 404, and
    # that refusal is still a share response.
    r = api.get("/share/" + "u" * 43)
    assert r.status_code == 404
    _privacy_headers(r)


def test_the_share_view_answers_304_to_a_matching_etag(api, clock):
    made = api.post("/api/shares", json={"name": "Sam", "lists": ["work"]}).json()
    first = _public(api, made["token"])
    etag = first.headers["etag"]
    clock.tick(10)
    again = _public(api, made["token"], headers={"If-None-Match": etag})
    # `generated_at` moved; nothing the person sees did, so nothing is sent.
    assert again.status_code == 304 and not again.content
    assert again.headers["etag"] == etag

    _seed_task(api.app.state.service._conn, LIST_A, "tb", "Call the printer")
    changed = _public(api, made["token"], headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    # GET only: a HEAD never builds the payload to send none of it.
    head = api.head(f"/api/public/share/{made['token']}")
    assert head.status_code != 200 and "etag" not in head.headers


def test_the_public_share_route_is_rate_limited(api):
    token = api.post("/api/shares", json={"name": "Sam"}).json()["token"]
    api.cookies.clear()
    for n in range(400):
        r = _public(api, token)
        if r.status_code == 429:
            break
    assert r.status_code == 429, "the public share route has no rate limit"
    # A share polls every 15 s, so the ceiling is well above one viewer's need.
    assert n == 300
    assert int(r.headers["retry-after"]) > 0
    assert r.headers["cache-control"] == "no-store, private, max-age=0"
    # A lockout, not a per-request check that resets.
    assert _public(api, token).status_code == 429


def test_token_misses_lock_out_guessing(api):
    token = api.post("/api/shares", json={"name": "Sam"}).json()["token"]
    api.cookies.clear()
    for i in range(30):
        assert _public(api, f"{i:043d}").status_code == 404
    locked = _public(api, token)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    _privacy_headers(locked)


def test_the_owners_cookie_does_not_change_the_public_view(api):
    made = api.post("/api/shares", json={"name": "Sam", "lists": ["work"],
                                         "calendars": ["cal-a"]}).json()
    as_owner = _public(api, made["token"])
    api.cookies.clear()
    as_stranger = _public(api, made["token"])
    assert as_owner.status_code == as_stranger.status_code == 200
    assert as_owner.headers["etag"] == as_stranger.headers["etag"]
    assert {**as_owner.json(), "generated_at": None} == \
        {**as_stranger.json(), "generated_at": None}


def test_internal_errors_are_generic(api, monkeypatch):
    token = api.post("/api/shares", json={"name": "Sam"}).json()["token"]

    def boom(self, row, *, now):
        # The app's KeyError handler would answer 404 with this in the body.
        raise KeyError("/u/secret-href/")

    monkeypatch.setattr(SmylteService, "_build_share_view", boom)
    r = _public(api, token)
    assert r.status_code == 500
    assert r.json() == {"detail": "share unavailable"}
    assert "secret-href" not in r.text and "secret-href" not in str(r.headers)


def test_the_share_route_never_reaches_the_wire(api):
    """The fixture's DAV URL is a closed port, so a share that went to
    Radicale for anything would fail here rather than answer."""
    made = api.post("/api/shares", json={"name": "Sam", "lists": ["work"],
                                         "calendars": ["cal-a"]}).json()
    api.cookies.clear()
    r = _public(api, made["token"])
    assert r.status_code == 200
    view = r.json()
    assert [t["title"] for t in view["lists"][0]["tasks"]] == ["Draft the memo"]
    assert [e["title"] for e in view["events"]] == ["Standup"]


def test_a_new_app_password_switches_every_share_off(tmp_path, monkeypatch):
    """The documented response to a leaked password is to change it. A share
    switched on under the old one is somebody else's window onto the account
    that the owner may never have made, so the change switches it off until
    the owner switches it back on."""
    monkeypatch.setattr(SmylteService, "_today", lambda self: DAY)
    settings = _api_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        _login(c)
        _seed_app(c)
        made = c.post("/api/shares", json={"name": "Sam", "lists": ["work"]}).json()
        assert _public(c, made["token"]).status_code == 200

    # Same database; only the password moved.
    changed = dataclasses.replace(settings, auth_password="a-brand-new-password")
    with TestClient(create_app(changed)) as c2:
        gone = _public(c2, made["token"])
        assert gone.status_code == 404 and gone.json() == {"detail": "unknown share"}
        _login(c2, "a-brand-new-password")
        [dto] = c2.get("/api/shares").json()
        assert dto["enabled"] is False and dto["switched_off_by_password"] is True
        # The owner can still see what it would show, and switch it back on.
        assert c2.get(f"/api/shares/{made['id']}/preview").status_code == 200
        revived = c2.patch(f"/api/shares/{made['id']}", json={"enabled": True}).json()
        assert revived["enabled"] is True and revived["switched_off_by_password"] is False
        assert _public(c2, made["token"]).status_code == 200


# ── the connector cannot reach shares ───────────────────────────────────────

class _NoSvc:
    """`build_tools` only reads names; no handler runs."""


def test_no_connector_tool_reaches_shares():
    """A share is a bearer URL to the account, so a connector that could make
    one would let a prompt-injected model hand the owner's day to anybody. No
    tool, adapter or resource reads or writes shares, and this keeps it so."""
    import pathlib

    import smylted.mcp

    names = list(build_tools(McpApi(_NoSvc())))
    assert names, "the tool table is empty — this test is measuring nothing"
    assert not [n for n in names if "share" in n.lower()]
    root = pathlib.Path(smylted.mcp.__file__).parent
    sources = sorted(root.glob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for needle in ("share_view", "create_share", "rotate_share_token", "/share"):
            assert needle not in text, f"{path.name} mentions {needle}"
