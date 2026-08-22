"""The adapter between the MCP tools and `TaskService`.

`TaskService` speaks collection hrefs and iCalendar edit objects; the tools
speak list ids, plain strings and JSON. This is the layer that translates, and
it exists so the tool table stays declarative — every handler in tools.py is one
line, and every awkwardness about the underlying API lives here where it can be
explained.

It also adds the two things the HTTP API has no reason to offer but a model
badly needs: filters that would otherwise mean fetching everything and sifting
it in the transcript, and `find_free_time`, which is a genuine computation
rather than a passthrough.

Errors raised here are `ToolError` — read by the model, not thrown at the
client. The distinction matters: a 500 tells it nothing, a sentence tells it
what to try instead.
"""
from __future__ import annotations

import re
import secrets
from contextlib import contextmanager
from datetime import date, datetime, time as time_of_day, timedelta
from zoneinfo import ZoneInfo

from ..ical import EventEdit, TaskEdit, rrule_from_spec
from ..ical.read import normalize_offset, split_duration
from ..service import day_key as _day_key, priority_from_label
from .tools import ToolError

# A free/busy sweep loads every event in the window across every calendar, so
# the window is bounded. A year is far more than any scheduling question needs.
MAX_RANGE_DAYS = 366


def _parse_dt(value, *, field: str):
    """A date or datetime, with the same rules the HTTP API uses.

    Empty means "unset" rather than an error, because that is how a caller
    clears a due date — the tool schemas say so explicitly.

    "The same rules the HTTP API uses" was an assertion this function did not
    keep: it is a second hand-written copy of `app._parse_datelike`, and both
    handed an offset-bearing value straight through to icalendar, which wrote it
    as a fabricated `TZID="UTC-07:00"`. The shared part now lives in
    `ical.read.normalize_offset` so the sentence is true by construction rather
    than by inspection — this sweep filed five findings whose common shape is a
    comment asserting a safety property the code does not deliver.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if "T" in s or " " in s:
            return normalize_offset(datetime.fromisoformat(s.replace(" ", "T")))
        return date.fromisoformat(s)
    except ValueError:
        raise ToolError(
            f"{field}={s!r} is not a date I can read. Use 'YYYY-MM-DD' for an "
            f"all-day value or 'YYYY-MM-DDTHH:MM' for a timed one."
        ) from None


def _as_dt(value: date | datetime | None) -> datetime | None:
    """A date-or-datetime flattened to a naive local datetime for comparison.

    All-day values become midnight. Zone-aware values are converted to the local
    wall clock and stripped, so an event another CalDAV client anchored to a
    zone compares against a local working window the way a person would read it.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    return datetime.combine(value, time_of_day.min)


# `fullmatch` at the call site, not `match`: `$` also matches before a trailing
# newline. The caller's `.strip()` happens to cover this one today — which is
# exactly why it is worth fixing at the pattern, where the guarantee belongs.
_DURATION = re.compile(
    r"(?P<sign>[+-])?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?"
)


def parse_duration(value: str | None) -> timedelta | None:
    """An RFC 5545 DURATION, e.g. 'PT1H30M' or 'P2D'.

    An event may carry DURATION *instead of* DTEND — the two are mutually
    exclusive — and the DTO passes it through untouched with `end` left null.
    Without reading it, a two-hour meeting written that way looked like a
    zero-length point, and the free/busy sweep's fallback reported the rest of
    it as free time to offer someone.
    """
    if not value:
        return None
    m = _DURATION.fullmatch(str(value).strip())
    if not m:
        return None
    parts = {k: int(v) for k, v in m.groupdict().items() if k != "sign" and v}
    if not parts:
        return None
    delta = timedelta(weeks=parts.get("w", 0), days=parts.get("d", 0),
                      hours=parts.get("h", 0), minutes=parts.get("m", 0),
                      seconds=parts.get("s", 0))
    # A negative DURATION is legal iCalendar but meaningless on a VEVENT; treat
    # it as unknown rather than letting it run the busy block backwards.
    return None if m.group("sign") == "-" else delta


def _hhmm(value: str, *, field: str) -> time_of_day:
    try:
        h, m = str(value).split(":")
        return time_of_day(int(h), int(m))
    except (ValueError, TypeError):
        raise ToolError(f"{field}={value!r} is not a time. Use 'HH:MM'.") from None


def _due_instant(t: dict, zone) -> float | None:
    """A task's deadline as an absolute instant, the way `dueAt` computes it.

    `order.ts` resolves a date-only due against BROWSER-local midnight and a
    naive timed due against the browser's zone. `_as_dt` resolved both against
    the SERVER's — `value.astimezone().replace(tzinfo=None)` — and the two only
    agree when the two zones do. With the browser in America/Chicago and the
    server in UTC, which is the ordinary Docker deployment, a task due 23:00
    local and an all-day task the next day swap places; this ordering is what
    decides which rows `limit` keeps, so the soonest deadline can fall off a page
    that looks ordered.

    `zone` is the owner's `home_timezone` — the honest stand-in for "the zone
    they read their calendar in", and the same value `busy_intervals` already
    uses for floating times. None keeps the previous behaviour (the server's
    local zone), which is what a caller with no service handle gets.
    """
    raw = t.get("due")
    if not raw:
        return None
    value = _parse_dt(raw, field="due")
    if value is None:
        return None
    if not isinstance(value, datetime):
        value = datetime.combine(value, time_of_day.min)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone) if zone is not None else value.astimezone()
    return value.timestamp()


