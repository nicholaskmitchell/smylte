"""Recurrence expansion — pure unit tests (no Radicale, no `radicale` marker).

Exercises `ical.recur.expand_occurrences` across the RFC 5545 matrix (RRULE,
EXDATE, RDATE, RECURRENCE-ID overrides, all-day, DST, sub-daily caps) and the
`store.get_events_in_range` candidate-selection fix that admits a recurring
master whose own DTSTART is in the past.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from helpers import foreign_event_raw

from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import (
    EventEdit,
    apply_event_changes,
    apply_occurrence_override,
    build_new_event,
    exclude_occurrence,
    parse_calendar,
    recur,
    rrule_from_spec,
    shift_series,
    split_series,
)
from tasksd.ical.read import extract_from_raw

_WIN = (date(2026, 1, 1), date(2026, 3, 1))


def _master(raw: bytes):
    """The series master component (the VEVENT with no RECURRENCE-ID)."""
    return next(ev for ev in parse_calendar(raw).walk("VEVENT")
                if "RECURRENCE-ID" not in ev)


def _overrides(raw: bytes) -> list:
    return [ev for ev in parse_calendar(raw).walk("VEVENT")
            if "RECURRENCE-ID" in ev]


def _series() -> bytes:
    """A weekly series 'Std' of 5 from 2026-01-06 09:00Z, carrying a foreign prop."""
    return foreign_event_raw("s@tasksd", "Std", rrule="FREQ=WEEKLY;COUNT=5")


def _starts(occs) -> list[str]:
    return [o.start for o in occs]


# ── RRULE basics ──────────────────────────────────────────────────────────────

def test_weekly_within_month():
    raw = foreign_event_raw("w1", "Standup", rrule="FREQ=WEEKLY")  # unbounded, from 2026-01-06
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    assert _starts(occs) == [
        "2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00",
        "2026-01-20T09:00:00+00:00", "2026-01-27T09:00:00+00:00",
    ]
    assert all(not o.start_is_date for o in occs)
    assert all(o.end == o.start.replace("T09:00", "T09:30") for o in occs)


def test_weekly_across_month_boundary():
    raw = foreign_event_raw("w2", rrule="FREQ=WEEKLY")
    occs = recur.expand_occurrences(raw, date(2026, 1, 20), date(2026, 2, 15))
    assert _starts(occs) == [
        "2026-01-20T09:00:00+00:00", "2026-01-27T09:00:00+00:00",
        "2026-02-03T09:00:00+00:00", "2026-02-10T09:00:00+00:00",
    ]


def test_unbounded_rule_starting_years_in_the_past():
    # Weekly since 2020 (a Monday); browsing July 2026 must still list July's Mondays.
    raw = foreign_event_raw("old", dtstart="20200106T090000Z", dtend="20200106T093000Z",
                            rrule="FREQ=WEEKLY")
    occs = recur.expand_occurrences(raw, date(2026, 7, 1), date(2026, 8, 1))
    assert _starts(occs) == [
        "2026-07-06T09:00:00+00:00", "2026-07-13T09:00:00+00:00",
        "2026-07-20T09:00:00+00:00", "2026-07-27T09:00:00+00:00",
    ]


def test_count_and_until_are_bounded():
    count = foreign_event_raw("c", rrule="FREQ=WEEKLY;COUNT=3")
    assert len(recur.expand_occurrences(count, date(2026, 1, 1), date(2027, 1, 1))) == 3

    until = foreign_event_raw("u", rrule="FREQ=WEEKLY;UNTIL=20260120T090000Z")
    assert len(recur.expand_occurrences(until, date(2026, 1, 1), date(2026, 2, 1))) == 3
    # A window entirely past UNTIL yields nothing (proves the store superset drops here).
    assert recur.expand_occurrences(until, date(2026, 2, 1), date(2026, 3, 1)) == []


# ── all-day, EXDATE, RDATE ────────────────────────────────────────────────────

def test_all_day_weekly():
    raw = foreign_event_raw("ad", dtstart="20260106", dtend="20260107",
                            all_day=True, rrule="FREQ=WEEKLY;COUNT=3")
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    assert _starts(occs) == ["2026-01-06", "2026-01-13", "2026-01-20"]
    assert all(o.start_is_date and o.end_is_date for o in occs)


def test_exdate_removes_one_instance():
    raw = foreign_event_raw("ex", rrule="FREQ=WEEKLY;COUNT=4", exdate="20260113T090000Z")
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 10))
    assert _starts(occs) == [
        "2026-01-06T09:00:00+00:00", "2026-01-20T09:00:00+00:00",
        "2026-01-27T09:00:00+00:00",
    ]


def test_rdate_only_series_expands():
    # No RRULE, but RDATE adds a second instance — and read() flags it as recurring.
    raw = foreign_event_raw("rd", rdate="20260110T090000Z")
    fields = extract_from_raw(raw)
    assert fields.has_rrule is True  # RDATE counts as a recurrence set
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    assert sorted(_starts(occs)) == ["2026-01-06T09:00:00+00:00", "2026-01-10T09:00:00+00:00"]


# ── RECURRENCE-ID overrides ───────────────────────────────────────────────────

def test_override_moves_and_renames_one_instance():
    raw = foreign_event_raw(
        "ov", "Std", rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID:20260113T090000Z",
            "DTSTART:20260114T110000Z",
            "DTEND:20260114T113000Z",
            "SUMMARY:Moved",
        ),),
    )
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 10))
    by_anchor = {o.recurrence_id: o for o in occs}
    moved = by_anchor["2026-01-13T09:00:00+00:00"]
    assert moved.start == "2026-01-14T11:00:00+00:00"
    assert moved.summary == "Moved"
    assert moved.is_override is True
    # The other instances are untouched, non-override, and keep the master summary.
    others = [o for o in occs if o.recurrence_id != "2026-01-13T09:00:00+00:00"]
    assert all(o.summary == "Std" and not o.is_override for o in others)


def test_cancelled_override_is_dropped():
    raw = foreign_event_raw(
        "cx", rrule="FREQ=WEEKLY;COUNT=3",
        overrides=((
            "RECURRENCE-ID:20260113T090000Z",
            "DTSTART:20260113T090000Z",
            "STATUS:CANCELLED",
        ),),
    )
    occs = recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    assert _starts(occs) == ["2026-01-06T09:00:00+00:00", "2026-01-20T09:00:00+00:00"]


# ── timezones / DST ───────────────────────────────────────────────────────────

_CHICAGO_VTZ = (
    "BEGIN:VTIMEZONE",
    "TZID:America/Chicago",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:-0600",
    "TZOFFSETTO:-0500",
    "TZNAME:CDT",
    "DTSTART:19700308T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0600",
    "TZNAME:CST",
    "DTSTART:19701101T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
)


def test_dst_transition_keeps_local_wall_time():
    # Weekly 09:00 America/Chicago straddling the 2026-03-08 spring-forward.
    raw = foreign_event_raw(
        "dst", dtstart="TZID=America/Chicago:20260304T090000",
        dtend=None, rrule="FREQ=WEEKLY;COUNT=3", vtimezone=_CHICAGO_VTZ,
    )
    occs = recur.expand_occurrences(raw, date(2026, 3, 1), date(2026, 3, 25))
    # Local wall time stays 09:00; the UTC offset flips -06:00 (CST) -> -05:00 (CDT).
    assert occs[0].start.startswith("2026-03-04T09:00:00-06:00")
    assert occs[1].start.startswith("2026-03-11T09:00:00-05:00")
    assert occs[2].start.startswith("2026-03-18T09:00:00-05:00")


# ── guards / passthrough ──────────────────────────────────────────────────────

def test_subdaily_rule_is_refused_not_expanded():
    """A sub-daily rule is declined up front rather than expanded to a capped
    prefix. The cap bounded how many occurrences were *kept*, not the work done
    to find them: the library skips from DTSTART to the window one instance at a
    time before it yields anything, so cost grew with the DTSTART→window gap and
    no cap or `except` could bound it."""
    raw = foreign_event_raw("min", dtend="20260106T090100Z", rrule="FREQ=MINUTELY")
    t = time.monotonic()
    with pytest.raises(ValueError, match="instances/day"):
        recur.expand_occurrences(raw, date(2026, 1, 6), date(2026, 2, 17), max_occurrences=50)
    assert time.monotonic() - t < 2.0


def test_subdaily_rule_starting_long_before_the_window_is_still_fast():
    """The shape the old cap missed. With DTSTART at the window start the skip
    was empty and the guard looked fine; years earlier it ran unbounded."""
    raw = foreign_event_raw("sec", dtstart="20200101T000000Z", dtend="20200101T000100Z",
                            rrule="FREQ=SECONDLY")
    t = time.monotonic()
    with pytest.raises(ValueError, match="instances/day"):
        recur.expand_occurrences(raw, date(2026, 1, 6), date(2026, 2, 17), max_occurrences=50)
    assert time.monotonic() - t < 2.0


@pytest.mark.parametrize("rrule, per_day", [
    ("FREQ=DAILY;BYHOUR=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23"
     ";BYMINUTE=0,15,30,45", 96),
    ("FREQ=WEEKLY;BYHOUR=9,10,11;BYMINUTE=0,10,20,30,40,50;BYSECOND=0,30", 36),
])
def test_by_part_density_cannot_bypass_the_guard(rrule, per_day):
    """BY* parts multiply a coarse FREQ, so a rule that never looks sub-daily can
    still reach thousands of instances a day. Judging on FREQ alone let these
    through to the materializing path, which built the whole expansion before the
    occurrence cap was ever consulted."""
    raw = foreign_event_raw(f"by{per_day}", rrule=rrule)
    t = time.monotonic()
    with pytest.raises(ValueError, match="instances/day"):
        recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 12))
    assert time.monotonic() - t < 2.0


@pytest.mark.parametrize("rrule", [
    "FREQ=HOURLY",                                   # 24/day — the densest allowed
    "FREQ=DAILY;BYHOUR=9,12,15;BYMINUTE=0,30",       # 6/day
    "FREQ=WEEKLY;BYDAY=MO,WE,FR",                    # BYDAY does not inflate a day
])
def test_ordinary_density_still_expands(rrule):
    raw = foreign_event_raw("ok", rrule=rrule)
    assert recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))


def test_dense_rule_with_ancient_dtstart_is_refused_promptly():
    """Density alone does not bound the cost. FREQ=HOURLY sits exactly at the
    24/day limit, so the density guard passes it — but `query.between` pays the
    whole DTSTART -> window skip before yielding anything, and that skip is
    charged in full even for a one-day query. Measured before the total-walk
    bound existed: a year-0001 DTSTART burned 72 s and 1.3 GB of RSS to return
    24 occurrences, inside the service lock, reachable from the unauthenticated
    booking routes."""
    raw = foreign_event_raw("ancient", dtstart="00010101T000000Z",
                            dtend="00010101T003000Z", rrule="FREQ=HOURLY")
    t = time.monotonic()
    with pytest.raises(ValueError, match="instances to reach the window"):
        recur.expand_occurrences(raw, date(2026, 8, 1), date(2026, 8, 2))
    assert time.monotonic() - t < 2.0


def test_a_flooded_rdate_list_is_refused_before_it_is_expanded():
    """The pathology guard used to judge RRULE shapes only — it `continue`d on a
    component with no rule — so a recurrence set built from RDATE alone, or an
    ordinary rule beside a huge RDATE, was never priced at all.

    The occurrence cap does not cover it: `query.between` materializes the whole
    expansion before the cap is consulted, so the work is done in full and only
    then thrown away. Measured on one 664 KiB resource: 3.0 s and ~95 MB of RSS,
    inside the service lock, on an unauthenticated GET
    /api/public/booking/{token} — and 120 requests per 300 s per IP is far more
    than enough to hold that lock continuously with a single planted resource.

    Timed, because the refusal is the point and an answer is not: the old code
    raised ValueError too, just after paying for it."""
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rdate = ",".join(
        (base + timedelta(seconds=i)).strftime("%Y%m%dT%H%M%SZ") for i in range(20_000))
    raw = foreign_event_raw("flood", dtstart="20260801T000000Z",
                            dtend="20260801T000500Z", rdate=rdate)
    t = time.monotonic()
    with pytest.raises(ValueError, match="RDATE names 20000 instants"):
        recur.expand_occurrences(raw, date(2026, 8, 1), date(2026, 8, 3))
    # Parsing 300 KiB of ICS is the floor here and is bounded by the body limit;
    # what must not happen is the expansion on top of it.
    assert time.monotonic() - t < 2.0


def test_an_ordinary_rdate_list_still_expands():
    """The guard must not swallow the shape it exists beside: a handful of extra
    instants is what RDATE is for."""
    raw = foreign_event_raw("few", rrule="FREQ=WEEKLY;COUNT=2",
                            rdate="20260220T090000Z,20260221T090000Z")
    got = sorted(_starts(recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 12, 1))))
    assert got == [
        "2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00",
        "2026-02-20T09:00:00+00:00", "2026-02-21T09:00:00+00:00",
    ]


def test_an_out_of_range_sequence_cannot_stall_the_collection():
    """`SEQUENCE` is bound straight into a SQLite INTEGER column, which is
    64-bit while Python's ints are not. A value past that raised OverflowError at
    the bind — not ValueError, so the sync engine's malformed-resource guard did
    not catch it — which aborted the transaction, left the sync token
    un-advanced, and made the next pass re-fetch the same resource and fail
    identically. One resource from one CalDAV client froze every change from
    every client on that collection, permanently.

    Clamped at the boundary, exactly as `calendar-order` already is in
    dav/client.py. Radicale's own parser round-trips this value happily, so it
    really does reach us."""
    import sqlite3

    raw = foreign_event_raw("seq", extra=("SEQUENCE:99999999999999999999",))
    fields = extract_from_raw(raw)
    assert fields.sequence is None, "an unstorable SEQUENCE must read as absent"

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (s INTEGER)")
    conn.execute("INSERT INTO t VALUES (?)", (fields.sequence,))   # must not raise

    # An ordinary one still round-trips.
    ok = extract_from_raw(foreign_event_raw("seq2", extra=("SEQUENCE:7",)))
    assert ok.sequence == 7


def test_dense_rule_from_a_recent_dtstart_still_expands():
    """The total-walk bound must not swallow ordinary series: an hourly rule
    running for a couple of years is well inside budget and still expands."""
    raw = foreign_event_raw("recent", dtstart="20240101T000000Z",
                            dtend="20240101T003000Z", rrule="FREQ=HOURLY")
    assert recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 1, 2))


@pytest.mark.parametrize("interval", ["0", "-1", "notanumber"])
def test_nonpositive_interval_is_rejected_not_expanded(interval):
    """INTERVAL=0 is invalid per RFC 5545 but Radicale accepts it on the wire, so
    any client sharing the collection can write one. Expanding it never returns:
    the rule advances by nothing, so neither the occurrence cap nor the caller's
    `except Exception` can stop it. It must raise promptly instead — the caller
    then degrades to showing the master."""
    raw = foreign_event_raw("iv", rrule=f"FREQ=DAILY;INTERVAL={interval}")
    t = time.monotonic()
    with pytest.raises(ValueError):
        recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    assert time.monotonic() - t < 2.0     # rejected up front, never expanded


def test_positive_interval_still_expands():
    raw = foreign_event_raw("iv2", rrule="FREQ=DAILY;INTERVAL=7;COUNT=3")
    assert len(recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 3, 1))) == 3


def test_non_recurring_in_and_out_of_window():
    raw = foreign_event_raw("plain")  # no rrule
    assert len(recur.expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))) == 1
    assert recur.expand_occurrences(raw, date(2026, 3, 1), date(2026, 4, 1)) == []


# ── store candidate query (pure sqlite via the `db` fixture) ───────────────────

# ── per-occurrence write helpers (Tier 3), verified through the expander ───────

def test_override_edits_only_this_instance():
    # The UI always submits both start and end for an event (as the modal does).
    raw = apply_occurrence_override(
        _series(), "2026-01-20T09:00:00+00:00",
        EventEdit(summary="Moved!",
                  dtstart=datetime(2026, 1, 21, 14, 0, tzinfo=timezone.utc),
                  dtend=datetime(2026, 1, 21, 15, 0, tzinfo=timezone.utc)),
    )
    occs = {o.recurrence_id: o for o in recur.expand_occurrences(raw, *_WIN)}
    moved = occs["2026-01-20T09:00:00+00:00"]
    assert moved.start == "2026-01-21T14:00:00+00:00"
    assert moved.end == "2026-01-21T15:00:00+00:00"
    assert moved.summary == "Moved!" and moved.is_override
    assert [o.summary for k, o in occs.items() if k != "2026-01-20T09:00:00+00:00"] == ["Std"] * 4
    assert b"X-FOREIGN-KEEP" in raw  # invariant #2: foreign data survives


def test_exclude_removes_only_this_instance():
    raw = exclude_occurrence(_series(), "2026-01-13T09:00:00+00:00")
    starts = [o.start for o in recur.expand_occurrences(raw, *_WIN)]
    assert "2026-01-13T09:00:00+00:00" not in starts
    assert len(starts) == 4


def test_split_this_and_following():
    head, tail = split_series(_series(), "2026-01-20T09:00:00+00:00", EventEdit(summary="New"))
    head_starts = [o.start for o in recur.expand_occurrences(head, *_WIN)]
    tail_occs = recur.expand_occurrences(tail, *_WIN)
    assert head_starts == ["2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00"]
    assert tail_occs[0].start == "2026-01-20T09:00:00+00:00"
    assert all(o.summary == "New" for o in tail_occs)
    # Head and tail are distinct resources (distinct UIDs).
    assert b"UID:s@tasksd" in head and b"UID:s@tasksd" not in tail


def test_split_delete_truncates_head():
    # Delete "this and following": the caller keeps only the head.
    head, _tail = split_series(_series(), "2026-01-20T09:00:00+00:00", EventEdit())
    starts = [o.start for o in recur.expand_occurrences(head, *_WIN)]
    assert starts == ["2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00"]


def test_splitting_at_the_first_occurrence_leaves_no_head_to_write():
    """The head is always bounded with `UNTIL = anchor - 1s`. At the series'
    FIRST occurrence that is earlier than the head's own DTSTART, so its
    recurrence set is empty — and PUTting it left a VEVENT on the server, and a
    cache row, expanding to zero occurrences forever: `events_in_range` never
    emits it, so nothing could render or delete it again. "Delete this and
    following" from the first occurrence answered 204 and cleared the rows while
    deleting nothing at all. None tells the caller to delete the resource."""
    head, tail = split_series(_series(), "2026-01-06T09:00:00+00:00", EventEdit())
    assert head is None
    # The tail is still the whole series — nothing is lost by deleting the head.
    assert len(recur.expand_occurrences(tail, *_WIN)) == 5


def test_an_rdate_before_the_anchor_still_leaves_a_head():
    """A surviving RDATE generates an occurrence even when the rule cannot, so
    the head is not empty and must still be written."""
    raw = foreign_event_raw("rd@x", "Std", rrule="FREQ=WEEKLY;COUNT=3",
                            rdate="20260102T090000Z")
    head, _tail = split_series(raw, "2026-01-06T09:00:00+00:00", EventEdit())
    assert head is not None
    assert _starts(recur.expand_occurrences(head, *_WIN)) == ["2026-01-02T09:00:00+00:00"]


def test_split_rejects_a_dateness_switch_like_shift_does():
    """`shift_series` rejects this with a clean ValueError the route turns into
    a 422. `split_series` had no equivalent check, so `_wall_delta` subtracted a
    date from a datetime and raised TypeError — which the route does not map, so
    it escaped as a 500. The SPA reaches it in one click: the modal renders the
    "all day" checkbox for a recurring event, and a non-'all' scope sends a bare
    date string with no all_day flag."""
    with pytest.raises(ValueError):
        split_series(_series(), "2026-01-20T09:00:00+00:00",
                     EventEdit(dtstart=date(2026, 1, 22)))

    # And the other direction: a timed edit against an all-day series.
    all_day = foreign_event_raw("ad@x", "Std", dtstart="20260106", dtend="20260107",
                                all_day=True, rrule="FREQ=WEEKLY;COUNT=5")
    with pytest.raises(ValueError):
        split_series(all_day, "2026-01-20", EventEdit(dtstart=datetime(2026, 1, 22, 9, 0)))


def test_a_mixed_dtstart_dtend_master_is_still_editable():
    """`_event_duration` was the one datetime helper left doing a raw
    subtraction. A DTSTART/DTEND that disagree on value type or tz-awareness —
    both writable through Radicale by anything sharing the collection — raised
    TypeError, and since it sits on BOTH per-occurrence write paths and the
    routes only map ValueError, the event 500ed and could never be edited
    again."""
    # DATE-valued DTSTART beside a DATE-TIME DTEND.
    raw = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
           b"BEGIN:VEVENT\r\nUID:mixed@x\r\nDTSTART;VALUE=DATE:20260106\r\n"
           b"DTEND:20260106T100000Z\r\nRRULE:FREQ=WEEKLY;COUNT=4\r\n"
           b"SUMMARY:Std\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    head, tail = split_series(raw, "2026-01-20", EventEdit(summary="New"))
    assert head is not None and b"UID:mixed@x" in head
    assert b"SUMMARY:New" in tail

    # And the aware/naive pair, through the other write path.
    raw2 = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
            b"BEGIN:VEVENT\r\nUID:mixed2@x\r\nDTSTART;TZID=America/Chicago:20260106T090000\r\n"
            b"DTEND:20260106T100000\r\nRRULE:FREQ=WEEKLY;COUNT=4\r\n"
            b"SUMMARY:Std\r\nEND:VEVENT\r\n"
            + ("\r\n".join(_CHICAGO_VTZ) + "\r\n").encode() + b"END:VCALENDAR\r\n")
    out = apply_occurrence_override(raw2, "2026-01-20T09:00:00-06:00",
                                    EventEdit(summary="Just this"))
    assert b"SUMMARY:Just this" in out


# ── whole-series reschedule (shift_series) ────────────────────────────────────

def test_shift_series_moves_rule_exdate_and_override_together():
    raw = foreign_event_raw(
        "sh", "Std", rrule="FREQ=WEEKLY;UNTIL=20260203T090000Z",
        exdate="20260113T090000Z",
        overrides=((
            "RECURRENCE-ID:20260120T090000Z",
            "DTSTART:20260121T110000Z",
            "DTEND:20260121T113000Z",
            "SUMMARY:Moved",
        ),),
    )
    # The UI sends floating local times (as the modal does): +2 days.
    shifted = shift_series(raw, "2026-01-06T09:00:00+00:00",
                           EventEdit(dtstart=datetime(2026, 1, 8, 9, 0),
                                     dtend=datetime(2026, 1, 8, 9, 30)))
    occs = recur.expand_occurrences(shifted, *_WIN)
    by_anchor = {o.recurrence_id: o for o in occs}
    # 5 slots (1/8..2/5) minus the shifted EXDATE (1/15) = 4 occurrences.
    assert sorted(by_anchor) == [
        "2026-01-08T09:00:00+00:00", "2026-01-22T09:00:00+00:00",
        "2026-01-29T09:00:00+00:00", "2026-02-05T09:00:00+00:00",
    ]
    # The override stayed attached to its slot and moved by the same offset.
    moved = by_anchor["2026-01-22T09:00:00+00:00"]
    assert moved.start == "2026-01-23T11:00:00+00:00"
    assert moved.summary == "Moved" and moved.is_override
    assert b"X-FOREIGN-KEEP" in shifted  # invariant #2


def test_shift_series_base_is_the_overridden_start():
    # Dragging an occurrence that was already moved shifts the series by the
    # offset from where the user *sees* it, not from its original slot.
    raw = foreign_event_raw(
        "shov", rrule="FREQ=WEEKLY;COUNT=3",
        overrides=((
            "RECURRENCE-ID:20260113T090000Z",
            "DTSTART:20260114T110000Z",
            "DTEND:20260114T113000Z",
        ),),
    )
    shifted = shift_series(raw, "2026-01-13T09:00:00+00:00",
                           EventEdit(dtstart=datetime(2026, 1, 16, 11, 0)))
    starts = _starts(recur.expand_occurrences(shifted, *_WIN))
    # Visual offset was +2 days: masters 1/6 -> 1/8, override 1/14 11:00 -> 1/16 11:00.
    assert starts == [
        "2026-01-08T09:00:00+00:00", "2026-01-16T11:00:00+00:00",
        "2026-01-22T09:00:00+00:00",
    ]


def test_shift_series_all_day():
    raw = foreign_event_raw("shad", dtstart="20260106", dtend="20260107",
                            all_day=True, rrule="FREQ=WEEKLY;COUNT=3")
    shifted = shift_series(raw, "2026-01-06", EventEdit(dtstart=date(2026, 1, 9)))
    occs = recur.expand_occurrences(shifted, *_WIN)
    assert _starts(occs) == ["2026-01-09", "2026-01-16", "2026-01-23"]
    assert all(o.start_is_date and o.end_is_date for o in occs)


def test_shift_series_resize_changes_master_duration():
    shifted = shift_series(_series(), "2026-01-06T09:00:00+00:00",
                           EventEdit(dtstart=datetime(2026, 1, 6, 9, 0),
                                     dtend=datetime(2026, 1, 6, 10, 30)))
    occs = recur.expand_occurrences(shifted, *_WIN)
    assert _starts(occs)[0] == "2026-01-06T09:00:00+00:00"  # delta 0: dates unchanged
    assert all(o.end == o.start.replace("T09:00", "T10:30") for o in occs)


def test_shift_series_dst_wall_clock_preserved():
    raw = foreign_event_raw(
        "shdst", dtstart="TZID=America/Chicago:20260304T090000",
        dtend=None, rrule="FREQ=WEEKLY;COUNT=3", vtimezone=_CHICAGO_VTZ,
    )
    shifted = shift_series(raw, "2026-03-04T09:00:00-06:00",
                           EventEdit(dtstart=datetime(2026, 3, 5, 9, 0)))
    occs = recur.expand_occurrences(shifted, date(2026, 3, 1), date(2026, 3, 25))
    # 09:00 local survives the 2026-03-08 spring-forward; the offset flips.
    assert occs[0].start.startswith("2026-03-05T09:00:00-06:00")
    assert occs[1].start.startswith("2026-03-12T09:00:00-05:00")
    assert occs[2].start.startswith("2026-03-19T09:00:00-05:00")


def test_shift_series_rotates_weekly_byday():
    raw = foreign_event_raw("shbd", rrule="FREQ=WEEKLY;BYDAY=TU;COUNT=3")  # 1/6 is a Tuesday
    shifted = shift_series(raw, "2026-01-06T09:00:00+00:00",
                           EventEdit(dtstart=datetime(2026, 1, 7, 9, 0)))
    assert b"BYDAY=WE" in shifted
    starts = _starts(recur.expand_occurrences(shifted, *_WIN))
    assert starts == [
        "2026-01-07T09:00:00+00:00", "2026-01-14T09:00:00+00:00",
        "2026-01-21T09:00:00+00:00",
    ]


def test_shift_series_rejects_dateness_switch():
    with pytest.raises(ValueError):
        shift_series(_series(), "2026-01-06T09:00:00+00:00",
                     EventEdit(dtstart=date(2026, 1, 8)))


def test_dragging_a_bounded_zoned_series_across_a_fall_back_keeps_every_occurrence():
    """UNTIL was shifted by the WALL-CLOCK delta while sitting in UTC.

    DTSTART is zone-aware, so `dt + delta` preserves its wall clock and its UTC
    instant moves by `delta ± the DST change`; UNTIL is a UTC instant and moved
    by exactly `delta`. Carrying the series across a transition made the two
    disagree by an hour, UNTIL landed before the final generated slot, and that
    occurrence was silently dropped — a bounded series quietly lost its last
    event on a drag that was only supposed to move it."""
    # Weekly 09:00 Chicago from Oct 14, bounded at its own last slot: Oct 28
    # 09:00 CDT is 14:00Z. Three occurrences, all before the fall-back.
    raw = foreign_event_raw(
        "shuntil", dtstart="TZID=America/Chicago:20261014T090000", dtend=None,
        rrule="FREQ=WEEKLY;UNTIL=20261028T140000Z", vtimezone=_CHICAGO_VTZ,
    )
    win = (date(2026, 10, 1), date(2026, 12, 15))
    assert len(recur.expand_occurrences(raw, *win)) == 3

    # Drag it a week later. The final slot is now Nov 4, on the far side of the
    # 2026-11-01 fall-back: 09:00 there is CST, 15:00Z, while a UTC UNTIL moved
    # by the bare 7-day delta lands at 14:00Z — an hour short of the occurrence
    # it is supposed to include.
    shifted = shift_series(raw, "2026-10-14T09:00:00-05:00",
                           EventEdit(dtstart=datetime(2026, 10, 21, 9, 0)))
    occs = recur.expand_occurrences(shifted, *win)
    assert len(occs) == 3, [o.start for o in occs]
    assert occs[0].start.startswith("2026-10-21T09:00:00-05:00")
    assert occs[2].start.startswith("2026-11-04T09:00:00-06:00")   # the one that vanished


def test_shift_series_tolerates_timed_override_on_all_day_series():
    # A foreign client gave one instance of an all-day series a timed override;
    # dragging the series via that occurrence must not crash (date − datetime).
    raw = foreign_event_raw(
        "shmx", dtstart="20260106", dtend=None, all_day=True,
        rrule="FREQ=WEEKLY;COUNT=3",
        overrides=((
            "RECURRENCE-ID;VALUE=DATE:20260113",
            "DTSTART:20260114T110000Z",
            "DTEND:20260114T113000Z",
        ),),
    )
    shifted = shift_series(raw, "2026-01-13", EventEdit(dtstart=date(2026, 1, 16)))
    occs = recur.expand_occurrences(shifted, *_WIN)
    # The visual base is the override's day (1/14), so the drag is +2 days.
    assert len(occs) == 3
    assert occs[0].start == "2026-01-08"


# ── TZID series: per-occurrence ops must stay in the series' zone ─────────────

def _chicago_series() -> bytes:
    """Weekly 09:00 America/Chicago, 4 occurrences straddling the 2026-03-08
    spring-forward (3/4 CST, then 3/11, 3/18, 3/25 CDT)."""
    return foreign_event_raw(
        "ctz", "Std", dtstart="TZID=America/Chicago:20260304T090000",
        dtend=None, rrule="FREQ=WEEKLY;COUNT=4", vtimezone=_CHICAGO_VTZ,
    )


_MARCH = (date(2026, 3, 1), date(2026, 4, 1))


def test_override_on_tzid_series_keeps_zone_and_edits_twice():
    # The anchor arrives as a fixed-offset ISO; the override written from it
    # must carry the series' real TZID, not a fabricated numeric one.
    raw = apply_occurrence_override(
        _chicago_series(), "2026-03-04T09:00:00-06:00", EventEdit(summary="Moved"))
    assert b'TZID="UTC-06:00"' not in raw
    assert raw.count(b"RECURRENCE-ID;TZID=America/Chicago:20260304T090000") == 1
    # Editing the same occurrence again must find that override (not append a
    # duplicate whose edit the expander silently ignores).
    raw2 = apply_occurrence_override(
        raw, "2026-03-04T09:00:00-06:00", EventEdit(summary="Moved again"))
    assert raw2.count(b"RECURRENCE-ID") == 1
    occs = {o.recurrence_id: o for o in recur.expand_occurrences(raw2, *_MARCH)}
    assert occs["2026-03-04T09:00:00-06:00"].summary == "Moved again"


def test_exclude_on_tzid_series_keeps_zone():
    raw = exclude_occurrence(_chicago_series(), "2026-03-11T09:00:00-05:00")
    assert b'TZID="UTC-05:00"' not in raw
    assert _starts(recur.expand_occurrences(raw, *_MARCH)) == [
        "2026-03-04T09:00:00-06:00",
        "2026-03-18T09:00:00-05:00", "2026-03-25T09:00:00-05:00",
    ]


def test_split_tzid_series_tail_keeps_zone():
    head, tail = split_series(_chicago_series(), "2026-03-11T09:00:00-05:00", EventEdit())
    assert b'TZID="UTC-05:00"' not in head and b'TZID="UTC-05:00"' not in tail
    assert b"DTSTART;TZID=America/Chicago:20260311T090000" in tail
    assert _starts(recur.expand_occurrences(head, *_MARCH)) == ["2026-03-04T09:00:00-06:00"]
    # The tail stays zone-aware — real offsets, DST-correct — not floating.
    assert _starts(recur.expand_occurrences(tail, *_MARCH)) == [
        "2026-03-11T09:00:00-05:00", "2026-03-18T09:00:00-05:00",
        "2026-03-25T09:00:00-05:00",
    ]


# ── split bookkeeping: COUNT stays bounded, RDATE/EXDATE are partitioned ──────

def test_split_count_series_tail_is_bounded():
    # COUNT=5 split at the 3rd: 2 stay in the head, 3 in the tail. The tail
    # must NOT become an unbounded forever-series.
    _head, tail = split_series(_series(), "2026-01-20T09:00:00+00:00", EventEdit())
    assert b"COUNT=3" in tail
    assert _starts(recur.expand_occurrences(tail, date(2026, 1, 1), date(2027, 1, 1))) == [
        "2026-01-20T09:00:00+00:00", "2026-01-27T09:00:00+00:00",
        "2026-02-03T09:00:00+00:00",
    ]


@pytest.mark.parametrize("rrule, rule_end", [
    ("FREQ=WEEKLY;COUNT=2", "FREQ=WEEKLY;COUNT=2"),
    ("FREQ=WEEKLY;UNTIL=20260113T090000Z", "FREQ=WEEKLY;UNTIL=20260113T090000Z"),
])
def test_splitting_at_an_rdate_past_the_rule_never_widens_the_head(rrule, rule_end):
    """A split cuts a series in two; it cannot conjure occurrences.

    The head used to be rebounded unconditionally — drop COUNT, set
    `UNTIL = anchor - 1s` — which only narrows when the anchor is a slot the
    RRULE itself generates. `_require_occurrence` deliberately accepts an anchor
    named by an RDATE, and an RDATE routinely sits AFTER where the rule stopped:
    that is the ordinary reason to add one. For those the rebind EXTENDED the
    rule, and every slot between the rule's real end and the anchor became live.

    Two clicks from the SPA, which offers the scope picker on an RDATE row like
    any other — and `delete_event(scope="thisandfuture")` PUTs the head, so the
    invented occurrences are written permanently into the shared collection,
    where they also start blocking the public booking page."""
    raw = foreign_event_raw("late", rrule=rrule, rdate="20260220T090000Z")
    wide = (date(2026, 1, 1), date(2026, 12, 1))
    before = _starts(recur.expand_occurrences(raw, *wide))
    assert sorted(before) == [
        "2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00",
        "2026-02-20T09:00:00+00:00",
    ]

    head, tail = split_series(raw, "2026-02-20T09:00:00+00:00", EventEdit())
    head_occ = _starts(recur.expand_occurrences(head, *wide)) if head else []
    tail_occ = _starts(recur.expand_occurrences(tail, *wide))

    # The head keeps exactly the two the rule already made — and its rule is
    # untouched, because the RDATE partition alone is the whole split here.
    assert sorted(head_occ) == [
        "2026-01-06T09:00:00+00:00", "2026-01-13T09:00:00+00:00",
    ]
    assert rule_end.encode() in head
    assert tail_occ == ["2026-02-20T09:00:00+00:00"]
    # Nothing invented, nothing lost.
    assert sorted(head_occ + tail_occ) == sorted(before)


def test_a_tail_split_off_past_the_rules_end_carries_no_dead_rule():
    """The mirror of the above on the other side of the cut: the tail inherited
    the original UNTIL, which now precedes its own DTSTART — a rule that
    generates nothing sitting beside a DTSTART that does. The anchor is a
    one-off, so the tail says so rather than shipping a self-contradicting
    rule."""
    raw = foreign_event_raw(
        "late2", rrule="FREQ=WEEKLY;UNTIL=20260113T090000Z", rdate="20260220T090000Z")
    _, tail = split_series(raw, "2026-02-20T09:00:00+00:00", EventEdit())
    assert b"RRULE" not in tail
    assert _starts(recur.expand_occurrences(
        tail, date(2026, 1, 1), date(2026, 12, 1))) == ["2026-02-20T09:00:00+00:00"]


def test_split_partitions_rdate_and_exdate():
    raw = foreign_event_raw(
        "rdx", rrule="FREQ=WEEKLY;COUNT=4",
        rdate="20260220T090000Z", exdate="20260127T090000Z",
    )
    head, tail = split_series(raw, "2026-01-13T09:00:00+00:00", EventEdit())
    wide = (date(2026, 1, 1), date(2026, 12, 1))
    # The post-anchor RDATE belongs to the tail — UNTIL only bounds the RRULE,
    # so without partitioning the 2/20 instance would survive in the head (and
    # "delete this and following" would resurrect it) AND duplicate in the tail.
    assert _starts(recur.expand_occurrences(head, *wide)) == ["2026-01-06T09:00:00+00:00"]
    # Tail: 1/13, 1/20 (1/27 is EXDATE'd — it moved here too), plus the RDATE.
    # (sorted: the expander doesn't order RDATE instances chronologically)
    assert sorted(_starts(recur.expand_occurrences(tail, *wide))) == [
        "2026-01-13T09:00:00+00:00", "2026-01-20T09:00:00+00:00",
        "2026-02-20T09:00:00+00:00",
    ]


def _seed(conn, uid, raw):
    fields = extract_from_raw(raw)
    item = Item(href=f"/cal/{uid}.ics", etag=f'"{uid}"', data=raw)
    store.upsert_item(conn, "/cal/", item, fields)


def test_range_query_admits_past_recurring_master(db):
    store.upsert_collection(
        db, CollectionInfo(href="/cal/", displayname="Cal", components={"VEVENT"})
    )
    # Recurring master whose own DTSTART/DTEND are long past (a Monday in 2020)…
    _seed(db, "recur", foreign_event_raw(
        "recur", dtstart="20200106T090000Z", dtend="20200106T093000Z", rrule="FREQ=WEEKLY"))
    # …vs a non-recurring event that really is in the past.
    _seed(db, "onceoff", foreign_event_raw(
        "onceoff", dtstart="20200106T090000Z", dtend="20200106T093000Z"))

    rows = store.get_events_in_range(db, "/cal/", "2026-07-01", "2026-08-01")
    uids = {r["uid"] for r in rows}
    assert "recur" in uids       # admitted on the upper bound alone (fixed)
    assert "onceoff" not in uids  # precise overlap still excludes a truly-past single


# ── split_series: the tail moves as a unit ───────────────────────────────────
# CalendarView sends start/end on EVERY "this and following" save, using the
# times the occurrence is DISPLAYED at. For an occurrence a previous override
# moved, that start differs from the anchor — so these are the ordinary paths,
# not edge cases.

def _overridden_series() -> bytes:
    """Weekly 09:00-10:00 from 2026-02-02 (COUNT=6), with 2026-02-09 overridden
    to 14:00-15:30 and retitled."""
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//EN\r\n"
        "BEGIN:VEVENT\r\nUID:s@x\r\nDTSTAMP:20260101T000000Z\r\n"
        "DTSTART:20260202T090000Z\r\nDTEND:20260202T100000Z\r\n"
        "SUMMARY:standup\r\nRRULE:FREQ=WEEKLY;COUNT=6\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:s@x\r\nDTSTAMP:20260101T000000Z\r\n"
        "RECURRENCE-ID:20260209T090000Z\r\n"
        "DTSTART:20260209T140000Z\r\nDTEND:20260209T153000Z\r\n"
        "SUMMARY:special\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


_FEB = (date(2026, 2, 1), date(2026, 3, 20))


def test_split_retitling_an_overridden_occurrence_leaves_the_schedule_alone():
    """A pure title edit. The modal still sends the occurrence's displayed
    14:00 start, which is not the 09:00 anchor — that difference used to be
    written onto the tail master as an absolute DTSTART, dragging every later
    occurrence to 14:00 and lengthening them to 90 minutes."""
    _head, tail = split_series(
        _overridden_series(), "2026-02-09T09:00:00+00:00",
        EventEdit(summary="renamed",
                  dtstart=datetime(2026, 2, 9, 14, 0, tzinfo=timezone.utc),
                  dtend=datetime(2026, 2, 9, 15, 30, tzinfo=timezone.utc)),
    )
    occs = recur.expand_occurrences(tail, *_FEB)
    assert _starts(occs) == [
        "2026-02-09T14:00:00+00:00",     # the override, untouched
        "2026-02-16T09:00:00+00:00",     # the cadence, untouched
        "2026-02-23T09:00:00+00:00",
        "2026-03-02T09:00:00+00:00",
        "2026-03-09T09:00:00+00:00",
    ]
    # And 2026-02-09 appears once: the re-homed override still replaces its slot
    # rather than sitting beside a generated instance.
    assert sum(1 for o in occs if o.start.startswith("2026-02-09")) == 1


def test_split_with_a_real_time_change_still_moves_the_whole_tail():
    """The other half — this must keep working."""
    _head, tail = split_series(
        _overridden_series(), "2026-02-16T09:00:00+00:00",
        EventEdit(dtstart=datetime(2026, 2, 16, 11, 0, tzinfo=timezone.utc),
                  dtend=datetime(2026, 2, 16, 12, 0, tzinfo=timezone.utc)),
    )
    assert _starts(recur.expand_occurrences(tail, *_FEB)) == [
        "2026-02-16T11:00:00+00:00", "2026-02-23T11:00:00+00:00",
        "2026-03-02T11:00:00+00:00", "2026-03-09T11:00:00+00:00",
    ]


def test_split_time_change_carries_the_tail_exdates_and_overrides():
    """Shifting the master alone left the partitioned EXDATE matching no
    generated slot, so a deleted occurrence came back, and left the re-homed
    override's RECURRENCE-ID replacing nothing, so it doubled."""
    raw = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//EN\r\n"
        "BEGIN:VEVENT\r\nUID:s@x\r\nDTSTAMP:20260101T000000Z\r\n"
        "DTSTART:20260202T090000Z\r\nDTEND:20260202T100000Z\r\n"
        "SUMMARY:standup\r\nRRULE:FREQ=WEEKLY;COUNT=6\r\n"
        "EXDATE:20260216T090000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:s@x\r\nDTSTAMP:20260101T000000Z\r\n"
        "RECURRENCE-ID:20260223T090000Z\r\n"
        "DTSTART:20260223T140000Z\r\nDTEND:20260223T150000Z\r\n"
        "SUMMARY:special\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()
    _head, tail = split_series(
        raw, "2026-02-02T09:00:00+00:00",
        EventEdit(dtstart=datetime(2026, 2, 3, 9, 0, tzinfo=timezone.utc),
                  dtend=datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)),
    )
    starts = _starts(recur.expand_occurrences(tail, *_FEB))
    assert not any(s.startswith("2026-02-17") for s in starts), "the EXDATE hole came back"
    assert starts == [
        "2026-02-03T09:00:00+00:00", "2026-02-10T09:00:00+00:00",
        "2026-02-24T14:00:00+00:00",      # the override, shifted with the tail
        "2026-03-03T09:00:00+00:00", "2026-03-10T09:00:00+00:00",
    ]


