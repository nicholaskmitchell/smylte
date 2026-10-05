"""Storage primitives for the mail pipeline — pure sqlite via the `db` fixture,
no Radicale, no network. The pipeline's policy is tested elsewhere; this pins
the guarantees it leans on: one claim per message, a compare-and-swap status
move, rejections that survive, and a candidate search that cannot raise.
"""
from __future__ import annotations

import json

import pytest

from smylted.dav.client import CollectionInfo, Item
from smylted.db import init_db, store
from smylted.ical import extract_from_raw

from helpers import foreign_raw

COL = "/u/tasks/"


def _claim(db, key="mid:a@x", **kw):
    args = dict(message_id="a@x", thread_id="mid:a@x", folder="INBOX", uid=7)
    args.update(kw)
    return store.mail_claim(db, key, **args)


def _suggestion(db, id="s1", **kw):
    fields = dict(
        kind="task", title="Pay the invoice", sender="office@school.example",
        message_key="mid:a@x", thread_id="mid:a@x",
    )
    fields.update(kw)
    return store.mail_insert_suggestion(db, id, fields)


# ── ledger ───────────────────────────────────────────────────────────────────

def test_second_claim_of_the_same_key_loses(db):
    assert _claim(db) is True
    assert _claim(db) is False
    row = store.mail_ledger_get(db, "mid:a@x")
    assert row["outcome"] == "processing"
    assert row["settled_at"] is None
    assert row["folder"] == "INBOX" and row["uid"] == 7


def test_settle_records_the_decision(db):
    _claim(db)
    store.mail_settle(db, "mid:a@x", stage="extract", outcome="suggested",
                      detail="ok", suggestion_id="s1")
    row = store.mail_ledger_get(db, "mid:a@x")
    assert (row["stage"], row["outcome"], row["detail"], row["suggestion_id"]) == (
        "extract", "suggested", "ok", "s1")
    assert row["settled_at"] is not None


def test_release_only_removes_unsettled_claims(db):
    _claim(db, "mid:open@x")
    _claim(db, "mid:done@x")
    store.mail_settle(db, "mid:done@x", stage="sender", outcome="skipped")
    store.mail_release(db, "mid:open@x")
    store.mail_release(db, "mid:done@x")
    assert store.mail_ledger_get(db, "mid:open@x") is None
    assert store.mail_ledger_get(db, "mid:done@x") is not None
    assert _claim(db, "mid:open@x") is True  # released, so claimable again


def test_recover_unsettled_counts_the_interruption_and_releases_every_unsettled_claim(db):
    for key in ("mid:old@x", "mid:new@x", "mid:settled@x"):
        _claim(db, key)
    store.mail_settle(db, "mid:settled@x", stage="s", outcome="skipped")
    db.execute("UPDATE mail_ledger SET claimed_at='2026-01-01T00:00:00.000Z' "
               "WHERE key='mid:old@x'")
    assert store.mail_recover_unsettled(db, max_interrupted=3) == (2, 0)
    for key in ("mid:old@x", "mid:new@x"):
        row = store.mail_ledger_get(db, key)
        assert (row["interrupted"], row["released"], row["settled_at"]) == (1, 1, None)
    settled = store.mail_ledger_get(db, "mid:settled@x")
    assert (settled["interrupted"], settled["released"], settled["outcome"]) == (0, 0, "skipped")


def test_recover_unsettled_gives_up_at_the_limit(db):
    _claim(db)
    for strike in (1, 2):
        assert store.mail_recover_unsettled(db, max_interrupted=3) == (1, 0)
        assert _claim(db) is True                      # the next run reads it again, and dies
        assert store.mail_ledger_get(db, "mid:a@x")["interrupted"] == strike
    assert store.mail_recover_unsettled(db, max_interrupted=3) == (0, 1)
    row = store.mail_ledger_get(db, "mid:a@x")
    assert (row["stage"], row["outcome"], row["interrupted"], row["released"]) == (
        "error", "error", 3, 0)
    assert row["detail"] == ("a scan was interrupted on this message 3 times (a crash, a hang "
                             "or a restart); skipped so the folder can go on")
    assert row["settled_at"] is not None
    assert _claim(db) is False                         # settled: a duplicate from now on
    assert store.mail_recover_unsettled(db, max_interrupted=3) == (0, 0)


