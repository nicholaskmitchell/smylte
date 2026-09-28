"""Habits: the rules that put entries on a day, and the reconcile that runs them.

A habit is A RULE THAT INSERTS ENTRIES, not a parallel subsystem. Its
occurrences are ordinary `day_plan` rows (kind="habit", source="habit") carrying
a COPY of the title, so every property the day plan already guarantees — a
dropped row is kept rather than deleted, a past day is never rewritten, an entry
outlives the thing it names — has to keep holding once habits exist. That is what
this file pins. Nothing here touches Radicale: habits are app-only, never PUT,
never an RRULE (docs/recurrence-findings.md), so the service reads and writes
SQLite and the wire is not involved.

The fixture pieces come from `test_day_plan` rather than a second copy of them.
The day keys in particular have to be the SAME fixed days: a snapshot is a
function of the day it is built for, and the two suites are asserting about one
mechanism.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from test_day_plan import DAY, LIST_A, NEXT, PREV, _seed_task, _settings

from smylted.dav.client import CollectionInfo
from smylted.db import store
from smylted.mcp.api import McpApi
from smylted.service import (
    SmylteService,
    _WEEKDAYS,
    habit_runs_on,
    normalize_habit_days,
)

# DAY is a Friday, PREV a Thursday, NEXT a Saturday — asserted below rather than
# trusted, because every scheduling expectation in this file rests on it.
FRI, THU, SAT = "fri", "thu", "sat"
# Two days before DAY: past even with `_habit_minting_allowed`'s one-day grace.
LONG_PAST = "2026-08-19"


@pytest.fixture
def svc(monkeypatch):
    s = SmylteService(_settings())
    store.upsert_collection(
        s._conn, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"})
    )
    # One ordinary task due on DAY, so the snapshot has something to put BEHIND
    # the habits: "habits lead the day" is only a claim worth making when there
    # is a second group for them to lead.
    _seed_task(s._conn, LIST_A, "due-today", "Ship the thing", due=DAY)
    # Today is DAY by default, for every test in this file.
    #
    # The pastness check governs BOTH paths that mint occurrences now — the
    # first snapshot as well as the top-up — so any test that opens DAY with a
    # habit in the account reads the clock, not just the ones that say they do.
    # Left unpinned, this suite passed only while the wall clock happened to sit
    # within a day of DAY and would have started failing on the day after that,
    # in tests that never mention time. Tests wanting a different today still
    # call `_pin_today`, which overrides this.
    _pin_today(monkeypatch, s, DAY)
    yield s
    s.close()


def _pin_today(monkeypatch, svc_, day: str) -> None:
    """Pin the service's idea of the owner's today.

    The window `_writable_floor` draws is the one part of this feature that
    consults a clock — but it is consulted from `_habit_entries_for`, so EVERY
    path that mints an occurrence reads it, and so does every estimate that
    fills or teaches one. A suite whose expectations move at midnight is a suite
    that fails at midnight. Patching `_today` rather than the clock keeps the
    seam where the code puts it: `_today` is the single place the owner's day is
    decided.
    """
    monkeypatch.setattr(svc_, "_today", lambda: day)


def _habits_on(plan: dict) -> list[dict]:
    return [e for e in plan["entries"] if e["kind"] == "habit"]


def _count(svc_, table: str) -> int:
    # The table names are literals in this file, never input.
    return svc_._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608


# ── the weekday vocabulary ───────────────────────────────────────────────────

def test_the_weekday_names_round_trip_against_python():
    """`_WEEKDAYS` is the ONE place the names and the numbers meet, so this is
    the test that it means what the rest of the code assumes.

    Python's `date.weekday()` is 0=Monday, scheduling.py already keys booking
    availability "0" (Monday).."6" (Sunday), and `days` is written mon..sun. A
    tuple written one place out — a leading "sun", say — would not raise
    anywhere: it would quietly shift every habit by a day, correctly for six of
    the seven names on any given week, which is the kind of bug that is found in
    production and not before.
    """
    assert _WEEKDAYS == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    # Name → number → name, over a real consecutive week (2026-08-17 is a Monday).
    for i, name in enumerate(_WEEKDAYS):
        key = (date(2026, 8, 17) + timedelta(days=i)).isoformat()
        assert date.fromisoformat(key).weekday() == i
        assert _WEEKDAYS[date.fromisoformat(key).weekday()] == name
        assert habit_runs_on(name, key)
        # …and only on that day: the other six names must not match it.
        assert not any(habit_runs_on(other, key) for other in _WEEKDAYS if other != name)
    # The fixture days this file reasons about.
    assert (_WEEKDAYS[date.fromisoformat(PREV).weekday()],
            _WEEKDAYS[date.fromisoformat(DAY).weekday()],
            _WEEKDAYS[date.fromisoformat(NEXT).weekday()]) == (THU, FRI, SAT)
    # "" is every day — the absence of a restriction, not a list of seven.
    assert all(habit_runs_on("", d) for d in (PREV, DAY, NEXT))
    # The weekday is taken from the KEY's own characters, never from a clock:
    # the same string always answers the same way, in any zone, at any hour.
    assert habit_runs_on("mon,fri", DAY) and not habit_runs_on("mon,sat", DAY)


def test_days_is_validated_and_normalised():
    assert normalize_habit_days(None) == ""
    assert normalize_habit_days("  ") == ""
    # Order-normalised: "fri,mon" and "mon,fri" are ONE schedule, so they get one
    # spelling — otherwise a client diffing what it sent against what it got back
    # would see a change that did not happen.
    assert normalize_habit_days("fri,mon") == "mon,fri"
    assert normalize_habit_days("SUN, Mon ") == "mon,sun"
    with pytest.raises(ValueError, match="listed twice"):
        normalize_habit_days("mon,mon")
    with pytest.raises(ValueError, match="unknown day"):
        normalize_habit_days("mon,funday")


def test_an_rrule_shaped_days_is_refused_by_name():
    """The boundary this app draws, stated in the error itself.

    "every second Tuesday" is the request that turns a habit into VTODO
    recurrence, which is GATED — so an RRULE arriving in `days` is refused with a
    message that names the design note, rather than being reported as a spelling
    mistake or, worse, half-parsed.
    """
    for bad in ("FREQ=WEEKLY;BYDAY=MO", "RRULE:FREQ=DAILY", "MO,WE,FR",
                "weekly", "INTERVAL=2"):
        with pytest.raises(ValueError) as e:
            normalize_habit_days(bad)
        assert "docs/recurrence-findings.md" in str(e.value), bad


# ── the occurrence ───────────────────────────────────────────────────────────

def test_an_occurrence_appears_on_a_scheduled_weekday_and_not_on_others(svc):
    """The whole feature in one test: a rule, and the row it puts on a day.

    The occurrence is an ordinary day_plan row — same table, same reading order,
    same patch surface — carrying a COPY of the habit's title and the id of the
    rule that minted it. It names no task, so `list` and `uid` are null.
    """
    habit = svc.create_habit(title="Stretch", days=FRI)
    plan = svc.open_day(DAY, create=True)
    rows = _habits_on(plan)
    assert len(rows) == 1
    row = rows[0]
    assert (row["title"], row["source"], row["habit_id"]) == ("Stretch", "habit", habit["id"])
    assert row["list"] is None and row["uid"] is None
    # Habits lead the dense position sequence, ahead of the day's due work:
    # what the owner does every day reads before what merely falls due.
    assert [e["kind"] for e in plan["entries"]] == ["habit", "task"]
    assert [e["position"] for e in plan["entries"]] == [1.0, 2.0]

    # Saturday is not Friday. The rule is the only thing that decides this, and
    # it decides it from the day KEY.
    assert _habits_on(svc.open_day(NEXT, create=True)) == []
    assert _habits_on(svc.open_day(PREV, create=True)) == []


def test_an_occurrence_never_carries_into_the_next_day(svc):
    """Tomorrow's occurrence is tomorrow's RULE running again — never today's
    leftover following the owner around.

    This falls out of source="habit": `_carry_into` keeps only source="user"
    rows. So an unfinished occurrence stays on its own day (which is the honest
    record: that is the day it was not done) and the next day gets a fresh row
    with a fresh entry_id.
    """
    svc.create_habit(title="Stretch")              # every day
    first = _habits_on(svc.open_day(PREV, create=True))[0]
    assert first["done_at"] is None                # deliberately left unfinished

    plan = svc.open_day(DAY, create=True)
    rows = _habits_on(plan)
    assert len(rows) == 1
    assert rows[0]["source"] == "habit"            # not "carried"
    assert rows[0]["entry_id"] != first["entry_id"]
    assert not [e for e in plan["entries"] if e["source"] == "carried"]
    # PREV keeps its own row, untouched.
    assert len(_habits_on(svc.open_day(PREV, create=False))) == 1


def test_a_preview_shows_the_habits_an_open_would_add(svc):
    """`preview_day` is the same derivation thrown away, so it has to include
    habits — a connector answering "what is on today" for an unopened day would
    otherwise describe a day that is missing exactly the entries the owner is
    most certain to see."""
    svc.create_habit(title="Stretch", days=FRI)
    preview = svc.preview_day(DAY)
    assert [p["kind"] for p in preview] == ["habit", "task"]
    assert preview[0]["title"] == "Stretch" and preview[0]["habit_id"]
    # Still a preview: nothing was written, so the day is still unplanned.
    assert svc.open_day(DAY, create=False)["planned"] is False
    assert _count(svc, "day_plan") == 0


def test_a_preview_of_a_planned_day_is_not_empty_once_a_habit_arrives(svc):
    """`preview_day` promised "[] for a day that has already had one". It never
    delivered that, and nothing pinned it.

    A habit created after the day was opened has no row on the day yet, so the
    derivation still proposes it — which is CORRECT and is what the next open's
    top-up would in fact add. The docstring now describes this instead of denying
    it, and this is the test that keeps the two in step.
    """
    svc.open_day(DAY, create=True)
    assert svc.preview_day(DAY) == []             # true right after the snapshot
    svc.create_habit(title="Stretch", days=FRI)
    preview = svc.preview_day(DAY)
    assert [p["kind"] for p in preview] == ["habit"]
    assert preview[0]["title"] == "Stretch"
    # And it was a forecast, not a fiction: the next open adds that very row.
    assert [e["title"] for e in _habits_on(svc.open_day(DAY, create=True))] == ["Stretch"]


# ── the top-up (the reconcile rule) ──────────────────────────────────────────

def test_a_habit_created_after_the_day_was_opened_appears_on_the_next_open(svc, monkeypatch):
    """The reason an already-planned day is reconciled at all.

    A rule made this morning has to reach today: the alternative is that creating
    a habit does nothing visible until tomorrow, on the one screen it exists for.
    Only the habit is added — the snapshot-once rule is untouched, so no task is
    re-derived — and it lands BEHIND the arrangement it is joining rather than
    renumbering it.
    """
    _pin_today(monkeypatch, svc, DAY)
    plan = svc.open_day(DAY, create=True)
    assert _habits_on(plan) == []
    before = [(e["entry_id"], e["position"]) for e in plan["entries"]]

    svc.create_habit(title="Stretch", days=FRI)
    after = svc.open_day(DAY, create=True)
    assert len(_habits_on(after)) == 1
    assert [(e["entry_id"], e["position"]) for e in after["entries"]][:len(before)] == before
    assert _habits_on(after)[0]["position"] == before[-1][1] + 1.0

    # And exactly once: the next open finds the habit already present on the day
    # and adds nothing.
    assert svc.open_day(DAY, create=True)["entries"] == after["entries"]
    assert _count(svc, "day_plan") == len(after["entries"])


def test_habits_lead_the_snapshot_but_never_jump_a_hand_added_row(svc):
    """"Habits lead the day" is true of `pending`, not of the day.

    A day whose first write was a hand-add is snapshotted on its first open all
    the same — `_snapshot_for` MERGES with those rows rather than landing beside
    them — so `base` is non-zero and the habits go behind the hand-added note,
    exactly as an evening top-up does. A comment claimed habits "lead only the
    FIRST snapshot, where there is no arrangement yet to disturb"; this is the
    first snapshot, and there is an arrangement.
    """
    svc.create_habit(title="Stretch")             # every day, so NEXT gets it too
    note = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note",
                             title="Hand-added first")
    plan = svc.open_day(DAY, create=True)         # still the FIRST open
    assert [e["kind"] for e in plan["entries"]] == ["note", "habit", "task"]
    assert plan["entries"][0]["entry_id"] == note["entry_id"]
    # The hand-added row keeps the position it was given; the snapshot appends.
    assert [e["position"] for e in plan["entries"]] == [1.0, 2.0, 3.0]

    # On an empty day the same snapshot does lead with the habit, which is the
    # half of the claim that was true.
    other = svc.open_day(NEXT, create=True)
    assert [e["kind"] for e in other["entries"]][:1] == ["habit"]


def test_a_dropped_occurrence_is_not_resurrected_by_the_top_up(svc, monkeypatch):
    """A DROPPED row counts as present.

    Dropping is how the owner says "not today", and the row is stamped rather
    than deleted so the day keeps that record. If the top-up looked only at live
    rows, a habit dropped this morning would come back on the very next visit to
    the tab — the resurrection the opened marker exists to prevent, happening
    once per render instead of once per day.
    """
    _pin_today(monkeypatch, svc, DAY)
    svc.create_habit(title="Stretch", days=FRI)
    row = _habits_on(svc.open_day(DAY, create=True))[0]
    assert svc.patch_day_entry(DAY, row["entry_id"], dropped=True)["dropped_at"]

    again = svc.open_day(DAY, create=True)
    rows = _habits_on(again)
    assert len(rows) == 1
    assert rows[0]["entry_id"] == row["entry_id"] and rows[0]["dropped_at"]
    assert _count(svc, "day_plan") == 2          # the occurrence plus the task


def test_a_past_day_is_never_reconciled(svc, monkeypatch):
    """A past day is the record of what was intended AT THE TIME.

    Topping it up writes today's rules into yesterday, which is a forgery however
    small — and it is the property the whole log depends on: a plan that can be
    backfilled can never be told apart from one that was written on the day.
    """
    _pin_today(monkeypatch, svc, LONG_PAST)
    opened = svc.open_day(LONG_PAST, create=True)
    assert _habits_on(opened) == []
    before = _count(svc, "day_plan")

    svc.create_habit(title="Stretch")             # every day, including that one
    _pin_today(monkeypatch, svc, DAY)             # …but that day is now past
    after = svc.open_day(LONG_PAST, create=True)
    assert _habits_on(after) == []
    assert _count(svc, "day_plan") == before
    assert [e["entry_id"] for e in after["entries"]] == [
        e["entry_id"] for e in opened["entries"]
    ]


def test_a_first_open_of_a_past_day_mints_no_habits(svc, monkeypatch):
    """The same forgery as above, through the door the check did not cover.

    The pastness rule used to be asked at ONE of the two places that mint
    occurrences — `open_day`'s top-up of an already-planned day. The other, the
    first snapshot of a day that had NEVER been opened, reached
    `_habit_entries_for` through `_snapshot_for` and minted freely: so
    `POST /api/day/2020-01-01/open` wrote today's rules into a day that had
    already happened, while the test above passed.

    It is the worse half of the two, because a habit occurrence's row is the ONLY
    record of it anywhere — there is no VTODO behind it to disagree — so once
    backfilled it cannot be told from one written on the day, and the phantom
    un-ticked rows read as MISSES in `review_day`'s habits arm and in the
    "n of m this week" the tab counts off these same rows.

    The day's TASKS still snapshot, which is deliberate and predates habits: a
    task entry is a pointer to a VTODO that is still due or still late, and it
    claims nothing about what the owner intended that day.
    """
    _seed_task(svc._conn, LIST_A, "old-work", "Due back then", due=LONG_PAST)
    svc.create_habit(title="Stretch")             # every day, including that one
    # The fixture's default, restated: every assertion here rests on LONG_PAST
    # being two days behind today, past even with the one-day grace.
    _pin_today(monkeypatch, svc, DAY)

    # The preview agrees before anything is written, because it is the same
    # derivation: one that showed habits would describe an open that cannot
    # happen.
    assert [p["kind"] for p in svc.preview_day(LONG_PAST)] == ["task"]

    plan = svc.open_day(LONG_PAST, create=True)   # the FIRST open of that day
    assert _habits_on(plan) == []
    assert [(e["kind"], e["uid"]) for e in plan["entries"]] == [("task", "old-work")]
    # Nowhere in the table, not merely absent from this DTO.
    assert svc._conn.execute(
        "SELECT COUNT(*) FROM day_plan WHERE kind='habit'"
    ).fetchone()[0] == 0
    # The marker still landed, so the day is planned and re-opening adds nothing.
    assert plan["planned"] is True
    assert svc.open_day(LONG_PAST, create=True)["entries"] == plan["entries"]


def test_yesterday_is_still_topped_up_by_the_one_day_grace(svc, monkeypatch):
    """The grace is deliberate, and it is what keeps the feature alive after 20:00.

    `home_timezone` is unset by default and the server is UTC in the ordinary
    deployment, so a browser in New York between 20:00 and midnight sends the key
    for a day the server already calls yesterday. Without the grace every habit
    would vanish from the tab each evening and reappear at midnight.
    """
    svc.create_habit(title="Stretch")              # every day
    # The evening browser: the day it asks for is one behind the server's own.
    _pin_today(monkeypatch, svc, NEXT)
    opened = svc.open_day(DAY, create=True)        # first open: full snapshot
    assert len(_habits_on(opened)) == 1
    # A second habit arrives while that same "yesterday" is still on screen.
    svc.create_habit(title="Water the plants")
    assert len(_habits_on(svc.open_day(DAY, create=True))) == 2
    # Two days back is past, grace or no grace.
    _pin_today(monkeypatch, svc, DAY)
    svc.open_day(LONG_PAST, create=True)
    svc.create_habit(title="Too late")
    titles = [e["title"] for e in _habits_on(svc.open_day(LONG_PAST, create=True))]
    assert "Too late" not in titles


# ── pause / rename / delete ──────────────────────────────────────────────────

def test_pausing_stops_future_occurrences_and_leaves_past_ones(svc, monkeypatch):
    """Pausing means "stop scheduling this", never "pretend the last three weeks
    did not happen". The rows already on past days are ordinary day_plan entries
    and nothing in the habits section can reach them."""
    _pin_today(monkeypatch, svc, DAY)
    habit = svc.create_habit(title="Stretch")      # every day
    done_row = _habits_on(svc.open_day(PREV, create=True))[0]
    svc.patch_day_entry(PREV, done_row["entry_id"], done=True)

    paused = svc.update_habit(habit["id"], paused=True)
    assert paused["paused_at"]
    assert _habits_on(svc.open_day(DAY, create=True)) == []
    # …and the top-up does not add it either, on a day that is already planned.
    assert _habits_on(svc.open_day(DAY, create=True)) == []
    # PREV is untouched, ticked stamp and all.
    kept = _habits_on(svc.open_day(PREV, create=False))
    assert len(kept) == 1 and kept[0]["done_at"] and kept[0]["title"] == "Stretch"
    # A paused habit is still LISTED — the screen that resumes it has to show it.
    assert [h["id"] for h in svc.list_habits()] == [habit["id"]]

    # Resuming puts it back on the next open, with no trace of the pause on the
    # day itself.
    assert svc.update_habit(habit["id"], paused=False)["paused_at"] is None
    assert len(_habits_on(svc.open_day(DAY, create=True))) == 1


def test_deleting_a_habit_leaves_its_past_occurrences_readable(svc, monkeypatch):
    """DELETE removes the DEFINITION only.

    The occurrence keeps the title it copied and a habit_id that now points at
    nothing. That dangling id is the design: those rows are the record that the
    owner planned this on those days, and no sweep may ever collect them —
    nothing in this app deletes from day_plan at all.
    """
    _pin_today(monkeypatch, svc, DAY)
    habit = svc.create_habit(title="Stretch")
    row = _habits_on(svc.open_day(DAY, create=True))[0]
    svc.patch_day_entry(DAY, row["entry_id"], done=True)

    assert svc.delete_habit(habit["id"]) is True
    assert svc.delete_habit(habit["id"]) is False       # gone, and idempotent-ish
    assert svc.list_habits() == []

    kept = _habits_on(svc.open_day(DAY, create=False))
    assert len(kept) == 1
    assert (kept[0]["title"], kept[0]["habit_id"]) == ("Stretch", habit["id"])
    assert kept[0]["done_at"]
    assert _count(svc, "day_plan") == 2                 # nothing was collected
    # And the day it is on is not re-derived by the deletion either.
    assert _habits_on(svc.open_day(DAY, create=True)) == kept


def test_a_rename_does_not_rewrite_yesterday(svc, monkeypatch):
    """The title is copied at mint time, so a past day keeps saying what the
    owner actually planned that day. Only occurrences minted from now on carry
    the new name."""
    _pin_today(monkeypatch, svc, DAY)
    habit = svc.create_habit(title="Stretch")
    svc.open_day(PREV, create=True)
    assert svc.update_habit(habit["id"], title="Stretch properly")["title"] == "Stretch properly"
    assert [e["title"] for e in _habits_on(svc.open_day(PREV, create=False))] == ["Stretch"]
    assert [e["title"] for e in _habits_on(svc.open_day(DAY, create=True))] == ["Stretch properly"]


def test_unknown_habit_and_empty_patches(svc):
    assert svc.update_habit("nope", title="x") is None
    assert svc.delete_habit("nope") is False
    habit = svc.create_habit(title="Stretch")
    # An empty patch is a read: it returns the habit unchanged rather than
    # reporting it missing.
    assert svc.update_habit(habit["id"]) == habit
    with pytest.raises(ValueError):
        svc.create_habit(title="   ")
    with pytest.raises(ValueError):
        svc.update_habit(habit["id"], title=" ")


# ── an estimate, said once ───────────────────────────────────────────────────
#
# How long a habit takes is a standing answer, so it is said once and every day
# after starts from it — whichever end it is said at. Typed on an occurrence in
# the app, it teaches the rule; set on the rule, it reaches the rows already
# waiting on days still open. Either way it only ever fills a BLANK: a number a
# day already holds is that day's own (copy-never-join, as for the title), and a
# day that has run, or a row the owner declined, is a record that no later
# answer rewrites. These tests pin both doors and each of the three fences.

# Further days after NEXT, for tests that need more than one open day ahead.
NEXT2 = "2026-08-23"
NEXT3 = "2026-08-24"


def _rule(svc_, habit_id: str) -> dict:
    return next(h for h in svc_.list_habits() if h["id"] == habit_id)


def _occ(svc_, day: str, habit_id: str) -> dict:
    """The one occurrence of `habit_id` on `day`, dropped or not, read back
    without opening anything."""
    rows = [e for e in svc_.open_day(day, create=False)["entries"]
            if e["habit_id"] == habit_id]
    assert len(rows) == 1, (day, rows)
    return rows[0]


def test_estimating_todays_occurrence_teaches_the_rule(svc, monkeypatch):
    """The bug this section exists for. Estimating "Read" on Today used to set
    that one row, so tomorrow's occurrence was minted blank and the ritual asked
    again — every morning, for a number that never changes. The row's number is
    now written through to the rule, and the next day's first open copies it."""
    habit = svc.create_habit(title="Read")               # every day, unestimated
    occ = _habits_on(svc.open_day(DAY, create=True))[0]
    assert occ["estimate_minutes"] is None
    sidecars = _count(svc, "sidecar")

    dto = svc.patch_day_entry(DAY, occ["entry_id"], estimate_minutes=20)
    assert dto["estimate_minutes"] == 20
    assert _rule(svc, habit["id"])["estimate_minutes"] == 20
    # The habit arm is not the task arm: an occurrence has no task behind it,
    # so nothing lands in the sidecar table.
    assert _count(svc, "sidecar") == sidecars

    _pin_today(monkeypatch, svc, NEXT)                   # tomorrow, as today
    assert [e["estimate_minutes"]
            for e in _habits_on(svc.open_day(NEXT, create=True))] == [20]


