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

from .recur import _MAX_SEARCH_STEPS, _instances_before
from .rrule_budget import SearchBudgetExceeded, search_budget

# How far an override's RECURRENCE-ID may sit from DTSTART, in instances, before
# reconciling it is priced as too expensive to be worth probing. ~55 years of a
# daily rule. A legitimate probe costs one dateutil step; only a far-future
# anchor is expensive, and _instances_before over-estimates for coarse FREQs,
# which errs toward skipping more probes — the safe direction here.
_MAX_PROBE_INSTANCES = 20_000

# Sentinel: a field left UNSET is not touched; None means "clear this property".
UNSET: Any = object()


class NotEditable(ValueError):
    """The resource holds no component this edit can be applied to.

    Distinct from the other ValueErrors raised here (an all-day <-> timed series
    switch, an unknown repeat frequency), which are about the *request* and
    which the API answers 422. This one is about the stored bytes: a foreign
    client rewrote the resource into something that is no longer a task or an
    event, so there is nothing to edit. Subclasses ValueError so every existing
    handler keeps working."""


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
    related_parent: Any = UNSET       # parent task UID, or None to unparent


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
    # TRANSP (RFC 5545 §3.8.2.7) as the boolean the property actually encodes:
    # True writes OPAQUE, False writes TRANSPARENT, None REMOVES the property.
    #
    # Three states rather than two, and the third is not decoration. Absent is
    # OPAQUE by the spec's own default, so removing it and writing OPAQUE mean
    # the same thing to every reader — but only one of them leaves the resource
    # as its author wrote it. A caller who has never heard of Busy/Free leaves
    # this UNSET and nothing is touched at all, which is invariant #2's rule:
    # a property another client authored is not ours to rewrite in passing.
    busy: Any = UNSET


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


# RFC 5545 §3.3.8: INTEGER is a signed 32-bit value, and icalendar enforces it
# on write. A SEQUENCE has to fit, whatever the resource arrived carrying.
_SEQUENCE_MAX = 2**31 - 1


def _next_sequence(comp) -> int:
    """The SEQUENCE every write stamps: the current one plus one.

    Read with the tolerance `read._int` has, and for the same reason. The
    sync-stall finding taught the read path to treat an out-of-range or
    non-numeric SEQUENCE as absent, so a foreign resource carrying
    `SEQUENCE:99999999999999999999` or `SEQUENCE:abc` syncs, caches, and shows
    in the UI. Every writer then did `int(comp.get("SEQUENCE", 0)) + 1`: the
    first raised inside icalendar ("outside the RFC 5545 range"), the second
    inside `int()` (a `vBroken`), and even a legitimate `SEQUENCE:2147483647`
    raised on the +1. The routes map ValueError to 422, so the owner saw
    icalendar's internal message on every rename, drag, complete, "delete this
    occurrence" and "this and following" — the resource was permanently
    uneditable through the app, and only whole-resource delete (which parses
    nothing) still worked. A value that is not a sequence number counts as none,
    and the ceiling is held rather than wrapped: a bump other clients would read
    as going backwards is worse than one they cannot see.
    """
    try:
        n = int(comp.get("SEQUENCE", 0))
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    return min(n + 1, _SEQUENCE_MAX)


def _set_datelike(todo: Todo, key: str, value: date | datetime | None) -> None:
    """Write a DUE/DTSTART/DTEND, keeping the zone the property already had.

    The API serves a zone-anchored DUE as an ISO string with a numeric offset,
    which is all a browser can send back. Writing that offset verbatim makes
    icalendar fabricate ``TZID="UTC+02:00"`` — a zone name no other CalDAV
    client can resolve, and the same trap ``_anchor_from_iso`` documents for
    RECURRENCE-ID. Re-expressing the instant in the property's own tzinfo keeps
    ``DUE;TZID=Europe/Berlin`` intact and moves it to exactly the moment the
    user picked.

    Only applies when both sides are zone-aware: a floating value stays floating
    (the app's own writes are floating local), and an all-day DATE is untouched."""
    old = todo.get(key)
    old_dt = old.dt if old is not None and hasattr(old, "dt") else None
    _replace(todo, key)
    if value is None:
        return
    if (isinstance(value, datetime) and value.tzinfo is not None
            and isinstance(old_dt, datetime) and old_dt.tzinfo is not None):
        value = value.astimezone(old_dt.tzinfo)
    # icalendar emits VALUE=DATE for a date and DATE-TIME for a datetime (spec §5).
    todo.add(key, value)


def _set_related_parent(todo: Todo, uid: str | None) -> None:
    """Repoint the RELTYPE=PARENT relation, leaving every other RELATED-TO be.

    Invariant #2: a property another client authored is not ours to drop, and a
    VTODO may carry several relations (CHILD, SIBLING, a foreign RELTYPE we have
    no opinion about). Only the parent link is rewritten; the rest are read off
    and put back with their parameters intact.

    RFC 5545 makes PARENT the default when RELTYPE is absent, so a bare
    RELATED-TO is the parent relation and is replaced too — the same reading
    ``read._related_parent`` uses, which is what makes the round trip agree."""
    rel = todo.get("RELATED-TO")
    kept = []
    if rel is not None:
        for r in rel if isinstance(rel, list) else [rel]:
            params = dict(getattr(r, "params", {}) or {})
            if str(params.get("RELTYPE", "PARENT")).upper() != "PARENT":
                kept.append((str(r), params))
    _replace(todo, "RELATED-TO")
    for value, params in kept:
        todo.add("RELATED-TO", value, parameters=params)
    if uid:
        todo.add("RELATED-TO", uid, parameters={"RELTYPE": "PARENT"})


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
        raise NotEditable("resource has no VTODO to edit")

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
    if edit.related_parent is not UNSET:
        _set_related_parent(todo, edit.related_parent)

    # Every edit stamps modification metadata and bumps the sequence.
    _replace(todo, "LAST-MODIFIED")
    todo.add("LAST-MODIFIED", now)
    _replace(todo, "DTSTAMP")
    todo.add("DTSTAMP", now)
    _set_int(todo, "SEQUENCE", _next_sequence(todo))

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


# Arithmetic near datetime's edges raises OverflowError, which is not a
# ValueError, so nothing on the edit path caught it: a foreign
# UNTIL=99991231T235959Z made every drag of that series a 500, and "repeat until
# 9999-12-31" from the UI did the same. Saturate rather than refuse — a rule
# running to the end of representable time is unbounded in every practical
# sense, and refusing would leave the foreign series exactly as uneditable, just
# with a tidier status code. The margin leaves room for a zone conversion (±14h)
# and a subsequent drag to move it again without walking off the end.
_UNTIL_GUARD = timedelta(days=2)


def _saturate(dt: datetime) -> datetime:
    """`dt`, pulled inside the range datetime arithmetic can survive."""
    lo, hi = datetime.min + _UNTIL_GUARD, datetime.max - _UNTIL_GUARD
    naive = dt.replace(tzinfo=None)
    if naive > hi:
        return hi.replace(tzinfo=dt.tzinfo)
    if naive < lo:
        return lo.replace(tzinfo=dt.tzinfo)
    return dt


def _bound(*, high: bool, tzinfo) -> datetime:
    """The saturation value itself, in the shape the caller returns."""
    edge = datetime.max - _UNTIL_GUARD if high else datetime.min + _UNTIL_GUARD
    return edge.replace(tzinfo=tzinfo)


def _safely(compute, *, high: bool, tzinfo):
    """`compute()`, saturating instead of overflowing.

    The RESULT has to be clamped, not just the input: pre-clamping only survives
    a delta smaller than the guard, so a bounded series dragged a day worked and
    the same series dragged a month still raised. That distinction is why the
    stage-1 pin (which drags one day) passed against a half-fix."""
    try:
        return _saturate(compute())
    except (OverflowError, ValueError):
        return _bound(high=high, tzinfo=tzinfo)


def _coerce_until(until, dtstart) -> date | datetime:
    """UNTIL, expressed in the value type RFC 5545 §3.3.10 requires of it.

    The rule is that UNTIL must match DTSTART's value type, and must be UTC
    whenever DTSTART is not floating. The UI's "Repeat until" field is an
    ``<input type="date">``, so a timed series arrives here asking to repeat
    until a bare *day* — and an expander reads a DATE as that day's midnight,
    which drops the very occurrence the user picked the day for. Widening the
    day to its last second (in the series' own zone, so "until Mar 2" means the
    end of Mar 2 where the user lives) keeps it."""
    if not isinstance(dtstart, datetime):
        # All-day series: UNTIL stays a bare DATE.
        return until.date() if isinstance(until, datetime) else until
    if not isinstance(until, datetime):
        until = datetime.combine(until, time(23, 59, 59), tzinfo=dtstart.tzinfo)
    elif until.tzinfo is None and dtstart.tzinfo is not None:
        until = until.replace(tzinfo=dtstart.tzinfo)
    until = _saturate(until)
    if dtstart.tzinfo is not None:
        return _safely(lambda: _as_utc(until), high=True, tzinfo=timezone.utc)
    return until.replace(tzinfo=None)


def _normalized_rule(rule: dict | None, event: Event) -> dict | None:
    """``rule`` with UNTIL expressed the way it will actually be written."""
    ds = event.get("DTSTART")
    if rule and rule.get("UNTIL") and ds is not None:
        return dict(rule, UNTIL=[_coerce_until(u, ds.dt) for u in rule["UNTIL"]])
    return rule


def _set_rrule(event: Event, rule: dict | None) -> None:
    """Write the master's RRULE. The single choke point for every rule write —
    `_apply_event_fields`, `_shift_rrule`, and both of `split_series`' rewrites —
    so UNTIL is normalized against DTSTART here, once."""
    _replace(event, "RRULE")
    rule = _normalized_rule(rule, event)
    if rule:
        event.add("RRULE", vRecur(rule))


