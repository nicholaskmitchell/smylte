"""The `.ics` fast path: an invitation already says what, when and where.

A calendar part attached to a message is structured data written by a calendar
program, so reading it needs no model: it is cheaper, exact about times and
time zones, and cannot be talked into anything. `parse_ics` turns it into
`EventProposal`s the pipeline stages as event suggestions.

What is deliberately NOT proposed:

- `METHOD:CANCEL` — a cancellation is about an event the owner may already have
  in a calendar; there is nothing to add, and adding it would be wrong.
- an event with `RECURRENCE-ID` — that is one changed occurrence of a series
  the invitation set up earlier, not a new event.
- `STATUS:CANCELLED` — same reason as the method.
- an event with no `DTSTART`, which has no time to put in a calendar.

Everything is capped (`MAX_EVENTS`, field lengths) because the data comes from
whoever sent the mail. A part that does not parse gives an empty list, never an
exception: a malformed attachment must not stop the message being read as
ordinary mail. The parser's error text is not logged — it can quote the
content — only the exception type.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

import icalendar

log = logging.getLogger("smylted.mail")

MAX_EVENTS = 5
MAX_SUMMARY = 300
MAX_LOCATION = 300
MAX_DESCRIPTION = 2000


@dataclass(frozen=True)
class EventProposal:
    uid: str | None
    summary: str
    start: date | datetime
    end: date | datetime | None
    all_day: bool
    location: str
    description: str
    rrule: str | None           # RRULE value text, e.g. "FREQ=WEEKLY;BYDAY=MO"
    method: str | None          # calendar METHOD upper-cased, e.g. "REQUEST", "PUBLISH"
    sequence: int


def _text(comp, name: str, limit: int) -> str:
    value = comp.get(name)
    return str(value).strip()[:limit] if value is not None else ""


def _proposal(comp, method: str | None) -> EventProposal | None:
    if "RECURRENCE-ID" in comp:
        return None
    if _text(comp, "STATUS", 40).upper() == "CANCELLED":
        return None
    if comp.get("DTSTART") is None:
        return None
    start = comp.decoded("DTSTART")
    if not isinstance(start, date):         # a value icalendar could not read as a date
        return None
    all_day = isinstance(start, date) and not isinstance(start, datetime)
    end = None
    if comp.get("DTEND") is not None:
        end = comp.decoded("DTEND")
    elif comp.get("DURATION") is not None:
        end = start + comp.decoded("DURATION")
    if end is not None and not isinstance(end, date):
        end = None
    try:
        sequence = int(comp.get("SEQUENCE", 0))
    except (TypeError, ValueError):
        sequence = 0
    rrule = comp.get("RRULE")
    uid = _text(comp, "UID", 255)
    return EventProposal(
        uid=uid or None,
        summary=_text(comp, "SUMMARY", MAX_SUMMARY) or "(no title)",
        start=start,
        end=end,
        all_day=all_day,
        location=_text(comp, "LOCATION", MAX_LOCATION),
        description=_text(comp, "DESCRIPTION", MAX_DESCRIPTION),
        rrule=rrule.to_ical().decode() if rrule is not None else None,
        method=method,
        sequence=sequence,
    )


def parse_ics(data: bytes, *, max_events: int = MAX_EVENTS) -> list[EventProposal]:
    """The events an iCalendar attachment proposes, at most `max_events`."""
    try:
        cal = icalendar.Calendar.from_ical(data)
        raw_method = cal.get("METHOD")
        method = str(raw_method).strip().upper() if raw_method is not None else None
        if method == "CANCEL":
            return []
        events = list(cal.walk("VEVENT"))
    except Exception as exc:
        log.debug("mail: calendar part could not be parsed (%s)", type(exc).__name__)
        return []
    out: list[EventProposal] = []
    for comp in events:
        if len(out) >= max_events:
            break
        try:
            proposal = _proposal(comp, method)
        except Exception as exc:
            log.debug("mail: a calendar event could not be read (%s)", type(exc).__name__)
            continue
        if proposal is not None:
            out.append(proposal)
    return out
