"""What a display says, as data. Pure: no DB, no clock, no I/O.

Everything this module needs is handed in, which is what makes the whole content
model unit-testable without a Radicale, and what keeps "what does the kitchen
screen show on a Tuesday" a question with one answer rather than three.

Two modes, because two are what a passive screen is actually good at:

  * `calendar` — the month, the way a paper wall calendar is the month. Not an
    agenda: an agenda is a thing you consult, and a wall calendar is a thing you
    glance at to place a day relative to the days around it.
  * `habits` — today's habits and today's rows, which is the other thing that
    earns a wall: a list short enough to read from the doorway, that gets
    shorter as the day goes.

There is no "tasks" mode. Every task view in the app is a query over a list that
grows without bound, and a screen with no scroll and no input cannot honestly
show one — it would show the first eight of forty and quietly imply that was all
of them. The day plan is the bounded version of that question and is what the
habits mode shows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# How different calendars are told apart when there is no colour to tell them
# apart with. On a 1-bit panel every colour is either ink or paper, so the
# distinction has to be carried by the SHAPE of the chip: a filled block, a
# hollow one, a rule down its left edge, a dotted underline. Four, because four
# is about what is distinguishable across a room — past that the differences are
# real on the bench and invisible on the wall.
#
# So a fifth calendar does not get a fifth pattern. Once there are more sources
# than treatments EVERY chip additionally carries its calendar's initial (see
# `assign_sources`), which is unambiguous at any count. The treatments still
# cycle underneath, so two calendars sharing "solid" are still separated by
# their letter rather than by nothing.
TREATMENTS = ("solid", "outline", "bar", "dotted")

# Weekday and month names for the two languages the app ships (see
# frontend/src/i18n/). Written out rather than taken from `locale`, which is
# process-global, needs the named locale to be generated on the host, and would
# make what a display says depend on how the server was provisioned.
#
# Sunday-first, matching `calendar.monthGrid` in the frontend — the app's month
# grid starts on Sunday, and a display that started on Monday would be a second
# opinion about the same month held by the same product.
_WEEKDAYS_SHORT = {
    "en": ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"),
    "de": ("So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"),
}
_MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"),
}
# The handful of words a display draws that are not data. A display has no
# chrome to speak of on purpose, so this stays small; anything that grows it is
# probably a control, and a display has no controls.
_TEXT = {
    "en": {
        "today": "Today", "nothing": "Nothing today", "no_events": "No events",
        "habits": "Habits", "day": "Today", "all_done": "All done",
        "not_planned": "Today isn’t planned yet",
        "not_planned_hint": "This is what opening it would put on it.",
        "too_small": "This screen is too small for a month.",
        "too_small_hint": "Set it to habits + today, or use a bigger panel.",
    },
    "de": {
        "today": "Heute", "nothing": "Heute nichts", "no_events": "Keine Termine",
        "habits": "Gewohnheiten", "day": "Heute", "all_done": "Alles erledigt",
        "not_planned": "Heute ist noch nicht geplant",
        "not_planned_hint": "Das käme beim Öffnen darauf.",
        "too_small": "Dieser Bildschirm ist zu klein für einen Monat.",
        "too_small_hint": "Auf Gewohnheiten + heute stellen oder ein größeres Panel nehmen.",
    },
}

# The most items one day of the month grid carries into the frame. A renderer
# truncates further to whatever actually fits and says "+N more" itself — layout
# is the renderer's job, and the browser page and an 800×480 panel do not fit
# the same number of rows. This cap is not layout: it is the bound that stops a
# day carrying two hundred imported birthdays into a JSON body an ESP32 has to
# parse. `hidden` records what it dropped, so a truncated day is never silently
# truncated.
MAX_ITEMS_PER_DAY = 20


def text(language: str, key: str) -> str:
    """One of the few fixed words a display draws, in the owner's language."""
    return _TEXT.get(language, _TEXT["en"]).get(key, _TEXT["en"][key])


