"""The day plan: the sidecar tables, the service that builds a day's snapshot,
and the HTTP contract over them.

Almost everything here runs with NO Radicale. A day plan is app-only state — it
exists nowhere on the wire — so the service reads the cache and writes SQLite,
and seeding `items` directly (the same trick test_service_unit.py uses for the
booking surface) exercises the real code with none of the round trips. The few
tests that drive the routes are marked `radicale` and use the shared `client`.

The properties pinned here are the ones that make the day log trustworthy: a
read never writes, a snapshot happens exactly once — even on a day the owner
wrote to first — a dropped entry is kept rather than deleted, an entry outlives
the task it names, and the day a DUE is filed under is the owner's own.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, timedelta

import pytest
from helpers import foreign_raw

from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import extract_from_raw
from tasksd.mcp.api import McpApi
from tasksd.mcp.tools import ToolError
from tasksd.service import TaskService

# A Friday, with the days either side of it. Fixed rather than derived from
# `date.today()`: a snapshot is a function of the day it is built for, and a
# suite whose expectations move at midnight is a suite that fails at midnight.
DAY = "2026-08-21"
PREV = "2026-08-20"
NEXT = "2026-08-22"
# Months before DAY, with nothing in the fixture due on or before it — so a
# snapshot of it is legitimately empty, which is the case the marker table
# exists for.
QUIET_DAY = "2026-01-05"

LIST_A, LIST_B = "/u/work/", "/u/home/"


def _settings() -> Settings:
    # The DAV URL points at a closed port on purpose: nothing in this suite may
    # reach the wire, and a test that starts trying will fail rather than hang.
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


def _seed_task(
    conn, href: str, uid: str, summary: str, *,
    due: str | None = None, due_utc: str | None = None,
    status: str = "NEEDS-ACTION", parent: str | None = None,
    completed_at: str | None = None,
) -> None:
    """Cache one VTODO as a foreign client would have written it.

    `due` is a DATE — "due Tuesday", a calendar day with no instant in it, and
    what this app's own picker writes. `due_utc` is the other shape a foreign
    client sends: an INSTANT, whose calendar day depends on who is looking.
    """
    extra: list[str] = []
    if due is not None:
        extra.append(f"DUE;VALUE=DATE:{due.replace('-', '')}")
    if due_utc is not None:
        extra.append(f"DUE:{due_utc}")
    if parent is not None:
        extra.append(f"RELATED-TO:{parent}")
    if completed_at is not None:
        # The property `_completions_by_day` actually reads. STATUS alone says a
        # task is finished; only COMPLETED says WHEN, and a day can only own a
        # completion it has a stamp for.
        extra.append(f"COMPLETED:{completed_at}")
    raw = foreign_raw(uid, summary, extra=tuple(extra))
    # foreign_raw hardcodes NEEDS-ACTION; swapping the whole line keeps one
    # STATUS property on the resource (two would be ambiguous to the parser).
    raw = raw.replace(b"STATUS:NEEDS-ACTION", f"STATUS:{status}".encode())
    store.upsert_item(conn, href, Item(f"{href}{uid}.ics", '"1"', raw), extract_from_raw(raw))


@pytest.fixture
def svc():
    s = TaskService(_settings())
    for href, name in ((LIST_A, "Work"), (LIST_B, "Home")):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components={"VTODO"})
        )
    # The cast every test draws from: one task due on DAY, one already late, one
    # due later, one finished, one subtask of the due-today task, and one with no
    # due date at all. Only the first two belong in a snapshot of DAY.
    _seed_task(s._conn, LIST_A, "due-today", "Ship the thing", due=DAY)
    _seed_task(s._conn, LIST_B, "late", "Call the plumber", due="2026-08-19")
    _seed_task(s._conn, LIST_A, "later", "Next week's problem", due="2026-08-28")
    _seed_task(s._conn, LIST_A, "done", "Already handled", due=DAY, status="COMPLETED")
    _seed_task(s._conn, LIST_A, "sub", "A checklist line", due=DAY, parent="due-today")
    _seed_task(s._conn, LIST_B, "someday", "Learn the harmonica")
    yield s
    s.close()


def _count(svc_, table: str) -> int:
    # The table names are literals in this file, never input.
    return svc_._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608


def _uids(plan: dict) -> list[str]:
    return [e["uid"] for e in plan["entries"] if e["kind"] == "task"]


# ── the read/write split ─────────────────────────────────────────────────────

def test_reading_a_never_opened_day_writes_nothing(svc):
    """`create=False` is the guard that keeps the log honest.

    GET is how the app looks at days it is not visiting — a prefetched week, a
    range read landing on an empty day — so a read that quietly opened them
    would record plans the owner never made and freeze each day's snapshot at
    whatever happened to be due when the prefetch ran. All three tables must be
    untouched afterwards, and the day must report itself unplanned even though
    there IS work that would qualify for a snapshot.

    Spelled as a whole-dict equality rather than a handful of key checks, and
    kept that way deliberately: it is what makes a field ADDED to the plan shape
    show up here, where its default on an untouched day gets looked at once."""
    plan = svc.open_day(DAY, create=False)
    assert plan == {
        "day": DAY, "planned": False, "entries": [],
        # Nothing said about this day, and — the one that matters — no capacity
        # invented for it. `capacity` is None rather than some assumed working
        # day, because an account that never stated one must not be told it has
        # overcommitted against a number it never gave.
        "capacity_minutes": None, "capacity": None,
        "committed_at": None, "shutdown_at": None, "reflection": None,
    }
    assert _count(svc, "day_plan") == 0
    assert _count(svc, "day_plan_opened") == 0
    # `day_ritual` is written lazily on the first statement about a day, and
    # reading one is not a statement — reporting its nulls must not mint the row
    # that holds them.
    assert _count(svc, "day_ritual") == 0
    # And again — a read is a read however many times it is repeated.
    assert svc.open_day(DAY, create=False)["planned"] is False
    assert _count(svc, "day_plan_opened") == 0
    assert _count(svc, "day_ritual") == 0


def test_opening_a_day_twice_does_not_duplicate_it(svc):
    """The snapshot happens exactly once. Opening a day is what the client does
    every time the Today tab is shown, so a second open that re-snapshotted
    would double every row on the second visit — and re-add work the owner had
    already dropped."""
    first = svc.open_day(DAY, create=True)
    assert first["planned"] is True and first["entries"]
    written = _count(svc, "day_plan")

    second = svc.open_day(DAY, create=True)
    assert [e["entry_id"] for e in second["entries"]] == [
        e["entry_id"] for e in first["entries"]
    ]
    assert _count(svc, "day_plan") == written


def test_an_opened_day_with_no_entries_is_still_planned(svc):
    """Why day_plan_opened exists at all.

    day_plan alone answers "never opened" and "opened, and it turned out there
    was nothing to do" with the same zero rows. Only the marker separates them,
    and the difference is load-bearing: without it this day would be
    re-snapshotted on every visit, which is also how a day the owner
    deliberately emptied would refill itself."""
    plan = svc.open_day(QUIET_DAY, create=True)
    assert plan["entries"] == []
    assert plan["planned"] is True
    assert _count(svc, "day_plan") == 0
    # The plain read agrees — the marker survives the round trip to SQLite.
    assert svc.open_day(QUIET_DAY, create=False)["planned"] is True


# ── what the snapshot picks up ───────────────────────────────────────────────

def test_snapshot_takes_due_today_as_auto(svc):
    """The one automatic rule, and the five exclusions that go with it.

    Due-today is what the day is *about*; everything else has to stay out, or
    the Today tab becomes a second copy of the task list. A completed task is
    not work, a subtask rides with its parent (one parent would otherwise drag
    its whole checklist in), a task due next week belongs to next week, undated
    work is something the owner picks rather than something a snapshot decides
    for them — and what is ALREADY LATE is offered rather than placed, which is
    the exclusion the test below states on its own."""
    plan = svc.open_day(DAY, create=True)
    assert _uids(plan) == ["due-today"]
    assert {e["source"] for e in plan["entries"]} == {"auto"}
    assert all(e["kind"] == "task" for e in plan["entries"])
    # The list SHORT id, never the href — the client only ever holds short ids.
    assert [e["list"] for e in plan["entries"]] == ["work"]
    # A dense ascending sequence: every row of the snapshot gets a position, so
    # the day's order never rests on a tie-break.
    assert [e["position"] for e in plan["entries"]] == [1.0]
    assert all(e["done_at"] is None and e["dropped_at"] is None for e in plan["entries"])


def test_what_is_already_late_is_not_snapshotted_onto_the_day(svc):
    """A missed deadline is a decision the owner has not made yet.

    Putting it back on every morning makes that decision for them — badly, by
    deferring it another day at the cost of a row they read and skip. So the
    snapshot leaves it alone and the app OFFERS it instead (the SPA's suggestion
    strip is built over exactly the tasks the day does not already hold), which
    is what makes choosing it an act rather than a default.

    `late` is due 2026-08-19, two days before DAY, and is open. Under the old
    rule it was the second row of every snapshot in this file."""
    plan = svc.open_day(DAY, create=True)
    assert "late" not in _uids(plan)
    # Still open, still late, still on its list: nothing was hidden or written.
    assert svc.get_task(LIST_B, "late")["completed"] is False
    # And a re-open does not quietly bring it back — there is no second rule
    # waiting behind the first.
    assert "late" not in _uids(svc.open_day(DAY, create=True))


def test_parked_work_is_not_derived_onto_a_day(svc):
    """Parking is an explicit act, and a day that derived the work anyway would
    be putting back exactly what the owner took out — the morning after they
    took it out, every morning.

    Worse than the overdue case it sits beside, in fact: a deadline slipping is
    something that happened TO them, and this is something they did."""
    svc.park_task(LIST_A, "due-today", parked=True)
    assert _uids(svc.open_day(DAY, create=True)) == []
    # The preview says the same thing, since both run `_snapshot_for`: a
    # connector must not describe a day differently from the app.
    assert svc.preview_day(NEXT) == []

    # And un-parking brings it back to the derivation — on a day that has not
    # been snapshotted yet, since the marker is what makes an open happen once.
    svc.park_task(LIST_A, "due-today", parked=False)
    _seed_task(svc._conn, LIST_A, "due-next", "Ship the other thing", due=NEXT)
    assert "due-next" in _uids(svc.open_day(NEXT, create=True))


def test_parked_work_does_not_carry_into_the_next_day(svc):
    """The other half, and the one the snapshot rule cannot cover.

    A task the owner CHOSE on Monday carries into Tuesday by design — that is
    the safety net for a decision they made and did not finish. Parking it on
    Monday evening is them withdrawing that decision, so the net has to let go;
    otherwise setting something aside would be undone a day after they did it,
    which is the one thing parking has to be proof against.

    Reversible, unlike done and dropped: un-park it and the ordinary rules
    apply again."""
    picked = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="task",
                               list_id="work", uid="later")
    assert picked["source"] == "user"
    svc.park_task(LIST_A, "later", parked=True)

    plan = svc.open_day(DAY, create=True)
    assert "later" not in _uids(plan)
    # The row on PREV is untouched — that day still records what was planned on
    # it, exactly as it does for a task completed or deleted afterwards.
    assert "later" in _uids(svc.open_day(PREV, create=False))


def test_a_preview_of_a_day_leaves_out_what_is_late_too(svc):
    """The preview stands in for a FIRST OPEN, so it has to derive what that open
    would derive and nothing else.

    `preview_day` runs the same `_snapshot_for` and throws it away, so this holds
    by construction — but the connector is the caller, it is the one caller with
    no person watching it, and a preview that named a task no open would add is
    exactly the kind of drift that is invisible until someone acts on it."""
    preview = svc.preview_day(DAY)
    assert [p["uid"] for p in preview if p["kind"] == "task"] == ["due-today"]


def test_a_preview_entry_has_the_same_shape_as_a_real_one(svc):
    """`preview_day` builds its dicts BY HAND — a second, independent spelling of
    `_day_entry_dto` — and its own docstring promises the caller one entry shape
    to handle rather than two. Nothing enforces that promise but this test.

    A field added to one and forgotten in the other makes a preview entry and a
    real entry differ in exactly the way the docstring says they do not, and the
    caller reading the missing key is the MCP connector: the one caller with no
    person watching it, answering "what is on today" for a day nobody has opened.
    """
    preview = svc.preview_day(DAY)
    assert preview
    plan = svc.open_day(DAY, create=True)
    for p, e in zip(preview, plan["entries"], strict=True):
        # Same keys, exactly — this is the assertion that catches the omission.
        assert set(p) == set(e)
        # Same derivation, so they agree about everything a preview can know.
        assert [p[k] for k in ("kind", "list", "uid", "title", "source", "habit_id")] == \
               [e[k] for k in ("kind", "list", "uid", "title", "source", "habit_id")]
        # …and the row-only columns are null, because none of these is a row.
        assert (p["position"], p["done_at"], p["dropped_at"], p["created_at"]) == (None,) * 4


def test_an_ordinary_entry_has_a_null_habit_id(svc):
    """A task entry and a note entry name no habit, so the column is NULL — and
    it is PRESENT, which is the half that matters. `habit_id` is only ever set by
    the rule that mints an occurrence (see test_habits.py)."""
    plan = svc.open_day(DAY, create=True)
    note = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note",
                             title="Ring the bank")
    assert all(e["habit_id"] is None for e in plan["entries"])
    assert note["habit_id"] is None
    assert {e["kind"] for e in svc.open_day(DAY, create=False)["entries"]} == {"task", "note"}


# ── which day a DUE is filed under ───────────────────────────────────────────

def test_a_zoned_due_is_filed_under_the_owners_day(svc):
    """The snapshot has to agree with the screen about what "due today" means.

    `dayKey` (frontend/src/util.ts) hands a due value to `Date` and reads LOCAL
    components back, so `DUE:20260822T000000Z` — which the cache holds as
    `2026-08-22T00:00:00+00:00` — is 20:00 on the 21st for an owner in New York,
    and the Today tab lists it as due today. Taking the cached string's first
    ten characters answered the 22nd instead, so the day's snapshot omitted the
    very task the same screen was showing as due that day.
    """
    _seed_task(svc._conn, LIST_A, "overnight", "Filed at midnight UTC",
               due_utc="20260822T000000Z")
    # A DATE-valued task on the day that instant only LOOKS like it belongs to.
    # This one must not move: it names a calendar day with no instant in it, so
    # resolving it in a zone would drag "due Saturday" back onto Friday for
    # every owner west of UTC. `items.due_is_date` is what tells the two apart —
    # not the shape of the string.
    _seed_task(svc._conn, LIST_A, "saturday", "Saturday's job", due=NEXT)
    svc.update_settings({"home_timezone": "America/New_York"})

    got = _uids(svc.open_day(DAY, create=True))
    assert "overnight" in got, (
        f"a DUE that is 20:00 on {DAY} in the owner's zone was filed under the "
        f"day its UTC spelling names: {got}"
    )
    assert "saturday" not in got, (
        f"a DATE-valued DUE was converted as though it named an instant: {got}"
    )


def test_a_zoned_due_falls_back_to_the_servers_zone(svc, monkeypatch):
    """With no `home_timezone` — the state every deployment starts in — the day
    is taken in this process's own zone, which is the nearest thing the server
    has to the browser's.

    The zone is pinned rather than assumed: CI and the ordinary Docker image
    both run in UTC, where the instant below is already the 22nd and the whole
    disagreement is invisible.
    """
    _seed_task(svc._conn, LIST_A, "overnight", "Filed at midnight UTC",
               due_utc="20260822T000000Z")
    assert not svc.get_settings().get("home_timezone")

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        got = _uids(svc.open_day(DAY, create=True))
    finally:
        # Put the process's zone back before the next test runs: monkeypatch
        # restores the VARIABLE but cannot make libc re-read it, so without this
        # the zone would follow every later test in the session.
        monkeypatch.undo()
        time.tzset()
    assert "overnight" in got, (
        f"with no home_timezone the day was not taken in the server's own "
        f"zone: {got}"
    )


def test_unfinished_user_entries_carry_into_the_next_day(svc):
    """Yesterday's deliberate choices follow the owner; yesterday's automatic
    ones do not. A hand-added entry has no second source — drop it and the
    decision is simply lost — while an auto entry is a proposal the DAY made,
    and carrying one would be the day proposing the same thing twice without
    being asked."""
    # Due on PREV, so PREV's own snapshot derives it. There is no such task in
    # the fixture on purpose: the fixture's `late` is due before PREV, and since
    # the snapshot stopped deriving overdue work it lands on no day at all.
    _seed_task(svc._conn, LIST_B, "due-prev", "Call the plumber", due=PREV)
    svc.open_day(PREV, create=True)
    assert _uids(svc.open_day(PREV, create=False)) == ["due-prev"]   # auto, from DUE
    note = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="note",
                             title="Ring the bank")
    picked = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="task",
                               list_id="work", uid="later")

    plan = svc.open_day(DAY, create=True)
    carried = [e for e in plan["entries"] if e["source"] == "carried"]
    assert [e["title"] for e in carried if e["kind"] == "note"] == ["Ring the bank"]
    assert [e["uid"] for e in carried if e["kind"] == "task"] == ["later"]
    # Fresh entry_ids: the entry belongs to ITS day, and reusing the id would
    # make one row that two days both claim (the primary key is (day, entry_id),
    # so the copy would collide the moment both days were written).
    assert {e["entry_id"] for e in carried}.isdisjoint({note["entry_id"], picked["entry_id"]})


def test_an_unactioned_auto_row_neither_carries_nor_re_derives(svc):
    """The one consequence of narrowing the derivation that is worth stating in
    a test rather than a comment.

    A task due yesterday that the day proposed and the owner left alone is
    overdue today. It does not carry (it was never chosen) and it is not derived
    (it is not due today), so it is on NO day — the suggestion strip offers it,
    and the owner decides. Under the old rule the snapshot picked it up again
    every morning for as long as it stayed undone, which is the eleven-day
    attention cost this change exists to remove.

    The task is untouched by any of that: still open, still late, still on its
    list. Nothing here deletes or hides work."""
    _seed_task(svc._conn, LIST_B, "due-prev", "Call the plumber", due=PREV)
    assert _uids(svc.open_day(PREV, create=True)) == ["due-prev"]

    plan = svc.open_day(DAY, create=True)
    assert "due-prev" not in _uids(plan)
    assert svc.get_task(LIST_B, "due-prev")["completed"] is False


def test_a_dropped_entry_is_kept_and_does_not_carry(svc):
    """Dropping means "I decided not to", which is the most useful thing a past
    day can tell you — so the row is stamped, never deleted. It is also the
    other half of what dropping means: the entry must not come back tomorrow,
    or dropping would be a gesture with no effect past midnight."""
    svc.open_day(PREV, create=True)
    entry = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="task",
                              list_id="work", uid="later")
    dropped = svc.patch_day_entry(PREV, entry["entry_id"], dropped=True)
    assert dropped["dropped_at"]

    kept = svc.open_day(PREV, create=False)["entries"]
    assert [e["entry_id"] for e in kept].count(entry["entry_id"]) == 1
    # This one row and nothing else: PREV has no task due on it, and nothing
    # overdue is derived any more, so the snapshot added none of its own.
    assert _count(svc, "day_plan") == 1

    plan = svc.open_day(DAY, create=True)
    assert not [e for e in plan["entries"] if e["source"] == "carried"]
    assert "later" not in _uids(plan)


# ── the first write is not always the open ───────────────────────────────────

def test_a_hand_added_day_still_gets_its_snapshot(svc):
    """A day whose FIRST write is an add is snapshotted all the same.

    `add_day_entry` used to mark the day opened, and `open_day` skipped the
    snapshot for any day that already held entries — so a single hand-added row
    suppressed that day's due-today and carried entries permanently.
    The shipped client makes that an ordinary sequence rather than an exotic
    one: TodayView renders the add box whether or not the open call succeeded,
    so one failed request lost the day's automatic rows for good.
    """
    note = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note",
                             title="Ring the bank")
    # Planned already — the entry says so, with no marker to say it. The two
    # facts are different: "the owner put something here" is not "the automatic
    # snapshot has been built", and only the second one is the marker's.
    assert svc.open_day(DAY, create=False)["planned"] is True
    assert _count(svc, "day_plan_opened") == 0

    plan = svc.open_day(DAY, create=True)
    assert _uids(plan) == ["due-today"]
    assert [e["source"] for e in plan["entries"]] == ["user", "auto"]
    # The hand-added row keeps its place and its id: a snapshot arriving late
    # lands BEHIND the arrangement it is joining rather than renumbering it.
    assert plan["entries"][0]["entry_id"] == note["entry_id"]
    assert [e["position"] for e in plan["entries"]] == [1.0, 2.0]
    # And exactly once: from here the marker is what answers, so the second open
    # is a read like any other.
    assert svc.open_day(DAY, create=True)["entries"] == plan["entries"]


def test_the_snapshot_does_not_duplicate_what_the_day_already_holds(svc):
    """The merge dedupes on (collection_href, uid) — the identity of a task
    everywhere in this app — against the rows the day ALREADY has.

    Without that, a task the owner put on a fresh day by hand would get a second
    row the moment the snapshot ran, and two rows for one task means two
    checkboxes that disagree about whether it is done.
    """
    picked = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="task",
                               list_id="work", uid="due-today")
    plan = svc.open_day(DAY, create=True)
    assert _uids(plan) == ["due-today"]
    # The OWNER's row is the one that survives — same entry_id the client is
    # already holding, still source=user, so it still carries into tomorrow.
    kept = [e for e in plan["entries"] if e["uid"] == "due-today"][0]
    assert (kept["entry_id"], kept["source"]) == (picked["entry_id"], "user")

    # A DROPPED row counts as present too. Re-proposing something the owner
    # dropped minutes earlier is exactly the resurrection the opened marker
    # exists to prevent — the row being dropped is not an invitation to add it
    # back, it is the decision not to. Seeded due ON PREV, because the dedupe
    # can only be shown against a row the snapshot would otherwise derive, and
    # since overdue stopped deriving that means a deadline on the day itself.
    _seed_task(svc._conn, LIST_B, "due-prev", "Call the plumber", due=PREV)
    gone = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="task",
                             list_id="home", uid="due-prev")
    svc.patch_day_entry(PREV, gone["entry_id"], dropped=True)
    prev = svc.open_day(PREV, create=True)
    assert _uids(prev) == ["due-prev"]
    assert prev["entries"][0]["dropped_at"]


# ── adding by hand ───────────────────────────────────────────────────────────

def test_adding_the_same_task_twice_yields_one_entry(svc):
    """Idempotent on the TASK, not just on the entry_id: a double-tap, a retried
    POST and a second drag of the same task all reach here, and two rows for one
    task means two checkboxes that disagree about whether it is done."""
    svc.open_day(DAY, create=True)
    before = _count(svc, "day_plan")
    first = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="task",
                              list_id="work", uid="later")
    # A DIFFERENT entry_id, so only the (list, uid) match can catch this one.
    again = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="task",
                              list_id="work", uid="later")
    assert again["entry_id"] == first["entry_id"]
    assert _count(svc, "day_plan") == before + 1
    # A task already on the day as an AUTO entry is the same task: adding it by
    # hand returns that row rather than shadowing it with a user copy.
    auto = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="task",
                             list_id="work", uid="due-today")
    assert auto["source"] == "auto"
    assert _count(svc, "day_plan") == before + 1


def test_reusing_an_entry_id_for_a_different_entry_is_refused(svc):
    """The replayed POST is answered from the row that landed; a DIFFERENT entry
    under the same id is refused rather than silently answered with the other
    one. Inserting is not an option either — (day, entry_id) is the primary key,
    so it would be an IntegrityError no handler maps."""
    svc.open_day(DAY, create=True)
    entry_id = uuid.uuid4().hex
    first = svc.add_day_entry(DAY, entry_id=entry_id, kind="note", title="Ring the bank")
    # The same note again: a replay, answered from the same row.
    assert svc.add_day_entry(DAY, entry_id=entry_id, kind="note",
                             title="Ring the bank")["entry_id"] == first["entry_id"]
    with pytest.raises(ValueError):
        svc.add_day_entry(DAY, entry_id=entry_id, kind="note", title="Something else")
    with pytest.raises(ValueError):
        svc.add_day_entry(DAY, entry_id=entry_id, kind="task", list_id="work", uid="later")


def test_a_task_entry_needs_a_list_that_resolves(svc):
    """An unresolvable list id would be stored as a collection_href nothing can
    join back to, and the entry would render forever as a task that cannot be
    opened, completed or removed."""
    with pytest.raises(ValueError):
        svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="task",
                          list_id="no-such-list", uid="later")
    assert _count(svc, "day_plan") == 0


def test_a_malformed_day_key_is_refused(svc):
    """One spelling of a day, everywhere. `date.fromisoformat` alone is not the
    check: since 3.11 it also accepts the basic format and ISO week dates, so
    "20260821" and "2026-W34-1" both name a real day — and would give the same
    calendar day a second primary key, under which the opened marker reads as
    absent and the day is silently re-snapshotted."""
    for bad in ("20260821", "2026-W34-1", "2026-02-30", "2026-8-1", "tomorrow", ""):
        with pytest.raises(ValueError):
            svc.open_day(bad, create=True)
        with pytest.raises(ValueError):
            svc.add_day_entry(bad, entry_id="e1", kind="note", title="x")
        with pytest.raises(ValueError):
            svc.patch_day_entry(bad, "e1", done=True)
        with pytest.raises(ValueError):
            svc.day_range(bad, DAY)
    assert _count(svc, "day_plan") == 0
    assert _count(svc, "day_plan_opened") == 0


def test_patching_an_unknown_entry_reports_it(svc):
    # None rather than a raise or a silent no-op: the route needs to tell a 404
    # from a successful patch, and a client retrying against a day it has since
    # left is an ordinary race, not an error worth logging.
    svc.open_day(DAY, create=True)
    assert svc.patch_day_entry(DAY, "not-an-entry", done=True) is None


def test_done_can_be_undone(svc):
    """False is a real value here, not "unset". The tick is a stamp, so undoing
    it has to clear the column — a client that could only ever set it would give
    the owner a checkbox they cannot uncheck.

    Driven through a NOTE. This used to tick the first entry of the snapshot,
    which is a TASK — and `done` no longer applies to one (see the test below):
    a task's doneness is its VTODO STATUS, so the day plan keeps no second
    answer. A note is the only entry that has a `done_at` of its own.
    """
    svc.open_day(DAY, create=True)
    note = svc.add_day_entry(DAY, entry_id=uuid.uuid4().hex, kind="note",
                             title="Ring the bank")
    entry_id, position = note["entry_id"], note["position"]
    assert svc.patch_day_entry(DAY, entry_id, done=True)["done_at"]
    assert svc.patch_day_entry(DAY, entry_id, done=False)["done_at"] is None
    # An untouched field stays untouched: position survives a done/undone pass.
    assert [e["position"] for e in svc.open_day(DAY, create=False)["entries"]
            if e["entry_id"] == entry_id] == [position]
    # Re-sending a state the entry is already in is a 200, not a 404. A retry
    # does exactly this, and the "unknown entry" answer keys off SQLite's
    # rowcount — which counts rows the UPDATE processed, not rows whose values
    # changed, so a no-op patch must still find its row.
    assert svc.patch_day_entry(DAY, entry_id, done=False) is not None
    assert svc.patch_day_entry(DAY, entry_id, position=position)["position"] == position


def test_done_does_not_apply_to_a_task_entry(svc):
    """One answer to "is this task done", and it is the VTODO's.

    STATUS is what the Tasks pane, a phone and Thunderbird all read and write. A
    `done_at` on a task entry would be a second answer that no other client can
    see, and the two disagree the moment the task is ticked anywhere else — so
    it is refused (routes → 422) rather than written. `dropped` and `position`
    still apply to every entry: those are facts about the DAY, not about the
    task.
    """
    plan = svc.open_day(DAY, create=True)
    entry = plan["entries"][0]
    assert entry["kind"] == "task"
    with pytest.raises(ValueError):
        svc.patch_day_entry(DAY, entry["entry_id"], done=True)
    # Refused whole, not half-applied.
    assert svc.open_day(DAY, create=False)["entries"][0]["done_at"] is None
    assert svc.patch_day_entry(DAY, entry["entry_id"], dropped=True)["dropped_at"]
    # An unknown entry is still the 404 answer, not this ValueError: there is no
    # entry to have a kind.
    assert svc.patch_day_entry(DAY, "not-an-entry", done=True) is None


# ── the no-FK guarantee ──────────────────────────────────────────────────────

def test_an_entry_survives_its_task_leaving_the_wire(svc):
    """day_plan has no foreign key to items, deliberately.

    A task gets completed and deleted, moved between lists by a phone client, or
    delete-and-recreated by a sync — and none of that changes what the owner
    planned that morning. With a FK (or a cascading cleanup) the day's record
    would quietly rewrite itself every time the wire moved, which is the one
    thing a log must not do."""
    svc.open_day(DAY, create=True)
    # The real removal path: this is what the sync engine calls when a resource
    # is gone from the collection.
    assert store.delete_item_by_href(svc._conn, LIST_A, f"{LIST_A}due-today.ics") == "due-today"
    assert store.get_item(svc._conn, LIST_A, "due-today") is None

    plan = svc.open_day(DAY, create=False)
    assert "due-today" in _uids(plan)
    entry = [e for e in plan["entries"] if e["uid"] == "due-today"][0]
    assert entry["list"] == "work"          # still says where it lived
    # And it is still editable: the day's own rows do not depend on the cache.
    # Dropped rather than ticked — `done` is a note's field, and this entry
    # names a task, whose doneness was its VTODO's right up until it vanished.
    assert svc.patch_day_entry(DAY, entry["entry_id"], dropped=True)["dropped_at"]


# ── upgrading a database written before habits ───────────────────────────────

# ── rolling work forward ─────────────────────────────────────────────────────
#
# The deliberate half of "unfinished work does not vanish". The automatic carry
# is the other half and stays exactly as it was — these tests are as much about
# the two not colliding as about the move itself.


def test_rolling_creates_on_the_target_and_stamps_the_source(svc):
    """MOVES NOTHING. The day that planned the work is still the day that
    planned it, so the row stays where it is and only records where it went."""
    today = _today()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(today, create=True)
    src = svc.add_day_entry(today, entry_id="n1", kind="note", title="Finish the draft")

    moved = svc.roll_entry(today, src["entry_id"], tomorrow)
    assert moved["rolled_to"] == tomorrow
    # Still on its own day, and NOT dropped: those are different answers.
    assert moved["dropped_at"] is None
    assert "n1" in [e["entry_id"] for e in svc.open_day(today, create=False)["entries"]]
    # And present on the target, which was never opened by this.
    landed = svc.open_day(tomorrow, create=False)
    assert [e["title"] for e in landed["entries"]] == ["Finish the draft"]
    # `create=False` throughout, so nothing above has built tomorrow a snapshot
    # — the only row on it is the one that was moved there.


def test_rolling_does_not_open_the_target_day(svc):
    """The rule the whole day plan is built around. Opening a day is the only
    call that derives a snapshot, and a roll must leave the target free to do
    that for itself when the owner actually arrives."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(_today(), create=True)
    src = svc.add_day_entry(_today(), entry_id="n1", kind="note", title="Later")
    svc.roll_entry(_today(), src["entry_id"], tomorrow)

    assert not store.day_is_opened(svc._conn, tomorrow)
    # It reports planned — it holds a row — but its snapshot has not been built,
    # so arriving tomorrow still derives due-today, overdue and the carry.
    assert svc.open_day(tomorrow, create=False)["planned"] is True


