"""Write path.

`apply_changes` is the embodiment of invariant #2: GET the raw resource, parse it
with `icalendar` (which retains everything foreign clients wrote), mutate ONLY the
fields the user changed, re-serialize, and hand the bytes to a PUT with If-Match.
It never rebuilds the component from our SQL model, so `X-APPLE-SORT-ORDER`,
`X-MOZ-*`, foreign VALARMs, RECURRENCE-ID overrides, etc. all survive.

`apply_changes` is a pure function of (raw, edit) — which is exactly what the 412
merge path needs: on a precondition failure, re-GET and re-apply the same field
intent to the fresh copy (invariant #5).

`build_new` creates a brand-new task. Creating from scratch is fine — invariant #2
constrains *editing* existing resources, not authoring new ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from icalendar import Calendar, Event, Todo

# Sentinel: a field left UNSET is not touched; None means "clear this property".
UNSET: Any = object()

_PRODID = "-//tasksd//Task Manager//EN"

# Our four-level priority vocabulary -> RFC 5545 PRIORITY (spec §5).
PRIORITY = {"none": 0, "low": 9, "medium": 5, "high": 1}


@dataclass
class TaskEdit:
    summary: Any = UNSET
    description: Any = UNSET
    priority: Any = UNSET              # int 0-9 or None
    status: Any = UNSET               # NEEDS-ACTION/IN-PROCESS/COMPLETED/CANCELLED or None
    due: Any = UNSET                  # date | datetime | None
    dtstart: Any = UNSET              # date | datetime | None
    categories: Any = UNSET           # list[str] | None
    percent_complete: Any = UNSET     # int | None


@dataclass
class EventEdit:
    summary: Any = UNSET
    description: Any = UNSET
    dtstart: Any = UNSET              # date | datetime
    dtend: Any = UNSET               # date | datetime | None
    location: Any = UNSET
    categories: Any = UNSET           # list[str] | None
    status: Any = UNSET               # CONFIRMED/TENTATIVE/CANCELLED or None


def _replace(todo: Todo, key: str) -> None:
    if key in todo:
        del todo[key]


def _set_text(todo: Todo, key: str, value: str | None) -> None:
    _replace(todo, key)
    if value:
        todo.add(key, value)


def _set_int(todo: Todo, key: str, value: int | None) -> None:
    _replace(todo, key)
    if value is not None:
        todo.add(key, int(value))


def _set_datelike(todo: Todo, key: str, value: date | datetime | None) -> None:
    _replace(todo, key)
    if value is not None:
        # icalendar emits VALUE=DATE for a date and DATE-TIME for a datetime (spec §5).
        todo.add(key, value)


def _set_categories(todo: Todo, cats: list[str] | None) -> None:
    _replace(todo, "CATEGORIES")
    if cats:
        todo.add("CATEGORIES", list(cats))


def _set_status(todo: Todo, status: str | None, now: datetime) -> None:
    _replace(todo, "STATUS")
    if not status:
        return
    status = status.upper()
    todo.add("STATUS", status)
    if status == "COMPLETED":
        # Completion is a coupled write (spec §5): STATUS + COMPLETED + 100%.
        _replace(todo, "COMPLETED")
        todo.add("COMPLETED", now)
        _set_int(todo, "PERCENT-COMPLETE", 100)
    else:
        _replace(todo, "COMPLETED")            # reopening clears the completion stamp
        if status == "NEEDS-ACTION":
            _set_int(todo, "PERCENT-COMPLETE", 0)


def apply_changes(raw: bytes | str, edit: TaskEdit, *, now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    todo = None
    for comp in cal.walk("VTODO"):
        todo = comp
        break
    if todo is None:
        raise ValueError("resource has no VTODO to edit")

    if edit.summary is not UNSET:
        _set_text(todo, "SUMMARY", edit.summary)
    if edit.description is not UNSET:
        _set_text(todo, "DESCRIPTION", edit.description)
    if edit.priority is not UNSET:
        _set_int(todo, "PRIORITY", edit.priority)
    if edit.categories is not UNSET:
        _set_categories(todo, edit.categories)
    if edit.due is not UNSET:
        _set_datelike(todo, "DUE", edit.due)
    if edit.dtstart is not UNSET:
        _set_datelike(todo, "DTSTART", edit.dtstart)
    if edit.percent_complete is not UNSET:
        _set_int(todo, "PERCENT-COMPLETE", edit.percent_complete)
    if edit.status is not UNSET:
        _set_status(todo, edit.status, now)

    # Every edit stamps modification metadata and bumps the sequence.
    _replace(todo, "LAST-MODIFIED")
    todo.add("LAST-MODIFIED", now)
    _replace(todo, "DTSTAMP")
    todo.add("DTSTAMP", now)
    _set_int(todo, "SEQUENCE", int(todo.get("SEQUENCE", 0)) + 1)

    return cal.to_ical()


def build_new(
    uid: str,
    *,
    summary: str,
    edit: TaskEdit | None = None,
    related_parent: str | None = None,
    now: datetime | None = None,
) -> bytes:
    """Author a fresh VTODO resource. Not governed by invariant #2 (nothing
    foreign exists yet). Subtasks pass ``related_parent`` (RELTYPE=PARENT)."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar()
    cal.add("PRODID", _PRODID)
    cal.add("VERSION", "2.0")
    todo = Todo()
    todo.add("UID", uid)
    todo.add("DTSTAMP", now)
    todo.add("CREATED", now)
    todo.add("LAST-MODIFIED", now)
    todo.add("SEQUENCE", 0)
    todo.add("SUMMARY", summary)
    todo.add("STATUS", "NEEDS-ACTION")
    if related_parent:
        todo.add("RELATED-TO", related_parent, parameters={"RELTYPE": "PARENT"})
    cal.add_component(todo)
    if edit is not None:
        return apply_changes(cal.to_ical(), edit, now=now)
    return cal.to_ical()