def test_recover_unsettled_does_not_strike_a_released_claim_nobody_retook(db):
    # A run that never reaches the message — Bridge still down after a reboot —
    # did not read it, so it must not count against it.
    _claim(db)
    assert store.mail_recover_unsettled(db, max_interrupted=3) == (1, 0)
    for _ in range(2):
        assert store.mail_recover_unsettled(db, max_interrupted=3) == (0, 0)
    row = store.mail_ledger_get(db, "mid:a@x")
    assert (row["interrupted"], row["released"], row["settled_at"]) == (1, 1, None)


def test_claim_retakes_a_released_claim_and_nothing_else(db):
    _claim(db, "mid:held@x")
    _claim(db, "mid:done@x")
    store.mail_settle(db, "mid:done@x", stage="s", outcome="skipped")
    _claim(db, "mid:released@x", folder="INBOX", uid=7)
    db.execute("UPDATE mail_ledger SET released=1, claimed_at='2026-01-01T00:00:00.000Z' "
               "WHERE key='mid:released@x'")
    assert _claim(db, "mid:released@x", folder="Labels/School", uid=9) is True
    row = store.mail_ledger_get(db, "mid:released@x")
    assert (row["released"], row["folder"], row["uid"]) == (0, "Labels/School", 9)
    assert row["claimed_at"] > "2026-01-01T00:00:00.000Z"
    # The upsert's WHERE is false for these: SQLite reports rowcount 0, so False.
    assert _claim(db, "mid:released@x") is False       # re-taken: held again
    assert _claim(db, "mid:held@x") is False           # held by this run
    assert _claim(db, "mid:done@x") is False           # settled
    done = store.mail_ledger_get(db, "mid:done@x")
    assert (done["outcome"], done["released"]) == ("skipped", 0)


def test_reset_stuck_approving_goes_by_age_and_status(db):
    for sid in ("old", "young", "oldpending"):
        _suggestion(db, sid, message_key=f"mid:{sid}@x")
    store.mail_transition_suggestion(db, "old", "pending", "approving")
    store.mail_transition_suggestion(db, "young", "pending", "approving")
    db.execute("UPDATE mail_suggestions SET updated_at='2026-01-01T00:00:00.000Z' "
               "WHERE id IN ('old','oldpending')")
    assert store.mail_reset_stuck_approving(db, before="2026-06-01T00:00:00.000Z") == 1
    row = store.mail_get_suggestion(db, "old")
    assert row["status"] == "pending" and row["updated_at"] > "2026-06-01"
    assert store.mail_get_suggestion(db, "young")["status"] == "approving"


def test_ledger_recent_and_counts(db):
    for i, outcome in enumerate(["suggested", "skipped", "skipped"]):
        key = f"mid:{i}@x"
        _claim(db, key)
        store.mail_settle(db, key, stage="s", outcome=outcome)
    _claim(db, "mid:inflight@x")
    db.execute("UPDATE mail_ledger SET claimed_at='2026-01-01T00:00:00.000Z' WHERE key='mid:0@x'")

    assert store.mail_ledger_counts(db) == {"suggested": 1, "skipped": 2}  # in flight excluded
    assert store.mail_ledger_counts(db, since="2026-06-01T00:00:00.000Z") == {"skipped": 2}
    recent = store.mail_ledger_recent(db, limit=2)
    assert len(recent) == 2 and all(isinstance(r, dict) for r in recent)
    assert "mid:0@x" not in [r["key"] for r in recent]  # oldest falls off


# ── cursors ──────────────────────────────────────────────────────────────────

def test_cursor_upsert_and_list(db):
    assert store.mail_get_cursor(db, "INBOX") is None
    store.mail_set_cursor(db, "INBOX", uidvalidity=5, last_uid=10, last_scan_at="t1")
    store.mail_set_cursor(db, "Labels/School", uidvalidity=9, last_uid=0, last_scan_at="t1")
    store.mail_set_cursor(db, "INBOX", uidvalidity=6, last_uid=2, last_scan_at="t2")
    row = store.mail_get_cursor(db, "INBOX")
    assert (row["uidvalidity"], row["last_uid"], row["last_scan_at"]) == (6, 2, "t2")
    assert row["window_since"] is None
    store.mail_set_cursor(db, "INBOX", uidvalidity=6, last_uid=4, last_scan_at="t3",
                          window_since="2026-09-06")
    assert store.mail_get_cursor(db, "INBOX")["window_since"] == "2026-09-06"
    store.mail_set_cursor(db, "INBOX", uidvalidity=6, last_uid=9, last_scan_at="t4")
    assert store.mail_get_cursor(db, "INBOX")["window_since"] is None    # the window ended
    assert [c["folder"] for c in store.mail_list_cursors(db)] == ["INBOX", "Labels/School"]


