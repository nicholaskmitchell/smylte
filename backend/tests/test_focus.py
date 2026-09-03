"""The focus session: the clock's settings, and (below) the session itself.

Everything here runs with NO Radicale, the way `test_day_plan.py` does: a focus
session is app-only state that exists nowhere on the wire, so the service reads
the cache and writes SQLite, and seeding `items` directly exercises the real
code with none of the round trips.
"""
from __future__ import annotations

from tasksd.service import FOCUS_DEFAULTS, focus_settings


# ── the clock's settings ─────────────────────────────────────────────────────

def test_focus_settings_fill_every_absent_key():
    """An account that never touched the section gets the whole table, so no
    reader of it has to know a default of its own."""
    assert focus_settings({}) == FOCUS_DEFAULTS
    assert focus_settings({"theme": "dark"}) == FOCUS_DEFAULTS


def test_focus_settings_clamp_and_refuse_junk():
    """A settings blob is hand-editable. An out-of-range int is clamped rather
    than obeyed (a zero-length interval would end before it began), a string is
    the default, and JSON `true` — an int subclass in Python — is NOT one
    minute: the same guard `_effective_capacity` keeps, for the same reason."""
    got = focus_settings({
        "focus_interval_minutes": 0,
        "focus_break_minutes": 999,
        "focus_long_break_minutes": "long",
        "focus_long_break_every": True,
        "focus_auto_continue": "yes",
        "focus_chime": False,
    })
    assert got["focus_interval_minutes"] == 1
    assert got["focus_break_minutes"] == 60
    assert got["focus_long_break_minutes"] == 15
    assert got["focus_long_break_every"] == 4
    assert got["focus_auto_continue"] is False
    assert got["focus_chime"] is False
    # Untouched keys still come back, at their defaults.
    assert got["focus_cap_default"] is False and got["focus_notify"] is False


# ── the session itself ───────────────────────────────────────────────────────
#
# The fixture cast, the seeding helper and `_today` are `test_day_plan`'s own,
# imported rather than copied: a session is a thing done TO a day plan, and a
# second spelling of the day's fixture would be a second thing to keep true.

import pytest  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from tasksd import service as service_mod  # noqa: E402
from tasksd.db import store  # noqa: E402
from tasksd.mcp.api import McpApi  # noqa: E402
from test_day_plan import DAY, LIST_A, LIST_B, _seed_task, _today, svc  # noqa: E402,F401
from test_displays import DAY as DISPLAY_DAY, api  # noqa: E402,F401