def _rule_changed(master: Event, new_rule: dict | None) -> bool:
    """Is ``new_rule`` actually a different repeat from the one on ``master``?

    The modal resends its whole repeat state on every save, so ``edit.rrule`` is
    set on a pure rename or drag too. Asking this before reconciling keeps an
    unrelated edit from dropping an override a foreign client anchored at an odd
    slot — or one an older write of ours mislabelled with a fabricated TZID."""
    def _ical(rule):
        return vRecur(rule).to_ical() if rule else None

    return _ical(_rrule_dict(master)) != _ical(_normalized_rule(new_rule, master))


def _datelist_values(event: Event, key: str) -> list:
    """Every value of a (possibly multi-line) EXDATE/RDATE property."""
    prop = event.get(key)
    if prop is None:
        return []
    lists = prop if isinstance(prop, list) else [prop]
    return [entry.dt for lst in lists for entry in lst.dts]


def _rule_for_probe(rule: dict, start: datetime, original_dtstart) -> str:
    """`rule` serialized so dateutil will accept it alongside `start`.

    dateutil refuses a rule whose UNTIL disagrees with dtstart about awareness —
    "RRULE UNTIL values must be specified in UTC when DTSTART is timezone-aware"
    — and `_comparable` strips BOTH ends of the probe to wall clock whenever an
    override's RECURRENCE-ID and the master's DTSTART disagree, which is exactly
    what a floating override left by an older write or a foreign client causes.
    That left `UNTIL=...Z` as the only aware value in the call, so one such
    override made "Repeat until <date>" permanently unsaveable on that series —
    a 422 carrying dateutil's internal message.

    Converted through the master's own zone before stripping, rather than merely
    having its tzinfo dropped, so the bound still lands on the wall clock the
    rule was written against.
    """
    until = rule.get("UNTIL")
    if not until:
        return vRecur(rule).to_ical().decode()

    zone = getattr(original_dtstart, "tzinfo", None)
    out, changed = [], False
    for v in (until if isinstance(until, list) else [until]):
        if isinstance(v, datetime):
            if start.tzinfo is None and v.tzinfo is not None:
                v = (v.astimezone(zone) if zone else v).replace(tzinfo=None)
                changed = True
            elif start.tzinfo is not None and v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
                changed = True
        out.append(v)
    return vRecur({**rule, "UNTIL": out} if changed else rule).to_ical().decode()


def _comparable(dtstart, moment) -> tuple[datetime, datetime]:
    """(dtstart, moment) as datetimes dateutil can compare — all-day values
    become midnight, and a mixed-awareness pair drops to wall clock rather than
    raising."""
    def _dt(v):
        return v if isinstance(v, datetime) else datetime.combine(v, time())

    start, at = _dt(dtstart), _dt(moment)
    if (start.tzinfo is None) != (at.tzinfo is None):
        start, at = start.replace(tzinfo=None), at.replace(tzinfo=None)
    return start, at


def _reconcile_overrides(cal: Calendar, master: Event) -> None:
    """Drop the override components the master's *new* recurrence rule no longer
    generates.

    Changing an event's repeat left its RECURRENCE-ID overrides behind. An
    override whose slot the new rule never produces is not part of the
    recurrence set at all, yet the expander still emits it — so the calendar
    showed an event belonging to a schedule the user had just deleted, with no
    way to get rid of it. Apple and Google clients reconcile here; so do we.

    Only rules from our own repeat vocabulary are reconciled. ``edit.rrule`` can
    carry nothing else (``rrule_from_spec`` builds it), and testing membership of
    a foreign rule means letting dateutil iterate from its DTSTART — the
    unbounded cost ``recur._pathological_rule`` refuses up front. An exotic rule
    keeps its overrides untouched, which is the safe direction to err: a phantom
    renders, where a wrong drop destroys an edit the user made.
    """
    rule = _rrule_dict(master)
    dtstart = master.get("DTSTART")
    if rule is not None:
        if not {str(f).upper() for f in rule.get("FREQ", [])} <= set(_FREQ.values()):
            return
        if dtstart is None:
            return

    # RDATE additions are part of the recurrence set too, independently of the rule.
    rdates = _datelist_values(master, "RDATE")

    def _generated(anchor) -> bool:
        if any(_same_instant(_period_start(r), anchor) for r in rdates):
            return True
        if rule is None:
            return False        # repeat cleared: only the master and its RDATEs remain
        # Re-anchored per override, because dateutil needs both ends of the probe
        # to agree on tz-awareness and an override's RECURRENCE-ID need not agree
        # with the master's (an older write may have lost or fabricated a zone).
        start, at = _comparable(dtstart.dt, anchor)
        # The FREQ whitelist above bounds the RULE; it does not bound the PROBE
        # TARGET, and that is the attacker-controlled half. `at` is the
        # override's RECURRENCE-ID, written by whatever client made it, so a
        # far-future anchor makes dateutil walk from DTSTART to it before it can
        # answer: measured 10.17s for two overrides, 51.40s for ten, all under
        # the global service lock, on an ordinary "change the repeat" edit.
        #
        # Reuse the read path's own arithmetic to price the walk before doing
        # it. Over the limit, keep the override without probing — the safe
        # direction this function's docstring already argues for, and the same
        # answer it gives a foreign rule. A legitimate probe costs one step, so
        # nothing real is near this.
        if _instances_before(rule, dtstart, at) > _MAX_PROBE_INSTANCES:
            return True
        rr = rrulestr(_rule_for_probe(rule, start, dtstart.dt), dtstart=start)
        return bool(rr.between(at, at, inc=True))

    def _keep(c) -> bool:
        if getattr(c, "name", "") != "VEVENT" or c.get("RECURRENCE-ID") is None:
            return True
        try:
            return _generated(c.get("RECURRENCE-ID").dt)
        except SearchBudgetExceeded:
            # The shared budget is the backstop behind the arithmetic above: a
            # shape it prices as cheap but that still walks. Keep the override,
            # same safe direction. Deciding this per component rather than for
            # the whole comprehension means one expensive probe cannot make
            # every LATER override un-reconcilable, which would silently keep
            # genuinely orphaned ones.
            return True

    # One budget for the whole reconcile, so a resource carrying many overrides
    # is bounded in aggregate and not merely per probe.
    with search_budget(_MAX_SEARCH_STEPS):
        cal.subcomponents = [c for c in cal.subcomponents if _keep(c)]


def _stamp(event: Event, now: datetime) -> None:
    """Modification metadata every write bumps."""
    _replace(event, "LAST-MODIFIED")
    event.add("LAST-MODIFIED", now)
    _replace(event, "DTSTAMP")
    event.add("DTSTAMP", now)
    _set_int(event, "SEQUENCE", _next_sequence(event))


def _check_event_span(event: Event, edit: EventEdit) -> None:
    """Refuse an edit that would leave DTSTART and DTEND disagreeing.

    RFC 5545 §3.6.1: DTEND's value type MUST match DTSTART's. Nothing enforced
    that, and the HTTP PATCH model decides each end independently by feeding the
    raw string to `_parse_datelike` — a bare `YYYY-MM-DD` becomes a `date`,
    anything with a `T` a `datetime` — with no `all_day` flag to pair them and no
    downstream re-pairing.

    So `PATCH {"start": "2026-03-12"}` on a timed meeting wrote
    `DTSTART;VALUE=DATE:20260312` beside the untouched `DTEND:20260310T100000`.
    Every other client sharing the collection then has to cope with an invalid
    resource — and this app's own read path reports `all_day` from DTSTART alone,
    while `scheduling.busy_intervals` skips all-day events, so the meeting
    stopped blocking anything and the anonymous booking page offered its hour as
    free. (The same PATCH also left DTEND two days before its own DTSTART.)

    The SPA always sends both ends, but `smylte_update_event` exposes them as
    independent optional strings, so an LLM moving a meeting to a date is enough.

    Refusing rather than guessing: coercing a bare date onto a timed event means
    inventing a time. ValueError, which `patch_event` maps to 422 and the MCP
    tools to a ToolError, so the caller reads the sentence below.
    """
    def kind(v) -> str:
        return "timed" if isinstance(v, datetime) else "all-day"

    start = edit.dtstart if (edit.dtstart is not UNSET and edit.dtstart is not None) else None
    end = edit.dtend if (edit.dtend is not UNSET and edit.dtend is not None) else None
    if start is None and end is None:
        return

    # An edit that CLEARS the end is not an edit that omits one. `EditEvent.end`
    # is `str | None` and `_parse_datelike(None)` is None, so `{"start": …,
    # "end": null}` arrives here with `dtend` SUPPLIED-as-None — and validating
    # it against the DTEND it is about to remove refused an edit that is
    # internally consistent. `_apply_event_fields` drops the property two lines
    # later; there is nothing left to disagree with.
    clearing_end = edit.dtend is not UNSET and edit.dtend is None
    if clearing_end and start is None:
        return

    # BEFORE the pair logic below, because that returns early when there is no
    # DTEND to compare against — and this is exactly the shape where there is
    # none. An event's length can be expressed as a DURATION instead, which is
    # what phone clients write, and RFC 5545 §3.6.1 asks the same of it: a DATE
    # start takes a NOMINAL, day-valued duration. Switching such an event to
    # all-day used to leave `DTSTART;VALUE=DATE` beside `DURATION:PT1H`, which
    # the read path then reports as all-day from DTSTART alone — so
    # `busy_intervals` skipped it and the booking page offered its hour.
    if start is not None and not isinstance(start, datetime) and event.get("DTEND") is None:
        dur = event.get("DURATION")
        if dur is not None and hasattr(dur, "dt") and isinstance(dur.dt, timedelta):
            if dur.dt.total_seconds() % 86400:
                raise ValueError(
                    "this event's length is measured in hours, so it cannot become "
                    "an all-day event without a new end; send both ends together"
                )

    if start is not None and end is not None:
        if kind(start) != kind(end):
            raise ValueError(
                f"start is {kind(start)} and end is {kind(end)} — an event's two "
                f"ends must be the same kind; send both as dates or both as times"
            )
        lo, hi = start, end
    else:
        incoming, other_key = (start, "DTEND") if start is not None else (end, "DTSTART")
        other = event.get(other_key)
        # `hasattr(…, "dt")`, because a resource can carry the property TWICE and
        # icalendar then hands back a list. Every other datelike reader in this
        # file guards for it; without it this raised AttributeError, which is
        # neither ValueError nor OverflowError, so `patch_event` did not map it
        # and the event became permanently uneditable through the app.
        if other is None or not hasattr(other, "dt"):
            return
        if start is not None and clearing_end:
            # Moving the start while removing the end: nothing to compare, and
            # the old DTEND is on its way out.
            return
        if kind(other.dt) != kind(incoming):
            raise ValueError(
                f"this event is {kind(other.dt)} and the new "
                f"{'start' if start is not None else 'end'} is {kind(incoming)} — "
                f"send both ends together to change which kind it is"
            )
        lo, hi = (incoming, other.dt) if start is not None else (other.dt, incoming)

    # Same guard, one layer up: the pair now agrees on kind, so it can be
    # ordered. Only checked when the edit touches an end, so a resource another
    # client already wrote backwards stays editable in every other respect.
    try:
        if _as_sortable(hi) < _as_sortable(lo):
            raise ValueError("an event cannot end before it starts")
    except TypeError:
        return                              # unorderable shapes are not this guard's


