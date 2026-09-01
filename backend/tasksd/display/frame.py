"""What a display says, as data. Pure: no DB, no clock, no I/O.

Everything this module needs is handed in, which is what makes the whole content
model unit-testable without a Radicale, and what keeps "what does the kitchen
screen show on a Tuesday" a question with one answer rather than three.

Three modes, because three are what a passive screen is actually good at:

  * `calendar` — the month, the way a paper wall calendar is the month. Not an
    agenda: an agenda is a thing you consult, and a wall calendar is a thing you
    glance at to place a day relative to the days around it.
  * `habits` — today's habits and today's rows, which is the other thing that
    earns a wall: a list short enough to read from the doorway, that gets
    shorter as the day goes.
  * `now` — the one thing you are on, the one after it, and a count of the rest.

There is still no "tasks" mode, and the argument against one has not weakened.
Every task view in the app is a query over a list that grows without bound, and
a screen with no scroll and no input cannot honestly show one — it would show
the first eight of forty and quietly imply that was all of them. The day plan is
the bounded version of that question, and the two modes that draw it are bounded
in the two ways available: `habits` shows what fits and counts what it dropped,
and `now` shows exactly two rows whether the day holds three items or thirty.

`now` is deliberately not that refused list with a smaller cap. A capped list is
a truncation the reader cannot see; two rows and a "+6" is the whole day, said in
the only shape a screen with no scroll can say it in.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
        "now": "Now", "next": "Next",
        "not_planned": "Today isn’t planned yet",
        "not_planned_hint": "This is what opening it would put on it.",
        "too_small": "This screen is too small for a month.",
        "too_small_hint": "Set it to now + next, or habits + today, or use a bigger panel.",
    },
    "de": {
        "today": "Heute", "nothing": "Heute nichts", "no_events": "Keine Termine",
        "habits": "Gewohnheiten", "day": "Heute", "all_done": "Alles erledigt",
        "now": "Jetzt", "next": "Als Nächstes",
        "not_planned": "Heute ist noch nicht geplant",
        "not_planned_hint": "Das käme beim Öffnen darauf.",
        "too_small": "Dieser Bildschirm ist zu klein für einen Monat.",
        "too_small_hint": "Auf Jetzt + als Nächstes oder Gewohnheiten + heute stellen oder ein größeres Panel nehmen.",
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

# The most characters of any one title a frame carries, and the only bound on
# it anywhere. `MAX_ITEMS_PER_DAY` above bounds how MANY items a day carries;
# nothing bounded how LONG one was, and the length is the dangerous half.
#
# Every string here is attacker-adjacent: Tasks.org, Thunderbird, jtx and the
# owner's phone all write to the same Radicale collections, `ical/read.py::_text`
# is `str(v)` with no cap, and the column is TEXT. So a SUMMARY is arbitrarily
# long by construction, and it lands on a route with no session
# (`/api/public/display/<token>.png`) that rasterizes it. Measured before this
# bound existed: one 4,000-character summary on a grid-spanning event took 88
# seconds of CPU per request and never got cheaper, because `render._fit` is
# quadratic and `service._display_events` copies the summary into all 42 cells.
# One request was enough; the rate limiter never came into it.
#
# 120 because a display is read from across a room and the renderer truncates to
# what actually fits long before this — nothing legible survives past it.
MAX_TEXT_CHARS = 120

# C0, DEL, and the Unicode line/paragraph separators, replaced by a space.
#
# A newline is the one character in an event title that does not degrade
# gracefully: Pillow's `textlength` REFUSES multiline text ("can't measure
# length of multiline text"), so `render._fit` raised ValueError and every
# `.png`, `.bmp` and `.bin` fetch for that display answered 500 — permanently,
# for as long as the event existed, while the JSON frame kept working. And a
# newline is ordinary in a SUMMARY: RFC 5545 escapes it as `\n` and every parser
# unescapes it back. So it is normalised here, at the one edge all three
# surfaces are built from, rather than guarded at each renderer.
_CONTROL = re.compile(r"[\s\x00-\x1f\x7f\u2028\u2029]+")


def plain(value: str | None, *, limit: int = MAX_TEXT_CHARS) -> str:
    """Free text from a CalDAV client, made safe to draw and bounded.

    A RUN of whitespace collapses to one space rather than each character
    becoming its own, so the two surfaces agree: HTML already collapses runs, and
    a panel that drew "Team    sync" where the browser page drew "Team sync"
    would be one frame reading differently on the two screens it exists to keep
    in step.
    """
    if not value:
        return ""
    # Cut AFTER collapsing, so the limit counts characters that will be drawn
    # rather than the whitespace that was thrown away; strip again after, so a
    # cut landing mid-gap does not leave a trailing space before the ellipsis.
    return _CONTROL.sub(" ", value).strip()[:limit].strip()


def text(language: str, key: str) -> str:
    """One of the few fixed words a display draws, in the owner's language."""
    return _TEXT.get(language, _TEXT["en"]).get(key, _TEXT["en"][key])


