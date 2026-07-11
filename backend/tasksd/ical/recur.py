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
and refuse to enumerate a pathological sub-daily RRULE.
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import date, datetime

import recurring_ical_events
from icalendar import Calendar

from .read import _iso, _text

log = logging.getLogger("tasksd.recur")

# Sub-daily frequencies enumerate enormous instance counts over a month window
# (FREQ=SECONDLY across 42 days is millions). We never expand these eagerly.
_EXPLOSIVE_FREQ = {"SECONDLY", "MINUTELY"}


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


def _has_explosive_freq(cal: Calendar) -> bool:
    for comp in cal.walk("VEVENT"):
        rrules = comp.get("RRULE")
        if rrules is None:
            continue
        for r in rrules if isinstance(rrules, list) else [rrules]:
            for f in r.get("FREQ") or []:
                if str(f).upper() in _EXPLOSIVE_FREQ:
                    return True
    return False


def _occurrence(comp, override_anchors: set[str]) -> Occurrence:
    start, start_is_date = _iso(comp.get("DTSTART"))
    end, end_is_date = _end_fields(comp)
    rid = comp.get("RECURRENCE-ID")
    anchor = (_iso(rid)[0] if rid is not None else start) or start or ""
    return Occurrence(
        start=start,
        start_is_date=start_is_date,
        end=end,
        end_is_date=end_is_date,
        recurrence_id=anchor,
        is_override=bool(anchor) and anchor in override_anchors,
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
    nothing in the window (e.g. a rule whose UNTIL is already past)."""
    cal = Calendar.from_ical(raw_ics)
    override_anchors = _override_anchors(cal)
    query = recurring_ical_events.of(cal, components=["VEVENT"])

    if _has_explosive_freq(cal):
        # Bounded, lazy prefix from the window start — the event still shows
        # without the server enumerating millions of sub-daily instances.
        comps = list(itertools.islice(query.after(window_start), max_occurrences))
        log.warning("recurrence: sub-daily RRULE capped at %d occurrences", max_occurrences)
    else:
        comps = query.between(window_start, window_end)

    out: list[Occurrence] = []
    for comp in comps:
        if str(comp.get("STATUS") or "").upper() == "CANCELLED":
            continue
        out.append(_occurrence(comp, override_anchors))
        if len(out) >= max_occurrences:
            break
    return out