def test_an_estimate_on_the_rule_fills_only_the_blanks_on_days_still_open(svc, monkeypatch):
    """Estimating a habit on the habits screen reaches the row already sitting on
    today — and on any later day already opened — rather than waiting for
    tomorrow's mint. What it may fill is narrow, and each exclusion below is a
    thing a day has already said: a number of its own (here one copied off an
    older version of the rule), a decision to decline the row, or simply having
    happened. The grace day is still open, as it is for minting."""
    habit = svc.create_habit(title="Read")               # every day, unestimated
    other = svc.create_habit(title="Stretch")            # never estimated at all
    # A day that has run, minted while it was still today.
    _pin_today(monkeypatch, svc, LONG_PAST)
    svc.open_day(LONG_PAST, create=True)
    _pin_today(monkeypatch, svc, DAY)
    # A number copied off an older rule: estimate the rule, mint a day, then
    # clear the rule — which fills nothing and UN-fills nothing.
    svc.update_habit(habit["id"], estimate_minutes=45)
    svc.open_day(NEXT2, create=True)
    svc.update_habit(habit["id"], estimate_minutes=-1)
    assert _occ(svc, NEXT2, habit["id"])["estimate_minutes"] == 45
    # Blanks on the grace day, today, tomorrow, and a later day then declined.
    for d in (PREV, DAY, NEXT, NEXT3):
        svc.open_day(d, create=True)
    svc.patch_day_entry(NEXT3, _occ(svc, NEXT3, habit["id"])["entry_id"], dropped=True)

    assert svc.update_habit(habit["id"], estimate_minutes=30)["estimate_minutes"] == 30

    got = {d: _occ(svc, d, habit["id"])["estimate_minutes"]
           for d in (LONG_PAST, PREV, DAY, NEXT, NEXT2, NEXT3)}
    assert got == {
        LONG_PAST: None,   # has run: a record, not a plan
        PREV: 30,          # the grace day is still open
        DAY: 30,
        NEXT: 30,
        NEXT2: 45,         # its own number, kept
        NEXT3: None,       # declined: counts for nothing, so is given nothing
    }
    # One rule's rows, and only habit rows: the other habit's blanks and the
    # day's task entry are untouched.
    assert [_occ(svc, d, other["id"])["estimate_minutes"]
            for d in (PREV, DAY, NEXT)] == [None, None, None]
    assert [e["estimate_minutes"] for e in svc.open_day(DAY, create=False)["entries"]
            if e["kind"] == "task"] == [None]


