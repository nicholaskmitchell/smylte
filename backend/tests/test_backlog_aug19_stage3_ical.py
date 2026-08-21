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

    # Forward-going is not enough: a guard that merely CLAMPED a backwards end to
    # its start would satisfy the two assertions below while emitting a
    # zero-length instance, and zero-length blocks nothing either. On the
    # spring-forward side the repaired instance occupies its authored 30 minutes.
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


@pytest.mark.parametrize("tail, spans", [
    # DURATION is EXACT when its parts are time-based (RFC 5545 §3.3.6), so every
    # instance owes thirty real minutes — including the one across the
    # transition. `_exact_durations` + `_repair_span` deliver that.
    (("DURATION:PT30M",), {timedelta(minutes=30)}),
    # DTEND names a WALL-CLOCK end, so the instance on the fall-back day really
    # does run from 01:30 CDT to 02:00 CST — ninety real minutes — and that is
    # the authored answer rather than a defect. Repairing it is what turned an
    # overnight 22:00->06:00 shift from the 9 hours it occupies into 8, releasing
    # the last hour to the public booking page.
    (("DTEND;TZID=America/Chicago:20261025T020000",),
     {timedelta(minutes=30), timedelta(minutes=90)}),
])
def test_the_fall_back_span_follows_how_the_series_authored_its_length(tail, spans):
    """The line between "repair" and "leave alone", pinned as a decision.

    Both spellings look identical to `recurring_ical_events`, which converts
    DURATION to a wall-clock DTEND before this app sees anything
    (`adapters/component.py` pops DURATION unconditionally). So the app has to
    read the length off the ORIGINAL calendar to know which rule applies, and
    off the component that GOVERNS each instance — a RANGE=THISANDFUTURE
    override supplies the length for every slot it covers.

    What must hold for both: never backwards, never zero, and never SHORTER than
    the series occupies, because short is the direction that hands a real
    commitment to an anonymous booker.
    """
    raw = foreign_event_raw(
        "fall@x", "Nightly", dtstart="TZID=America/Chicago:20261025T013000",
        dtend=None, rrule="FREQ=DAILY;COUNT=10",
        vtimezone=CHICAGO_VTIMEZONE, extra=tail,
    )
    occurrences = expand_occurrences(raw, date(2026, 10, 25), date(2026, 11, 10))
    got = {
        f"{o.start} -> {o.end}": (
            datetime.fromisoformat(o.end).astimezone(UTC)
            - datetime.fromisoformat(o.start).astimezone(UTC)
        )
        for o in occurrences
    }
    too_short = {k: str(v) for k, v in got.items() if v < timedelta(minutes=30)}
    assert not too_short, (
        f"an instance blocks LESS time than it occupies, so the booking page "
        f"offers part of a real commitment: {too_short}")
    assert set(got.values()) == spans, (
        f"the spans this series produces changed: { {k: str(v) for k, v in got.items()} }")


def test_an_authored_overnight_span_across_the_fall_back_is_left_alone(): 
    """The regression the narrowing exists for, driven end to end into the busy
    set. A 22:00->06:00 shift authored ON the transition night occupies 9 real
    hours; the over-eager repair reported 8 and freed the last one."""
    raw = foreign_event_raw(
        "night@x", "Night shift", dtstart="TZID=America/Chicago:20261031T220000",
        dtend="TZID=America/Chicago:20261101T060000", rrule="FREQ=WEEKLY;COUNT=3",
        vtimezone=CHICAGO_VTIMEZONE,
    )
    first = expand_occurrences(raw, date(2026, 10, 25), date(2026, 11, 20))[0]
    span = (datetime.fromisoformat(first.end).astimezone(UTC)
            - datetime.fromisoformat(first.start).astimezone(UTC))
    assert span == timedelta(hours=9), (
        f"the authored overnight span came back {span}, not the 9 real hours it "
        f"occupies: {first.start} -> {first.end}")
    busy = scheduling.busy_intervals([{"start": first.start, "end": first.end}], CHICAGO)
    assert busy[0].end.astimezone(UTC) == datetime(2026, 11, 1, 12, 0, tzinfo=UTC), (
        f"the shift stops blocking at {busy[0].end.astimezone(UTC)} but runs to "
        f"2026-11-01T12:00Z — an hour of a real commitment is on offer")


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


# ══ Filed by the Stage 3 adversarial review — 2026-08-20 ═══════════════════
#
# Three findings that Stage 3 CREATED. Each is pinned here before it is fixed,
# the way the harness intends, because the review's own conclusion was that a
# test written after a fix asserts what the fix does rather than what the finding
# needs — which is how three of the four regressions it found got in.


