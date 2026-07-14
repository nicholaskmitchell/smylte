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
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4

from dateutil.rrule import rrulestr
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


def _find_master_todo(cal: Calendar):
    """The series master: the first VTODO without a RECURRENCE-ID. A recurring
    task's resource may carry override components — and a foreign client may
    serialize them before the master — so "first in walk order" is not safe.
    Mirrors ``_find_master_event`` (and ``read.find_component``, the read side)."""
    todos = list(cal.walk("VTODO"))
    for td in todos:
        if "RECURRENCE-ID" not in td:
            return td
    return todos[0] if todos else None


def apply_changes(raw: bytes | str, edit: TaskEdit, *, now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    todo = _find_master_todo(cal)
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

def _anchor_from_iso(recurrence_id: str, master: Event | None = None) -> date | datetime:
    """Parse an occurrence anchor (the ISO the read path emitted) back to a
    date (all-day) or datetime (timed).

    An aware ISO carries only a numeric offset, so ``fromisoformat`` yields a
    fixed-offset tzinfo — which icalendar would serialize as a fabricated
    ``TZID="UTC-06:00"``: unparseable by other clients and unmatchable against
    the series. Re-express the anchor in the master DTSTART's real zone so
    RECURRENCE-ID / EXDATE / DTSTART values written from it stay in the
    series' own TZID (the instant is unchanged)."""
    s = recurrence_id.strip()
    anchor = datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)
    if isinstance(anchor, datetime) and anchor.tzinfo is not None and master is not None:
        ds = master.get("DTSTART")
        mdt = ds.dt if ds is not None else None
        if isinstance(mdt, datetime) and mdt.tzinfo is not None:
            anchor = anchor.astimezone(mdt.tzinfo)
    return anchor


def _as_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt


def _same_instant(a, b) -> bool:
    if isinstance(a, datetime) and isinstance(b, datetime):
        if (a.tzinfo is None) != (b.tzinfo is None):
            # One side lost its zone (e.g. a RECURRENCE-ID whose TZID an old
            # write fabricated and no longer resolves): fall back to wall-clock
            # so the occurrence is still addressable rather than silently
            # spawning a duplicate override.
            return a.replace(tzinfo=None) == b.replace(tzinfo=None)
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
    anchor = _anchor_from_iso(recurrence_id, master)
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
    anchor = _anchor_from_iso(recurrence_id, master)
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


_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _wall_delta(a: date | datetime, b: date | datetime) -> timedelta:
    """Wall-clock difference a − b, tolerating mixed tz-awareness: the app
    writes floating local times while a foreign master may be zone-aware, and
    "shift the series by what the user dragged" is a wall-clock notion."""
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a.replace(tzinfo=None) - b.replace(tzinfo=None)
    return a - b


def _shift_datelike(event: Event, key: str, delta: timedelta) -> None:
    prop = event.get(key)
    if prop is None:
        return
    old = prop.dt
    _replace(event, key)
    # Adding to the original value keeps its type and tzinfo, so a zone-aware
    # series keeps its wall-clock time across DST boundaries.
    event.add(key, old + delta)


def _shift_datelist(event: Event, key: str, delta: timedelta) -> None:
    """Shift every EXDATE/RDATE entry (possibly several property lines)."""
    prop = event.get(key)
    if prop is None:
        return
    lists = prop if isinstance(prop, list) else [prop]
    values = [entry.dt + delta for lst in lists for entry in lst.dts]
    _replace(event, key)
    if values:
        event.add(key, values)


def _shift_rrule(master: Event, delta: timedelta, day_delta: int) -> None:
    """UNTIL moves with the series (preserving the occurrence count), and a
    WEEKLY BYDAY list rotates with the day offset so "every Mon" dragged one
    day becomes "every Tue". Other BY* parts (foreign clients only — our own
    rules never carry them) are left untouched."""
    rule = _rrule_dict(master)
    if rule is None:
        return
    changed = False
    if "UNTIL" in rule:
        rule["UNTIL"] = [u + delta for u in rule["UNTIL"]]
        changed = True
    freq = [str(f).upper() for f in rule.get("FREQ", [])]
    if day_delta % 7 and "WEEKLY" in freq and "BYDAY" in rule:
        codes = [str(d).upper() for d in rule["BYDAY"]]
        if all(c in _WEEKDAYS for c in codes):
            rule["BYDAY"] = [_WEEKDAYS[(_WEEKDAYS.index(c) + day_delta) % 7] for c in codes]
            changed = True
    if changed:
        _set_rrule(master, rule)