# ── EXDATE/RDATE property lines survive a rewrite intact ─────────────────────
# Rewriting a date-list used to flatten every property line into one, so
# icalendar derived a single TZID for the whole set (the last entry's zone)
# while still serializing each value in its own wall time — silently moving
# every exclusion that came from a different zone.

def _paris_exdate_series() -> bytes:
    """Weekly 09:00 America/New_York with two exclusions a foreign client wrote
    in different zones — ordinary in a shared collection."""
    return foreign_event_raw(
        "mz", "Std", dtstart="TZID=America/New_York:20260105T090000",
        dtend="TZID=America/New_York:20260105T093000", rrule="FREQ=WEEKLY",
        extra=(
            "EXDATE;TZID=America/New_York:20260112T090000",
            "EXDATE;TZID=Europe/Paris:20260119T150000",
        ),
    )


def _exdate_instants(raw: bytes) -> list[str]:
    """Every EXDATE value, re-parsed and normalized to UTC. Compares the
    *instants* the property names, which is what a wrong TZID label corrupts —
    a string compare would not notice."""
    prop = _master(raw).get("EXDATE")
    return sorted(
        entry.dt.astimezone(timezone.utc).isoformat()
        for lst in (prop if isinstance(prop, list) else [prop])
        for entry in lst.dts
    )