# ── suggestions ──────────────────────────────────────────────────────────────

def test_insert_get_and_defaults(db):
    row = _suggestion(db)
    assert row["id"] == "s1"
    assert row["status"] == "pending"
    assert row["notes"] == "" and row["event_all_day"] == 0
    assert json.loads(row["updates"]) == []
    assert row["created_at"] and row["decided_at"] is None
    assert store.mail_get_suggestion(db, "nope") is None


def test_updates_list_round_trips_as_json(db):
    merged = [{"message_key": "mid:b@x", "note": "moved to Friday"}]
    row = _suggestion(db, updates=merged)
    assert json.loads(row["updates"]) == merged
    row = store.mail_update_suggestion(db, "s1", updates=[*merged, {"message_key": "mid:c@x"}])
    assert len(json.loads(row["updates"])) == 2


def test_unknown_columns_are_refused(db):
    with pytest.raises(ValueError):
        _suggestion(db, bogus=1)
    _suggestion(db)
    with pytest.raises(ValueError):
        store.mail_update_suggestion(db, "s1", **{"title; DROP TABLE x": "y"})
    with pytest.raises(ValueError):
        store.mail_transition_suggestion(db, "s1", "pending", "approving", bogus="x")
    with pytest.raises(ValueError):
        store.mail_transition_suggestion(db, "s1", "pending", "approving", status="rejected")


def test_update_changes_fields_and_stamps_updated_at(db):
    _suggestion(db)
    db.execute("UPDATE mail_suggestions SET updated_at='2026-01-01T00:00:00.000Z'")
    row = store.mail_update_suggestion(db, "s1", title="Pay it today", due="2026-10-09")
    assert (row["title"], row["due"]) == ("Pay it today", "2026-10-09")
    assert row["updated_at"] > "2026-01-01T00:00:00.000Z"
    assert store.mail_update_suggestion(db, "missing", title="x") is None


def test_list_orders_newest_first_and_filters_by_status(db):
    for i, ts in enumerate(["2026-01-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z",
                            "2026-02-01T00:00:00.000Z"]):
        _suggestion(db, f"s{i}", message_key=f"mid:{i}@x")
        db.execute("UPDATE mail_suggestions SET created_at=? WHERE id=?", (ts, f"s{i}"))
    store.mail_transition_suggestion(db, "s2", "pending", "rejected")
    assert [r["id"] for r in store.mail_list_suggestions(db)] == ["s1", "s2", "s0"]
    assert [r["id"] for r in store.mail_list_suggestions(db, status="pending")] == ["s1", "s0"]
    assert [r["id"] for r in store.mail_list_suggestions(db, limit=1)] == ["s1"]
    assert store.mail_count_suggestions(db, "pending") == 2
    assert store.mail_count_suggestions(db, "rejected") == 1


def test_transition_is_compare_and_swap(db):
    _suggestion(db)
    assert store.mail_transition_suggestion(db, "s1", "approving", "approved") is False
    assert store.mail_get_suggestion(db, "s1")["status"] == "pending"

    assert store.mail_transition_suggestion(db, "s1", "pending", "approving") is True
    row = store.mail_get_suggestion(db, "s1")
    assert row["status"] == "approving" and row["decided_at"] is None  # not final yet

    assert store.mail_transition_suggestion(
        db, "s1", "approving", "approved", target_list=COL, target_uid="u1") is True
    row = store.mail_get_suggestion(db, "s1")
    assert (row["status"], row["target_list"], row["target_uid"]) == ("approved", COL, "u1")
    assert row["decided_at"] is not None

    # The loser of a double approval sees False and the row is unchanged.
    assert store.mail_transition_suggestion(db, "s1", "pending", "approving") is False
    assert store.mail_get_suggestion(db, "s1")["status"] == "approved"


def test_rejecting_stamps_decided_at(db):
    _suggestion(db)
    assert store.mail_transition_suggestion(db, "s1", "pending", "rejected") is True
    assert store.mail_get_suggestion(db, "s1")["decided_at"] is not None