def local(value: str, zone: ZoneInfo | None) -> datetime | None:
    """A stored ISO value as a datetime in the display's zone, or None.

    The one place the display path decides what an instant means, and it is a
    port of the frontend's `parseDate` + local-component reads rather than a
    second opinion:

      * an OFFSET-CARRYING value names an instant, so it is converted. This is
        what another CalDAV client writes — `_iso` keeps whatever offset the
        wire had — and it is the whole bug: the panel drew the authoring
        client's clock while the app's own calendar tab drew the viewer's.
      * a FLOATING value is naive local wall time, which is what this app
        writes itself. Its clock is the clock it already spells, so it is
        returned unchanged. `new Date("2026-08-31T09:00:00")` reads the same
        way in the browser.

    `zone` is the owner's `home_timezone`, and None means the process's own
    zone — the same fallback `_due_day` and `_today` take, so a display's grid,
    its chips and the day plan behind them are all in ONE zone rather than
    three.
    """
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp
    try:
        return stamp.astimezone(zone)
    except (OverflowError, OSError, ValueError):
        # `astimezone` on a value near datetime.min/max overflows rather than
        # raising ValueError, and this runs on a route with no session — an
        # unhandled one there is a 500 for every fetch of that display.
        return None


def instant(value: str | None, zone: ZoneInfo | None) -> float:
    """The moment `value` names, for ordering. Ports `calendar.ts::startOrder`.

    Sorting the chips in a cell by their RAW string is wrong the moment two of
    them carry different offsets, and the frontend says why at length: the
    lexicographic order of `2026-08-03T19:00:00+01:00` and a floating
    `2026-08-03T16:00:00` has nothing to do with their order on the clock. It
    is not only a reorder either — the cell keeps the first `MAX_ITEMS_PER_DAY`
    and the renderer keeps the first `room` of those, so a mis-sort drops a
    different event than the app does.

    A floating value is anchored in the display's zone, which is what
    `new Date(...)` does with one in the browser.
    """
    if not value:
        return 0.0
    stamp = local(value, zone)
    if stamp is None:
        return 0.0
    try:
        if stamp.tzinfo is None and zone is not None:
            stamp = stamp.replace(tzinfo=zone)
        return stamp.timestamp()
    except (OverflowError, OSError, ValueError):
        return 0.0


def fmt_time(value: str | None, *, all_day: bool, time_format: str,
             zone: ZoneInfo | None = None) -> str:
    """An event's start as a display clock, or "" for an all-day one.

    The app's own rule, ported: `time.ts` is the only thing that formats a clock
    in the frontend, and this is the only thing that formats one for a display —
    two implementations rather than three, and both read the same setting.

    The clock is the one the OWNER is in, not the one the authoring client was
    in: see `local`. `zone=None` is the process zone, which is what an account
    with no `home_timezone` gets everywhere else too.
    """
    if all_day or not value:
        return ""
    stamp = local(value, zone)
    if stamp is None:
        return ""
    if time_format == "24h":
        return f"{stamp.hour:02d}:{stamp.minute:02d}"
    hour = stamp.hour % 12 or 12
    suffix = "AM" if stamp.hour < 12 else "PM"
    # No space before the meridiem and no minutes on the hour: a wall display is
    # read at distance and every character costs width. "9 AM", "9:30 PM".
    return f"{hour} {suffix}" if stamp.minute == 0 else f"{hour}:{stamp.minute:02d} {suffix}"