def test_rolling_the_same_row_twice_lands_once(svc):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(_today(), create=True)
    src = svc.add_day_entry(_today(), entry_id="n1", kind="note", title="Once")
    svc.roll_entry(_today(), src["entry_id"], tomorrow)
    svc.roll_entry(_today(), src["entry_id"], tomorrow)
    assert len(svc.open_day(tomorrow, create=False)["entries"]) == 1


def test_a_rolled_row_is_not_also_carried(svc):
    """THE COLLISION THIS FEATURE COULD HAVE CAUSED. A row the owner moved to
    Thursday has been decided about; without `rolled_to` in `_carry_into`'s
    filter the automatic safety net would ALSO pull it into tomorrow, and they
    would find two of it — one from their decision and one from the rule that
    exists for when they make none."""
    today = _today()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    later = (date.today() + timedelta(days=3)).isoformat()
    svc.open_day(today, create=True)
    src = svc.add_day_entry(today, entry_id="n1", kind="note", title="Thursday's job")
    svc.roll_entry(today, src["entry_id"], later)

    titles = [e["title"] for e in svc.open_day(tomorrow, create=True)["entries"]]
    assert "Thursday's job" not in titles


def test_an_unrolled_row_still_carries(svc):
    # The other side of the same line: the safety net is untouched for anything
    # the ritual did not decide about.
    today = _today()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(today, create=True)
    svc.add_day_entry(today, entry_id="n1", kind="note", title="Nobody decided")

    titles = [e["title"] for e in svc.open_day(tomorrow, create=True)["entries"]]
    assert "Nobody decided" in titles


