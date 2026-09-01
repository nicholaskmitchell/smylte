"""Displays: the passive screens, the frame they fetch, and the pixels for a
panel with no browser.

Nothing here touches Radicale. A display is app-only state — a row in SQLite and
a read over the cache — so the service is driven directly and `items` is seeded
the way test_day_plan seeds it. The HTTP tier is exercised against an app whose
DAV URL points at a closed port, because none of these routes may reach the wire.

The properties pinned are the ones that make a screen on a wall safe to hang:

  * a display READS. Fetching a frame never opens a day, never writes an entry,
    and the single write anywhere behind it is the display's own `last_seen_at`.
  * a token reaches exactly one thing, and a revoked or switched-off display is
    indistinguishable from one that never existed.
  * the eink frame is one bit deep and the same frame renders the same bytes —
    which is what the ETag, and therefore every repaint a panel does not do,
    rests on.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_day_plan import DAY, LIST_A, _seed_task, _settings

from tasksd.app import create_app
from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo
from tasksd.db import store
from tasksd.display import frame as F
from tasksd.display import render as R
from tasksd.service import TaskService

CAL_A, CAL_B = "/u/cal-a/", "/u/cal-b/"


@pytest.fixture
def svc(monkeypatch):
    s = TaskService(_settings())
    store.upsert_collection(
        s._conn, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"}))
    store.upsert_collection(
        s._conn, CollectionInfo(href=CAL_A, displayname="Personal", components={"VEVENT"}))
    store.upsert_collection(
        s._conn, CollectionInfo(href=CAL_B, displayname="Shared", components={"VEVENT"}))
    # Every day-derived answer is pinned to DAY rather than to the wall clock,
    # for the reason test_day_plan gives: a suite whose expectations move at
    # midnight is a suite that fails at midnight.
    monkeypatch.setattr(TaskService, "_today", lambda self: DAY)
    return s


def _seed_event(conn, href: str, uid: str, summary: str, *, start: str,
                end: str | None = None, all_day: bool = False) -> None:
    """Cache one VEVENT, the way the sync engine would have."""
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"DTSTART;VALUE=DATE:{start.replace('-', '')}" if all_day else f"DTSTART:{start}",
    ]
    if end:
        lines.append(
            f"DTEND;VALUE=DATE:{end.replace('-', '')}" if all_day else f"DTEND:{end}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    raw = "\r\n".join(lines)
    conn.execute(
        "INSERT INTO items (collection_href, href, uid, etag, component, summary, "
        "dtstart, dtstart_is_date, dtend, dtend_is_date, has_rrule, raw_ics, status) "
        "VALUES (?,?,?,?,'VEVENT',?,?,?,?,?,0,?,'')",
        (href, f"{href}{uid}.ics", uid, f"e-{uid}", summary,
         start if not all_day else start, int(all_day),
         end, int(all_day and bool(end)), raw),
    )


# ── the frame builder (pure) ────────────────────────────────────────────────

def test_month_grid_is_six_sunday_first_weeks_holding_the_month():
    grid = F.month_grid("2026-08-31")
    assert len(grid) == 6 and all(len(w) == 7 for w in grid)
    # Sunday-first, matching the app's own `calendar.monthGrid`. A display that
    # started the week on Monday would be a second opinion about the same month
    # held by the same product.
    assert grid[0][0] == "2026-07-26"
    flat = [d for week in grid for d in week]
    assert "2026-08-01" in flat and "2026-08-31" in flat
    # Always six rows, even for a month five would hold — the fixed layout is
    # what stops an eink panel repainting itself on the 1st.
    assert len(F.month_grid("2026-02-10")) == 6


def test_sources_cycle_treatments_and_take_initials_all_or_none():
    four = F.assign_sources([{"id": str(i), "name": f"Cal {i}"} for i in range(4)])
    assert [s["treatment"] for s in four] == list(F.TREATMENTS)
    # Four fit the treatments, so no letters at all.
    assert all(s["initial"] == "" for s in four)

    five = F.assign_sources([{"id": str(i), "name": f"Cal{i}"} for i in range(5)])
    # Past four EVERY chip carries a letter, not just the ones that collided: a
    # letter on some chips and not others reads as meaning something extra.
    assert all(s["initial"] for s in five)
    assert five[4]["treatment"] == F.TREATMENTS[0]     # the shapes keep cycling


def test_initial_is_the_first_character_upper_cased():
    [one] = F.assign_sources([{"id": "a", "name": "work"}] * 1)
    assert one["initial"] == ""                        # one source needs none
    five = F.assign_sources([{"id": str(i), "name": n} for i, n in
                             enumerate(["work", "Weekend trips", "b", "c", "d"])])
    assert five[0]["initial"] == "W" and five[1]["initial"] == "W"


def test_clock_follows_the_account_setting_and_all_day_has_none():
    assert F.fmt_time("2026-08-31T13:05:00", all_day=False, time_format="24h") == "13:05"
    assert F.fmt_time("2026-08-31T13:05:00", all_day=False, time_format="12h") == "1:05 PM"
    # On the hour drops the minutes: a wall display is read at distance and
    # every character costs width.
    assert F.fmt_time("2026-08-31T09:00:00", all_day=False, time_format="12h") == "9 AM"
    assert F.fmt_time("2026-08-31T09:00:00", all_day=True, time_format="12h") == ""
    assert F.fmt_time(None, all_day=False, time_format="24h") == ""
    assert F.fmt_time("not a date", all_day=False, time_format="24h") == ""


def test_calendar_cells_carry_their_own_items_and_count_what_was_capped():
    events = [{"day": "2026-08-31", "summary": f"E{i}", "start": None,
               "all_day": True, "source": "a", "continued": False}
              for i in range(F.MAX_ITEMS_PER_DAY + 3)]
    cal = F.build_calendar(day="2026-08-31", events=events, language="en",
                           time_format="24h")
    cell = next(c for w in cal["weeks"] for c in w if c["day"] == "2026-08-31")
    assert len(cell["items"]) == F.MAX_ITEMS_PER_DAY
    # What the frame itself dropped is COUNTED, never silently discarded.
    assert cell["hidden"] == 3
    assert cell["today"] is True and cell["in_month"] is True


def test_all_day_events_lead_the_cell_then_the_clock():
    events = [
        {"day": "2026-08-31", "summary": "Late", "start": "2026-08-31T18:00:00",
         "all_day": False, "source": "a", "continued": False},
        {"day": "2026-08-31", "summary": "Early", "start": "2026-08-31T09:00:00",
         "all_day": False, "source": "a", "continued": False},
        {"day": "2026-08-31", "summary": "Holiday", "start": None,
         "all_day": True, "source": "a", "continued": False},
    ]
    cal = F.build_calendar(day="2026-08-31", events=events, language="en",
                           time_format="24h")
    cell = next(c for w in cal["weeks"] for c in w if c["day"] == "2026-08-31")
    # The all-day event is the day's frame; a timed one reads as an entry in it.
    assert [i["text"] for i in cell["items"]] == ["Holiday", "Early", "Late"]


def test_month_title_and_weekdays_are_localized_server_side():
    en = F.build_calendar(day="2026-08-31", events=[], language="en", time_format="24h")
    de = F.build_calendar(day="2026-03-01", events=[], language="de", time_format="24h")
    assert en["title"] == "August 2026" and en["weekday_names"][0] == "Sun"
    assert de["title"] == "März 2026" and de["weekday_names"][0] == "So"
    # An unknown language falls back to English rather than to a missing key.
    frame = F.build_frame(display=_display_row(), day="2026-08-31", generated_at="t",
                          language="kl", time_format="24h", events=[])
    assert frame["language"] == "en"


def _display_row(**over):
    row = {"name": "Hallway", "mode": "calendar", "palette": "eink",
           "refresh_seconds": 300, "rotation": 0,
           "hide_done_habits": True, "hide_done_tasks": True}
    row.update(over)
    return row


def test_habit_counts_are_taken_before_the_done_rows_are_hidden():
    rows = [
        {"kind": "habit", "title": "Stretch", "done": True},
        {"kind": "habit", "title": "Read", "done": False},
        {"kind": "task", "title": "Invoice", "done": True},
        {"kind": "note", "title": "Roof", "done": False},
    ]
    block = F.build_habits(rows=rows, planned=True, language="en",
                           hide_done_habits=True, hide_done_tasks=True)
    assert [h["text"] for h in block["habits"]] == ["Read"]
    assert [t["text"] for t in block["tasks"]] == ["Roof"]
    # The whole point of counting first: with hiding on, the list empties as the
    # day goes and this is the only thing left that remembers what was on it.
    assert block["counts"] == {"habits_done": 1, "habits_total": 2,
                               "tasks_done": 1, "tasks_total": 2}

    kept = F.build_habits(rows=rows, planned=True, language="en",
                          hide_done_habits=False, hide_done_tasks=False)
    assert len(kept["habits"]) == 2 and len(kept["tasks"]) == 2


def test_the_frame_never_carries_the_token():
    frame = F.build_frame(display=_display_row(), day=DAY, generated_at="t",
                          language="en", time_format="24h", events=[])
    # The token is the credential that fetched this. Echoing it into the body
    # would put it in every cache, screenshot and firmware log.
    assert "token" not in frame["display"]
    assert "token" not in str(frame["display"])


# ── the service ─────────────────────────────────────────────────────────────

def test_display_crud_round_trips(svc):
    made = svc.create_display({"name": "Hallway", "mode": "calendar"})
    assert made["name"] == "Hallway" and made["enabled"] is True
    # Long enough to be a credential for private data rather than a link meant
    # to be published: token_urlsafe(32), not the booking link's 16.
    assert len(made["token"]) >= 40
    assert made["last_seen_at"] is None

    edited = svc.update_display(made["token"], {"mode": "habits", "palette": "eink"})
    assert edited["mode"] == "habits" and edited["palette"] == "eink"
    assert [d["token"] for d in svc.list_displays()] == [made["token"]]
    assert svc.delete_display(made["token"]) is True
    assert svc.list_displays() == []
    assert svc.delete_display(made["token"]) is False


@pytest.mark.parametrize("fields", [
    {"name": "  "},                          # a display needs a name
    {"mode": "agenda"},                      # not one of the two it draws well
    {"palette": "sepia"},
    {"refresh_seconds": 5},                  # below the floor
    {"refresh_seconds": 200_000},
    {"rotation": 45},
    {"panel_width": 12},                     # below legibility
    {"panel_height": 9000},                  # an allocation, not a panel
    {"calendars": "work"},                   # not a list
    {"lists": [1, 2]},
])
def test_display_fields_are_refused_rather_than_coerced(svc, fields):
    with pytest.raises(ValueError):
        svc.create_display({"name": "X", **fields})


def test_rotating_a_token_keeps_the_display_and_clears_last_seen(svc):
    made = svc.create_display({"name": "Kitchen", "mode": "habits",
                               "palette": "eink", "refresh_seconds": 900})
    svc.display_frame(made["token"])                    # stamps last_seen_at
    assert svc.list_displays_one(made["token"])["last_seen_at"] is not None

    rotated = svc.rotate_display_token(made["token"])
    assert rotated["token"] != made["token"]
    # Everything the owner set survives — otherwise a leaked token would cost
    # them the display, which is exactly what makes people leave one in place.
    assert rotated["name"] == "Kitchen" and rotated["mode"] == "habits"
    assert rotated["palette"] == "eink" and rotated["refresh_seconds"] == 900
    # The stamp does NOT: the panel is still holding a URL that no longer works,
    # and showing it as live would be a lie about a screen in another room.
    assert rotated["last_seen_at"] is None
    assert svc.display_frame(made["token"]) is None      # the old URL is dead
    assert svc.display_frame(rotated["token"]) is not None
    assert svc.rotate_display_token("nope") is None


def test_a_disabled_display_answers_exactly_like_one_that_never_existed(svc):
    made = svc.create_display({"name": "Hallway"})
    assert svc.display_frame(made["token"]) is not None
    svc.update_display(made["token"], {"enabled": False})
    # Collapsed into one answer on purpose: a 403 for "disabled" would tell
    # whoever holds a revoked URL that it used to be real.
    assert svc.display_frame(made["token"]) is None
    assert svc.display_frame("never-existed") is None


def test_fetching_a_frame_stamps_last_seen_and_writes_nothing_else(svc):
    made = svc.create_display({"name": "Hallway"})
    before = svc._conn.execute("SELECT COUNT(*) c FROM day_plan").fetchone()["c"]
    svc.display_frame(made["token"])
    seen = svc.list_displays_one(made["token"])["last_seen_at"]
    assert seen is not None
    assert svc._conn.execute("SELECT COUNT(*) c FROM day_plan").fetchone()["c"] == before


def test_a_display_never_opens_a_day(svc):
    """The rule the whole feature hangs on.

    A screen in a hallway intends nothing, and the day plan is worth keeping
    only while it records what was actually intended. So a panel polling every
    five minutes for a year must never leave a single opened day behind.
    """
    _seed_task(svc._conn, LIST_A, "t1", "Invoice", due=DAY)
    made = svc.create_display({"name": "Kitchen", "mode": "habits"})
    for _ in range(5):
        frame = svc.display_frame(made["token"])
    assert store.day_is_opened(svc._conn, DAY) is False
    assert store.get_day_entries(svc._conn, DAY) == []
    # The rows are still shown — as a PREVIEW, labelled as one, so the screen
    # never claims a commitment the owner has not made.
    assert frame["habits"]["planned"] is False
    assert [r["text"] for r in frame["habits"]["tasks"]] == ["Invoice"]


def test_an_opened_day_reads_as_planned(svc):
    _seed_task(svc._conn, LIST_A, "t1", "Invoice", due=DAY)
    svc.open_day(DAY, create=True)
    made = svc.create_display({"name": "Kitchen", "mode": "habits"})
    frame = svc.display_frame(made["token"])
    assert frame["habits"]["planned"] is True
    assert [r["text"] for r in frame["habits"]["tasks"]] == ["Invoice"]


def test_task_rows_take_their_title_and_doneness_from_the_vtodo(svc):
    _seed_task(svc._conn, LIST_A, "t1", "Invoice", due=DAY)
    _seed_task(svc._conn, LIST_A, "t2", "Book train", due=DAY)
    svc.open_day(DAY, create=True)
    made = svc.create_display({"name": "Kitchen", "mode": "habits",
                               "hide_done_tasks": False})
    assert {r["text"]: r["done"] for r in svc.display_frame(made["token"])["habits"]["tasks"]} \
        == {"Invoice": False, "Book train": False}

    # Ticked on a phone, in Tasks.org, on the collection this app shares. The
    # day entry is a POINTER — it stores no title and no done flag for a task —
    # so the wall has to be reading the VTODO rather than a copy taken when the
    # day was opened.
    svc._conn.execute("UPDATE items SET status='COMPLETED' WHERE uid='t2'")
    rows = {r["text"]: r["done"] for r in svc.display_frame(made["token"])["habits"]["tasks"]}
    assert rows == {"Invoice": False, "Book train": True}

    # And with the hiding on — the default — it simply leaves the screen.
    hiding = svc.create_display({"name": "Study", "mode": "habits"})
    shown = [r["text"] for r in svc.display_frame(hiding["token"])["habits"]["tasks"]]
    assert shown == ["Invoice"]


def test_a_row_whose_task_has_left_the_wire_is_dropped_not_drawn_blank(svc):
    _seed_task(svc._conn, LIST_A, "t1", "Invoice", due=DAY)
    svc.open_day(DAY, create=True)
    svc._conn.execute("DELETE FROM items WHERE uid='t1'")
    made = svc.create_display({"name": "Kitchen", "mode": "habits"})
    frame = svc.display_frame(made["token"])
    # The entry outlives the task by design (there is no FK), but a row with no
    # title is a blank line on a wall.
    assert frame["habits"]["tasks"] == []


def test_dropped_and_rolled_rows_stay_off_the_wall(svc):
    _seed_task(svc._conn, LIST_A, "t1", "Invoice", due=DAY)
    _seed_task(svc._conn, LIST_A, "t2", "Later", due=DAY)
    plan = svc.open_day(DAY, create=True)
    by_uid = {e["uid"]: e["entry_id"] for e in plan["entries"]}
    svc.patch_day_entry(DAY, by_uid["t1"], dropped=True)
    svc.roll_entry(DAY, by_uid["t2"], "2026-08-22")
    made = svc.create_display({"name": "Kitchen", "mode": "habits"})
    frame = svc.display_frame(made["token"])
    # "I decided against this" and "I am doing this Thursday" are what a day's
    # RECORD needs and what a screen in a kitchen cannot act on.
    assert frame["habits"]["tasks"] == []


def test_habit_occurrences_come_through_as_habits(svc):
    svc.create_habit(title="Stretch", days="")
    svc.open_day(DAY, create=True)
    made = svc.create_display({"name": "Kitchen", "mode": "habits"})
    frame = svc.display_frame(made["token"])
    assert [h["text"] for h in frame["habits"]["habits"]] == ["Stretch"]
    assert frame["habits"]["counts"]["habits_total"] == 1


def test_a_completed_habit_leaves_the_screen_when_asked_and_stays_when_not(svc):
    svc.create_habit(title="Stretch", days="")
    plan = svc.open_day(DAY, create=True)
    entry = next(e for e in plan["entries"] if e["kind"] == "habit")
    svc.patch_day_entry(DAY, entry["entry_id"], done=True)

    hiding = svc.create_display({"name": "Kitchen", "mode": "habits"})
    frame = svc.display_frame(hiding["token"])
    assert frame["habits"]["habits"] == []
    # The tally still remembers it. A tracker that empties has nothing else left
    # to say the day went well.
    assert frame["habits"]["counts"] == {"habits_done": 1, "habits_total": 1,
                                         "tasks_done": 0, "tasks_total": 0}

    showing = svc.create_display({"name": "Study", "mode": "habits",
                                  "hide_done_habits": False})
    kept = svc.display_frame(showing["token"])
    assert [h["done"] for h in kept["habits"]["habits"]] == [True]


def test_calendar_mode_buckets_events_and_spans_every_day_they_cover(svc):
    _seed_event(svc._conn, CAL_A, "e1", "Standup", start=f"{DAY}T09:00:00")
    _seed_event(svc._conn, CAL_A, "e2", "Trip",
                start="2026-08-24", end="2026-08-27", all_day=True)
    made = svc.create_display({"name": "Hallway", "mode": "calendar"})
    frame = svc.display_frame(made["token"])
    cells = {c["day"]: c for w in frame["calendar"]["weeks"] for c in w}
    assert [i["text"] for i in cells[DAY]["items"]] == ["Standup"]
    assert cells[DAY]["items"][0]["time"] in ("09:00", "9 AM")
    # DTEND is EXCLUSIVE for an all-day event, so the trip runs 24th-26th. A
    # span is on every day it touches or it is misinformation by the second day.
    for day in ("2026-08-24", "2026-08-25", "2026-08-26"):
        assert [i["text"] for i in cells[day]["items"]] == ["Trip"], day
    assert cells["2026-08-27"]["items"] == []
    # Only the first day is the start; the rest are continuations.
    assert cells["2026-08-24"]["items"][0]["continued"] is False
    assert cells["2026-08-25"]["items"][0]["continued"] is True


def test_the_calendar_allowlist_is_empty_means_everything(svc):
    _seed_event(svc._conn, CAL_A, "e1", "Personal thing", start=f"{DAY}T09:00:00")
    _seed_event(svc._conn, CAL_B, "e2", "Shared thing", start=f"{DAY}T11:00:00")
    everything = svc.create_display({"name": "Hallway", "mode": "calendar"})
    frame = svc.display_frame(everything["token"])
    cells = {c["day"]: c for w in frame["calendar"]["weeks"] for c in w}
    assert len(cells[DAY]["items"]) == 2
    assert {s["id"] for s in frame["sources"]} == {"cal-a", "cal-b"}

    one = svc.create_display({"name": "Study", "mode": "calendar",
                              "calendars": ["cal-a"]})
    narrowed = svc.display_frame(one["token"])
    cells = {c["day"]: c for w in narrowed["calendar"]["weeks"] for c in w}
    assert [i["text"] for i in cells[DAY]["items"]] == ["Personal thing"]


def test_an_archived_calendar_stays_off_the_wall(svc):
    _seed_event(svc._conn, CAL_A, "e1", "Personal thing", start=f"{DAY}T09:00:00")
    _seed_event(svc._conn, CAL_B, "e2", "Shared thing", start=f"{DAY}T11:00:00")
    store.update_settings(svc._conn, {"archived_calendars": ["cal-b"]})
    made = svc.create_display({"name": "Hallway", "mode": "calendar"})
    frame = svc.display_frame(made["token"])
    cells = {c["day"]: c for w in frame["calendar"]["weeks"] for c in w}
    # Archiving is the owner saying a calendar is not part of their present, and
    # a screen on the wall is as present as it gets.
    assert [i["text"] for i in cells[DAY]["items"]] == ["Personal thing"]


def test_the_frame_reports_the_accounts_clock_and_language(svc):
    store.update_settings(svc._conn, {"time_format": "24h", "language": "de"})
    _seed_event(svc._conn, CAL_A, "e1", "Standup", start=f"{DAY}T09:00:00")
    made = svc.create_display({"name": "Flur", "mode": "calendar"})
    frame = svc.display_frame(made["token"])
    assert frame["time_format"] == "24h" and frame["language"] == "de"
    assert frame["calendar"]["title"] == "August 2026"
    assert frame["calendar"]["weekday_names"][0] == "So"


# ── the renderer ────────────────────────────────────────────────────────────

def _frame(mode="calendar", palette="eink", **over):
    display = _display_row(mode=mode, palette=palette, **over)
    if mode == "habits":
        return F.build_frame(
            display=display, day=DAY, generated_at="t", language="en",
            time_format="24h", planned=True,
            rows=[{"kind": "habit", "title": "Stretch", "done": True},
                  {"kind": "task", "title": "Invoice", "done": False}])
    return F.build_frame(
        display=display, day=DAY, generated_at="t", language="en",
        time_format="24h",
        sources=[{"id": "a", "name": "Work", "color": "#3B82F6"}],
        events=[{"day": DAY, "summary": "Standup", "start": f"{DAY}T09:00:00",
                 "all_day": False, "source": "a", "continued": False}])


@pytest.mark.parametrize("mode", ["calendar", "habits"])
def test_an_eink_render_is_one_bit_deep(mode):
    from PIL import Image
    import io

    body, media = R.render_frame(_frame(mode), width=800, height=480, fmt="png")
    assert media == "image/png"
    img = Image.open(io.BytesIO(body))
    # Mode "1" is the whole contract with the panel: every pixel is ink or
    # paper, with no intermediate value to become a dither pattern.
    assert img.mode == "1" and img.size == (800, 480)
    assert set(img.convert("L").tobytes()) <= {0, 255}


def test_a_colour_render_keeps_its_colour():
    from PIL import Image
    import io

    body, _ = R.render_frame(_frame(palette="color"), width=800, height=480, fmt="png")
    img = Image.open(io.BytesIO(body)).convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=100_000)}
    # More than ink and paper: the calendar's own colour is on the chip.
    assert len(colors) > 2


def test_bmp_is_offered_because_a_panel_library_may_have_no_decompressor():
    from PIL import Image
    import io

    body, media = R.render_frame(_frame(), width=800, height=480, fmt="bmp")
    assert media == "image/bmp"
    img = Image.open(io.BytesIO(body))
    assert img.mode == "1" and img.size == (800, 480)


def test_raw_is_the_framebuffer_a_panel_already_holds():
    """The whole point of the format: no container, nothing to decode.

    Byte-equal to the PNG's own decoded pixels, so it is provably the same
    picture — and exactly `stride × height` long, which is what a firmware
    checks `Content-Length` against before it paints anything.
    """
    from PIL import Image
    import io

    frame = _frame()
    body, media = R.render_frame(frame, width=800, height=480, fmt="raw")
    assert media == "application/octet-stream"
    # 800 / 8 = 100 bytes a row, 480 rows. The number a Waveshare 7.5" driver
    # allocates as `bytearray(800 * 480 // 8)`.
    assert len(body) == 48_000
    png, _ = R.render_frame(frame, width=800, height=480, fmt="png")
    assert body == Image.open(io.BytesIO(png)).tobytes()


def test_raw_is_one_bit_even_on_a_display_configured_for_colour():
    """The footgun this format exists to not have.

    On `.bmp` the one-bit guarantee holds only while the display is CONFIGURED
    as eink; flip it to colour and the same URL serves 24-bit BGR — 1,152,054
    bytes at 800×480 against the 48,000 a board just allocated, with no header
    in a raw stream to say so. Raw is one-bit by construction instead.
    """
    colour = _frame(palette="color")
    body, _ = R.render_frame(colour, width=800, height=480, fmt="raw")
    assert len(body) == 48_000
    # And the other formats are unchanged — this must not have been achieved by
    # thresholding everything, which is what `test_a_colour_render_keeps_its_colour`
    # is standing guard over.
    bmp, _ = R.render_frame(colour, width=800, height=480, fmt="bmp")
    assert len(bmp) > 1_000_000


def test_raw_pads_each_row_to_a_whole_byte():
    """The reason `X-Display-Stride` is on the wire.

    A width that is not a multiple of eight is padded to a byte per row — 250
    pixels is 32 bytes, not 31.25 — and a client that divided rather than asking
    would shear its picture by two more pixels on every row down the panel.
    This is also MicroPython's own `framebuf.MONO_HLSB` stride, which is why the
    packing needs no translation at the other end.
    """
    body, _ = R.render_frame(_frame(), width=250, height=122, fmt="raw")
    assert len(body) == 32 * 122 == 3_904
    assert len(body) != 250 * 122 // 8


def test_invert_is_a_strict_complement_of_every_bit():
    """Guards the one line that three obvious cleanups would silently break.

    `ImageChops.invert`, `Image.eval(v: 255-v)` and `img.point(lambda v: 255-v)`
    on a mode-"1" image all return an entirely WHITE image — measured — because
    mode "1" is stored one byte per pixel and those calls leave 254 behind,
    which repacks as 1. Only inverting the packed bytes inverts the picture.
    A panel would show blank white and nobody would know why.
    """
    frame = _frame()
    plain, _ = R.render_frame(frame, width=800, height=480, fmt="raw")
    flipped, _ = R.render_frame(frame, width=800, height=480, fmt="raw", invert=True)
    assert flipped == bytes(b ^ 0xFF for b in plain)
    # Not merely different — a blank white buffer would also be "different".
    assert flipped != plain and set(plain) != {0xFF}


def test_invert_is_refused_on_a_format_that_has_no_bits_to_flip():
    # Ignoring it would hand back a normal PNG with no way to tell, and the
    # failure would surface as a panel full of black.
    for fmt in ("png", "bmp"):
        with pytest.raises(ValueError):
            R.render_frame(_frame(), width=800, height=480, fmt=fmt, invert=True)


def test_raw_renders_the_same_bytes_twice():
    """The raw sibling of the determinism test, and the ETag rests on it.

    Nothing in the render draws a clock — if anything ever did, every panel
    would repaint on every poll and the 304 would quietly stop meaning anything.
    """
    frame = _frame()
    first, _ = R.render_frame(frame, width=800, height=480, fmt="raw")
    second, _ = R.render_frame(
        {**frame, "generated_at": "a completely different timestamp"},
        width=800, height=480, fmt="raw")
    assert first == second


def test_a_portrait_panel_is_laid_out_portrait_and_turned_at_the_end():
    from PIL import Image
    import io

    body, _ = R.render_frame(_frame("habits"), width=800, height=480,
                             rotation=90, fmt="png")
    img = Image.open(io.BytesIO(body))
    # The device is handed its own framebuffer shape...
    assert img.size == (800, 480)
    # ...but the layout happened in the shape a reader sees, which is what stops
    # a seven-column month grid being drawn on its side.
    unrotated, _ = R.render_frame(_frame("habits"), width=480, height=800, fmt="png")
    assert body != unrotated


def test_a_bigger_panel_shows_more_rather_than_the_same_thing_louder():
    """The principle `_scale` states and `_item_scale` is what makes true.

    A headline growing with the panel is right — there is one of it. A cell's
    event text growing with the panel is not: the column it sits in grows at
    exactly the same rate, so the number of characters that fit never improves
    and a 13" panel truncates the same titles a 7.5" one does, with half its
    cells empty.
    """
    # The common 7.5" panel is the reference and is untouched by this.
    assert R._item_scale(R._scale(480)) == 1.0
    assert R._item_scale(R._scale(825)) < R._scale(825)

    day = DAY
    events = [{"day": day, "summary": f"Event number {i}", "start": f"{day}T0{i}:00:00",
               "all_day": False, "source": "a", "continued": False} for i in range(1, 8)]
    frame = F.build_frame(
        display=_display_row(), day=day, generated_at="t", language="en",
        time_format="24h", events=events,
        sources=[{"id": "a", "name": "Work", "color": None}])

    def drawn(height: int) -> int:
        """How many of the day's events the renderer actually put on the panel."""
        scale = R._scale(height)
        small = R._item_scale(scale)
        pad = int(16 * scale)
        row_h = (height - (pad + int(38 * scale) + int(18 * scale)) - pad) / 6
        item_top = int(3 * scale) + int(21 * scale)
        return max(0, int((row_h - item_top - 2 * scale) // int(15 * small)))

    assert drawn(825) > drawn(480), "a taller panel drew no more rows"
    # And it is not merely taller-per-row: the small tier grew more slowly than
    # the panel, which is where the extra rows and the extra words come from.
    assert R._font("sans", int(12 * R._item_scale(R._scale(825)))).size \
        < R._font("sans", int(12 * R._scale(825))).size


def test_a_month_grid_refuses_a_panel_it_cannot_be_read_on():
    """A 2.9" panel is 296×128 — a 39px column, four characters wide.

    Seven of those is not a small month grid, it is a smear, and a screen
    rendering a smear looks BROKEN rather than misconfigured, so the owner has
    no way to know what to do. The predicate is exported and the service uses
    the same one, so Settings can say it at the moment the size is typed.
    """
    # The panels people actually mount, and the verdict each one gets.
    assert R.month_grid_fits(800, 480)          # Waveshare 7.5", the reference
    assert R.month_grid_fits(400, 300)          # Waveshare 4.2", cramped but real
    assert R.month_grid_fits(600, 800)          # a portrait Kindle
    assert not R.month_grid_fits(296, 128)      # Waveshare 2.9"
    assert not R.month_grid_fits(250, 122)      # Waveshare 2.13"

    from PIL import Image
    import io

    body, _ = R.render_frame(_frame(), width=296, height=128, fmt="png")
    img = Image.open(io.BytesIO(body))
    assert img.size == (296, 128)
    # It still draws — a blank panel is no more use than a smeared one — but
    # what it draws is a sentence naming the mode that does fit.
    ink = sum(1 for px in img.convert("L").tobytes() if px < 128)
    assert ink > 0


def test_a_narrow_column_spends_its_width_on_the_event_not_the_clock():
    """The failure a portrait panel found.

    `_scale` reads the panel's HEIGHT, which is right for a headline and wrong
    for seven columns. On a 600×800 Kindle that inflated the type past what the
    column could hold: every cell drew its clock and then had no room left, so
    the month came out as a grid of bare times with nothing saying what any of
    them were.
    """
    # The grid's scale is bound by the column, so a tall narrow panel does not
    # inflate the small tier past it.
    assert R._grid_scale(800, 480) == 1.0                 # the reference, unmoved
    assert R._grid_scale(600, 800) < R._scale(800)
    assert R._grid_scale(1200, 825) > 1.0                 # a big panel still grows

    day = DAY
    frame = F.build_frame(
        display=_display_row(), day=day, generated_at="t", language="en",
        time_format="24h",
        sources=[{"id": "a", "name": "Work", "color": None}],
        events=[{"day": day, "summary": "Dentist", "start": f"{day}T14:30:00",
                 "all_day": False, "source": "a", "continued": False}])
    wide, _ = R.render_frame(frame, width=800, height=480, fmt="png")
    narrow, _ = R.render_frame(frame, width=600, height=800, fmt="png")
    # Both draw something for that day; the narrow one differs because it made a
    # different trade, not because it gave up.
    assert wide != narrow
    assert len(narrow) > 0


def _plan(width: float, items, initial: str = "") -> tuple[list, int]:
    """`_plan_cell` at a given column width, with the fonts an 800×480 uses."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("L", (10, 10), 255))
    item_font, time_font = R._font("sans", 12), R._font("mono", 10)
    return R._plan_cell(
        draw, items, {"a": {"treatment": "solid", "initial": initial}},
        room=len(items), avail=width, item_font=item_font, time_font=time_font,
        initial_size=11, gap=max(4, int(item_font.size * 0.6)))


def _item(text: str, time: str = "") -> dict:
    return {"text": text, "time": time, "all_day": not time, "source": "a",
            "continued": False}


def test_a_row_is_never_drawn_as_a_marker_with_nothing_beside_it():
    """The orphan the first version left on every narrow column.

    The marker and the clock were drawn, and only then was the title measured —
    so a title with no room left a bullet and a bare "14:30" saying nothing. A
    row that cannot say what it is belongs in the "+N", not on the panel.

    Tested here rather than through a rendered panel because it cannot be
    reached through one: `month_grid_fits` refuses the sizes narrow enough to
    make it happen, which is the belt to this brace.
    """
    planned, dropped = _plan(6, [_item("Dentist", "14:30"), _item("Lunch")])
    assert planned == []
    assert dropped == 2, "a row that could not be drawn was not counted"


def test_a_clock_gives_up_its_space_when_the_event_would_have_none():
    """The failure a portrait panel found, at the level it is decided.

    A clock is fixed-width mono and it goes first, so on a narrow column it eats
    the title whole. On a 600×800 Kindle every cell rendered its time and then
    had no room left — a month of bare clocks with nothing saying what any of
    them were.
    """
    wide, _ = _plan(200, [_item("Dentist", "14:30")])
    assert wide[0][1] == "14:30", "a wide column should keep the clock"
    assert wide[0][2] == "Dentist"

    narrow, _ = _plan(64, [_item("Dentist", "14:30")])
    # The trade: "Dentist" with no time beats "14:30 …" with no event.
    assert narrow[0][1] == "", "the clock kept its space and starved the title"
    assert narrow[0][2] == "Dentist"


def test_a_title_is_truncated_rather_than_dropped_while_it_still_says_something():
    planned, dropped = _plan(90, [_item("Quarterly planning workshop", "13:00")])
    assert dropped == 0
    assert planned[0][2].endswith("…") and len(planned[0][2]) > 3


def test_a_calendars_initial_is_paid_for_out_of_the_row_it_marks():
    """With more calendars than treatments every chip carries a letter, and that
    letter costs width the title would otherwise have had. It has to come out of
    the same budget, or the row overruns its column."""
    without, _ = _plan(80, [_item("Dentist", "14:30")])
    with_letter, _ = _plan(80, [_item("Dentist", "14:30")], initial="W")
    assert len(with_letter[0][2]) <= len(without[0][2])


def test_the_clock_and_the_title_do_not_touch():
    """Measured, because it shipped wrong: at the small end the gap after the
    clock was one space wide and "10:00" ran into "1:1 with Sam" as
    "10:001:1 with…" — one word, on a screen read from across a room."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("L", (10, 10), 255))
    for width, height in ((400, 300), (648, 480), (800, 480), (1200, 825)):
        small = R._item_scale(R._grid_scale(width, height))
        item = R._font("sans", int(12 * small))
        gap = max(4, int(item.size * 0.6))
        # Comfortably more than the space it would take in running text — a mono
        # field abutting a sans one needs more air than two words of one face.
        assert gap > draw.textlength(" ", font=item) * 1.5, f"{width}x{height}"


def test_a_habits_face_says_how_many_rows_it_could_not_show():
    """A 2.9" panel fits two rows of seven.

    A screen that quietly showed two and said nothing is the same lie as a task
    list showing the first eight of forty — which is the thing this feature
    refuses to do everywhere else.
    """
    from PIL import Image
    import io

    rows = [{"kind": "habit", "title": f"Habit {i}", "done": False} for i in range(4)]
    rows += [{"kind": "task", "title": f"Task {i}", "done": False} for i in range(4)]
    frame = F.build_frame(
        display=_display_row(mode="habits"), day=DAY, generated_at="t",
        language="en", time_format="24h", rows=rows, planned=True)

    tiny, _ = R.render_frame(frame, width=296, height=128, fmt="png")
    roomy, _ = R.render_frame(frame, width=800, height=600, fmt="png")
    assert tiny != roomy
    # The tiny one drew a counter it did not need at the roomy size, and no
    # section header with nothing under it.
    assert Image.open(io.BytesIO(tiny)).size == (296, 128)


def test_the_same_frame_renders_the_same_bytes():
    # Everything a panel does NOT repaint rests on this: the routes hash the
    # body for the ETag, and a renderer that varied run to run would flash the
    # screen every poll while saying the same thing.
    first, _ = R.render_frame(_frame(), width=800, height=480, fmt="png")
    second, _ = R.render_frame(_frame(), width=800, height=480, fmt="png")
    assert first == second


@pytest.mark.parametrize("bad", [{"rotation": 45}, {"fmt": "gif"}])
def test_the_renderer_refuses_what_it_cannot_draw(bad):
    with pytest.raises(ValueError):
        R.render_frame(_frame(), width=800, height=480, **bad)


def test_long_text_is_cut_with_an_ellipsis_rather_than_overrunning():
    from PIL import Image, ImageDraw

    img = Image.new("L", (200, 40), 255)
    draw = ImageDraw.Draw(img)
    font = R._font("sans", 14)
    assert R._fit(draw, "short", font, 200) == "short"
    long = R._fit(draw, "a title far too long for the space it has", font, 60)
    assert long.endswith("…") and len(long) < 40
    # No room at all answers with nothing, not with a lone ellipsis: a column of
    # "…" tells the reader only that the layout is wrong.
    assert R._fit(draw, "anything", font, 2) == ""


def test_the_renderer_draws_in_the_apps_three_type_slots():
    """A display is drawn in the product's own typefaces, not in a default one.

    Asserted by ROLE rather than by filename, which is also how the renderer
    names them at every call site: "this is a micro-label" survives a change of
    typeface and "this is JetBrainsMono-Medium" does not. What matters is that
    three distinct faces exist and that the roles map to different files —
    collapsing them (a stray `_font("sans", …)` on a headline) is exactly the
    regression that turns this back into a generic dashboard.
    """
    faces = {role: R._font(role, 20).path for role in ("serif", "sans", "mono")}
    assert len(set(faces.values())) == 3
    assert "Fraunces" in faces["serif"]
    assert "Inter" in faces["sans"]
    assert "JetBrainsMono" in faces["mono"]


def test_a_micro_label_is_tracked_and_right_aligns_to_its_edge():
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("L", (400, 60), 255))
    # Tracked by hand, one glyph at a time: Pillow has no letter-spacing, and
    # uppercase mono set solid is a different thing from the app's label.
    solid = R._label(draw, (0, 0), "HABITS", 12, 0, track=0)
    airy = R._label(draw, (0, 20), "HABITS", 12, 0, track=R._TRACK_WIDE)
    assert airy > solid
    # Five gaps for six characters, not six: CSS puts letter-spacing after every
    # character including the last, which leaves a right-aligned label sitting a
    # gap short of its edge.
    assert round(airy - solid, 3) == round(12 * R._TRACK_WIDE * 5, 3)


def test_a_right_aligned_label_ends_where_it_was_told_to():
    from PIL import Image, ImageDraw

    img = Image.new("L", (200, 30), 255)
    draw = ImageDraw.Draw(img)
    width = R._label(draw, (0, 5), "SAT", 12, 0, right=150)
    ink = [x for x in range(200) if any(img.getpixel((x, y)) < 128 for y in range(30))]
    assert ink, "nothing was drawn"
    # Within a glyph's side bearing of the edge it was aligned to, and starting
    # where the measured width says it should.
    assert 140 <= max(ink) <= 150
    assert abs(min(ink) - (150 - width)) <= 3


def test_a_day_outside_the_month_is_told_apart_by_SIZE_not_only_colour():
    """The eink regression this exists to keep closed.

    `--fg-muted` on a one-bit panel IS black, so drawing July's last week in
    "muted" and August's first in "ink" produced two identical numbers — and the
    only reason to draw the neighbouring month at all is to show where it ends.
    """
    import copy

    frame = _frame()                                  # eink, one bit deep
    assert any(not c["in_month"] for w in frame["calendar"]["weeks"] for c in w)
    flat = copy.deepcopy(frame)
    for week in flat["calendar"]["weeks"]:
        for cell in week:
            cell["in_month"] = True

    # The assertion is that the two renders DIFFER. If `in_month` were carried
    # by colour alone, they would be byte-identical here — the eink palette has
    # exactly one ink — and that byte-identity is precisely the bug.
    assert R.render_frame(frame, width=800, height=480, fmt="png") \
        != R.render_frame(flat, width=800, height=480, fmt="png")


# ── the HTTP tier ───────────────────────────────────────────────────────────

def _api_settings(tmp_path) -> Settings:
    # The DAV URL points at a closed port: no display route may reach the wire.
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=str(tmp_path / "displays.db"), sync_interval_s=3600,
        request_timeout_s=1, static_dir="/nonexistent", hook_secret="h",
        auth_enabled=True, auth_user="admin", auth_password_hash="",
        auth_password="testpass123", session_secret="s" * 40, session_ttl_s=3600,
        cookie_secure=False, access_required=False, access_team_domain="",
        access_aud="",
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(TaskService, "_today", lambda self: DAY)
    app = create_app(_api_settings(tmp_path))
    with TestClient(app) as c:
        assert c.post("/api/login",
                      json={"username": "admin", "password": "testpass123"}
                      ).status_code == 200
        yield c


def test_display_routes_need_a_session_and_the_frame_does_not(api):
    made = api.post("/api/displays", json={"name": "Hallway"}).json()
    token = made["token"]
    api.cookies.clear()
    # The owner's routes are behind the session like everything else...
    assert api.get("/api/displays").status_code == 401
    assert api.patch(f"/api/displays/{token}", json={"name": "X"}).status_code == 401
    assert api.delete(f"/api/displays/{token}").status_code == 401
    # ...and the frame is not, because a screen on a wall has no session and
    # never will. The token is the whole credential.
    assert api.get(f"/api/public/display/{token}").status_code == 200


def test_an_unknown_or_switched_off_display_is_a_404(api):
    made = api.post("/api/displays", json={"name": "Hallway"}).json()
    token = made["token"]
    assert api.get("/api/public/display/nope").status_code == 404
    api.patch(f"/api/displays/{token}", json={"enabled": False})
    assert api.get(f"/api/public/display/{token}").status_code == 404


def test_the_frame_carries_an_etag_and_answers_304_to_a_match(api):
    token = api.post("/api/displays", json={"name": "Hallway"}).json()["token"]
    first = api.get(f"/api/public/display/{token}")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-store, private"
    assert first.headers["x-display-refresh-seconds"] == "300"
    again = api.get(f"/api/public/display/{token}", headers={"If-None-Match": etag})
    # The one piece of HTTP that matters to an eink screen: a 304 is a repaint
    # that does not happen. It has to survive `generated_at` moving, which is
    # why the hash is taken over the frame WITHOUT it.
    assert again.status_code == 304 and not again.content


def test_head_reaches_every_display_route(api):
    """A HEAD is how a panel asks whether anything changed without pulling the
    bytes down to find out — on a board with a few hundred kilobytes of RAM,
    that is the difference between a cheap poll and an expensive one.

    It is also the trap `/book/{token}` already documents: `@app.get` builds a
    FastAPI `APIRoute`, which does NOT derive HEAD from GET the way Starlette's
    plain `Route` does, so these fell through to the SPA mount and answered a
    bare JSON 404 with no ETag in sight.
    """
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 800,
                           "panel_height": 480}).json()["token"]
    for path in (f"/api/public/display/{token}",
                 f"/api/public/display/{token}.png",
                 f"/api/public/display/{token}.bmp",
                 f"/api/public/display/{token}.bin"):
        head = api.head(path)
        assert head.status_code == 200, path
        # The ETag has to be THERE and has to be the one a GET would give, or a
        # panel comparing the two repaints on every poll.
        assert head.headers["etag"] == api.get(path).headers["etag"], path
        assert not head.content, path
        # And it still answers 304, which is the whole point of asking.
        assert api.head(path, headers={"If-None-Match": head.headers["etag"]}
                        ).status_code == 304, path