def _intrinsic_order(t: dict, zone=None):
    """Everything except the manual position: due, priority, title, then uid.

    The port of `compareIntrinsic` in `frontend/src/order.ts`. `due` is compared
    as an INSTANT rather than as a string — lexical comparison happens to agree
    for ISO values of equal shape and stops agreeing the moment a date-only and a
    timed value meet, or an offset appears — and the instant is resolved in the
    reader's zone rather than the server's. See `_due_instant`.

    Sort keys are `(is_null, value)` pairs so a missing value sorts last without
    ever comparing None to a number. The final uid tie-break is the point, not a
    flourish: rows arrive as one list's block after another's, so without a TOTAL
    order `limit=3` returned "whichever list came first" and the soonest deadline
    on the account could be missing from a page that looked ordered.
    """
    due = _due_instant(t, zone)
    priority = t.get("priority") or None       # iCal: 0/absent means unset
    summary = t.get("summary") or None
    return (
        (due is None, due if due is not None else 0.0),
        (priority is None, priority or 0),
        (summary is None, _title_key(summary or "")),
        t.get("uid") or "",
    )


def _title_key(s: str) -> tuple:
    """A sort key approximating `String.prototype.localeCompare`.

    order.ts compares titles with `localeCompare`, which is a collation, not a
    codepoint comparison: case is a TERTIARY difference, and lowercase sorts
    before uppercase for otherwise identical letters. Python's `<` is codepoint
    order (so "Alpha" < "alpha") and `casefold` alone calls them equal — either
    way the two implementations put "alpha" and "Alpha" in different places, and
    this ordering is what decides which rows `limit` keeps.

    Casefold first, then lowercase-before-uppercase, which reproduces ICU for
    the ASCII case. It does NOT reproduce full ICU: accent folding ("é" sorting
    with "e") needs a collation table the stdlib does not carry, so a title
    differing only by an accent may land on the other side of its neighbour. The
    uid tie-break keeps the result a deterministic total order regardless, which
    is the property `limit` actually depends on; a cross-check against the real
    order.ts over 400 generated cases is recorded in the pin.
    """
    return (s.casefold(), tuple(0 if c.islower() else 1 for c in s))


def _task_key(t: dict) -> tuple:
    """A task's identity ACROSS lists — `taskKey` in order.ts.

    `list_tasks` merges every list's rows, and the backend keys items on
    `(collection_href, uid)`, so the same uid genuinely appears twice when a
    VTODO has been copied between lists in another CalDAV client. Keyed on the
    bare uid, the unplaced-task loop below overwrites the placed twin's entry.
    """
    return (t.get("list") or "", t.get("uid") or "")


def _in_display_order(tasks: list[dict], zone=None) -> list[dict]:
    """`tasks` in the order the app shows them, as a new list.

    The port of `sortTasks`, which is what every view calls — NOT of
    `compareTasks`, which is what this used to reproduce. `compareTasks` sorts a
    null position last, and order.ts' own docstring says at length why that is
    not how a list is ordered: a drag renumbers the whole account (the server's
    `ReorderTasks` model says so explicitly — "nothing left null once a drag
    lands"), so after the first drag a null position stops meaning "ordinary,
    unplaced" and starts meaning "created since the last drag". Sinking those
    below everything is not what anyone wants — and here it was worse than a
    display quirk, because this ordering is the ONE thing that decides which rows
    `limit` keeps. Every task made since the last drag fell off page one, while
    the tool description promises "ordered the way the app shows them".

    Not a pairwise comparator, for the reason order.ts gives: comparing
    placed-to-placed by position while comparing placed-to-unplaced by due date
    is not transitive — P1(pos 1, due Dec), P2(pos 2, due Jan), U(due Jun) gives
    P1 < P2 < U < P1 — and sorting on an inconsistent comparator is undefined.
    So each task gets ONE effective position: a placed task keeps its own,
    normalised to its index so gaps and duplicates cannot matter, and an unplaced
    task takes half a step before the first placed task it intrinsically
    precedes. Ordering by that single number, tie-broken by the intrinsic keys,
    is a total order again.
    """
    placed = sorted(
        (t for t in tasks if t.get("sort_order") is not None),
        key=lambda t: (t["sort_order"], _intrinsic_order(t, zone)),
    )
    # Nothing has been dragged — the common case, and every case before the first
    # drag: the intrinsic order is the whole answer.
    if not placed:
        return sorted(tasks, key=lambda t: _intrinsic_order(t, zone))

    at: dict[tuple, float] = {_task_key(t): float(i) for i, t in enumerate(placed)}
    keys = [_intrinsic_order(t, zone) for t in placed]
    for t in tasks:
        if t.get("sort_order") is not None:
            continue
        mine = _intrinsic_order(t, zone)
        nxt = next((i for i, k in enumerate(keys) if mine < k), -1)
        at[_task_key(t)] = float(len(placed)) if nxt < 0 else nxt - 0.5
    return sorted(tasks, key=lambda t: (at[_task_key(t)], _intrinsic_order(t, zone)))


@contextmanager
def _not_found(message: str):
    """Turn the engine's unknown-uid KeyError into an answer the model can act on.

    `SyncEngine._edit` / `_move` raise `KeyError(f"unknown {kind} {uid} ...")`
    when the uid is not in the cache, and nothing caught it — so the `is None`
    guards below were dead code, and McpServer's catch-all reported "could not be
    completed (KeyError). The calendar server may be unreachable". That sent the
    model chasing an outage that was not happening, over a typo it could have
    corrected itself.

    Caught here, at the API boundary, rather than in McpServer: a KeyError from a
    genuine dict bug must keep reporting as an internal failure, not as
    "not found".
    """
    try:
        yield
    except KeyError:
        raise ToolError(message) from None


