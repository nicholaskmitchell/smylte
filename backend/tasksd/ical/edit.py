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

import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from icalendar import Calendar, Event, Todo, vRecur

# Sentinel: a field left UNSET is not touched; None means "clear this property".
UNSET: Any = object()

_PRODID = "-//tasksd//Task Manager//EN"

# Our four-level priority vocabulary -> RFC 5545 PRIORITY (spec §5).
PRIORITY = {"none": 0, "low": 9, "medium": 5, "high": 1}

# Structured repeat vocabulary -> RFC 5545 FREQ.
_FREQ = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}


def rrule_from_spec(
    repeat: str | None,
    *,
    interval: int = 1,
    until: date | datetime | None = None,
    count: int | None = None,
) -> dict | None:
    """Translate the app's structured repeat into an icalendar RRULE value dict,
    or None for "does not repeat" (which clears any existing rule). ``repeat`` is
    none|daily|weekly|monthly|yearly. COUNT and UNTIL are mutually exclusive
    (COUNT wins if both are given)."""
    if not repeat or repeat.lower() == "none":
        return None
    freq = _FREQ.get(repeat.lower())
    if freq is None:
        raise ValueError(f"unknown repeat frequency: {repeat!r}")
    rule: dict = {"FREQ": [freq]}
    if interval and int(interval) > 1:
        rule["INTERVAL"] = [int(interval)]
    if count:
        rule["COUNT"] = [int(count)]
    elif until is not None:
        rule["UNTIL"] = [until]
    return rule


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
    rrule: Any = UNSET               # icalendar RRULE value dict, or None to clear


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

def _find_master_event(cal: Calendar):
    """The series master: the first VEVENT without a RECURRENCE-ID. Overrides
    (which carry one) are never the edit target for series-level changes. Falls
    back to the first VEVENT if every instance is an override (malformed)."""
    events = list(cal.walk("VEVENT"))
    for ev in events:
        if "RECURRENCE-ID" not in ev:
            return ev
    return events[0] if events else None


def _set_rrule(event: Event, rule: dict | None) -> None:
    _replace(event, "RRULE")
    if rule:
        event.add("RRULE", vRecur(rule))


def _stamp(event: Event, now: datetime) -> None:
    """Modification metadata every write bumps."""
    _replace(event, "LAST-MODIFIED")
    event.add("LAST-MODIFIED", now)
    _replace(event, "DTSTAMP")
    event.add("DTSTAMP", now)
    _set_int(event, "SEQUENCE", int(event.get("SEQUENCE", 0)) + 1)


def _apply_event_fields(event: Event, edit: EventEdit, now: datetime) -> None:
    """Apply an EventEdit's field intent to a single VEVENT (master or override)."""
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
    if edit.rrule is not UNSET:
        _set_rrule(event, edit.rrule)
    _stamp(event, now)