def test_work_can_only_be_moved_forward(svc):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    svc.open_day(_today(), create=True)
    src = svc.add_day_entry(_today(), entry_id="n1", kind="note", title="Back in time")
    with pytest.raises(ValueError):
        svc.roll_entry(_today(), src["entry_id"], yesterday)
    # And not to the day it is already on.
    with pytest.raises(ValueError):
        svc.roll_entry(_today(), src["entry_id"], _today())


def test_leftovers_can_be_rolled_out_of_a_past_day(svc):
    """Allowed, and needed. It manufactures no record of the past day — the new
    row lands on a day that has not happened — and the planning ritual's
    leftovers step depends on exactly this when a shutdown was skipped."""
    svc.open_day(PREV, create=True)
    src = svc.add_day_entry(PREV, entry_id="n1", kind="note", title="Missed it")
    moved = svc.roll_entry(PREV, src["entry_id"], _today())
    assert moved["rolled_to"] == _today()
    assert [e["title"] for e in svc.open_day(_today(), create=False)["entries"]] \
        == ["Missed it"]


def test_a_habit_occurrence_cannot_be_moved(svc):
    """Tomorrow gets its own from the rule, so moving one would either duplicate
    it or fabricate an occurrence on a day the rule does not schedule — the
    forgery `add_day_entry`'s kind check is the last line against."""
    today = _today()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.create_habit(title="Read")
    occ = next(e for e in svc.open_day(today, create=True)["entries"]
               if e["kind"] == "habit")
    with pytest.raises(ValueError):
        svc.roll_entry(today, occ["entry_id"], tomorrow)