class McpApi:
    """Everything the tools can reach, and nothing else.

    Deliberately a hand-written surface rather than a generic proxy onto
    `TaskService`: a token granted `mcp:write` should not be able to reach
    settings, session revocation or the sync engine just because they happen to
    be public methods. What is here is what the connector can do.
    """

    def __init__(self, service):
        self._svc = service

    def _home_zone(self):
        """The zone the owner reads their calendar in, or None.

        `order.ts` resolves a due date against the BROWSER's midnight; the
        server's own zone is not that, and in the ordinary Docker deployment it
        is UTC while the owner is somewhere else. `home_timezone` is the closest
        thing this process has to the reader's zone and is already what
        `busy_intervals` uses for floating times.

        Fail-soft in the same shape as `TaskService._home_tz`: a stored blob can
        hold anything, and an unusable zone must degrade to the old behaviour
        rather than break every task listing. Read through whatever the service
        exposes, so a stub without settings still works.
        """
        getter = getattr(self._svc, "get_settings", None)
        if getter is None:
            return None
        try:
            name = getter().get("home_timezone")
        except Exception:  # noqa: BLE001 — an ordering must not fail on settings
            return None
        if not isinstance(name, str) or not name:
            return None
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — a stored blob can hold anything
            return None

    # ── resolution ───────────────────────────────────────────────────────────

    _COMPONENT = {"list": "VTODO", "calendar": "VEVENT"}

    def _href(self, list_id: str, *, kind: str = "list") -> str:
        """The collection href for an id — of the right KIND.

        `kind` used to affect only the wording of the error, so every task tool
        accepted a calendar id and every calendar tool accepted a task-list id:
        `smylte_delete_list` deleted calendars, and `smylte_create_task` wrote a
        VTODO into an event-only calendar where no reader in this app would ever
        return it again.
        """
        href = self._svc.resolve_list(list_id, component=self._COMPONENT.get(kind))
        if href is None:
            raise ToolError(
                f"There is no {kind} with id {list_id!r}. Call "
                f"smylte_list_{'calendars' if kind == 'calendar' else 'lists'} "
                f"to see the ids that exist."
            )
        return href

    # ── lists and calendars ──────────────────────────────────────────────────

    def list_lists(self):
        return self._svc.list_lists()

    def list_calendars(self):
        return self._svc.list_calendars()

    def create_list(self, *, name, color=None):
        return self._svc.create_list(name, color=color)

    def create_calendar(self, *, name, color=None):
        return self._svc.create_calendar(name, color=color)

    # `kind` threaded rather than defaulted: these two back BOTH
    # smylte_update_list/smylte_delete_list AND their calendar twins, so without
    # it `smylte_delete_list(<a calendar id>)` deleted the calendar.
    def update_collection(self, list_id, *, name=None, color=None, kind="list"):
        if name is None and color is None:
            raise ToolError("Nothing to change — pass a name or a color.")
        return self._svc.update_collection(
            self._href(list_id, kind=kind), name=name, color=color, clear_color=False
        )

    def delete_collection(self, list_id, *, kind="list"):
        self._svc.delete_collection(self._href(list_id, kind=kind))

    # ── tasks ────────────────────────────────────────────────────────────────

    def _task_lists(self, list_id):
        if list_id:
            return [self._href(list_id)]
        return [l["href"] for l in self._svc.list_lists()]

    def list_tasks(self, list_id=None, *, include_done=False, due_before=None,
                   due_after=None, overdue_only=False, tag=None):
        before = _as_dt(_parse_dt(due_before, field="due_before"))
        after = _as_dt(_parse_dt(due_after, field="due_after"))
        now = datetime.now()
        rows: list[dict] = []
        for href in self._task_lists(list_id):
            rows.extend(self._svc.list_tasks(href, include_done=True))
        out = []
        for t in rows:
            if not include_done and (t["completed"] or t["cancelled"]):
                continue
            if tag and tag not in (t.get("tags") or []):
                continue
            if before or after or overdue_only:
                due = _as_dt(_parse_dt(t.get("due"), field="due"))
                if due is None:
                    continue          # a filter on the deadline excludes undated work
                if before and due >= before:
                    continue
                if after and due < after:
                    continue
                if overdue_only and (due >= now or t["completed"] or t["cancelled"]):
                    continue
            out.append(t)
        return _in_display_order(out, self._home_zone())

    def get_task(self, list_id, uid):
        task = self._svc.get_task(self._href(list_id), uid)
        if task is None:
            raise ToolError(f"No task {uid!r} in list {list_id!r}.")
        return task

    def search(self, query):
        return self._svc.search(query)

    def all_tags(self):
        return self._svc.all_tags()

    def create_task(self, list_id, *, summary, notes=None, due=None, start=None,
                    priority=None, tags=None, parent=None):
        href = self._href(list_id)
        if parent and not self._svc.has_task(href, parent):
            raise ToolError(
                f"No task {parent!r} in this list to be the parent. A subtask "
                f"has to live in the same list as its parent."
            )
        kw = {}
        if notes is not None:
            kw["description"] = notes
        if due is not None:
            kw["due"] = _parse_dt(due, field="due")
        if start is not None:
            kw["dtstart"] = _parse_dt(start, field="start")
        if priority is not None:
            kw["priority"] = priority_from_label(priority)
        if tags is not None:
            kw["categories"] = list(tags)
        return self._svc.create_task(
            href, summary, edit=TaskEdit(**kw) if kw else None, parent_uid=parent or None
        )

    def update_task(self, list_id, uid, fields: dict):
        href = self._href(list_id)
        if not fields:
            raise ToolError("Nothing to change — pass at least one field to update.")
        kw = {}
        if "summary" in fields:
            kw["summary"] = fields["summary"]
        if "notes" in fields:
            kw["description"] = fields["notes"]
        if "due" in fields:
            kw["due"] = _parse_dt(fields["due"], field="due")
        if "start" in fields:
            kw["dtstart"] = _parse_dt(fields["start"], field="start")
        if "priority" in fields:
            kw["priority"] = priority_from_label(fields["priority"])
        if "tags" in fields:
            kw["categories"] = list(fields["tags"] or [])
        if "status" in fields:
            status = str(fields["status"]).strip().upper()
            if status not in ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"):
                raise ToolError(
                    f"status={fields['status']!r} is not one of NEEDS-ACTION, "
                    f"IN-PROCESS, COMPLETED, CANCELLED."
                )
            kw["status"] = status
        if "parent" in fields:
            parent = (fields["parent"] or "").strip()
            if parent:
                if parent == uid:
                    raise ToolError("A task cannot be its own parent.")
                if not self._svc.has_task(href, parent):
                    raise ToolError(f"No task {parent!r} in this list to be the parent.")
            kw["related_parent"] = parent or None
        with _not_found(f"No task {uid!r} in list {list_id!r}."):
            task = self._svc.edit_task(href, uid, TaskEdit(**kw))
        if task is None:
            raise ToolError(f"No task {uid!r} in list {list_id!r}.")
        return task

    def complete_task(self, list_id, uid, *, done=True):
        with _not_found(f"No task {uid!r} in list {list_id!r}."):
            task = self._svc.complete_task(self._href(list_id), uid, done=done)
        if task is None:
            raise ToolError(f"No task {uid!r} in list {list_id!r}.")
        return task

    def cancel_task(self, list_id, uid):
        with _not_found(f"No task {uid!r} in list {list_id!r}."):
            task = self._svc.cancel_task(self._href(list_id), uid)
        if task is None:
            raise ToolError(f"No task {uid!r} in list {list_id!r}.")
        return task

    def delete_task(self, list_id, uid):
        # Checked BEFORE the delete, because the engine returns silently when the
        # uid is not in the cache and the tool then answers `{"deleted": uid}`
        # regardless — telling the model a task is gone that never existed, or
        # that is alive in a different list, so it reports success and stops.
        href = self._href(list_id)
        if not self._svc.has_task(href, uid):
            raise ToolError(f"No task {uid!r} in list {list_id!r} to delete.")
        with _not_found(f"No task {uid!r} in list {list_id!r} to delete."):
            self._svc.delete_task(href, uid)

    # ── events ───────────────────────────────────────────────────────────────

    def _event_calendars(self, calendar_id):
        if calendar_id:
            return [self._href(calendar_id, kind="calendar")]
        return [c["href"] for c in self._svc.list_calendars()]

    def _range(self, start, end):
        s = _parse_dt(start, field="start")
        e = _parse_dt(end, field="end")
        if s is None or e is None:
            raise ToolError("Both start and end are required, as 'YYYY-MM-DD' or ISO datetimes.")
        sd, ed = _as_dt(s), _as_dt(e)
        if ed <= sd:
            raise ToolError("end must be after start.")
        if (ed - sd).days > MAX_RANGE_DAYS:
            raise ToolError(
                f"That range is longer than {MAX_RANGE_DAYS} days. Ask for a "
                f"narrower window."
            )
        return s, e, sd, ed

    def list_events(self, start, end, calendar_id=None):
        s, e, _, _ = self._range(start, end)
        rows: list[dict] = []
        for href in self._event_calendars(calendar_id):
            rows.extend(self._svc.events_in_range(href, s.isoformat(), e.isoformat()))
        rows.sort(key=lambda r: (r.get("start") or "", r.get("summary") or ""))
        return rows

    def get_event(self, calendar_id, uid):
        event = self._svc.get_event(self._href(calendar_id, kind="calendar"), uid)
        if event is None:
            raise ToolError(f"No event {uid!r} on calendar {calendar_id!r}.")
        return event

    def create_event(self, calendar_id, *, summary, start, end=None, all_day=False,
                     location=None, description=None, tags=None, repeat=None,
                     repeat_interval=1, repeat_count=None, repeat_until=None):
        href = self._href(calendar_id, kind="calendar")
        dtstart = self._event_dt(start, all_day, field="start")
        dtend = self._event_dt(end, all_day, field="end") if end else None
        if dtstart is None:
            raise ToolError("start is required.")
        kw = {}
        if description is not None:
            kw["description"] = description
        if location is not None:
            kw["location"] = location
        if tags is not None:
            kw["categories"] = list(tags)
        if repeat is not None:
            kw["rrule"] = self._rrule(repeat, repeat_interval, repeat_count, repeat_until)
        event = self._svc.create_event(
            href, summary, dtstart=dtstart, dtend=dtend,
            edit=EventEdit(**kw) if kw else None,
        )
        if event is None:
            raise ToolError("The event was written but could not be read back.")
        return event

    @staticmethod
    def _event_dt(value, all_day, *, field):
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        if all_day:
            try:
                return date.fromisoformat(s)
            except ValueError:
                raise ToolError(
                    f"{field}={s!r} — an all-day event needs a bare date, 'YYYY-MM-DD'."
                ) from None
        return _parse_dt(s, field=field)

    @staticmethod
    def _rrule(repeat, interval, count, until):
        try:
            return rrule_from_spec(
                repeat,
                interval=int(interval or 1),
                until=_parse_dt(until, field="repeat_until"),
                count=int(count) if count else None,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def update_event(self, calendar_id, uid, fields: dict):
        href = self._href(calendar_id, kind="calendar")
        scope = fields.get("scope") or "all"
        if scope not in ("all", "this", "thisandfuture"):
            raise ToolError("scope must be 'all', 'this' or 'thisandfuture'.")
        recurrence_id = fields.get("recurrence_id")
        if scope in ("this", "thisandfuture") and not recurrence_id:
            raise ToolError(
                f"scope={scope!r} needs recurrence_id — the occurrence's slot, "
                f"which smylte_list_events returns on every expanded occurrence."
            )
        kw = {}
        for key, target in (("summary", "summary"), ("description", "description"),
                            ("location", "location")):
            if key in fields:
                kw[target] = fields[key]
        if "start" in fields:
            kw["dtstart"] = _parse_dt(fields["start"], field="start")
        if "end" in fields:
            kw["dtend"] = _parse_dt(fields["end"], field="end")
        if "tags" in fields:
            kw["categories"] = list(fields["tags"] or [])
        if "status" in fields:
            status = str(fields["status"]).strip().upper()
            if status not in ("CONFIRMED", "TENTATIVE", "CANCELLED"):
                raise ToolError(
                    f"status={fields['status']!r} is not CONFIRMED, TENTATIVE or CANCELLED."
                )
            kw["status"] = status
        if "repeat" in fields:
            kw["rrule"] = self._rrule(
                fields["repeat"], fields.get("repeat_interval", 1),
                fields.get("repeat_count"), fields.get("repeat_until"),
            )
        if not kw:
            raise ToolError("Nothing to change — pass at least one field to update.")
        try:
            with _not_found(f"No event {uid!r} on calendar {calendar_id!r}."):
                event = self._svc.edit_event(
                    href, uid, EventEdit(**kw), recurrence_id=recurrence_id, scope=scope
                )
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        if event is None:
            raise ToolError(f"No event {uid!r} on calendar {calendar_id!r}.")
        return event

    def move_event(self, calendar_id, uid, to_calendar_id):
        src = self._href(calendar_id, kind="calendar")
        dst = self._href(to_calendar_id, kind="calendar")
        with _not_found(f"No event {uid!r} on calendar {calendar_id!r}."):
            event = self._svc.move_event(src, dst, uid)
        if event is None:
            raise ToolError(f"No event {uid!r} on calendar {calendar_id!r}.")
        return event

    def delete_event(self, calendar_id, uid, *, recurrence_id=None, scope="all"):
        if scope not in ("all", "this", "thisandfuture"):
            raise ToolError("scope must be 'all', 'this' or 'thisandfuture'.")
        # `.strip()`, like the HTTP route: "   " is not an anchor, and `not
        # recurrence_id` alone let it through to be parsed deep in the edit path.
        if scope in ("this", "thisandfuture") and not (recurrence_id or "").strip():
            raise ToolError(f"scope={scope!r} needs recurrence_id.")
        # Same reason as delete_task: a silent no-op reported as a deletion.
        href = self._href(calendar_id, kind="calendar")
        if self._svc.get_event(href, uid) is None:
            raise ToolError(f"No event {uid!r} on calendar {calendar_id!r} to delete.")
        with _not_found(f"No event {uid!r} on calendar {calendar_id!r} to delete."):
            try:
                self._svc.delete_event(
                    href, uid, recurrence_id=recurrence_id, scope=scope,
                )
            except ValueError as exc:
                # The arm update_event already had. Without it, an unreadable
                # recurrence_id reached `date.fromisoformat` in the edit path and
                # McpServer's catch-all reported it as "the calendar server may
                # be unreachable" — sending the model after an outage that was
                # not happening, over an argument it chose and could fix.
                raise ToolError(str(exc)) from None

    # ── free/busy ────────────────────────────────────────────────────────────

    def find_free_time(self, start, end, *, minutes=30, calendar_id=None,
                       day_start="09:00", day_end="17:00"):
        """Gaps of at least `minutes` inside the working window of each day.

        All-day events are treated as blocking their whole day: an all-day entry
        usually means "this day is spoken for", and reporting the day as wide
        open because the event carries no times would be actively misleading.
        """
        s, e, sd, ed = self._range(start, end)
        open_from = _hhmm(day_start, field="day_start")
        open_to = _hhmm(day_end, field="day_end")
        if open_to <= open_from:
            raise ToolError("day_end must be later than day_start.")
        span = timedelta(minutes=max(5, int(minutes)))

        busy: list[tuple[datetime, datetime]] = []
        for event in self.list_events(start, end, calendar_id):
            if (event.get("status") or "").upper() == "CANCELLED":
                continue
            raw_start = _parse_dt(event.get("start"), field="start")
            b_start = _as_dt(raw_start)
            if b_start is None:
                continue
            b_end = _as_dt(_parse_dt(event.get("end"), field="end"))
            if b_end is None:
                # DURATION is the other half of the pair — an event carries one
                # or the other, never both — so it has to be read before any
                # fallback, or the fallback silently shortens a real meeting.
                #
                # `advance` splits the duration the way RFC 5545 §3.3.6
                # defines it — the weeks/days half is NOMINAL ("a day later" is
                # the same wall-clock time tomorrow, 23 or 25 real hours across
                # a transition) and the time half is EXACT — and it applies
                # each half in whatever frame it is handed. So the frame is the
                # whole of this fix, and getting it wrong is two different bugs:
                #
                #   * `b_start + length` (the original) adds everything to the
                #     wall clock, so the EXACT half is an hour out across a
                #     transition. That is the defect Stage 3 closed at
                #     scheduling.py:163.
                #   * `advance(raw_start, …)` — the first repair — hands it the
                #     value `normalize_offset` produced, which is **UTC**. UTC
                #     has no transitions, so the nominal half becomes 24 real
                #     hours; `_as_dt` then converts back to LOCAL, where the
                #     transitions do live, and the NOMINAL half is an hour out.
                #     It fixed one half by breaking the other.
                #
                # So each half is applied in its OWN frame, which is the only
                # arrangement that gets both right:
                #
                #   exact  -> added to the aware value, i.e. to the INSTANT,
                #             and only then flattened to local;
                #   nominal-> added to that local WALL CLOCK afterwards.
                #
                # `advance` does this split too, but it can only do it correctly
                # given a value carrying a real zone, and nothing here has one:
                # `normalize_offset` has already re-expressed the start as UTC,
                # and `.astimezone()` yields a FIXED OFFSET rather than a zone,
                # so nominal arithmetic on either cannot see a transition. Hence
                # the split is done here, against `split_duration`, which is the
                # same decomposition `advance` uses.
                #
                # Checked both ways round: `P1D` from 09:00 the day before the
                # fall-back must end 09:00 the next day (25 real hours), and
                # `PT2H` from 01:30 before the spring-forward must end 04:30
                # (2 real hours). `P1DT2H` needs both halves at once.
                parts = split_duration(event.get("duration"))
                length = parse_duration(event.get("duration"))
                if parts is not None:
                    nominal, exact = parts
                    b_end = _as_dt(raw_start + exact if isinstance(raw_start, datetime)
                                   else raw_start) + nominal
                elif length:
                    # Unparseable text but a usable total: no worse off than the
                    # plain addition this replaced.
                    b_end = b_start + length
            if event.get("all_day"):
                # DTEND is exclusive for an all-day event; with none, it is one day.
                b_end = b_end or (b_start + timedelta(days=1))
            elif b_end is None or b_end <= b_start:
                # Genuinely unknown: assume a short meeting rather than none at
                # all, since reporting occupied time as free is the worse error.
                b_end = b_start + timedelta(minutes=30)
            busy.append((b_start, b_end))
        busy.sort()

        merged: list[list[datetime]] = []
        for b_start, b_end in busy:
            if merged and b_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b_end)
            else:
                merged.append([b_start, b_end])

        free: list[dict] = []
        day = sd.date()
        while datetime.combine(day, time_of_day.min) < ed:
            window_start = max(datetime.combine(day, open_from), sd)
            window_end = min(datetime.combine(day, open_to), ed)
            cursor = window_start
            for b_start, b_end in merged:
                if b_end <= cursor or b_start >= window_end:
                    continue
                if b_start - cursor >= span:
                    free.append({"start": cursor.isoformat(timespec="minutes"),
                                 "end": b_start.isoformat(timespec="minutes")})
                cursor = max(cursor, b_end)
            if window_end - cursor >= span:
                free.append({"start": cursor.isoformat(timespec="minutes"),
                             "end": window_end.isoformat(timespec="minutes")})
            # MAX_RANGE_DAYS bounds how LONG the range is, not where it ends, so
            # a range finishing inside 9999-12-31 walked the cursor off date.max
            # and raised OverflowError — outside every handler, from an argument
            # the calling model chooses.
            if day >= date.max:
                break
            day += timedelta(days=1)
        return free

    # ── scheduling ───────────────────────────────────────────────────────────

    def list_booking_links(self):
        return self._svc.list_booking_links()

    def list_bookings(self, link=None):
        return self._svc.list_bookings(link)

    def update_booking_link(self, token, fields: dict):
        if not fields:
            raise ToolError("Nothing to change — pass at least one field to update.")
        try:
            link = self._svc.update_booking_link(token, dict(fields))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        if link is None:
            raise ToolError(
                f"No booking link {token!r}. Call smylte_list_booking_links for the tokens."
            )
        return link

    # ── the day ──────────────────────────────────────────────────────────────
    #
    # Two rules govern everything here, and both exist because the caller is a
    # model rather than a browser.
    #
    # A model has no clock. The browser resolves local midnight for itself; a
    # model's idea of the date comes from its context and may be stale or in
    # another zone, and the server's own zone is UTC in the ordinary Docker
    # deployment while the owner is somewhere else. So no tool takes a REQUIRED
    # day: every one defaults to the owner's day (`_home_zone`, the same helper
    # the task ordering uses) and every answer echoes the day it resolved.
    #
    # A read never creates. `open_day` is only ever called with create=False
    # from here, and an unplanned day is answered with `preview_day` — what
    # opening it WOULD derive — instead of by opening it. A connector that could
    # open days would fill the log with plans nobody made, and the day plan is
    # only worth keeping while it is an honest record of what the owner actually
    # intended.

    def _today(self) -> str:
        """The owner's calendar day, not the server's.

        `datetime.now(None)` is local naive time, which is the right fallback
        when `home_timezone` is unset: it is the same clock the deployment's own
        logs and the browser-on-the-same-box would use. There is no correct
        answer when the server is elsewhere and the setting is empty, which is
        what the setting is for.
        """
        return datetime.now(self._home_zone()).date().isoformat()

    def _day_or_today(self, day: str | None) -> str:
        """Validate a supplied day, or fall back to the owner's today."""
        if day is None or str(day).strip() == "":
            return self._today()
        try:
            return _day_key(str(day))
        except ValueError as exc:
            raise ToolError(f"{exc}. Omit `day` for today.") from None

    def _writable_day(self, day: str | None) -> str:
        """A day this connector may put something on: today or later, never past.

        Adding to tomorrow is ordinary planning — the owner is stating an
        intention now. Writing to a past day is something else: it manufactures a
        record of what they meant to do on a day that has already happened, and
        the whole value of this log is that it was written at the time. The plan
        can then never be told apart from a backfill, which is exactly the
        property the retrospective depends on.
        """
        resolved = self._day_or_today(day)
        today = self._today()
        if resolved < today:
            raise ToolError(
                f"{resolved} is in the past, and a past day cannot be planned — "
                f"the day plan is a record of what was intended at the time. "
                f"Today is {today}; pass that or a later day."
            )
        return resolved

    def _entries_with_tasks(self, entries: list[dict]) -> list[dict]:
        """Day entries with the task each one names folded in.

        A day entry is a POINTER: the wire stores no title and no done flag for a
        task entry, deliberately, because the VTODO is the single truth for both.
        Handing a model bare (list, uid) pairs would make it call
        smylte_get_task once per row to learn what any of them say, so the join
        happens once here instead.

        Tasks are read a LIST at a time rather than one call per entry: each
        `get_task` takes the global service lock, and a twelve-row day would take
        it twelve times behind whatever CalDAV I/O happens to be in flight.

        Every record that comes back carries `task`, whatever its kind — see the
        loop for why the alternative was a trap.
        """
        wanted = {e["list"] for e in entries if e["kind"] == "task" and e["list"]}
        by_key: dict[tuple[str, str], dict] = {}
        for list_id in sorted(wanted):
            href = self._svc.resolve_list(list_id, component="VTODO")
            if href is None:
                # The list has left the wire. The ENTRY still stands — that is
                # the no-FK guarantee — so this is a hole in the join, not an
                # error, and `task: None` below is what says so.
                continue
            for t in self._svc.list_tasks(href, include_done=True):
                by_key[(t["list"], t["uid"])] = t
        out = []
        for e in entries:
            row = dict(e)
            # `task` is set on EVERY record, null where there is nothing to join
            # to. It used to be attached only to kind="task" rows, which meant a
            # day mixing kinds handed the model TWO record shapes and the missing
            # key was the only thing separating them: a reader that reaches for
            # `row["task"]` raises on the first note or habit occurrence, and one
            # that tests `"task" in row` has learnt a rule that silently changes
            # meaning the day a fourth kind exists. A uniform shape says the same
            # thing without either failure.
            #
            # Null therefore means one of two things, and `kind` is what tells
            # them apart. On a task row it is the hole in the join: the list has
            # left the wire (the `continue` above) or the task itself has, and
            # the entry outlives either by design — there is no FK. On any other
            # kind it is structural: a note and a habit occurrence name no task
            # and never will, so there was nothing to look up in the first place.
            t = by_key.get((e["list"], e["uid"])) if e["kind"] == "task" else None
            row["task"] = None if t is None else {
                "list": t["list"], "uid": t["uid"], "summary": t["summary"],
                "due": t["due"], "due_is_date": t["due_is_date"],
                "completed": t["completed"], "cancelled": t["cancelled"],
                "priority_label": t["priority_label"],
                # Gated: nothing in this app advances a recurring VTODO
                # (docs/recurrence-findings.md). Surfaced so a model can say
                # so rather than treating it as an ordinary task.
                "has_rrule": t["has_rrule"],
            }
            out.append(row)
        return out

    def today(self) -> dict:
        """Today's plan, or a preview of one for a day that has none.

        Never writes — see the section note above. `planned` distinguishes the
        two answers, and `preview` is only ever present on the unplanned one so a
        model cannot mistake a proposal for something the owner committed to.

        Habits are the sharp edge of that. A preview row's `entry_id` is minted
        by `preview_day` and thrown away, so on a day nobody has opened the
        habits are VISIBLE but not tickable — `update_day_entry` finds no row and
        says so — and nothing in this toolset can open the day to change that.
        The tool descriptions say so outright, because the alternative is a model
        discovering it by reporting a habit done that was never recorded.
        """
        day = self._today()
        plan = self._svc.open_day(day, create=False)
        entries = self._entries_with_tasks(plan["entries"])
        out = {"day": day, "planned": plan["planned"], "entries": entries}
        if not plan["planned"]:
            out["preview"] = self._entries_with_tasks(self._svc.preview_day(day))
        return out

    def plan_day(self, *, day=None, list_id=None, uid=None, title=None) -> dict:
        """Put one task or one note on a day.

        Exactly one of (list_id + uid) or title, checked here because the tool
        schemas cannot express it: `mcp/validate.py` implements no oneOf, and a
        keyword it does not implement would be advertised and silently
        unenforced.

        The entry_id is minted here rather than asked of the model. A model holds
        nothing between calls, so an id it invented would be fresh on every
        retry and could not deduplicate anything — but `add_day_entry` also
        matches on the task and on the note text, which is the idempotency that
        actually applies to this caller.
        """
        resolved = self._writable_day(day)
        has_task, has_note = bool(list_id or uid), bool(title and title.strip())
        if has_task and has_note:
            raise ToolError(
                "Pass either list_id + uid (to put an existing task on the day) "
                "or title (for a one-off note), not both."
            )
        if not has_task and not has_note:
            raise ToolError(
                "Nothing to add. Pass list_id + uid to put an existing task on "
                "the day, or title for a one-off note."
            )
        if has_task and not (list_id and uid):
            raise ToolError(
                "A task entry needs BOTH list_id and uid. Call smylte_list_tasks "
                "to find them, or pass title instead for a one-off note."
            )
        if has_task:
            self._href(list_id)          # raises the standard ToolError if unknown
        try:
            return self._svc.add_day_entry(
                resolved, entry_id=secrets.token_hex(16),
                kind="task" if has_task else "note",
                list_id=list_id, uid=uid, title=title,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    def update_day_entry(self, entry_id, *, day=None, done=None, dropped=None,
                         position=None) -> dict:
        """Tick a note or a habit occurrence, or drop any entry off a day.

        `done` on a TASK entry is refused by the service, and the message points
        at smylte_complete_task rather than restating the refusal: a task's
        doneness is its VTODO STATUS, which every other client on the account
        reads too, and recording it here as well would give the same question two
        answers that disagree the moment the task is ticked anywhere else. A note
        and a habit occurrence are the opposite case — they live only in the day
        plan, so the stamp written here is the only record there is.

        Which is why `done` is refused on a PAST day; see below.
        """
        if done is None and dropped is None and position is None:
            raise ToolError(
                "Nothing to change — pass done, dropped or position."
            )
        resolved = self._day_or_today(day)
        # NOT `_writable_day`, which would refuse the whole call: this tool has
        # to keep working on a past day, because only ONE of the three fields is
        # a claim about what happened.
        #
        # `done` is that one. It says "this was actually done", and the only
        # thing that makes the stamp worth anything is that it was written on the
        # day. A habit is where the difference bites: its occurrence is ticked
        # HERE and nowhere else, so a model backfilling "yes, Tuesday too" is not
        # tidying a record, it is writing the record — these rows are the only
        # thing the app counts into a habit's "n of m this week", and afterwards
        # nothing distinguishes a filled-in tick from a kept one. `done=False`
        # is refused for the same reason in the other direction: erasing a tick
        # made on the day rewrites the day just as thoroughly.
        #
        # `dropped` and `position` are not claims about what happened. Dropping
        # says "this did not happen", which SUBTRACTS from the day rather than
        # adding to it — no record is manufactured by admitting a plan went
        # unmet, and the row itself stays (the service stamps, never deletes), so
        # the day still shows it was planned. A position is only the order the
        # rows are read in. Tidying history is not falsifying it, so both stay
        # allowed on any day.
        #
        # `_habit_minting_allowed` draws the same line on the other half of the
        # rule — a PAST day is given no habit rows, whether it is being opened
        # for the first time or topped up — and it allows one day of grace there
        # for a browser whose local day key is behind the server's. None is needed here: both sides of the comparison
        # below are resolved server-side in the owner's own zone (`_day_or_today`
        # falls back to `_today`, and an explicit `day` is compared against it),
        # so a day that reads as past IS past, and the message says which day the
        # owner is actually on.
        today = self._today()
        if done is not None and resolved < today:
            raise ToolError(
                f"{resolved} has already happened, so `done` cannot be changed "
                f"on it — a tick is a record that something was done AT THE "
                f"TIME, and a habit log that can be filled in afterwards is "
                f"worth nothing. Today is {today}. You CAN still drop an entry "
                f"from {resolved} or reorder it: saying it did not happen, or "
                f"tidying the order, does not rewrite what did."
            )
        try:
            entry = self._svc.patch_day_entry(
                resolved, entry_id, done=done, dropped=dropped, position=position,
            )
        except ValueError as exc:
            raise ToolError(
                f"{exc} To finish a task, call smylte_complete_task with its "
                f"list and uid — that writes the VTODO every client reads."
            ) from None
        if entry is None:
            raise ToolError(
                f"There is no entry {entry_id!r} on {resolved}. Call "
                f"smylte_get_today for the entries on today, or smylte_review_day "
                f"with a day for another one."
            )
        return entry

    def review_day(self, *, day=None, from_day=None, to_day=None) -> dict:
        """What was planned against what actually happened.

        One day, or a range. Not both: a call carrying `day` AND `from`/`to` is
        ambiguous about which it means, and answering the wrong one silently is
        worse than a sentence saying so.

        Live entries come back bucketed by `source` — `chosen`, `carried`,
        `derived`, `habits`, and `other` for anything this code does not
        recognise — plus `dropped`. See the loop for why the residual exists.

        Completions come from the task's own COMPLETED stamp, not from the plan,
        so this answers for days before the day plan existed at all — and it
        picks up what was finished off-plan, which is usually the more
        interesting half of a retrospective.
        """
        ranged = bool(from_day or to_day)
        if day and ranged:
            raise ToolError(
                "Pass either day (one day) or from + to (a range), not both."
            )
        if ranged and not (from_day and to_day):
            raise ToolError("A range needs both from and to; `to` is exclusive.")
        if ranged:
            start, end = self._day_or_today(from_day), self._day_or_today(to_day)
            try:
                plans = self._svc.day_range(start, end)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
            days = [p["day"] for p in plans]
        else:
            resolved = self._day_or_today(day)
            plan = self._svc.open_day(resolved, create=False)
            plans = [plan] if plan["planned"] else []
            start, end, days = resolved, resolved, [resolved]
        # `end` is exclusive everywhere in this service, so a single day is the
        # half-open span [day, day+1) rather than a second code path.
        span_end = end if ranged else (
            date.fromisoformat(start) + timedelta(days=1)).isoformat()
        done_by_day = self._completions_by_day(start, span_end)
        by_day = {p["day"]: p for p in plans}
        # A day with completions but no plan still belongs in a range review:
        # `day_range` omits unplanned days by design, but finishing five things
        # on a day you never planned is exactly what a look-back should show.
        # The single-day case already asks about one named day, planned or not.
        wanted = sorted(set(by_day) | set(done_by_day)) if ranged else days
        # `source` is what makes this worth reading: it separates what the owner
        # CHOSE from what merely turned up on the day, and habits from both.
        #
        # One pass over a source→arm map, rather than one `==` comprehension per
        # arm. The arms then PARTITION the day by construction, which is the
        # property that was missing: three equality tests covered the three
        # sources that existed when they were written, so when occurrences
        # arrived carrying source="habit" they matched none of them and dropped
        # out of the retrospective in silence — the half of the day most worth
        # reviewing, since whether a habit was ticked is recorded nowhere else.
        #
        # `other` is a residual bucket and not an assertion, deliberately. An
        # assertion here raises inside a tool handler, and `server._call` turns
        # any non-ToolError into "smylte_review_day could not be completed
        # (AssertionError). The calendar server may be unreachable" — so an
        # unrecognised source would cost the model the WHOLE day's review and
        # point it at an outage that is not happening. The residual costs it one
        # unfamiliar key holding rows that carry their own `source` for it to
        # read. Always present, empty or not: an answer whose keys come and go is
        # the inconsistent shape `_entries_with_tasks` was just fixed for.
        arm_of = {"user": "chosen", "carried": "carried", "auto": "derived",
                  "habit": "habits"}
        out = []
        for d in wanted:
            plan = by_day.get(d)
            entries = self._entries_with_tasks(plan["entries"]) if plan else []
            buckets: dict[str, list] = {
                "chosen": [], "carried": [], "derived": [], "habits": [], "other": [],
            }
            for e in entries:
                # Dropped rows are their own arm and are not bucketed by source:
                # "planned it and did not do it" is one answer whatever put it
                # there.
                if not e["dropped_at"]:
                    buckets[arm_of.get(e["source"], "other")].append(e)
            out.append({
                "day": d,
                "planned": bool(plan),
                **buckets,
                "dropped": [e for e in entries if e["dropped_at"]],
                "completed_that_day": done_by_day.get(d, []),
            })
        return {"from": start, "to": end, "days": out} if ranged else out[0]

    def _completions_by_day(self, start: str, end: str) -> dict[str, list]:
        """Tasks finished in [start, end), bucketed by the day they were finished.

        Bucketed with the same rule the snapshot uses — a stamp carrying a zone
        is converted to the owner's before its day is taken — so "finished on the
        21st" means the same thing here as it does everywhere else in this app. A
        stamp that will not parse is dropped rather than guessed at, and a task
        completed by a client that wrote no COMPLETED property simply has no day
        to file it under.
        """
        zone = self._home_zone()
        out: dict[str, list] = {}
        for href in self._task_lists(None):
            for t in self._svc.list_tasks(href, include_done=True):
                stamp = t.get("completed_at")
                if not stamp:
                    continue
                try:
                    when = datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                if when.tzinfo is not None:
                    when = when.astimezone(zone)
                key = when.date().isoformat()
                if not (start <= key < end):
                    continue
                out.setdefault(key, []).append({
                    "list": t["list"], "uid": t["uid"], "summary": t["summary"],
                    "completed_at": stamp,
                })
        return out