def _rid_values(raw: bytes) -> list[str]:
    """Every RECURRENCE-ID value in the resource, in file order."""
    return [ln.split(":", 1)[1] for ln in raw.decode().splitlines()
            if ln.startswith("RECURRENCE-ID")]


def test_detaching_a_range_override_does_not_land_on_a_slot_already_claimed():
    """`_detach_thisandfuture` re-homes the `RANGE=THISANDFUTURE` override onto
    "the next occurrence", and `_next_generated` computes that from the RRULE
    alone — it never asks whether some other component already addresses that
    slot.

    A range override anchored Jan 7 with a plain single-slot override on Jan 8 is
    the ordinary Apple Calendar / Thunderbird shape: "change this and everything
    after", then "…except that one Thursday". Editing "this event" on Jan 7 moves
    the range override onto Jan 8, and now TWO components claim
    `20260108T090000`.

    That is the exact state this fix's own docstring says the FIRST attempt was
    rejected for — "the reader has no way to rank them" — so the fix reproduced
    the failure it was written to avoid, one slot over. The user's explicit Jan-8
    edit is the one that loses, and it goes to Radicale, so the loss is permanent
    and visible to every other client on the account.

    Asserted as the two things that must both hold: no duplicate RECURRENCE-ID,
    and the Jan-8 edit still on the calendar. Skipping to the next FREE slot,
    refusing the edit, or any other repair satisfies it.
    
    **Fixed** by `_claimed_anchors` plus a bounded skip: `_next_generated` now
    walks with `rr.xafter(count=len(blocked) + len(exdates) + 1)` and returns the
    first slot that neither another override nor an EXDATE has spoken for. The
    count is what makes it terminate — at most that many slots can be
    unavailable, so a free one appears within them if it exists at all, where a
    loop of `.after()` calls has no such bound.
    """
    raw = foreign_event_raw(
        "claim@x", "standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=DAILY;COUNT=6",
        overrides=(
            ("RECURRENCE-ID;RANGE=THISANDFUTURE:20260107T090000Z",
             "DTSTART:20260107T100000Z", "DTEND:20260107T103000Z",
             "SUMMARY:standup moved to 10"),
            ("RECURRENCE-ID:20260108T090000Z",
             "DTSTART:20260108T110000Z", "DTEND:20260108T113000Z",
             "SUMMARY:jan 8 special"),
        ),
    )
    edited = apply_occurrence_override(
        raw, "2026-01-07T09:00:00+00:00", EventEdit(summary="renamed just this one"))

    rids = _rid_values(edited)
    assert len(rids) == len(set(rids)), (
        f"two components claim one RECURRENCE-ID, which no reader can rank: {rids}")

    summaries = {o.summary for o in expand_occurrences(
        edited, date(2026, 1, 1), date(2026, 2, 1))}
    assert "jan 8 special" in summaries, (
        f"the user's explicit Jan-8 edit was destroyed by re-homing the range "
        f"override on top of it; the series now reads {sorted(summaries)}")


def test_detaching_a_range_override_does_not_land_on_an_excluded_slot():
    """The other half of "the next occurrence", and the half a fix that only
    checks other OVERRIDES sails past — verified: deleting the EXDATE check while
    keeping the claimed-anchor one passes every other test in this file.

    An EXDATE'd slot is not an occurrence. Re-homing a `RANGE=THISANDFUTURE`
    override onto one hands every other CalDAV client a RECURRENCE-ID that
    addresses a deleted instance: nothing renders it, so nothing can act on it,
    and the values it carries for the occurrences after it are attached to a slot
    the series does not generate.

    Jan 8 is excluded here, so detaching Jan 7 has to skip it and land on Jan 9 —
    carrying the +1h shift with it, which is what keeps the later occurrences at
    the time the user actually sees.
    """
    raw = foreign_event_raw(
        "exdate@x", "standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=DAILY;COUNT=6", exdate="20260108T090000Z",
        overrides=(
            ("RECURRENCE-ID;RANGE=THISANDFUTURE:20260107T090000Z",
             "DTSTART:20260107T100000Z", "DTEND:20260107T103000Z",
             "SUMMARY:standup moved to 10"),
        ),
    )
    edited = apply_occurrence_override(
        raw, "2026-01-07T09:00:00+00:00", EventEdit(summary="renamed just this one"))

    rids = _rid_values(edited)
    assert "20260108T090000Z" not in rids, (
        f"the range override was re-homed onto an EXDATE'd slot, so it now "
        f"addresses an occurrence that does not exist: {rids}")

    by_start = {o.start: o.summary for o in expand_occurrences(
        edited, date(2026, 1, 1), date(2026, 2, 1))}
    assert "2026-01-08T09:00:00+00:00" not in by_start, (
        f"the excluded occurrence came back: {sorted(by_start)}")
    assert by_start.get("2026-01-07T10:00:00+00:00") == "renamed just this one"
    # …and the range override still governs what follows, at the hour it moved
    # them to rather than back at the master's.
    assert by_start.get("2026-01-09T10:00:00+00:00") == "standup moved to 10", (
        f"the occurrences the range override governs lost its values or its "
        f"time: {by_start}")