# ── VEVENT (calendar events) — same invariant-#2 discipline ───────────────────

def apply_event_changes(raw: bytes | str, edit: EventEdit, *, now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    event = None
    for comp in cal.walk("VEVENT"):
        event = comp
        break
    if event is None:
        raise ValueError("resource has no VEVENT to edit")

    if edit.summary is not UNSET:
        _set_text(event, "SUMMARY", edit.summary)
    if edit.description is not UNSET:
        _set_text(event, "DESCRIPTION", edit.description)
    if edit.location is not UNSET:
        _set_text(event, "LOCATION", edit.location)
    if edit.dtstart is not UNSET and edit.dtstart is not None:
        _set_datelike(event, "DTSTART", edit.dtstart)
    if edit.dtend is not UNSET:
        _replace(event, "DURATION")            # DTEND and DURATION are exclusive
        _set_datelike(event, "DTEND", edit.dtend)
    if edit.categories is not UNSET:
        _set_categories(event, edit.categories)
    if edit.status is not UNSET:
        _replace(event, "STATUS")
        if edit.status:
            event.add("STATUS", edit.status.upper())

    _replace(event, "LAST-MODIFIED")
    event.add("LAST-MODIFIED", now)
    _replace(event, "DTSTAMP")
    event.add("DTSTAMP", now)
    _set_int(event, "SEQUENCE", int(event.get("SEQUENCE", 0)) + 1)
    return cal.to_ical()


def build_new_event(
    uid: str,
    *,
    summary: str,
    dtstart: date | datetime,
    dtend: date | datetime | None = None,
    edit: EventEdit | None = None,
    now: datetime | None = None,
) -> bytes:
    now = now or datetime.now(timezone.utc)
    cal = Calendar()
    cal.add("PRODID", _PRODID)
    cal.add("VERSION", "2.0")
    event = Event()
    event.add("UID", uid)
    event.add("DTSTAMP", now)
    event.add("CREATED", now)
    event.add("LAST-MODIFIED", now)
    event.add("SEQUENCE", 0)
    event.add("SUMMARY", summary)
    event.add("DTSTART", dtstart)
    if dtend is not None:
        event.add("DTEND", dtend)
    cal.add_component(event)
    if edit is not None:
        return apply_event_changes(cal.to_ical(), edit, now=now)
    return cal.to_ical()