def test_shift_series_keeps_each_exdate_in_its_own_zone():
    raw = _paris_exdate_series()
    assert _exdate_instants(raw) == [
        "2026-01-12T14:00:00+00:00", "2026-01-19T14:00:00+00:00",
    ]
    shifted = shift_series(raw, "2026-01-05T09:00:00-05:00",
                           EventEdit(dtstart=datetime(2026, 1, 5, 10, 0),
                                     dtend=datetime(2026, 1, 5, 11, 0)))
    # Both exclusions moved by the same +1h the series did — and no more.
    assert _exdate_instants(shifted) == [
        "2026-01-12T15:00:00+00:00", "2026-01-19T15:00:00+00:00",
    ]
    # Still two property lines, each labelled with the zone it was written in.
    lines = [ln for ln in shifted.decode().replace("\r\n", "\n").split("\n")
             if ln.startswith("EXDATE")]
    assert lines == [
        "EXDATE;TZID=America/New_York:20260112T100000",
        "EXDATE;TZID=Europe/Paris:20260119T160000",
    ]


def test_shift_series_never_puts_a_tzid_on_a_utc_exdate():
    """RFC 5545 §3.2.19 forbids TZID on a UTC value; merging the lines produced
    exactly that, so other CalDAV clients rejected the resource outright."""
    raw = foreign_event_raw(
        "uz", "Std", dtstart="TZID=America/New_York:20260105T090000",
        dtend="TZID=America/New_York:20260105T093000", rrule="FREQ=WEEKLY",
        extra=(
            "EXDATE:20260119T140000Z",
            "EXDATE;TZID=America/New_York:20260126T090000",
        ),
    )
    shifted = shift_series(raw, "2026-01-05T09:00:00-05:00",
                           EventEdit(dtstart=datetime(2026, 1, 5, 10, 0)))
    lines = [ln for ln in shifted.decode().replace("\r\n", "\n").split("\n")
             if ln.startswith("EXDATE")]
    assert lines == [
        "EXDATE:20260119T150000Z",
        "EXDATE;TZID=America/New_York:20260126T100000",
    ]