def test_the_image_needs_a_panel_size_and_then_renders_one(api):
    token = api.post("/api/displays", json={"name": "Hallway"}).json()["token"]
    # 422 rather than a guessed default: there is no honest default panel size,
    # and inventing one hands a device a picture the wrong shape for its screen.
    missing = api.get(f"/api/public/display/{token}.png")
    assert missing.status_code == 422 and "panel size" in missing.text

    asked = api.get(f"/api/public/display/{token}.png?w=800&h=480")
    assert asked.status_code == 200 and asked.headers["content-type"] == "image/png"
    api.patch(f"/api/displays/{token}", json={"panel_width": 640, "panel_height": 384})
    stored = api.get(f"/api/public/display/{token}.png")
    assert stored.status_code == 200
    bmp = api.get(f"/api/public/display/{token}.bmp")
    assert bmp.headers["content-type"] == "image/bmp"
    raw = api.get(f"/api/public/display/{token}.bin")
    assert raw.headers["content-type"] == "application/octet-stream"


def test_the_image_answers_304_as_well(api):
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 800,
                           "panel_height": 480}).json()["token"]
    first = api.get(f"/api/public/display/{token}.png")
    again = api.get(f"/api/public/display/{token}.png",
                    headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and not again.content


@pytest.mark.parametrize("query", ["rotate=45", "palette=sepia", "w=10", "h=99999"])
def test_the_image_refuses_a_geometry_it_cannot_draw(api, query):
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 800,
                           "panel_height": 480}).json()["token"]
    assert api.get(f"/api/public/display/{token}.png?{query}").status_code == 422


