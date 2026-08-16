"""Stage 3 of the audit backlog: silent data corruption and wrong results.

The dangerous class: nothing raises, nothing is logged, and the answer is wrong
— a deletion confirmed that never happened, a series that quietly reverts, a
page of results that is an arbitrary subset of the truth.

See test_backlog_stage1.py for how the xfail(strict=True) harness works and
docs/STAGES.md for the staging.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tasksd import scheduling
from tasksd.db import store
from tasksd.ical import EventEdit, rrule_from_spec
from tasksd.ical.edit import apply_event_changes, split_series
from tasksd.mcp.api import McpApi, ToolError
from tests.helpers import foreign_event_raw

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

XFAIL = dict(strict=True)


class _Svc:
    """A stub TaskService. Defaults mimic the real one's behaviour for the
    unknown-uid cases: the engine looks the item up in the cache and either
    raises KeyError (edits) or returns silently (deletes)."""

    def __init__(self, *, tasks=None, lists=None):
        self._tasks = tasks or {}
        self._lists = lists or ["/u/inbox/"]

    def resolve_list(self, list_id):
        href = f"/u/{list_id}/"
        return href if href in self._lists else None

    def list_lists(self):
        return [{"href": h} for h in self._lists]

    def list_tasks(self, href, *, include_done=True):
        return list(self._tasks.get(href, []))

    def edit_task(self, href, uid, edit):
        # engine._edit: `row is None -> raise KeyError(f"unknown task ...")`
        raise KeyError(f"unknown task {uid} in {href}")

    def delete_task(self, href, uid):
        return None            # engine.delete_task: `if row is None: return`


# ── AUDIT: the ToolError guards in api.py are unreachable dead code ────────

@pytest.mark.xfail(reason="AUDIT open: api.py:257 unreachable ToolError guards", **XFAIL)
def test_editing_an_unknown_task_names_the_uid():
    """`api.edit_task` ends with `if task is None: raise ToolError(f"No task
    {uid!r}...")`, but `service.edit_task` never returns None for a missing uid
    — `engine._edit` raises KeyError first. So the guard is dead code, and
    McpServer's catch-all turns it into "could not be completed (KeyError). The
    calendar server may be unreachable" — pointing the model at an outage that
    is not happening, for a typo it could have corrected."""
    api = McpApi(_Svc())
    with pytest.raises(ToolError) as exc:
        api.update_task("inbox", "no-such-uid", {"summary": "x"})
    assert "no-such-uid" in str(exc.value)


# ── AUDIT: delete confirms a uid that does not exist ──────────────────────

@pytest.mark.xfail(reason="AUDIT open: tools.py:325 delete confirms a phantom", **XFAIL)
def test_deleting_an_unknown_task_is_refused_not_confirmed():
    """`api.delete_task` calls straight through and `engine.delete_task` returns
    silently when the uid is not in the cache; the tool then answers
    `{"deleted": uid}` regardless. The model is told a task is gone that never
    existed — or that still exists in a different list — so it reports success
    to the user and stops retrying."""
    api = McpApi(_Svc())
    with pytest.raises(ToolError):
        api.delete_task("inbox", "no-such-uid")


# ── AUDIT: list_tasks across all lists is unsorted before `limit` ──────────

@pytest.mark.xfail(reason="AUDIT open: api.py:168 unsorted before limit", **XFAIL)
def test_tasks_across_all_lists_are_ordered_before_the_limit_applies():
    """`list_tasks` extends one list's rows after another's and never sorts, but
    the tool then pages that concatenation. The description promises due-date
    order, so `limit=3` should be the three most urgent tasks on the account; it
    is actually "whatever list came first", and the soonest deadline can be
    missing entirely."""
    def _t(uid, due):
        return {"uid": uid, "due": due, "completed": False, "cancelled": False,
                "tags": [], "summary": uid}

    api = McpApi(_Svc(
        lists=["/u/a/", "/u/b/"],
        tasks={
            "/u/a/": [_t("late-1", "2026-12-01"), _t("late-2", "2026-12-02")],
            "/u/b/": [_t("URGENT", "2026-01-01")],       # the soonest, in list b
        },
    ))

    rows = api.list_tasks(include_done=True)
    dues = [r["due"] for r in rows]
    assert dues == sorted(dues), (
        f"rows are returned in list order, not due order: {dues}; "
        f"a limit over this drops the most urgent task"
    )


# ── AUDIT: generate_slots' default max_slots truncates the public page ────

@pytest.mark.xfail(reason="AUDIT open: service.py:715 max_slots truncation", **XFAIL)
def test_a_long_horizon_is_not_silently_truncated():
    """`public_link_info` calls `generate_slots` without `max_slots`, taking the
    1000 default. A 15-minute link with a wide weekly window and a 60-day
    horizon generates far more than that, so the cap lands mid-horizon and every
    day past it renders as fully booked — indistinguishable, to a visitor, from
    the owner genuinely having no time."""
    tz = ZoneInfo("UTC")
    av = scheduling.parse_availability({str(d): ["09:00-17:00"] for d in range(7)})
    now = datetime(2026, 1, 5, 8, 0, tzinfo=tz)

    slots = scheduling.generate_slots(
        availability=av, duration_minutes=15, busy=[], buffer_minutes=0, tz=tz,
        now=now, min_notice_hours=0, horizon_days=60,
    )

    last = max(s.start for s in slots)
    horizon_end = (now + timedelta(days=60)).date()
    assert last.date() >= horizon_end - timedelta(days=1), (
        f"the last offered slot is {last.date()}, but the horizon runs to "
        f"{horizon_end}: {horizon_end - last.date()} of advertised availability "
        f"was silently truncated by the max_slots cap"
    )


# ── AUDIT: changing "Repeat until" with a mismatched override ──────────────

@pytest.mark.xfail(reason="AUDIT open: edit.py:393 naive dtstart vs UTC UNTIL", **XFAIL)
def test_setting_repeat_until_survives_a_floating_override():
    """`_reconcile_overrides` builds its dateutil probe from a tz-STRIPPED
    dtstart while the rule it passes still carries `UNTIL=...Z`, and dateutil
    refuses that combination outright. One override whose RECURRENCE-ID is
    floating — which is what an older write or a foreign client leaves behind —
    makes "Repeat until <date>" permanently unsaveable on that series."""
    raw = foreign_event_raw(
        "s2", "Std", dtstart="TZID=America/Chicago:20260106T090000",
        dtend="TZID=America/Chicago:20260106T093000", rrule="FREQ=WEEKLY;COUNT=6",
        overrides=(("RECURRENCE-ID:20260113T090000", "DTSTART:20260113T100000",
                    "DTEND:20260113T103000", "SUMMARY:moved"),),
    )
    # Control: the same edit without an UNTIL succeeds, which is what pins the
    # cause on the un-normalized UNTIL rather than on the override.
    apply_event_changes(raw, EventEdit(rrule=rrule_from_spec("monthly")))

    apply_event_changes(
        raw, EventEdit(rrule=rrule_from_spec("daily", until=date(2026, 2, 1))))


# ── AUDIT: split_series drops a THISANDFUTURE override ────────────────────

@pytest.mark.xfail(reason="AUDIT open: edit.py:932 THISANDFUTURE dropped", **XFAIL)
def test_this_and_following_keeps_a_this_and_future_overrides_values():
    """`_drop_overrides(tail, anchor, keep_before=False)` discards every override
    whose RECURRENCE-ID precedes the anchor. That is right for a single-slot
    override, but a RANGE=THISANDFUTURE one carries the times, summary, location,
    alarms and attendees for every occurrence AFTER it — the whole tail included.
    Dropping it snaps the tail back to the master, and since the tail is written
    as a new resource with a fresh UID, the loss is permanent."""
    raw = foreign_event_raw(
        "s1", "Std", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
            "DTSTART:20260113T100000Z", "DTEND:20260113T103000Z",
            "SUMMARY:TF", "LOCATION:Room B"),),
    )

    _head, tail = split_series(raw, "2026-01-20T09:00:00+00:00", EventEdit())
    text = tail.decode()

    assert "Room B" in text and "TF" in text, (
        "the tail reverted to the master: the THISANDFUTURE override's location "
        "and summary (and its alarms, attendees and X- properties) are gone, "
        f"permanently — tail is:\n{text}"
    )


# ── AUDIT: reorder_tasks' `with self._conn:` opens no transaction ──────────

@pytest.mark.xfail(reason="AUDIT open: service.py:403 no real transaction", **XFAIL)
def test_a_failed_reorder_leaves_no_partial_order():
    """`store.connect` sets `isolation_level=None`, so `with self._conn:` commits
    nothing and rolls back nothing — sqlite3's context manager only manages a
    transaction it started itself. `set_sort_orders`' documented all-or-nothing
    guarantee therefore does not exist: a failure part-way leaves some rows
    renumbered and some not, and 20 000 rows are 20 000 separate commits under
    the global lock."""
    from tasksd import service as service_mod
    from tasksd.dav.client import CollectionInfo

    svc = service_mod.TaskService.__new__(service_mod.TaskService)
    svc._conn = store.connect(":memory:")
    store.init_db(svc._conn)
    svc._lock = threading.RLock()
    svc._listeners, svc._loop = set(), None
    store.upsert_collection(svc._conn, CollectionInfo(
        href="/u/inbox/", displayname="Inbox", components={"VTODO"}))

    assert svc._conn.isolation_level is None
    before = {r["uid"]: r["sort_order"]
              for r in svc._conn.execute("SELECT uid, sort_order FROM sidecar")}

    placed = [("/u/inbox/", f"u-{i}") for i in range(5)]
    placed.append(("/u/inbox/", object()))          # unbindable: fails mid-write

    with pytest.raises(Exception):
        svc.reorder_tasks(placed)

    after = {r["uid"]: r["sort_order"]
             for r in svc._conn.execute("SELECT uid, sort_order FROM sidecar")}
    assert after == before, (
        f"a failed reorder left {len(after) - len(before)} rows renumbered; "
        f"the write is not atomic"
    )