def test_split_partitioning_keeps_each_exdate_in_its_own_zone():
    # _partition_datelist had the same flattening bug as _shift_datelist, so the
    # side that keeps entries from two zones is the one that has to be asserted.
    raw = foreign_event_raw(
        "mz3", "Std", dtstart="TZID=America/New_York:20260105T090000",
        dtend="TZID=America/New_York:20260105T093000", rrule="FREQ=WEEKLY",
        extra=(
            "EXDATE;TZID=America/New_York:20260112T090000",
            "EXDATE;TZID=Europe/Paris:20260119T150000",
            "EXDATE;TZID=America/New_York:20260126T090000",
        ),
    )
    head, tail = split_series(raw, "2026-01-19T15:00:00+01:00", EventEdit())
    assert _exdate_instants(head) == ["2026-01-12T14:00:00+00:00"]
    assert _exdate_instants(tail) == [
        "2026-01-19T14:00:00+00:00", "2026-01-26T14:00:00+00:00",
    ]
    assert b"EXDATE;TZID=America/New_York:20260112T090000" in head
    assert b"EXDATE;TZID=Europe/Paris:20260119T150000" in tail
    assert b"EXDATE;TZID=America/New_York:20260126T090000" in tail


# ── RDATE;VALUE=PERIOD (a tuple value, not a datetime) ───────────────────────
# vDDDTypes.dt is a (start, end) or (start, duration) tuple for a PERIOD, which
# used to raise TypeError in the shift and partition helpers — a 500 that made
# such an event permanently uneditable.