def test_the_raw_route_states_what_its_bytes_are(api):
    """Everything a firmware needs to refuse a frame instead of painting it.

    The product assertion is the one that matters: a board compares
    `Content-Length` against `stride × height` computed from its own constants,
    and aborts on a mismatch rather than clocking a mis-shaped buffer onto glass
    it then has to walk over and look at.
    """
    token = api.post("/api/displays",
                     json={"name": "Hallway", "palette": "eink",
                           "panel_width": 800, "panel_height": 480}).json()["token"]
    r = api.get(f"/api/public/display/{token}.bin")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-display-width"] == "800"
    assert r.headers["x-display-height"] == "480"
    assert r.headers["x-display-stride"] == "100"
    assert r.headers["x-display-format"] == "mono-hlsb"
    stride, height = int(r.headers["x-display-stride"]), int(r.headers["x-display-height"])
    assert int(r.headers["content-length"]) == stride * height == len(r.content) == 48_000


def test_the_stride_header_is_not_offered_where_it_would_be_a_lie(api):
    """A BMP's rows are padded to FOUR bytes, not to `ceil(w/8)`.

    At 296 wide that is 40 against 37, so the same header on `.bmp` would be
    wrong for every width where the two disagree, and a client trusting it would
    skew three bytes further on every row.
    """
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 296,
                           "panel_height": 128}).json()["token"]
    assert "x-display-stride" not in api.get(f"/api/public/display/{token}.bmp").headers
    assert "x-display-stride" in api.get(f"/api/public/display/{token}.bin").headers


