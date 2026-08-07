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
from datetime import date, datetime, timedelta

import recurring_ical_events
from icalendar import Calendar

from .read import _iso, _text

log = logging.getLogger("tasksd.recur")

# Instances one day of a rule may yield before we call it pathological and
# decline to expand it. Hourly (24) is the densest shape a person plausibly puts
# on a calendar; past that the cost is unbounded in practice, so the resource
# renders as its master row instead (see _pathological_rule).
_MAX_PER_DAY = 24

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


def _end_fields(comp) -> tuple[str | None, bool]:
    """(iso, is_date) for the instance end: DTEND if present, else DTSTART+DURATION."""
    dtend = comp.get("DTEND")
    if dtend is not None:
        return _iso(dtend)
    dtstart, dur = comp.get("DTSTART"), comp.get("DURATION")
    if dtstart is not None and dur is not None:
        return _iso(dtstart.dt + dur.dt)
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
        if iso is None or isinstance(rid.dt, datetime) != isinstance(dtstart.dt, datetime):
            continue                      # mismatched dateness: no meaningful offset
        out[iso] = dtstart.dt - rid.dt
    return out


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


def _pathological_rule(cal: Calendar) -> str | None:
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
    return None


def _occurrence(comp, override_anchors: set[str], tf_shifts: dict[str, timedelta]) -> Occurrence:
    start, start_is_date = _iso(comp.get("DTSTART"))
    end, end_is_date = _end_fields(comp)
    rid = comp.get("RECURRENCE-ID")
    rid_iso = _iso(rid)[0] if rid is not None else None
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
    )


def expand_occurrences(
    raw_ics: bytes | str,
    window_start: date | datetime,
    window_end: date | datetime,
    *,
    max_occurrences: int = 750,
) -> list[Occurrence]:
    """Occurrences of the resource's VEVENT series within ``[window_start,
    window_end)``, most-relevant first. Returns ``[]`` when the series produces
    nothing in the window (e.g. a rule whose UNTIL is already past).

    Raises ``ValueError`` for a rule too dense or too malformed to expand within
    a bounded cost — the caller degrades to the master row."""
    cal = Calendar.from_ical(raw_ics)
    why = _pathological_rule(cal)
    if why is not None:
        raise ValueError(f"refusing to expand recurrence: {why}")
    override_anchors = _override_anchors(cal)
    tf_shifts = _thisandfuture_shifts(cal)
    query = recurring_ical_events.of(cal, components=["VEVENT"])
    comps = query.between(window_start, window_end)

    out: list[Occurrence] = []
    seen: set[str] = set()
    for comp in comps:
        if str(comp.get("STATUS") or "").upper() == "CANCELLED":
            continue
        occ = _occurrence(comp, override_anchors, tf_shifts)
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
        if len(out) >= max_occurrences:
            break
    return out