def apply_event_changes(raw: bytes | str, edit: EventEdit, *, now: datetime | None = None) -> bytes:
    """Edit the series master (or a plain event) — the "all events" path."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    event = _find_master_event(cal)
    if event is None:
        raise ValueError("resource has no VEVENT to edit")
    _apply_event_fields(event, edit, now)
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


# ── per-occurrence editing (RECURRENCE-ID overrides / EXDATE / split) ──────────

def _anchor_from_iso(recurrence_id: str) -> date | datetime:
    """Parse an occurrence anchor (the ISO the read path emitted) back to a
    date (all-day) or datetime (timed)."""
    s = recurrence_id.strip()
    return datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)


def _as_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt


def _same_instant(a, b) -> bool:
    if isinstance(a, datetime) and isinstance(b, datetime):
        return _as_utc(a) == _as_utc(b)
    if isinstance(a, datetime) or isinstance(b, datetime):
        return False
    return a == b


def _at_or_after(a, anchor) -> bool:
    """True if instant/date `a` is on or after `anchor` (used to split a series)."""
    if isinstance(a, datetime) and isinstance(anchor, datetime):
        return _as_utc(a) >= _as_utc(anchor)
    da = a.date() if isinstance(a, datetime) else a
    db = anchor.date() if isinstance(anchor, datetime) else anchor
    return da >= db


def _event_duration(master: Event):
    ds, de, dur = master.get("DTSTART"), master.get("DTEND"), master.get("DURATION")
    if ds is not None and de is not None:
        return de.dt - ds.dt
    if dur is not None:
        return dur.dt
    return None


def _find_override(cal: Calendar, anchor):
    for ev in cal.walk("VEVENT"):
        rid = ev.get("RECURRENCE-ID")
        if rid is not None and _same_instant(rid.dt, anchor):
            return ev
    return None


def _new_override(master: Event, anchor) -> Event:
    """A fresh override VEVENT for `anchor`: a complete copy of the master with
    the recurrence properties stripped, RECURRENCE-ID set to the original slot,
    and DTSTART/DTEND set to that slot (edits applied by the caller afterwards)."""
    ev = copy.deepcopy(master)
    for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"):
        _replace(ev, key)
    ev.add("RECURRENCE-ID", anchor)
    dur = _event_duration(master)
    _replace(ev, "DTSTART")
    ev.add("DTSTART", anchor)
    _replace(ev, "DURATION")
    _replace(ev, "DTEND")
    if dur is not None:
        ev.add("DTEND", anchor + dur)
    return ev


def apply_occurrence_override(
    raw: bytes | str, recurrence_id: str, edit: EventEdit, *, now: datetime | None = None
) -> bytes:
    """Edit one instance ("this event"). Find-or-create the RECURRENCE-ID override
    for `recurrence_id` and apply the field intent to it; the master rule is left
    untouched, so every other occurrence is unchanged. A never-recurring RRULE is
    never written onto an override."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    master = _find_master_event(cal)
    if master is None:
        raise ValueError("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id)
    override = _find_override(cal, anchor)
    if override is None:
        override = _new_override(master, anchor)
        cal.add_component(override)
    # An override is a single instance; it never carries the series rule.
    _apply_event_fields(override, replace(edit, rrule=UNSET), now)
    return cal.to_ical()


def exclude_occurrence(
    raw: bytes | str, recurrence_id: str, *, now: datetime | None = None
) -> bytes:
    """Delete one instance ("this event"): add EXDATE to the master for the slot
    and drop any override that had moved/edited it."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    master = _find_master_event(cal)
    if master is None:
        raise ValueError("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id)
    master.add("EXDATE", anchor)
    cal.subcomponents = [
        c for c in cal.subcomponents
        if not (
            getattr(c, "name", "") == "VEVENT"
            and c.get("RECURRENCE-ID") is not None
            and _same_instant(c.get("RECURRENCE-ID").dt, anchor)
        )
    ]
    _stamp(master, now)
    return cal.to_ical()


def _until_before(anchor) -> date | datetime:
    if isinstance(anchor, datetime):
        return _as_utc(anchor - timedelta(seconds=1))
    return anchor - timedelta(days=1)


def _rrule_dict(master: Event) -> dict | None:
    rrule = master.get("RRULE")
    if rrule is None:
        return None
    rule = rrule[0] if isinstance(rrule, list) else rrule
    return {k: list(v) for k, v in rule.items()}


def _drop_overrides(cal: Calendar, anchor, *, keep_before: bool) -> None:
    """Keep only the overrides on one side of the split anchor."""
    kept = []
    for c in cal.subcomponents:
        rid = c.get("RECURRENCE-ID") if getattr(c, "name", "") == "VEVENT" else None
        if rid is not None:
            after = _at_or_after(rid.dt, anchor)
            if (keep_before and after) or (not keep_before and not after):
                continue  # drop overrides belonging to the other side
        kept.append(c)
    cal.subcomponents = kept


def split_series(
    raw: bytes | str, recurrence_id: str, edit: EventEdit, *, now: datetime | None = None
) -> tuple[bytes, bytes]:
    """Split a series at `recurrence_id` ("this and following"). Returns
    (head_ics, tail_ics): the head is the original resource with its rule bounded
    to end just before the anchor; the tail is a brand-new resource (new UID)
    starting at the anchor with the remaining recurrence and the edits applied.

    Note: a COUNT-bounded rule's tail is emitted without the COUNT bound (it keeps
    FREQ/INTERVAL/BY*/UNTIL). Delete-this-and-following passes an empty edit and
    the caller PUTs only the head, discarding the tail."""
    now = now or datetime.now(timezone.utc)
    anchor = _anchor_from_iso(recurrence_id)

    # Head: bound the master rule with UNTIL, keep only earlier overrides.
    head = Calendar.from_ical(raw)
    hmaster = _find_master_event(head)
    if hmaster is None:
        raise ValueError("resource has no VEVENT to edit")
    rule = _rrule_dict(hmaster)
    if rule is not None:
        rule.pop("COUNT", None)
        rule["UNTIL"] = [_until_before(anchor)]
        _set_rrule(hmaster, rule)
    _drop_overrides(head, anchor, keep_before=True)
    _stamp(hmaster, now)

    # Tail: fresh UID, DTSTART=anchor, remaining rule, later overrides re-homed.
    tail = Calendar.from_ical(raw)
    tmaster = _find_master_event(tail)
    new_uid = f"{uuid4().hex}@tasksd"
    dur = _event_duration(tmaster)
    _replace(tmaster, "DTSTART")
    tmaster.add("DTSTART", anchor)
    _replace(tmaster, "DURATION")
    _replace(tmaster, "DTEND")
    if dur is not None:
        tmaster.add("DTEND", anchor + dur)
    tail_rule = _rrule_dict(tmaster)
    if tail_rule is not None:
        tail_rule.pop("COUNT", None)
        _set_rrule(tmaster, tail_rule)
    _drop_overrides(tail, anchor, keep_before=False)
    for ev in tail.walk("VEVENT"):
        _replace(ev, "UID")
        ev.add("UID", new_uid)
    _apply_event_fields(tmaster, edit, now)
    return head.to_ical(), tail.to_ical()