def fmt_duration(minutes: Any) -> str:
    """An estimate in minutes as the app spells it, or "" for none.

    A port of `frontend/src/time.ts::fmtDuration`, character for character —
    "45m", "1h 30m", "2h" — for the same reason `fmt_time` is a port of that
    file's clock rather than a second opinion about it. A day whose estimates
    read "1h 30m" in the Today tab and "90 min" on the wall would be one app
    disagreeing with itself about a number the owner typed once.

    Language-independent by construction, which is why it takes no `language`:
    the app draws the same two letters in both, and inventing a German form here
    would be this module's only unlocalized string pretending to be localized.

    Anything that is not a number is "". The value reaches here from a sidecar
    column on a route with no session, and `round("soon")` is a TypeError that
    would 500 every fetch of the display until the entry was edited.
    """
    if minutes is None:
        return ""
    try:
        m = max(0, round(float(minutes)))
    except (TypeError, ValueError):
        return ""
    hours, rest = divmod(m, 60)
    if not hours:
        return f"{rest}m"
    return f"{hours}h {rest}m" if rest else f"{hours}h"


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
        name = plain(src.get("name"))
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
    zone: ZoneInfo | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """One cell's chips, all-day first then by clock, and what was dropped."""
    on_day = [e for e in events if e.get("day") == day]
    on_day.sort(key=lambda e: (
        # All-day events lead: they are the day's frame, and a timed event reads
        # as an entry within it. Then by the INSTANT the start names — never by
        # the string, which is a different order the moment two events carry
        # different offsets (see `instant`, and the same argument spelled out in
        # `calendar.ts::startOrder`). Then by title, so two events at the same
        # minute have an order rather than the query's.
        0 if e.get("all_day") else 1,
        instant(e.get("start"), zone),
        (e.get("summary") or "").lower(),
    ))
    items = [{
        "text": plain(e.get("summary")),
        # No clock on a continuation. Days 2..N of a span carry the SAME start,
        # so printing it says a conference begins at 09:00 on the Wednesday as
        # well as the Monday. The app draws the clock only on the first day
        # (`!e.cont` in CalendarView) and a marker on the rest; the frame says
        # the same thing by leaving the time empty, which every renderer
        # already handles because an all-day event has none either.
        "time": "" if e.get("continued") else fmt_time(
            e.get("start"), all_day=bool(e.get("all_day")),
            time_format=time_format, zone=zone),
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
    zone: ZoneInfo | None = None,
) -> dict[str, Any]:
    """The month grid mode."""
    anchor = date.fromisoformat(day)
    month = anchor.strftime("%Y-%m")
    weeks = []
    for row in month_grid(day):
        cells = []
        for key in row:
            items, hidden = _day_items(events, key, time_format=time_format,
                                       zone=zone)
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
            "text": plain(row.get("title")),
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
    shown_habits = [h for h in habits if not (hide_done_habits and h["done"])]
    shown_tasks = [t for t in tasks if not (hide_done_tasks and t["done"])]
    return {
        "planned": planned,
        "heading": text(language, "habits"),
        "day_heading": text(language, "day"),
        # Capped, and the cap is counted — the same contract the month grid has
        # had all along (`_day_items` and its `hidden`). This side had neither,
        # so a day with forty rows sent forty: the rasterizer drew what fitted
        # and the browser page let the tail run off the bottom of the panel with
        # nothing on screen saying there was more. `MAX_ITEMS_PER_DAY` is the
        # same bound because it is the same question — how much of a day a
        # screen with no scroll can honestly claim to be showing.
        "habits": shown_habits[:MAX_ITEMS_PER_DAY],
        "tasks": shown_tasks[:MAX_ITEMS_PER_DAY],
        "habits_hidden": max(0, len(shown_habits) - MAX_ITEMS_PER_DAY),
        "tasks_hidden": max(0, len(shown_tasks) - MAX_ITEMS_PER_DAY),
        "counts": counts,
        "empty_text": text(language, "nothing"),
        "all_done_text": text(language, "all_done"),
        "preview_text": text(language, "not_planned"),
        "preview_hint": text(language, "not_planned_hint"),
    }


def build_now(
    *, rows: list[dict[str, Any]], planned: bool, language: str,
) -> dict[str, Any]:
    """The rolling mode: the one you are on, the one after it, and a count.

    `rows` are the same already-resolved day entries `build_habits` takes, in
    the same plan order — so the queue on the wall is the order the owner put
    the day in, and reordering Today reorders the panel. There is no second
    sort here on purpose: a display that ranked the day by due date or priority
    would be a fourth opinion about what to do next, held by the screen least
    able to explain itself.

    The cursor is simply the first row that is not done, which is what makes
    this mode CYCLE without anything cycling it. A display takes no input and
    writes nothing; completing a task in the app, on a phone or in another
    CalDAV client moves the cursor here, and the panel picks it up on its next
    poll. Nothing schedules that and nothing is animated — the frame is just a
    different frame.

    Done rows never reach the frame. In `habits` they are drawn struck through,
    because that face is a tracker and the strike IS the record; here the record
    is `counts`, and a finished item on a face whose whole claim is "this is
    what you are on" would be reading out the past.

    `remaining` is uncapped, and this is the one mode where that is safe.
    `MAX_ITEMS_PER_DAY` exists because a body an ESP32 has to parse could
    otherwise carry two hundred imported birthdays; this one carries at most two
    items and an integer no matter how long the day is.
    """
    def item(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": plain(row.get("title")),
            "kind": row.get("kind"),
            "source": row.get("source_id"),
            # Formatted here, like every other string a display draws, so the
            # two renderers cannot disagree about a duration. The raw number
            # rides alongside it, as it does on a habits item: a board drawing
            # the JSON itself can format its own minutes and cannot get them
            # back out of "1h 30m".
            "estimate": fmt_duration(row.get("estimate_minutes")),
            "estimate_minutes": row.get("estimate_minutes"),
        }

    queue = [r for r in rows if not r.get("done")]
    return {
        "planned": planned,
        "heading": text(language, "now"),
        "next_heading": text(language, "next"),
        "current": item(queue[0]) if queue else None,
        "next": item(queue[1]) if len(queue) > 1 else None,
        # What is behind `next`. NOT always the number a renderer draws: a panel
        # too short for the next row hides one more than this, and both
        # renderers add it back (`render._render_now`, `DisplayView.NowFace`).
        # Carried this way rather than pre-summed because only the renderer
        # knows what fitted — the same split the month grid has, where the frame
        # caps and the cell counts what the cap and the layout dropped together.
        "remaining": max(0, len(queue) - 2),
        # Over EVERY row, done included — the score, exactly as the habits tally
        # is, and for the same reason: with the finished items gone from the
        # face this is all that remembers there were any.
        "counts": {
            "done": sum(1 for r in rows if r.get("done")),
            "total": len(rows),
        },
        "empty_text": text(language, "nothing"),
        "all_done_text": text(language, "all_done"),
        "preview_text": text(language, "not_planned"),
        "preview_hint": text(language, "not_planned_hint"),
    }


def build_frame(
    *, display: dict[str, Any], day: str, generated_at: str,
    language: str, time_format: str, zone: ZoneInfo | None = None,
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
            "name": plain(display["name"]),
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
    mode = display["mode"]
    if mode == "habits":
        frame["habits"] = build_habits(
            rows=rows or [], planned=planned, language=language,
            hide_done_habits=bool(display["hide_done_habits"]),
            hide_done_tasks=bool(display["hide_done_tasks"]),
        )
    elif mode == "now":
        # `hide_done_*` is not read here, and that is not an oversight: this face
        # has no done rows to hide. The two settings stay habits-only rather than
        # growing a meaning for a mode they do not apply to.
        frame["now"] = build_now(
            rows=rows or [], planned=planned, language=language)
    else:
        # The calendar is the fall-through as well as a mode, matching the
        # schema's `DEFAULT 'calendar'`: a row carrying a mode this build does
        # not know about draws a month rather than a blank panel.
        frame["calendar"] = build_calendar(
            day=day, events=events or [], language=language,
            time_format=time_format, zone=zone,
        )
    return frame