def test_a_range_override_survives_an_edit_it_cannot_be_re_homed_around():
    """`_next_generated` returns None for a FREQ outside the `_FREQ` whitelist,
    for a probe over `_MAX_PROBE_INSTANCES`, and for a search budget that fires —
    and `_detach_thisandfuture` treats that identically to "the range override
    anchored the last occurrence", which is the one case where deleting it is
    right.

    So on a foreign rule this app cannot probe — `FREQ=HOURLY;INTERVAL=24` is a
    perfectly ordinary way to write "daily", and the whitelist exists because
    probing a foreign rule is unbounded, not because the rule is invalid — one
    "this event" click silently deletes the summary, the moved time and the
    LOCATION a foreign client authored for every later occurrence. The docstring
    calls that "the safe direction". It is permanent data loss on the next PUT,
    where the code it replaced preserved those values.

    Either outcome is correct: keep the range override (and put the edit
    somewhere that does not collide), or refuse the edit with a ValueError, which
    both call paths already map — `patch_event` to 422, `update_event` to a
    ToolError. What is not correct is answering success and deleting the values.
    
    **Fixed** with a `_UNKNOWN` sentinel separating "the rule was evaluated and
    there is nothing later" — where dropping the override is right, and
    `test_detaching_the_last_occurrence_of_a_range_override_does_not_strand_it`
    covers it — from "the rule could not be evaluated", which now raises.
    """
    raw = foreign_event_raw(
        "unprobe@x", "standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=HOURLY;INTERVAL=24;COUNT=6",
        overrides=(
            ("RECURRENCE-ID;RANGE=THISANDFUTURE:20260107T090000Z",
             "DTSTART:20260107T100000Z", "DTEND:20260107T103000Z",
             "SUMMARY:standup moved to 10", "LOCATION:Room B"),
        ),
    )
    try:
        edited = apply_occurrence_override(
            raw, "2026-01-07T09:00:00+00:00", EventEdit(summary="just this one"))
    except ValueError:
        return                                  # a clean refusal is a fix

    body = edited.decode()
    assert "SUMMARY:standup moved to 10" in body and "LOCATION:Room B" in body, (
        "the range override was deleted, so the summary, the moved time and the "
        "location a foreign client authored for every later occurrence are gone "
        "from the bytes about to be PUT:\n" + body)


def test_a_duration_authored_instance_holds_its_exact_length_across_the_fall_back():
    """The half of finding 26 that the narrowed `_repair_span` does not reach.

    A DURATION is EXACT when its parts are hours/minutes/seconds (RFC 5545
    §3.3.6 — "the duration of a week or a day depends on its position in the
    calendar" while an hour does not), so every instance of a `DURATION:PT30M`
    series occupies thirty minutes of real time. On the fall-back day the library
    emits `01:30-05:00 -> 02:00-06:00`, which is ninety.

    `_repair_span` currently repairs only a non-positive span, deliberately: the
    version that repaired every span whose exact duration disagreed with its
    wall-clock duration also rewrote AUTHORED DTEND spans, turning an overnight
    22:00->06:00 shift across that night from the 9 real hours it occupies into 8
    and releasing the last hour to the public booking page.

    The distinction the repair needs is how the governing component authored its
    LENGTH — DURATION is exact, DTEND is a wall-clock end. This drives the
    DURATION spelling only; the DTEND control next door must keep passing, and so
    must `test_an_authored_overnight_span_across_the_fall_back_is_left_alone`.
    
    **Fixed** by `_exact_durations`, which reads the authored length off the
    ORIGINAL calendar (the library pops DURATION before this app sees a
    component) and keys it by the GOVERNING component — a RANGE=THISANDFUTURE
    override supplies the length for every slot it covers, so an instance it
    governs must not read the master's.

    One thing the pin caught that reading would not have:
    `recurring_ical_events` stamps a RECURRENCE-ID on EVERY instance it emits,
    including the ones a plain series generates, so keying the lookup on the
    emitted value matched nothing. `override_anchors` — the rids an AUTHORED
    override carries — is what distinguishes them, and it was already in scope.
    """
    raw = foreign_event_raw(
        "exact@x", "Nightly", dtstart="TZID=America/Chicago:20261025T013000",
        dtend=None, rrule="FREQ=DAILY;COUNT=10",
        vtimezone=CHICAGO_VTIMEZONE, extra=("DURATION:PT30M",),
    )
    spans = {
        f"{o.start} -> {o.end}": (
            datetime.fromisoformat(o.end).astimezone(UTC)
            - datetime.fromisoformat(o.start).astimezone(UTC)
        )
        for o in expand_occurrences(raw, date(2026, 10, 25), date(2026, 11, 10))
    }
    wrong = {k: str(v) for k, v in spans.items() if v != timedelta(minutes=30)}
    assert not wrong, (
        f"a PT30M instance does not occupy thirty minutes of real time, so it "
        f"withholds availability the owner actually has: {wrong}")