def test_an_occurrence_estimate_fills_the_habits_other_blanks(svc):
    """The other door onto the same fill. Tomorrow, already opened, would
    otherwise keep asking the question today just answered. And a second answer
    later moves the rule again without reaching back into the rows the first
    one filled — by then those numbers are those days' own."""
    habit = svc.create_habit(title="Read")
    for d in (DAY, NEXT, NEXT2):
        svc.open_day(d, create=True)

    svc.patch_day_entry(NEXT, _occ(svc, NEXT, habit["id"])["entry_id"], estimate_minutes=10)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 10
    assert [_occ(svc, d, habit["id"])["estimate_minutes"]
            for d in (DAY, NEXT, NEXT2)] == [10, 10, 10]

    svc.patch_day_entry(DAY, _occ(svc, DAY, habit["id"])["entry_id"], estimate_minutes=25)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 25
    assert [_occ(svc, d, habit["id"])["estimate_minutes"]
            for d in (DAY, NEXT, NEXT2)] == [25, 10, 10]
    # A day minted afterwards starts from the newest answer.
    assert _habits_on(svc.open_day(NEXT3, create=True))[0]["estimate_minutes"] == 25


def test_a_declined_occurrence_or_a_day_that_has_run_teaches_nothing(svc, monkeypatch):
    """Two rows whose number is that day's business alone.

    A day that has run: REST can still estimate it — only the connector fences
    a past-day estimate — but a number tidied onto last week is a record being
    corrected, not a plan for tomorrow. A dropped row: it counts for nothing on
    its own day, so it must not decide every day after it. "Dropped" is judged
    as the row stands once the PATCH lands, so a body that drops and estimates
    teaches nothing, and one that restores and estimates does teach.
    """
    habit = svc.create_habit(title="Read", estimate_minutes=20)
    _pin_today(monkeypatch, svc, LONG_PAST)
    past = _habits_on(svc.open_day(LONG_PAST, create=True))[0]
    _pin_today(monkeypatch, svc, DAY)
    today = _habits_on(svc.open_day(DAY, create=True))[0]
    tomorrow = _habits_on(svc.open_day(NEXT, create=True))[0]

    assert svc.patch_day_entry(
        LONG_PAST, past["entry_id"], estimate_minutes=90)["estimate_minutes"] == 90
    assert _rule(svc, habit["id"])["estimate_minutes"] == 20

    svc.patch_day_entry(DAY, today["entry_id"], dropped=True)
    assert svc.patch_day_entry(
        DAY, today["entry_id"], estimate_minutes=50)["estimate_minutes"] == 50
    assert _rule(svc, habit["id"])["estimate_minutes"] == 20

    svc.patch_day_entry(NEXT, tomorrow["entry_id"], dropped=True, estimate_minutes=5)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 20

    svc.patch_day_entry(DAY, today["entry_id"], dropped=False, estimate_minutes=35)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 35


