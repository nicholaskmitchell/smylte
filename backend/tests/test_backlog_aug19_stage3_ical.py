"""Audit backlog, 2026-08-19 sweep — stage 3: silent data corruption in the
iCalendar, recurrence, sync and scheduling paths.

Eight findings from the sweep of 2026-08-19, all of them **OPEN**. Unlike
test_backlog_stage1.py … stage5.py beside this file — whose findings are closed
and whose tests are now ordinary regression tests — every test here is an
`xfail(strict=True)` pin: it asserts the behaviour the code SHOULD have and
fails against the code as it stands. CI stays green while the finding is open
and goes red the moment it is fixed, which is the signal to drop the marker and
tick the finding off. The harness is described in docs/STAGES.md.

They share the shape that makes this stage the dangerous one: nothing raises,
nothing is logged, and the answer is quietly wrong. Six of the eight are one
arithmetic mistake made in five separate places — a `timedelta` added to a
zone-aware *local* datetime, or a comparison between two datetimes that share a
`ZoneInfo` object, both of which operate on the NAIVE fields. `scheduling._u()`
exists precisely to forbid the second ("Every comparison in this module must go
through here") and `pad`/`generate_slots` carry comments explaining the first,
yet `busy_intervals` does both, and `recur._end_fields` does the first again.
Their consequence is not cosmetic: `busy_intervals` discards any interval that
is not strictly positive, so on one day a year the owner's real commitment stops
blocking, and `POST /api/public/booking/{token}` — the only unauthenticated
write path into their calendar — hands the slot to a stranger.

The other three lose data outright: a "this and following" split whose 412
recovery cannot succeed and strands an ownerless duplicate series; a "this
event" edit that rewrites every later occurrence a foreign client authored; and
a drag of a monthly series that desynchronizes the rule from its own DTSTART.

Every pin is behavioural: each drives the real function, the real sync engine or
the real HTTP route and asserts an outcome a user or an API client can see —
"the meeting still blocks its slot", "the calendar holds one event, not two",
"the series still has ten occurrences". None reads source text, and none names
the repair: several findings have two defensible fixes (apply the shift, or
refuse it; complete the split, or roll it back), so each pin asserts the
invariant both fixes preserve rather than the one its author imagined.

Reproduced by hand first — against the pinned icalendar/dateutil and, for the
sync and HTTP pins, the scratch Radicale on :5233 — so the evidence in the
docstrings is observed, not inferred. Run just this file with
`pytest tests/test_backlog_aug19_stage3_ical.py -rxX`.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tasksd import scheduling
from tasksd.dav.errors import DavError
from tasksd.ical import EventEdit
from tasksd.ical.edit import apply_occurrence_override, shift_series, split_series
from tasksd.ical.recur import expand_occurrences
from tests.helpers import foreign_event_raw

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

UTC = timezone.utc
# America/Chicago because both transitions land on a weekend at 02:00 local and
# the offsets (-06:00 / -05:00) are unambiguous in a failure message. 2026-03-08
# springs forward, 2026-11-01 falls back.
CHICAGO = ZoneInfo("America/Chicago")

# A VTIMEZONE a foreign client would ship for that zone, so the recurrence pins
# resolve TZID from the resource itself rather than from whatever the host's
# tzdata happens to hold.
CHICAGO_VTIMEZONE = (
    "BEGIN:VTIMEZONE",
    "TZID:America/Chicago",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:-0600", "TZOFFSETTO:-0500", "TZNAME:CDT",
    "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:-0500", "TZOFFSETTO:-0600", "TZNAME:CST",
    "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
)


def _span(iv: scheduling.Interval) -> timedelta:
    """An interval's length in ABSOLUTE time — the only length a booking has."""
    return iv.end.astimezone(UTC) - iv.start.astimezone(UTC)


@pytest.fixture
def event_collection(dav):
    """A throwaway VEVENT collection on scratch Radicale, removed afterwards."""
    ci = dav.create_task_collection(
        f"aug19-s3-{uuid.uuid4().hex[:8]}", components=("VEVENT",))
    yield ci
    try:
        dav.delete_collection(ci.href)
    except Exception:  # noqa: BLE001 — cleanup must not mask the finding
        pass


@pytest.fixture
def calendar(client):
    """A throwaway calendar created through the owner's own API, removed after."""
    cid = client.post(
        "/api/calendars", json={"name": f"aug19-s3-{uuid.uuid4().hex[:8]}"}
    ).json()["id"]
    yield cid
    client.delete(f"/api/calendars/{cid}")


# ── AUDIT: busy_intervals drops any event crossing the DST fall-back ────────

