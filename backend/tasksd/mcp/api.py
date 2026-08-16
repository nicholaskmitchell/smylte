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
from contextlib import contextmanager
from datetime import date, datetime, time as time_of_day, timedelta

from ..ical import EventEdit, TaskEdit, rrule_from_spec
from ..service import priority_from_label
from .tools import ToolError

# A free/busy sweep loads every event in the window across every calendar, so
# the window is bounded. A year is far more than any scheduling question needs.
MAX_RANGE_DAYS = 366


def _parse_dt(value, *, field: str):
    """A date or datetime, with the same rules the HTTP API uses.

    Empty means "unset" rather than an error, because that is how a caller
    clears a due date — the tool schemas say so explicitly.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if "T" in s or " " in s:
            return datetime.fromisoformat(s.replace(" ", "T"))
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


_DURATION = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
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
    m = _DURATION.match(str(value).strip())
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


def _display_order(t: dict):
    """The order the app shows tasks in, which is what these tools advertise.

    Mirrors `frontend/src/order.ts` — manual position, due date, priority, title,
    then uid — key for key, including nulls-last on every one. The two cannot
    share code across languages, so they are kept deliberately parallel: the tool
    description promises "ordered the way the app shows them", and a model paging
    with `limit` is entitled to that being true.

    The final uid tie-break is the point, not a flourish. Rows arrive here as one
    list's block after another's, so without a TOTAL order `limit=3` returned
    "whichever list came first" — and the soonest deadline on the account could
    be missing from a page that looked ordered. `order.ts`' header makes the same
    argument at length.

    Sort keys are `(is_null, value)` pairs so a missing value sorts last without
    ever comparing None to a number.
    """
    due = t.get("due") or None
    # A date-only due sorts as that day's start, which is how the app reads it.
    due_key = f"{due}T00:00" if due and "T" not in due else due
    priority = t.get("priority") or None       # iCal: 0/absent means unset
    order = t.get("sort_order")
    summary = t.get("summary") or None
    return (
        (order is None, order or 0),
        (due_key is None, due_key or ""),
        (priority is None, priority or 0),
        (summary is None, (summary or "").casefold()),
        t.get("uid") or "",
    )


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

    # ── resolution ───────────────────────────────────────────────────────────

    def _href(self, list_id: str, *, kind: str = "list") -> str:
        href = self._svc.resolve_list(list_id)
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

    def update_collection(self, list_id, *, name=None, color=None):
        if name is None and color is None:
            raise ToolError("Nothing to change — pass a name or a color.")
        return self._svc.update_collection(
            self._href(list_id), name=name, color=color, clear_color=False
        )

    def delete_collection(self, list_id):
        self._svc.delete_collection(self._href(list_id))

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
        out.sort(key=_display_order)
        return out

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
        if scope in ("this", "thisandfuture") and not recurrence_id:
            raise ToolError(f"scope={scope!r} needs recurrence_id.")
        # Same reason as delete_task: a silent no-op reported as a deletion.
        href = self._href(calendar_id, kind="calendar")
        if self._svc.get_event(href, uid) is None:
            raise ToolError(f"No event {uid!r} on calendar {calendar_id!r} to delete.")
        with _not_found(f"No event {uid!r} on calendar {calendar_id!r} to delete."):
            self._svc.delete_event(
                href, uid, recurrence_id=recurrence_id, scope=scope,
            )

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
            b_start = _as_dt(_parse_dt(event.get("start"), field="start"))
            if b_start is None:
                continue
            b_end = _as_dt(_parse_dt(event.get("end"), field="end"))
            if b_end is None:
                # DURATION is the other half of the pair — an event carries one
                # or the other, never both — so it has to be read before any
                # fallback, or the fallback silently shortens a real meeting.
                length = parse_duration(event.get("duration"))
                if length:
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
