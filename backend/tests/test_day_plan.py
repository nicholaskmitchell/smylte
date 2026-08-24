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

def test_snapshot_takes_due_today_and_overdue_as_auto(svc):
    """The two automatic rules, and the four exclusions that go with them.

    Due-today and overdue are what the day is *about*; everything else has to
    stay out, or the Today tab becomes a second copy of the task list. A
    completed task is not work, a subtask rides with its parent (one parent
    would otherwise drag its whole checklist in), a task due next week belongs
    to next week, and undated work is something the owner picks rather than
    something a snapshot decides for them."""
    plan = svc.open_day(DAY, create=True)
    assert _uids(plan) == ["due-today", "late"]      # due-today first, then late
    assert {e["source"] for e in plan["entries"]} == {"auto"}
    assert all(e["kind"] == "task" for e in plan["entries"])
    # The list SHORT id, never the href — the client only ever holds short ids.
    assert [e["list"] for e in plan["entries"]] == ["work", "home"]
    # A dense ascending sequence: every row of the snapshot gets a position, so
    # the day's order never rests on a tie-break.
    assert [e["position"] for e in plan["entries"]] == [1.0, 2.0]
    assert all(e["done_at"] is None and e["dropped_at"] is None for e in plan["entries"])


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
    ones do not. An auto entry re-derives itself from the wire every morning (it
    is still due, or still late), so carrying it as well would give the task two
    rows on one day. A hand-added entry has no such second source — drop it and
    the decision is simply lost."""
    svc.open_day(PREV, create=True)
    assert _uids(svc.open_day(PREV, create=False)) == ["late"]   # auto, from DUE
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
    # PREV's auto entry is not carried — it arrives on its own merits instead,
    # as an overdue task, and exactly once.
    assert _uids(plan).count("late") == 1
    assert [e["source"] for e in plan["entries"] if e["uid"] == "late"] == ["auto"]


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
    assert _count(svc, "day_plan") == 2          # the auto entry plus this one

    plan = svc.open_day(DAY, create=True)
    assert not [e for e in plan["entries"] if e["source"] == "carried"]
    assert "later" not in _uids(plan)


# ── the first write is not always the open ───────────────────────────────────

def test_a_hand_added_day_still_gets_its_snapshot(svc):
    """A day whose FIRST write is an add is snapshotted all the same.

    `add_day_entry` used to mark the day opened, and `open_day` skipped the
    snapshot for any day that already held entries — so a single hand-added row
    suppressed that day's due-today, overdue and carried entries permanently.
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
    assert _uids(plan) == ["due-today", "late"]
    assert [e["source"] for e in plan["entries"]] == ["user", "auto", "auto"]
    # The hand-added row keeps its place and its id: a snapshot arriving late
    # lands BEHIND the arrangement it is joining rather than renumbering it.
    assert plan["entries"][0]["entry_id"] == note["entry_id"]
    assert [e["position"] for e in plan["entries"]] == [1.0, 2.0, 3.0]
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
    assert _uids(plan) == ["due-today", "late"]
    # The OWNER's row is the one that survives — same entry_id the client is
    # already holding, still source=user, so it still carries into tomorrow.
    kept = [e for e in plan["entries"] if e["uid"] == "due-today"][0]
    assert (kept["entry_id"], kept["source"]) == (picked["entry_id"], "user")

    # A DROPPED row counts as present too. Re-proposing something the owner
    # dropped minutes earlier is exactly the resurrection the opened marker
    # exists to prevent — the row being dropped is not an invitation to add it
    # back, it is the decision not to.
    gone = svc.add_day_entry(PREV, entry_id=uuid.uuid4().hex, kind="task",
                             list_id="home", uid="late")
    svc.patch_day_entry(PREV, gone["entry_id"], dropped=True)
    prev = svc.open_day(PREV, create=True)          # "late" is overdue on PREV
    assert _uids(prev) == ["late"]
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
    svc.open_day(DAY, create=True)
    dto = svc.add_day_entry(DAY, entry_id="jot", kind="note", title="Ring the bank")
    svc.patch_day_entry(DAY, dto["entry_id"], estimate_minutes=10)
    # Nothing to write through to, and nothing written: a note names no task.
    assert store.get_sidecar(svc._conn, LIST_A, "due-today") is None


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
    r = client.get(f"/api/day/{day}")
    assert r.status_code == 200 and r.json() == {"day": day, "planned": False, "entries": []}

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
