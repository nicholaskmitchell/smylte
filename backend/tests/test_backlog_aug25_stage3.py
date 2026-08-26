"""The 2026-08-25 sweep, stage 3: silent data corruption.

Nothing raises, nothing is logged, and the answer is quietly wrong. Both earlier
backlogs call this the dangerous stage, and these three keep the theme: a
reschedule that rewrites a series into one the user never asked for, a filter
that files a deadline on the wrong day, and a move that leaves the event in two
calendars with no way to finish.

**These findings are CLOSED**, and every test here is now an ordinary regression
test that must stay green. Each was written first as an `xfail(strict=True)` pin
asserting the CORRECTED behaviour — green while the bug was open, red (XPASS) the
moment it was fixed — and the marker was dropped as part of the commit that fixed
it. See docs/STAGES.md for the harness and for what remediation taught.

Tests added DURING remediation sit beside the originals and say so in their own
docstrings. They exist because a mutation escaped the pin: each fix was run
against two to four deliberately wrong versions of itself, and anything that
survived got a test rather than a comment.

Three of the stage's twelve findings are here; the other nine are in the SPA and
live in `frontend/src/backlog.aug25.stage3.test.tsx`.

Every pin is behavioural and in-process. The reschedule is judged by
`expand_occurrences` over the bytes `shift_series` actually produces, the filter
runs through the real `McpApi` over a stub service, and the move drives the real
`SyncEngine` against a fake DAV whose DELETE reply is lost once. Nothing here
needs the scratch Radicale, so none of it carries `@pytest.mark.radicale`.

Each pin asserts the *class* of the corrected answer rather than a particular
repair. That matters most on the first, where a clean refusal and a correct
rotation are both right and the audit's suggested fix picks the refusal; and it
is why the `overdue_only` half of the second finding was deliberately NOT pinned.
The stage decided that one — the MCP filter follows `util.ts::isOverdue` and
`service._due_day` rather than inventing a third answer — and it has tests now.

Two of the three carry CONTROLS: ordinary passing tests that the feature still
works, because the cheap over-correction in both cases is a guard that refuses
everything, and refusing everything would satisfy the pin by deleting it.

The move pin takes either of two repairs and says so. Only one of them is
actually safe, which its neighbouring test explains: rolling the copy back on any
delete failure reaches the same end state when the delete provably did not
happen, and destroys the last copy when it did.

Run just this file with `pytest tests/test_backlog_aug25_stage3.py`.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from helpers import foreign_event_raw
from zoneinfo import ZoneInfo

from tasksd import ical
from tasksd.dav.client import CollectionInfo, Item
from tasksd.dav.errors import Conflict, DavError, NotFound, PreconditionFailed
from tasksd.db import store
from tasksd.ical.edit import EventEdit, shift_series, split_series
from tasksd.ical.recur import expand_occurrences
from tasksd.mcp.api import McpApi
from tasksd.sync import SyncEngine
from tasksd.sync.engine import ConflictError

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

# A window wide enough to hold the fifth occurrence the defect mints, which is
# the whole point: a window that stopped at the fourth would count four either
# way and the pin would pass against unfixed code.
WINDOW = (date(2026, 1, 1), date(2026, 4, 1))


def _drag(rrule: str, anchor: str, new_start: str, *, minutes: int = 60):
    """Drag one occurrence of `rrule` with scope "all events".

    Returns `(before, after)` as lists of ISO starts, or `(before, None)` when
    the edit was REFUSED — which is a correct outcome and the one the audit's
    suggested fix produces, so the caller must accept it.
    """
    raw = foreign_event_raw("series@x", "Standup", dtstart="20260105T090000Z",
                            dtend="20260105T100000Z", rrule=rrule)
    before = [o.start for o in expand_occurrences(raw, *WINDOW)]
    ns = datetime.fromisoformat(new_start)
    try:
        out = shift_series(raw, anchor,
                           EventEdit(dtstart=ns, dtend=ns + timedelta(minutes=minutes)))
    except ValueError:
        return before, None
    return before, [o.start for o in expand_occurrences(out, *WINDOW)]


# ── AUDIT: a time-only drag skips the desynchronization check entirely ──────

def test_a_time_only_drag_of_a_time_pinned_series_neither_desynchronizes_it_nor_gains_an_occurrence():
    """`_shift_rrule`'s own docstring spells out this exact failure for the DAY
    half — "`FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4` by a day turned Jan 6/Feb 6/Mar
    6/Apr 6 into Jan 7/Feb 6/Mar 6/Apr 6/**May 6** — five occurrences instead of
    four, only the dragged one moved, and a May the user never asked for,
    because COUNT is now consumed from a later start."

    The guard cannot see the TIME half, and it misses twice over:

      * `_DAY_SELECTING = ("BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH",
        "BYSETPOS")` contains no `BYHOUR`/`BYMINUTE`/`BYSECOND`; and
      * `if not day_delta: return None` bails out before that loop is reached
        whenever the drag changed only the time of day — which is precisely when
        a BYHOUR rule desynchronizes.

    Measured against the tree as it stands, judged by `expand_occurrences`:

        DTSTART:20260105T090000Z
        RRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4
        before: 01-05T09:00, 01-12T09:00, 01-19T09:00, 01-26T09:00        (4)

        drag the Jan 5 chip 09:00 -> 11:00, scope "all events"
        after:  01-05T11:00, 01-12T09:00, 01-19T09:00, 01-26T09:00,
                02-02T09:00                                               (5)

    and the written-back rule is `FREQ=WEEKLY;COUNT=4;BYHOUR=9;BYDAY=MO` beside
    `DTSTART:20260105T110000Z` — unchanged, because `_shift_rrule` decided there
    was nothing to change. `FREQ=DAILY;BYMINUTE=0;COUNT=4` dragged +30 min does
    the same: 01-05T09:30 and then four 09:00s, the last of them a day past the
    end of the series.

    `split_series` calls `_shift_rrule` too (edit.py:1685), so "this and
    following" with a time change corrupts the tail the same way. The bytes go to
    Radicale, so the loss is permanent and visible in every other client.

    ASSERTED AS A CLASS, not as a repair. Two answers are correct here and the
    pin takes either: REFUSE the reschedule (`ValueError`, which `patch_event`
    maps to 422 — the audit's suggested fix, and the same shape the day-selecting
    parts already get), or MOVE THE WHOLE SERIES coherently, which means the
    occurrence count is unchanged and no occurrence stayed behind at the old
    time. What is not correct is the third thing, which is what happens today.
    """
    broken = []
    for rrule, anchor, new_start in (
        ("FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4",
         "2026-01-05T09:00:00+00:00", "2026-01-05T11:00:00+00:00"),
        ("FREQ=DAILY;BYMINUTE=0;COUNT=4",
         "2026-01-05T09:00:00+00:00", "2026-01-05T09:30:00+00:00"),
    ):
        before, after = _drag(rrule, anchor, new_start)
        if after is None:
            continue                     # a clean refusal is a correct outcome
        if len(after) != len(before):
            broken.append(f"{rrule}: {len(before)} occurrences {before} became "
                          f"{len(after)} {after}")
        elif before[1] in after:
            broken.append(f"{rrule}: {before[1]} did not move with the series: {after}")
    assert not broken, (
        "a time-only drag of a series whose rule pins the time of day neither "
        "moved the series nor refused the change:\n  " + "\n  ".join(broken)
    )


@pytest.mark.parametrize("label, rrule, expect_refusal", [
    # The finding's second half, which the pin above cannot reach: `split_series`
    # calls `_shift_rrule` too, so "this and following" with a time change
    # corrupted the TAIL exactly the same way — and the tail is the part the user
    # keeps. One guard covers both because both go through `_shift_rrule`, and
    # this is what says so rather than leaving it to be inferred.
    ("time-pinned", "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4", True),
    # ...and the control beside it: an ordinary rule still splits.
    ("ordinary", "FREQ=WEEKLY;COUNT=4", False),
])
def test_this_and_following_answers_a_time_change_the_same_way(label, rrule, expect_refusal):
    raw = foreign_event_raw("split@x", "Standup", dtstart="20260105T090000Z",
                            dtend="20260105T100000Z", rrule=rrule)
    anchor = "2026-01-12T09:00:00+00:00"
    ns = datetime.fromisoformat("2026-01-12T11:00:00+00:00")
    edit = EventEdit(dtstart=ns, dtend=ns + timedelta(minutes=60))

    if expect_refusal:
        with pytest.raises(ValueError, match="pins it to a particular time"):
            split_series(raw, anchor, edit)
        return

    head, tail = split_series(raw, anchor, edit)[:2]
    kept = [o.start for o in expand_occurrences(head, *WINDOW)]
    moved = [o.start for o in expand_occurrences(tail, *WINDOW)]
    assert kept == ["2026-01-05T09:00:00+00:00"], kept
    assert moved == ["2026-01-12T11:00:00+00:00", "2026-01-19T11:00:00+00:00",
                     "2026-01-26T11:00:00+00:00"], moved


@pytest.mark.parametrize("rrule, anchor, new_start, expected_days", [
    # A DAY-only drag of a time-pinned rule desynchronizes nothing — the hour the
    # rule names is still the hour DTSTART lands on — and the WEEKLY BYDAY
    # rotation must still happen. A guard that refused on the mere PRESENCE of
    # BYHOUR would break this.
    ("FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4", "2026-01-05T09:00:00+00:00",
     "2026-01-06T09:00:00+00:00",
     [date(2026, 1, 6), date(2026, 1, 13), date(2026, 1, 20), date(2026, 1, 27)]),
    # And the ordinary time-only drag — no BY* part at all — must still move the
    # whole series, which is the gesture the pin above must not cost.
    ("FREQ=WEEKLY;COUNT=4", "2026-01-05T09:00:00+00:00",
     "2026-01-05T11:00:00+00:00",
     [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)]),
])
def test_a_series_that_can_still_be_moved_is_still_moved(
    rrule, anchor, new_start, expected_days
):
    """CONTROL — passes today and must keep passing. A refusal satisfies the pin
    above, so a fix that refused every reschedule touching a rule with a BY* part
    would pass it while breaking the ordinary gesture.

    `test_backlog_aug19_stage3_ical.py::test_a_series_that_can_be_moved_is_still_
    moved` is the twin of this and covers the day-selecting parts (including a
    time-only drag of `BYMONTHDAY`, which must still succeed). These two are the
    cases that twin does not have: a time-PINNED rule dragged by days, and a
    plain rule dragged by time.
    """
    before, after = _drag(rrule, anchor, new_start)
    assert after is not None, f"{rrule} dragged to {new_start} was refused outright"
    got = [datetime.fromisoformat(o).date() for o in after]
    assert got == expected_days, f"{rrule} dragged to {new_start} produced {got}"


# ── AUDIT: list_tasks' due filters resolve in the server's zone ─────────────

class _ZonedStub:
    """The narrowest stand-in for `TaskService` that `McpApi.list_tasks` needs,
    plus the one thing `_home_zone` reads.

    Same shape as `test_backlog_aug19_stage3_core.py::_ZonedService`, kept local
    rather than imported: that file is CLOSED history and importing across sweep
    files would tie a live pin's fixture to a finished one.
    """

    def __init__(self, tasks: dict[str, list[dict]], *, home_timezone: str):
        self._tasks = tasks
        self._home_timezone = home_timezone

    def list_lists(self):
        return [{"href": h} for h in self._tasks]

    def list_tasks(self, href, *, include_done=True):
        return list(self._tasks[href])

    def get_settings(self):
        return {"home_timezone": self._home_timezone}

    def resolve_list(self, list_id, component=None):
        return f"/u/{list_id}/"


def _task(uid: str, *, due: str | None) -> dict:
    return {"uid": uid, "summary": uid, "due": due, "sort_order": None,
            "priority": None, "tags": [], "completed": False, "cancelled": False}


@pytest.fixture
def _server_in_utc(monkeypatch):
    """The ordinary Docker deployment: the process in UTC, the owner somewhere
    else. `_as_dt` flattens an aware value to the SERVER's wall clock, so the
    skew this pin is about only exists when the two zones differ — a test run on
    a developer's machine in America/Chicago would pass vacuously."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    # `monkeypatch` restores the variable; `tzset` has to be re-run by hand or
    # every later test in the session keeps this process's zone.
    time.tzset()


def test_the_due_filters_file_a_deadline_on_the_day_the_owner_sees(_server_in_utc):
    """`_due_instant` was deliberately changed to resolve a deadline in
    `home_timezone`; its docstring says why. The FILTERS in the same function
    were left on `_as_dt`
    (`value.astimezone().replace(tzinfo=None)` — the server's local wall clock),
    so `smylte_list_tasks` disagrees with its own ordering, with
    `service._due_day`, and with the SPA about which day a task is due.

    Measured with the process in UTC and `home_timezone="America/Chicago"`, one
    foreign VTODO carrying an instant:

        DUE:20260822T030000Z        # = 2026-08-21 22:00 in the owner's own zone
        DUE;VALUE=DATE:20260821     # control, files on the 21st in both zones

        list_tasks(due_before="2026-08-22") -> ['anchor']    # Friday 22:00 MISSING
        list_tasks(due_after="2026-08-22")  -> ['evening']   # reported as Saturday's

    A model asked "what is due before Saturday" is told the Friday-evening
    deadline does not exist, and then finds it under Saturday.

    `overdue_only` was deliberately left out of this pin, because its answer
    depended on a question the finding did not settle — whether a DATE-ONLY
    deadline resolves to midnight or to the end of its day — and pinning it
    would have been pinning one repair rather than a class of them. That
    question is now answered, by precedent rather than invention, and the test
    below it is the one that follows.
    """
    api = McpApi(_ZonedStub({"/u/inbox/": [
        _task("evening", due="2026-08-22T03:00:00+00:00"),
        _task("anchor", due="2026-08-21"),
    ]}, home_timezone="America/Chicago"))

    before = [t["uid"] for t in api.list_tasks(None, due_before="2026-08-22")]
    after = [t["uid"] for t in api.list_tasks(None, due_after="2026-08-22")]

    assert "evening" in before, (
        f"a deadline the owner reads as 22:00 on Friday the 21st was excluded "
        f"from 'due before 2026-08-22': {before}")
    assert "evening" not in after, (
        f"the same deadline was reported as Saturday's or later: {after}")


def test_overdue_only_waits_for_the_owners_day_to_end(_server_in_utc):
    """The half the pin above left open, and the decision it was waiting on.

    Two precedents already existed and they agree, so no third answer was
    invented: `util.ts::isOverdue` says "an all-day item isn't overdue until its
    whole day has passed", and `service._due_day` resolves a deadline's day in
    `home_timezone`. `overdue_only` now honours both.

    That decision is also what makes this DETERMINISTIC, which is why it could
    not be written before. Under the old rule — a date-only due flattened to
    midnight and compared against the server's `datetime.now()` — a task due
    today was reported overdue for part of every day and not for the rest, so
    any assertion about it passed or failed depending on the hour it ran. Under
    the day rule the answer does not depend on the clock at all: today's work is
    never overdue, yesterday's always is.

    The two timed rows are the control on the other side: an instant-valued
    deadline is overdue the moment it passes, with no day of grace, because it
    named a moment rather than a day.
    """
    chicago_today = datetime.now(ZoneInfo("America/Chicago")).date()
    now = datetime.now(timezone.utc)
    api = McpApi(_ZonedStub({"/u/inbox/": [
        _task("today", due=chicago_today.isoformat()),
        _task("yesterday", due=(chicago_today - timedelta(days=1)).isoformat()),
        _task("an-hour-ago", due=(now - timedelta(hours=1)).isoformat()),
        _task("in-an-hour", due=(now + timedelta(hours=1)).isoformat()),
    ]}, home_timezone="America/Chicago"))

    overdue = {t["uid"] for t in api.list_tasks(None, overdue_only=True)}
    assert overdue == {"yesterday", "an-hour-ago"}, (
        f"overdue_only answered {sorted(overdue)}; work due TODAY in the owner's "
        f"zone ({chicago_today}) still has the rest of the day to happen in, and "
        f"a deadline that named an instant is overdue the moment it passes"
    )


@pytest.mark.parametrize("label, day, hours", [
    # Chicago springs forward on 2026-03-08, so that day is 23 hours long...
    ("spring forward", "2026-03-08", 23),
    # ...and falls back on 2026-11-01, which is 25.
    ("fall back", "2026-11-01", 25),
    ("an ordinary day", "2026-03-15", 24),
])
def test_a_deadlines_day_is_as_long_as_the_owners_day_actually_is(label, day, hours):
    """The unit test behind `_due_parts`' wall-clock claim, because nothing else
    can reach it.

    `overdue_only` is asserted above against the real clock, so it only ever
    exercises whatever today happens to be — and a mutation that added the day as
    a flat 86400 seconds instead of as a calendar day passed the whole suite. The
    difference is one hour, twice a year, on the one path that decides whether a
    deadline has expired.

    Compared as INSTANTS, deliberately: every datetime here shares one ZoneInfo
    object and CPython short-circuits `==` to a naive field comparison when
    `self.tzinfo is other.tzinfo`, so a local comparison cannot tell the two
    versions apart at all — the same trap the closed scheduling findings were
    about, one module over.
    """
    from tasksd.mcp.api import _due_parts

    zone = ZoneInfo("America/Chicago")
    due_at, overdue_at = _due_parts(day, zone)
    assert (overdue_at - due_at) / 3600 == hours, (
        f"{label}: a deadline of {day} expired {(overdue_at - due_at) / 3600}h "
        f"after it fell due, but that day is {hours} hours long in the owner's zone"
    )


# ── AUDIT: move_event has no replay tolerance ──────────────────────────────

SRC = "/u/a/"
DST = "/u/b/"
MOVED = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//EN\r\nBEGIN:VEVENT\r\nUID:e-1\r\n"
    b"DTSTART:20260101T100000Z\r\nDTEND:20260101T110000Z\r\nSUMMARY:Standup\r\n"
    b"END:VEVENT\r\nEND:VCALENDAR\r\n"
)
FOREIGN = MOVED.replace(b"UID:e-1", b"UID:someone-elses")


class _FakeDav:
    """A write-capable DAV double: `{href: (etag, bytes)}`.

    There is no such double in the suite — the DAV fakes that exist are
    read-only PROPFIND/REPORT stubs for the sync sweep — and this finding cannot
    be driven without one, because the whole defect is what the SERVER is left
    holding after a write fails halfway. `fail_delete` drops the DELETE reply
    once, which is the ordinary trigger: a lost response, a reset connection, a
    tunnel blip between the copy and the delete.
    """

    def __init__(self, initial: dict[str, bytes]):
        self.store: dict[str, tuple[str, bytes]] = {
            h: ('"1"', b) for h, b in initial.items()}
        self.fail_delete = False
        self.lose_delete_reply = False

    def get(self, href):
        if href not in self.store:
            raise NotFound(f"GET {href} -> 404")
        etag, data = self.store[href]
        return Item(href=href, etag=etag, data=data)

    def put(self, href, data, *, if_match=None, if_none_match=None):
        if if_none_match == "*" and href in self.store:
            raise PreconditionFailed(f"PUT {href} -> 412")
        self.store[href] = ('"2"', data if isinstance(data, bytes) else data.encode())
        return '"2"'

    def delete(self, href, *, if_match=None):
        if self.fail_delete:
            self.fail_delete = False     # the network recovers after one loss
            raise DavError(f"transport error on DELETE {href}: connection reset")
        if self.lose_delete_reply:
            # The OTHER half of the same blip, and the one that decides whether
            # rolling the copy back is safe: the server performed the delete and
            # the caller never heard so. Indistinguishable, from here, from the
            # `fail_delete` case above.
            self.lose_delete_reply = False
            self.store.pop(href, None)
            raise DavError(f"transport error on DELETE {href}: connection reset")
        self.store.pop(href, None)


def _engine(initial: dict[str, bytes]) -> tuple[SyncEngine, _FakeDav, object]:
    conn = store.connect(":memory:")
    store.init_db(conn)
    for href in (SRC, DST):
        store.upsert_collection(conn, CollectionInfo(
            href=href, displayname=href, components={"VEVENT"}))
    dav = _FakeDav(initial)
    engine = SyncEngine(dav, conn)
    store.upsert_item(conn, SRC, Item(SRC + "e-1.ics", '"1"', MOVED),
                      ical.extract_from_raw(MOVED))
    return engine, dav, conn


def test_a_move_whose_delete_reply_was_lost_can_still_be_completed():
    """`move_event` is copy-then-delete, and the destination href is
    DETERMINISTIC (`new_href = f"{dst_href}{basename}"`, with `basename` taken
    from the unchanged source cache row). So once the copy has landed, every
    subsequent attempt at the same move hits its own copy and answers 409
    forever. Meanwhile the source delete is rolled back only for
    `PreconditionFailed` — a transport error, a 403, a 423 propagates with the
    copy still in place.

    `_put_new` (engine.py:376) solves exactly this for creates: on a 412 it GETs
    the occupant and treats it as success when the UID is ours — "a replay finds
    the resource already on the server — that is the create succeeding, not a
    conflict, as long as the occupant is ours". `move_event` never got that
    treatment, even though this same `except` clause was edited once already to
    add `Conflict`.

    Measured against the tree as it stands, with the DELETE reply lost once:

        attempt 1 -> DavError transport error on DELETE /u/a/e-1.ics
                     server hrefs: ['/u/a/e-1.ics', '/u/b/e-1.ics']
        attempt 2 -> ConflictError event e-1 already exists in the target calendar
                     server hrefs: ['/u/a/e-1.ics', '/u/b/e-1.ics']
                     cache src row: True | cache dst row: False

    After the next 30 s sweep the SPA renders the event in both calendars and
    the booking-conflict set counts it twice. The message the caller gets is
    actively misleading: over HTTP it reads as "the move is already done" while
    the source copy is still there, and over MCP `mcp/server.py:222` has no
    `ConflictError` branch at all, so `smylte_move_event` says "try again
    shortly" about a call that can never succeed.

    ASSERTED AS THE END STATE, not as a repair. Rolling the copy back on any
    delete failure and giving the PUT `_put_new`'s replay tolerance are both
    correct and reach the same place: after the caller has retried, the event is
    in the destination and nowhere else. The first attempt is allowed to fail
    however it likes — that half is the network, not the engine.
    """
    engine, dav, conn = _engine({SRC + "e-1.ics": MOVED})
    dav.fail_delete = True

    with pytest.raises(DavError):
        engine.move_event(SRC, DST, "e-1")     # the network eats the DELETE reply

    # The retry the caller is invited to make. Its exception, if any, is folded
    # into the assertion rather than allowed to be the failure: a pin that dies
    # on a raise reports "ConflictError" where the finding is about what the
    # SERVER is left holding, and a partial fix that changed only the exception
    # would then look like progress.
    retry = None
    try:
        engine.move_event(SRC, DST, "e-1")
    except Exception as e:                     # noqa: BLE001 — reported, not handled
        retry = f"{type(e).__name__}: {e}"

    assert sorted(dav.store) == [DST + "e-1.ics"], (
        f"after a retry the event is still in both calendars: {sorted(dav.store)}"
        + (f"; the retry raised {retry}" if retry else ""))
    assert store.get_item(conn, DST, "e-1") is not None, "the cache lost the moved event"
    assert store.get_item(conn, SRC, "e-1") is None, "the cache still holds the source row"


def test_the_retry_carries_the_revision_the_source_holds_NOW():
    """The adopted copy is REFRESHED, not merely accepted.

    Not pinned by the finding, and deliberately covered anyway: the whole reason
    `move_event` reads the bytes off the wire instead of the cache is that
    another client may edit the event inside the window, and "the source delete
    could not save it either ... here destroyed the only copy of the newer
    revision" (its own docstring). A retry after a lost DELETE reply reopens that
    window — the destination holds the bytes of the FIRST attempt, and the source
    that holds the newer ones is about to be deleted. Accepting the occupant
    unchanged, which is all the finding asks for, would silently discard the edit
    in exactly the way the docstring says it must not.
    """
    engine, dav, _ = _engine({SRC + "e-1.ics": MOVED})
    dav.fail_delete = True

    with pytest.raises(DavError):
        engine.move_event(SRC, DST, "e-1")

    # Another CalDAV client edits the source between the two attempts.
    edited = MOVED.replace(b"SUMMARY:Standup", b"SUMMARY:Standup (moved to 11)")
    dav.store[SRC + "e-1.ics"] = ('"9"', edited)

    engine.move_event(SRC, DST, "e-1")

    assert sorted(dav.store) == [DST + "e-1.ics"]
    assert dav.store[DST + "e-1.ics"][1] == edited, (
        "the retry adopted the first attempt's stale copy and the source, which "
        "held the newer revision, was deleted on top of it")


def test_a_delete_that_happened_but_was_not_heard_does_not_destroy_the_event():
    """The copy is NOT rolled back when the source delete fails for anything but
    a 412, and this is why.

    The finding offers a rollback "for any exception from the source DELETE" as
    an alternative to replay tolerance, and the pin above accepts either, because
    both reach the same end state when the delete provably did not happen. This
    is the case where it did. A transport error is a lost REPLY as often as a
    lost request, and the two are indistinguishable from this side — so a
    rollback here deletes the one remaining copy, and the event is gone from both
    calendars. A duplicate is recoverable; this is not.

    The 412 branch keeps its rollback: there the server ANSWERED, so the delete
    provably did not happen, which is exactly the distinction the finding draws.
    """
    engine, dav, _ = _engine({SRC + "e-1.ics": MOVED})
    dav.lose_delete_reply = True

    with pytest.raises(DavError):
        engine.move_event(SRC, DST, "e-1")

    assert DST + "e-1.ics" in dav.store, (
        "the copy was rolled back over a delete that had already succeeded; the "
        f"event now exists nowhere: {sorted(dav.store)}")
    assert dav.store[DST + "e-1.ics"][1] == MOVED


def test_a_move_onto_a_stranger_is_still_a_conflict():
    """CONTROL — passes today and must keep passing. The cheap over-correction
    for the pin above is "treat a 412 on the destination PUT as success", which
    would satisfy it by CLOBBERING whatever already occupies that href. The
    occupant here carries a different UID: it is somebody else's resource, the
    one true conflict, and `_put_new`'s own comment draws exactly this line.
    """
    engine, dav, _ = _engine({SRC + "e-1.ics": MOVED, DST + "e-1.ics": FOREIGN})

    with pytest.raises(ConflictError):
        engine.move_event(SRC, DST, "e-1")

    assert dav.store[DST + "e-1.ics"][1] == FOREIGN, "the stranger's event was overwritten"
    assert SRC + "e-1.ics" in dav.store, "the source was deleted despite the conflict"