def test_a_meeting_across_the_fall_back_transition_still_blocks_its_slot():
    """The owner has a 30-minute commitment at 06:30Z-07:00Z on 2026-11-01. In
    America/Chicago that is 01:30 CDT -> 01:00 CST: it starts in the first pass
    of the repeated hour and ends in the second, so its end WALL CLOCK precedes
    its start.

    `busy_intervals`' sanity guard `if end > start` (scheduling.py:148) is the
    one comparison in the module that was never routed through `_u()`, whose own
    docstring says "Every comparison in this module must go through here" —
    because `tz` is built once per link, both operands come from
    `parse_event_time(...).astimezone(tz)`, and CPython compares two datetimes
    sharing one ZoneInfo on their naive fields. So the guard silently discards
    the event: it never reaches `merge`, the busy set has no trace of it,
    `generate_slots` offers the slot sitting on top of it, and `book_slot`
    re-validates against that same empty busy set and writes the VEVENT.

    Observed against the real module: `busy_intervals` returns `[]` for this
    event, and `generate_slots` then offers 2026-11-01T01:30-05:00 — the same
    instant, to the byte, as the meeting already on the calendar. Any crossing
    event no longer than the repeated hour is affected, this app's OWN bookings
    included: a 30-minute booking of the 01:30 CDT slot is exactly 06:30Z-07:00Z.
    That matters because `POST /api/public/booking/{token}` is the only
    unauthenticated write path into the owner's calendar, and `generate_slots`
    deliberately offers both passes of the repeated hour, so those slots are
    real and reachable by a stranger.

    **Fixed** by routing the guard through `_u`, which is all it ever needed —
    the module's own docstring had already written the rule down. The wider
    lesson is in docs/STAGES.md: a comment asserting a safety property is
    evidence of intent, not of behaviour, and this is the fifth finding of that
    shape in one sweep.
    """
    meeting = {"start": "2026-11-01T06:30:00+00:00", "end": "2026-11-01T07:00:00+00:00"}

    busy = scheduling.busy_intervals([meeting], CHICAGO)
    assert busy, (
        "a 30-minute meeting spanning the fall-back transition produced an EMPTY "
        "busy set — the owner's calendar entry blocks nothing at all on 2026-11-01"
    )
    assert _span(busy[0]) == timedelta(minutes=30), (
        f"the meeting blocks {_span(busy[0])} of absolute time, not the 30 minutes "
        f"it actually occupies: {busy[0]}"
    )

    # …and the consequence a visitor sees: the slot must not be on offer.
    slots = scheduling.generate_slots(
        availability=scheduling.parse_availability({"6": ["00:00-05:00"]}),
        duration_minutes=30, busy=busy, buffer_minutes=0, tz=CHICAGO,
        now=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        min_notice_hours=0, horizon_days=1,
    )
    offered = {s.start.astimezone(UTC) for s in slots}
    taken = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert taken not in offered, (
        "the public booking page offers 2026-11-01T01:30:00-05:00 as free while "
        "the owner is already in a meeting at that exact instant — an anonymous "
        "POST double-books them"
    )


# ── AUDIT: a DURATION-only event's end is derived by wall-clock addition ────

def test_a_duration_only_event_blocks_its_authored_length_across_a_transition():
    """`end = start + vDuration.from_ical(ev["duration"])` (scheduling.py:145)
    adds a timedelta to a zone-aware LOCAL datetime, which adds to the naive
    fields and re-derives the offset — the exact wall-clock arithmetic that
    `generate_slots` (line 264) and `pad` (line 186) both carry comments
    explaining they must avoid.

    DURATION-only VEVENTs are ordinary foreign-client output (DAVx5, phone
    clients); `get_events_in_range` was specially fixed to admit them precisely
    because "the row feeds the booking conflict check".

    Observed, tz=America/Chicago:

      * spring-forward, 07:30Z + PT2H blocked 07:30Z->08:30Z instead of
        07:30Z->09:30Z. The last hour of a real two-hour commitment is missing
        from the busy set, so the public page offers it and an anonymous POST
        writes a VEVENT on top of it.
      * fall-back, 06:30Z + PT30M blocked 06:30Z->08:00Z — 90 minutes instead of
        30, quietly withholding an hour of genuine availability.

    PT2H and PT30M are exact-time durations, so both directions are wrong under
    any reading: what is asked for here is that a busy interval last as long as
    the event that produced it.

    **Fixed** by `ical.read.advance`, which applies the two halves of a DURATION
    the way RFC 5545 §3.3.6 defines them instead of picking one — weeks and days
    nominal, hours/minutes/seconds exact. The obvious repair (add the whole
    timedelta to the instant) fixes PT2H and breaks P1D, so the nominal cases
    below are as load-bearing as the exact ones: `vDuration.from_ical` collapses
    P1D and PT24H to the same `timedelta`, and only the raw string can tell them
    apart.
    """
    cases = (
        ("spring-forward", {"start": "2026-03-08T07:30:00+00:00", "duration": "PT2H"},
         timedelta(hours=2)),
        ("fall-back", {"start": "2026-11-01T06:30:00+00:00", "duration": "PT30M"},
         timedelta(minutes=30)),
        # An ordinary July day, so a fix cannot pass by changing every span.
        ("no transition", {"start": "2026-07-13T14:00:00+00:00", "duration": "PT1H"},
         timedelta(hours=1)),
        # PT24H is EXACT: twenty-four hours of real time, transition or not.
        ("exact day, spring", {"start": "2026-03-08T07:30:00+00:00", "duration": "PT24H"},
         timedelta(hours=24)),
        # …and P1D is NOMINAL — "the same time tomorrow", which across the
        # spring-forward is 23 real hours. This is the half a fix that simply
        # added the whole duration to the instant would get wrong, trading one
        # wrong answer for another. RFC 5545 §3.3.6.
        ("nominal day, spring", {"start": "2026-03-08T07:30:00+00:00", "duration": "P1D"},
         timedelta(hours=23)),
        ("nominal day, fall", {"start": "2026-11-01T05:30:00+00:00", "duration": "P1D"},
         timedelta(hours=25)),
    )
    wrong = []
    for label, ev, authored in cases:
        busy = scheduling.busy_intervals([ev], CHICAGO)
        assert len(busy) == 1, f"{label}: expected one busy interval, got {busy}"
        got = _span(busy[0])
        if got != authored:
            wrong.append(
                f"{label}: DURATION {ev['duration']} blocked {got} of absolute time "
                f"({busy[0].start.astimezone(UTC)} -> {busy[0].end.astimezone(UTC)}), "
                f"not {authored}"
            )
    assert not wrong, (
        "a DURATION-only event does not block the time it occupies across a DST "
        "transition:\n  " + "\n  ".join(wrong)
    )