def _period_series() -> bytes:
    return foreign_event_raw(
        "per", "P", dtstart="20260101T090000Z", dtend="20260101T110000Z",
        rrule="FREQ=WEEKLY",
        extra=("RDATE;VALUE=PERIOD:20260210T090000Z/20260210T110000Z,"
               "20260217T090000Z/PT2H",),
    )


def _rdate_lines(raw: bytes) -> list[str]:
    return [ln for ln in raw.decode().replace("\r\n", "\n").split("\n")
            if ln.startswith("RDATE")]


def test_shift_series_moves_a_period_rdate():
    shifted = shift_series(_period_series(), "2026-01-01T09:00:00+00:00",
                           EventEdit(dtstart=datetime(2026, 1, 1, 10, 0)))
    # Both ends of an explicit period move; a duration is a span, so it stays.
    assert _rdate_lines(shifted) == [
        "RDATE;VALUE=PERIOD:20260210T100000Z/20260210T120000Z,"
        "20260217T100000Z/PT2H"
    ]


def test_split_series_partitions_a_period_rdate():
    # The periods (2/10, 2/17) both sit after the anchor, so they belong to the
    # tail — addressed by where each period starts.
    head, tail = split_series(_period_series(), "2026-01-08T09:00:00+00:00",
                              EventEdit())
    assert _rdate_lines(head) == []
    assert _rdate_lines(tail) == _rdate_lines(_period_series())


# ── property parameters survive a shift (RANGE=THISANDFUTURE) ────────────────

def test_shift_series_preserves_recurrence_id_parameters():
    """`_shift_datelike` re-added only the value, so RANGE=THISANDFUTURE — "this
    override covers this and every later occurrence" — was dropped and every
    later occurrence silently reverted to the master."""
    raw = foreign_event_raw(
        "tf", "Std", dtstart="TZID=America/New_York:20260105T090000",
        dtend="TZID=America/New_York:20260105T093000", rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=America/New_York:20260112T090000",
            "DTSTART;TZID=America/New_York:20260112T110000",
            "DTEND;TZID=America/New_York:20260112T113000",
            "SUMMARY:TF",
        ),),
    )
    shifted = shift_series(raw, "2026-01-05T09:00:00-05:00",
                           EventEdit(dtstart=datetime(2026, 1, 5, 10, 0)))
    rid = _overrides(shifted)[0].get("RECURRENCE-ID")
    assert rid.params.get("RANGE") == "THISANDFUTURE"
    # TZID is re-derived from the shifted value, never carried over verbatim.
    assert rid.params.get("TZID") == "America/New_York"
    assert rid.dt == datetime(2026, 1, 12, 10, 0, tzinfo=ZoneInfo("America/New_York"))


# ── UNTIL matches DTSTART's value type (RFC 5545 §3.3.10) ────────────────────
# The "Repeat until" field is an <input type="date">, so a timed series used to
# get `UNTIL=20260302` against a DATE-TIME DTSTART — read as that day's midnight,
# dropping the occurrence on the very day the user picked.

def _rrule_line(raw: bytes) -> str:
    return next(ln for ln in raw.decode().replace("\r\n", "\n").split("\n")
                if ln.startswith("RRULE"))


_UNTIL_WIN = (date(2026, 1, 1), date(2026, 4, 1))


