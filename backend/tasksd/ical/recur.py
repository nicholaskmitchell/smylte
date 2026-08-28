"""Recurrence expansion (spec §6).

Project a resource's recurrence set — RRULE / RDATE / EXDATE plus any
RECURRENCE-ID overrides — into the individual occurrences that fall inside a
``[window_start, window_end)`` range, working entirely from the cached
``raw_ics`` (no network, no DB). This is the read-path counterpart to
``read.extract``: ``read`` caches the *master's* columns; ``recur`` fans the
*series* out into per-instance rows for the calendar grid.

The calendar math is delegated to ``recurring_ical_events`` (built on the same
``icalendar`` objects we already parse). It applies EXDATE holes, RDATE
additions and RECURRENCE-ID overrides, and honours VALUE=DATE vs DATE-TIME,
DTEND vs DURATION, and VTIMEZONE/TZID. Every occurrence it returns carries a
RECURRENCE-ID equal to that instance's *original* slot — we use it as the stable
anchor that both keys the UI row and (Tier 3) addresses a single instance for a
per-occurrence edit. Two things we still do ourselves: drop CANCELLED instances,
and refuse to enumerate a pathological RRULE (see ``_pathological_rule`` — the
cost of such a rule cannot be bounded after expansion starts, so the shape is
judged up front and the resource renders as its master row).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from math import ceil

import recurring_ical_events
from icalendar import Calendar

from .rrule_budget import SearchBudgetExceeded, search_budget
from .read import _iso, _text, advance, split_duration, wire_durations

log = logging.getLogger("tasksd.recur")

# Instances one day of a rule may yield before we call it pathological and
# decline to expand it. Hourly (24) is the densest shape a person plausibly puts
# on a calendar; past that the cost is unbounded in practice, so the resource
# renders as its master row instead (see _pathological_rule).
_MAX_PER_DAY = 24

# Ceiling on the *total* walk from a rule's DTSTART to the end of the requested
# window. Generous enough for any real series (a decade of daily standups is
# ~3.6k, 24/day for five years is ~44k) while refusing the ancient-DTSTART dense
# rules whose skip phase dominates everything. See _instances_before.
_MAX_TOTAL_INSTANCES = 200_000

# Periods dateutil may walk, per expansion, before we stop it. The guards above
# bound a rule's YIELD; this bounds its SEARCH, which is the part an
# unsatisfiable rule makes unbounded — UNTIL and COUNT are tested only when an
# instance is actually produced, so neither bounds a rule that produces none.
# See tasksd/ical/rrule_budget.py for why this is a cost bound rather than a
# satisfiability check.
#
# Measured over a 42-day grid: the most expensive LEGITIMATE rule found costs 890
# periods (FREQ=DAILY;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO from a 1970 DTSTART — the
# skip phase dominates, and window width barely moves it), while every
# never-matching rule that costs real time walks 95,760. 5000 sits between with
# 5.6x headroom under the worst legitimate rule and 19x under the expensive
# hostile ones. The budget is per expand_occurrences call, so it also caps a
# resource carrying many VEVENTs rather than each rule separately.
_MAX_SEARCH_STEPS = 5000

# How many instances each FREQ yields per day before BY* parts are applied.
_FREQ_PER_DAY = {"SECONDLY": 86400, "MINUTELY": 1440, "HOURLY": 24}


@dataclass
class Occurrence:
    start: str | None
    start_is_date: bool          # all-day (VALUE=DATE) instance?
    end: str | None
    end_is_date: bool
    recurrence_id: str           # ISO of the ORIGINAL slot — anchors/addresses the instance
    is_override: bool            # backed by an explicit RECURRENCE-ID override component
    summary: str | None
    description: str | None
    location: str | None
    status: str | None
    # This instance's TRANSP, if the component carries one. An override may
    # differ from its master — "the Tuesday standup is Free that week" is a
    # thing Apple Calendar can express — so it is read per occurrence like
    # `status` beside it, and falls back to the master's in `_occurrence_dto`.
    transp: str | None


def _end_fields(comp) -> tuple[str | None, bool]:
    """(iso, is_date) for the instance end: DTEND if present, else DTSTART+DURATION."""
    dtend = comp.get("DTEND")
    if dtend is not None:
        return _iso(dtend)
    dtstart, dur = comp.get("DTSTART"), comp.get("DURATION")
    # UNREACHABLE from `expand_occurrences`: `recurring_ical_events` pops DURATION
    # from every component it emits and always writes DTEND
    # (adapters/component.py). Kept for a caller that hands over a raw component,
    # but it is NOT the source of truth for an expanded instance's length —
    # `_exact_durations` reads that off the original calendar.
    if dtstart is not None and dur is not None:
        # Not `dtstart.dt + dur.dt`: see `advance`. That is the same wall-clock
        # addition `_repair_span` below exists to undo, one layer earlier.
        return _iso(advance(dtstart.dt, dur.to_ical(), dur.dt))
    return None, False


def _override_anchors(cal: Calendar) -> set[str]:
    """ISO RECURRENCE-IDs of the resource's explicit override components, so an
    expanded instance can be flagged as an override even when the override
    changed only a non-time field (same DTSTART as the generated slot)."""
    out: set[str] = set()
    for comp in cal.walk("VEVENT"):
        rid = comp.get("RECURRENCE-ID")
        if rid is not None:
            iso = _iso(rid)[0]
            if iso is not None:
                out.add(iso)
    return out


def _thisandfuture_shifts(cal: Calendar) -> dict[str, timedelta]:
    """ISO RECURRENCE-ID -> the offset each ``RANGE=THISANDFUTURE`` override
    applies (its own DTSTART minus its RECURRENCE-ID).

    Such an override (RFC 5545 §3.2.13, written by Apple Calendar and
    Thunderbird for "this and all future events") covers its own slot *and every
    later one*, so ``recurring_ical_events`` correctly emits several instances
    from it — but every one of them carries the same RECURRENCE-ID. Knowing the
    offset lets ``_occurrence`` subtract it back off each instance's start to
    recover the distinct rule slot that instance actually stands for."""
    out: dict[str, timedelta] = {}
    for comp in cal.walk("VEVENT"):
        rid, dtstart = comp.get("RECURRENCE-ID"), comp.get("DTSTART")
        if rid is None or dtstart is None:
            continue
        if str(rid.params.get("RANGE", "")).upper() != "THISANDFUTURE":
            continue
        iso = _iso(rid)[0]
        if iso is None or not _same_shape(rid.dt, dtstart.dt):
            continue                      # mismatched pair: no meaningful offset
        out[iso] = dtstart.dt - rid.dt
    return out


def _exact_durations(cal: Calendar, wire: dict[str | None, str]) -> dict[str | None, timedelta]:
    """ISO RECURRENCE-ID (None for the master) -> the EXACT length it authored.

    Only components that authored a time-based `DURATION` appear. RFC 5545 §3.3.6
    makes hours/minutes/seconds exact and weeks/days nominal, so a `PT30M` series
    occupies thirty minutes of real time on every instance while a `P1D` one
    means "the same time tomorrow" — the second is what the library's wall-clock
    arithmetic already produces, so only the first needs repairing.

    Keyed by governing component rather than taken from the master alone, because
    a `RANGE=THISANDFUTURE` override supplies the values for every instance it
    covers — including its length — and `recurring_ical_events` emits those
    instances from it. Applying the master's duration to an instance the master
    does not govern would be a new wrong answer in place of the old one.

    A component authoring DTEND is deliberately absent, and the reason is §3.3.6
    rather than §3.8.5.3. It is worth being precise, because the obvious citation
    argues the opposite: §3.8.5.3 says a DTEND-authored recurrence carries the
    same EXACT duration to every instance, and applying that literally is what
    turned an overnight 22:00->06:00 shift across the fall-back night from the 9
    real hours it occupies into 8 — the regression this file was narrowed to undo.

    The honest argument is about information, not about that clause: a DURATION
    carries the nominal/exact distinction in its own bytes, and a DTEND does not.
    With nothing to say which reading was meant, wall-clock preservation is the
    only non-destructive answer and it is what every other client does.
    """
    out: dict[str | None, timedelta] = {}
    for comp in cal.walk("VEVENT"):
        dur = comp.get("DURATION")
        if dur is None or comp.get("DTEND") is not None:
            continue
        rid = comp.get("RECURRENCE-ID")
        # The WIRE text, not `to_ical()`. icalendar parses a DURATION into a
        # normalized `timedelta`, so `PT24H` comes back out as `P1D` — and this
        # function's entire job is to tell those two apart. Reading the
        # re-serialization here classified every exact duration of a day or more
        # as nominal and left the instance unrepaired.
        key = str(rid.to_ical().decode()) if rid is not None else None
        # `or` on the PARSE, not on the string: an unparseable wire value must
        # fall back to the library's reading rather than disable the repair.
        parts = split_duration(wire.get(key)) or split_duration(dur.to_ical())
        if parts is None:
            continue
        nominal, exact = parts
        if nominal or not exact:
            continue                      # nominal in whole or in part: wall clock
        out[_iso(rid)[0] if rid is not None else None] = exact
    return out


def _same_shape(a, b) -> bool:
    """Can `a - b` be taken at all?

    Two guards, not one. Mismatched DATENESS (a DATE beside a DATE-TIME) was
    already handled; mismatched AWARENESS was not, and both values are
    `datetime` in that case so the dateness check passes and the subtraction
    raises `TypeError: can't subtract offset-naive and offset-aware datetimes`.
    That runs before any expansion, so it escapes `expand_occurrences` — which
    documents itself as raising ValueError — and `events_in_range` falls into
    its `except Exception` branch: the whole series collapses to a single master
    row and every occurrence disappears from the calendar. Mixed floating/zoned
    values in one component are exactly the hostile-shaped ICS the trust model
    calls out. Skipping just means the dedup fallback gives each covered
    instance its own start as an anchor, which is the intended degradation."""
    if isinstance(a, datetime) != isinstance(b, datetime):
        return False
    if isinstance(a, datetime) and (a.tzinfo is None) != (b.tzinfo is None):
        return False
    return True


def _per_day(rule) -> float:
    """Upper bound on the instances one day of ``rule`` can yield.

    BY* parts multiply a coarse FREQ — RFC 5545 lets ``FREQ=DAILY`` with
    BYHOUR/BYMINUTE/BYSECOND reach 86400 instances a day without the FREQ itself
    ever looking sub-daily. Where a BY* part *restricts* rather than expands (
    BYSECOND under FREQ=SECONDLY) this overestimates, which is the safe
    direction: it only ever declines to expand something.
    """
    freq = str((rule.get("FREQ") or ["DAILY"])[0]).upper()
    per_day = _FREQ_PER_DAY.get(freq, 1)
    for part in ("BYHOUR", "BYMINUTE", "BYSECOND"):
        vals = rule.get(part)
        if vals:
            per_day *= len(vals if isinstance(vals, list) else [vals])
    return per_day


def _instances_before(rule, dtstart, window_end: date | datetime | None) -> float:
    """Roughly how many instances the library must step through to reach
    ``window_end``. ``query.between`` pays for the whole DTSTART -> window skip
    before it yields anything, so this — not the window width — is the real cost.
    Returns 0 when it cannot be judged (no DTSTART, or no window supplied)."""
    if window_end is None or dtstart is None:
        return 0.0
    start = getattr(dtstart, "dt", dtstart)
    end = window_end
    # Compare like with like: dates and datetimes, aware and naive.
    if isinstance(start, datetime) != isinstance(end, datetime):
        start = start.date() if isinstance(start, datetime) else start
        end = end.date() if isinstance(end, datetime) else end
    if isinstance(start, datetime) and isinstance(end, datetime):
        if (start.tzinfo is None) != (end.tzinfo is None):
            start = start.replace(tzinfo=None)
            end = end.replace(tzinfo=None)
    try:
        days = (end - start).total_seconds() / 86400 if isinstance(start, datetime) else (end - start).days
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, days) * _per_day(rule)


def _rdate_count(comp, window_start, window_end) -> int:
    """How many instants this component's RDATE properties name INSIDE the window.

    Restricted to the window, and that restriction is the whole correctness of
    the guard below. Counting the LIFETIME list and pricing it against
    `_occurrence_cap` — which is a per-WINDOW bound — refuses an ordinary
    resource: "every weekday for three years" is 780 RDATE instants, which any
    client can write, and it was refused for every window including ones holding
    none of them. On the calendar that collapses the resource to its master row;
    on the booking path `blocking=True` marks the owner busy for the entire query
    window, so one such resource zeroes out their public availability. That is a
    worse outcome than the flood this guard exists to stop.

    Counting is cheap and expansion is not — the values are already parsed by
    `Calendar.from_ical`, so this is comparisons, while `query.between`
    materialises every component. A value that cannot be read is COUNTED rather
    than skipped: the guard must not be silently disarmed by input it cannot
    price.
    """
    rdates = comp.get("RDATE")
    if rdates is None:
        return 0
    lo, hi = _as_datetime(window_start), _as_datetime(window_end)
    total = 0
    for prop in (rdates if isinstance(rdates, list) else [rdates]):
        # `dts` is icalendar's parsed list for one RDATE line; a property it
        # could not parse has none, and counts as the single line it is.
        dts = getattr(prop, "dts", None)
        if not dts:
            total += 1
            continue
        for entry in dts:
            value = getattr(entry, "dt", entry)
            if isinstance(value, tuple):        # VALUE=PERIOD -> (start, end|dur)
                value = value[0]
            try:
                when = _as_datetime(value)
            except (TypeError, ValueError):
                total += 1
                continue
            if lo <= when < hi:
                total += 1
    return total


def _pathological_rule(
    cal: Calendar,
    window_end: date | datetime | None = None,
    occurrence_cap: int | None = None,
    window_start: date | datetime | None = None,
) -> str | None:
    """Why this resource must not be expanded, or None if it is safe.

    Both shapes below are writable through Radicale by any client sharing the
    collection, and both are reachable unauthenticated: ``GET
    /api/public/booking/{token}`` → ``public_link_info`` → ``_link_busy`` →
    ``events_in_range``, with ``_link_busy`` holding the service lock for the
    duration — so one poisoned resource stalls every request in the process.

    Neither can be caught after the fact. The occurrence cap bounds how many
    results are *kept*, not the work done to find them: a dense rule whose
    DTSTART precedes the window spends its time inside the library before it
    yields anything, and ``query.between`` materializes the whole expansion
    before the cap is consulted (measured: FREQ=DAILY at 3600/day over a 42-day
    grid took 13.9 s and 354 MB; FREQ=SECONDLY from a 2020 DTSTART did not
    finish). So the decision has to be made up front, from the rule's shape.

    Declining means the caller shows the master row — the same degradation it
    already applies to a resource it cannot parse.
    """
    for comp in cal.walk("VEVENT"):
        # RDATE first, and OUTSIDE the RRULE arm below. This function used to
        # judge RRULE shapes only — `continue` when there was none — so a
        # recurrence set built from RDATE alone, or an ordinary rule beside a
        # huge RDATE, was never priced at all. The occurrence cap does not save
        # it, for the reason stated above: `query.between` materializes the whole
        # expansion before the cap is consulted, so the CPU and the memory are
        # spent in full and only then is the answer thrown away. Measured on one
        # 664 KiB resource: 3.2 s and ~70 MB, inside the service lock, on an
        # unauthenticated `GET /api/public/booking/{token}` — and the public
        # limiter's 120 requests / 300 s is far more than enough to keep the lock
        # held continuously with a single planted resource.
        #
        # An RDATE list is its own occurrence count, so unlike a rule it needs no
        # estimate: it is refused when it alone cannot fit the window's cap.
        if occurrence_cap is not None and window_start is not None and window_end is not None:
            count = _rdate_count(comp, window_start, window_end)
            if count > occurrence_cap:
                return (
                    f"RDATE names {count} instants inside this window, more than "
                    f"the {occurrence_cap} occurrences it can hold"
                )
        rrules = comp.get("RRULE")
        if rrules is None:
            continue
        for r in rrules if isinstance(rrules, list) else [rrules]:
            # RFC 5545 §3.3.10 requires a positive INTERVAL, but Radicale accepts
            # INTERVAL=0 — and expanding it never terminates at all, since the
            # rule advances by nothing.
            for iv in r.get("INTERVAL") or []:
                try:
                    if int(iv) < 1:
                        return f"RRULE INTERVAL must be a positive integer, got {iv!r}"
                except (TypeError, ValueError):
                    return f"unparseable RRULE INTERVAL {iv!r}"
            per_day = _per_day(r)
            if per_day > _MAX_PER_DAY:
                return f"RRULE yields up to {per_day:g} instances/day (limit {_MAX_PER_DAY})"
            # Density alone is not the cost. A rule inside the allowed 1..24/day
            # band whose DTSTART is decades before the window still makes the
            # library step through every instance in between before it yields
            # anything, and that skip is paid in full even for a one-day query:
            # measured, FREQ=HOURLY from a year-0001 DTSTART burned 72 s and
            # 1.3 GB to return 24 occurrences. _link_busy holds the service lock
            # across this for every collection, and both public booking routes
            # reach it, so bound the total walk as well as its density.
            total = _instances_before(r, comp.get("DTSTART"), window_end)
            if total > _MAX_TOTAL_INSTANCES:
                return (
                    f"RRULE would step through ~{total:.0f} instances to reach the "
                    f"window (limit {_MAX_TOTAL_INSTANCES})"
                )
    return None


def _repair_span(start_iso: str | None, end_iso: str | None,
                 exact: timedelta | None = None) -> str | None:
    """The instance end, when the library emitted one that precedes its start.

    `recurring_ical_events` derives each instance's end by wall-clock arithmetic
    on that instance's DTSTART. When the instance's local start falls inside the
    hour the clock SKIPS, the two ends resolve with different offsets and the
    emitted occurrence runs BACKWARDS:

        2026-03-08T02:30:00-06:00 -> 2026-03-08T03:00:00-05:00     -30 minutes

    `busy_intervals` discards any interval that is not strictly positive, so the
    owner's recurring 02:30 commitment stopped blocking bookings on that one day
    and the public page handed the time to an anonymous visitor. The SPA rendered
    it "3:30 AM - 3:00 AM".

    …and one more, when the governing component authored an EXACT length (see
    `_exact_durations`) AND the emitted pair still states that length in wall
    clock: a `DURATION:PT30M` instance owes thirty minutes of real time, and on
    the fall-back day the library emits a pair that reads thirty and spans
    ninety. That over-blocks
    rather than under-blocks, so it withholds availability rather than allowing a
    double-booking — the milder direction, which is why it was left open when
    this function was first narrowed rather than fixed in a hurry.

    NOT every span whose exact duration disagrees with its wall-clock one. The
    first version of this repaired all of them, on the reasoning that the stated
    span is a wall-clock quantity — and that is wrong in a way that costs exactly
    what it was meant to save. RFC 5545 §3.8.5.3 says a DTEND-authored
    recurrence carries the same EXACT duration to every instance, and for the
    master's own occurrence the DTSTART/DTEND the library emits are the bytes the
    author wrote, correct by construction. Repairing those turned an overnight
    22:00->06:00 shift across the fall-back night from the 9 real hours it
    occupies into 8, and released the last hour to the booking page.

    So the remaining disagreement — an instance spanning a transition being an
    hour LONGER than the master's — is left alone. It blocks more time than it
    occupies, which withholds availability rather than double-booking, and that
    is the direction to err in on this path. It is filed as its own finding
    rather than papered over here.

    The end is rebuilt in the START's zone, which is a fixed offset recovered
    from an ISO string. That is exact as an instant, which is what every consumer
    of this value compares on; the wall-clock rendering of the repaired end can
    name the pre-transition offset.
    """
    if start_iso is None or end_iso is None:
        return end_iso
    try:
        start, end = datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso)
    except ValueError:
        return end_iso
    if start.tzinfo is None or end.tzinfo is None:
        return end_iso                     # floating: no offset to disagree about
    if end.astimezone(timezone.utc) <= start.astimezone(timezone.utc):
        wall = end.replace(tzinfo=None) - start.replace(tzinfo=None)
        if wall <= timedelta(0):
            return end_iso                 # authored as zero/negative; not an artifact
        return (start.astimezone(timezone.utc) + wall).astimezone(
            start.tzinfo).isoformat()

    # Forward-going, so nothing above applies — but if the governing component
    # authored an EXACT length, every instance owes exactly that much real time
    # and the library's wall-clock arithmetic does not deliver it across a
    # transition. `exact` is None for a DTEND-authored component, which is the
    # case that must be left alone.
    if exact is None:
        return end_iso
    if end.astimezone(timezone.utc) - start.astimezone(timezone.utc) == exact:
        return end_iso                     # already the authored length
    # The DST artifact has a signature: the emitted pair states the authored
    # length in WALL CLOCK and delivers something else in real time. Anything
    # whose wall-clock span is a different length came from somewhere else, and
    # rewriting it destroys an authored value.
    #
    # This guard is not belt-and-braces. Without it an `RDATE;VALUE=PERIOD` block
    # — whose length the library takes from the period, not the master — was
    # truncated to the master's DURATION: a four-hour commitment reported as
    # thirty minutes, on an ordinary January day with no transition anywhere near
    # it, releasing three and a half hours to the public booking page. Which is
    # the failure this whole function was narrowed to prevent, arriving through a
    # different door. Failing closed on every family not enumerated is the point.
    if end.replace(tzinfo=None) - start.replace(tzinfo=None) != exact:
        return end_iso
    return (start.astimezone(timezone.utc) + exact).astimezone(
        start.tzinfo).isoformat()


def _occurrence(comp, override_anchors: set[str], tf_shifts: dict[str, timedelta],
                exact_durations: dict[str | None, timedelta] | None = None) -> Occurrence:
    start, start_is_date = _iso(comp.get("DTSTART"))
    end, end_is_date = _end_fields(comp)
    rid = comp.get("RECURRENCE-ID")
    rid_iso = _iso(rid)[0] if rid is not None else None
    if not start_is_date and not end_is_date:
        # WHICH component authored this instance's length. Not simply
        # `.get(rid_iso)`: `recurring_ical_events` stamps a RECURRENCE-ID on every
        # instance it emits, including the ones a plain series generates, so the
        # emitted value says nothing on its own about whether an override is in
        # play. `override_anchors` is the set of rids an AUTHORED override
        # carries — so a hit means the governing component is that override (a
        # RANGE=THISANDFUTURE one stamps its own rid on every instance it covers,
        # which is exactly the case that must not read the master's length), and
        # a miss means the master governs. An override that authored a DTEND is
        # absent from the map and correctly yields None rather than falling back
        # to a length it does not have.
        durations = exact_durations or {}
        governing = rid_iso if rid_iso in override_anchors else None
        end = _repair_span(start, end, durations.get(governing))
    anchor = rid_iso or start or ""
    is_override = bool(anchor) and rid_iso in override_anchors
    shift = tf_shifts.get(rid_iso) if rid_iso is not None else None
    if shift is not None and comp.get("DTSTART") is not None:
        # A RANGE=THISANDFUTURE override stamps its own RECURRENCE-ID on every
        # instance it covers. Undoing the offset it applied recovers the rule
        # slot *this* instance stands for — the anchor the master's RRULE
        # actually generates, so it is both unique per instance and the value an
        # EXDATE or a new override has to carry to address it. (For the override's
        # own slot this reproduces the RECURRENCE-ID exactly.)
        recovered = _iso(comp.get("DTSTART").dt - shift)[0]
        if recovered is not None:
            anchor = recovered
    return Occurrence(
        start=start,
        start_is_date=start_is_date,
        end=end,
        end_is_date=end_is_date,
        recurrence_id=anchor,
        is_override=is_override,
        summary=_text(comp, "SUMMARY"),
        description=_text(comp, "DESCRIPTION"),
        location=_text(comp, "LOCATION"),
        status=_text(comp, "STATUS"),
        transp=_text(comp, "TRANSP"),
    )


def _occurrence_cap(
    window_start: date | datetime, window_end: date | datetime, floor: int = 750
) -> int:
    """How many occurrences a window can legitimately hold.

    A flat constant was wrong in both directions. `_pathological_rule` refuses
    anything over `_MAX_PER_DAY` (24) instances a day and *permits* everything
    under it, so a rule the guard explicitly allows could still overrun a fixed
    750 — an hourly series passes the density check and produces 1032 over the
    calendar's 43-day grid. The window is what decides how many there can be, so
    the bound is derived from it.

    The floor keeps short windows from getting a cap tighter than the old one.
    """
    start = _as_datetime(window_start)
    end = _as_datetime(window_end)
    days = max(1, ceil((end - start).total_seconds() / 86400))
    # +1 day of slack: the query is inclusive at the edges and an override or an
    # RDATE can add an instance the rule itself did not generate.
    return max(floor, int(_MAX_PER_DAY * (days + 1)))


def _as_datetime(v: date | datetime) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    return datetime.combine(v, dtime.min)


def expand_occurrences(
    raw_ics: bytes | str,
    window_start: date | datetime,
    window_end: date | datetime,
    *,
    max_occurrences: int | None = None,
) -> list[Occurrence]:
    """Occurrences of the resource's VEVENT series within ``[window_start,
    window_end)``, most-relevant first. Returns ``[]`` when the series produces
    nothing in the window (e.g. a rule whose UNTIL is already past).

    Raises ``ValueError`` for a rule too dense or too malformed to expand within
    a bounded cost, and for one that overruns the window's occurrence cap — the
    caller degrades to the master row.

    Overrunning used to return a silently short list instead, with no signal the
    caller could tell apart from "the series really ends here". Two things went
    wrong with that. The calendar grid rendered the tail of its month empty with
    nothing to say anything was hidden; worse, `_link_busy` builds the public
    booking page's conflict set from this, so a busy series past the cap stopped
    blocking and the page advertised — and let an anonymous visitor book — hours
    the owner was already in a meeting. Raising puts both on the existing
    degrade-to-master-row path, which is visible."""
    cap = (max_occurrences if max_occurrences is not None
           else _occurrence_cap(window_start, window_end))
    cal = Calendar.from_ical(raw_ics)
    why = _pathological_rule(cal, window_end, occurrence_cap=cap,
                             window_start=window_start)
    if why is not None:
        raise ValueError(f"refusing to expand recurrence: {why}")
    override_anchors = _override_anchors(cal)
    tf_shifts = _thisandfuture_shifts(cal)
    exact_durations = _exact_durations(cal, wire_durations(raw_ics))
    query = recurring_ical_events.of(cal, components=["VEVENT"])
    try:
        with search_budget(_MAX_SEARCH_STEPS):
            comps = query.between(window_start, window_end)
    except SearchBudgetExceeded as e:
        # Into the vocabulary this function already raises, so every caller
        # degrades the way it already does for a too-dense rule: the calendar
        # shows the master row, and `_link_busy` treats the series as an opaque
        # busy span. Blocking the window rather than freeing it is the safe
        # direction on the booking path.
        raise ValueError(
            f"refusing to expand recurrence: the rule searched past "
            f"{_MAX_SEARCH_STEPS} periods without producing an occurrence"
        ) from e

    out: list[Occurrence] = []
    seen: set[str] = set()
    for comp in comps:
        if str(comp.get("STATUS") or "").upper() == "CANCELLED":
            continue
        occ = _occurrence(comp, override_anchors, tf_shifts, exact_durations)
        if occ.recurrence_id in seen:
            # The anchor keys the UI row and addresses the instance for a
            # per-occurrence edit or delete, so a duplicate is not cosmetic: two
            # rows would share a React key, and acting on one would write to the
            # other. `_occurrence` resolves the shape that causes this, but a
            # resource can always be malformed in a way it cannot — fall back to
            # the instance's own start rather than emit a collision.
            occ = replace(occ, recurrence_id=occ.start or occ.recurrence_id)
        seen.add(occ.recurrence_id)
        out.append(occ)
        if len(out) > cap:
            raise ValueError(
                f"refusing to expand recurrence: more than {cap} occurrences in the window"
            )
    return out
