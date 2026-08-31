"""One answer to "when is this task due, and when is it late".

The rule was written for the MCP connector and lived in `mcp/api.py`, which was
fine while the connector was the only caller. It is not any more: the daily
digest counts overdue tasks, and a notifier that computed its own answer would
be the third one — after `frontend/src/util.ts::isOverdue` and the connector —
and the first two only agree because a finding made them agree. Three readers of
a deadline is three chances to tell the owner a different number for the same
task, in the same hour, on the same screen.

So the rule lives here, `mcp/api.py` imports it, and the notifier imports it.
Nothing about the behaviour changed in the move.

The two-number shape is the whole point. A deadline *expires* later than it is
*due*, and only for an all-day one: `util.ts::isOverdue` is the app's own rule —
an all-day item is not overdue until its whole day has passed — and
`service._due_day` resolves which day that is in `home_timezone`. Both are
honoured here rather than a third answer being invented.
"""
from __future__ import annotations

from datetime import date, datetime, time as time_of_day, timedelta

from .ical.read import normalize_offset


def parse_datelike(value) -> date | datetime | None:
    """A cached DUE as a date or datetime, or None if it cannot be read.

    Soft on purpose, and only ever used on values that came out of the CACHE.
    A deadline another CalDAV client wrote in a shape this cannot parse is not
    worth dropping the task over — the caller degrades to "no deadline" and the
    task still appears. Values supplied by a CALLER are parsed strictly
    elsewhere (`mcp/api.py::_parse_dt`, `app.py::_parse_datelike`), because
    there a refusal is a correct, actionable error rather than lost data.
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
        return None


def instant_in(value: date | datetime, zone) -> float:
    """A date-or-datetime as an absolute instant, resolved in `zone`.

    THE one resolution rule: an all-day value becomes midnight, a naive time is
    read as the owner's, an aware one keeps the instant it already names. Two
    rules in one module was the whole of a finding — `smylte_list_tasks` sorted
    a task by one zone and filtered it by another, and disagreed with
    `service._due_day` and with the SPA about which day a deadline falls on.
    """
    if not isinstance(value, datetime):
        value = datetime.combine(value, time_of_day.min)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone) if zone is not None else value.astimezone()
    return value.timestamp()


def due_parts(raw, zone) -> tuple[float, float] | None:
    """A deadline as `(due_at, overdue_at)`, both instants in `zone`.

    The day is added as WALL CLOCK, so a deadline whose day contains a DST
    transition expires 23 or 25 hours later, not 24.
    """
    value = parse_datelike(raw)
    if value is None:
        return None
    due_at = instant_in(value, zone)
    if isinstance(value, datetime):
        return due_at, due_at
    return due_at, instant_in(value + timedelta(days=1), zone)