def test_until_day_is_included_on_a_floating_timed_series():
    raw = build_new_event(
        "u@f", summary="S", dtstart=datetime(2026, 2, 2, 9, 0),
        edit=EventEdit(rrule=rrule_from_spec("weekly", until=date(2026, 3, 2))),
    )
    assert _rrule_line(raw) == "RRULE:FREQ=WEEKLY;UNTIL=20260302T235959"
    assert _starts(recur.expand_occurrences(raw, *_UNTIL_WIN))[-1] == "2026-03-02T09:00:00"


def test_until_is_utc_and_covers_the_local_day_on_a_zone_aware_series():
    """DTSTART is not floating, so RFC 5545 requires a UTC UNTIL — but the day
    the user picked is a *local* day, so it has to be widened in the series' own
    zone before conversion, not in UTC."""
    raw = build_new_event(
        "u@z", summary="S",
        dtstart=datetime(2026, 2, 2, 9, 0, tzinfo=ZoneInfo("America/New_York")),
        edit=EventEdit(rrule=rrule_from_spec("weekly", until=date(2026, 3, 2))),
    )
    # 2026-03-02 23:59:59 New York, expressed as the UTC instant it is.
    assert _rrule_line(raw) == "RRULE:FREQ=WEEKLY;UNTIL=20260303T045959Z"
    assert _starts(recur.expand_occurrences(raw, *_UNTIL_WIN))[-1] == \
        "2026-03-02T09:00:00-05:00"


def test_until_stays_a_bare_date_on_an_all_day_series():
    raw = build_new_event(
        "u@a", summary="A", dtstart=date(2026, 2, 2), dtend=date(2026, 2, 3),
        edit=EventEdit(rrule=rrule_from_spec("weekly", until=date(2026, 3, 2))),
    )
    assert _rrule_line(raw) == "RRULE:FREQ=WEEKLY;UNTIL=20260302"
    assert _starts(recur.expand_occurrences(raw, *_UNTIL_WIN))[-1] == "2026-03-02"


def test_a_foreign_until_is_not_rewritten_by_an_unrelated_edit():
    # Already the right value type: renaming the event must leave it byte-identical
    # (invariant #2 — we only touch what the user changed).
    raw = foreign_event_raw("u@k", "F", rrule="FREQ=WEEKLY;UNTIL=20260302T090000Z")
    assert _rrule_line(apply_event_changes(raw, EventEdit(summary="renamed"))) == \
        "RRULE:FREQ=WEEKLY;UNTIL=20260302T090000Z"


def test_shifting_a_series_keeps_until_in_dtstarts_value_type():
    raw = build_new_event(
        "u@s", summary="S", dtstart=datetime(2026, 2, 2, 9, 0),
        edit=EventEdit(rrule=rrule_from_spec("weekly", until=date(2026, 3, 2))),
    )
    shifted = shift_series(raw, "2026-02-02T09:00:00",
                           EventEdit(dtstart=datetime(2026, 2, 3, 9, 0)))
    # UNTIL moved with the series and stayed a floating DATE-TIME.
    assert _rrule_line(shifted) == "RRULE:FREQ=WEEKLY;UNTIL=20260303T235959"
    assert _starts(recur.expand_occurrences(shifted, *_UNTIL_WIN))[-1] == \
        "2026-03-03T09:00:00"


# ── RANGE=THISANDFUTURE: one override, several distinct instances ────────────
# Such an override covers its own slot and every later one, so the expander
# emits several instances that all carry the *same* RECURRENCE-ID. The anchor
# both keys the UI row and addresses the instance for a per-occurrence write, so
# a shared one meant "delete this event" on the last instance EXDATE'd the first.

def _thisandfuture_series() -> bytes:
    """Weekly 09:00Z of 4; from the 2nd on, an Apple-style "this and all future
    events" override moves them to 10:00 and renames them."""
    return foreign_event_raw(
        "tf@x", "Std", rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
            "DTSTART:20260113T100000Z",
            "DTEND:20260113T103000Z",
            "SUMMARY:TF",
            # A LOCATION the MASTER does not carry, so "which component was this
            # seeded from" is answerable rather than a matter of inspection.
            "LOCATION:Room B",
        ),),
    )


_TF_WIN = (date(2026, 1, 1), date(2026, 2, 10))


def test_thisandfuture_instances_get_their_own_rule_slot():
    occs = recur.expand_occurrences(_thisandfuture_series(), *_TF_WIN)
    assert len({o.recurrence_id for o in occs}) == len(occs), "duplicate anchors"
    # Each anchor is the slot the master's RRULE generates for that instance —
    # 09:00, not the 10:00 the override moved it to.
    assert [(o.recurrence_id, o.start) for o in occs] == [
        ("2026-01-06T09:00:00+00:00", "2026-01-06T09:00:00+00:00"),
        ("2026-01-13T09:00:00+00:00", "2026-01-13T10:00:00+00:00"),
        ("2026-01-20T09:00:00+00:00", "2026-01-20T10:00:00+00:00"),
        ("2026-01-27T09:00:00+00:00", "2026-01-27T10:00:00+00:00"),
    ]
    # Every instance the override covers is still flagged as override-backed —
    # it is where their summary and times come from — even though each now
    # anchors on its own slot.
    assert [o.is_override for o in occs] == [False, True, True, True]


def test_deleting_a_thisandfuture_instance_removes_that_one():
    """The anchor has to be the value an EXDATE must carry to name this
    instance. Sharing the first override's anchor meant deleting the last
    occurrence silently deleted the first instead."""
    series = _thisandfuture_series()
    # Address it exactly as the SPA does: with the anchor the expander handed it
    # for the row the user clicked (the last one, on 2026-01-27).
    clicked = recur.expand_occurrences(series, *_TF_WIN)[-1]
    assert clicked.start.startswith("2026-01-27")
    raw = exclude_occurrence(series, clicked.recurrence_id)
    assert _starts(recur.expand_occurrences(raw, *_TF_WIN)) == [
        "2026-01-06T09:00:00+00:00", "2026-01-13T10:00:00+00:00",
        "2026-01-20T10:00:00+00:00",
    ]


def test_a_thisandfuture_override_mixing_floating_and_zoned_still_expands():
    """`_thisandfuture_shifts` guarded one mismatch between the override's
    RECURRENCE-ID and its DTSTART — dateness — and not the other. A floating
    value beside a zoned one is two datetimes, so the dateness check passes and
    `dtstart.dt - rid.dt` raises TypeError. That runs before any expansion, so
    it escapes `expand_occurrences` (documented as raising ValueError) and
    `events_in_range` falls into its `except Exception` branch: the whole series
    collapses to one master row and every occurrence vanishes from the
    calendar."""
    series = foreign_event_raw(
        "mixtf@x", "Std", rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",   # zoned (UTC)
            "DTSTART:20260113T100000",                              # floating
            "DTEND:20260113T103000",
            "SUMMARY:TF",
        ),),
    )
    occs = recur.expand_occurrences(series, *_TF_WIN)

    # It expands rather than blowing up, and every instance keeps a distinct
    # anchor — the dedup fallback, which is the intended degradation.
    assert len(occs) >= 4, _starts(occs)
    assert len({o.recurrence_id for o in occs}) == len(occs), "duplicate anchors"


def test_the_edit_path_tolerates_the_same_mixed_override():
    """`edit._tf_shift` is the write-path twin of the guard above, and had the
    identical gap — so the same resource 500ed on a split instead of expanding
    wrong."""
    series = foreign_event_raw(
        "mixtf2@x", "Std", rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
            "DTSTART:20260113T100000",
            "DTEND:20260113T103000",
            "SUMMARY:TF",
        ),),
    )
    head, tail = split_series(series, "2026-01-20T09:00:00+00:00", EventEdit(summary="New"))
    assert head is not None and b"SUMMARY:New" in tail


def test_deleting_a_thisandfuture_overrides_own_slot_keeps_the_later_ones():
    """A RANGE=THISANDFUTURE override carries the values for its own slot AND
    every later one (RFC 5545 §3.2.13). `exclude_occurrence` dropped any
    component whose RECURRENCE-ID matched the anchor, which for this shape threw
    away the times, summary and everything else a foreign client had authored
    for all subsequent occurrences — they silently snapped back to the master.
    The EXDATE alone removes the instance the user asked about."""
    series = _thisandfuture_series()
    # Delete the override's OWN slot, the second occurrence.
    raw = exclude_occurrence(series, "2026-01-13T09:00:00+00:00")
    occs = recur.expand_occurrences(raw, *_TF_WIN)

    assert _starts(occs) == [
        "2026-01-06T09:00:00+00:00",     # before the override: untouched
        "2026-01-20T10:00:00+00:00",     # still moved to 10:00 by the override…
        "2026-01-27T10:00:00+00:00",
    ]
    # …and still carrying the summary it authored, not the master's.
    assert [o.summary for o in occs[1:]] == ["TF", "TF"]


def test_editing_a_thisandfuture_instance_edits_that_one():
    """WIDENED. This asserted only `.summary`, and that is exactly why the
    finding below stayed invisible: the summary is the one field the edit itself
    sets, so it is right whichever component the override was seeded from.

    2026-01-20 is a slot the RANGE=THISANDFUTURE override COVERS but does not
    ANCHOR, so `_find_override` finds nothing and the new single-slot override
    used to be built from the MASTER. The instance then snapped back to the
    master's 09:00 and lost the LOCATION the range override supplied — a
    "rename this one" that silently rescheduled the meeting an hour earlier and
    moved it to a different room.

    `.start` and `.location` are what tell the two seeds apart.
    """
    raw = apply_occurrence_override(
        _thisandfuture_series(), "2026-01-20T09:00:00+00:00",
        EventEdit(summary="just this one"),
    )
    occs = {o.recurrence_id: o for o in recur.expand_occurrences(raw, *_TF_WIN)}
    edited = occs["2026-01-20T09:00:00+00:00"]
    assert edited.summary == "just this one"
    assert edited.start == "2026-01-20T10:00:00+00:00", (
        f"editing one instance rescheduled it from the range override's 10:00 "
        f"back to the master's 09:00: {edited.start}"
    )
    assert edited.location == "Room B", (
        f"editing one instance dropped the location the range override supplied: "
        f"{edited.location!r}"
    )
    # The occurrences on either side still belong to the THISANDFUTURE override.
    assert occs["2026-01-13T09:00:00+00:00"].summary == "TF"
    assert occs["2026-01-27T09:00:00+00:00"].summary == "TF"
    assert occs["2026-01-13T09:00:00+00:00"].start == "2026-01-13T10:00:00+00:00"
    assert occs["2026-01-27T09:00:00+00:00"].start == "2026-01-27T10:00:00+00:00"
    # …and the one BEFORE the range override still belongs to the master, so a
    # repair cannot simply seed every override from the range one.
    assert occs["2026-01-06T09:00:00+00:00"].start == "2026-01-06T09:00:00+00:00"
    assert not occs["2026-01-06T09:00:00+00:00"].location