# ── AUDIT: split_event's 412 recovery strands a duplicate series ────────────

@pytest.mark.radicale
def test_a_contended_this_and_following_split_leaves_no_duplicate_series(
    engine, dav, event_collection
):
    """"This and following" writes the tail to a brand-new href FIRST, then
    truncates the head with If-Match. On the 412 the docstring calls expected
    ("a 412 re-derives both from the fresh copy (invariant #5)") the recovery
    re-derives head and tail from the fresh body and overwrites the tail it
    already wrote — but `ical.split_series` mints a fresh `uuid4().hex@tasksd`
    UID for the tail on every call, so the replacement carries a DIFFERENT UID
    than the resource sitting at `tail_href`. Radicale refuses exactly that with
    409 `no-uid-conflict`, which is `Conflict`, not `PreconditionFailed`, so it
    escapes the whole handler: the head is never truncated, the tail is never
    cleaned up (the only cleanup lives inside the inner `except
    PreconditionFailed`), and app.py's `DavError` catch-all tells the user
    "calendar server unavailable, try again shortly".

    The trigger is what `move_event`'s own docstring calls normal, not rare:
    "the cache lags Radicale by up to one poll, and it is normal for another
    CalDAV client to edit an event inside that window".

    Observed against scratch Radicale: `split_event` raised `Conflict 409 PUT
    …ae7e2575….ics`, the original was left untouched at ten occurrences and
    still named "Standup", and an eight-occurrence "Renamed" duplicate was left
    on the wire that nothing in the app had created a cache row for — so it is
    ownerless, renders as eight phantom events beside the originals after the
    next poll, and counts as busy time on the public booking page. Retrying
    inside the poll window strands another one, since the cached etag is still
    the stale one.

    The assertion is deliberately fix-agnostic. A ten-occurrence series that has
    been split "this and following" must still be ten occurrences: two in the
    head plus eight in the tail if the split completed, or ten in the untouched
    original if it was refused and rolled back. Only the stranded-duplicate
    outcome — the head still whole AND a tail beside it — can exceed ten.
    
    **Fixed** two ways, because the finding is two failures wearing one symptom.
    The rebuilt tail now re-stamps the UID the first build minted, so replacing
    our own just-written resource is an ordinary overwrite rather than a
    `no-uid-conflict` 409. And the cleanup moved from the inner
    `except PreconditionFailed` — which covered exactly one of the ways this can
    fail — to a `try/except BaseException` around the whole recovery, so a
    concurrent delete of the master (`dav.get` raising NotFound), a transport
    error, or a rebuild that now refuses the anchor all delete the tail instead
    of stranding a headless duplicate series under a UID nothing references.
    """
    col = event_collection.href
    uid = "series@x"
    href = f"{col}{uuid.uuid4().hex}.ics"

    def series(*extra: str) -> bytes:
        return foreign_event_raw(
            uid, "Standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
            rrule="FREQ=WEEKLY;COUNT=10", extra=extra,
        )

    engine.discover()
    engine.sync(col)
    etag0 = dav.put(href, series(), if_none_match="*")
    engine.sync(col)                       # the cache now holds etag0

    # A foreign CalDAV client edits the same resource inside the poll window.
    dav.put(href, series("LOCATION:Room 4"), if_match=etag0)

    try:
        engine.split_event(col, uid, "2026-01-20T09:00:00+00:00",
                           EventEdit(summary="Renamed"))
    except (DavError, ValueError):
        pass                # a clean refusal is a correct outcome; a duplicate is not

    # Radicale reports a getetag for the collection itself; only the item
    # resources under it are the series.
    on_wire = sorted(h for h in dav.list_etags(col) if h.rstrip("/") != col.rstrip("/"))
    per_resource = {
        h: len(expand_occurrences(dav.get(h).data, date(2026, 1, 1), date(2027, 1, 1)))
        for h in on_wire
    }
    assert sum(per_resource.values()) == 10, (
        "the ten-occurrence series is now "
        f"{sum(per_resource.values())} occurrences across {len(on_wire)} resources "
        f"({per_resource}): the head was never truncated and the tail written "
        "before it was left behind, so the calendar carries a duplicate series "
        "no cache row owns"
    )


# ── AUDIT: "this event" on a THISANDFUTURE override's own slot ──────────────