def test_yesterday_still_teaches_inside_the_grace(svc, monkeypatch):
    """The same one-day grace minting and the rituals allow, for the same
    reason: an evening browser west of the server sends yesterday's key for what
    is, to its owner, still today. Estimating that row has to teach the rule,
    or the feature stops working after dinner."""
    habit = svc.create_habit(title="Read")
    _pin_today(monkeypatch, svc, PREV)
    occ = _habits_on(svc.open_day(PREV, create=True))[0]
    _pin_today(monkeypatch, svc, DAY)                    # the server has moved on

    svc.patch_day_entry(PREV, occ["entry_id"], estimate_minutes=40)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 40


def test_an_occurrence_of_a_deleted_habit_can_still_be_estimated(svc):
    """A dangling habit_id is the design — the row outlives its rule — so there
    is no rule to teach, and that is not an error: the day's own write lands and
    no habit is conjured back into existence."""
    habit = svc.create_habit(title="Read")
    occ = _habits_on(svc.open_day(DAY, create=True))[0]
    assert svc.delete_habit(habit["id"]) is True

    dto = svc.patch_day_entry(DAY, occ["entry_id"], estimate_minutes=30)
    assert dto["estimate_minutes"] == 30 and dto["habit_id"] == habit["id"]
    assert svc.list_habits() == [] and _count(svc, "habits") == 0