def test_rolling_an_unknown_entry_is_a_miss_not_an_error(svc):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(_today(), create=True)
    assert svc.roll_entry(_today(), "nope", tomorrow) is None


# ── capacity, and what the owner says about a day ────────────────────────────


def _today() -> str:
    return date.today().isoformat()


def test_capacity_is_none_until_somebody_says_otherwise(svc):
    """THE ANSWER THAT MATTERS MOST, because it is the one that keeps the feature
    from inventing a standard. An account that has never stated a capacity is
    never told it has overcommitted — there is no assumed working day here."""
    assert svc.open_day(DAY, create=False)["capacity"] is None


def test_capacity_falls_through_the_account_default(svc):
    svc.update_settings({"day_capacity_minutes": 300})
    assert svc.open_day(DAY, create=False)["capacity"] == 300


def test_a_weekday_default_beats_the_account_one(svc):
    # DAY is a Friday. The map is keyed by the same weekday names habits use,
    # resolved through the one place those names meet Python's numbering.
    svc.update_settings({
        "day_capacity_minutes": 300,
        "day_capacity_by_weekday": {"fri": 120},
    })
    assert svc.open_day(DAY, create=False)["capacity"] == 120
    # A day the map says nothing about still gets the account default.
    assert svc.open_day("2026-08-20", create=False)["capacity"] == 300


def test_what_the_owner_said_for_the_day_beats_everything(svc):
    svc.update_settings({
        "day_capacity_minutes": 300, "day_capacity_by_weekday": {"fri": 120},
    })
    svc.set_day_ritual(_today(), capacity_minutes=90)
    plan = svc.open_day(_today(), create=False)
    assert plan["capacity"] == 90
    # And the two are reported separately on purpose: `capacity_minutes` is what
    # they SAID, `capacity` is what the total is read against. A day that merely
    # inherited a default must stay distinguishable from one they looked at.
    assert plan["capacity_minutes"] == 90
    assert svc.open_day(DAY, create=False)["capacity_minutes"] is None


def test_a_junk_capacity_map_is_ignored_rather_than_guessed_at(svc):
    # A settings blob is hand-editable, so a key that is not a weekday name, and
    # a value that is not a sane count of minutes, must not become a capacity.
    # `true` is the one worth pinning: bool is an int subclass, so an unguarded
    # read would store JSON true as one minute.
    svc.update_settings({
        "day_capacity_minutes": 300,
        "day_capacity_by_weekday": {"funday": 60, "fri": True},
    })
    assert svc.open_day(DAY, create=False)["capacity"] == 300


def test_an_account_default_can_be_un_said(svc):
    """`update_settings` merges shallowly and SKIPS None, so without a sentinel
    an owner who once set a default could never get back to "never said" — the
    state that keeps the app from putting a number on screen nobody gave. -1 is
    that sentinel, the same one this feature uses everywhere else, and 0 cannot
    be it because "I do not work today" is a real capacity."""
    svc.update_settings({"day_capacity_minutes": 300})
    assert svc.open_day(DAY, create=False)["capacity"] == 300
    svc.update_settings({"day_capacity_minutes": -1})
    assert svc.open_day(DAY, create=False)["capacity"] is None
    # And zero still means zero.
    svc.update_settings({"day_capacity_minutes": 0})
    assert svc.open_day(DAY, create=False)["capacity"] == 0


def test_a_capacity_of_zero_is_a_real_answer(svc):
    # "I am not working today" is a statement, and it has to survive every falsy
    # check between the wire and the read — which is why the clear needs a
    # sentinel of its own rather than borrowing zero.
    svc.set_day_ritual(_today(), capacity_minutes=0)
    assert svc.open_day(_today(), create=False)["capacity"] == 0
    # -1 is the clear, and it falls back through to nothing said at all.
    svc.set_day_ritual(_today(), capacity_minutes=-1)
    assert svc.open_day(_today(), create=False)["capacity"] is None


def test_the_ritual_stamps_and_un_stamps(svc):
    today = _today()
    assert svc.set_day_ritual(today, committed=True)["committed_at"] is not None
    # False CLEARS, which is how a day begun by mistake is re-opened. That is why
    # these are tri-state rather than flags.
    assert svc.set_day_ritual(today, committed=False)["committed_at"] is None

    assert svc.set_day_ritual(today, shutdown=True)["shutdown_at"] is not None
    assert svc.set_day_ritual(today, reflection="  Slow start, fine finish  ")[
        "reflection"] == "Slow start, fine finish"
    # An emptied reflection clears rather than storing "", so "nothing written"
    # has exactly one representation.
    assert svc.set_day_ritual(today, reflection="   ")["reflection"] is None


def test_nothing_may_be_said_about_a_day_that_has_happened(svc):
    """A capacity is a plan and a shutdown is a boundary; neither can be
    performed after the fact. The same line `mcp/api.py::update_day_entry` draws
    for `done`, and the reason the ritual is a ritual rather than a form."""
    for kwargs in (
        {"capacity_minutes": 120}, {"committed": True},
        {"shutdown": True}, {"reflection": "went fine"},
    ):
        with pytest.raises(ValueError):
            svc.set_day_ritual(DAY, **kwargs)