def test_suggestions_for_thread_and_ics_lookup(db):
    _suggestion(db, "s1", thread_id="t1", ics_uid="inv-1", kind="event",
                event_start="2026-10-09T18:00:00")
    _suggestion(db, "s2", thread_id="t1", message_key="mid:b@x")
    _suggestion(db, "s3", thread_id="t2", message_key="mid:c@x", ics_uid="inv-2")
    assert {r["id"] for r in store.mail_suggestions_for_thread(db, "t1")} == {"s1", "s2"}
    assert store.mail_find_suggestion_by_ics_uid(db, "inv-1")["id"] == "s1"
    assert store.mail_find_suggestion_by_ics_uid(db, "nope") is None

    store.mail_transition_suggestion(db, "s3", "pending", "rejected")
    # A rejected invite is found too: the owner's "no" must hold for a re-send.
    assert store.mail_find_suggestion_by_ics_uid(db, "inv-2")["status"] == "rejected"
    _suggestion(db, "s4", thread_id="t3", message_key="mid:d@x", ics_uid="inv-2")
    db.execute("UPDATE mail_suggestions SET created_at='2099-01-01T00:00:00.000Z' WHERE id='s4'")
    assert store.mail_find_suggestion_by_ics_uid(db, "inv-2")["id"] == "s4"  # most recent first
    store.mail_transition_suggestion(db, "s1", "pending", "approving")
    assert store.mail_find_suggestion_by_ics_uid(db, "inv-1")["id"] == "s1"


# ── threads ──────────────────────────────────────────────────────────────────

def test_thread_upsert_is_partial(db):
    assert store.mail_get_thread(db, "t1") is None
    store.mail_upsert_thread(db, "t1", suggestion_id="s1")
    row = store.mail_get_thread(db, "t1")
    assert row["suggestion_id"] == "s1" and row["task_list"] is None

    store.mail_upsert_thread(db, "t1", task_list=COL, task_uid="u1")   # absent key untouched
    row = store.mail_get_thread(db, "t1")
    assert (row["suggestion_id"], row["task_list"], row["task_uid"]) == ("s1", COL, "u1")

    store.mail_upsert_thread(db, "t1", suggestion_id=None)             # present None clears
    row = store.mail_get_thread(db, "t1")
    assert (row["suggestion_id"], row["task_list"]) == (None, COL)

    with pytest.raises(ValueError):
        store.mail_upsert_thread(db, "t1", updated_at="x")


# ── rejections ───────────────────────────────────────────────────────────────

def test_rejections_are_insert_or_ignore_and_listed_per_thread(db):
    kw = dict(suggestion_id="s1", message_key="mid:a@x", message_id="a@x",
              thread_id="t1", title="Pay it", due="2026-10-09")
    store.mail_add_rejection(db, **kw)
    store.mail_add_rejection(db, **kw)                                  # no error, no duplicate
    store.mail_add_rejection(db, **{**kw, "message_key": "mid:b@x", "message_id": "b@x"})
    store.mail_add_rejection(db, **{**kw, "suggestion_id": "s2", "thread_id": "t2"})

    in_t1 = store.mail_rejections_for_thread(db, "t1")
    assert sorted(r["message_key"] for r in in_t1) == ["mid:a@x", "mid:b@x"]
    assert in_t1[0]["title"] == "Pay it" and in_t1[0]["rejected_at"]
    assert store.mail_rejections_for_thread(db, "t3") == []
    assert store.mail_is_rejected_message(db, "mid:a@x") is True
    assert store.mail_is_rejected_message(db, "mid:zzz@x") is False


# ── meta ─────────────────────────────────────────────────────────────────────

def test_meta_helpers(db):
    assert store.get_meta(db, "k") is None
    store.set_meta(db, "k", "v")
    store.set_meta(db, "k", "v2")
    assert store.get_meta(db, "k") == "v2"
    store.set_meta(db, "k", None)
    assert store.get_meta(db, "k") is None


def test_meta_json_tolerates_garbage(db):
    assert store.get_meta_json(db, "j") == {}
    store.set_meta(db, "j", "{not json")
    assert store.get_meta_json(db, "j") == {}
    store.set_meta(db, "j", "[1, 2]")
    assert store.get_meta_json(db, "j") == {}
    store.set_meta_json(db, "j", {"a": 1})
    assert store.get_meta_json(db, "j") == {"a": 1}