# ── the design review of these three fixes found four more, all pinned here ──
#
# Written after the fixes rather than before, and said so plainly: they came out
# of a design review of the fixes themselves, so there was never a moment when
# the finding existed and the fix did not. Each was reproduced before it was
# fixed.

def test_an_rdate_period_keeps_its_own_length_not_the_masters():
    """The blocker the design review found in the exact-duration repair.

    `RDATE;VALUE=PERIOD` states its own length, and `recurring_ical_events` takes
    it from the period rather than from the master. The first version of the
    repair read the master's DURATION for any instance no AUTHORED override
    claimed — and a period slot is not an override — so a four-hour block came
    back as thirty minutes, on an ordinary January day with no transition
    anywhere near it. Three and a half hours of a real commitment released to the
    public booking page: the same failure `_repair_span` was narrowed to prevent,
    through a different door.

    The repair now fires only on the DST artifact's own signature — the emitted
    pair states the authored length in WALL CLOCK and delivers something else in
    real time. Anything whose wall-clock span is a different length came from
    somewhere else and is left alone, which fails closed for every family nobody
    thought to enumerate.
    """
    raw = foreign_event_raw(
        "period@x", "Block", dtstart="20260106T090000Z", dtend=None,
        rrule="FREQ=WEEKLY;COUNT=2",
        extra=("DURATION:PT30M", "RDATE;VALUE=PERIOD:20260120T090000Z/PT4H"),
    )
    spans = {
        o.start: (datetime.fromisoformat(o.end).astimezone(UTC)
                  - datetime.fromisoformat(o.start).astimezone(UTC))
        for o in expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))
    }
    assert spans.get("2026-01-20T09:00:00+00:00") == timedelta(hours=4), (
        f"the RDATE period's own four-hour length was overwritten with the "
        f"master's PT30M: { {k: str(v) for k, v in spans.items()} }")
    assert spans.get("2026-01-06T09:00:00+00:00") == timedelta(minutes=30)


def test_a_date_valued_exdate_still_blocks_a_re_homed_override():
    """A DATE-valued EXDATE on a TIMED series removes the whole day — that is
    what `recurring_ical_events` does, keeping a separate date-keyed exclusion
    set. `_same_instant` answers False outright for a date/datetime pair, so
    comparing instants alone let the re-homed override land on the excluded slot
    and the deleted occurrence came back.

    The `VALUE=DATE` spelling is what a client writes when the user deletes a
    whole day, so this is not an exotic input.
    """
    raw = foreign_event_raw(
        "exdate2@x", "standup", dtstart="20260105T090000Z", dtend="20260105T093000Z",
        rrule="FREQ=DAILY;COUNT=6",
        # Through `extra`, not the `exdate=` kwarg: the helper renders that one
        # as `EXDATE:<value>` and only special-cases a TZID parameter, so a
        # VALUE=DATE would come out as `EXDATE:VALUE=DATE:...` — malformed.
        extra=("EXDATE;VALUE=DATE:20260107",),
        overrides=(
            ("RECURRENCE-ID;RANGE=THISANDFUTURE:20260106T090000Z",
             "DTSTART:20260106T100000Z", "DTEND:20260106T103000Z",
             "SUMMARY:moved to 10"),
        ),
    )
    edited = apply_occurrence_override(
        raw, "2026-01-06T09:00:00+00:00", EventEdit(summary="just this one"))

    rids = _rid_values(edited)
    assert not any(r.startswith("20260107") for r in rids), (
        f"the override was re-homed onto a day the series excludes: {rids}")
    starts = {o.start for o in expand_occurrences(
        edited, date(2026, 1, 1), date(2026, 2, 1))}
    assert not any(s.startswith("2026-01-07") for s in starts), (
        f"the excluded day came back: {sorted(starts)}")