def test_editing_the_slot_a_this_and_future_override_anchors_leaves_later_ones_alone():
    """`_find_override` matches purely on the RECURRENCE-ID *instant* and never
    looks at `rid.params`. For an Apple/Thunderbird
    `RECURRENCE-ID;RANGE=THISANDFUTURE` component (RFC 5545 §3.2.13) that
    component carries the values for its own slot AND every later occurrence, so
    "this event" on the override's own anchor mutates the shared component in
    place and silently rewrites all subsequent occurrences.

    This is the third of three sibling paths and the only one still missing the
    guard: `exclude_occurrence` excludes `_is_thisandfuture` from its drop
    predicate (edit.py:667) and `split_series` folds a governing TF override
    into the tail (edit.py:1109), both fixed by earlier audits.
    `_is_thisandfuture` exists in the file and is never consulted here.

    The existing coverage looks like it covers this and does not:
    `test_editing_a_thisandfuture_instance_edits_that_one` edits
    2026-01-20T09:00:00+00:00, a slot the override *covers* but does not
    *anchor*, so `_find_override` misses and a fresh single-slot override is
    created — the correct branch. Nothing edits 2026-01-13, the anchor itself.

    Observed: expanding the edited resource, all three of Jan 13, Jan 20 and
    Jan 27 come back reading "just this one" in Room C. The user clicked one
    chip and renamed three; a drag of that chip moves all three. The foreign
    client's authored values are gone from the bytes PUT to Radicale, so the
    loss is permanent. Reachable in one click: `recur._occurrence` gives the
    first covered instance the override's own RECURRENCE-ID, and
    CalendarView.tsx:839 sends `{recurrence_id, scope: 'this'}` for that chip.
    """
    raw = foreign_event_raw(
        "tf@x", "Standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=WEEKLY;COUNT=4",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
            "DTSTART:20260113T100000Z", "DTEND:20260113T103000Z",
            "SUMMARY:TF", "LOCATION:Room B"),),
    )
    window = (date(2026, 1, 1), date(2026, 2, 10))
    before = {o.recurrence_id: o for o in expand_occurrences(raw, *window)}
    later = ["2026-01-20T09:00:00+00:00", "2026-01-27T09:00:00+00:00"]
    assert all(before[k].summary == "TF" for k in later), before   # sanity

    edited = apply_occurrence_override(
        raw, "2026-01-13T09:00:00+00:00",
        EventEdit(summary="just this one", location="Room C"))

    after = {o.recurrence_id: o for o in expand_occurrences(edited, *window)}
    damaged = [
        f"{k}: {before[k].summary!r}/{before[k].location!r} at {before[k].start} "
        f"became {after[k].summary!r}/{after[k].location!r} at {after[k].start}"
        for k in later
        if (after[k].summary, after[k].location, after[k].start)
        != (before[k].summary, before[k].location, before[k].start)
    ]
    assert not damaged, (
        "editing ONE occurrence rewrote the later ones the THISANDFUTURE "
        "override governs:\n  " + "\n  ".join(damaged)
    )

    # The edited instance keeps the time the RANGE override gave it (10:00), not
    # the master's 09:00. This is the half the first attempt at the fix got
    # wrong: `_new_override` places DTSTART at the rule's slot, so detaching an
    # instance silently rescheduled it back an hour — a different corruption in
    # place of the one being fixed.
    detached = after["2026-01-13T09:00:00+00:00"]
    assert detached.summary == "just this one" and detached.location == "Room C"
    assert detached.start == "2026-01-13T10:00:00+00:00", (
        f"the edited occurrence moved to {detached.start}: detaching it from the "
        f"range override snapped it back to the master's hour"
    )

    # And every RECURRENCE-ID value appears exactly once. Two components claiming
    # one instance is unorderable for any reader, and the FIRST attempt at this
    # fix did precisely that — added a plain override beside the range one — at
    # which point the expansion still applied the range one to every later slot
    # and the failure looked identical to the original bug.
    rids = [ln.split(":", 1)[1] for ln in edited.decode().splitlines()
            if ln.startswith("RECURRENCE-ID")]
    assert len(rids) == len(set(rids)), f"duplicate RECURRENCE-ID values: {rids}"


def test_detaching_the_last_occurrence_of_a_range_override_does_not_strand_it():
    """The edge the re-homing has to handle: when the range override anchors the
    FINAL occurrence there is nothing after it to govern, so it must be dropped
    rather than moved to a slot the series does not generate."""
    raw = foreign_event_raw(
        "tf2@x", "Standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=WEEKLY;COUNT=2",
        overrides=((
            "RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
            "DTSTART:20260113T100000Z", "DTEND:20260113T103000Z",
            "SUMMARY:TF", "LOCATION:Room B"),),
    )
    edited = apply_occurrence_override(
        raw, "2026-01-13T09:00:00+00:00", EventEdit(summary="last one"))
    occurrences = expand_occurrences(edited, date(2026, 1, 1), date(2026, 3, 1))

    assert len(occurrences) == 2, (
        f"the series gained or lost an occurrence: "
        f"{[(o.recurrence_id, o.start) for o in occurrences]}")
    assert occurrences[-1].summary == "last one"
    assert occurrences[-1].start == "2026-01-13T10:00:00+00:00"
    rids = [ln.split(":", 1)[1] for ln in edited.decode().splitlines()
            if ln.startswith("RECURRENCE-ID")]
    assert len(rids) == len(set(rids)), f"duplicate RECURRENCE-ID values: {rids}"


# ── AUDIT: dragging a foreign MONTHLY series desynchronizes its rule ────────