class _Clock:
    """The focus clock's `now`, moved by hand. Anchored at a fixed instant so
    every stamp in a test is reproducible; what matters is the differences."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc)

    def tick(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(service_mod, "_focus_now", lambda: c.now)
    return c


@pytest.fixture
def published(monkeypatch, svc):
    events: list[dict] = []
    monkeypatch.setattr(svc, "_publish", events.append)
    return events


def _open_with_notes(svc_, *titles: str) -> str:
    """Today, opened, with one note per title — n1, n2, … — positioned AHEAD
    of whatever the snapshot carried (the fixture's overdue tasks). Negative
    positions because the snapshot and a hand-add both number from 1, and a
    tie is broken by `created_at`, which the snapshot wins."""
    today = _today()
    svc_.open_day(today, create=True)
    for i, title in enumerate(titles, 1):
        svc_.add_day_entry(today, entry_id=f"n{i}", kind="note", title=title)
        svc_.patch_day_entry(today, f"n{i}", position=float(i) - 100)
    return today


def _worked(svc_, day: str, entry_id: str) -> int | None:
    return store.find_day_entry(svc_._conn, day, entry_id=entry_id)["worked_seconds"]


def test_start_needs_a_planned_day_that_is_still_running(svc, clock):
    """A session never opens a day — the same rule a display and the connector
    keep — and never starts on a day that has run."""
    with pytest.raises(ValueError) as caught:
        svc.start_focus(_today())
    assert "not planned" in str(caught.value)
    assert svc.get_focus(_today()) is None
    svc.open_day(DAY, create=True)
    with pytest.raises(ValueError) as caught:
        svc.start_focus(DAY)
    assert "already happened" in str(caught.value)


def test_start_points_at_the_first_open_row_and_is_idempotent(svc, clock, published):
    today = _open_with_notes(svc, "Memo", "Invoice")
    s = svc.start_focus(today)
    assert s["phase"] == "focus" and s["phase_length_s"] == 25 * 60
    assert s["phase_elapsed_s"] == 0 and s["running_since"] and s["ended_at"] is None
    assert s["intervals_done"] == 0 and s["passed"] == []
    assert s["entry_id"] == "n1"
    assert published[-1] == {"type": "focus_updated", "day": today}
    # The other window presses Start a minute later: the session that is
    # running comes back, unchanged and unannounced.
    n = len(published)
    clock.tick(60)
    again = svc.start_focus(today)
    assert again == s and len(published) == n


def test_a_phase_credits_at_most_its_own_length(svc, clock):
    """THE CLAMP. Ten minutes in, a pause banks ten minutes on the row. Resume,
    close the laptop, come back eight hours later: the row shows the one
    interval it was actually given, not the night."""
    today = _open_with_notes(svc, "Memo")
    svc.start_focus(today)
    clock.tick(600)
    s = svc.focus_clock(today, "pause")
    assert s["running_since"] is None and s["phase_elapsed_s"] == 600
    assert _worked(svc, today, "n1") == 600
    svc.focus_clock(today, "resume")
    clock.tick(8 * 3600)
    s = svc.focus_clock(today, "pause")
    assert s["phase_elapsed_s"] == 1500 and _worked(svc, today, "n1") == 1500
    # Resume on a finished phase does not restart the clock: the interval is
    # over, and `next` is the way on.
    assert svc.focus_clock(today, "resume")["running_since"] is None


def test_next_walks_the_pomodoro_cadence(svc, clock):
    svc.update_settings({
        "focus_long_break_every": 2, "focus_break_minutes": 3,
        "focus_long_break_minutes": 9,
    })
    today = _open_with_notes(svc, "Memo")
    svc.start_focus(today)
    clock.tick(1500)
    s = svc.focus_clock(today, "next", expect_phase="focus", expect_intervals=0)
    assert (s["phase"], s["phase_length_s"], s["intervals_done"], s["phase_elapsed_s"]) \
        == ("break", 180, 1, 0)
    assert s["running_since"]
    s = svc.focus_clock(today, "next", expect_phase="break", expect_intervals=1)
    assert s["phase"] == "focus" and s["phase_length_s"] == 1500
    # The second interval done is the long one.
    s = svc.focus_clock(today, "next")
    assert (s["phase"], s["phase_length_s"], s["intervals_done"]) == ("long_break", 540, 2)
    svc.focus_clock(today, "next")
    # "Keep going": straight into the next interval, the finished one counted.
    s = svc.focus_clock(today, "next", skip_break=True)
    assert s["phase"] == "focus" and s["intervals_done"] == 3
    # 0 = never a long one; and a setting changed now moves only the NEXT phase.
    svc.update_settings({"focus_long_break_every": 0, "focus_interval_minutes": 10})
    assert svc.get_focus(today)["phase_length_s"] == 1500
    s = svc.focus_clock(today, "next")
    assert s["phase"] == "break" and s["intervals_done"] == 4
    assert svc.focus_clock(today, "next")["phase_length_s"] == 600


def test_a_stale_next_is_a_silent_no_op(svc, clock, published):
    """Two windows see the interval end and both ask for the next phase. The
    second is answered with the state there is, and nothing is written or
    announced — otherwise it would skip the break the first one started."""
    today = _open_with_notes(svc, "Memo")
    svc.start_focus(today)
    clock.tick(1500)
    first = svc.focus_clock(today, "next", expect_phase="focus", expect_intervals=0)
    n = len(published)
    second = svc.focus_clock(today, "next", expect_phase="focus", expect_intervals=0)
    assert second == first and len(published) == n


def test_pass_sets_the_row_aside_once_however_many_windows_ask(svc, clock, published):
    today = _open_with_notes(svc, "Memo", "Invoice", "Call")
    svc.start_focus(today)
    clock.tick(300)
    s = svc.focus_cursor(today, "pass", entry_id="n1")
    assert s["entry_id"] == "n2" and s["passed"] == ["n1"]
    # Passing is not a pause: the clock kept running, with the time so far banked.
    assert s["running_since"] and s["phase_elapsed_s"] == 300
    assert _worked(svc, today, "n1") == 300
    n = len(published)
    assert svc.focus_cursor(today, "pass", entry_id="n1")["passed"] == ["n1"]
    assert len(published) == n
    # `select` brings a set-aside row back and jumps to it; an unknown row is refused.
    s = svc.focus_cursor(today, "select", entry_id="n1")
    assert s["entry_id"] == "n1" and s["passed"] == []
    with pytest.raises(ValueError):
        svc.focus_cursor(today, "select", entry_id="nope")
    # Pass the three notes: the snapshot's own overdue tasks are still queued
    # behind them, and `again` while a row is open keeps that row — bringing
    # the set-aside ones back is not a reason to leave the one being worked.
    for eid in ("n1", "n2", "n3"):
        svc.focus_cursor(today, "pass", entry_id=eid)
    s = svc.get_focus(today)
    assert s["passed"] == ["n1", "n2", "n3"]
    current = s["entry_id"]
    assert current is not None and current not in ("n1", "n2", "n3")
    s = svc.focus_cursor(today, "again")
    assert s["passed"] == [] and s["entry_id"] == current
    # Drain the queue entirely — the cursor answers None — and `again` starts
    # the round from the first row set aside.
    while (cur := svc.get_focus(today)["entry_id"]) is not None:
        svc.focus_cursor(today, "pass", entry_id=cur)
    s = svc.focus_cursor(today, "again")
    assert s["entry_id"] == "n1" and s["passed"] == []


def test_the_cursor_follows_the_day(svc, clock):
    """Ticked on a phone, cancelled in Thunderbird, deleted by another client:
    the row leaves the queue and the next transition finds the cursor moved,
    with the time up to then credited to the row that was actually being
    worked."""
    today = _open_with_notes(svc, "Memo", "Invoice")
    svc.start_focus(today)
    clock.tick(120)
    svc.patch_day_entry(today, "n1", done=True)
    s = svc.focus_clock(today, "sync")
    assert s["entry_id"] == "n2" and s["running_since"] and s["phase_elapsed_s"] == 120
    assert _worked(svc, today, "n1") == 120 and _worked(svc, today, "n2") is None
    # Behind the notes sit the fixture's overdue tasks, oldest due first.
    svc.focus_cursor(today, "pass", entry_id="n2")
    plan = svc.open_day(today, create=False)
    by_uid = {e["uid"]: e["entry_id"] for e in plan["entries"] if e["kind"] == "task"}
    assert svc.get_focus(today)["entry_id"] == by_uid["late"]
    _seed_task(svc._conn, LIST_B, "late", "Call the plumber", due="2026-08-19",
               status="CANCELLED")
    assert svc.focus_clock(today, "sync")["entry_id"] == by_uid["due-today"]
    store.delete_item_by_href(svc._conn, LIST_A, f"{LIST_A}due-today.ics")
    assert svc.focus_clock(today, "sync")["entry_id"] == by_uid["later"]


def test_habits_come_first_as_today_paints_them(svc, clock):
    """Today draws its habit rows above the day's rows; the queue follows what
    the owner sees rather than the raw column order, under which an
    unpositioned habit would sort last."""
    svc.create_habit(title="Stretch")
    today = _open_with_notes(svc, "Memo")
    s = svc.start_focus(today)
    plan = svc.open_day(today, create=False)
    habit = next(e for e in plan["entries"] if e["kind"] == "habit")
    assert s["entry_id"] == habit["entry_id"]
    svc.patch_day_entry(today, habit["entry_id"], done=True)
    assert svc.focus_clock(today, "sync")["entry_id"] == "n1"


def test_end_settles_and_a_later_start_is_a_fresh_session(svc, clock):
    today = _open_with_notes(svc, "Memo")
    first = svc.start_focus(today)
    clock.tick(700)
    s = svc.focus_clock(today, "end")
    assert s["ended_at"] and s["running_since"] is None
    assert _worked(svc, today, "n1") == 700
    # An ended session is a record: no clock or cursor action moves it.
    assert svc.focus_clock(today, "resume")["running_since"] is None
    assert svc.focus_cursor(today, "pass", entry_id="n1")["passed"] == []
    clock.tick(60)
    fresh = svc.start_focus(today)
    assert fresh["ended_at"] is None and fresh["intervals_done"] == 0
    assert fresh["phase_elapsed_s"] == 0 and fresh["started_at"] != first["started_at"]
    # The credit outlives the session it was earned in.
    assert _worked(svc, today, "n1") == 700


def test_a_day_with_no_session_answers_none_and_a_bad_action_is_refused(svc, clock):
    today = _open_with_notes(svc, "Memo")
    assert svc.get_focus(today) is None
    assert svc.focus_clock(today, "pause") is None
    assert svc.focus_cursor(today, "again") is None
    svc.start_focus(today)
    with pytest.raises(ValueError):
        svc.focus_clock(today, "fly")
    with pytest.raises(ValueError):
        svc.focus_cursor(today, "select")


def test_the_connector_reports_what_was_worked(svc, clock):
    today = _open_with_notes(svc, "Memo")
    svc.start_focus(today)
    clock.tick(600)
    svc.focus_clock(today, "pause")
    out = McpApi(svc).today()
    assert out["totals"]["worked_minutes"] == 10
    memo = next(e for e in out["entries"] if e["entry_id"] == "n1")
    assert memo["worked_seconds"] == 600 and memo["capped"] is None


# ── the routes ───────────────────────────────────────────────────────────────

def test_focus_routes(api):
    """The HTTP contract over the service: null for no session, 422 for every
    refusal the service spells (a day nobody planned, a row that is not open,
    an action the model does not know), 404 for a day with no session, and
    the SPA shell on both spellings of /focus."""
    day = DISPLAY_DAY
    assert api.get(f"/api/focus/{day}").json() is None
    assert api.post(f"/api/focus/{day}/start").status_code == 422
    api.post(f"/api/day/{day}/open")
    api.post(f"/api/day/{day}/entries",
             json={"entry_id": "n1", "kind": "note", "title": "Memo"})
    r = api.post(f"/api/focus/{day}/start")
    assert r.status_code == 200 and r.json()["entry_id"] == "n1", r.text
    r = api.post(f"/api/focus/{day}/clock", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["running_since"] is None
    r = api.patch(f"/api/day/{day}/entries/n1", json={"capped": True})
    assert r.status_code == 200 and r.json()["capped"] is True
    assert api.post(f"/api/focus/{day}/clock", json={"action": "fly"}).status_code == 422
    assert api.post(f"/api/focus/{day}/cursor",
                    json={"action": "select", "entry_id": "nope"}).status_code == 422
    assert api.post("/api/focus/2027-01-01/clock", json={"action": "pause"}).status_code == 404
    assert api.post("/api/focus/2027-13-01/start").status_code == 422
    for path in ("/focus", "/focus/"):
        r = api.get(path)
        assert r.status_code == 404 and "frontend not built" in r.text
    api.cookies.clear()
    assert api.get(f"/api/focus/{day}").status_code == 401