def test_an_rdate_only_series_can_still_have_one_occurrence_edited():
    """An RDATE-only resource is a real series — the library puts RDATEs into the
    same rruleset and a range override governs them — and the first version of
    the `_UNKNOWN` sentinel answered `_UNKNOWN` for any resource with no RRULE.
    That turned "delete the override" into "refuse forever": no occurrence of
    such a series could be edited at all.

    A fix for a data-loss bug must not close a door the loss did not.
    """
    raw = foreign_event_raw(
        "rdonly@x", "standup", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rdate="20260113T090000Z,20260120T090000Z",
        overrides=(
            ("RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z",
             "DTSTART:20260113T100000Z", "DTEND:20260113T103000Z",
             "SUMMARY:moved to 10", "LOCATION:Room B"),
        ),
    )
    edited = apply_occurrence_override(
        raw, "2026-01-13T09:00:00+00:00", EventEdit(summary="just this one"))

    body = edited.decode()
    assert "SUMMARY:moved to 10" in body and "LOCATION:Room B" in body, (
        "the range override was deleted, so what it authored for the later RDATE "
        "occurrences is gone:\n" + body)
    by_start = {o.start: o.summary for o in expand_occurrences(
        edited, date(2026, 1, 1), date(2026, 2, 1))}
    assert by_start.get("2026-01-13T10:00:00+00:00") == "just this one"
    assert by_start.get("2026-01-20T10:00:00+00:00") == "moved to 10", (
        f"the later RDATE occurrence lost the range override's values: {by_start}")


# ── Filed by the Stage 3 adversarial review — OPEN when written ─────────────
#
# These carry `xfail(strict=True)` like every other pin in this file. The rest
# of it is closed regression tests; a marker here is what tells the two apart.


def test_an_exact_day_long_duration_survives_the_cache_and_the_expansion():
    """`split_duration`'s whole premise is that only the DURATION's own bytes say
    whether it was nominal or exact, and neither consumer ever sees those bytes.

    `read.extract` stores `comp.get("DURATION").to_ical().decode()`, and
    `to_ical()` re-serializes a normalized `timedelta`: icalendar parses `PT24H`
    to `timedelta(days=1)`, which comes back out as `P1D`. `recur._exact_durations`
    reads the same `to_ical()` and classifies the event as nominal. So an exact
    duration of a day or more is misread at BOTH layers — `advance` is handed a
    string that has already lost the distinction it exists to preserve.

    Measured: `PT24H` across the 2026-03-08 spring-forward blocks 23 real hours
    instead of 24, releasing an hour to the public booking page, which is the
    same failure the DST work in this stage was about.

    Two halves, deliberately, because a repair at one layer leaves the other
    wrong and looks done: the CACHED value (what `busy_intervals` re-parses) and
    the EXPANDED instance (what `_exact_durations` feeds `_repair_span`).
    """
    from tasksd.ical.read import extract_from_raw

    # -- the cached column --
    for authored in ("PT24H", "PT36H", "P1DT12H", "P1D", "PT1H30M"):
        raw = foreign_event_raw(
            "dur@x", "Block", dtstart="20260308T073000Z", dtend=None,
            extra=(f"DURATION:{authored}",))
        got = extract_from_raw(raw).duration
        assert got == authored, (
            f"authored DURATION:{authored} was cached as {got!r} — "
            f"the nominal/exact distinction is gone before anything reads it"
        )

    # -- and the expansion, which reads its own copy --
    #
    # In a ZONE THAT OBSERVES DST, and that is the whole point: in UTC a 24-hour
    # wall-clock span IS 24 real hours, so a version of this case anchored to
    # UTC passes against the bug and against a repair that fixes only the cached
    # column. It has to straddle the 2026-03-08 spring-forward, where the
    # library's wall-clock arithmetic yields 23 real hours and `_exact_durations`
    # is the only thing that can say the authored PT24H meant otherwise.
    raw = foreign_event_raw(
        "dur2@x", "Block", dtstart="TZID=America/Chicago:20260307T230000",
        dtend=None, extra=("DURATION:PT24H", "RRULE:FREQ=DAILY;COUNT=3"),
        vtimezone=CHICAGO_VTIMEZONE)
    spans = {
        o.start: (datetime.fromisoformat(o.end) - datetime.fromisoformat(o.start))
        for o in expand_occurrences(raw, date(2026, 3, 1), date(2026, 3, 20))
    }
    assert spans, "the series produced no occurrences"
    for start, span in spans.items():
        assert span == timedelta(hours=24), (
            f"the instance at {start} spans {span}, not the authored 24 hours"
        )