def test_dragging_a_monthly_series_moves_it_instead_of_desynchronizing_the_rule():
    """`_shift_rrule` rotates only `BYDAY` on a `WEEKLY` rule; its docstring
    dismisses the rest as "left untouched". Untouched is not a no-op:
    `shift_series` moves DTSTART by `delta` while `BYMONTHDAY` / ordinal `BYDAY`
    keep naming the OLD day, so the new DTSTART no longer satisfies the rule.
    The occurrence the user dragged detaches from the series, every other
    occurrence stays exactly where it was, and a phantom one appears at the far
    end because COUNT is now consumed from a later start.

    `FREQ=MONTHLY;BYMONTHDAY=n` and `FREQ=MONTHLY;BYDAY=1TU` are what DAVx5,
    Tasks.org, jtx Board, Thunderbird and Apple all write for a monthly repeat,
    so this is the ordinary shape of a foreign monthly series. Reachable in one
    gesture: CalendarView.tsx:836 sends the changed times plus `recurrence_id`
    with scope 'all', and service.py:602 routes that to `shift_series`. The
    write goes to Radicale, so the loss is permanent, and the SPA shows the drag
    as successful until the next sync.

    Observed, dragging the 2026-01-06 chip of `FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4`
    to Jan 7 and choosing "All events": Jan 6/Feb 6/Mar 6/Apr 6 became
    Jan 7/Feb 6/Mar 6/Apr 6/**May 6** — five occurrences instead of four, only
    the dragged one moved, and a May the user never asked for. The ordinal form
    `FREQ=MONTHLY;BYDAY=1TU;COUNT=4` behaves the same way (…/May 5 appears).

    Both defensible fixes satisfy this pin: shifting the day-selecting BY* parts
    alongside DTSTART, or refusing the reschedule with a ValueError the way the
    all-day/timed switch is already refused (the route answers 422). What is not
    acceptable is a schedule that silently gains an occurrence.
    """
    window = (date(2026, 1, 1), date(2026, 7, 1))

    def drag_by_one_day(rrule: str):
        """Returns the occurrence dates after the drag, or None if it was refused."""
        raw = foreign_event_raw(
            "m@x", "Monthly", dtstart="20260106T090000Z", dtend="20260106T093000Z",
            rrule=rrule)
        before = [datetime.fromisoformat(o.start).date()
                  for o in expand_occurrences(raw, *window)]
        try:
            out = shift_series(
                raw, "2026-01-06T09:00:00+00:00",
                EventEdit(dtstart=datetime.fromisoformat("2026-01-07T09:00:00+00:00"),
                          dtend=datetime.fromisoformat("2026-01-07T09:30:00+00:00")))
        except ValueError:
            return before, None          # a clean refusal is a correct outcome
        return before, [datetime.fromisoformat(o.start).date()
                        for o in expand_occurrences(out, *window)]

    broken = []
    for rrule in ("FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4", "FREQ=MONTHLY;BYDAY=1TU;COUNT=4"):
        before, after = drag_by_one_day(rrule)
        if after is None:
            continue
        if len(after) != len(before):
            broken.append(f"{rrule}: {len(before)} occurrences {before} became "
                          f"{len(after)} {after}")
        elif date(2026, 1, 7) not in after:
            broken.append(f"{rrule}: the dragged occurrence is not on 2026-01-07: {after}")
        elif before[1] in after:
            broken.append(f"{rrule}: {before[1]} did not move with the series: {after}")
    assert not broken, (
        "dragging one occurrence of a monthly series with 'All events' neither "
        "moved the series nor refused the change:\n  " + "\n  ".join(broken)
    )


@pytest.mark.parametrize("rrule, new_start, expected", [
    # A time-only drag desynchronizes nothing, whatever the rule pins.
    ("FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4", "2026-01-06T11:00:00+00:00",
     [date(2026, 1, 6), date(2026, 2, 6), date(2026, 3, 6), date(2026, 4, 6)]),
    # The one BY* rotation that IS handled must keep working.
    ("FREQ=WEEKLY;BYDAY=TU;COUNT=4", "2026-01-07T09:00:00+00:00",
     [date(2026, 1, 7), date(2026, 1, 14), date(2026, 1, 21), date(2026, 1, 28)]),
    ("FREQ=WEEKLY;COUNT=4", "2026-01-07T09:00:00+00:00",
     [date(2026, 1, 7), date(2026, 1, 14), date(2026, 1, 21), date(2026, 1, 28)]),
    ("FREQ=DAILY;COUNT=4", "2026-01-07T09:00:00+00:00",
     [date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 10)]),
])
def test_a_series_that_can_be_moved_is_still_moved(rrule, new_start, expected):
    """The control, and it is not optional. A refusal satisfies the pin above,
    so a fix that refused EVERY "all events" reschedule would pass it while
    breaking the ordinary gesture — the same trap the search-budget pins in
    stage 2 needed controls for. These four must still move."""
    raw = foreign_event_raw(
        "ok@x", "Series", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule=rrule)
    out = shift_series(
        raw, "2026-01-06T09:00:00+00:00",
        EventEdit(dtstart=datetime.fromisoformat(new_start),
                  dtend=datetime.fromisoformat(new_start) + timedelta(minutes=30)))
    got = [datetime.fromisoformat(o.start).date()
           for o in expand_occurrences(out, date(2026, 1, 1), date(2026, 7, 1))]
    assert got == expected, f"{rrule} dragged to {new_start} produced {got}"


# ── AUDIT: split_series never checks the anchor is an occurrence ────────────