def test_clearing_an_occurrence_clears_the_rule_and_no_other_day(svc):
    """-1 on an occurrence passes through to the rule, as a task entry's clear
    passes through to its sidecar: days minted from now on start blank. A clear
    never reaches another day's number — that was copied, so it is that day's."""
    habit = svc.create_habit(title="Read", estimate_minutes=20)
    today = _habits_on(svc.open_day(DAY, create=True))[0]
    svc.open_day(NEXT, create=True)

    assert svc.patch_day_entry(
        DAY, today["entry_id"], estimate_minutes=-1)["estimate_minutes"] is None
    assert _rule(svc, habit["id"])["estimate_minutes"] is None
    assert _occ(svc, NEXT, habit["id"])["estimate_minutes"] == 20
    assert _habits_on(svc.open_day(NEXT2, create=True))[0]["estimate_minutes"] is None


def test_teach_habit_false_keeps_an_estimate_to_its_day(svc):
    """The switch the connector uses. The row takes the number; the rule and
    every other row are exactly as they were."""
    habit = svc.create_habit(title="Read")
    today = _habits_on(svc.open_day(DAY, create=True))[0]
    svc.open_day(NEXT, create=True)

    dto = svc.patch_day_entry(DAY, today["entry_id"], estimate_minutes=50, teach_habit=False)
    assert dto["estimate_minutes"] == 50
    assert _rule(svc, habit["id"])["estimate_minutes"] is None
    assert _occ(svc, NEXT, habit["id"])["estimate_minutes"] is None