def test_an_overrides_own_duration_is_not_classified_by_the_masters():
    """WIDENING. Both halves of the pin above use a SINGLE-VEVENT resource, so
    nothing in them distinguishes "the authored DURATION of this VEVENT" from
    "the authored DURATION of this RESOURCE". An adversarial review collapsed
    `wire_durations`' per-RECURRENCE-ID map to one entry — `out[None]`, read
    back as `wire.get(None)` in both `extract` and `_exact_durations` — and the
    whole ical suite stayed green.

    That collapse hands every instance the FIRST VEVENT's duration text, and the
    master is written first. A master authored `P1D` (NOMINAL: "a day", which
    across a spring-forward is 23 real hours) and an override authored `PT24H`
    (EXACT: 24 real hours, RFC 5545 §3.3.6) are the two values that disagree by
    exactly the hour, so the override's own kind is what has to survive.

    2026-03-07 23:00 America/Chicago is the instance that straddles the
    transition. Under the collapse it is classified nominal like the master and
    spans 23:00:00 — an hour of a real appointment released to the public
    booking page, which is the failure the whole mechanism exists to prevent.
    """
    raw = foreign_event_raw(
        "mixed@x", "Block", dtstart="TZID=America/Chicago:20260305T230000",
        dtend=None, vtimezone=CHICAGO_VTIMEZONE,
        extra=("DURATION:P1D", "RRULE:FREQ=DAILY;COUNT=4"),
        overrides=((
            "RECURRENCE-ID;TZID=America/Chicago:20260307T230000",
            "DTSTART;TZID=America/Chicago:20260307T230000",
            "SUMMARY:Block",
            "DURATION:PT24H",
        ),),
    )

    from tasksd.ical.read import wire_durations
    wire = wire_durations(raw)
    assert wire.get("20260307T230000") == "PT24H", (
        f"the override's own DURATION did not survive the scan: {wire!r}"
    )
    assert wire.get(None) == "P1D", (
        f"the master's own DURATION did not survive the scan: {wire!r}"
    )

    spans = {
        o.start: (datetime.fromisoformat(o.end) - datetime.fromisoformat(o.start))
        for o in expand_occurrences(raw, date(2026, 3, 1), date(2026, 3, 20))
    }
    assert spans, "the series produced no occurrences"
    overridden = [st for st in spans if st.startswith("2026-03-07T23:00")]
    assert overridden, f"the overridden instance is missing: {sorted(spans)}"
    assert spans[overridden[0]] == timedelta(hours=24), (
        f"the 7 March instance spans {spans[overridden[0]]} — the override's "
        f"EXACT PT24H was classified by the master's NOMINAL P1D"
    )
    others = {st: sp for st, sp in spans.items() if st != overridden[0]}
    assert others, "the master produced no un-overridden instances"
    for st, sp in others.items():
        assert sp == timedelta(hours=24), (
            f"the un-overridden instance at {st} spans {sp}, not a day"
        )

    # Control, and it needs its own resource. Only ONE instance of this series
    # straddles the transition — 2026-03-07 23:00 — and above it is the
    # overridden one, so nothing in that calendar can show what the MASTER's
    # nominal P1D does there. A repair that reached the override's kind by
    # treating every DURATION as exact would pass everything above.
    #
    # The same master with the override removed: its 7 March instance must span
    # 23 real hours, because "a day" is nominal and that day is 23 hours long.
    plain = foreign_event_raw(
        "plain@x", "Block", dtstart="TZID=America/Chicago:20260305T230000",
        dtend=None, vtimezone=CHICAGO_VTIMEZONE,
        extra=("DURATION:P1D", "RRULE:FREQ=DAILY;COUNT=4"))
    plain_spans = {
        o.start: (datetime.fromisoformat(o.end) - datetime.fromisoformat(o.start))
        for o in expand_occurrences(plain, date(2026, 3, 1), date(2026, 3, 20))
    }
    straddling = [st for st in plain_spans if st.startswith("2026-03-07T23:00")]
    assert straddling, f"the un-overridden series lost 7 March: {sorted(plain_spans)}"
    assert plain_spans[straddling[0]] == timedelta(hours=23), (
        f"an un-overridden NOMINAL P1D across the spring-forward spans "
        f"{plain_spans[straddling[0]]}, not the 23 real hours that day holds"
    )