def test_merge_meta_json_stores_none(db):
    store.set_meta_json(db, "j", {"task_list": "work", "model": "m"})
    merged = store.merge_meta_json(db, "j", {"task_list": None, "enabled": True})
    assert merged == {"task_list": None, "model": "m", "enabled": True}
    assert store.get_meta_json(db, "j") == merged
    assert "task_list" in store.get_meta_json(db, "j")                  # None kept, not dropped


# ── candidate search ─────────────────────────────────────────────────────────

def _task(db, uid, summary, *, status="NEEDS-ACTION", extra=()):
    raw = foreign_raw(uid, summary, extra=(f"STATUS:{status}",) if False else extra)
    raw = raw.replace(b"STATUS:NEEDS-ACTION", f"STATUS:{status}".encode())
    store.upsert_item(db, COL, Item(f"{COL}{uid}.ics", '"1"', raw), extract_from_raw(raw))


@pytest.fixture
def tasks(db):
    store.upsert_collection(db, CollectionInfo(href=COL, displayname="Tasks", components={"VTODO"}))
    _task(db, "open@x", "Pay the school invoice")
    _task(db, "done@x", "Pay the electricity invoice", status="COMPLETED")
    _task(db, "other@x", "Water the plants")
    return db


def test_search_finds_open_tasks_only(tasks):
    got = [r["uid"] for r in store.search_open_tasks_any(tasks, ["invoice"])]
    assert got == ["open@x"]                                           # COMPLETED is excluded


def test_search_has_or_semantics(tasks):
    got = {r["uid"] for r in store.search_open_tasks_any(tasks, ["school", "plants", "nothing"])}
    assert got == {"open@x", "other@x"}                                # one shared word suffices
    assert len(store.search_open_tasks_any(tasks, ["school", "plants"], limit=1)) == 1


def test_search_ignores_short_and_junk_terms_without_raising(tasks):
    assert store.search_open_tasks_any(tasks, ['"*)(']) == []
    assert store.search_open_tasks_any(tasks, ["of", "a", "", "NEAR(", "x OR y", "a\x00bc"]) == []
    assert store.search_open_tasks_any(tasks, []) == []
    # junk mixed with a real term still finds the real one
    assert [r["uid"] for r in store.search_open_tasks_any(tasks, ['"*)(', "SCHOOL"])] == ["open@x"]


def test_search_caps_terms(tasks):
    many = [f"word{i:02d}" for i in range(40)] + ["school"]
    # "school" is past the 12-term cap, so it is dropped rather than raising.
    assert store.search_open_tasks_any(tasks, many) == []


# ── schema ───────────────────────────────────────────────────────────────────

def test_init_db_adds_window_since_to_an_old_cursor_table(db):
    db.execute("DROP TABLE mail_cursors")
    db.execute("CREATE TABLE mail_cursors (folder TEXT PRIMARY KEY, uidvalidity INTEGER NOT NULL, "
               "last_uid INTEGER NOT NULL DEFAULT 0, last_scan_at TEXT)")
    db.execute("INSERT INTO mail_cursors VALUES ('INBOX', 1, 5, 't')")
    init_db(db)
    assert store.mail_get_cursor(db, "INBOX")["window_since"] is None


def test_init_db_adds_interrupted_and_released_to_an_old_ledger_table(db):
    db.execute("DROP TABLE mail_ledger")
    db.execute("CREATE TABLE mail_ledger (key TEXT PRIMARY KEY, message_id TEXT, "
               "thread_id TEXT NOT NULL, folder TEXT NOT NULL, uid INTEGER, stage TEXT, "
               "outcome TEXT NOT NULL DEFAULT 'processing', detail TEXT, suggestion_id TEXT, "
               "claimed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
               "settled_at TEXT)")
    db.execute("INSERT INTO mail_ledger (key, thread_id, folder) VALUES ('mid:a@x', 'mid:a@x', "
               "'INBOX')")
    init_db(db)
    row = store.mail_ledger_get(db, "mid:a@x")
    assert (row["interrupted"], row["released"]) == (0, 0)
    assert store.mail_recover_unsettled(db, max_interrupted=3) == (1, 0)


def test_init_db_twice_is_idempotent(db):
    _claim(db)
    _suggestion(db)
    init_db(db)
    init_db(db)
    assert store.mail_ledger_get(db, "mid:a@x") is not None
    assert store.mail_get_suggestion(db, "s1") is not None
