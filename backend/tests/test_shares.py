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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from helpers import foreign_raw
from test_day_plan import LIST_A, LIST_B, _seed_task, _settings
from test_displays import CAL_A, _seed_event

from smylted import share as share_mod
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