def fmt_time(value: str | None, *, all_day: bool, time_format: str) -> str:
    """An event's start as a display clock, or "" for an all-day one.

    The app's own rule, ported: `time.ts` is the only thing that formats a clock
    in the frontend, and this is the only thing that formats one for a display —
    two implementations rather than three, and both read the same setting.
    """
    if all_day or not value:
        return ""
    try:
        # Both shapes the cache holds: a bare floating `2026-08-31T09:00:00` and
        # an offset-carrying one. The offset is NOT converted here — the events
        # were already selected for this day in the owner's zone, and converting
        # again would move a 23:30 event into tomorrow on the label while
        # leaving it in today's cell.
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if time_format == "24h":
        return f"{stamp.hour:02d}:{stamp.minute:02d}"
    hour = stamp.hour % 12 or 12
    suffix = "AM" if stamp.hour < 12 else "PM"
    # No space before the meridiem and no minutes on the hour: a wall display is
    # read at distance and every character costs width. "9 AM", "9:30 PM".
    return f"{hour} {suffix}" if stamp.minute == 0 else f"{hour}:{stamp.minute:02d} {suffix}"


def assign_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every calendar/list a treatment, and an initial when it needs one.

    `initial` is set on ALL of them or on none, never on the ones that happen to
    collide. A screen where three chips carry a letter and five do not reads as
    though the letter means something extra — it is a distinction the design did
    not intend and the viewer has to rule out. Either the treatments carry it or
    the letters do.
    """
    needs_initial = len(sources) > len(TREATMENTS)
    out = []
    for i, src in enumerate(sources):
        name = (src.get("name") or "").strip()
        out.append({
            "id": src["id"],
            "name": name,
            "color": src.get("color"),
            "treatment": TREATMENTS[i % len(TREATMENTS)],
            # The first CHARACTER, upper-cased — not the first letter of each
            # word: "Work" and "Weekend trips" both give "W", and that is
            # correct, because the treatment underneath them differs. Taking
            # initials from every word would give "W" and "WT", which are
            # different widths and break the chip's alignment for no gain.
            "initial": (name[:1].upper() if needs_initial else ""),
        })
    return out


def month_grid(day: str) -> list[list[str]]:
    """The six-week Sunday-first grid holding `day`'s month, as day keys.

    Six weeks always, even when five would hold the month, for the reason a
    paper calendar has a fixed grid: a display that changed height between
    March and April would repaint its whole layout on the 1st, and on eink that
    is a visible full-panel flash for no information.
    """
    anchor = date.fromisoformat(day)
    first = anchor.replace(day=1)
    # `isoweekday() % 7` is days since Sunday: Sunday 7→0, Monday 1→1.
    start = first - timedelta(days=first.isoweekday() % 7)
    return [
        [(start + timedelta(days=week * 7 + i)).isoformat() for i in range(7)]
        for week in range(6)
    ]


def _day_items(
    events: list[dict[str, Any]], day: str, *, time_format: str,
) -> tuple[list[dict[str, Any]], int]:
    """One cell's chips, all-day first then by clock, and what was dropped."""
    on_day = [e for e in events if e.get("day") == day]
    on_day.sort(key=lambda e: (
        # All-day events lead: they are the day's frame, and a timed event reads
        # as an entry within it. Then by start, then by title so two events at
        # the same minute have an order rather than the query's.
        0 if e.get("all_day") else 1,
        e.get("start") or "",
        (e.get("summary") or "").lower(),
    ))
    items = [{
        "text": (e.get("summary") or "").strip(),
        "time": fmt_time(e.get("start"), all_day=bool(e.get("all_day")),
                         time_format=time_format),
        "all_day": bool(e.get("all_day")),
        "source": e.get("source"),
        # A span's later days. The frontend's `bucketByDay` lists a week-long
        # event on all seven days and marks the continuations; a display does
        # the same, so a conference does not vanish after its first morning.
        "continued": bool(e.get("continued")),
    } for e in on_day[:MAX_ITEMS_PER_DAY]]
    return items, max(0, len(on_day) - MAX_ITEMS_PER_DAY)