@pytest.mark.radicale
def test_this_and_following_on_a_non_repeating_event_does_not_duplicate_it(
    client, calendar
):
    """`split_series` derives the head purely from `_rrule_dict(hmaster)`: with
    no RRULE the head is returned completely unbounded, and a tail is minted
    anyway with a fresh UID at the anchor. Nothing on the path verifies that the
    resource recurs or that `recurrence_id` names a slot the rule generates —
    not mcp/api.py:435, not app.py's `_check_scope`/`_check_recurrence_id`
    (which check the anchor is *parseable*, not that it *exists*), not
    service.py:600, not `engine.split_event`.

    So a "this and following" edit of a one-off event PUTs the original back
    untouched AND creates a second resource with a new UID at the anchor. The
    single event is now on the calendar twice, in two collection rows, under two
    UIDs — and because the tail carries the original's ATTENDEE/ORGANIZER, it is
    a second invitation. The delete variant is the mirror image: `delete_tail`
    leaves a non-None head, so `write_head` PUTs the unchanged resource, the API
    answers 204, and the SPA optimistically removes a row that is still there.

    Observed through the real HTTP route: creating "Lunch" on 2026-01-06 and
    PATCHing it with `{"scope": "thisandfuture", "recurrence_id":
    "2026-05-01T10:00:00"}` answered 200 and left TWO events in the calendar —
    the untouched original and a "Lunch v2" on 2026-05-01 under
    `…@tasksd`. Driven end-to-end rather than against `split_series` directly
    because the check belongs at whichever layer its author chooses; the pin
    asks only that one event stay one event.

    The same missing check turns a stale anchor on a genuinely recurring series
    into schedule corruption — two tabs, or `engine.split_event`'s 412 path
    re-applying a stale `recurrence_id` against the fresh copy — by bounding the
    head at an instant that was never an occurrence and restarting the tail's
    rule there.

    **Fixed** by `edit._require_occurrence`, called before the head is derived:
    a master carrying neither RRULE nor RDATE raises "this event does not
    repeat", and an anchor no rule generates raises "recurrence_id does not name
    an occurrence". An RDATE-only resource is a real series, so the test is "does
    anything generate this anchor", not "is there an RRULE"; the membership probe
    reuses the stage-2 cost guard, and an unprobeable rule is ALLOWED, since
    refusing an edit is the outcome that costs the user something.

    The DELETE route needed the same `except ValueError -> 422` its PATCH sibling
    already had, or the new refusal escaped as a 500.
    """
    created = client.post(f"/api/calendars/{calendar}/events", json={
        "summary": "Lunch", "start": "2026-01-06T09:00:00", "end": "2026-01-06T09:30:00",
    })
    assert created.status_code == 201, created.text
    uid = created.json()["uid"]

    # "This and following" from an instant that is not an occurrence of anything:
    # the event does not repeat at all.
    client.patch(f"/api/calendars/{calendar}/events/{uid}", json={
        "summary": "Lunch v2", "scope": "thisandfuture",
        "recurrence_id": "2026-05-01T10:00:00",
    })

    events = client.get(f"/api/calendars/{calendar}/events",
                        params={"start": "2026-01-01", "end": "2026-12-31"}).json()
    assert len(events) == 1, (
        "a single non-repeating event was duplicated by a 'this and following' "
        "edit — the calendar now holds "
        f"{[(e['uid'], e['summary'], e['start']) for e in events]}"
    )
    assert events[0]["summary"] == "Lunch", (
        "the refused edit was partly applied to the original")

    # The DELETE mirror: it answered 204 while deleting nothing, and the SPA
    # removes the row optimistically — so the user watched it disappear and found
    # it again on the next sync.
    deleted = client.request(
        "DELETE", f"/api/calendars/{calendar}/events/{uid}",
        params={"scope": "thisandfuture", "recurrence_id": "2026-05-01T10:00:00"})
    assert deleted.status_code == 422, (
        f"deleting 'this and following' from an instant that is not an occurrence "
        f"answered {deleted.status_code}; it deletes nothing, so it must not "
        f"report success")
    still = client.get(f"/api/calendars/{calendar}/events",
                       params={"start": "2026-01-01", "end": "2026-12-31"}).json()
    assert len(still) == 1, "the event should still be there"