def test_the_connector_estimates_an_occurrence_for_that_day_only(svc, monkeypatch):
    """A model may say how long today's "Read" will take; it may not decide how
    long "Read" takes. The rule is the owner's standing decision, and the
    connector reports those and never writes them — so neither the rule nor
    tomorrow's blank moves.

    The connector keeps its own clock (`McpApi._today`), which refuses a past
    estimate; it is pinned to the same DAY as the service so the two agree
    about which side of today this falls on.
    """
    api = McpApi(svc)
    monkeypatch.setattr(api, "_today", lambda: DAY)
    habit = svc.create_habit(title="Read")
    today = _habits_on(svc.open_day(DAY, create=True))[0]
    svc.open_day(NEXT, create=True)

    out = api.update_day_entry(today["entry_id"], estimate_minutes=30)
    assert out["estimate_minutes"] == 30 and out["day"] == DAY
    assert _rule(svc, habit["id"])["estimate_minutes"] is None
    assert _occ(svc, NEXT, habit["id"])["estimate_minutes"] is None


def test_the_rule_and_what_it_fills_land_together_or_not_at_all(svc, monkeypatch):
    """The connection is autocommit, so "one change" has to be a transaction on
    purpose. Without one, a failure between the statements leaves the rule
    saying 30 while the rows the same edit was meant to reach are still blank —
    or, on the occurrence path, the rule taught by a number the row it was typed
    on never took. The failure is injected at the LAST write of each path."""
    habit = svc.create_habit(title="Read")
    today = _habits_on(svc.open_day(DAY, create=True))[0]
    svc.open_day(NEXT, create=True)

    def boom(*_a, **_k):
        raise RuntimeError("database or disk is full")

    real_fill = store.fill_habit_estimates
    monkeypatch.setattr(store, "fill_habit_estimates", boom)
    with pytest.raises(RuntimeError):
        svc.update_habit(habit["id"], estimate_minutes=30)
    assert _rule(svc, habit["id"])["estimate_minutes"] is None
    monkeypatch.setattr(store, "fill_habit_estimates", real_fill)

    real_update = store.update_day_entry
    monkeypatch.setattr(store, "update_day_entry", boom)
    with pytest.raises(RuntimeError):
        svc.patch_day_entry(DAY, today["entry_id"], estimate_minutes=30)
    monkeypatch.setattr(store, "update_day_entry", real_update)
    assert _rule(svc, habit["id"])["estimate_minutes"] is None
    assert [_occ(svc, d, habit["id"])["estimate_minutes"] for d in (DAY, NEXT)] == [None, None]

    # And the connection is left usable: no transaction was stranded open.
    svc.patch_day_entry(DAY, today["entry_id"], estimate_minutes=30)
    assert _rule(svc, habit["id"])["estimate_minutes"] == 30
    assert _occ(svc, NEXT, habit["id"])["estimate_minutes"] == 30