def shift_series(
    raw: bytes | str, recurrence_id: str, edit: EventEdit, *, now: datetime | None = None
) -> bytes:
    """Reschedule a whole series ("all events" with a time change): move every
    occurrence by the offset the user applied to one of them. The base slot is
    the dragged occurrence's current start (its override's DTSTART if it was
    moved, else the `recurrence_id` anchor), so the visual offset and the series
    offset agree. Master DTSTART/DTEND, RRULE UNTIL, EXDATE/RDATE, and every
    override's RECURRENCE-ID and times shift together so no anchor orphans.
    Date-ness is preserved — an all-day series stays all-day, and switching a
    series between all-day and timed is rejected. A new end changes the master's
    duration (a resize); remaining non-time fields apply to the master as usual.
    """
    if edit.dtstart is UNSET or edit.dtstart is None:
        raise ValueError("rescheduling a series requires a new start")
    now = now or datetime.now(timezone.utc)

    cal = Calendar.from_ical(raw)
    master = _find_master_event(cal)
    if master is None or master.get("DTSTART") is None:
        raise ValueError("resource has no dated VEVENT to edit")

    anchor = _anchor_from_iso(recurrence_id, master)
    if isinstance(anchor, datetime) != isinstance(edit.dtstart, datetime):
        raise ValueError(
            "cannot switch a series between all-day and timed with 'all events'; "
            "edit single occurrences instead"
        )

    override = _find_override(cal, anchor)
    base = override.get("DTSTART").dt if override is not None and override.get("DTSTART") else anchor
    # A foreign client may have given this occurrence's override a different
    # dateness than the series (a timed override on an all-day series, say);
    # the drag delta is a series-dateness notion, so coerce the base to match
    # the anchor rather than crashing on date − datetime.
    if isinstance(anchor, datetime) and not isinstance(base, datetime):
        base = datetime.combine(base, time())
    elif not isinstance(anchor, datetime) and isinstance(base, datetime):
        base = base.date()
    delta = _wall_delta(edit.dtstart, base)
    old_start = master.get("DTSTART").dt
    new_start = old_start + delta
    day_delta = (
        (new_start.date() if isinstance(new_start, datetime) else new_start)
        - (old_start.date() if isinstance(old_start, datetime) else old_start)
    ).days
    duration = None
    if edit.dtend is not UNSET and edit.dtend is not None:
        duration = _wall_delta(edit.dtend, edit.dtstart)

    for ev in cal.walk("VEVENT"):
        is_master = "RECURRENCE-ID" not in ev
        _shift_datelike(ev, "RECURRENCE-ID", delta)
        _shift_datelike(ev, "DTSTART", delta)
        if duration is not None and is_master:
            # Resize: the master's span becomes the new duration; overrides keep
            # their own explicit times (shifted, but not re-sized).
            _replace(ev, "DURATION")
            _replace(ev, "DTEND")
            ev.add("DTEND", ev.get("DTSTART").dt + duration)
        else:
            _shift_datelike(ev, "DTEND", delta)
        if is_master:
            _shift_datelist(ev, "EXDATE", delta)
            _shift_datelist(ev, "RDATE", delta)
            _shift_rrule(ev, delta, day_delta)
        else:
            _stamp(ev, now)

    # Non-time fields (summary, rrule change, …) land on the master, which also
    # picks up its stamp here.
    _apply_event_fields(master, replace(edit, dtstart=UNSET, dtend=UNSET), now)
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


def _partition_datelist(event: Event, key: str, anchor, *, keep_before: bool) -> None:
    """Keep only the RDATE/EXDATE entries on one side of the split anchor.
    UNTIL bounds the RRULE only — list-based instances ignore it, so without
    this a post-anchor RDATE would survive in the head AND duplicate into the
    tail."""
    prop = event.get(key)
    if prop is None:
        return
    lists = prop if isinstance(prop, list) else [prop]
    values = [entry.dt for lst in lists for entry in lst.dts]
    keep = [v for v in values if _at_or_after(v, anchor) != keep_before]
    if len(keep) == len(values):
        return
    _replace(event, key)
    if keep:
        event.add(key, keep)