def test_yesterday_is_still_writable_so_the_evening_ritual_works(svc):
    """The grace, and it is not slack. `home_timezone` is unset by default and
    the server runs UTC, so a browser in New York between 20:00 and midnight
    sends a key the server already calls yesterday. Without this the shutdown
    ritual would be refused every evening after dinner — which is when it is for.
    Shared with habit minting rather than reasoned about twice."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert svc.set_day_ritual(yesterday, shutdown=True)["shutdown_at"] is not None
    two_days = (date.today() - timedelta(days=2)).isoformat()
    with pytest.raises(ValueError):
        svc.set_day_ritual(two_days, shutdown=True)


def test_saying_something_about_a_day_does_not_open_it(svc):
    """Stating a capacity is not planning. The marker means "the automatic
    snapshot has been built", and setting one here would suppress that snapshot
    forever — the same trap `add_day_entry` documents for hand-adds."""
    svc.set_day_ritual(_today(), capacity_minutes=240)
    assert _count(svc, "day_plan_opened") == 0
    assert _count(svc, "day_plan") == 0
    assert svc.open_day(_today(), create=False)["planned"] is False


# ── estimates ────────────────────────────────────────────────────────────────
#
# The rule these pin: the ENTRY is what its day counts, and the estimate on it
# is a COPY taken when the row was made. What a task, a note or a habit
# "remembers" only ever decides what the NEXT entry starts at — so re-estimating
# something today can never rewrite what a finished day said the work would take.


def test_an_estimate_is_set_and_cleared_on_the_entry(svc):
    plan = svc.open_day(DAY, create=True)
    eid = plan["entries"][0]["entry_id"]

    dto = svc.patch_day_entry(DAY, eid, estimate_minutes=45)
    assert dto["estimate_minutes"] == 45

    # 0 is a REAL estimate — "not worth counting" — and must survive, which is
    # why the clear needs a sentinel of its own rather than borrowing falsiness.
    assert svc.patch_day_entry(DAY, eid, estimate_minutes=0)["estimate_minutes"] == 0
    # -1 is that sentinel.
    assert svc.patch_day_entry(DAY, eid, estimate_minutes=-1)["estimate_minutes"] is None


def test_a_cap_is_a_tri_state_on_the_entry(svc):
    """Not said, stop at the estimate, or run until ticked — three answers, and
    the first is the one an untouched row gives. It reads back as a real
    boolean or None, never as the 0/1 the column stores, and an empty patch
    leaves it alone: None on the way in is "not sent", not "clear"."""
    today = _today()
    svc.open_day(today, create=True)
    dto = svc.add_day_entry(today, entry_id="n1", kind="note", title="Write it up")
    assert dto["capped"] is None
    assert svc.patch_day_entry(today, "n1", capped=True)["capped"] is True
    assert svc.patch_day_entry(today, "n1", capped=False)["capped"] is False
    assert svc.patch_day_entry(today, "n1")["capped"] is False


def test_a_cap_cannot_be_decided_for_a_day_that_has_run(svc):
    """The same fence `set_day_ritual` keeps: a cap is how a row WILL be worked,
    and a day that has happened has no will left in it. Refused rather than
    recorded, the record untouched by the attempt — and the other fields on the
    same PATCH path are not fenced by this: dropping a row off a past day is
    still allowed, exactly as before."""
    plan = svc.open_day(DAY, create=True)
    eid = plan["entries"][0]["entry_id"]
    with pytest.raises(ValueError) as caught:
        svc.patch_day_entry(DAY, eid, capped=True)
    assert "already happened" in str(caught.value)
    assert svc.open_day(DAY, create=False)["entries"][0]["capped"] is None
    assert svc.patch_day_entry(DAY, eid, dropped=True)["dropped_at"]


def test_worked_seconds_are_credited_never_assigned(svc):
    """The column starts NULL — "never worked", a different fact from 0 — and
    only ever grows by an increment the server computed. There is no field a
    client could send to set it, which is what `_DAY_ENTRY_FIELDS` not listing
    it enforces; and a negative credit is clamped rather than subtracted,
    because nothing has a reason to un-work a row."""
    today = _today()
    svc.open_day(today, create=True)
    dto = svc.add_day_entry(today, entry_id="n1", kind="note", title="Write it up")
    assert dto["worked_seconds"] is None
    assert store.add_worked_seconds(svc._conn, today, "n1", 90)["worked_seconds"] == 90
    assert store.add_worked_seconds(svc._conn, today, "n1", 30)["worked_seconds"] == 120
    assert store.add_worked_seconds(svc._conn, today, "n1", -500)["worked_seconds"] == 120
    assert store.add_worked_seconds(svc._conn, today, "nope", 10) is None
    with pytest.raises(ValueError):
        store.update_day_entry(svc._conn, today, "n1", worked_seconds=5)
    entries = svc.open_day(today, create=False)["entries"]
    assert next(e for e in entries if e["entry_id"] == "n1")["worked_seconds"] == 120


def test_estimating_a_task_teaches_the_task_for_next_time(svc):
    plan = svc.open_day(DAY, create=True)
    entry = next(e for e in plan["entries"] if e["uid"] == "due-today")
    svc.patch_day_entry(DAY, entry["entry_id"], estimate_minutes=25)

    # The sidecar learned it, so a later day starts from this answer instead of
    # asking again. This is the column that has been writable and unread since
    # the sidecar table was created.
    side = store.get_sidecar(svc._conn, LIST_A, "due-today")
    assert side["estimated_minutes"] == 25
    # And it reaches the task DTO, which nothing read it through before.
    assert svc.get_task(LIST_A, "due-today")["estimated_minutes"] == 25


def test_a_new_entry_starts_from_what_the_task_remembers(svc):
    store.set_sidecar(svc._conn, LIST_B, "someday", estimated_minutes=90)
    svc.open_day(DAY, create=True)
    dto = svc.add_day_entry(
        DAY, entry_id="hand", kind="task", list_id="home", uid="someday")
    assert dto["estimate_minutes"] == 90


def test_a_note_starts_unestimated_because_nothing_remembers_one(svc):
    svc.open_day(DAY, create=True)
    dto = svc.add_day_entry(DAY, entry_id="jot", kind="note", title="Ring the bank")
    assert dto["estimate_minutes"] is None


def test_a_snapshot_row_starts_from_what_the_task_remembers(svc):
    store.set_sidecar(svc._conn, LIST_A, "due-today", estimated_minutes=15)
    plan = svc.open_day(DAY, create=True)
    entry = next(e for e in plan["entries"] if e["uid"] == "due-today")
    assert entry["estimate_minutes"] == 15


def test_re_estimating_a_task_does_not_rewrite_a_day_already_planned(svc):
    """THE POINT OF COPYING RATHER THAN JOINING.

    A day is a snapshot of what was intended at the time, and how long the owner
    thought something would take is part of that. Reading the estimate through a
    join would make today's re-think retroactively edit every past day the task
    ever appeared on.
    """
    store.set_sidecar(svc._conn, LIST_A, "due-today", estimated_minutes=15)
    svc.open_day(DAY, create=True)

    store.set_sidecar(svc._conn, LIST_A, "due-today", estimated_minutes=240)
    entry = next(e for e in svc.open_day(DAY, create=False)["entries"]
                 if e["uid"] == "due-today")
    assert entry["estimate_minutes"] == 15


def test_a_carried_entry_keeps_the_estimate_it_was_carried_with(svc):
    svc.open_day(PREV, create=True)
    chosen = svc.add_day_entry(
        PREV, entry_id="c1", kind="note", title="Finish the draft")
    svc.patch_day_entry(PREV, chosen["entry_id"], estimate_minutes=50)

    carried = next(e for e in svc.open_day(DAY, create=True)["entries"]
                   if e["title"] == "Finish the draft")
    # A note has no task to remember for it, so the row it carried from is the
    # only place yesterday's answer exists. Losing it here would make the ritual
    # ask again every morning the jot survived.
    assert carried["source"] == "carried"
    assert carried["estimate_minutes"] == 50


def test_a_habit_occurrence_copies_the_estimate_off_its_rule(svc):
    # TODAY rather than this file's fixed DAY: minting is gated on pastness
    # (`_habit_minting_allowed`), because an occurrence's row is the only record
    # of it anywhere and backfilling one into a finished day is a forgery. So a
    # test about occurrences has to ask for a day that may still have them.
    today = date.today().isoformat()
    svc.create_habit(title="Read", estimate_minutes=20)
    entry = next(e for e in svc.open_day(today, create=True)["entries"]
                 if e["kind"] == "habit")
    assert entry["estimate_minutes"] == 20

    # Re-estimating the RULE leaves the day that already ran it alone, exactly as
    # renaming it leaves that day's title alone.
    hb = svc.list_habits()[0]
    svc.update_habit(hb["id"], estimate_minutes=90)
    again = next(e for e in svc.open_day(today, create=False)["entries"]
                 if e["kind"] == "habit")
    assert again["estimate_minutes"] == 20


def test_estimating_a_note_teaches_no_task(svc):
    """A note names no task, so there is nothing to write an estimate through to.

    This used to assert that ONE unrelated task — LIST_A/"due-today", which the
    test never touches — had no sidecar row. That was true before the code under
    test ran, so the test could not have failed however the write-through
    behaved. It now counts the sidecar table across the write, which is the
    thing actually claimed: estimating a note writes no sidecar row at all.
    """
    svc.open_day(DAY, create=True)
    before = _count(svc, "sidecar")
    dto = svc.add_day_entry(DAY, entry_id="jot", kind="note", title="Ring the bank")
    svc.patch_day_entry(DAY, dto["entry_id"], estimate_minutes=10)
    assert _count(svc, "sidecar") == before, "a note taught something a duration"

    # And the control, so the count is measuring a real mechanism rather than a
    # table nothing ever writes to: the same call on a TASK entry does write.
    task_entry = _entry_id(svc.open_day(DAY, create=False), "due-today")
    svc.patch_day_entry(DAY, task_entry, estimate_minutes=25)
    assert store.get_sidecar(svc._conn, LIST_A, "due-today")["estimated_minutes"] == 25


def test_an_older_database_gains_the_focus_columns(tmp_path):
    """The two ALTERs a focus session needs, on the same rule as the three before
    them: `_day_entry_dto` reads both keys, sqlite3.Row answers IndexError for a
    column the query did not return, and IndexError is a 500 on every read of
    every day. Hand-built rather than captured, like the estimate test below,
    so it keeps testing the upgrade rather than a fixture that ages out."""
    conn = store.connect(str(tmp_path / "old.db"))
    conn.executescript(
        """CREATE TABLE day_plan (
               day              TEXT NOT NULL,
               entry_id         TEXT NOT NULL,
               kind             TEXT NOT NULL,
               collection_href  TEXT,
               uid              TEXT,
               title            TEXT,
               source           TEXT NOT NULL,
               habit_id         TEXT,
               position         REAL,
               estimate_minutes INTEGER,
               done_at          TEXT,
               dropped_at       TEXT,
               rolled_to        TEXT,
               created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
               PRIMARY KEY (day, entry_id)
           );
           INSERT INTO day_plan (day, entry_id, kind, title, source)
           VALUES ('2026-08-21', 'legacy', 'note', 'Written before focus', 'user');"""
    )
    store.init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(day_plan)")}
    assert {"worked_seconds", "capped"} <= cols
    row = store.find_day_entry(conn, "2026-08-21", entry_id="legacy")
    assert row["worked_seconds"] is None and row["capped"] is None
    # And the legacy row reads through the DTO — which is the whole point.
    dto = TaskService._day_entry_dto(row)
    assert dto["worked_seconds"] is None and dto["capped"] is None
    conn.close()


def test_an_older_database_gains_the_estimate_columns(tmp_path):
    """The second and third hand-written ALTERs, on the same rule as habit_id.

    Estimates arrived after both `day_plan` and `habits` existed, so the same
    trap applies to both: `_day_entry_dto` reads `row["estimate_minutes"]` and
    `_habit_dto` reads it off the rule, and sqlite3.Row answers IndexError for a
    column the query did not return — a 500 on every read of every day and of
    the habits list, not a degraded one.

    Hand-built pre-estimate tables rather than a captured file, so this keeps
    testing the upgrade rather than a fixture that ages out.
    """
    conn = store.connect(str(tmp_path / "old.db"))
    conn.executescript(
        """CREATE TABLE day_plan (
               day             TEXT NOT NULL,
               entry_id        TEXT NOT NULL,
               kind            TEXT NOT NULL,
               collection_href TEXT,
               uid             TEXT,
               title           TEXT,
               source          TEXT NOT NULL,
               habit_id        TEXT,
               position        REAL,
               done_at         TEXT,
               dropped_at      TEXT,
               created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
               PRIMARY KEY (day, entry_id)
           );
           CREATE TABLE habits (
               id         TEXT PRIMARY KEY,
               title      TEXT NOT NULL,
               days       TEXT NOT NULL DEFAULT '',
               paused_at  TEXT,
               position   REAL,
               created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           );
           INSERT INTO day_plan (day, entry_id, kind, title, source)
           VALUES ('2026-08-21', 'legacy', 'note', 'Written before estimates', 'user');
           INSERT INTO habits (id, title, days) VALUES ('hb-old', 'Read', '');"""
    )
    store.init_db(conn)
    assert "estimate_minutes" in {
        r["name"] for r in conn.execute("PRAGMA table_info(day_plan)")}
    assert "estimate_minutes" in {
        r["name"] for r in conn.execute("PRAGMA table_info(habits)")}

    # Both pre-existing rows read through the REAL DTOs, unestimated. NULL is
    # the honest answer — nobody said how long these take — and it is what keeps
    # them out of the day's total rather than counting them as zero-length work.
    row = store.find_day_entry(conn, "2026-08-21", entry_id="legacy")
    dto = TaskService._day_entry_dto(row)
    assert dto["estimate_minutes"] is None
    assert dto["title"] == "Written before estimates"

    habit = next(iter(store.list_habits(conn)))
    assert TaskService._habit_dto(habit)["estimate_minutes"] is None

    # Idempotent: init_db runs on every start, and the second pass must not try
    # to add either column again (SQLite has no ADD COLUMN IF NOT EXISTS).
    store.init_db(conn)
    conn.close()


def test_an_older_database_gains_the_habit_id_column(tmp_path):
    """The hand-written ALTER in `store.init_db`, and why it is not optional.

    There is no migration runner here: `executescript` runs CREATE TABLE IF NOT
    EXISTS, which does nothing at all to a day_plan that already exists, so a
    column added to schema.sql reaches an upgraded database ONLY through the
    PRAGMA/ALTER block. Without it `_day_entry_dto`'s `row["habit_id"]` raises
    IndexError — sqlite3.Row's answer for a column the query did not return —
    and IndexError is outside the taxonomy app.py maps, so the failure is a 500
    on every read of every day, not just the days holding a habit.

    Written against a hand-built pre-habits table rather than a captured file, so
    it keeps testing the upgrade rather than a fixture that ages out.
    """
    conn = store.connect(str(tmp_path / "old.db"))
    conn.executescript(
        """CREATE TABLE day_plan (
               day             TEXT NOT NULL,
               entry_id        TEXT NOT NULL,
               kind            TEXT NOT NULL,
               collection_href TEXT,
               uid             TEXT,
               title           TEXT,
               source          TEXT NOT NULL,
               position        REAL,
               done_at         TEXT,
               dropped_at      TEXT,
               created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
               PRIMARY KEY (day, entry_id)
           );
           INSERT INTO day_plan (day, entry_id, kind, title, source)
           VALUES ('2026-08-21', 'legacy', 'note', 'Written before habits', 'user');"""
    )
    store.init_db(conn)
    assert "habit_id" in {r["name"] for r in conn.execute("PRAGMA table_info(day_plan)")}

    # The pre-existing row reads through the real DTO, with a null habit_id —
    # nothing to backfill, because "no rule minted this" IS null.
    row = store.find_day_entry(conn, "2026-08-21", entry_id="legacy")
    dto = TaskService._day_entry_dto(row)
    assert dto["habit_id"] is None and dto["title"] == "Written before habits"
    # Idempotent: init_db runs on every start, and the second pass must not try
    # to add the column again (SQLite has no ADD COLUMN IF NOT EXISTS).
    store.init_db(conn)
    conn.close()


# ── ranges ───────────────────────────────────────────────────────────────────

def test_day_range_is_planned_days_only_and_excludes_its_end(svc):
    svc.open_day(PREV, create=True)
    svc.open_day(DAY, create=True)
    days = [p["day"] for p in svc.day_range(PREV, NEXT)]
    # QUIET_DAY-style unopened days are absent rather than present-and-empty:
    # absence is what the client draws as "not planned yet", and a six-month
    # query would otherwise be mostly padding.
    assert days == [PREV, DAY]
    assert [p["day"] for p in svc.day_range(PREV, DAY)] == [PREV]      # `to` excluded
    assert svc.day_range(DAY, DAY) == []
    assert all(p["planned"] for p in svc.day_range(PREV, NEXT))


def test_day_range_is_bounded(svc):
    """The caller chooses the width of this scan, so the width is bounded. 190
    days is more than any view asks for; past it the answer is 422, not a walk
    of the whole table."""
    from tasksd.service import DAY_RANGE_MAX_DAYS

    assert svc.day_range("2026-01-01", "2026-07-10") == []      # 190 days exactly
    with pytest.raises(ValueError):
        svc.day_range("2026-01-01", "2026-07-11")
    assert DAY_RANGE_MAX_DAYS == 190


def test_day_range_touches_the_connection_only_under_the_service_lock(svc):
    """`store.connect` opens ONE connection `check_same_thread=False`, on the
    stated promise that this class serializes every access behind `_lock`. The
    route reaches `day_range` through `asyncio.to_thread`, so two concurrent
    GET /api/day calls are two threadpool threads inside that one connection.

    `day_range` used to close the lock after the range read and then build the
    DTOs outside it — and `_day_plan_dto` is not a pure formatter: it reads
    `day_ritual`, and through `_effective_capacity` the settings blob. That was
    two unserialized queries per day, up to 380 at the 190-day bound. Concurrent
    callers raised `sqlite3.InterfaceError: bad parameter or other API misuse`;
    the quieter outcome was worse, a row fetched for one day handed to the
    reader for another, so a day reported another day's capacity or reflection
    with no error at all.

    Asserted by counting store reads issued while the lock is NOT held, rather
    than by racing threads: a thread race reproduces this most of the time,
    which is not the same as always, and a flaky pin on a data-integrity
    property is worth less than none."""
    for day in (PREV, DAY, NEXT):
        svc.open_day(day, create=True)
        store.set_day_ritual(svc._conn, day, reflection="went fine")

    unlocked: list[str] = []
    originals = {n: getattr(store, n) for n in ("get_day_ritual", "get_settings")}

    def watch(name, fn):
        def spy(conn, *a, **k):
            if not svc._lock._is_owned():
                unlocked.append(name)
            return fn(conn, *a, **k)
        return spy

    for name, fn in originals.items():
        setattr(store, name, watch(name, fn))
    try:
        days = svc.day_range(PREV, "2026-08-23")
    finally:
        for name, fn in originals.items():
            setattr(store, name, fn)

    assert [d["day"] for d in days] == [PREV, DAY, NEXT]
    assert all(d["reflection"] == "went fine" for d in days), (
        "the batched ritual read must still reach each day's own row")
    assert unlocked == [], (
        f"day_range read the shared connection {len(unlocked)} times outside the "
        f"service lock ({sorted(set(unlocked))}); every access must be serialized")


# ── the HTTP contract ────────────────────────────────────────────────────────
#
# The routes over the same service, through the real app. Each test uses days of
# its own: the `client` fixture is session-scoped, so its database is shared with
# every other suite in the run.

@pytest.mark.radicale
def test_routes_round_trip_a_day(client):
    day = "2027-03-01"
    lst = client.post("/api/lists", json={"name": f"D-{uuid.uuid4().hex[:8]}"}).json()
    task = client.post(f"/api/lists/{lst['id']}/tasks",
                       json={"summary": "write it up", "due": day}).json()

    # GET never creates: the day is unplanned even though a task is due on it.
    #
    # Whole-dict equality, like the service-level assertion this mirrors and for
    # the same reason: it is what makes a field ADDED to the plan shape get
    # looked at once, with its default on an untouched day in front of you. This
    # is the WIRE contract rather than the service's — the route's job is to
    # serialise that shape unchanged — so the two are worth having both.
    #
    # It has now caught exactly what it exists to catch. The five ritual fields
    # landed on `_day_plan_dto`, the service-level twin was updated with them,
    # and this one was not, because it is `radicale`-marked and skips wherever
    # Docker is unavailable. Nothing but CI was ever going to say so.
    r = client.get(f"/api/day/{day}")
    assert r.status_code == 200 and r.json() == {
        "day": day, "planned": False, "entries": [],
        # No capacity INVENTED for a day nobody has spoken about — the one that
        # matters. An account that never stated one must not be told it has
        # overcommitted against a number it never gave.
        "capacity_minutes": None, "capacity": None,
        "committed_at": None, "shutdown_at": None, "reflection": None,
    }

    opened = client.post(f"/api/day/{day}/open")
    assert opened.status_code == 200
    # Containment, not equality: this database is shared with every other suite
    # in the run, so the snapshot legitimately also holds their overdue tasks.
    snapshot = opened.json()["entries"]
    assert task["uid"] in [e["uid"] for e in snapshot]
    assert {e["source"] for e in snapshot} == {"auto"}
    assert client.get(f"/api/day/{day}").json()["planned"] is True

    entry_id = uuid.uuid4().hex
    r = client.post(f"/api/day/{day}/entries",
                    json={"entry_id": entry_id, "kind": "note", "title": "buy milk"})
    assert r.status_code == 201 and r.json()["source"] == "user"
    # Replayed with the same entry_id — one row, not two.
    again = client.post(f"/api/day/{day}/entries",
                        json={"entry_id": entry_id, "kind": "note", "title": "buy milk"})
    assert again.json()["entry_id"] == entry_id
    assert len(client.get(f"/api/day/{day}").json()["entries"]) == len(snapshot) + 1

    r = client.patch(f"/api/day/{day}/entries/{entry_id}", json={"done": True})
    assert r.status_code == 200 and r.json()["done_at"]
    # The same field on a TASK entry is a 422: the entry exists, `done` does not
    # apply to it — a task's doneness is its VTODO STATUS.
    task_entry = [e for e in snapshot if e["uid"] == task["uid"]][0]
    assert client.patch(f"/api/day/{day}/entries/{task_entry['entry_id']}",
                        json={"done": True}).status_code == 422

    r = client.get("/api/day", params={"from": day, "to": "2027-03-02"})
    assert [p["day"] for p in r.json()] == [day]


@pytest.mark.radicale
def test_routes_refuse_a_bad_day_and_an_unknown_entry(client):
    day = "2027-03-05"
    assert client.get("/api/day/20270305").status_code == 422
    assert client.post("/api/day/2027-02-30/open").status_code == 422
    assert client.get("/api/day", params={"from": day, "to": "not-a-day"}).status_code == 422
    # Past the 190-day bound.
    assert client.get("/api/day", params={"from": "2027-01-01", "to": "2027-12-31"}
                      ).status_code == 422
    # An unknown entry_id on a real day is a 404, not a silent 200.
    client.post(f"/api/day/{day}/open")
    assert client.patch(f"/api/day/{day}/entries/nope", json={"done": True}).status_code == 404
    # A task entry naming a list that does not resolve is a 422: the id is a
    # field of the body, and the day in the path exists whether or not it is
    # planned.
    assert client.post(f"/api/day/{day}/entries", json={
        "entry_id": uuid.uuid4().hex, "kind": "task", "list": "nope", "uid": "x",
    }).status_code == 422


@pytest.mark.radicale
def test_settings_accepts_the_today_tab(client):
    """The fifth tab has to be accepted by the backend BEFORE the frontend ships
    it. `sanitizeTabOrder` appends any shipped tab a stored blob lacks, so the
    first settings write from a client that knows the Today tab carries "today"
    whether or not the user touched the tab strip — and a 422 rejects the WHOLE
    settings write, taking the theme and the dashboard layout with it."""
    r = client.put("/api/settings", json={
        "tab_order": ["today", "home", "tasks", "calendar", "scheduling"],
        "start_tab": "today",
        "last_tab": "today",
    })
    assert r.status_code == 200, r.text
    assert r.json()["start_tab"] == "today"
    assert client.get("/api/settings").json()["tab_order"][0] == "today"


# ── what the connector says about a day ──────────────────────────────────────
#
# `McpApi` over the same in-process service, so these run with no Radicale like
# the rest of this file. They live HERE rather than in test_mcp.py, whose day
# tests all need the scratch server and skip without Docker — a rule about how a
# day is described is worth more in a suite that actually runs.
#
# The rule they exist for is `REVIEW_ARM`'s: two surfaces describing one day
# differently is worse than either being slightly wrong. Everything below is a
# claim the Today tab also makes, checked on the other side of the wall.
#
# THESE USE THE REAL CLOCK, unlike everything above, and have to: half of them
# are about a PASTNESS rule — a capacity cannot be stated for a day that has
# run, work cannot be moved backwards — and `DAY` is a fixed Friday that is
# already in the past. A fixed day cannot exercise a rule about which side of
# today something falls on. Resolved at call time rather than at import, so a
# suite that runs across midnight still agrees with the service it is asking.


def _live() -> str:
    """Today, as the service resolves it."""
    return date.today().isoformat()


def _live_plus(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _seed_due_on(svc_, day: str) -> None:
    """Two open tasks due ON `day`, so a snapshot of it has rows to work with.

    The `svc` fixture's cast is dated around DAY, a fixed Friday in 2026, while
    the connector tests below run against the REAL today — which every one of
    those deadlines is long past. That was invisible for as long as the snapshot
    derived overdue work, because the whole cast then landed on any live day.
    It derives only what is due on the day itself now, so a live day has to be
    given its own deadlines rather than inheriting the fixture's by lateness.

    Deliberately NOT folded into the `svc` fixture: a fixture whose seeds move
    with the wall clock is the thing this file's fixed day constants exist to
    avoid, and only the handful of tests that need a live day should pay for it.
    """
    _seed_task(svc_._conn, LIST_A, "live-a", "Ship the thing", due=day)
    _seed_task(svc_._conn, LIST_B, "live-b", "Call the plumber", due=day)


@pytest.fixture
def mcp_api(svc):
    return McpApi(svc)


def _entry_id(plan: dict, uid: str) -> str:
    return next(e["entry_id"] for e in plan["entries"] if e["uid"] == uid)


def test_the_connector_reports_what_the_owner_said_about_a_day(mcp_api, svc):
    """A model that cannot see the capacity will happily propose an eleventh
    thing for a day already an hour over — which is the exact failure the number
    exists to prevent. It reports both `capacity_minutes` (what was stated FOR
    this day) and `capacity` (what the total should be read against), because a
    day that merely inherited a weekday default must stay distinguishable from
    one the owner looked at and set."""
    day = _live()
    svc.open_day(day, create=True)
    svc.set_day_ritual(day, capacity_minutes=300, reflection="  Slow start.  ")
    out = mcp_api.review_day(day=day)

    assert out["capacity_minutes"] == 300 and out["capacity"] == 300
    assert out["reflection"] == "Slow start."
    assert out["shutdown_at"] is None and out["committed_at"] is None


def test_a_day_nobody_planned_still_has_every_key(mcp_api):
    """An answer whose keys come and go teaches a reader a shape that is only
    sometimes true, and the first unplanned day is where they find out. The
    residual `other` bucket is always present for the same reason."""
    out = mcp_api.review_day(day=QUIET_DAY)
    assert out["planned"] is False
    for key in ("capacity", "capacity_minutes", "committed_at", "shutdown_at",
                "reflection"):
        assert out[key] is None, key
    assert out["totals"] == {
        "planned_minutes": 0, "done_minutes": 0, "unestimated": 0,
        "worked_minutes": 0}
    for bucket in ("chosen", "carried", "derived", "habits", "other", "moved",
                   "dropped"):
        assert out[bucket] == [], bucket


def test_moved_work_is_not_reported_as_abandoned(mcp_api, svc):
    """THE DISTINCTION `rolled_to` EXISTS FOR. "Happening on Thursday" and "not
    happening" are different answers, and a look-back that filed both under
    `dropped` would tell the owner they abandoned something they rescheduled."""
    day, target = _live(), _live_plus(1)
    _seed_due_on(svc, day)
    plan = svc.open_day(day, create=True)
    moved, declined = _entry_id(plan, "live-a"), _entry_id(plan, "live-b")
    svc.roll_entry(day, moved, target)
    svc.patch_day_entry(day, declined, dropped=True)

    out = mcp_api.review_day(day=day)
    assert [e["entry_id"] for e in out["moved"]] == [moved]
    assert out["moved"][0]["rolled_to"] == target, "a model has to say WHERE"
    assert [e["entry_id"] for e in out["dropped"]] == [declined]
    # And neither is still reported as sitting on the day.
    everywhere_else = [e["entry_id"] for k in ("chosen", "carried", "derived",
                                               "habits", "other")
                       for e in out[k]]
    assert moved not in everywhere_else and declined not in everywhere_else


def test_the_totals_leave_out_what_was_decided_about(mcp_api, svc):
    """Declining something, or doing it on Thursday, is how a day gets back
    under its capacity — a total that kept counting it would make the two
    controls that help useless. And an unestimated row counts as NOTHING, which
    is why the third number is reported beside the other two: "0m of 1h 20m"
    with no `unestimated` reads as a day nothing happened on."""
    day, target = _live(), _live_plus(1)
    _seed_due_on(svc, day)
    plan = svc.open_day(day, create=True)
    kept, moved = _entry_id(plan, "live-a"), _entry_id(plan, "live-b")
    svc.patch_day_entry(day, kept, estimate_minutes=45)
    svc.patch_day_entry(day, moved, estimate_minutes=90)
    before = mcp_api.review_day(day=day)["totals"]
    assert before["planned_minutes"] == 135

    svc.roll_entry(day, moved, target)
    after = mcp_api.review_day(day=day)["totals"]
    assert after["planned_minutes"] == 45, "the moved row still counts"
    # Everything on the day that is neither of those two carries no estimate.
    assert after["unestimated"] == len(
        [e for e in plan["entries"] if e["entry_id"] not in (kept, moved)])
    # And it travelled with the work rather than being left behind.
    assert [e["estimate_minutes"] for e in svc.open_day(target, create=False)["entries"]
            if e["uid"] == "live-b"] == [90]


def test_done_minutes_counts_only_what_was_finished_that_day(mcp_api, svc):
    """A task planned today and ticked next Thursday is Thursday's work.
    Counting it as today's is the one way a look-back can flatter a day that did
    not happen — the same fence the app's `rowDone` draws for a past day.

    This test used to assert `done_minutes == 0` on a day where NOTHING had been
    completed, which made it unable to tell its own rule from a function that
    returned zero unconditionally — both figures could be hardcoded to 0 and it
    stayed green. It now needs a completion ON the day to pass, and a completion
    on ANOTHER day to stay out of the figure, so only the real rule satisfies it.
    """
    day, elsewhere = _live(), _live_plus(-4)
    # One task finished ON the day, one finished four days earlier. Both are on
    # the same list and both carry a real COMPLETED stamp, which is the only
    # thing that gives a completion a day to belong to.
    _seed_task(svc._conn, LIST_A, "did-today", "Finished today", due=day,
               status="COMPLETED", completed_at=f"{day.replace('-', '')}T120000Z")
    _seed_task(svc._conn, LIST_A, "did-before", "Finished earlier", due=day,
               status="COMPLETED", completed_at=f"{elsewhere.replace('-', '')}T120000Z")

    _seed_due_on(svc, day)
    plan = svc.open_day(day, create=True)
    svc.patch_day_entry(day, _entry_id(plan, "live-a"), estimate_minutes=45)
    # Added by hand rather than looked for in the snapshot: a COMPLETED task is
    # correctly left out of the derived plan, and what is being tested here is a
    # row that IS on the day and was finished — which is what the owner ticking
    # something they had planned actually leaves behind.
    for uid, minutes in (("did-today", 20), ("did-before", 90)):
        added = svc.add_day_entry(
            day, entry_id=uuid.uuid4().hex, kind="task", list_id="work", uid=uid)
        svc.patch_day_entry(day, added["entry_id"], estimate_minutes=minutes)

    totals = mcp_api.review_day(day=day)["totals"]
    assert totals["planned_minutes"] == 155, "every live row counts toward planned"
    # 20 and not 110: the row finished four days ago is on today's plan, but it
    # was not done today, and today does not get to claim it.
    assert totals["done_minutes"] == 20


def test_the_connector_may_not_state_a_capacity_or_write_a_reflection(mcp_api):
    """The same call that gives habits no tool for creating a rule. A capacity,
    a start, a shutdown and a reflection are the owner's declarations about
    their own day; a connector able to make them would be manufacturing the
    record they exist to keep honest.

    Checked against the SIGNATURES and not just the names. Reading method names
    alone was the weaker half of this test and nearly all of it: a method called
    `set_day_facts(capacity_minutes=...)` passes a name check and defeats the
    rule entirely. What actually matters is whether any reachable entry point
    ACCEPTS one of these fields, so that is what is inspected.

    `_day_facts` and `_day_totals` are private and excluded: they REPORT the
    capacity, which is the whole point of the connector seeing a day at all.
    """
    import inspect

    FORBIDDEN = ("capacity_minutes", "capacity", "reflection", "committed",
                 "shutdown")
    reachable = [n for n in dir(McpApi) if not n.startswith("_")]
    assert "review_day" in reachable, "the surface is not being enumerated"

    for name in reachable:
        member = getattr(McpApi, name)
        if not callable(member):
            continue
        # No entry point may be NAMED for the ritual...
        for word in ("ritual", "capacity", "reflection", "shutdown", "commit"):
            assert word not in name, f"{name} reaches {word}"
        # ...and none may TAKE one of its fields, whatever it is called.
        try:
            params = inspect.signature(member).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        taken = sorted(set(params) & set(FORBIDDEN))
        assert not taken, f"McpApi.{name} accepts {taken}, which only the owner may set"

    # And the positive half: the connector can still SEE all of it, because a
    # model that cannot read the capacity will propose an eleventh thing for a
    # day already over. Reporting is the whole reason the fields are exposed.
    out = mcp_api.review_day(day=_live())
    for field in ("capacity", "capacity_minutes", "committed_at", "shutdown_at",
                  "reflection"):
        assert field in out, field


def test_an_estimate_cannot_be_written_onto_a_day_that_has_run(mcp_api, svc):
    """An estimate is what something was expected to take BEFORE it was
    attempted. Written afterwards it is a number chosen with the answer in hand,
    and the day's "2h of 3h planned" stops meaning anything the moment either
    half can be edited to taste. `dropped` and `position` stay allowed on a past
    day for the reason they always were: neither manufactures a record."""
    past = "2020-01-02"
    svc.open_day(past, create=True)
    entry = svc.add_day_entry(past, entry_id=uuid.uuid4().hex, kind="note",
                              title="Last decade")
    with pytest.raises(ToolError) as caught:
        mcp_api.update_day_entry(entry["entry_id"], day=past, estimate_minutes=30)
    assert "already happened" in str(caught.value)

    # Dropping the same row on the same day still works.
    out = mcp_api.update_day_entry(entry["entry_id"], day=past, dropped=True)
    assert out["dropped_at"]

    # And on a day that has NOT run, the same call lands.
    day = _live()
    live = svc.add_day_entry(day, entry_id=uuid.uuid4().hex, kind="note",
                             title="Today's")
    assert mcp_api.update_day_entry(
        live["entry_id"], day=day, estimate_minutes=30)["estimate_minutes"] == 30


def test_the_connector_moves_work_rather_than_dropping_and_re_adding(mcp_api, svc):
    """Without this the model's only way to say "do it Thursday" is drop + add,
    which files the row under `dropped` and reports it abandoned — losing the
    very distinction the bucket above exists to keep."""
    day, target = _live(), _live_plus(1)
    _seed_due_on(svc, day)
    plan = svc.open_day(day, create=True)
    entry_id = _entry_id(plan, "live-a")
    out = mcp_api.update_day_entry(entry_id, day=day, move_to=target)

    assert out["rolled_to"] == target and out["dropped_at"] is None
    landed = [e["uid"] for e in svc.open_day(target, create=False)["entries"]]
    assert landed.count("live-a") == 1
    # Backwards is refused: an entry appearing on a finished day is the forgery
    # every other rule here exists to prevent.
    with pytest.raises(ToolError):
        mcp_api.update_day_entry(_entry_id(plan, "live-b"), day=day,
                                 move_to="2020-01-01")


def test_moving_is_an_answer_and_will_not_be_combined_with_another(mcp_api, svc):
    """Applying both would file one row under two contradictory decisions in the
    same call, and whichever landed second would be the day's record of it."""
    day = _live()
    _seed_due_on(svc, day)
    plan = svc.open_day(day, create=True)
    with pytest.raises(ToolError) as caught:
        mcp_api.update_day_entry(_entry_id(plan, "live-a"), day=day,
                                 move_to=_live_plus(1), dropped=True)
    assert "on its own" in str(caught.value)