# ── the guards ───────────────────────────────────────────────────────────────

def test_a_client_cannot_hand_mint_an_occurrence(svc):
    """An occurrence is minted BY A RULE, from the day key's own weekday.

    A client able to hand one in could fabricate an occurrence on a day the rule
    does not schedule — a habit that appears to have come round on a day it never
    did, indistinguishable afterwards from a real one. So `add_day_entry` refuses
    the kind outright (routes → 422).

    That refusal is the ONLY guard in the service, which this test now says
    instead of the opposite. It used to vouch for a second one: "`find_day_entry`
    has no habit arm behind it and would raise". It does not raise. The title arm
    filters on `kind='note'`, so a habit row is simply not matched and the lookup
    answers None — the second half below is that fact, asserted against a day
    that really is holding an occurrence. With the kind check gone, that None is
    what sends control on to `insert_day_entry`, and the forged row lands.
    """
    with pytest.raises(ValueError, match="kind must be task or note"):
        svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="habit", title="Stretch")
    assert _count(svc, "day_plan") == 0

    svc.create_habit(title="Stretch", days=FRI)
    assert _habits_on(svc.open_day(DAY, create=True))[0]["title"] == "Stretch"
    # The named fallback, run against exactly the row it was credited with
    # catching: None, not an exception, and so no guard at all.
    assert store.find_day_entry(svc._conn, DAY, title="Stretch") is None


def test_a_note_matching_a_habits_text_is_still_its_own_entry(svc):
    """The title arm of `find_day_entry` keeps its `kind='note'` filter.

    An occurrence copies the habit's title onto the row, so a title lookup that
    admitted every kind would answer an add-a-note request with the HABIT row —
    and the note would silently never be created, on the one screen where a note
    is the owner's own words.
    """
    svc.create_habit(title="Stretch", days=FRI)
    plan = svc.open_day(DAY, create=True)
    occ = _habits_on(plan)[0]
    note = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note", title="Stretch")
    assert note["entry_id"] != occ["entry_id"]
    assert (note["kind"], note["source"], note["habit_id"]) == ("note", "user", None)
    # The note is idempotent against ITSELF, still.
    again = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note", title="Stretch")
    assert again["entry_id"] == note["entry_id"]


def test_a_carried_entry_of_every_kind_round_trips(svc):
    """The carry branch is exhaustive, and this is what it costs when it is not.

    It used to read "note, and EVERYTHING ELSE IS A TASK". A row whose kind is
    neither — a habit occurrence hand-edited into source='user', a kind added by
    a later version, a partially restored backup — was laundered into
    {kind: "task", collection_href: None, uid: None}: a permanent blank row on
    today that nothing can join back to a task, that the owner cannot explain and
    cannot complete. Worse, it put (None, None) into the dedupe set, so the NEXT
    such row was silently swallowed — one corrupt row plus one disappearance,
    neither of which raises anything.

    The rows are written through the store directly because no route can produce
    them: `add_day_entry` refuses kind='habit', which is the OTHER guard. This
    one has to hold for a row that got there anyway.
    """
    for kind, title in (("habit", "Stretch"), ("habit", "Water the plants"),
                        ("sunrise", "A kind from the future")):
        store.insert_day_entry(
            svc._conn, day=PREV, entry_id=uuid.uuid4().hex, kind=kind,
            source="user", title=title, position=1.0, habit_id=None,
        )
    store.mark_day_opened(svc._conn, PREV)
    real = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="note",
                             title="Ring the bank")

    plan = svc.open_day(DAY, create=True)
    # Not one blank task row: every task entry names a task.
    assert not [e for e in plan["entries"]
                if e["kind"] == "task" and (e["uid"] is None or e["list"] is None)]
    # The odd kinds carried nothing at all — an occurrence belongs to its own day.
    assert not [e for e in plan["entries"] if e["kind"] in ("habit", "sunrise")]
    # …and the ordinary user note behind them still carried, which is what the
    # poisoned dedupe set used to eat.
    assert [e["title"] for e in plan["entries"] if e["source"] == "carried"] == [real["title"]]
    assert [e["kind"] for e in plan["entries"]] == ["task", "note"]


