"""The `.ics` fast path: an invitation already says what, when and where.

A calendar part attached to a message is structured data written by a calendar
program, so reading it needs no model: it is cheaper, exact about times and
time zones, and cannot be talked into anything. `parse_ics` turns it into
`EventProposal`s the pipeline stages as event suggestions.

What is deliberately NOT proposed:

- any `METHOD` other than `PUBLISH`, `REQUEST` or `ADD` (or none at all).
  `CANCEL` is about an event the owner may already have in a calendar; there
  is nothing to add, and adding it would be wrong. `REPLY`, `COUNTER`,
  `DECLINECOUNTER` and `REFRESH` are an attendee answering an invitation the
  owner sent: they carry the owner's own event back, not a new one. An
  allowlist rather than a list of refusals, so a method nobody has seen yet
  is not proposed either.
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
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import icalendar

log = logging.getLogger("smylted.mail")

MAX_EVENTS = 5
MAX_SUMMARY = 300
MAX_LOCATION = 300
MAX_DESCRIPTION = 2000

_PROPOSING_METHODS = frozenset({"PUBLISH", "REQUEST", "ADD"})


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


def _own_tz(value, prop) -> date | datetime:
    """`value` with a tzinfo this process owns, never the sender's.

    For a TZID it does not know, icalendar builds a tzinfo from the VTIMEZONE
    the sender put in the calendar, and that tzinfo computes offsets by
    expanding the sender's RRULEs. A VTIMEZONE with `FREQ=SECONDLY` from 1601
    makes one `utcoffset()` call — which `isoformat()`, comparison and
    `astimezone` all make — run for centuries. So the foreign tzinfo is never
    asked anything: the TZID is looked up in the system zone database, and
    `replace()` swaps it in without consulting the old one. A TZID the database
    does not have (an Outlook Windows zone name icalendar has no mapping for,
    an invented one) becomes floating time, which approval reads in the
    owner's home zone — right for the usual case of an invitation from someone
    in the same place.
    """
    if not isinstance(value, datetime) or value.tzinfo is None:
        return value
    if value.tzinfo is timezone.utc or isinstance(value.tzinfo, ZoneInfo):
        return value
    tzid = prop.params.get("TZID") if prop is not None and hasattr(prop, "params") else None
    if tzid:
        try:
            return value.replace(tzinfo=ZoneInfo(str(tzid)))
        except Exception:                # not found, or not a valid key at all
            pass
    return value.replace(tzinfo=None)


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
    start = _own_tz(start, comp.get("DTSTART"))
    all_day = isinstance(start, date) and not isinstance(start, datetime)
    end = None
    if comp.get("DTEND") is not None:
        end = _own_tz(comp.decoded("DTEND"), comp.get("DTEND"))
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
        if method is not None and method not in _PROPOSING_METHODS:
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