def _count_consumed(rule: dict, dtstart: date | datetime, anchor) -> int:
    """How many RRULE-generated occurrences fall strictly before `anchor` — the
    head's share of a COUNT-bounded series. (EXDATE'd instances still consume
    COUNT per RFC 5545, and RDATE additions never do, so the raw rule is the
    right thing to enumerate.)"""
    def _dt(v):
        return v if isinstance(v, datetime) else datetime.combine(v, time())

    start, end = _dt(dtstart), _dt(anchor)
    if (start.tzinfo is None) != (end.tzinfo is None):
        start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    rr = rrulestr(vRecur(rule).to_ical().decode(), dtstart=start)
    consumed = 0
    for occ in rr:                      # finite: the rule carries COUNT
        if occ >= end:
            break
        consumed += 1
    return consumed


def split_series(
    raw: bytes | str, recurrence_id: str, edit: EventEdit, *, now: datetime | None = None
) -> tuple[bytes, bytes]:
    """Split a series at `recurrence_id` ("this and following"). Returns
    (head_ics, tail_ics): the head is the original resource with its rule bounded
    to end just before the anchor; the tail is a brand-new resource (new UID)
    starting at the anchor with the remaining recurrence and the edits applied.
    A COUNT-bounded rule keeps its overall length: the tail's COUNT is the
    original minus the occurrences the head consumed. RDATE/EXDATE entries are
    partitioned by the anchor alongside the overrides.

    Delete-this-and-following passes an empty edit and the caller PUTs only the
    head, discarding the tail."""
    now = now or datetime.now(timezone.utc)

    # Head: bound the master rule with UNTIL, keep only earlier overrides.
    head = Calendar.from_ical(raw)
    hmaster = _find_master_event(head)
    if hmaster is None:
        raise ValueError("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id, hmaster)
    rule = _rrule_dict(hmaster)
    if rule is not None:
        rule.pop("COUNT", None)
        rule["UNTIL"] = [_until_before(anchor)]
        _set_rrule(hmaster, rule)
    _drop_overrides(head, anchor, keep_before=True)
    _partition_datelist(hmaster, "RDATE", anchor, keep_before=True)
    _partition_datelist(hmaster, "EXDATE", anchor, keep_before=True)
    _stamp(hmaster, now)

    # Tail: fresh UID, DTSTART=anchor, remaining rule, later overrides re-homed.
    tail = Calendar.from_ical(raw)
    tmaster = _find_master_event(tail)
    new_uid = f"{uuid4().hex}@tasksd"
    dur = _event_duration(tmaster)
    orig_start = tmaster.get("DTSTART").dt if tmaster.get("DTSTART") is not None else anchor
    _replace(tmaster, "DTSTART")
    tmaster.add("DTSTART", anchor)
    _replace(tmaster, "DURATION")
    _replace(tmaster, "DTEND")
    if dur is not None:
        tmaster.add("DTEND", anchor + dur)
    tail_rule = _rrule_dict(tmaster)
    if tail_rule is not None:
        if "COUNT" in tail_rule:
            remaining = int(tail_rule["COUNT"][0]) - _count_consumed(
                tail_rule, orig_start, anchor
            )
            # The anchor is an occurrence, so ≥1 remains for any sane split;
            # clamp defensively so a bad anchor can't emit COUNT=0 (invalid).
            tail_rule["COUNT"] = [max(remaining, 1)]
        _set_rrule(tmaster, tail_rule)
    _drop_overrides(tail, anchor, keep_before=False)
    _partition_datelist(tmaster, "RDATE", anchor, keep_before=False)
    _partition_datelist(tmaster, "EXDATE", anchor, keep_before=False)
    for ev in tail.walk("VEVENT"):
        _replace(ev, "UID")
        ev.add("UID", new_uid)
    _apply_event_fields(tmaster, edit, now)
    return head.to_ical(), tail.to_ical()