def test_raw_inverts_on_request_and_says_that_it_did(api):
    token = api.post("/api/displays",
                     json={"name": "Hallway", "palette": "eink",
                           "panel_width": 800, "panel_height": 480}).json()["token"]
    plain = api.get(f"/api/public/display/{token}.bin")
    flipped = api.get(f"/api/public/display/{token}.bin?invert=1")
    assert flipped.content == bytes(b ^ 0xFF for b in plain.content)
    assert flipped.headers["x-display-format"] == "mono-hlsb-inverted"
    # Different bytes must mean a different ETag, or two panels of opposite
    # polarity behind one cache would be handed each other's frame.
    assert flipped.headers["etag"] != plain.headers["etag"]
    # And the parameter is a real boolean, so nonsense is a 422 rather than a
    # silently un-inverted panel.
    assert api.get(f"/api/public/display/{token}.bin?invert=maybe").status_code == 422


def test_raw_refuses_a_palette_because_it_only_has_one(api):
    """Declared so it can be refused.

    FastAPI ignores a query it was never told about, so leaving `palette` out
    would let `?palette=color` look accepted and do nothing — on the one route
    whose entire contract is that its byte width never depends on a setting.
    """
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 800,
                           "panel_height": 480}).json()["token"]
    for value in ("color", "eink"):
        r = api.get(f"/api/public/display/{token}.bin?palette={value}")
        assert r.status_code == 422 and "1-bit" in r.text