def _apply_event_fields(event: Event, edit: EventEdit, now: datetime) -> None:
    """Apply an EventEdit's field intent to a single VEVENT (master or override)."""
    _check_event_span(event, edit)
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
    if edit.busy is not UNSET:
        # Written EXPLICITLY on both arms, OPAQUE included, rather than leaving
        # the default to say it. This is the property Apple Calendar, Google
        # Calendar and Thunderbird all render as a control the owner has just
        # touched, and "I set this back to Busy" reaching the wire as the
        # absence of a line is a change no other client can see the owner made —
        # it reads identically to never having been asked. `None` is the one
        # value that removes it, and no client sends that today.
        _replace(event, "TRANSP")
        if edit.busy is not None:
            event.add("TRANSP", "OPAQUE" if edit.busy else "TRANSPARENT")
    if edit.rrule is not UNSET:
        _set_rrule(event, edit.rrule)
    _stamp(event, now)


def apply_event_changes(raw: bytes | str, edit: EventEdit, *, now: datetime | None = None) -> bytes:
    """Edit the series master (or a plain event) — the "all events" path."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    event = _find_master_event(cal)
    if event is None:
        raise NotEditable("resource has no VEVENT to edit")
    # Asked before the write, while the master still carries the old rule.
    repeat_changed = edit.rrule is not UNSET and _rule_changed(event, edit.rrule)
    _apply_event_fields(event, edit, now)
    if repeat_changed:
        _reconcile_overrides(cal, event)
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
    date (all-day) or datetime (timed), IN THE SERIES' OWN ZONE.

    Everything written from an anchor — a split tail's DTSTART, an override's
    RECURRENCE-ID, an EXDATE — inherits its awareness, so an anchor with no zone
    produces a form-1 DATE-TIME: a FLOATING time (RFC 5545 §3.3.5), meaning
    "09:00 wherever the reader is" rather than 09:00 in the series' zone. Each
    of the three fails differently in another client: a floating tail drifts away
    from its own head across a DST boundary, a floating RECURRENCE-ID stops
    matching the instance the rule generates so the override renders as a
    DUPLICATE, and a floating EXDATE excludes nothing so a deleted occurrence
    comes back.

    Two arms, and only the first was here:

    * An AWARE ISO carries only a numeric offset, so ``fromisoformat`` yields a
      fixed-offset tzinfo — which icalendar would serialize as a fabricated
      ``TZID="UTC-06:00"``: unparseable by other clients and unmatchable against
      the series. Converted into the master's real zone; the instant is
      unchanged.
    * A NAIVE ISO is what the read path actually emits and the SPA actually sends
      back — a local wall time in the series' own zone with no offset on it — so
      this is the arm that runs in production, and it did not exist. The zone is
      ATTACHED rather than converted, because the value already IS a reading in
      that zone.

    A wall time inside a fall-back repeat is ambiguous in this format however it
    is parsed; ``replace`` takes the first of the two (``fold=0``). That
    ambiguity is in the ISO the SPA sends, not in what is done with it here, and
    naming one of the two instants is strictly better than naming neither.

    A master whose own DTSTART is floating, or an all-day series (whose anchor is
    a ``date``), has no zone to keep and is left exactly as it was — the control
    for that is that ``VALUE=DATE`` is what makes an event all-day.
    """
    s = recurrence_id.strip()
    anchor = datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)
    if isinstance(anchor, datetime) and master is not None:
        ds = master.get("DTSTART")
        mdt = ds.dt if ds is not None else None
        if isinstance(mdt, datetime) and mdt.tzinfo is not None:
            anchor = (anchor.astimezone(mdt.tzinfo) if anchor.tzinfo is not None
                      else anchor.replace(tzinfo=mdt.tzinfo))
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


def _period_start(value):
    """The instant a date-list entry identifies. An RDATE;VALUE=PERIOD entry
    parses as a ``(start, end)`` or ``(start, duration)`` tuple, and a period is
    addressed by where it starts."""
    return value[0] if isinstance(value, tuple) else value


def _at_or_after(a, anchor) -> bool:
    """True if instant/date `a` is on or after `anchor` (used to split a series)."""
    a, anchor = _period_start(a), _period_start(anchor)
    if isinstance(a, datetime) and isinstance(anchor, datetime):
        if (a.tzinfo is None) != (anchor.tzinfo is None):
            # Same guard, and the same reasoning, as `_same_instant` above:
            # `_as_utc` leaves a naive value naive, so one floating EXDATE /
            # RDATE / RECURRENCE-ID — which is exactly what a foreign client
            # leaves behind — made every "this and following" edit or delete a
            # TypeError. Fall back to wall clock so the occurrence stays
            # addressable rather than taking the whole edit down.
            return a.replace(tzinfo=None) >= anchor.replace(tzinfo=None)
        return _as_utc(a) >= _as_utc(anchor)
    da = a.date() if isinstance(a, datetime) else a
    db = anchor.date() if isinstance(anchor, datetime) else anchor
    return da >= db


def _event_duration(master: Event):
    """The event's span, tolerating the shapes a foreign client can write.

    Every other datetime helper in this file deliberately survives a mismatched
    pair — `_wall_delta` handles mixed tz-awareness, `_comparable` drops to wall
    clock rather than raising, `_shift_value` handles PERIOD tuples. This was
    the one left doing a raw subtraction, and it sits on BOTH per-occurrence
    write paths. A DTSTART/DTEND that disagree on value type (DATE vs
    DATE-TIME) or on awareness (`DTSTART;TZID=…` beside a floating DTEND) —
    both writable through Radicale by anything sharing the collection — raised
    TypeError, which the routes do not map (they translate ValueError to 422),
    so it escaped as a 500 and the event could never be edited again."""
    ds, de, dur = master.get("DTSTART"), master.get("DTEND"), master.get("DURATION")
    if ds is not None and de is not None:
        start, end = _comparable(ds.dt, de.dt)
        return end - start
    if dur is not None:
        return dur.dt
    return None


def _find_override(cal: Calendar, anchor):
    for ev in cal.walk("VEVENT"):
        rid = ev.get("RECURRENCE-ID")
        if rid is not None and _same_instant(rid.dt, anchor):
            return ev
    return None


def _claimed_anchors(cal: Calendar, *, exclude: Event | None = None) -> list:
    """Every instant an override component already addresses, except `exclude`.

    Two components may not both claim one RECURRENCE-ID value — a reader has no
    way to rank them — so anything that MOVES an override has to know which slots
    are spoken for. Nothing in this file answered that before: `_find_override`
    looks up one instant, `_governing_thisandfuture` filters by RANGE, and
    `_drop_overrides` partitions by side of a split.
    """
    out = []
    for c in cal.walk("VEVENT"):
        if c is exclude:
            continue
        rid = c.get("RECURRENCE-ID")
        if rid is not None:
            out.append(rid.dt)
    return out


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


# "The rule could not be evaluated", as distinct from "the rule was evaluated and
# there is nothing later". `_next_generated` used to answer None for both, and
# its only caller deleted an override for both — which is right for the second
# and permanent data loss for the first.
_UNKNOWN = object()


def _as_sortable(v):
    """A key that orders dates and datetimes, aware or not, without raising."""
    if isinstance(v, datetime):
        return (v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo
                else v)
    return datetime.combine(v, time())


def _after(values, moment) -> list:
    """Those of `values` strictly after `moment`."""
    return [v for v in values
            if not _same_instant(v, moment) and _at_or_after(v, moment)]


def _excluded(slot, excluded) -> bool:
    """Is `slot` removed by one of these EXDATE values?

    A DATE-valued EXDATE on a TIMED series removes the whole day — that is what
    `recurring_ical_events` does, keeping a separate date-keyed exclusion set —
    and `_same_instant` answers False outright for a date/datetime pair, so
    comparing instants alone let a re-homed override land on an excluded slot and
    resurrect a deleted occurrence.
    """
    for x in excluded:
        x = _period_start(x)
        if _same_instant(x, slot):
            return True
        if not isinstance(x, datetime) and isinstance(slot, datetime):
            if x == slot.date():
                return True
    return False


