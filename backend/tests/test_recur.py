"""Recurrence expansion — pure unit tests (no Radicale, no `radicale` marker).

Exercises `ical.recur.expand_occurrences` across the RFC 5545 matrix (RRULE,
EXDATE, RDATE, RECURRENCE-ID overrides, all-day, DST, sub-daily caps) and the
`store.get_events_in_range` candidate-selection fix that admits a recurring
master whose own DTSTART is in the past.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import pytest
from helpers import foreign_event_raw

from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import (
    EventEdit,
    apply_occurrence_override,
    exclude_occurrence,
    recur,
    shift_series,
    split_series,
)
from tasksd.ical.read import extract_from_raw

_WIN = (date(2026, 1, 1), date(2026, 3, 1))


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

def test_subdaily_rule_is_capped_and_fast():
    raw = foreign_event_raw("min", dtend="20260106T090100Z", rrule="FREQ=MINUTELY")
    t = time.monotonic()
    occs = recur.expand_occurrences(raw, date(2026, 1, 6), date(2026, 2, 17),
                                    max_occurrences=50)
    elapsed = time.monotonic() - t
    assert len(occs) == 50
    assert elapsed < 2.0  # bounded, lazy prefix — never enumerates the full set


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