def test_raw_is_still_one_bit_when_the_display_is_set_to_colour(api):
    """The colour trap, at the HTTP tier.

    A board that sized its buffer from the documentation and pointed itself at a
    display someone later switched to colour would otherwise be handed 1,152,054
    bytes for its 48,000-byte framebuffer.
    """
    token = api.post("/api/displays",
                     json={"name": "Hallway", "palette": "color",
                           "panel_width": 800, "panel_height": 480}).json()["token"]
    assert len(api.get(f"/api/public/display/{token}.bin").content) == 48_000
    assert len(api.get(f"/api/public/display/{token}.bmp").content) > 1_000_000


def test_an_eink_display_cannot_be_set_to_refresh_faster_than_its_glass(api):
    """Waveshare rate these panels at one refresh per 180s and require them to
    sleep in between — the alternative damages them beyond repair. A minute was
    on offer, which on that hardware is the app recommending its own
    destruction. A colour screen is a backlight and keeps the minute."""
    refused = api.post("/api/displays",
                       json={"name": "Panel", "palette": "eink", "refresh_seconds": 60})
    assert refused.status_code == 422 and "180" in refused.text

    colour = api.post("/api/displays",
                      json={"name": "Tablet", "palette": "color", "refresh_seconds": 60})
    assert colour.status_code == 201 and colour.json()["refresh_seconds"] == 60

    # Flipping that display to eink says nothing about its interval, so refusing
    # the write would be refusing a change the owner DID make because of a value
    # they did not touch. It comes up to the floor instead, and the DTO says so.
    flipped = api.patch(f"/api/displays/{colour.json()['token']}",
                        json={"palette": "eink"})
    assert flipped.status_code == 200 and flipped.json()["refresh_seconds"] == 180