def _first_free(slots, after, blocked, excluded):
    """The earliest of `slots` strictly after `after` that nothing has claimed."""
    for slot in slots:
        if _same_instant(slot, after) or not _at_or_after(slot, after):
            continue
        if any(_same_instant(b, slot) for b in blocked):
            continue
        if _excluded(slot, excluded):
            continue
        return slot
    return None


def _like_anchor(value, anchor):
    """`value` coerced to the anchor's dateness and awareness.

    Every value this normalizes is about to be compared with the anchor, written
    back as a RECURRENCE-ID, and subtracted from the anchor — so a mixed list is
    not an inconsistency, it is a TypeError waiting for the one resource that
    carries the other shape. Mixed-awareness drops to wall clock, which is the
    same call `_comparable` makes for the same reason.
    """
    if not isinstance(value, date):          # datetime is a date subclass
        return value                         # a shape we do not recognise; leave it
    if isinstance(anchor, datetime):
        if not isinstance(value, datetime):
            value = datetime.combine(value, time())
        if anchor.tzinfo is not None and value.tzinfo is None:
            return value.replace(tzinfo=anchor.tzinfo)
        if anchor.tzinfo is None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value
    return value.date() if isinstance(value, datetime) else value


def _next_generated(master: Event, after, *, blocked=()) -> date | datetime | None:
    """The series' next occurrence strictly after `after` that is FREE.

    Free means: generated by the rule, not excluded by an EXDATE, and not already
    addressed by one of `blocked` (the anchors other override components claim).
    Used to re-home a THISANDFUTURE override, so landing on an occupied or
    excluded slot is not a near miss — it either destroys another component's
    edit or points at an occurrence that does not exist.

    Returns `_UNKNOWN` when the rule cannot be evaluated at all: a FREQ outside
    our own vocabulary, a probe priced over `_MAX_PROBE_INSTANCES`, or the shared
    search budget firing. The caller must not treat that as "nothing later".
    """
    rule = _rrule_dict(master)
    dtstart = master.get("DTSTART")
    # Normalised HERE, not at the point of use, because both branches below
    # return from this list: the rule-less one answers straight out of it, and
    # the rule one merges it with the generated candidates.
    rdates = [_like_anchor(_period_start(r), after)
              for r in _datelist_values(master, "RDATE")]
    if dtstart is None:
        return _UNKNOWN
    if rule is None:
        # No rule at all. An RDATE-only resource is still a series — the library
        # puts RDATEs into the same rruleset and a range override governs them —
        # so answer from the list. Nothing at all generating anything is the one
        # case where "there is no next occurrence" is genuinely true.
        return _first_free(sorted(_after(rdates, after)), after, blocked,
                           _datelist_values(master, "EXDATE")) if rdates else None
    if not {str(f).upper() for f in rule.get("FREQ", [])} <= set(_FREQ.values()):
        return _UNKNOWN
    if _instances_before(rule, dtstart, after) > _MAX_PROBE_INSTANCES:
        return _UNKNOWN

    excluded = _datelist_values(master, "EXDATE")
    extra = _after(rdates, after)
    # Every slot we might have to skip, plus one that cannot be: at most
    # len(blocked) + len(excluded) are unavailable, so a free one appears within
    # that many if it exists at all. This is what makes the walk terminate — a
    # loop of `.after()` calls has no such bound.
    budget = len(blocked) + len(excluded) + 1
    try:
        start, at = _comparable(dtstart.dt, after)
        rr = rrulestr(_rule_for_probe(rule, start, dtstart.dt), dtstart=start)
        with search_budget(_MAX_SEARCH_STEPS):
            candidates = list(rr.xafter(at, count=budget))
    except (SearchBudgetExceeded, ValueError, TypeError):
        return _UNKNOWN

    # Back into the anchor's own dateness and awareness before comparing or
    # returning — `_comparable` may have stripped both ends to wall clock, and
    # the value is about to become a RECURRENCE-ID and to be SUBTRACTED from the
    # anchor by `_detach_thisandfuture`.
    #
    # `extra` goes through this too, which it did not before. Only the
    # dateutil-produced candidates were normalized; the master's RDATEs were
    # appended raw, so `_first_free` could hand back a floating datetime beside a
    # zoned anchor, or a datetime beside a DATE anchor, and `nxt - anchor` raised
    # TypeError — neither ValueError nor OverflowError, so nothing mapped it and
    # it escaped as a 500 with the occurrence left permanently uneditable. Both
    # shapes are ordinary in a shared collection: mixed zones are what
    # `_rebuild_datelist` already calls out, and a DATE-valued
    # RANGE=THISANDFUTURE override is what Apple and Thunderbird write for "this
    # and all future events".
    slots = sorted(
        [_like_anchor(nxt, after) for nxt in candidates] + extra,
        key=_as_sortable,
    )
    free = _first_free(slots, after, blocked, excluded)
    if free is not None:
        return free
    # `xafter` yields fewer than `count` when the rule runs out (COUNT/UNTIL), so
    # a short list genuinely means there is nothing left. A FULL list every entry
    # of which was blocked should be impossible — at most `len(blocked) +
    # len(excluded)` slots can be — but "impossible, so return None" is how bug B
    # lost a user's data, and None deletes the override. Fail closed instead.
    return None if len(candidates) < budget else _UNKNOWN


