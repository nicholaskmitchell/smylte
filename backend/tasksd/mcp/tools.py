"""The MCP toolset over the tasks + calendar API.

One table, `TOOLS`, drives everything: what `tools/list` advertises, which scope
a call needs, and how it reaches `TaskService`. Adding a capability is one entry
rather than an edit in three places — the same shape the frontend's FIELDS table
uses for task properties.

Two things shape the schemas more than anything else:

**They are written for a reader who cannot see the app.** A description that
says "list tasks" tells a model nothing about `include_done`, that a list id may
be a slug or an href, or that undated tasks sort last. Where the API has a rule
that would otherwise have to be found by trial, it is stated here.

**Errors are answers, not exceptions.** A failed call comes back as an ordinary
result with `isError` set and a sentence saying what to do instead, because a
transport-level error tells the model only that something went wrong. The one
exception is authorization, which has to reach the client as a real 401 so it
can refresh — see server.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .oauth import SCOPE_READ, SCOPE_WRITE

# Enough to be useful, small enough that a wide query cannot bury a context
# window. Every list tool takes `limit` and reports what it held back.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class ToolError(Exception):
    """A failure the model should read and act on, not a crash."""


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    schema: dict
    handler: Callable[..., Any]
    scope: str = SCOPE_READ
    # MCP tool annotations — hints a client uses to decide what needs
    # confirmation. `destructive` is only true where data actually goes away.
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = False

    def descriptor(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                # Everything here is this account's own CalDAV data, which other
                # clients also write — so the world is not closed.
                "openWorldHint": True,
            },
        }


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


_LIST_ID = {
    "type": "string",
    "description": "Task-list id, as returned by smylte_list_lists (short slug or full href).",
}
_CAL_ID = {
    "type": "string",
    "description": "Calendar id, as returned by smylte_list_calendars (short slug or full href).",
}
_LIMIT = {
    "type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT,
    "description": f"Maximum items to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
}
_OFFSET = {
    "type": "integer", "minimum": 0, "default": 0,
    "description": "How many items to skip, for paging through a long result.",
}
_PRIORITY = {
    "type": "string", "enum": ["none", "low", "medium", "high"],
    "description": "Priority band. Maps to iCalendar PRIORITY (high=1, medium=5, low=9).",
}
_DUE = {
    "type": "string",
    "description": (
        "Due date. 'YYYY-MM-DD' for an all-day deadline, or 'YYYY-MM-DDTHH:MM' "
        "for a timed one. Send an empty string to clear it."
    ),
}
_TAGS = {
    "type": "array", "items": {"type": "string"},
    "description": "Tags (iCalendar CATEGORIES). Replaces the whole set.",
}
_SCOPE = {
    "type": "string", "enum": ["all", "this", "thisandfuture"], "default": "all",
    "description": (
        "For a repeating event: 'this' touches one occurrence, 'thisandfuture' "
        "splits the series from that point, 'all' changes the whole series. "
        "'this' and 'thisandfuture' require recurrence_id."
    ),
}
_RECURRENCE_ID = {
    "type": "string",
    "description": (
        "Which occurrence, as the `recurrence_id` from smylte_list_events. "
        "Required when scope is 'this' or 'thisandfuture'."
    ),
}
_REPEAT = {
    "type": "string", "enum": ["none", "daily", "weekly", "monthly", "yearly"],
    "description": "Repeat rule. 'none' clears an existing one.",
}


def page(rows: list, limit: int | None, offset: int | None, *, key: str) -> dict:
    """A slice plus what it left behind, so a model knows to ask for more."""
    lim = DEFAULT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    off = max(0, int(offset or 0))
    window = rows[off:off + lim]
    out = {"total": len(rows), "count": len(window), "offset": off, key: window}
    if off + len(window) < len(rows):
        out["has_more"] = True
        out["next_offset"] = off + len(window)
    return out


def build_tools(api) -> dict[str, Tool]:
    """Build the registry against `api`, the adapter over TaskService."""
    tools: list[Tool] = []

    def tool(name, title, description, schema, *, scope=SCOPE_READ, read_only=True,
             destructive=False, idempotent=False):
        def register(fn):
            tools.append(Tool(
                name=name, title=title, description=description, schema=schema,
                handler=fn, scope=scope, read_only=read_only,
                destructive=destructive, idempotent=idempotent,
            ))
            return fn
        return register

    # ── lists ────────────────────────────────────────────────────────────────

    @tool(
        "smylte_list_lists", "List task lists",
        "Every task list, with its colour and how many tasks are open in it. "
        "Start here: the other task tools need a list id.",
        _obj({}),
    )
    def _list_lists():
        return {"lists": api.list_lists()}

    @tool(
        "smylte_create_list", "Create a task list",
        "Create a task list. This is a real CalDAV collection, so it appears in "
        "every other client on this account too.",
        _obj({
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$",
                      "description": "Hex colour, #RRGGBB or #RRGGBBAA."},
        }, ["name"]),
        scope=SCOPE_WRITE, read_only=False,
    )
    def _create_list(name, color=None):
        return api.create_list(name=name, color=color)

    @tool(
        "smylte_update_list", "Rename or recolour a task list",
        "Rename a task list or change its colour. Written to the server, so "
        "other CalDAV clients see it.",
        _obj({"list_id": _LIST_ID,
              "name": {"type": "string", "minLength": 1, "maxLength": 200},
              "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$"}},
             ["list_id"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _update_list(list_id, name=None, color=None):
        return api.update_collection(list_id, name=name, color=color)

    @tool(
        "smylte_delete_list", "Delete a task list",
        "Delete a task list AND every task in it, on the server. This cannot be "
        "undone from here. Any booking link pointing at it is disabled.",
        _obj({"list_id": _LIST_ID}, ["list_id"]),
        scope=SCOPE_WRITE, read_only=False, destructive=True, idempotent=True,
    )
    def _delete_list(list_id):
        api.delete_collection(list_id)
        return {"deleted": list_id}

    # ── tasks ────────────────────────────────────────────────────────────────

    @tool(
        "smylte_list_tasks", "List tasks",
        "Tasks in one list, or across every list when list_id is omitted. "
        "Ordered the way the app shows them: manual position first, then due "
        "date (undated last), then priority, then title.",
        _obj({
            "list_id": {**_LIST_ID,
                        "description": _LIST_ID["description"] + " Omit to span every list."},
            "include_done": {"type": "boolean", "default": False,
                             "description": "Include completed and cancelled tasks."},
            "due_before": {"type": "string",
                           "description": "Only tasks due strictly before this date "
                                          "('YYYY-MM-DD' or an ISO datetime)."},
            "due_after": {"type": "string",
                          "description": "Only tasks due on or after this date."},
            "overdue_only": {"type": "boolean", "default": False,
                             "description": "Only tasks whose deadline has passed."},
            "tag": {"type": "string", "description": "Only tasks carrying this tag."},
            "limit": _LIMIT, "offset": _OFFSET,
        }),
    )
    def _list_tasks(list_id=None, include_done=False, due_before=None, due_after=None,
                    overdue_only=False, tag=None, limit=None, offset=None):
        rows = api.list_tasks(list_id, include_done=include_done, due_before=due_before,
                              due_after=due_after, overdue_only=overdue_only, tag=tag)
        return page(rows, limit, offset, key="tasks")

    @tool(
        "smylte_get_task", "Get one task",
        "One task in full, including its subtasks, tags and notes.",
        _obj({"list_id": _LIST_ID, "uid": {"type": "string"}}, ["list_id", "uid"]),
    )
    def _get_task(list_id, uid):
        return api.get_task(list_id, uid)

    @tool(
        "smylte_search_tasks", "Search tasks",
        "Full-text search over task titles, notes and tags, across every list. "
        "Searches tasks only — use smylte_list_events for calendar entries.",
        _obj({"query": {"type": "string", "minLength": 1},
              "limit": _LIMIT, "offset": _OFFSET}, ["query"]),
    )
    def _search_tasks(query, limit=None, offset=None):
        return page(api.search(query), limit, offset, key="tasks")

    @tool(
        "smylte_create_task", "Create a task",
        "Add a task to a list. Only list_id and summary are required; pass "
        "`parent` to make it a subtask of an existing task in the same list.",
        _obj({
            "list_id": _LIST_ID,
            "summary": {"type": "string", "minLength": 1, "description": "The task title."},
            "notes": {"type": "string"},
            "due": _DUE,
            "start": {"type": "string", "description": "Start date/time, same format as due."},
            "priority": _PRIORITY,
            "tags": _TAGS,
            "parent": {"type": "string",
                       "description": "uid of the parent task, which must be in the same list."},
        }, ["list_id", "summary"]),
        scope=SCOPE_WRITE, read_only=False,
    )
    def _create_task(list_id, summary, notes=None, due=None, start=None,
                     priority=None, tags=None, parent=None):
        return api.create_task(list_id, summary=summary, notes=notes, due=due,
                               start=start, priority=priority, tags=tags, parent=parent)

    @tool(
        "smylte_update_task", "Update a task",
        "Change a task. Only the fields you pass are touched; pass an empty "
        "string to clear a date, or an empty array to clear tags.",
        _obj({
            "list_id": _LIST_ID, "uid": {"type": "string"},
            "summary": {"type": "string"}, "notes": {"type": "string"},
            "due": _DUE, "start": {"type": "string"},
            "priority": _PRIORITY, "tags": _TAGS,
            "status": {"type": "string",
                       "enum": ["NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"]},
            "parent": {"type": "string",
                       "description": "Re-parent the task. Empty string promotes it to top level."},
        }, ["list_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _update_task(list_id, uid, **fields):
        return api.update_task(list_id, uid, fields)

    @tool(
        "smylte_complete_task", "Complete or reopen a task",
        "Tick a task off, or reopen it with done=false. Completing also stamps "
        "the completion time and sets progress to 100%.",
        _obj({"list_id": _LIST_ID, "uid": {"type": "string"},
              "done": {"type": "boolean", "default": True}}, ["list_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _complete_task(list_id, uid, done=True):
        return api.complete_task(list_id, uid, done=done)

    @tool(
        "smylte_cancel_task", "Mark a task won't-do",
        "Mark a task cancelled — kept for the record, but out of the active "
        "list. Use smylte_delete_task to remove it entirely.",
        _obj({"list_id": _LIST_ID, "uid": {"type": "string"}}, ["list_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _cancel_task(list_id, uid):
        return api.cancel_task(list_id, uid)

    @tool(
        "smylte_delete_task", "Delete a task",
        "Delete a task from the server for good. Prefer smylte_complete_task or "
        "smylte_cancel_task unless it should genuinely vanish.",
        _obj({"list_id": _LIST_ID, "uid": {"type": "string"}}, ["list_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, destructive=True, idempotent=True,
    )
    def _delete_task(list_id, uid):
        api.delete_task(list_id, uid)
        return {"deleted": uid}

    @tool(
        "smylte_list_tags", "List tags",
        "Every tag currently in use across all tasks. Useful before filtering "
        "smylte_list_tasks by tag, since a tag that matches nothing returns "
        "silently empty.",
        _obj({}),
    )
    def _list_tags():
        return {"tags": api.all_tags()}

    # ── calendars and events ─────────────────────────────────────────────────

    @tool(
        "smylte_list_calendars", "List calendars",
        "Every calendar, with its colour and event count. The other event tools "
        "need a calendar id from here.",
        _obj({}),
    )
    def _list_calendars():
        return {"calendars": api.list_calendars()}

    @tool(
        "smylte_create_calendar", "Create a calendar",
        "Create a calendar as a real CalDAV collection, visible to every other "
        "client on this account.",
        _obj({"name": {"type": "string", "minLength": 1, "maxLength": 200},
              "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$"}},
             ["name"]),
        scope=SCOPE_WRITE, read_only=False,
    )
    def _create_calendar(name, color=None):
        return api.create_calendar(name=name, color=color)

    @tool(
        "smylte_update_calendar", "Rename or recolour a calendar",
        "Rename a calendar or change its colour. Written to the server, so "
        "other CalDAV clients see it. Does not touch the events on it.",
        _obj({"calendar_id": _CAL_ID,
              "name": {"type": "string", "minLength": 1, "maxLength": 200},
              "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$"}},
             ["calendar_id"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _update_calendar(calendar_id, name=None, color=None):
        return api.update_collection(calendar_id, name=name, color=color)

    @tool(
        "smylte_delete_calendar", "Delete a calendar",
        "Delete a calendar AND every event on it, on the server. Cannot be "
        "undone from here.",
        _obj({"calendar_id": _CAL_ID}, ["calendar_id"]),
        scope=SCOPE_WRITE, read_only=False, destructive=True, idempotent=True,
    )
    def _delete_calendar(calendar_id):
        api.delete_collection(calendar_id)
        return {"deleted": calendar_id}

    @tool(
        "smylte_list_events", "List events in a date range",
        "Events between two dates, across every calendar or just one. Repeating "
        "events are expanded into individual occurrences: each carries a "
        "`recurrence_id` naming its slot, which is what the edit and delete "
        "tools need to touch a single occurrence.",
        _obj({
            "start": {"type": "string", "description": "Range start, 'YYYY-MM-DD' or ISO datetime."},
            "end": {"type": "string", "description": "Range end, exclusive."},
            "calendar_id": {**_CAL_ID,
                            "description": _CAL_ID["description"] + " Omit to span every calendar."},
            "limit": _LIMIT, "offset": _OFFSET,
        }, ["start", "end"]),
    )
    def _list_events(start, end, calendar_id=None, limit=None, offset=None):
        return page(api.list_events(start, end, calendar_id), limit, offset, key="events")

    @tool(
        "smylte_get_event", "Get one event",
        "One event in full. For a repeating event this returns the series "
        "master, not a single occurrence — use smylte_list_events for those.",
        _obj({"calendar_id": _CAL_ID, "uid": {"type": "string"}}, ["calendar_id", "uid"]),
    )
    def _get_event(calendar_id, uid):
        return api.get_event(calendar_id, uid)

    @tool(
        "smylte_create_event", "Create an event",
        "Add an event to a calendar. For an all-day event set all_day=true and "
        "give dates as 'YYYY-MM-DD'; otherwise give ISO datetimes. Pass `repeat` "
        "to make it recur.",
        _obj({
            "calendar_id": _CAL_ID,
            "summary": {"type": "string", "minLength": 1},
            "start": {"type": "string",
                      "description": "'YYYY-MM-DD' when all_day, else 'YYYY-MM-DDTHH:MM'."},
            "end": {"type": "string",
                    "description": "Same format as start. For an all-day event this is "
                                   "exclusive — the day after the last one."},
            "all_day": {"type": "boolean", "default": False},
            "location": {"type": "string"},
            "description": {"type": "string"},
            "tags": _TAGS,
            "repeat": _REPEAT,
            "repeat_interval": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1,
                                "description": "Every N periods; 2 with weekly is fortnightly."},
            "repeat_count": {"type": "integer", "minimum": 1, "maximum": 10000,
                             "description": "Stop after this many occurrences."},
            "repeat_until": {"type": "string",
                             "description": "Stop after this date. Ignored if repeat_count is set."},
        }, ["calendar_id", "summary", "start"]),
        scope=SCOPE_WRITE, read_only=False,
    )
    def _create_event(calendar_id, summary, start, **rest):
        return api.create_event(calendar_id, summary=summary, start=start, **rest)

    @tool(
        "smylte_update_event", "Update an event",
        "Change an event. For a repeating event, `scope` decides how far the "
        "change reaches — read the scope description before editing one.",
        _obj({
            "calendar_id": _CAL_ID, "uid": {"type": "string"},
            "summary": {"type": "string"}, "description": {"type": "string"},
            "location": {"type": "string"},
            "start": {"type": "string"}, "end": {"type": "string"},
            "tags": _TAGS,
            "status": {"type": "string", "enum": ["CONFIRMED", "TENTATIVE", "CANCELLED"]},
            "repeat": _REPEAT,
            "repeat_interval": {"type": "integer", "minimum": 1, "maximum": 1000},
            "repeat_count": {"type": "integer", "minimum": 1, "maximum": 10000},
            "repeat_until": {"type": "string"},
            "recurrence_id": _RECURRENCE_ID, "scope": _SCOPE,
        }, ["calendar_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _update_event(calendar_id, uid, **fields):
        return api.update_event(calendar_id, uid, fields)

    @tool(
        "smylte_move_event", "Move an event to another calendar",
        "Move an event, and its whole series if it repeats, to another calendar.",
        _obj({"calendar_id": _CAL_ID, "uid": {"type": "string"},
              "to_calendar_id": {**_CAL_ID, "description": "Destination calendar id."}},
             ["calendar_id", "uid", "to_calendar_id"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _move_event(calendar_id, uid, to_calendar_id):
        return api.move_event(calendar_id, uid, to_calendar_id)

    @tool(
        "smylte_delete_event", "Delete an event",
        "Delete an event. For a repeating one, scope='this' removes a single "
        "occurrence and scope='all' removes the entire series.",
        _obj({"calendar_id": _CAL_ID, "uid": {"type": "string"},
              "recurrence_id": _RECURRENCE_ID, "scope": _SCOPE},
             ["calendar_id", "uid"]),
        scope=SCOPE_WRITE, read_only=False, destructive=True, idempotent=True,
    )
    def _delete_event(calendar_id, uid, recurrence_id=None, scope="all"):
        api.delete_event(calendar_id, uid, recurrence_id=recurrence_id, scope=scope)
        return {"deleted": uid, "scope": scope}

    @tool(
        "smylte_find_free_time", "Find free time",
        "Free gaps of at least `minutes`, computed across every calendar (or "
        "one). Useful before proposing a meeting time. Considers only the given "
        "hours of each day, 09:00-17:00 by default.",
        _obj({
            "start": {"type": "string", "description": "Range start, 'YYYY-MM-DD'."},
            "end": {"type": "string", "description": "Range end, exclusive."},
            "minutes": {"type": "integer", "minimum": 5, "maximum": 1440, "default": 30,
                        "description": "Shortest gap worth reporting."},
            "calendar_id": {**_CAL_ID,
                            "description": _CAL_ID["description"] + " Omit to consider all."},
            "day_start": {"type": "string", "default": "09:00",
                          "description": "Earliest time of day to consider, 'HH:MM'."},
            "day_end": {"type": "string", "default": "17:00",
                        "description": "Latest time of day to consider, 'HH:MM'."},
            "limit": _LIMIT,
        }, ["start", "end"]),
    )
    def _find_free_time(start, end, minutes=30, calendar_id=None,
                        day_start="09:00", day_end="17:00", limit=None):
        slots = api.find_free_time(start, end, minutes=minutes, calendar_id=calendar_id,
                                   day_start=day_start, day_end=day_end)
        return page(slots, limit, 0, key="free")

    # ── scheduling ───────────────────────────────────────────────────────────

    @tool(
        "smylte_list_booking_links", "List booking links",
        "The public booking links on this account — the pages other people use "
        "to book time — with their availability and how many bookings each has "
        "taken.",
        _obj({}),
    )
    def _list_booking_links():
        return {"links": api.list_booking_links()}

    @tool(
        "smylte_list_bookings", "List bookings",
        "Who has booked time, and when. Optionally filtered to one booking link.",
        _obj({"link": {"type": "string", "description": "Booking link token, to filter by."},
              "limit": _LIMIT, "offset": _OFFSET}),
    )
    def _list_bookings(link=None, limit=None, offset=None):
        return page(api.list_bookings(link), limit, offset, key="bookings")

    @tool(
        "smylte_update_booking_link", "Enable, disable or adjust a booking link",
        "Turn a booking link on or off, or change its title, duration, notice or "
        "horizon. Disabling makes the public page 404 without losing its history "
        "or settings.",
        _obj({
            "token": {"type": "string", "description": "Link token from smylte_list_booking_links."},
            "enabled": {"type": "boolean"},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": "string", "maxLength": 2000},
            "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 480},
            "buffer_minutes": {"type": "integer", "minimum": 0, "maximum": 240},
            "min_notice_hours": {"type": "integer", "minimum": 0, "maximum": 720},
            "horizon_days": {"type": "integer", "minimum": 1, "maximum": 180},
        }, ["token"]),
        scope=SCOPE_WRITE, read_only=False, idempotent=True,
    )
    def _update_booking_link(token, **fields):
        return api.update_booking_link(token, fields)

    return {t.name: t for t in tools}