def test_a_legacy_display_below_the_floor_can_still_be_edited(api):
    """The trap a merged-validation floor would spring.

    A display stored at eink/60s before the floor existed must not become
    uneditable: renaming it sends only `{"name": ...}`, and a floor that
    validated the merged row would 422 on a field the caller never touched.
    """
    made = api.post("/api/displays",
                    json={"name": "Legacy", "palette": "color",
                          "refresh_seconds": 60}).json()
    svc = api.app.state.service
    store.update_display(svc._conn, made["token"], {"palette": "eink"})
    renamed = api.patch(f"/api/displays/{made['token']}", json={"name": "Hallway"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Hallway"
    # And it is reported at the floor rather than at what the row still says,
    # so no panel is ever told 60 by a row nobody edited.
    assert renamed.json()["refresh_seconds"] == 180


def test_a_palette_override_reaches_the_render_without_changing_the_display(api):
    token = api.post("/api/displays",
                     json={"name": "Hallway", "palette": "color",
                           "panel_width": 800, "panel_height": 480}).json()["token"]
    colour = api.get(f"/api/public/display/{token}.png").content
    ink = api.get(f"/api/public/display/{token}.png?palette=eink").content
    assert colour != ink
    # The override is per-FETCH: what the display IS has not moved.
    assert api.get("/api/displays").json()[0]["palette"] == "color"


def test_patch_refuses_an_explicit_null_and_zero_clears_the_panel_size(api):
    token = api.post("/api/displays",
                     json={"name": "Hallway", "panel_width": 800,
                           "panel_height": 480}).json()["token"]
    # None is how the service spells "the client did not send this", so a null
    # would be dropped silently and the caller told an edit landed.
    nulled = api.patch(f"/api/displays/{token}", json={"name": None})
    assert nulled.status_code == 422 and "cannot be null" in nulled.text
    cleared = api.patch(f"/api/displays/{token}",
                        json={"panel_width": 0, "panel_height": 0}).json()
    assert cleared["panel_width"] is None and cleared["panel_height"] is None


def test_the_rotate_route_re_keys_in_place(api):
    made = api.post("/api/displays", json={"name": "Hallway"}).json()
    rotated = api.post(f"/api/displays/{made['token']}/rotate").json()
    assert rotated["token"] != made["token"] and rotated["name"] == "Hallway"
    assert api.get(f"/api/public/display/{made['token']}").status_code == 404
    assert api.get(f"/api/public/display/{rotated['token']}").status_code == 200
    assert api.post("/api/displays/nope/rotate").status_code == 404


def test_the_display_page_is_served_as_the_spa_shell(api, tmp_path):
    token = api.post("/api/displays", json={"name": "Hallway"}).json()["token"]
    # No build in this fixture, so the shell is a 404 rather than a route that
    # does not exist — what matters is that BOTH spellings reach the same
    # handler, since a trailing slash is easy to type into a kiosk config.
    for path in (f"/display/{token}", f"/display/{token}/"):
        r = api.get(path)
        assert r.status_code == 404 and "frontend not built" in r.text


# ── what a CalDAV client can write, and what the panel does with it ──────────
#
# Every string in a frame is attacker-adjacent: Tasks.org, Thunderbird, jtx and
# the owner's phone all write to the same Radicale collections, and it lands on
# a route with no session that rasterizes it. These are the two properties that
# were missing, both found by an adversarial sweep of this branch and both
# reproduced end-to-end before being fixed.

def test_a_newline_in_a_title_does_not_500_the_image_routes(api):
    """A newline is ordinary in a SUMMARY and used to be fatal.

    Pillow REFUSES to measure multiline text, so `_fit` raised ValueError out of
    `render_frame` and every image fetch for that display answered 500 — for as
    long as the event existed, while the JSON frame kept working. Asserted
    through the real routes because that is where the 500 was.
    """
    token = api.post("/api/displays",
                     json={"name": "Hall\nway", "palette": "color",
                           "panel_width": 800, "panel_height": 480}).json()["token"]
    api.cookies.clear()
    for suffix in ("", ".png", ".bmp", ".bin"):
        assert api.get(f"/api/public/display/{token}{suffix}").status_code == 200, suffix


def test_control_characters_are_normalised_out_of_the_frame():
    """`plain` is the one edge all three surfaces are built from."""
    assert F.plain("Stand\nup") == "Stand up"
    assert F.plain("a\r\nb") == "a b"
    # A RUN collapses to ONE space rather than each character becoming its own,
    # so the panel and the browser page — which collapses runs itself — draw the
    # same frame the same way.
    assert F.plain("Team \t\n  sync") == "Team sync"
    assert F.plain("  padded  ") == "padded"
    assert F.plain(None) == "" and F.plain("") == ""
    # It is a normaliser, not a sanitiser of legitimate text.
    assert F.plain("Ünïcode — fine") == "Ünïcode — fine"


def test_item_text_is_bounded_wherever_it_enters_the_frame():
    """The length bound, at all four points free text gets in.

    `MAX_ITEMS_PER_DAY` bounds how MANY items a day carries; nothing bounded how
    LONG one was, and the length is the dangerous half — see `MAX_TEXT_CHARS`.
    """
    long = "x" * 5_000
    frame = F.build_frame(
        display=_display_row(name=long), day=DAY, generated_at="t",
        language="en", time_format="24h",
        sources=[{"id": "a", "name": long, "color": "#3B82F6"}],
        events=[{"day": DAY, "summary": long, "start": f"{DAY}T09:00:00",
                 "all_day": False, "source": "a", "continued": False}])
    assert len(frame["display"]["name"]) == F.MAX_TEXT_CHARS
    assert len(frame["sources"][0]["name"]) == F.MAX_TEXT_CHARS
    drawn = [i for wk in frame["calendar"]["weeks"] for c in wk for i in c["items"]]
    assert drawn and all(len(i["text"]) == F.MAX_TEXT_CHARS for i in drawn)

    habits = F.build_frame(
        display=_display_row(mode="habits"), day=DAY, generated_at="t",
        language="en", time_format="24h", planned=True,
        rows=[{"kind": "habit", "title": long, "done": False}])
    assert len(habits["habits"]["habits"][0]["text"]) == F.MAX_TEXT_CHARS


def test_fit_is_not_quadratic_in_the_length_it_is_handed():
    """The half that does not depend on every caller going through `plain`.

    The character-at-a-time loop re-measured the WHOLE string on every step:
    1,000 characters took 0.23s, 4,000 took 2.99s, and `_display_events` copies
    a grid-spanning event's summary into all 42 cells. A wall clock rather than
    a call count because the call count is the mechanism, not the property.
    """
    import time
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("L", (200, 40), 255))
    font = R._font("sans", 14)
    start = time.perf_counter()
    out = R._fit(draw, "A" * 100_000, font, 80)
    assert time.perf_counter() - start < 1.0, "still superlinear in title length"
    assert out.endswith("…") and len(out) < 100

    # And it still answers exactly what the loop it replaced answered.
    for text in ("short", "a title far too long for the space it has", "Küchendienst"):
        for width in (0, 3, 10, 25, 60, 140, 400):
            got = R._fit(draw, text, font, width)
            if got not in ("", text):
                assert got.endswith("…")
                assert R._text_width(draw, got, font) <= width


def test_the_public_render_is_bounded_by_area_and_not_only_by_side(api):
    """Each side being capped at 4096 is not the AREA being capped.

    4096×4096 is 16.7 million pixels and `.bmp` on a colour display is three
    bytes each: one ~200-byte unauthenticated request came back with 50,331,702
    bytes before this bound existed.
    """
    token = api.post("/api/displays", json={"name": "Big", "palette": "color"}).json()["token"]
    api.cookies.clear()
    # A real panel is unaffected — this is every browserless screen that exists.
    assert api.get(f"/api/public/display/{token}.bmp?w=1600&h=1200").status_code == 200
    for suffix in (".png", ".bmp", ".bin"):
        r = api.get(f"/api/public/display/{token}{suffix}?w=4096&h=4096")
        assert r.status_code == 422, suffix
    # And the renderer refuses it too, so the bound is not one caller's habit.
    with pytest.raises(ValueError, match="pixels"):
        R.render_frame(_frame(), width=4096, height=4096, fmt="png")


def test_raw_takes_the_eink_palette_whatever_the_display_is_configured_as():
    """`.bin` is a one-bit format, so it is drawn in one-bit colours.

    Thresholding a COLOUR render was only half of it, and the half that was
    missing was the visible one: `_RULE` is (206, 204, 200), luma 204, so every
    column separator, week rule and header rule converted to PAPER and vanished
    on a display left on the default `color` palette. The length was right and
    the picture was a month with no grid — which is why asserting the byte
    COUNT, as the earlier test did, could not see it.
    """
    colour = R.render_frame(_frame(palette="color"), width=800, height=480, fmt="raw")[0]
    eink = R.render_frame(_frame(palette="eink"), width=800, height=480, fmt="raw")[0]
    assert colour == eink, "raw still depends on how the display is configured"
    # Not vacuously equal because both are blank: a month grid is mostly paper,
    # but its rules alone are thousands of ink pixels.
    ink = sum(8 - bin(byte).count("1") for byte in colour)
    assert ink > 5_000, f"only {ink} ink pixels — the grid is missing"
    # The other two formats keep their palette, which is the whole reason `raw`
    # needed saying separately.
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(
        R.render_frame(_frame(palette="color"), width=800, height=480,
                       fmt="png")[0])).mode == "RGB"