def test_editing_an_instance_before_a_range_override_seeds_from_the_master():
    """Control, and the one that makes "governing" mean something.

    2026-01-06 is BEFORE the RANGE=THISANDFUTURE override at 2026-01-13, so the
    range override does not govern it — §3.2.13 is "this and future", not "this
    and every". A repair that seeded a new single-slot override from any range
    override it could find, rather than from the one that COVERS the anchor,
    would move this instance to 10:00 and into Room B: values the user has never
    seen on this occurrence.

    Verified as an over-correction: replacing `_governing_thisandfuture` with
    "the first THISANDFUTURE override in the resource" passes every other case
    in this file and fails this one.
    """
    raw = apply_occurrence_override(
        _thisandfuture_series(), "2026-01-06T09:00:00+00:00",
        EventEdit(summary="the first one"),
    )
    occs = {o.recurrence_id: o for o in recur.expand_occurrences(raw, *_TF_WIN)}
    first = occs["2026-01-06T09:00:00+00:00"]
    assert first.summary == "the first one"
    assert first.start == "2026-01-06T09:00:00+00:00", (
        f"an instance before the range override was moved to the range "
        f"override's hour: {first.start}"
    )
    assert not first.location, (
        f"an instance before the range override inherited its location: "
        f"{first.location!r}"
    )
    # …and the range override still governs everything from its own slot on.
    assert occs["2026-01-13T09:00:00+00:00"].start == "2026-01-13T10:00:00+00:00"
    assert occs["2026-01-27T09:00:00+00:00"].summary == "TF"


def test_a_plain_override_anchors_on_its_recurrence_id_exactly():
    """The common path: a single-slot override still anchors on the slot it
    replaces, not on the time it moved to — that is what lets a second edit find
    the override instead of appending a duplicate."""
    raw = foreign_event_raw(
        "p1", "Std", rrule="FREQ=WEEKLY;COUNT=3",
        overrides=((
            "RECURRENCE-ID:20260113T090000Z",
            "DTSTART:20260114T110000Z",
            "DTEND:20260114T113000Z",
            "SUMMARY:Moved",
        ),),
    )
    occs = {o.recurrence_id: o for o in recur.expand_occurrences(raw, *_TF_WIN)}
    moved = occs["2026-01-13T09:00:00+00:00"]
    assert moved.start == "2026-01-14T11:00:00+00:00" and moved.is_override


def test_thisandfuture_on_an_all_day_series_still_gets_distinct_anchors():
    raw = foreign_event_raw(
        "tfa", "Std", dtstart="20260106", dtend="20260107", all_day=True,
        rrule="FREQ=WEEKLY;COUNT=3",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE:20260113",
            "DTSTART;VALUE=DATE:20260114",
            "DTEND;VALUE=DATE:20260115",
            "SUMMARY:TF",
        ),),
    )
    occs = recur.expand_occurrences(raw, *_TF_WIN)
    assert [(o.recurrence_id, o.start) for o in occs] == [
        ("2026-01-06", "2026-01-06"),
        ("2026-01-13", "2026-01-14"),
        ("2026-01-20", "2026-01-21"),
    ]


# ── changing the repeat reconciles the overrides it orphans ──────────────────

def _overridden_weekly() -> bytes:
    """Weekly standup with one occurrence moved to the afternoon and renamed."""
    return foreign_event_raw(
        "rc", "standup", dtstart="20260202T090000Z", dtend="20260202T093000Z",
        rrule="FREQ=WEEKLY",
        overrides=((
            "RECURRENCE-ID:20260209T090000Z",
            "DTSTART:20260209T140000Z",
            "DTEND:20260209T143000Z",
            "SUMMARY:special",
        ),),
    )


_RC_WIN = (date(2026, 2, 1), date(2026, 3, 10))


def test_changing_the_repeat_drops_the_orphaned_override():
    """Weekly -> monthly: the 2/9 override belongs to a schedule that no longer
    exists, but the expander still emitted it — a phantom event the user had no
    way to delete."""
    raw = apply_event_changes(_overridden_weekly(),
                              EventEdit(rrule=rrule_from_spec("monthly")))
    assert [(o.start, o.summary) for o in recur.expand_occurrences(raw, *_RC_WIN)] == [
        ("2026-02-02T09:00:00+00:00", "standup"),
        ("2026-03-02T09:00:00+00:00", "standup"),
    ]


def test_clearing_the_repeat_drops_every_override():
    raw = apply_event_changes(_overridden_weekly(), EventEdit(rrule=None))
    assert [(o.start, o.summary) for o in recur.expand_occurrences(raw, *_RC_WIN)] == [
        ("2026-02-02T09:00:00+00:00", "standup"),
    ]


def test_an_override_the_new_rule_still_generates_survives():
    # Weekly -> every-two-weeks, which still lands on 2/16 but not 2/9.
    raw = foreign_event_raw(
        "rc2", "standup", dtstart="20260202T090000Z", dtend="20260202T093000Z",
        rrule="FREQ=WEEKLY",
        overrides=(
            ("RECURRENCE-ID:20260209T090000Z", "DTSTART:20260209T140000Z",
             "DTEND:20260209T143000Z", "SUMMARY:orphaned"),
            ("RECURRENCE-ID:20260216T090000Z", "DTSTART:20260216T140000Z",
             "DTEND:20260216T143000Z", "SUMMARY:kept"),
        ),
    )
    edited = apply_event_changes(
        raw, EventEdit(rrule=rrule_from_spec("weekly", interval=2)))
    summaries = [o.summary for o in recur.expand_occurrences(edited, *_RC_WIN)]
    assert "kept" in summaries and "orphaned" not in summaries


def test_an_override_anchored_on_an_rdate_survives():
    # RDATE additions are part of the recurrence set independently of the rule.
    raw = foreign_event_raw(
        "rc3", "standup", dtstart="20260202T090000Z", dtend="20260202T093000Z",
        rrule="FREQ=WEEKLY", rdate="20260220T090000Z",
        overrides=(("RECURRENCE-ID:20260220T090000Z", "DTSTART:20260220T140000Z",
                    "DTEND:20260220T143000Z", "SUMMARY:on the rdate"),),
    )
    edited = apply_event_changes(raw, EventEdit(rrule=rrule_from_spec("monthly")))
    assert "on the rdate" in [o.summary
                              for o in recur.expand_occurrences(edited, *_RC_WIN)]


def test_an_unrelated_edit_never_reconciles():
    """The modal resends its whole repeat state on every save, so `edit.rrule`
    is set even on a pure rename. Reconciling then would let an unrelated edit
    drop an override a foreign client anchored at an odd slot."""
    raw = foreign_event_raw(
        "rc4", "standup", dtstart="20260202T090000Z", dtend="20260202T093000Z",
        rrule="FREQ=WEEKLY",
        # RFC-wise this RECURRENCE-ID names no generated slot, but it is a real
        # thing a foreign client wrote and invariant #2 says we do not touch it.
        overrides=(("RECURRENCE-ID:20260210T113000Z", "DTSTART:20260210T113000Z",
                    "DTEND:20260210T120000Z", "SUMMARY:odd slot"),),
    )
    renamed = apply_event_changes(
        raw, EventEdit(summary="renamed", rrule=rrule_from_spec("weekly")))
    assert b"20260210T113000Z" in renamed
    assert _master(renamed).get("SUMMARY") == "renamed"


def test_a_foreign_rule_keeps_its_overrides():
    """A rule outside our repeat vocabulary is not enumerated to test membership
    — that is the unbounded cost `_pathological_rule` refuses up front — so its
    overrides are left alone."""
    raw = foreign_event_raw(
        "rc5", "standup", dtstart="20260202T090000Z", dtend="20260202T093000Z",
        rrule="FREQ=WEEKLY;BYDAY=MO,WE",
        overrides=(("RECURRENCE-ID:20260209T090000Z", "DTSTART:20260209T140000Z",
                    "DTEND:20260209T143000Z", "SUMMARY:special"),),
    )
    # Switching to an hourly rule we could never have authored ourselves.
    edited = apply_event_changes(raw, EventEdit(rrule={"FREQ": ["HOURLY"]}))
    assert b"SUMMARY:special" in edited


def test_shifting_a_series_without_a_repeat_change_keeps_its_overrides():
    shifted = shift_series(
        _overridden_weekly(), "2026-02-02T09:00:00+00:00",
        EventEdit(dtstart=datetime(2026, 2, 3, 9, 0, tzinfo=timezone.utc),
                  rrule=rrule_from_spec("weekly")),
    )
    assert "special" in [o.summary for o in recur.expand_occurrences(shifted, *_RC_WIN)]


# ── the search budget (2026-08-19 stage 2, finding 8) ────────────────────────