def test_dragging_an_every_weekday_series_refuses_rather_than_corrupting_it():
    """The REVERSE of what this test asserted when the finding was first closed,
    and the reversal is the finding.

    The audit asked for `FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR` — Google Calendar's
    "Every weekday" — to become draggable, on the reasoning that BYDAY under a
    sub-weekly FREQ is a filter rather than a day selector, so a shift inside the
    set desynchronizes nothing. Allowing it was shipped, and an adversarial
    review reproduced what it does:

        BEFORE  Jan 7, 9, 14, 16, 19      (the user had deleted Jan 12)
        AFTER   Jan 9, 12, 16, 19, 21

    Jan 12 — deleted — is back. Jan 14 — live — is gone. The RRULE never rotated,
    so the series did not move at all; only DTSTART and the EXDATEs did.
    `shift_series` shifts every EXDATE, RDATE and RECURRENCE-ID by `delta`, and
    with the rule's own days unchanged those land on the wrong occurrences.

    So the suggested fix was wrong on its own terms, and its premise — that this
    series "previously worked correctly" — was wrong too: before finding 16 it
    silently corrupted in exactly this way. Refusing is the honest answer, and
    this test now pins the refusal so the next attempt has to reckon with it.

    The finding is REOPENED in docs/AUDIT.md with this evidence.
    """
    raw = foreign_event_raw(
        "wd@x", "Standup", dtstart="20260105T090000Z", dtend="20260105T093000Z",
        rrule="FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=10")
    moved = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)      # Mon -> Tue
    with pytest.raises(ValueError, match="BYDAY"):
        shift_series(
            raw, "2026-01-05T09:00:00+00:00",
            EventEdit(dtstart=moved, dtend=moved + timedelta(minutes=30)))


def test_a_weekday_drag_does_not_move_an_exdate_onto_a_live_occurrence():
    """What the refusal above is protecting, stated as the outcome rather than
    as the mechanism — so a future fix that makes the drag work has something to
    satisfy rather than just a `pytest.raises` to delete.

    Either the edit is refused, or the occurrence set afterwards is the one the
    user asked for: their deleted day still deleted, their live days still live.
    """
    raw = foreign_event_raw(
        "mwf@x", "standup", dtstart="20260107T090000Z", dtend="20260107T093000Z",
        rrule="FREQ=DAILY;BYDAY=MO,WE,FR;COUNT=6",
        extra=("EXDATE:20260112T090000Z",))
    before = [datetime.fromisoformat(o.start).date()
              for o in expand_occurrences(raw, date(2026, 1, 1), date(2026, 2, 1))]
    assert date(2026, 1, 12) not in before      # the user deleted it
    assert date(2026, 1, 14) in before          # and this one is real

    moved = datetime(2026, 1, 9, 9, 0, tzinfo=timezone.utc)      # Wed -> Fri
    try:
        out = shift_series(
            raw, "2026-01-07T09:00:00+00:00",
            EventEdit(dtstart=moved, dtend=moved + timedelta(minutes=30)))
    except ValueError:
        return                                  # refused: nothing was corrupted

    after = [datetime.fromisoformat(o.start).date()
             for o in expand_occurrences(out, date(2026, 1, 1), date(2026, 2, 1))]
    assert date(2026, 1, 12) not in after, (
        f"an occurrence the user had DELETED came back: {after}")
    assert date(2026, 1, 14) in after, (
        f"a live occurrence was deleted by a drag that did not touch it: {after}")


def test_a_weekday_series_dragged_onto_a_weekend_is_still_refused():
    """The control for the pin above, and the reason the repair has to test the
    PROPERTY rather than just whitelisting `FREQ=DAILY;BYDAY=…`.

    Saturday is not in `MO,TU,WE,TH,FR`, so a +5-day drag puts DTSTART on a day
    the rule cannot generate — the series really would desynchronize from its own
    start. Refusing is correct here, and a fix that simply stopped looking at
    BYDAY under FREQ=DAILY would let it through.
    """
    raw = foreign_event_raw(
        "wd2@x", "Standup", dtstart="20260105T090000Z", dtend="20260105T093000Z",
        rrule="FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=10")
    moved = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)     # Mon -> Sat
    with pytest.raises(ValueError):
        shift_series(
            raw, "2026-01-05T09:00:00+00:00",
            EventEdit(dtstart=moved, dtend=moved + timedelta(minutes=30)))