# ── the HTTP contract ────────────────────────────────────────────────────────
#
# The routes over the same service, through the real app. The `client` fixture is
# session-scoped and its database is shared with every other suite in the run, so
# these assert about the habits they create rather than about the whole list.

@pytest.mark.radicale
def test_routes_round_trip_a_habit(client):
    title = f"Stretch-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/habits", json={"title": title, "days": "fri,mon"})
    assert r.status_code == 201
    habit = r.json()
    assert habit["days"] == "mon,fri"           # order-normalised on the way in
    assert habit["paused_at"] is None and habit["created_at"]

    listed = {h["id"]: h for h in client.get("/api/habits").json()}
    assert listed[habit["id"]]["title"] == title

    r = client.patch(f"/api/habits/{habit['id']}", json={"paused": True, "days": ""})
    assert r.status_code == 200 and r.json()["paused_at"] and r.json()["days"] == ""
    assert client.patch(f"/api/habits/{habit['id']}", json={"paused": False}).json()["paused_at"] is None

    assert client.delete(f"/api/habits/{habit['id']}").status_code == 204
    assert client.delete(f"/api/habits/{habit['id']}").status_code == 404
    assert client.patch(f"/api/habits/{habit['id']}", json={"title": "x"}).status_code == 404


@pytest.mark.radicale
def test_routes_refuse_a_bad_habit(client):
    assert client.post("/api/habits", json={"title": ""}).status_code == 422
    r = client.post("/api/habits", json={"title": "x", "days": "FREQ=WEEKLY;BYDAY=MO"})
    assert r.status_code == 422
    assert "docs/recurrence-findings.md" in r.json()["detail"]
    assert client.post("/api/habits", json={"title": "x", "days": "mon,mon"}).status_code == 422
    made = client.post("/api/habits", json={"title": f"H-{uuid.uuid4().hex[:8]}"}).json()
    # An explicit null is refused rather than silently ignored: None is how the
    # service spells "not sent", so a null would be dropped and the caller told
    # its edit landed.
    assert client.patch(f"/api/habits/{made['id']}", json={"title": None}).status_code == 422
    client.delete(f"/api/habits/{made['id']}")


def _open_friday() -> date:
    """A Friday at least a week out, by the clock the app under `client` reads.

    These tests go through the real app, whose `_today` is not pinned, so the
    day they open has to be worked out from that same clock. A literal date is
    a test that passes until the calendar reaches it: once `_writable_floor`
    passes the day, nothing is minted on it and the assertion about the
    occurrence fails with no code having changed. A week of margin puts the day
    beyond any timezone or grace-day edge.
    """
    d = date.today() + timedelta(days=7)
    return d + timedelta(days=(4 - d.weekday()) % 7)


@pytest.mark.radicale
def test_an_occurrence_reaches_the_day_over_http(client):
    """End to end: a habit created through the API shows up on the day the API
    opens, with `habit_id` on the entry and `done` accepted on it — an
    occurrence's doneness lives nowhere but in the day, exactly like a note's."""
    day = _open_friday().isoformat()
    title = f"Stretch-{uuid.uuid4().hex[:8]}"
    habit = client.post("/api/habits", json={"title": title, "days": "fri"}).json()
    try:
        entries = client.post(f"/api/day/{day}/open").json()["entries"]
        mine = [e for e in entries if e["habit_id"] == habit["id"]]
        assert len(mine) == 1
        assert (mine[0]["kind"], mine[0]["source"], mine[0]["title"]) == ("habit", "habit", title)
        r = client.patch(f"/api/day/{day}/entries/{mine[0]['entry_id']}", json={"done": True})
        assert r.status_code == 200 and r.json()["done_at"]
    finally:
        client.delete(f"/api/habits/{habit['id']}")


@pytest.mark.radicale
def test_an_occurrence_estimate_reaches_the_habit_over_http(client):
    """The Today row's estimate control PATCHes the ENTRY, and nothing else. The
    habit behind it has to learn the number through that same route, or the
    ritual asks again on the next day the rule runs — which is the bug this
    closes, seen from the wire."""
    day = (date.today() + timedelta(days=7)).isoformat()   # a day not yet run
    title = f"Read-{uuid.uuid4().hex[:8]}"
    habit = client.post("/api/habits", json={"title": title}).json()   # every day
    try:
        entries = client.post(f"/api/day/{day}/open").json()["entries"]
        mine = [e for e in entries if e["habit_id"] == habit["id"]]
        assert len(mine) == 1 and mine[0]["estimate_minutes"] is None
        r = client.patch(f"/api/day/{day}/entries/{mine[0]['entry_id']}",
                         json={"estimate_minutes": 25})
        assert r.status_code == 200 and r.json()["estimate_minutes"] == 25
        listed = {h["id"]: h for h in client.get("/api/habits").json()}
        assert listed[habit["id"]]["estimate_minutes"] == 25
    finally:
        client.delete(f"/api/habits/{habit['id']}")