@pytest.mark.parametrize("rrule, dtstart", [
    # Every one of these is SATISFIABLE and must keep expanding. A guard that
    # only forbids slowness is satisfied by a version that refuses everything,
    # so these are the half of the contract that stops the cure being worse.
    ("FREQ=WEEKLY;BYDAY=MO", "19700101T090000Z"),
    ("FREQ=MONTHLY;BYMONTHDAY=31", "19700101T090000Z"),      # skips short months
    ("FREQ=MONTHLY;BYMONTHDAY=-1", "19700101T090000Z"),      # last day of month
    ("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29", "19700101T090000Z"),  # leap day: valid
    ("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO", "19700101T090000Z"),
    ("FREQ=HOURLY", "20240101T090000Z"),                     # the density boundary
])
def test_a_satisfiable_rule_is_never_refused_by_the_search_budget(rrule, dtstart):
    """The budget prices a rule's SEARCH, and a sparse-but-real rule from an old
    DTSTART is the shape most likely to be caught by mistake.

    Measured over a 42-day grid, the most expensive legitimate rule here costs
    890 dateutil periods from a 1970 DTSTART against a 5000 budget — 5.6x
    headroom — and window width barely moves it (682 -> 733 going from 42 days
    to five years), because the cost is the DTSTART -> window skip, not the
    window. The never-matching rules that cost real time walk 95,760.
    """
    # DTEND has to travel with DTSTART. Leaving the helper's 2026 default against
    # a 1970 DTSTART makes every occurrence a 56-year-long event, so all of them
    # overlap the window and the unrelated `_occurrence_cap` fires first — which
    # would let this test pass while proving nothing about the budget.
    begin = datetime.strptime(dtstart, "%Y%m%dT%H%M%SZ")
    raw = foreign_event_raw(
        "ok", rrule=rrule, dtstart=dtstart,
        dtend=(begin + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ"),
    )
    # No exception is the assertion: a refusal raises ValueError.
    recur.expand_occurrences(raw, date(2026, 8, 1), date(2026, 9, 12))


def test_the_search_budget_actually_fires():
    """The guard wraps a PRIVATE attribute of dateutil (`_iterinfo.rebuild`), so
    a future release that renames it would turn the bound into a silent no-op
    and nothing else in the suite would notice — every test would still pass,
    just slowly, and the unauthenticated DoS would be back.

    So assert the mechanism, not just the outcome: a deliberately tiny budget
    must stop an ordinary rule that would otherwise complete easily.
    """
    from dateutil.rrule import rrulestr

    from tasksd.ical.rrule_budget import SearchBudgetExceeded, search_budget

    with pytest.raises(SearchBudgetExceeded):
        with search_budget(2):
            rrulestr("FREQ=DAILY", dtstart=datetime(1970, 1, 1, 9, 0)).between(
                datetime(2026, 8, 1), datetime(2026, 9, 12))

    # ...and outside a budget block the wrapper is inert, so importing this
    # module cannot affect any other dateutil user in the process.
    assert rrulestr("FREQ=DAILY", dtstart=datetime(2026, 1, 1, 9, 0)).between(
        datetime(2026, 8, 1), datetime(2026, 9, 12))


# ── detaching one instance from a THISANDFUTURE override ────────────────────

@pytest.mark.parametrize("label, raw, recurrence_id", [
    (
        # Mixed zones in one resource — what `_rebuild_datelist`'s own docstring
        # calls "ordinary in a shared collection". The rule's COUNT is exhausted
        # at the anchor, so re-homing falls through to the floating RDATE.
        "a floating RDATE beside a zoned master",
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:mix@x\r\nDTSTAMP:20260101T000000Z\r\n"
        b"DTSTART;TZID=Europe/Berlin:20260105T090000\r\n"
        b"DTEND;TZID=Europe/Berlin:20260105T100000\r\n"
        b"RRULE:FREQ=DAILY;COUNT=3\r\nRDATE:20260210T090000\r\nSUMMARY:S\r\n"
        b"END:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nUID:mix@x\r\nDTSTAMP:20260101T000000Z\r\n"
        b"RECURRENCE-ID;RANGE=THISANDFUTURE:20260107T090000Z\r\n"
        b"DTSTART:20260107T110000Z\r\nDTEND:20260107T120000Z\r\nSUMMARY:Moved\r\n"
        b"END:VEVENT\r\nEND:VCALENDAR\r\n",
        "2026-01-07T09:00:00+00:00",
    ),
    (
        # A DATE-valued RANGE=THISANDFUTURE override on a DATE-TIME series —
        # the shape Apple and Thunderbird write for "this and all future
        # events", which this repo explicitly supports.
        "a DATE-valued THISANDFUTURE override on a timed series",
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:dv@x\r\nDTSTAMP:20260101T000000Z\r\n"
        b"DTSTART:20260105T090000Z\r\nDTEND:20260105T100000Z\r\n"
        b"RDATE:20260107T090000Z,20260109T090000Z\r\nSUMMARY:S\r\nEND:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nUID:dv@x\r\nDTSTAMP:20260101T000000Z\r\n"
        b"RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE:20260107\r\n"
        b"DTSTART;VALUE=DATE:20260108\r\nSUMMARY:Moved\r\nEND:VEVENT\r\n"
        b"END:VCALENDAR\r\n",
        "2026-01-07",
    ),
])
def test_detaching_one_instance_survives_a_mixed_shape_date_list(label, raw, recurrence_id):
    """`_detach_thisandfuture` computes `nxt - anchor` to re-home the range
    override onto the next slot. `_next_generated` normalized only the values
    dateutil produced and appended the master's RDATEs raw, so `nxt` could come
    back floating beside a zoned anchor, or a datetime beside a DATE anchor.

    TypeError is neither ValueError nor OverflowError, so `patch_event` did not
    map it and there is no catch-all handler — it escaped as a 500, with the
    occurrence then permanently uneditable via "this event" because the bytes
    live on the server. Every other datetime site in edit.py already carried
    this tolerance; this was the one arithmetic left raw."""
    out = apply_occurrence_override(raw, recurrence_id, EventEdit(summary="edited"))
    assert b"SUMMARY:edited" in out, label


# ── an event's two ends must stay the same kind ─────────────────────────────

def _timed_event() -> bytes:
    return foreign_event_raw("span", dtstart="20260310T090000Z", dtend="20260310T100000Z")


def test_moving_one_end_cannot_silently_flip_an_event_to_all_day():
    """RFC 5545 §3.6.1: DTEND's value type MUST match DTSTART's. Nothing enforced
    it, and the PATCH model decides each end independently from the raw string —
    a bare `YYYY-MM-DD` becomes a date, anything with a `T` a datetime — with no
    `all_day` flag pairing them.

    `PATCH {"start": "2026-03-12"}` on a timed meeting therefore wrote
    `DTSTART;VALUE=DATE:20260312` beside the untouched `DTEND:20260310T100000`:
    an invalid resource every other client on the collection has to cope with,
    with DTEND two days before its own start. Worse, this app then reports
    `all_day` from DTSTART alone and `busy_intervals` skips all-day events — so
    the meeting stopped blocking anything and the anonymous booking page
    advertised its hour as free.

    The SPA sends both ends, but `smylte_update_event` takes them as independent
    optional strings, so an LLM moving a meeting to a date is enough."""
    with pytest.raises(ValueError, match="send both ends together"):
        apply_event_changes(_timed_event(), EventEdit(dtstart=date(2026, 3, 12)))
    with pytest.raises(ValueError, match="send both ends together"):
        apply_event_changes(_timed_event(), EventEdit(dtend=date(2026, 3, 12)))


def test_two_ends_of_different_kinds_are_refused_even_when_both_are_sent():
    """The same mismatch reachable through create, where `all_day=false` beside a
    bare date parses one end to a `date` and the other to a `datetime`."""
    with pytest.raises(ValueError, match="both as dates or both as times"):
        apply_event_changes(_timed_event(), EventEdit(
            dtstart=date(2026, 3, 12),
            dtend=datetime(2026, 3, 12, 10, tzinfo=timezone.utc)))


def test_an_edit_cannot_leave_an_event_ending_before_it_starts():
    """Only checked when the edit touches an end, so a resource another client
    already wrote backwards stays editable in every other respect."""
    with pytest.raises(ValueError, match="cannot end before it starts"):
        apply_event_changes(_timed_event(), EventEdit(
            dtstart=datetime(2026, 3, 10, 11, tzinfo=timezone.utc)))


@pytest.mark.parametrize("edit", [
    EventEdit(summary="Renamed"),
    EventEdit(dtstart=datetime(2026, 3, 12, 9, tzinfo=timezone.utc),
              dtend=datetime(2026, 3, 12, 10, tzinfo=timezone.utc)),
    EventEdit(dtstart=date(2026, 3, 12), dtend=date(2026, 3, 13)),
    EventEdit(dtstart=datetime(2026, 3, 10, 9, 30, tzinfo=timezone.utc)),
])
def test_the_span_guard_lets_every_ordinary_edit_through(edit):
    """A rename, a move that stays timed, a genuine switch to all-day with both
    ends sent, and a one-end move inside the existing span."""
    assert apply_event_changes(_timed_event(), edit)


def test_a_period_valued_property_never_becomes_a_python_repr_in_the_cache():
    """`_iso`'s fallback used to be `str(dt)`, and icalendar parses
    `VALUE=PERIOD` into a tuple and `VALUE=DURATION` into a timedelta — both
    writable by any client sharing the collection.

    The repr landed in `min_instant`, which the candidate query compares as a
    STRING against a window bound. `(` sorts below every digit, so it is `<=`
    every bound that will ever exist and the resource became a candidate for
    EVERY window, forever — the exact state store.py's docstring measures at 50
    rows taking a two-day booking window from ~0 s to 9.13 s, one expansion per
    candidate, under the global lock, on the unauthenticated routes.

    A value that does not name an instant now reads as absent, which every
    consumer already handles."""
    raw = foreign_event_raw("per", rrule="FREQ=WEEKLY;COUNT=2",
                            rdate="20260210T090000Z/PT2H;VALUE=PERIOD")
    # `rdate=` renders as `RDATE:<value>`, so build the parameterised form by hand.
    raw = raw.replace(b"RDATE:20260210T090000Z/PT2H;VALUE=PERIOD",
                      b"RDATE;VALUE=PERIOD:20260210T090000Z/PT2H")
    fields = extract_from_raw(raw)
    assert fields.min_instant == "2026-01-06T09:00:00+00:00", fields.min_instant
    assert not fields.min_instant.startswith("("), (
        "a Python repr in min_instant is <= every window bound there will ever be")


def test_an_unreadable_due_reads_as_absent_rather_than_as_a_repr():
    """The same fallback reached DUE, where the MCP layer parses every row's
    value to build a sort key — so one foreign VTODO made `smylte_list_tasks`
    fail for the whole account."""
    raw = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
           b"BEGIN:VTODO\r\nUID:bad@x\r\nDTSTAMP:20260101T000000Z\r\nSUMMARY:T\r\n"
           b"DUE;VALUE=PERIOD:20260101T000000Z/20260102T000000Z\r\n"
           b"END:VTODO\r\nEND:VCALENDAR\r\n")
    assert extract_from_raw(raw).due is None

    # And the MCP sort key fails soft even if a row reaches it unreadable anyway.
    from tasksd.mcp.api import _intrinsic_order
    rows = [{"due": "(datetime.datetime(2026, 1, 1, 0, 0),)", "uid": "bad",
             "summary": "T", "priority": None},
            {"due": "2026-01-05", "uid": "ok", "summary": "O", "priority": None}]
    assert [r["uid"] for r in sorted(rows, key=_intrinsic_order)] == ["ok", "bad"], (
        "an unreadable deadline must sort as no deadline, not raise")