def test_an_alarms_duration_is_not_mistaken_for_the_events():
    """A VALARM is a SUBCOMPONENT of a VEVENT, and it carries its own DURATION —
    the repeat interval that sits beside `REPEAT:` (RFC 5545 §3.8.6.3). Apple
    Calendar and DAVx5 write one for any repeating or snoozing alarm, so this is
    an ordinary resource, not a crafted one.

    `wire_durations` scans content lines with a single boolean and tracks only
    `BEGIN:VEVENT`/`END:VEVENT`, so the alarm's line lands in the same branch as
    the event's. Producers put VALARM last, so the alarm's value is the one that
    survives to `END:VEVENT` — and `extract` PREFERS the wire value over
    `to_ical()`, so it is what reaches the cache's `duration` column, which
    `busy_intervals` re-parses.

    A two-hour appointment therefore blocks five minutes, and the hour and
    fifty-five minutes left over are offered to anonymous visitors on the public
    booking page. That is the same failure the wire-DURATION work was written to
    stop, one layer further out and larger.

    Two more shapes are pinned with it, because they are the same defect and the
    same blast radius: a value that makes the event vanish from the busy set
    entirely, and a parameterised DURATION whose first colon is inside the
    parameter rather than before the value.
    """
    from tasksd.ical.read import extract_from_raw, split_duration, wire_durations

    def alarmed(dur: str, alarm: str = "PT5M") -> str:
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:al@x\r\n"
            "DTSTART:20260909T140000Z\r\n"
            f"DURATION:{dur}\r\nSUMMARY:Deposition\r\n"
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\n"
            f"DURATION:{alarm}\r\nREPEAT:3\r\nEND:VALARM\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )

    # The alarm's interval, whatever it is, is never the event's length.
    for alarm in ("PT5M", "P0D", "PT0S", "-PT5M"):
        raw = alarmed("PT2H", alarm)
        assert wire_durations(raw) == {None: "PT2H"}, (
            f"a VALARM DURATION:{alarm} was read as the event's: "
            f"{wire_durations(raw)}"
        )
        assert extract_from_raw(raw).duration == "PT2H", (
            f"a VALARM DURATION:{alarm} reached the cache column as "
            f"{extract_from_raw(raw).duration!r}"
        )

    # …and the whole point of the column: what the busy set makes of it.
    ev = {"start": "2026-09-09T14:00:00+00:00", "end": None,
          "duration": extract_from_raw(alarmed("PT2H")).duration,
          "all_day": False, "start_is_date": False, "end_is_date": False}
    busy = scheduling.busy_intervals([ev], timezone.utc)
    assert busy, "the event left the busy set entirely"
    assert _span(busy[0]) == timedelta(hours=2), (
        f"the busy interval is {_span(busy[0])}, not the authored 2 hours "
        f"— the difference is offered to anonymous visitors"
    )

    # A DURATION line this scan cannot read cleanly must never REPLACE what the
    # library made of it. `X-A=a:b:PT8H` is malformed — RFC 5545 §3.1 forbids a
    # colon in an unquoted parameter value, so the value really is `b:PT8H` —
    # and the point is not which of the two readings wins but that an
    # unparseable string is never what gets cached and re-parsed downstream.
    param = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:p@x\r\n"
        "DTSTART:20260909T140000Z\r\n"
        "DURATION;X-EVOLUTION-ALARM-UID=a:b:PT8H\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    cached = extract_from_raw(param).duration
    assert cached is None or split_duration(cached) is not None, (
        f"an unparseable DURATION reached the cache column as {cached!r}; "
        f"busy_intervals re-parses this and drops what it cannot read, which "
        f"removes the event from the busy set entirely"
    )


def test_unfolding_a_large_resource_stays_linear():
    """A COST BOUND, not a benchmark — the same shape as `rrule_budget`'s.

    `unfold` runs inside `expand_occurrences`, which the PUBLIC BOOKING PAGE
    reaches for every event calendar, uncached, and which runs inside the
    service's global lock. So its cost is an anonymous visitor's lever on the
    owner's whole app, and the resource size is set by whatever CalDAV client
    wrote the item — Radicale's default cap is 100 MB, well past the app's own
    1 MB body limit, which does not apply to bytes arriving through sync.

    The first version accumulated with `out[-1] += line[1:]`. The list holds a
    reference at concat time, so CPython cannot append in place and every
    continuation line copied the whole accumulated string: measured 0.63 s for
    200k folded lines and 16 s for a 4 MB resource, against the icalendar
    parser's own 0.27 s for the same input.

    The bound is deliberately loose — 20x headroom over the measured ~0.04 s, so
    a slow CI box cannot flake it — because it only has to separate linear from
    quadratic, and quadratic misses it by two orders of magnitude.
    """
    import time
    from tasksd.ical.read import unfold

    folded = ("BEGIN:VCALENDAR\r\nDESCRIPTION:x"
              + "".join("\r\n abcd" for _ in range(200_000))
              + "\r\nEND:VCALENDAR\r\n")
    started = time.perf_counter()
    lines = unfold(folded)
    elapsed = time.perf_counter() - started

    assert lines[1] == "DESCRIPTION:x" + "abcd" * 200_000
    assert elapsed < 1.0, (
        f"unfolding 200k folded lines took {elapsed:.2f}s — that is the "
        f"quadratic shape returning, on a path the public booking page reaches "
        f"under the global service lock"
    )