@pytest.mark.parametrize("recurrence_id, ok", [
    ("2026-01-20T09:00:00+00:00", True),    # a real occurrence
    ("2026-01-06T09:00:00+00:00", True),    # the series' own first slot
    ("2026-01-21T09:00:00+00:00", False),   # one day off
    ("2026-01-20T10:00:00+00:00", False),   # one hour off
])
def test_a_split_anchor_must_name_an_occurrence_of_the_series(recurrence_id, ok):
    """The half the end-to-end pin above cannot reach, and the one with teeth on
    a REAL series: an anchor that is off by a day or an hour bounded the head at
    an instant the rule never generated and restarted the tail there, moving
    every later occurrence. Two tabs produce it, and so does `engine.split_event`
    re-applying a stale `recurrence_id` against a fresh copy after a 412.

    The `True` rows are the control: a check that refused every split would
    satisfy the duplication pin while breaking the feature outright.
    """
    raw = foreign_event_raw(
        "s@x", "Weekly", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=WEEKLY;COUNT=4")
    if ok:
        head, tail = split_series(raw, recurrence_id, EventEdit(summary="v2"))
        assert b"SUMMARY:v2" in tail
    else:
        with pytest.raises(ValueError, match="does not name an occurrence"):
            split_series(raw, recurrence_id, EventEdit(summary="v2"))


# ── AUDIT: expansion emits occurrences whose end precedes their start ───────

def test_every_expanded_occurrence_across_spring_forward_blocks_real_time():
    """`recurring_ical_events` derives each instance's end by wall-clock
    arithmetic on that instance's DTSTART, and `_end_fields` does the same for
    the DURATION path (`_iso(dtstart.dt + dur.dt)` — `aware + timedelta`
    operates on the naive fields and re-derives the offset). `expand_occurrences`
    accepts whatever comes back without checking that `end > start`.

    When a recurring event's local start falls inside the hour the clock skips,
    PEP 495 resolves the start with the pre-transition offset and the end with
    the post-transition one, so the emitted occurrence runs BACKWARDS.

    Observed for a daily 02:30 America/Chicago series with DURATION:PT30M
    expanded over 2026-03-01..2026-03-20 (the DTEND-authored variant produces
    the identical row, so this is not specific to DURATION):

        2026-03-07T02:30:00-06:00 -> 2026-03-07T03:00:00-06:00     30 min
        2026-03-08T02:30:00-06:00 -> 2026-03-08T03:00:00-05:00     start 08:30Z,
                                                                   END 08:00Z
        2026-03-09T02:30:00-05:00 -> 2026-03-09T03:00:00-05:00     30 min

    The consequence is not cosmetic. `scheduling.busy_intervals` discards any
    interval that is not strictly positive, so `busy_intervals([that row])`
    returns `[]`: on that one day the owner's recurring 02:30-03:00 commitment —
    a nightly maintenance window, an overseas call — stops blocking bookings
    entirely and the public page hands the time to an anonymous visitor. The SPA
    renders the same row as "3:30 AM - 3:00 AM". The mirror case on 2026-11-01
    stretches a 30-minute instance to 90 and withholds an hour of real
    availability.

    Nothing in tests/test_recur.py asserts an occurrence *end* across a
    transition: `test_dst_transition_keeps_local_wall_time` and
    `test_shift_series_dst_wall_clock_preserved` both assert only `.start`.
    """
    raw = foreign_event_raw(
        "dst@x", "Nightly", dtstart="TZID=America/Chicago:20260306T023000",
        dtend=None, rrule="FREQ=DAILY;COUNT=8",
        vtimezone=CHICAGO_VTIMEZONE, extra=("DURATION:PT30M",),
    )
    occurrences = expand_occurrences(raw, date(2026, 3, 1), date(2026, 3, 20))
    assert len(occurrences) == 8, occurrences        # sanity: the series expanded

    # Every instance must occupy the thirty minutes it was authored with — not
    # merely be forward-going. A guard that only clamped a backwards end to its
    # start would satisfy the two assertions below while still emitting a
    # zero-length instance here, and zero-length blocks nothing either.
    spans = {
        f"{o.start} -> {o.end}": (
            datetime.fromisoformat(o.end).astimezone(UTC)
            - datetime.fromisoformat(o.start).astimezone(UTC)
        )
        for o in occurrences
    }
    assert set(spans.values()) == {timedelta(minutes=30)}, (
        "instances do not all occupy their authored 30 minutes of real time: "
        + str({k: str(v) for k, v in spans.items() if v != timedelta(minutes=30)})
    )

    backwards = [
        f"{o.start} -> {o.end}"
        for o in occurrences
        if datetime.fromisoformat(o.end) <= datetime.fromisoformat(o.start)
    ]
    assert not backwards, (
        "expansion emitted occurrences whose end is at or before their start, "
        "which busy_intervals then discards entirely:\n  " + "\n  ".join(backwards)
    )

    # The reason it matters, asserted rather than argued: every occurrence of a
    # real commitment has to block time on the booking page.
    unblocked = [
        f"{o.start} -> {o.end}"
        for o in occurrences
        if not scheduling.busy_intervals([{"start": o.start, "end": o.end}], CHICAGO)
    ]
    assert not unblocked, (
        "these occurrences of the owner's recurring commitment block nothing at "
        "all, so the public booking page offers them as free:\n  "
        + "\n  ".join(unblocked)
    )


@pytest.mark.parametrize("tail", [
    ("DURATION:PT30M",),
    # The library derives the end the same wrong way whether the master authored
    # DURATION or DTEND, so both spellings have to be driven — a fix applied only
    # to `_end_fields` would leave this one broken.
    ("DTEND;TZID=America/Chicago:20261025T020000",),
])
def test_the_fall_back_mirror_does_not_stretch_an_instance_to_three_times_its_length(tail):
    """The other direction of the same defect, and the one the pin above cannot
    see: on 2026-11-01 a 30-minute 01:30 instance is emitted as
    01:30-05:00 -> 02:00-06:00, which is 90 minutes of real time. It is forward-
    going, so `busy_intervals` accepts it and nothing looks wrong — it simply
    withholds an hour of the owner's genuine availability from the public page,
    every year, on one day.

    Note what a correct answer looks like locally: 01:30 CDT + 30 real minutes is
    01:00 CST, so the instance reads "1:30 AM - 1:00 AM". That is the repeated
    hour, and it is the same shape this app's own 01:30 bookings already have
    (06:30Z -> 07:00Z), which is why `busy_intervals` must compare instants.
    """
    raw = foreign_event_raw(
        "fall@x", "Nightly", dtstart="TZID=America/Chicago:20261025T013000",
        dtend=None, rrule="FREQ=DAILY;COUNT=10",
        vtimezone=CHICAGO_VTIMEZONE, extra=tail,
    )
    occurrences = expand_occurrences(raw, date(2026, 10, 25), date(2026, 11, 10))
    wrong = {
        f"{o.start} -> {o.end}": str(
            datetime.fromisoformat(o.end).astimezone(UTC)
            - datetime.fromisoformat(o.start).astimezone(UTC)
        )
        for o in occurrences
        if (datetime.fromisoformat(o.end).astimezone(UTC)
            - datetime.fromisoformat(o.start).astimezone(UTC)) != timedelta(minutes=30)
    }
    assert not wrong, (
        "an instance spanning the fall-back transition blocks more time than it "
        f"occupies, withholding real availability: {wrong}"
    )


# ── AUDIT: an offset-bearing datetime is written as TZID="UTC±HH:MM" ────────

@pytest.mark.radicale
def test_an_event_created_with_a_zone_offset_keeps_the_instant_it_names(
    client, calendar
):
    """`_parse_datelike` (app.py:531) returns `datetime.fromisoformat(...)`
    verbatim, so `2026-08-10T09:00:00-07:00` becomes a datetime whose tzinfo is
    a bare fixed-offset `datetime.timezone`. Nothing at the HTTP edge, in
    `service.create_event` or in `ical.build_new_event` normalizes it:
    `event.add("DTSTART", dtstart)` receives it raw, and `icalendar` serializes a
    fixed offset as a fabricated `TZID="UTC-07:00"` — a zone name no CalDAV
    client, and not even this app's own reader, can resolve. The value comes back
    FLOATING, and the instant shifts by the whole offset.

    The seam is that `ical/edit.py::_set_datelike` documents this exact trap
    ("Writing that offset verbatim makes icalendar fabricate
    `TZID="UTC+02:00"`") and defends against it only when the property being
    overwritten is ALREADY zone-aware. On a create there is no old value at all,
    so the guard never fires, and the comment makes the other cases look handled.
    Zero-offset input is safe by accident (Python normalizes `+00:00`/`Z` to
    `timezone.utc`, which icalendar emits as `…Z`); every non-zero offset is
    corrupted.

    Observed against the real modules:

        build_new_event(..., dtstart=fromisoformat('2026-08-10T09:00:00-07:00'))
        ->  DTSTART;TZID="UTC-07:00":20260810T090000
            read.extract_from_raw(raw).dtstart == '2026-08-10T09:00:00'

    Failure scenario: an MCP connector holding a write grant calls
    `smylte_create_event` (whose schema says "otherwise give ISO datetimes") with
    `start="2026-08-10T09:00:00-07:00"` for a 09:00 Pacific meeting. The cache
    stores a start with no zone, so `scheduling.parse_event_time` reads it as
    naive wall time in the owner's home timezone — say Europe/Berlin — and the
    busy interval lands at 09:00 Berlin instead of 18:00. The public page then
    advertises 18:00-18:30 Berlin, a slot the owner is genuinely in a meeting
    for, as free. Thunderbird and DAVx5 see an unresolvable TZID on the same
    resource. No test anywhere sends an offset-bearing datetime to any route.

    The pin asks only that the instant survive the round trip; whether it comes
    back as UTC, as the original offset, or in the owner's zone is the fixer's
    choice.

    **Fixed** in `ical.read.normalize_offset`, called from BOTH parsers: a bare
    fixed offset is re-expressed as UTC, which icalendar emits as `…Z` and which
    round-trips losslessly, while a real `ZoneInfo` is left alone so a series
    keeps its own TZID. `_set_datelike` can still re-express a UTC value into an
    old property's zone.

    Both parsers, because `mcp/api._parse_dt` is a second hand-written copy whose
    docstring says "the same rules the HTTP API uses" and had the identical bug —
    and the finding's own failure scenario goes through `smylte_create_event`, so
    fixing only the HTTP edge would have left the path it describes open. That
    sentence is now true by construction rather than by inspection.
    """
    created = client.post(f"/api/calendars/{calendar}/events", json={
        "summary": "Pacific standup",
        "start": "2026-08-10T09:00:00-07:00",
        "end": "2026-08-10T09:30:00-07:00",
    })
    assert created.status_code == 201, created.text
    uid = created.json()["uid"]

    got = client.get(f"/api/calendars/{calendar}/events/{uid}")
    assert got.status_code == 200, got.text
    start = got.json()["start"]

    parsed = datetime.fromisoformat(start)
    assert parsed.tzinfo is not None, (
        f"the event reads back as {start!r} — floating, naming no instant at all; "
        "the -07:00 the client sent was written as an unresolvable "
        'TZID="UTC-07:00" and then dropped'
    )
    assert parsed.astimezone(UTC) == datetime(2026, 8, 10, 16, 0, tzinfo=UTC), (
        f"the event reads back as {start!r} = {parsed.astimezone(UTC)}, but the "
        "client asked for 09:00 at -07:00, which is 2026-08-10T16:00:00Z"
    )
    assert 'TZID="UTC' not in client.get(
        f"/api/calendars/{calendar}/events/{uid}").text, "a fabricated TZID leaked"


@pytest.mark.parametrize("sent, expect_utc", [
    ("2026-08-10T09:00:00-07:00", datetime(2026, 8, 10, 16, 0, tzinfo=UTC)),
    ("2026-08-10T09:00:00+05:30", datetime(2026, 8, 10, 3, 30, tzinfo=UTC)),
    # The two spellings that were already safe by accident — a fix must not
    # disturb them.
    ("2026-08-10T09:00:00Z", datetime(2026, 8, 10, 9, 0, tzinfo=UTC)),
    ("2026-08-10T09:00:00+00:00", datetime(2026, 8, 10, 9, 0, tzinfo=UTC)),
])
def test_the_mcp_create_path_keeps_the_instant_too(sent, expect_utc):
    """The route the finding's own failure scenario runs through.
    `mcp/api._parse_dt` is a separate copy of the HTTP parser — its docstring
    claims "the same rules the HTTP API uses" — and it carried the same defect,
    so a fix applied only to `app._parse_datelike` would have left
    `smylte_create_event` writing unresolvable TZIDs.

    Driven at the parser plus the builder rather than over MCP, because what is
    being asserted is the bytes that reach Radicale.
    """
    from tasksd.ical import build_new_event
    from tasksd.ical.read import extract_from_raw
    from tasksd.mcp.api import _parse_dt

    raw = build_new_event(
        "z@tasksd", summary="S", dtstart=_parse_dt(sent, field="start"))
    assert 'TZID="UTC' not in raw.decode(), (
        f"{sent} was written as a fabricated TZID: "
        + next(ln for ln in raw.decode().splitlines() if ln.startswith("DTSTART")))
    back = datetime.fromisoformat(extract_from_raw(raw).dtstart)
    assert back.tzinfo is not None and back.astimezone(UTC) == expect_utc, (
        f"{sent} read back as {back}, not {expect_utc}")


def test_a_real_named_zone_is_not_flattened_to_utc():
    """The control on the other side. Normalizing must catch a BARE OFFSET, not
    every aware value: a datetime carrying a real `ZoneInfo` has a zone name
    other clients can resolve and a series anchored to it must keep it, or every
    recurring event would silently lose its DST behaviour."""
    from tasksd.ical.read import normalize_offset

    z = datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert normalize_offset(z).tzinfo is z.tzinfo
    naive = datetime(2026, 8, 10, 9, 0)
    assert normalize_offset(naive) is naive          # floating stays floating