def test_every_sidecar_table_schema_names_is_in_the_backup_list():
    """Two files enumerate the tables a resync cannot rebuild, and they have to
    agree: schema.sql's header, for whoever is reading the schema, and
    docs/DEPLOY.md's backup section, for whoever is restoring a machine.

    A table in the first and missing from the second is not a documentation nit
    — it is a table nobody backs up, discovered on the day someone needs it. That
    drifted once already: `day_ritual` was added to the schema and to DEPLOY.md
    and left out of schema.sql's own list.

    One-way containment on purpose. DEPLOY.md legitimately names tables this
    schema comment does not itemise (the scheduling pair), so requiring equality
    would fail on a difference that is not a mistake.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    schema = (root / "backend/tasksd/db/schema.sql").read_text(encoding="utf-8")
    deploy = (root / "docs/DEPLOY.md").read_text(encoding="utf-8")

    # The parenthesised list in the "SIDECAR tables (...)" header line, which may
    # wrap across several comment lines.
    m = re.search(r"SIDECAR tables \(([^)]*)\)", schema, re.S)
    assert m, "schema.sql no longer has a 'SIDECAR tables (...)' header to check"
    named = {t.strip() for t in re.sub(r"--", " ", m.group(1)).split(",") if t.strip()}
    assert named, "the SIDECAR list parsed empty — the header shape changed"

    missing = sorted(t for t in named if f"`{t}`" not in deploy)
    assert not missing, (
        f"{missing} are named as sidecar-class in schema.sql but appear in no "
        f"backup instruction in docs/DEPLOY.md. A resync rebuilds none of them, "
        f"so a table missing there is a table nobody backs up."
    )
    # And the tables must actually exist, so a rename cannot leave the list
    # naming something gone while still passing the check above.
    for table in named:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema, table


def test_a_created_habit_cannot_be_given_the_clear_sentinel(svc):
    """The clear sentinel is a PATCH's, and only a PATCH's.

    `EditHabit.estimate_minutes` takes -1 to mean "un-state this", the same
    spelling `patch_day_entry` uses. `CreateHabit` advertised the same bound and
    `create_habit` had no arm to match it — it wrote the -1 STRAIGHT INTO the
    habits row, and every occurrence the rule minted afterwards was copied from
    it. A day holding one then reported a NEGATIVE planned total and counted the
    row as estimated, because -1 is not None.

    Refused at the edge rather than swallowed in the service: there is nothing to
    clear on a rule that does not exist yet (the same reasoning
    `CreateDayEntry.estimate_minutes` carries), and a service-side swallow would
    leave two spellings of "no estimate" in one column.
    """
    from tasksd.app import CreateHabit
    import pydantic

    # 0 is a real estimate and still passes; -1 is not a value, it is a verb.
    assert CreateHabit(title="Read", estimate_minutes=0).estimate_minutes == 0
    assert CreateHabit(title="Read").estimate_minutes is None
    with pytest.raises(pydantic.ValidationError):
        CreateHabit(title="Read", estimate_minutes=-1)

    # And the clear still works where it belongs — on the edit.
    habit = svc.create_habit(title="Read", days="", estimate_minutes=30)
    assert habit["estimate_minutes"] == 30
    assert svc.update_habit(habit["id"], estimate_minutes=-1)["estimate_minutes"] is None


def test_saying_nothing_about_a_day_writes_no_ritual_row(svc):
    """`service.set_day_ritual` calls a PATCH with an empty body a read, and
    publishes no event for one. The store has to agree: it used to INSERT the
    row before checking whether there was anything to put in it, so a read minted
    the row holding the nulls it had just reported.

    That row is not free. `day_ritual` is sidecar-class — no resync rebuilds it
    and every backup has to carry it — so a day nobody ever spoke about was
    taking up space in the one table that cannot be regenerated.
    """
    day = _live()
    assert _count(svc, "day_ritual") == 0
    dto = svc.set_day_ritual(day)
    assert _count(svc, "day_ritual") == 0, "an empty PATCH minted a row"
    # It still ANSWERS, with the nulls that are true of a day nobody has spoken
    # about — it simply does not write them down.
    assert dto["capacity"] is None and dto["reflection"] is None

    # A real statement does write, and the row it writes is readable.
    svc.set_day_ritual(day, capacity_minutes=300)
    assert _count(svc, "day_ritual") == 1
    assert svc.open_day(day, create=False)["capacity"] == 300


def test_the_day_tools_advertise_bounds_the_validator_actually_enforces(svc):
    """A schema keyword the validator does not implement is advertised and
    silently unenforced — and these bounds are not cosmetic. An unbounded int
    reaches SQLite as an OverflowError, which is outside the taxonomy the routes
    map and so a 500 rather than a refusal.

    -1 is accepted on a PATCH and refused on a create, and that asymmetry is the
    point: the sentinel CLEARS an estimate, and there is nothing to clear on a
    row that does not exist yet. 0 is a real value on both, which is why the
    clear cannot borrow falsiness.

    test_mcp.py checks the whole registry for unsupported keywords, but it needs
    the scratch server and skips without Docker. The day tools are checked here,
    where it runs."""
    from tasksd.mcp.tools import build_tools
    from tasksd.mcp.validate import SchemaError, check_arguments, unsupported_keywords

    tools = build_tools(McpApi(svc))

    def takes(name: str, args: dict) -> bool:
        try:
            check_arguments(args, tools[name].schema, tool=name)
            return True
        except SchemaError:
            return False

    for name in ("smylte_get_today", "smylte_plan_day", "smylte_update_day_entry",
                 "smylte_review_day"):
        assert not unsupported_keywords(tools[name].schema), name

    assert takes("smylte_update_day_entry", {"entry_id": "x", "estimate_minutes": 0})
    assert takes("smylte_update_day_entry", {"entry_id": "x", "estimate_minutes": -1})
    assert not takes("smylte_update_day_entry", {"entry_id": "x", "estimate_minutes": -2})
    assert not takes("smylte_update_day_entry", {"entry_id": "x", "estimate_minutes": 1441})
    assert takes("smylte_update_day_entry", {"entry_id": "x", "move_to": "2026-08-28"})
    assert not takes("smylte_update_day_entry", {"entry_id": "x", "move_to": "thursday"})

    assert takes("smylte_plan_day", {"title": "x", "estimate_minutes": 0})
    assert not takes("smylte_plan_day", {"title": "x", "estimate_minutes": -1}), (
        "there is nothing to clear on a row that does not exist yet")


def test_an_estimate_given_when_planning_survives_a_retry(mcp_api, svc):
    """The add is idempotent — a task already on the day comes back as the row
    that is there — so without a second write the estimate the model just stated
    would be silently dropped on every retry."""
    day = _live()
    first = mcp_api.plan_day(day=day, list_id="home", uid="someday",
                             estimate_minutes=25)
    assert first["estimate_minutes"] == 25
    again = mcp_api.plan_day(day=day, list_id="home", uid="someday",
                             estimate_minutes=40)
    assert again["entry_id"] == first["entry_id"], "still one row"
    assert again["estimate_minutes"] == 40, "the stated estimate was dropped"


def test_review_day_saturates_at_the_last_representable_day(mcp_api):
    """`_day_or_today` accepts "9999-12-31" because it is a real calendar date,
    and the span computation added a day to it — OverflowError, which is not a
    ValueError, so nothing on this path caught it and the catch-all reported "the
    calendar server may be unreachable" for an argument the calling model chose.

    The same boundary was already fixed twice elsewhere: `find_free_time` breaks
    at `date.max`, and the HTTP event PATCH maps OverflowError to a 422. The HTTP
    twin of this route is unaffected — it was MCP-only."""
    out = mcp_api.review_day(day="9999-12-31")
    assert out is not None
    # The day before still answers the same way, so the clamp did not change the
    # ordinary case into the boundary one.
    assert mcp_api.review_day(day="9999-12-30") is not None