def build_calendar(
    *, day: str, events: list[dict[str, Any]], language: str, time_format: str,
) -> dict[str, Any]:
    """The month grid mode."""
    anchor = date.fromisoformat(day)
    month = anchor.strftime("%Y-%m")
    weeks = []
    for row in month_grid(day):
        cells = []
        for key in row:
            items, hidden = _day_items(events, key, time_format=time_format)
            cells.append({
                "day": key,
                "label": str(int(key[8:10])),
                "in_month": key[:7] == month,
                "today": key == day,
                "items": items,
                "hidden": hidden,
            })
        weeks.append(cells)
    names = _MONTHS.get(language, _MONTHS["en"])
    return {
        "month": month,
        "title": f"{names[anchor.month - 1]} {anchor.year}",
        "weekday_names": list(_WEEKDAYS_SHORT.get(language, _WEEKDAYS_SHORT["en"])),
        "weeks": weeks,
        # What to say on a screen too small to hold seven columns. Carried in
        # the frame rather than owned by either renderer, because BOTH have to
        # say it and in the owner's language: `render.py` when the panel it is
        # handed fails `month_grid_fits`, and the browser page under the one
        # media query that matches a panel and never a phone.
        "too_small_text": text(language, "too_small"),
        "too_small_hint": text(language, "too_small_hint"),
    }


def build_habits(
    *, rows: list[dict[str, Any]], planned: bool, language: str,
    hide_done_habits: bool, hide_done_tasks: bool,
) -> dict[str, Any]:
    """The habits + tasks mode: today, in two blocks.

    `rows` are already-resolved day entries — a task entry's title read off its
    VTODO, a habit's off the occurrence. `planned` is false when these came from
    a PREVIEW: nobody has opened today, and this is what opening it would put on
    it. The distinction is surfaced rather than smoothed over, because a display
    that showed a preview as though it were a plan would be claiming the owner
    committed to a day they have not looked at.

    The counts are computed BEFORE the hiding, and that is the point of them.
    With `hide_done_habits` on, a finished habit leaves the screen — and a
    tracker that empties as the day goes has no way left to say how much of the
    day was done. "4 / 5" is that record, and it costs six characters.
    """
    habits, tasks = [], []
    for row in rows:
        done = bool(row.get("done"))
        item = {
            "text": (row.get("title") or "").strip(),
            "done": done,
            "kind": row.get("kind"),
            "source": row.get("source_id"),
            "estimate_minutes": row.get("estimate_minutes"),
        }
        (habits if row.get("kind") == "habit" else tasks).append(item)
    counts = {
        "habits_done": sum(1 for h in habits if h["done"]),
        "habits_total": len(habits),
        "tasks_done": sum(1 for t in tasks if t["done"]),
        "tasks_total": len(tasks),
    }
    return {
        "planned": planned,
        "heading": text(language, "habits"),
        "day_heading": text(language, "day"),
        "habits": [h for h in habits if not (hide_done_habits and h["done"])],
        "tasks": [t for t in tasks if not (hide_done_tasks and t["done"])],
        "counts": counts,
        "empty_text": text(language, "nothing"),
        "all_done_text": text(language, "all_done"),
        "preview_text": text(language, "not_planned"),
        "preview_hint": text(language, "not_planned_hint"),
    }


def build_frame(
    *, display: dict[str, Any], day: str, generated_at: str,
    language: str, time_format: str,
    sources: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    planned: bool = True,
) -> dict[str, Any]:
    """The whole frame: what this display shows, right now, in one object.

    The `display` dict is the row's own settings — everything the renderers need
    about the screen — and never the token. A frame is fetched by a device whose
    only credential is that token; echoing it back into the body would put it in
    every cache, every screenshot of a debugging session and every firmware log
    that prints its own response.
    """
    language = language if language in _TEXT else "en"
    frame: dict[str, Any] = {
        "display": {
            "name": display["name"],
            "mode": display["mode"],
            "palette": display["palette"],
            "refresh_seconds": display["refresh_seconds"],
            "rotation": display.get("rotation", 0),
        },
        "generated_at": generated_at,
        "day": day,
        "language": language,
        "time_format": time_format,
        "sources": assign_sources(sources or []),
    }
    if display["mode"] == "habits":
        frame["habits"] = build_habits(
            rows=rows or [], planned=planned, language=language,
            hide_done_habits=bool(display["hide_done_habits"]),
            hide_done_tasks=bool(display["hide_done_tasks"]),
        )
    else:
        frame["calendar"] = build_calendar(
            day=day, events=events or [], language=language, time_format=time_format,
        )
    return frame