def _detach_thisandfuture(cal: Calendar, master: Event, governing: Event, anchor) -> Event:
    """A single-slot override for `anchor`, with the range override re-homed.

    Two components may not both claim one RECURRENCE-ID value — the reader has no
    way to rank them, and the first attempt at this fix did exactly that: it
    added a plain override beside the range one and the expansion still applied
    the range one's values to every later occurrence, so the pin stayed red for a
    reason that looked like the original bug.

    So the range override is MOVED to the next occurrence after `anchor`, keeping
    RANGE=THISANDFUTURE and shifting its DTSTART/DTEND by the same step, which
    preserves the offset it applies (`_tf_shift` is DTSTART - RECURRENCE-ID) and
    leaves it governing exactly the occurrences it governed before, minus the one
    being detached. The new single-slot override is seeded from the range
    override rather than the master so the instance keeps the values the user is
    looking at.

    If there is no next occurrence the range override governed only this slot, so
    it is dropped rather than left pointing past the end of the series. If the
    rule cannot be evaluated the edit is REFUSED — see the `_UNKNOWN` branch.

    "The next occurrence" means the next FREE one. Taking the next slot the rule
    generates, without asking whether another component already claims it, put
    two components on one RECURRENCE-ID and destroyed the edit that was there —
    the same unrankable state this docstring says the first attempt was rejected
    for, one slot over.
    """
    detached = _new_override(governing, anchor)
    # `_new_override` places DTSTART at the anchor, which is the RULE's slot —
    # but a range override that moved this-and-future to 10:00 means 10:00 is
    # what the user is looking at and clicked on. Carry its own times across, or
    # detaching one instance would silently reschedule it back to the master's
    # hour. Safe to read directly: we are here only because this override's
    # RECURRENCE-ID matched the anchor, so its DTSTART/DTEND ARE this slot's.
    for key in ("DTSTART", "DTEND", "DURATION"):
        prop = governing.get(key)
        _replace(detached, key)
        if prop is not None:
            detached.add(key, prop.dt)
    cal.add_component(detached)

    nxt = _next_generated(master, anchor,
                          blocked=_claimed_anchors(cal, exclude=governing))
    if nxt is _UNKNOWN:
        # Refuse rather than delete. Dropping the override here loses the
        # summary, the moved time and the location a foreign client authored for
        # every later occurrence, permanently, on the next PUT — and the user is
        # told the edit succeeded. Refusing costs them one edit and names a scope
        # that works. `patch_event` maps this to 422 and `update_event` to a
        # ToolError, so the sentence below is what they actually read.
        raise ValueError(
            "this occurrence is covered by a 'this and future' change and the "
            "series' repeat rule cannot be evaluated here; edit the whole series "
            "instead, or change the repeat first"
        )
    if nxt is None:
        cal.subcomponents = [c for c in cal.subcomponents if c is not governing]
        return detached

    step = nxt - anchor
    _replace(governing, "RECURRENCE-ID")
    governing.add("RECURRENCE-ID", nxt, parameters={"RANGE": "THISANDFUTURE"})
    for key in ("DTSTART", "DTEND"):
        prop = governing.get(key)
        if prop is not None:
            moved = prop.dt + step
            _replace(governing, key)
            governing.add(key, moved)
    return detached


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
        raise NotEditable("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id, master)
    # Before anything is created: an orphan RECURRENCE-ID is not an inert record,
    # it reads back as a live occurrence. See `_require_addressable`.
    _require_addressable(cal, master, anchor)
    override = _find_override(cal, anchor)
    if override is None:
        # Seeded from whatever GOVERNS this slot, which is not always the
        # master. A RANGE=THISANDFUTURE override carries the values for its own
        # slot and every later one (RFC 5545 §3.2.13), so on a slot it COVERS
        # but does not ANCHOR, the master is not what the user is looking at.
        # Seeding from the master snapped the instance back to the master's hour
        # and dropped the LOCATION the range override supplied — a "rename this
        # one" that silently rescheduled the meeting and moved the room.
        #
        # `_detach_thisandfuture` one branch down already carries DTSTART/DTEND
        # across for exactly this reason; this is the same argument for the
        # branch that had never been given it, and `_governing_thisandfuture`
        # has been sitting in this file unconsulted here.
        governing = _governing_thisandfuture(cal, anchor)
        override = _new_override(governing or master, anchor)
        if governing is not None:
            # `_new_override` puts DTSTART at the anchor — the RULE's slot — so
            # the range override's own shift has to be re-applied, not copied:
            # its DTSTART/DTEND belong to ITS anchor, several occurrences back.
            # `_tf_shift` is that offset (DTSTART - RECURRENCE-ID), the same
            # quantity the read path computes to place these instances.
            shift = _tf_shift(governing)
            for key in ("DTSTART", "DTEND"):
                prop = override.get(key)
                if prop is not None:
                    _replace(override, key)
                    override.add(key, prop.dt + shift)
        cal.add_component(override)
    elif _is_thisandfuture(override.get("RECURRENCE-ID")):
        # `_find_override` matches on the RECURRENCE-ID instant and ignores
        # RANGE, so editing "this event" on the slot a THISANDFUTURE override
        # ANCHORS used to mutate that shared component in place — and RFC 5545
        # §3.2.13 makes it carry the values for its own slot AND every later
        # occurrence, so the rename, the move, the new location silently applied
        # to all of them, permanently, in the bytes PUT to Radicale.
        #
        # This is the third path with this hazard: `exclude_occurrence` and
        # `split_series` were each given a guard when their turn came, and
        # `_is_thisandfuture` has been sitting in this file unconsulted here.
        override = _detach_thisandfuture(cal, master, override, anchor)
    # An override is a single instance; it never carries the series rule.
    _apply_event_fields(override, replace(edit, rrule=UNSET), now)
    return cal.to_ical()


def exclude_occurrence(
    raw: bytes | str, recurrence_id: str, *, now: datetime | None = None
) -> bytes:
    """Delete one instance ("this event"): add EXDATE to the master for the slot
    and drop any override that had moved/edited it.

    A `RANGE=THISANDFUTURE` override is the exception, and it is why the drop
    predicate below is not just "same RECURRENCE-ID". RFC 5545 §3.2.13 makes
    such a component carry the edits for its own slot AND every later one —
    Apple Calendar's and Thunderbird's "this and all future events", a shape
    this repo explicitly supports (see `recur._thisandfuture_shifts`). Removing
    it to delete a single occurrence threw away the times, summary, location
    and everything else a foreign client had authored for all subsequent
    occurrences, which silently snapped back to the master's values. The EXDATE
    alone already removes the instance the user asked about, and leaves the
    later ones covered."""
    now = now or datetime.now(timezone.utc)
    cal = Calendar.from_ical(raw)
    master = _find_master_event(cal)
    if master is None:
        raise NotEditable("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id, master)
    # An EXDATE matching no occurrence is a write that answers 204 and deletes
    # nothing, while the SPA optimistically removes the row. See
    # `_require_addressable`.
    _require_addressable(cal, master, anchor)
    master.add("EXDATE", anchor)
    cal.subcomponents = [
        c for c in cal.subcomponents
        if not (
            getattr(c, "name", "") == "VEVENT"
            and c.get("RECURRENCE-ID") is not None
            and _same_instant(c.get("RECURRENCE-ID").dt, anchor)
            and not _is_thisandfuture(c.get("RECURRENCE-ID"))
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


def _keep_params(params) -> dict:
    """A property's parameters minus the two icalendar re-derives from the value.

    TZID has to go: icalendar writes it from the value's tzinfo, so carrying the
    source line's copy onto a rewritten value relabels the instant. VALUE too —
    it follows the value's type, and a stale ``VALUE=DATE-TIME`` left on a DATE
    is invalid iCalendar. Everything else rides along, which is the point:
    ``RANGE=THISANDFUTURE`` on a RECURRENCE-ID (RFC 5545 §3.2.13, written by
    Apple Calendar and others) means "this override covers this and every later
    occurrence", so dropping it silently collapses the override to one instance
    and every later occurrence reverts to the master."""
    return {k: v for k, v in params.items() if k.upper() not in ("TZID", "VALUE")}


def _shift_value(value, delta: timedelta):
    """Shift a date, datetime, or RDATE period by ``delta``. Adding to the
    original value keeps its type and tzinfo, so a zone-aware series keeps its
    wall-clock time across DST boundaries."""
    if isinstance(value, tuple):
        start, second = value
        # A period is (start, end) or (start, duration); a duration is a span,
        # not an instant, so only the start moves.
        return (start + delta, second if isinstance(second, timedelta) else second + delta)
    return value + delta


def _shift_datelike(event: Event, key: str, delta: timedelta) -> None:
    prop = event.get(key)
    if prop is None:
        return
    old, params = prop.dt, _keep_params(prop.params)
    _replace(event, key)
    event.add(key, _shift_value(old, delta), parameters=params)


def _datelist_group(value) -> tuple:
    """Values that can share one EXDATE/RDATE property line: same value type and
    same zone. icalendar derives a single TZID for a whole property, so a line
    must never mix them."""
    if isinstance(value, tuple):
        return ("PERIOD", str(getattr(value[0], "tzinfo", None)))
    if isinstance(value, datetime):
        return ("DATE-TIME", str(value.tzinfo))
    return ("DATE", None)


def _rebuild_datelist(event: Event, key: str, fn) -> None:
    """Rewrite every EXDATE/RDATE entry through ``fn`` — which returns a new
    value, or None to drop that entry — emitting one property line per source
    line. Leaves the property untouched when ``fn`` changed nothing.

    Rebuilding per line is load-bearing. Flattening every line into one property
    lets icalendar derive a single TZID for the whole set (it takes the last
    entry's zone) while still serializing each value in its own local wall time,
    so entries written in another zone come back out labelled as a different
    instant — and a UTC value beside a TZID one emits ``EXDATE;TZID=...:...Z``,
    which RFC 5545 §3.2.19 forbids outright. Mixed zones are ordinary in a
    shared collection: an exclusion written before the user changed the event's
    zone sits right next to one written after."""
    prop = event.get(key)
    if prop is None:
        return
    lists = prop if isinstance(prop, list) else [prop]
    rebuilt: list[tuple[list, dict]] = []
    changed = False
    for lst in lists:
        params = _keep_params(lst.params)
        groups: dict[tuple, list] = {}
        for entry in lst.dts:
            new = fn(entry.dt)
            if new is None:
                changed = True
                continue
            changed = changed or new != entry.dt
            groups.setdefault(_datelist_group(new), []).append(new)
        for group, values in groups.items():
            line = dict(params)
            if group[0] == "PERIOD":
                line["VALUE"] = "PERIOD"   # the one VALUE icalendar cannot re-derive
            rebuilt.append((values, line))
    if not changed:
        return
    _replace(event, key)
    for values, line in rebuilt:
        event.add(key, values, parameters=line)


def _shift_datelist(event: Event, key: str, delta: timedelta) -> None:
    """Shift every EXDATE/RDATE entry (possibly across several property lines)."""
    _rebuild_datelist(event, key, lambda v: _shift_value(v, delta))


def _shift_until(until, delta: timedelta, master: Event):
    """Move an UNTIL by `delta` measured in the series' OWN zone.

    `delta` is a wall-clock offset — the same one DTSTART is shifted by, and
    DTSTART is usually zone-aware (TZID), so its UTC instant moves by
    `delta ± the DST change`. UNTIL, though, is required to be UTC for a
    zone-aware rule (`_coerce_until` normalises it there), and adding the same
    wall-clock delta to a UTC instant moves it by exactly `delta`. When the
    shift carries the series across a DST transition the two disagree by an
    hour and UNTIL lands BEFORE the final generated occurrence, which is then
    silently dropped — the user drags a bounded series a week and quietly loses
    its last event. Nothing downstream repairs it: `_set_rrule`/`_coerce_until`
    pass an already-UTC UNTIL through unchanged.

    So re-express UNTIL in the series' zone, add the wall-clock delta there, and
    convert back — the same discipline `_shift_value` applies to DTSTART.
    Floating and DATE-valued UNTILs are already wall clock and keep the old
    path."""
    dtstart = master.get("DTSTART")
    zone = getattr(getattr(dtstart, "dt", None), "tzinfo", None)
    high = delta >= timedelta(0)
    if not isinstance(until, datetime):
        # A DATE-valued UNTIL: date.max is the edge here, not datetime.max.
        try:
            return until + delta
        except (OverflowError, ValueError):
            return date.max - _UNTIL_GUARD if high else date.min + _UNTIL_GUARD
    if zone is None or until.tzinfo is None:
        return _safely(lambda: _saturate(until) + delta,
                       high=high, tzinfo=until.tzinfo)
    return _safely(lambda: (_saturate(until).astimezone(zone) + delta).astimezone(timezone.utc),
                   high=high, tzinfo=timezone.utc)


# BY* parts that name WHICH DAY the rule fires on. Moving DTSTART without them
# leaves the rule pointing at the old day, so the series desynchronizes from its
# own start. BYDAY is handled separately: a plain weekday list on a WEEKLY rule
# rotates cleanly, an ordinal one ("1TU") does not.
_DAY_SELECTING = ("BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS")

# ...and the parts that name WHICH TIME OF DAY it fires at. Exactly the same
# failure, one axis over, and the guard used to miss it twice: these were not in
# the tuple above, and the `if not day_delta` early return bailed out before the
# loop precisely when a time-only drag was in progress — which is the only time
# they matter. `FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4` dragged 09:00 -> 11:00
# moved DTSTART and left BYHOUR naming 9, so the series produced Jan 5 at 11:00
# and then three unmoved 09:00s and a FIFTH occurrence, because COUNT is
# consumed from a later start. The bytes go to Radicale, so the loss is
# permanent and visible in every other client.
_TIME_SELECTING = ("BYHOUR", "BYMINUTE", "BYSECOND")


def _desynchronizing(rule: dict, day_delta: int, new_weekday: int | None = None,
                     *, time_changed: bool = False) -> str | None:
    """The BY* part a shift would leave naming the old slot, if any.

    Two axes, and a shift can move along either or both. `day_delta` is the
    change in CALENDAR DAY and `time_changed` is whether the wall-clock time of
    day moved — derived by the caller from the same delta, so a drag inside one
    day has `day_delta == 0` and a whole-day drag has `time_changed` false.

    `new_weekday` is the weekday (Mon=0) DTSTART has AFTER the shift — the
    caller has already applied it — and is needed only for the BYDAY case below.
    None means "unknown", which keeps the old conservative answer."""
    if time_changed:
        for key in _TIME_SELECTING:
            if rule.get(key):
                return key
    if not day_delta:
        # A time-only drag moves nothing else — but only once the time-selecting
        # parts above have had their say. This return is where they used to be
        # missed.
        return None
    for key in _DAY_SELECTING:
        if rule.get(key):
            return key
    byday = [str(d).upper() for d in rule.get("BYDAY", [])]
    if byday and not all(c in _WEEKDAYS for c in byday):
        return "BYDAY"                      # ordinal, e.g. 1TU — not a rotation
    if byday and "WEEKLY" not in [str(f).upper() for f in rule.get("FREQ", [])]:
        # REVERTED to a refusal after an attempt to allow this was shown to lose
        # data. The reasoning that looked right: under a FREQ shorter than
        # WEEKLY, BYDAY is a FILTER over the days the rule already generates
        # rather than a selector pinning it to one weekday, so a shift landing
        # inside the set "desynchronizes nothing" — and
        # `FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR` (Google Calendar's "Every weekday")
        # is a common series to want to drag.
        #
        # It is wrong twice, and the second reason is the fatal one:
        #
        #  1. The occurrence set does not move. Every weekday is still in the
        #     set whatever weekday DTSTART lands on, so allowing the drag
        #     produces a series that did not move — not what was asked for.
        #  2. Everything AROUND the rule moves anyway. `shift_series` shifts
        #     every EXDATE, RDATE and RECURRENCE-ID by `delta` before this runs.
        #     With the rule's own days unchanged, a +2-day drag of an MWF
        #     standup moved an EXDATE off the occurrence the user had deleted
        #     and onto a live one — the deleted instance came back, a real one
        #     vanished, and an override's RECURRENCE-ID landed on a day the rule
        #     never generates, rendering as a duplicate beside the series.
        #
        # `new_weekday` is kept in the signature and unused, so the next attempt
        # starts from the note above rather than rediscovering it.
        return "BYDAY"                      # only the WEEKLY rotation is handled
    return None


def _shift_rrule(master: Event, delta: timedelta, day_delta: int) -> None:
    """UNTIL moves with the series (preserving the occurrence count), and a
    WEEKLY BYDAY list rotates with the day offset so "every Mon" dragged one
    day becomes "every Tue".

    Every other day-selecting BY* part makes the reschedule impossible to
    express, and the old docstring's "left untouched" was not the no-op it
    sounds like: `shift_series` moves DTSTART by `delta` while `BYMONTHDAY` /
    ordinal `BYDAY` / `BYMONTH` keep naming the OLD day, so the new DTSTART no
    longer satisfies the rule. Dragging one occurrence of a DAVx5-style
    `FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4` by a day turned Jan 6/Feb 6/Mar 6/Apr 6
    into Jan 7/Feb 6/Mar 6/Apr 6/**May 6** — five occurrences instead of four,
    only the dragged one moved, and a May the user never asked for, because COUNT
    is now consumed from a later start. `FREQ=MONTHLY;BYDAY=1TU` behaves the
    same. Those are the ordinary shapes DAVx5, jtx, Thunderbird and Apple write
    for "monthly", so this is not an exotic input, and the write goes to Radicale
    so the loss is permanent.

    Refusing is the honest answer and the one the audit recommends: rotating
    BYMONTHDAY across month lengths, ordinal BYDAY across weeks, and BYMONTH
    across a year boundary is a lot of arithmetic to get subtly wrong, and the
    user has a working alternative the error names. It is the same shape as the
    all-day/timed refusal `shift_series` already raises, and `patch_event` maps
    ValueError to 422.
    """
    rule = _rrule_dict(master)
    if rule is None:
        return
    # DTSTART has ALREADY been shifted by the caller when this runs, so this is
    # the weekday the series would end up on — which is exactly what the BYDAY
    # property test below needs.
    dtstart = master.get("DTSTART")
    start_value = getattr(dtstart, "dt", None)
    new_weekday = start_value.weekday() if start_value is not None else None
    # The wall-clock time of day moved iff the delta is not a whole number of
    # days. `timedelta` normalises to (days, seconds, microseconds) with the
    # sub-day parts always non-negative, so this reads correctly for a backwards
    # drag too: -2h is `timedelta(days=-1, seconds=79200)`.
    time_changed = bool(delta.seconds or delta.microseconds)
    blocker = _desynchronizing(rule, day_delta, new_weekday, time_changed=time_changed)
    if blocker is not None:
        axis = "time" if blocker in _TIME_SELECTING else "day"
        raise ValueError(
            f"cannot move a series whose repeat rule pins it to a particular {axis} "
            f"({blocker}); edit the occurrence instead, or change the repeat"
        )
    changed = False
    if "UNTIL" in rule:
        rule["UNTIL"] = [_shift_until(u, delta, master) for u in rule["UNTIL"]]
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
        raise NotEditable("resource has no dated VEVENT to edit")

    anchor = _anchor_from_iso(recurrence_id, master)
    if isinstance(anchor, datetime) != isinstance(edit.dtstart, datetime):
        raise ValueError(
            "cannot switch a series between all-day and timed with 'all events'; "
            "edit single occurrences instead"
        )

    repeat_changed = edit.rrule is not UNSET and _rule_changed(master, edit.rrule)
    override = _find_override(cal, anchor)

    # The anchor is not just a label here: it is the BASE the delta is measured
    # from, and that delta moves EVERY occurrence, the RRULE's UNTIL, both date
    # lists and every override's RECURRENCE-ID. So an anchor naming no
    # occurrence does not fail — it silently reschedules the whole series by an
    # amount nobody asked for. Measured: an anchor from an unrelated resource
    # moved every occurrence back four hours and left the series otherwise
    # intact, so nothing about the result said it had happened.
    _require_addressable(cal, master, anchor, whole_series=True)

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
    # picks up its stamp here. Reconciling last, so it judges the overrides by
    # the RECURRENCE-IDs the shift above just gave them.
    _apply_event_fields(master, replace(edit, dtstart=UNSET, dtend=UNSET), now)
    if repeat_changed:
        _reconcile_overrides(cal, master)
    return cal.to_ical()


def _until_before(anchor) -> date | datetime:
    if isinstance(anchor, datetime):
        return _as_utc(anchor - timedelta(seconds=1))
    return anchor - timedelta(days=1)


def _bound_head_rule(master: Event, rule: dict, anchor) -> None:
    """Bound the head's rule at the split. **Narrowing only, never widening.**

    A split cuts a series in two; it cannot conjure occurrences. But the head
    used to be rebounded unconditionally — `rule.pop("COUNT"); rule["UNTIL"] =
    anchor - 1s` — on the assumption that the anchor is always a slot the RRULE
    itself generates, where that can only narrow.

    It is not always. `_require_occurrence` deliberately accepts an anchor named
    by an **RDATE**, and an RDATE routinely sits *after* where the rule stopped —
    that is the ordinary reason to add one ("the weekly run ended in January,
    plus one extra session in March"). For those, dropping COUNT and writing a
    later UNTIL EXTENDED the rule, and every slot between the rule's real end and
    the anchor became a live occurrence.

    Measured: `RRULE:FREQ=DAILY;COUNT=3` + `RDATE:20260210T090000Z` is four
    occurrences; "this and following" on the RDATE produced a 36-occurrence head.
    Reachable in two clicks — the SPA offers the scope picker on an RDATE row
    like any other — and `delete_event(scope="thisandfuture")` PUTs the head, so
    33 events the owner never created were written permanently into the shared
    Radicale collection, where they also start blocking the public booking page.

    So each bound is compared before it is replaced, and a rule that already ends
    before the anchor is left exactly as it is — the RDATE partition alone is
    then the whole split, which is correct.
    """
    cut = _until_before(anchor)
    existing = rule.get("UNTIL")
    if existing:
        current, new = _comparable(existing[0], cut)
        if current <= new:
            return                          # already ends before the anchor
    elif rule.get("COUNT"):
        dtstart = master.get("DTSTART")
        try:
            original = int(rule["COUNT"][0])
        except (TypeError, ValueError):
            original = 0
        # `_count_consumed` under-counts rather than over-counts when its search
        # budget runs out, so this can only fail towards the old behaviour — and
        # the old behaviour is exactly right whenever the anchor IS a rule slot.
        if original and dtstart is not None and (
            _count_consumed(rule, dtstart.dt, anchor) >= original
        ):
            return                          # every slot it makes is already before
    rule.pop("COUNT", None)
    rule["UNTIL"] = [cut]
    _set_rrule(master, rule)


def _rrule_dict(master: Event) -> dict | None:
    rrule = master.get("RRULE")
    if rrule is None:
        return None
    rule = rrule[0] if isinstance(rrule, list) else rrule
    return {k: list(v) for k, v in rule.items()}


# What the tail's master must own itself, so a fold cannot overwrite the split's
# own decisions (its new identity, its rebased start, its remaining rule).
_MASTER_OWNS = frozenset({
    "UID", "RECURRENCE-ID", "RRULE", "RDATE", "EXDATE",
    "DTSTART", "DTEND", "DURATION", "DTSTAMP", "SEQUENCE",
})


def _is_thisandfuture(rid) -> bool:
    """Does this RECURRENCE-ID govern every later occurrence too (RFC 5545
    §3.2.13)? One place, because getting it wrong in either direction loses
    another client's edits."""
    return rid is not None and str(rid.params.get("RANGE", "")).upper() == "THISANDFUTURE"


def _governing_thisandfuture(cal: Calendar, anchor):
    """The ``RANGE=THISANDFUTURE`` override that governs `anchor`, if any.

    Such an override carries the values for its own slot *and every later one*
    (RFC 5545 §3.2.13), so when a split lands after one, that override — not the
    master — is what the tail actually looks like, even though its RECURRENCE-ID
    sits back in the head. The latest one strictly before the anchor wins; one at
    or after it belongs to the tail and is re-homed as an ordinary override.
    """
    best = None
    for c in cal.walk("VEVENT"):
        rid = c.get("RECURRENCE-ID")
        if not _is_thisandfuture(rid):
            continue
        if _at_or_after(rid.dt, anchor):
            continue
        if best is None or _at_or_after(rid.dt, best.get("RECURRENCE-ID").dt):
            best = c
    return best


def _tf_shift(override) -> timedelta:
    """How far a THISANDFUTURE override moves the occurrences it governs.

    The same quantity `recur._thisandfuture_shifts` computes on the read path
    (its own DTSTART minus its RECURRENCE-ID), with the same guard: a pair that
    disagrees about dateness has no meaningful offset, so it contributes none.
    """
    rid, dtstart = override.get("RECURRENCE-ID"), override.get("DTSTART")
    if rid is None or dtstart is None:
        return timedelta(0)
    # Dateness AND awareness. A floating value beside a zoned one is two
    # datetimes, so the dateness check alone passes and the subtraction raises
    # TypeError — see recur._same_shape, the read-path twin of this guard, which
    # had the identical gap.
    if isinstance(rid.dt, datetime) != isinstance(dtstart.dt, datetime):
        return timedelta(0)
    if isinstance(rid.dt, datetime) and (rid.dt.tzinfo is None) != (dtstart.dt.tzinfo is None):
        return timedelta(0)
    return dtstart.dt - rid.dt


def _fold_override(master: Event, override) -> None:
    """Copy a governing override's values onto the tail's master.

    Folded rather than carried across as a component: the tail is a new resource
    with a new UID, so an override whose RECURRENCE-ID names a slot back in the
    head would replace nothing and render as a duplicate.

    Subcomponents (VALARM) are replaced wholesale rather than merged, because an
    override IS the complete event for the occurrences it covers — its reminder
    set is authoritative, including when it is empty.
    """
    for key in list(override.keys()):
        if key.upper() in _MASTER_OWNS:
            continue
        _replace(master, key)
        master[key] = override[key]
    master.subcomponents = [copy.deepcopy(c) for c in override.subcomponents]


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
    _rebuild_datelist(
        event, key, lambda v: v if _at_or_after(v, anchor) != keep_before else None
    )


def _require_addressable(cal: Calendar, master: Event, anchor, *,
                         whole_series: bool = False) -> None:
    """Refuse an anchor that names no occurrence of this resource.

    `split_series` has demanded this since the stale-anchor finding recorded on
    `_require_occurrence`; the other three anchored write paths did not, and a
    stale anchor reaches all four the same two ways — a second tab holding an
    older expansion, and `engine`'s retry re-applying the caller's
    `recurrence_id` against a fresh copy after a 412. The MCP tools and the HTTP
    route take `recurrence_id` straight from the caller, so an invented one is a
    third.

    What each path did with an anchor naming nothing, measured on
    `FREQ=WEEKLY;COUNT=3` with a Friday anchor against a Tuesday series:

      * `apply_occurrence_override` ADDED AN EVENT. The orphan RECURRENCE-ID is
        not inert — `expand_occurrences` takes it for an instance, so the set
        went from three occurrences to four and "edit this one" put a meeting on
        the calendar that nothing generates. `_link_busy` builds the public
        booking page's conflict set from that same expansion, so it also removes
        an hour the owner never blocked.
      * `shift_series` rescheduled the WHOLE series by a delta measured from the
        slot that does not exist.
      * `exclude_occurrence` wrote an EXDATE matching nothing: the write returns
        204, the SPA optimistically drops the row, and the occurrence is still
        there on the next read.

    Three shapes are addressable without probing anything, and all three are
    checked first so the guard cannot refuse work that already succeeds: an
    instant an override component already claims (the resource itself vouches
    for it, however it got there), the master's own DTSTART, and — via
    `_require_occurrence` — an RDATE. Everything else is priced by the rule, on
    that function's terms, including its allow-when-unprobeable policy.

    The DTSTART shape is per caller, which `whole_series` says. It is right for
    `shift_series` unconditionally: scope='all' with a `recurrence_id` on a
    one-off is a plain reschedule, and the anchor is only the base the delta is
    measured from. For the two per-occurrence writers it is right only when the
    resource REPEATS, and this used to accept it before asking. On a plain
    event whose only "occurrence" is its DTSTART, `exclude_occurrence` wrote an
    `EXDATE` beside no rule and `apply_occurrence_override` appended a
    RECURRENCE-ID component — both PUT fine, the route answered 204/200, the
    MCP tool reported `{"deleted": uid, "scope": "this"}` — and every Smylte
    read then showed the untouched master, because `has_rrule` is derived from
    RRULE/RDATE alone and `find_component` never picks an override. The stray
    EXDATE also survived a later "make it repeat" and silently ate the new
    series' first occurrence. Other CalDAV clients may honour what Smylte
    ignores, so the same UID could show two titles indefinitely.
    """
    if _find_override(cal, anchor) is not None:
        return
    rule = _rrule_dict(master)
    repeats = rule is not None or bool(_datelist_values(master, "RDATE"))
    dtstart = master.get("DTSTART")
    if dtstart is not None and hasattr(dtstart, "dt") and _same_instant(dtstart.dt, anchor):
        if repeats or whole_series:
            return
        # `_require_occurrence`'s sentence, which for a per-occurrence scope on a
        # one-off is exactly the advice: the edit the caller wants IS scope='all'.
        raise ValueError("this event does not repeat; use scope='all'")
    if not repeats:
        # `_require_occurrence`'s wording for a non-repeating event tells the
        # caller to use scope='all'. Two of the three callers here ARE a
        # per-occurrence scope, and the third IS scope='all' — so that sentence
        # is either irrelevant or actively wrong. Name the real problem.
        raise ValueError("recurrence_id does not name an occurrence of this event")
    _require_occurrence(master, rule, anchor)


def _require_occurrence(master: Event, rule: dict | None, anchor) -> None:
    """Refuse a "this and following" split the resource cannot support.

    `split_series` derived the head purely from the master's RRULE, with no
    `else` branch and no check that the anchor is a slot the rule generates. Two
    silently wrong outcomes followed:

    * On a NON-RECURRING event the head came back completely unbounded and a tail
      was minted anyway, so one event became two resources with two UIDs — and
      because the tail carries the original's ATTENDEE/ORGANIZER, a second
      invitation. The delete variant PUT the unchanged resource, answered 204,
      and the SPA optimistically removed a row that still existed.
    * On a real series a STALE anchor (two tabs, or `engine.split_event`
      re-applying a `recurrence_id` against a fresh copy after a 412) bounded the
      head at an instant that was never an occurrence and restarted the tail's
      rule from it, moving every later occurrence.

    Both raise ValueError, which `patch_event` and the MCP tools already map to a
    clean 422.

    An RDATE-only resource is a legitimate series, so the check is "does anything
    generate this anchor", not "is there an RRULE". The membership probe reuses
    `_reconcile_overrides`' cost guard for the reason recorded there: the anchor
    is caller-supplied and dateutil walks from DTSTART to reach it. Over the
    limit the probe is skipped and the split is ALLOWED — the same safe direction
    that function takes, since refusing an edit is the outcome with a cost.
    """
    dtstart = master.get("DTSTART")
    if dtstart is None:
        return
    rdates = _datelist_values(master, "RDATE")
    if any(_same_instant(_period_start(r), anchor) for r in rdates):
        return
    if rule is None:
        if rdates:
            # A pure RDATE list that does not name this anchor.
            raise ValueError(
                "recurrence_id does not name an occurrence of this series")
        raise ValueError("this event does not repeat; use scope='all'")
    if _same_instant(dtstart.dt, anchor):
        return                              # the series' own first occurrence
    if not {str(f).upper() for f in rule.get("FREQ", [])} <= set(_FREQ.values()):
        # The same FREQ whitelist `_reconcile_overrides` uses, for the same
        # reason: probing a foreign rule means letting dateutil iterate from its
        # DTSTART, and a rule outside our own vocabulary is not one we can price.
        return
    if _instances_before(rule, dtstart, anchor) > _MAX_PROBE_INSTANCES:
        return
    try:
        start, at = _comparable(dtstart.dt, anchor)
        rr = rrulestr(_rule_for_probe(rule, start, dtstart.dt), dtstart=start)
        with search_budget(_MAX_SEARCH_STEPS):
            generated = bool(rr.between(at, at, inc=True))
    except (SearchBudgetExceeded, ValueError, TypeError):
        return                              # unprobeable: allow, as above
    if not generated:
        raise ValueError("recurrence_id does not name an occurrence of this series")


def _count_consumed(rule: dict, dtstart: date | datetime, anchor) -> int:
    """How many RRULE-generated occurrences fall strictly before `anchor` — the
    head's share of a COUNT-bounded series. (EXDATE'd instances still consume
    COUNT per RFC 5545, and RDATE additions never do, so the raw rule is the
    right thing to enumerate.)"""
    start, end = _comparable(dtstart, anchor)
    rr = rrulestr(vRecur(rule).to_ical().decode(), dtstart=start)
    consumed = 0
    try:
        # NOT finite just because the rule carries COUNT — that was the comment
        # here, and it is wrong for the same reason UNTIL is: dateutil tests
        # COUNT only when it produces an instance, so a rule that never matches
        # walks to year 9999 regardless. Measured 3.53s on the authenticated
        # "this and following" split path with FREQ=DAILY;COUNT=5;BYMONTH=2;
        # BYMONTHDAY=30. Filed as its own finding rather than fixed silently.
        with search_budget(_MAX_SEARCH_STEPS):
            for occ in rr:
                if occ >= end:
                    break
                consumed += 1
    except SearchBudgetExceeded:
        # The head consumed whatever the walk found before the budget ran out.
        # The caller already clamps this to at least 1, so a zero here is safe.
        pass
    return consumed


def split_series(
    raw: bytes | str, recurrence_id: str, edit: EventEdit, *, now: datetime | None = None
) -> tuple[bytes | None, bytes]:
    """Split a series at `recurrence_id` ("this and following"). Returns
    (head_ics, tail_ics): the head is the original resource with its rule bounded
    to end just before the anchor; the tail is a brand-new resource (new UID)
    starting at the anchor with the remaining recurrence and the edits applied.

    The head is **None** when the split leaves it generating nothing — the
    anchor is the series' first occurrence — because a bounded-to-empty VEVENT
    is not something to write. The caller deletes the resource instead; see
    `_head_is_empty`.
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
        raise NotEditable("resource has no VEVENT to edit")
    anchor = _anchor_from_iso(recurrence_id, hmaster)
    # The same guard shift_series has, for the same reason. Without it
    # `_wall_delta(edit.dtstart, base)` below subtracts a `date` from a
    # `datetime` and raises TypeError, which `patch_event` does not map (it
    # catches ValueError), so it escaped as a 500. The SPA reaches this in one
    # click: the modal renders the "all day" checkbox for a recurring event too,
    # and a non-'all' scope sends a bare date string with no all_day flag.
    if edit.dtstart is not UNSET and edit.dtstart is not None and (
        isinstance(anchor, datetime) != isinstance(edit.dtstart, datetime)
    ):
        raise ValueError(
            "cannot switch a series between all-day and timed with 'this and following'; "
            "edit single occurrences instead"
        )
    rule = _rrule_dict(hmaster)
    _require_occurrence(hmaster, rule, anchor)
    if rule is not None:
        _bound_head_rule(hmaster, rule, anchor)
    _drop_overrides(head, anchor, keep_before=True)
    _partition_datelist(hmaster, "RDATE", anchor, keep_before=True)
    _partition_datelist(hmaster, "EXDATE", anchor, keep_before=True)
    _stamp(hmaster, now)

    # Tail: fresh UID, DTSTART=anchor, remaining rule, later overrides re-homed.
    tail = Calendar.from_ical(raw)
    tmaster = _find_master_event(tail)
    repeat_changed = edit.rrule is not UNSET and _rule_changed(tmaster, edit.rrule)
    new_uid = f"{uuid4().hex}@tasksd"
    dur = _event_duration(tmaster)
    orig_start = tmaster.get("DTSTART").dt if tmaster.get("DTSTART") is not None else anchor

    # A THISANDFUTURE override before the split governs the whole tail, so fold
    # it into the tail's master before `_drop_overrides` discards it below.
    # Without this the tail snapped back to the master's values — losing the
    # summary, location, alarms, attendees and X- properties the user had set for
    # every one of these occurrences — and because the tail is written with a
    # fresh UID, that loss was permanent.
    governing = _governing_thisandfuture(tail, anchor)
    shift = timedelta(0)
    if governing is not None:
        shift = _tf_shift(governing)
        gov_dur = _event_duration(governing)
        if gov_dur is not None:
            dur = gov_dur                 # the override may also change length
        _fold_override(tmaster, governing)

    # The shift is what keeps the tail at the time the user actually sees: an
    # override that moved this-and-future to 10:00 means the tail's occurrences
    # are at 10:00, not back at the rule's original hour.
    start = anchor + shift if shift else anchor
    _replace(tmaster, "DTSTART")
    tmaster.add("DTSTART", start)
    _replace(tmaster, "DURATION")
    _replace(tmaster, "DTEND")
    if dur is not None:
        tmaster.add("DTEND", start + dur)
    tail_rule = _rrule_dict(tmaster)
    if tail_rule is not None:
        if "COUNT" in tail_rule:
            remaining = int(tail_rule["COUNT"][0]) - _count_consumed(
                tail_rule, orig_start, anchor
            )
            # The anchor is an occurrence, so ≥1 remains for any sane split;
            # clamp defensively so a bad anchor can't emit COUNT=0 (invalid).
            tail_rule["COUNT"] = [max(remaining, 1)]
        elif tail_rule.get("UNTIL"):
            # The other half of `_bound_head_rule`'s problem. When the anchor is
            # an RDATE past the rule's own end, the tail inherits an UNTIL that
            # now precedes its own DTSTART — a rule that generates nothing, sat
            # next to a DTSTART that does, which is not a series at all. The
            # anchor is a one-off; say so by dropping the rule rather than
            # shipping a self-contradicting one.
            until, start_at = _comparable(tail_rule["UNTIL"][0], start)
            if until < start_at:
                tail_rule = None
                _replace(tmaster, "RRULE")
    if tail_rule is not None:
        _set_rrule(tmaster, tail_rule)
    _drop_overrides(tail, anchor, keep_before=False)
    _partition_datelist(tmaster, "RDATE", anchor, keep_before=False)
    _partition_datelist(tmaster, "EXDATE", anchor, keep_before=False)
    for ev in tail.walk("VEVENT"):
        _replace(ev, "UID")
        ev.add("UID", new_uid)

    # A time change with "this and following" moves the whole tail, so the tail
    # has to move as a unit — the way shift_series already moves a whole series.
    # Letting _apply_event_fields write edit.dtstart/dtend onto the master alone
    # left every other anchor in the tail pinned to the old slots: the
    # partitioned EXDATE/RDATE stopped matching any generated slot (so a deleted
    # occurrence came back) and each re-homed override's RECURRENCE-ID stopped
    # replacing anything (so it rendered as a duplicate alongside the generated
    # instance).
    #
    # The offset is measured from the anchor occurrence's CURRENT start — its
    # override's DTSTART if one moved it, else the anchor itself — as in
    # shift_series. That also fixes a pure title edit: CalendarView sends the
    # displayed times on every "this and following" save, so an occurrence a
    # previous override had moved reported a start that differed from the anchor
    # and silently rescheduled the entire tail.
    delta = timedelta(0)
    if edit.dtstart is not UNSET and edit.dtstart is not None:
        base = anchor
        src_override = _find_override(Calendar.from_ical(raw), anchor)
        if src_override is not None and src_override.get("DTSTART") is not None:
            base = src_override.get("DTSTART").dt
        if isinstance(anchor, datetime) and not isinstance(base, datetime):
            base = datetime.combine(base, time())
        elif not isinstance(anchor, datetime) and isinstance(base, datetime):
            base = base.date()
        delta = _wall_delta(edit.dtstart, base)

    # A new end resizes the tail master (overrides keep their own spans).
    duration = None
    if edit.dtend is not UNSET and edit.dtend is not None:
        if edit.dtstart is not UNSET and edit.dtstart is not None:
            duration = _wall_delta(edit.dtend, edit.dtstart)
        elif dur is not None:
            duration = dur

    if delta or duration is not None:
        tail_start = tmaster.get("DTSTART").dt
        shifted = tail_start + delta
        day_delta = (
            (shifted.date() if isinstance(shifted, datetime) else shifted)
            - (tail_start.date() if isinstance(tail_start, datetime) else tail_start)
        ).days
        for ev in tail.walk("VEVENT"):
            is_master = "RECURRENCE-ID" not in ev
            _shift_datelike(ev, "RECURRENCE-ID", delta)
            _shift_datelike(ev, "DTSTART", delta)
            if duration is not None and is_master:
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

    # Non-time fields land on the master, which also picks up its stamp here.
    _apply_event_fields(tmaster, replace(edit, dtstart=UNSET, dtend=UNSET), now)
    if repeat_changed:
        _reconcile_overrides(tail, tmaster)
    return (None if _head_is_empty(head, anchor) else head.to_ical()), tail.to_ical()


def _head_is_empty(head: Calendar, anchor) -> bool:
    """Would the bounded head generate nothing at all?

    The head is always bounded with `UNTIL = anchor - 1s` (or -1 day for
    all-day). When the anchor IS the series' first occurrence that UNTIL is
    earlier than the head's own DTSTART, so its recurrence set is empty — and
    PUTting it left a VEVENT on Radicale, and a cache row, that expands to zero
    occurrences forever: `events_in_range` never emits it, so the app can never
    render or delete it again. For "delete this and following" from the first
    occurrence — the natural way to remove a whole series from an occurrence
    chip — the server answered 204 and the SPA cleared the rows while nothing
    had actually been deleted.

    A surviving RDATE before the anchor still generates an occurrence, so the
    head is only empty when there is none.
    """
    master = _find_master_event(head)
    if master is None:
        return True
    dtstart = master.get("DTSTART")
    if dtstart is None:
        return False
    if not _at_or_after(dtstart.dt, anchor):
        return False        # the rule still generates occurrences before the split
    rdates = master.get("RDATE")
    for prop in (rdates if isinstance(rdates, list) else [rdates] if rdates else []):
        for value in getattr(prop, "dts", []):
            start = _period_start(value.dt)
            if not _at_or_after(start, anchor):
                return False
    return True
