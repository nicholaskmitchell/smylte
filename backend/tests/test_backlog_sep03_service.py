"""The 2026-09-03 sweep, group be-b1: the service layer, the SQLite store and
`due.py`.

Twelve findings share these files and nothing else: an FTS query whose cost was
quadratic in its term count and reachable from the least-privileged MCP grant; a
whole-series edit that wrote an occurrence's absolute end onto the master; a day
entry that could be rolled onto no day at all; a deadline at the end of the
calendar that took down every task read; a sync outage the notifier could not
see; a reminder lost in a calendar move; an estimate the task never learned; a
day key below the carry look-back that answered 500; a phantom booking
confirmed for a time no event occupies; a bookings list in wall-clock rather
than chronological order; and two guards that were correct but unpinned (a link
whose calendar another CalDAV client deleted, and the `init_db` ALTER
migrations).

Every pin here is in-process. The series edit and the move drive the real
`SyncEngine` against a write-capable DAV double (the same shape
`test_backlog_aug25_stage3.py` introduced), the search pin goes through the
real `McpServer` with a read-only scope, and everything else is `SmylteService`
over an in-memory cache. Nothing needs the scratch Radicale, so nothing here
carries `@pytest.mark.radicale`.

Where the cheap over-correction is "refuse everything", a CONTROL sits beside
the pin — the two-word search still finds things, a series reschedule that
carries its start still moves, and a one-off event with an end-only edit still
takes it.

Run just this file with `pytest tests/test_backlog_sep03_service.py`.
"""
from __future__ import annotations

import time as time_mod
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from helpers import foreign_event_raw, foreign_raw

from smylted import ical
from smylted import due
from smylted.config import Settings
from smylted.dav.client import CollectionInfo, Item
from smylted.dav.errors import DavError, NotFound, PreconditionFailed
from smylted.db import store
from smylted.ical import extract_from_raw
from smylted.ical.edit import EventEdit
from smylted.mcp.api import McpApi, _intrinsic_order
from smylted.mcp.server import INVALID_PARAMS, McpServer
from smylted.mcp.tools import SCOPE_READ
from smylted.notify import rules as R
from smylted.service import SmylteService
from smylted.sync import ConflictError, SyncEngine

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

CAL_A, CAL_B = "/u/meetings/", "/u/personal/"
LIST_A = "/u/work/"
TZ = ZoneInfo("America/Chicago")
# A Monday morning, link-local (CDT, -05:00).
NOW = datetime(2026, 7, 13, 8, 0, tzinfo=TZ)


def _settings(**over) -> Settings:
    # The DAV URL points at a closed port on purpose: nothing in this file may
    # reach the wire, and a test that starts trying fails rather than hangs.
    fields = dict(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )
    fields.update(over)
    return Settings(**fields)


def _cache(conn, href: str, uid: str, raw: bytes) -> None:
    store.upsert_item(conn, href, Item(f"{href}{uid}.ics", '"1"', raw), extract_from_raw(raw))


def _task(conn, href: str, uid: str, summary: str, *, due_date: str | None = None) -> None:
    extra = (f"DUE;VALUE=DATE:{due_date.replace('-', '')}",) if due_date else ()
    _cache(conn, href, uid, foreign_raw(uid, summary, extra=extra))


@pytest.fixture
def svc():
    s = SmylteService(_settings())
    for href, name, comps in ((CAL_A, "Meetings", {"VEVENT"}), (CAL_B, "Personal", {"VEVENT"}),
                              (LIST_A, "Work", {"VTODO"})):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components=comps))
    yield s
    s.close()


class _FakeDav:
    """A write-capable DAV double: `{href: (etag, bytes)}`. The engine's edit
    path needs GET, PUT-with-If-Match and DELETE, and nothing else."""

    def __init__(self, initial: dict[str, bytes] | None = None):
        self.store: dict[str, tuple[str, bytes]] = {
            h: ('"1"', b) for h, b in (initial or {}).items()}
        self.rev = 1

    def get(self, href):
        if href not in self.store:
            raise NotFound(f"GET {href} -> 404")
        etag, data = self.store[href]
        return Item(href=href, etag=etag, data=data)

    def put(self, href, data, *, if_match=None, if_none_match=None):
        if if_none_match == "*" and href in self.store:
            raise PreconditionFailed(f"PUT {href} -> 412")
        if if_match is not None and href in self.store and self.store[href][0] != if_match:
            raise PreconditionFailed(f"PUT {href} -> 412")
        self.rev += 1
        etag = f'"{self.rev}"'
        self.store[href] = (etag, data if isinstance(data, bytes) else data.encode())
        return etag

    def delete(self, href, *, if_match=None):
        self.store.pop(href, None)

    def close(self):
        pass


def _with_fake_dav(svc: SmylteService, initial: dict[str, bytes]) -> _FakeDav:
    """Swap the service's engine for one over the double, caching `initial`."""
    dav = _FakeDav(initial)
    svc._engine = SyncEngine(dav, svc._conn)
    for href, raw in initial.items():
        col = href.rsplit("/", 1)[0] + "/"
        uid = extract_from_raw(raw).uid
        _cache(svc._conn, col, uid, raw)
    return dav


def _rpc(server: McpServer, name: str, args: dict, *, scopes=frozenset({SCOPE_READ})) -> dict:
    return server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }, scopes=set(scopes))


# ── #1  search: the query's length was unbounded and its cost quadratic ──────

def test_a_1mb_search_query_is_refused_before_the_lock(svc, monkeypatch):
    """`smylte_search_tasks.query` had `minLength` and no `maxLength`, and
    POST /mcp accepts a 1 MB body. `store.search` turns every whitespace token
    into an FTS5 prefix phrase and the MATCH is quadratic in the term count on
    an EMPTY table (10k terms 0.09 s, 40k 3.0 s, 500k — what fits the body cap —
    nine minutes), all of it under the one global service lock, from a grant
    holding only mcp:read.

    Pinned at the door: the schema refuses the argument, so `store.search` is
    never reached and the lock is never taken. The sentinel is what makes this
    a pin rather than a timing test — before the fix the query went straight
    through to FTS."""
    reached = []

    def sentinel(conn, query):
        reached.append(len(query))
        return []

    monkeypatch.setattr("smylted.service.store.search", sentinel)
    server = McpServer(McpApi(svc))
    reply = _rpc(server, "smylte_search_tasks", {"query": "a " * 500_000})

    assert not reached, "a 1 MB query reached store.search"
    refused = ("error" in reply and reply["error"]["code"] == INVALID_PARAMS) or (
        reply.get("result", {}).get("isError") is True)
    assert refused, reply
    text = reply["error"]["message"] if "error" in reply else reply["result"]["content"][0]["text"]
    assert "query" in text and "at most" in text, text


def test_store_search_cannot_be_handed_a_pathological_match(svc):
    """Defence in depth below the schema: no caller — the HTTP twin, a future
    tool, a direct import — can build a MATCH whose cost is quadratic in what
    it typed. 100k terms on an empty index used to take ~22 s."""
    t0 = time_mod.perf_counter()
    rows = store.search(svc._conn, "a " * 100_000)
    elapsed = time_mod.perf_counter() - t0
    assert rows == []
    assert elapsed < 1.0, f"store.search took {elapsed:.2f}s on a 100k-term query"


def test_an_ordinary_two_word_search_still_finds_things(svc):
    """CONTROL. The cheap over-correction refuses every query; the live path
    has to keep working through the same door the pin drives."""
    _task(svc._conn, LIST_A, "t-proj", "Project meeting notes")
    _task(svc._conn, LIST_A, "t-other", "Buy milk")
    server = McpServer(McpApi(svc))
    reply = _rpc(server, "smylte_search_tasks", {"query": "proj mee"})
    assert reply["result"]["isError"] is False, reply
    hits = reply["result"]["structuredContent"]["tasks"]
    assert [t["uid"] for t in hits] == ["t-proj"]
    # And every term still narrows: a word the task does not carry excludes it.
    reply = _rpc(server, "smylte_search_tasks", {"query": "proj zzz"})
    assert reply["result"]["structuredContent"]["tasks"] == []


# ── #2  edit_event: end-only + scope=all + recurrence_id corrupted the series ─

WEEKLY = foreign_event_raw(
    "wk", "Standup", dtstart="20260105T100000", dtend="20260105T103000", rrule="FREQ=WEEKLY",
)


def _september(svc) -> list[tuple[str, str]]:
    occ = svc.events_in_range(CAL_A, "2026-09-01", "2026-09-30")
    return sorted((e["start"], e["end"]) for e in occ if e["uid"] == "wk")


def test_an_end_only_edit_of_a_whole_series_does_not_stretch_every_occurrence(svc):
    """The scope=all dispatch recognised a time change only through `dtstart`,
    so an edit carrying just `dtend` — "extend every standup to 11:00",
    anchored on one occurrence — fell through to the master edit, which wrote
    the OCCURRENCE's absolute end as the master DTEND. A weekly 10:00-10:30
    series from January became a series of eight-month-long events: the
    September window went from 4 occurrences to 39, and the public booking
    page saw the owner busy for the rest of the year.

    `shift_series` cannot express an end-only reschedule (it measures its
    delta from the new start), so the honest answer is a refusal that says
    what to send — a ValueError the routes map to 422 and the MCP tool to a
    ToolError — and, above all, an UNCHANGED series."""
    _with_fake_dav(svc, {f"{CAL_A}wk.ics": WEEKLY})
    before = _september(svc)
    assert len(before) == 4

    with pytest.raises(ValueError, match="start"):
        svc.edit_event(CAL_A, "wk", EventEdit(dtend=datetime(2026, 9, 7, 11, 0)),
                       recurrence_id="2026-09-07T10:00:00", scope="all")

    assert _september(svc) == before
    assert svc.get_event(CAL_A, "wk")["end"] == "2026-01-05T10:30:00"


def test_a_series_reschedule_that_carries_its_start_still_moves_and_resizes(svc):
    """CONTROL for the arm the pin lives in: the same edit with `dtstart`
    beside `dtend` is the shape the SPA sends, and it must keep going through
    `shift_series` — every occurrence 60 minutes long, still four of them."""
    _with_fake_dav(svc, {f"{CAL_A}wk.ics": WEEKLY})
    svc.edit_event(CAL_A, "wk",
                   EventEdit(dtstart=datetime(2026, 9, 7, 10, 0), dtend=datetime(2026, 9, 7, 11, 0)),
                   recurrence_id="2026-09-07T10:00:00", scope="all")
    after = _september(svc)
    assert len(after) == 4
    for start, end in after:
        assert datetime.fromisoformat(end) - datetime.fromisoformat(start) == timedelta(hours=1)


def test_an_end_only_edit_of_a_one_off_event_is_still_taken(svc):
    """CONTROL. A one-off event has no series to stretch: its DTEND IS the
    absolute end the caller named, with or without a `recurrence_id` naming
    its own start (which `smylte_list_events` hands out on every row)."""
    single = foreign_event_raw("one", "Lunch", dtstart="20260907T120000", dtend="20260907T123000")
    _with_fake_dav(svc, {f"{CAL_A}one.ics": single})
    svc.edit_event(CAL_A, "one", EventEdit(dtend=datetime(2026, 9, 7, 13, 0)),
                   recurrence_id="2026-09-07T12:00:00", scope="all")
    assert svc.get_event(CAL_A, "one")["end"] == "2026-09-07T13:00:00"


# ── #3  day plan: rolling back to the origin day stranded the work ───────────

def _today() -> str:
    return date.today().isoformat()


def _live(svc, day: str) -> list[dict]:
    return [e for e in svc.open_day(day, create=False)["entries"] if not e["rolled_to"]]


def test_rolling_an_entry_back_to_the_day_it_came_from_lands_it_there(svc):
    """`add_day_entry`'s idempotency lookup skipped DROPPED rows but not
    ROLLED ones, so rolling tomorrow's copy back to today "landed" on today's
    inert rolled-away row, then stamped the copy too — both rows carried
    `rolled_to`, and the work was live on no day at all. Every reader
    (`_resolved_day_rows`, the carry, the Today tab, the focus queue) skips
    rolled rows, so it simply vanished while reporting success."""
    _task(svc._conn, LIST_A, "t1", "Write the report")
    today, tomorrow = _today(), (date.today() + timedelta(days=1)).isoformat()
    e1 = svc.add_day_entry(today, entry_id="e1", kind="task", list_id="work", uid="t1")
    svc.roll_entry(today, e1["entry_id"], tomorrow)
    (e2,) = svc.open_day(tomorrow, create=False)["entries"]

    svc.roll_entry(tomorrow, e2["entry_id"], today)

    live_today = _live(svc, today)
    assert [e["uid"] for e in live_today] == ["t1"], (
        "rolling back to the origin day stranded the task on no day")
    assert _live(svc, tomorrow) == []
    # The original row keeps its record — it went to tomorrow — and the copy
    # records that it came back. Nothing is rewritten, one live row exists.
    rows = {r["entry_id"]: r["rolled_to"]
            for r in svc.open_day(today, create=False)["entries"]}
    assert rows["e1"] == tomorrow and len(rows) == 2


def test_a_task_rolled_off_a_day_can_be_added_to_that_day_again(svc):
    """The other half: re-adding a task the day rolled away used to answer
    with the inert rolled row and insert nothing, unlike a DROPPED task, which
    is addable again. `smylte_plan_day` on such a task reported success and
    planned nothing."""
    _task(svc._conn, LIST_A, "t1", "Write the report")
    today, tomorrow = _today(), (date.today() + timedelta(days=1)).isoformat()
    e1 = svc.add_day_entry(today, entry_id="e1", kind="task", list_id="work", uid="t1")
    svc.roll_entry(today, e1["entry_id"], tomorrow)

    again = svc.add_day_entry(today, entry_id="e3", kind="task", list_id="work", uid="t1")
    assert again["rolled_to"] is None and again["entry_id"] == "e3"
    assert [e["uid"] for e in _live(svc, today)] == ["t1"]


def test_a_repeated_roll_still_lands_once(svc):
    """CONTROL for the idempotency the lookup exists for: a retried roll to a
    day that holds the LIVE copy finds it and adds nothing."""
    _task(svc._conn, LIST_A, "t1", "Write the report")
    today, tomorrow = _today(), (date.today() + timedelta(days=1)).isoformat()
    e1 = svc.add_day_entry(today, entry_id="e1", kind="task", list_id="work", uid="t1")
    svc.roll_entry(today, e1["entry_id"], tomorrow)
    svc.roll_entry(today, e1["entry_id"], tomorrow)
    assert len(svc.open_day(tomorrow, create=False)["entries"]) == 1


# ── #4  booking link whose calendar another CalDAV client deleted ────────────

def _make_link(svc, **over) -> str:
    fields = dict(
        title="Chat", description=None, calendar_href=CAL_A, duration_minutes=60,
        timezone="America/Chicago", availability={"0": ["09:00-17:00"]},
        show_busy=True, buffer_minutes=0, min_notice_hours=0, horizon_days=1,
        enabled=True,
    )
    fields.update(over)
    return svc.create_booking_link(fields)["token"]


def test_a_link_whose_calendar_was_deleted_elsewhere_is_unbookable(svc):
    """An ordinary passing test, written because its subject was correct but
    unpinned. `_link_is_live` is `enabled AND has_collection`; the app's own
    DELETE route flips `enabled`, and the only test on this subject drives
    that route, so it is satisfied by the `enabled` half alone. A calendar
    deleted by Tasks.org or Thunderbird reaches the cache through the sync
    sweep's `mark_collection_deleted`, which leaves `enabled=1` — and with the
    `has_collection` half removed the link advertised slots and `book_slot`
    raised the engine's "collection /u/meetings/ is unknown" ValueError, which
    the public route answers verbatim as a 422 to an anonymous caller."""
    token = _make_link(svc)
    assert svc.public_link_info(token, now=NOW) is not None

    store.mark_collection_deleted(svc._conn, CAL_A)            # what a sync sweep does

    assert svc.public_link_info(token, now=NOW) is None
    assert svc.book_slot(token, start_iso="2026-07-13T09:00:00-05:00",
                         name="V", email="v@x.co", now=NOW) is None
    dto = svc.list_booking_links_one(token)
    assert dto["calendar_missing"] is True


# ── #5  init_db: the ALTER migrations nothing exercised ──────────────────────

def test_an_older_database_gains_the_cache_and_token_columns(tmp_path):
    """An ordinary passing test for six ALTERs no test ran: every test DB is
    created fresh, so `CREATE TABLE IF NOT EXISTS` supplies every column and
    the `if "<col>" not in cols` guards are always false. Deleting any of them
    was green across the suite while 500ing every task and event read
    (`_task_dto`/`_event_dto` read the missing key off a sqlite3.Row —
    IndexError, unmapped) or every token exchange on an upgraded database.

    Hand-built pre-column tables, the way the day_plan migration tests are,
    so it keeps testing the upgrade rather than a fixture that ages out."""
    conn = store.connect(str(tmp_path / "old.db"))
    conn.executescript(
        """CREATE TABLE collections (
               href TEXT PRIMARY KEY, displayname TEXT NOT NULL,
               components TEXT NOT NULL DEFAULT 'VTODO', color TEXT,
               deleted INTEGER NOT NULL DEFAULT 0,
               updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')));
           INSERT INTO collections (href, displayname, components) VALUES ('/u/w/', 'W', 'VTODO,VEVENT');
           CREATE TABLE items (
               collection_href TEXT NOT NULL REFERENCES collections(href) ON DELETE CASCADE,
               uid TEXT NOT NULL, href TEXT NOT NULL, etag TEXT NOT NULL,
               raw_ics BLOB NOT NULL, component TEXT NOT NULL DEFAULT 'VTODO',
               summary TEXT, description TEXT, status TEXT, priority INTEGER,
               percent_complete INTEGER, completed TEXT, due TEXT,
               due_is_date INTEGER NOT NULL DEFAULT 0, dtstart TEXT,
               dtstart_is_date INTEGER NOT NULL DEFAULT 0, dtend TEXT,
               dtend_is_date INTEGER NOT NULL DEFAULT 0, duration TEXT,
               related_parent TEXT, sequence INTEGER, has_rrule INTEGER NOT NULL DEFAULT 0,
               location TEXT, created TEXT, last_modified TEXT,
               synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
               PRIMARY KEY (collection_href, uid));
           INSERT INTO items (collection_href, uid, href, etag, raw_ics, component, summary)
           VALUES ('/u/w/', 'old-task', '/u/w/old-task.ics', '"1"', X'00', 'VTODO', 'Legacy task');
           INSERT INTO items (collection_href, uid, href, etag, raw_ics, component, summary, dtstart, dtend)
           VALUES ('/u/w/', 'old-ev', '/u/w/old-ev.ics', '"1"', X'00', 'VEVENT', 'Legacy event',
                   '2026-01-06T09:00:00', '2026-01-06T09:30:00');
           CREATE TABLE sidecar (
               collection_href TEXT NOT NULL, uid TEXT NOT NULL, kanban_column TEXT,
               sort_order REAL, pinned INTEGER NOT NULL DEFAULT 0, estimated_minutes INTEGER,
               repeat_from_completion INTEGER NOT NULL DEFAULT 0, orphaned_at TEXT,
               updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
               PRIMARY KEY (collection_href, uid));
           INSERT INTO sidecar (collection_href, uid, pinned) VALUES ('/u/w/', 'old-task', 1);
           CREATE TABLE oauth_tokens (
               token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
               scope TEXT NOT NULL, resource TEXT NOT NULL, family_id TEXT NOT NULL,
               used_at REAL, expires_at REAL NOT NULL, created_at REAL NOT NULL);
           INSERT INTO oauth_tokens (token_hash, kind, client_id, scope, resource, family_id,
                                     expires_at, created_at)
           VALUES ('h1', 'access', 'c1', 'mcp:read', 'https://x/mcp', 'f1', 9e9, 1);"""
    )
    store.init_db(conn)
    store.init_db(conn)                                       # idempotent

    cols = lambda t: {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}  # noqa: E731
    assert "ord" in cols("collections")
    assert {"transp", "min_instant", "fts_rowid"} <= cols("items")
    # The pair too, and both names rather than one: they ship under a single
    # `if` (store.py reads `side_cols` once), so a half-applied migration would
    # leave the flag missing on a database that has the date, and every
    # remembered deadline would render as midnight.
    assert {"notify_minutes_before", "parked_at",
            "original_due", "original_due_is_date", "original_due_moved"} <= cols("sidecar")
    assert "cv" in cols("oauth_tokens")

    # The real readers, over the legacy rows — which is the whole point.
    svc = SmylteService(_settings(db_path=str(tmp_path / "unused.db")))
    try:
        cats = store.get_all_categories(conn, "/u/w/")
        side = store.get_all_sidecar(conn, "/u/w/")
        ev = svc._event_dto(store.get_item(conn, "/u/w/", "old-ev"), cats, side)
        assert ev["busy"] is True                           # absent TRANSP is OPAQUE
        assert ev["notify_minutes_before"] is None
        task = svc._task_dto(store.get_item(conn, "/u/w/", "old-task"), cats, side, {})
        assert task["notify_minutes_before"] is None and task["pinned"] is True
        # NULL on a legacy row is "this one has not missed a deadline" — the
        # only answer available, since the date a task was moved off is not
        # recoverable from anything left on the row.
        assert task["original_due"] is None
        assert task["original_due_is_date"] is False
        assert task["original_due_moved"] is False
    finally:
        svc.close()
    assert store.get_oauth_token(conn, "h1")["cv"] == ""
    assert [r["href"] for r in store.get_collections(conn)] == ["/u/w/"]
    # One upsert on the legacy row gives it an FTS rowid, and the new token
    # INSERT names `cv`.
    _task(conn, "/u/w/", "old-task", "Legacy task, resynced")
    assert store.get_item(conn, "/u/w/", "old-task")["fts_rowid"] is not None
    store.create_oauth_token(conn, token_hash="h2", kind="access", client_id="c1",
                             scope="mcp:read", resource="https://x/mcp", family_id="f2",
                             expires_at=9e9, now=1, cv="v1")
    assert store.get_oauth_token(conn, "h2")["cv"] == "v1"
    conn.close()


def test_a_database_that_remembers_deadlines_gains_why_they_were_left(tmp_path):
    """Every deployed database already has the `original_due` pair, so the
    ALTER adding `original_due_moved` must not sit behind the pair's own guard:
    those databases would never gain it, and every read of a task with a
    remembered deadline would 500 (`_task_dto` reads the missing key off a
    sqlite3.Row). The test above starts before the pair existed and so cannot
    tell. Built as the previous release left it: today's schema minus the new
    column, holding a remembered deadline."""
    conn = store.connect(str(tmp_path / "prev.db"))
    store.init_db(conn)
    conn.execute("ALTER TABLE sidecar DROP COLUMN original_due_moved")
    store.upsert_collection(
        conn, CollectionInfo(href="/u/w/", displayname="W", components={"VTODO"}))
    _task(conn, "/u/w/", "late", "Late one", due_date="2099-03-11")
    conn.execute("INSERT INTO sidecar (collection_href, uid, original_due, original_due_is_date)"
                 " VALUES ('/u/w/', 'late', '2020-03-11', 1)")
    cols = lambda: {r["name"] for r in conn.execute("PRAGMA table_info(sidecar)")}  # noqa: E731
    assert "original_due_moved" not in cols()

    store.init_db(conn)

    assert "original_due_moved" in cols()
    svc = SmylteService(_settings(db_path=str(tmp_path / "unused.db")))
    try:
        task = svc._task_dto(store.get_item(conn, "/u/w/", "late"),
                             store.get_all_categories(conn, "/u/w/"),
                             store.get_all_sidecar(conn, "/u/w/"), {})
        # Late, which is what the app recorded it as when it was written.
        assert (task["original_due"], task["original_due_moved"]) == ("2020-03-11", False)
    finally:
        svc.close()
    conn.close()


# ── #6  sync_all: an outage after boot recorded no error ─────────────────────

def test_a_full_outage_after_boot_is_recorded_where_the_notifier_looks(svc):
    """`sync_all` called `discover()` with no try, and discovery is the first
    network call — so when Radicale went down after startup the exception
    left before the per-collection loop, `store.set_sync_error` was never
    reached, `sync_health()` stayed empty, and the one notifier rule written
    for "everything on screen looks normal and the data is simply frozen"
    never fired. Only `bootstrap()` recorded it, i.e. only if smylted happened
    to restart during the outage."""
    store.set_sync_token(svc._conn, CAL_A, "t0")
    stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    svc._conn.execute("UPDATE sync_state SET last_sync_at=? WHERE collection_href=?",
                      (stale, CAL_A))

    for _ in range(3):
        svc.sync_all()                       # the loop's every-30-seconds call

    health = svc.sync_health()
    assert [r["collection_href"] for r in health] == [CAL_A, CAL_B, LIST_A][:len(health)]
    assert CAL_A in {r["collection_href"] for r in health}, "the outage left no trace"
    assert all(r["last_error"] for r in health)

    sweep = R.Sweep(svc=svc, now=datetime.now(timezone.utc), tz=None,
                    day=_today(), prefs={}, interval_s=60)
    pending = R._eval_sync_stalled(sweep)
    assert len(pending) == 1 and "Meetings" in pending[0].text


# ── #7  due_parts: a deadline at the end of the calendar raised ──────────────

@pytest.mark.parametrize("zone", [ZoneInfo("America/Chicago"), None], ids=["zoned", "unzoned"])
def test_a_deadline_at_the_end_of_the_calendar_is_a_deadline_not_a_crash(zone):
    """`due_parts` is documented "soft on purpose" for cached values, but only
    the parse was soft: `date(9999, 12, 31) + timedelta(days=1)` raises
    OverflowError, and with no home zone the `.astimezone()` in `instant_in`
    raises ValueError first. `_intrinsic_order` is the sort key applied to every
    row of every `smylte_list_tasks` call, so one "someday" task another client
    wrote took down the whole tool, and the daily digest and task_overdue rules
    that share the function silently stopped."""
    parts = due.due_parts("9999-12-31", zone)
    if parts is not None:
        due_at, overdue_at = parts
        assert overdue_at >= due_at
        assert overdue_at > datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()
    rows = [{"uid": "someday", "due": "9999-12-31", "summary": "Someday"},
            {"uid": "soon", "due": "2026-09-10", "summary": "Soon"},
            {"uid": "undated", "summary": "Whenever"}]
    ordered = [t["uid"] for t in sorted(rows, key=lambda t: _intrinsic_order(t, zone))]
    # The sort no longer raises, and a real deadline still leads the far one.
    assert ordered[0] == "soon" and ordered.index("someday") < ordered.index("undated") + 1


def test_an_ordinary_deadline_still_expires_at_the_end_of_its_day():
    """CONTROL: the day is still added as wall clock for every representable
    date, so nothing about the guard changes the app's overdue rule."""
    zone = ZoneInfo("America/Chicago")
    due_at, overdue_at = due.due_parts("2026-09-10", zone)
    assert due_at == datetime(2026, 9, 10, tzinfo=zone).timestamp()
    assert overdue_at - due_at == 24 * 3600


# ── #8  move_event: the reminder stayed on the orphaned source sidecar ───────

def test_a_moved_event_keeps_its_reminder(svc):
    """The sidecar is keyed on (collection_href, uid) and the engine's move
    orphans the SOURCE row, so the event's app-only `notify_minutes_before` —
    deliberately not a VALARM, so nothing on the wire restores it — stayed
    behind and the destination started empty. The move answered 200 with a
    null reminder and the item-reminder rule never fired for it again."""
    raw = foreign_event_raw("mv", "Dentist", dtstart="20260907T120000", dtend="20260907T123000")
    _with_fake_dav(svc, {f"{CAL_A}mv.ics": raw})
    svc.set_event_sidecar(CAL_A, "mv", notify_minutes_before=30)
    assert svc.get_event(CAL_A, "mv")["notify_minutes_before"] == 30

    moved = svc.move_event(CAL_A, CAL_B, "mv")

    assert moved["notify_minutes_before"] == 30
    assert svc.get_event(CAL_B, "mv")["notify_minutes_before"] == 30
    assert svc.get_event(CAL_A, "mv") is None


# ── moving a task to another list: what a failure part-way leaves ────────────
# The move is one resource at a time, copy then delete, so each of these is a
# real state the owner can be left in. In every one, a retry has to finish the
# job, and what already moved has to be announced and carry its refs.

LIST_B = "/dav/me/home/"


class _FlakyDav(_FakeDav):
    """The double, with one failure armed at a time: a request that never
    lands (`fail_*`), one that lands and loses its answer (`lose_*`), or a
    source DELETE refused because the source changed (`delete_412`)."""

    def __init__(self, initial):
        super().__init__(initial)
        self.fail_delete = False
        self.fail_get = None
        self.fail_put = None
        self.lose_put_reply = None
        self.lose_delete_reply = False
        self.delete_412 = False

    def get(self, href):
        if href == self.fail_get:
            self.fail_get = None
            raise DavError(f"GET {href}: connection reset")
        return super().get(href)

    def put(self, href, data, **kw):
        if href == self.fail_put:
            self.fail_put = None
            raise DavError(f"PUT {href}: connection reset")
        etag = super().put(href, data, **kw)
        if href == self.lose_put_reply:
            self.lose_put_reply = None
            raise DavError(f"PUT {href}: read timeout")
        return etag

    def delete(self, href, *, if_match=None):
        if self.fail_delete:
            self.fail_delete = False
            raise DavError(f"DELETE {href}: connection reset")
        if self.delete_412:
            self.delete_412 = False
            raise PreconditionFailed(f"DELETE {href} -> 412")
        if if_match is not None and href in self.store and self.store[href][0] != if_match:
            raise PreconditionFailed(f"DELETE {href} -> 412")
        super().delete(href, if_match=if_match)
        if self.lose_delete_reply:
            self.lose_delete_reply = False
            raise DavError(f"DELETE {href}: read timeout")


def _sync_copy(svc, dav, href):
    """What the 30 s sync does with a resource that appeared on the wire."""
    item = dav.get(href)
    store.upsert_item(svc._conn, href.rsplit("/", 1)[0] + "/", item, extract_from_raw(item.data))


def _two_lists(svc, initial):
    store.upsert_collection(
        svc._conn, CollectionInfo(href=LIST_B, displayname="Home", components={"VTODO"}))
    dav = _FlakyDav(initial)
    svc._engine = SyncEngine(dav, svc._conn)
    for href, raw in initial.items():
        _cache(svc._conn, href.rsplit("/", 1)[0] + "/", extract_from_raw(raw).uid, raw)
    published = []
    svc._publish = published.append
    return dav, published


def test_a_task_move_whose_source_delete_failed_can_be_retried(svc):
    """The copy landed, the DELETE failed, and the next sync cached the copy in
    the destination. The retry recognises that copy as its own, because it
    says what the source does, and finishes; otherwise the task would stay in
    both lists for good."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1)
    dav.fail_delete = True
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    _sync_copy(svc, dav, f"{LIST_B}t1.ics")

    moved = svc.move_task(LIST_A, LIST_B, "t1")

    assert moved["pinned"] is True
    assert sorted(dav.store) == [f"{LIST_B}t1.ics"]
    assert svc.get_task(LIST_A, "t1") is None


@pytest.mark.parametrize("synced", [False, True])
def test_a_task_move_whose_copy_reply_was_lost_can_be_retried(svc, synced):
    """The PUT of the copy landed and its answer did not. The retry finds the
    copy in place, saying what the source does, whether or not a sync has
    cached it meanwhile."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    dav.lose_put_reply = f"{LIST_B}t1.ics"
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    if synced:
        _sync_copy(svc, dav, f"{LIST_B}t1.ics")

    svc.move_task(LIST_A, LIST_B, "t1")

    assert sorted(dav.store) == [f"{LIST_B}t1.ics"]


def test_a_subtask_moved_alone_can_be_retried_though_each_attempt_restamps_it(svc):
    """A subtask moved on its own is rewritten without its parent, and every
    write renews DTSTAMP, LAST-MODIFIED and SEQUENCE, so no two attempts write
    the same bytes. The comparison ignores those stamps, or the retry would
    refuse the move's own copy and the task would be wedged in both lists."""
    dav, _ = _two_lists(svc, {
        f"{LIST_A}p.ics": foreign_raw("p", "Trip"),
        f"{LIST_A}c.ics": foreign_raw("c", "Charger", extra=("RELATED-TO;RELTYPE=PARENT:p",)),
    })
    dav.fail_delete = True
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "c")
    _sync_copy(svc, dav, f"{LIST_B}c.ics")
    time_mod.sleep(1.1)                       # a later second, so the stamps differ

    moved = svc.move_task(LIST_A, LIST_B, "c")

    assert moved["parent"] is None
    assert sorted(dav.store) == sorted([f"{LIST_A}p.ics", f"{LIST_B}c.ics"])


def test_a_task_move_whose_delete_reply_was_lost_finishes_at_once(svc):
    """The source DELETE landed and its answer did not. The engine asks the
    server, finds the source gone, and finishes, and the refs follow."""
    dav, published = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1)
    dav.lose_delete_reply = True

    moved = svc.move_task(LIST_A, LIST_B, "t1")

    assert moved["pinned"] is True
    assert sorted(dav.store) == [f"{LIST_B}t1.ics"]
    assert ("task_created", "t1") in {(e["type"], e["uid"]) for e in published}


def test_a_retry_after_a_lost_delete_answer_finishes_the_move(svc):
    """The DELETE's answer was lost and so was the question asked after it, so
    the move raised with the task really moved. The retry finds the source
    gone and its copy in place, saying what the cached source did, and does
    Smylte's half: the refs follow."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1)
    dav.lose_delete_reply = True
    real_get, calls = dav.get, {"n": 0}

    def get(href):                            # the probe after the lost answer fails
        if href == f"{LIST_A}t1.ics":
            calls["n"] += 1
            if calls["n"] == 2:
                raise DavError(f"GET {href}: connection reset")
        return real_get(href)
    dav.get = get
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")

    moved = svc.move_task(LIST_A, LIST_B, "t1")

    assert moved["pinned"] is True
    assert svc.get_task(LIST_A, "t1") is None


def _lose_delete_answer_and_probe(dav):
    """The source DELETE lands, its answer is lost, and so is the question
    asked after it, so the move raises with the task really moved."""
    dav.lose_delete_reply = True
    real_get, calls = dav.get, {}

    def get(href):
        if href.startswith(LIST_A):
            calls[href] = calls.get(href, 0) + 1
            if calls[href] == 2:
                raise DavError(f"GET {href}: connection reset")
        return real_get(href)
    dav.get = get


def _sync_tick(svc, dav, *hrefs):
    """What the 30 s sync does once the sources left the old list: drop each
    row and orphan its sidecar, and cache the copies in the new list."""
    for href in hrefs:
        uid = href.rsplit("/", 1)[-1].removesuffix(".ics")
        store.delete_item_by_href(svc._conn, LIST_A, f"{LIST_A}{uid}.ics")
        store.orphan_sidecar(svc._conn, LIST_A, uid)
        _sync_copy(svc, dav, href)


def test_a_move_that_lost_every_answer_is_not_finished_after_a_sync(svc):
    """The one case left unrecovered, on purpose. Every answer was lost and a
    sync then ran, so the task is in the new list and its Smylte data is
    orphaned in the old one. Nothing proves the task in the new list is this
    one (a UID does not), so the retry is a 404 and changes nothing."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1)
    _lose_delete_answer_and_probe(dav)
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    _sync_tick(svc, dav, f"{LIST_B}t1.ics")

    with pytest.raises(KeyError):
        svc.move_task(LIST_A, LIST_B, "t1")
    assert svc.get_task(LIST_B, "t1") is not None


def test_a_stale_move_of_a_deleted_task_never_touches_another_with_its_uid(svc):
    """The reason for the case above. A task deleted from the old list leaves
    its Smylte data orphaned there, and a different task with the same UID can
    live in the new list. A move request that arrives late, from a stale tab
    or an agent working from an old listing, must not pour the deleted task's
    data onto that other task, or take that task's own."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack"),
                              f"{LIST_B}t1.ics": foreign_raw("t1", "Groceries")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1, estimated_minutes=15)
    store.set_sidecar(svc._conn, LIST_B, "t1", notify_minutes_before=5, kanban_column="mine")
    svc._conn.execute("INSERT INTO day_plan (day, entry_id, kind, collection_href, uid, source) "
                      "VALUES ('2026-10-30', 'e1', 'task', ?, 't1', 'user')", (LIST_A,))
    svc.delete_task(LIST_A, "t1")

    with pytest.raises(KeyError):
        svc.move_task(LIST_A, LIST_B, "t1")
    theirs = svc.get_task(LIST_B, "t1")
    assert (theirs["summary"], theirs["notify_minutes_before"], theirs["pinned"]) == (
        "Groceries", 5, False)
    assert svc._conn.execute("SELECT collection_href FROM day_plan WHERE entry_id='e1'"
                             ).fetchone()[0] == LIST_A


def test_what_was_set_on_the_copy_in_the_meantime_is_kept(svc):
    """The first attempt left the copy, so the task showed in both lists, and
    the owner set a reminder on the copy and parked it there. The retry
    accepts the copy, and the copy's own Smylte data survives, merged with
    the source's (its pin and estimate)."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1, estimated_minutes=15,
                      notify_minutes_before=60)
    dav.fail_delete = True
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    _sync_copy(svc, dav, f"{LIST_B}t1.ics")
    svc.set_sidecar(LIST_B, "t1", notify_minutes_before=30)
    svc.park_task(LIST_B, "t1", parked=True)

    moved = svc.move_task(LIST_A, LIST_B, "t1")

    assert moved["notify_minutes_before"] == 30, "the copy's own reminder"
    assert moved["parked"] is True
    assert (moved["pinned"], moved["estimated_minutes"]) == (True, 15)


@pytest.mark.parametrize("synced", [False, True])
@pytest.mark.parametrize("first", ["delete_failed", "put_reply_lost"])
def test_a_copy_edited_since_the_failed_move_is_not_overwritten(svc, first, synced):
    """The first attempt left the copy in place, so the task showed in both
    lists, and the owner edited the copy. Repeating the move must not put the
    source's bytes over that edit. The copy no longer says what the source
    does, so the move is refused and both stay for the owner to settle."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    if first == "delete_failed":
        dav.fail_delete = True
    else:
        dav.lose_put_reply = f"{LIST_B}t1.ics"
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    edited = foreign_raw("t1", "Pack the charger too")
    dav.put(f"{LIST_B}t1.ics", edited)
    if synced:
        _sync_copy(svc, dav, f"{LIST_B}t1.ics")

    for _ in range(2):
        with pytest.raises(ConflictError):
            svc.move_task(LIST_A, LIST_B, "t1")
    assert dav.store[f"{LIST_B}t1.ics"][1] == edited
    assert f"{LIST_A}t1.ics" in dav.store


def test_a_source_edited_since_the_failed_move_is_not_lost_either(svc):
    """The other way round: another client edited the source after the first
    attempt left a copy. The copy is older, so it is not this move's to keep,
    and overwriting it would need to know nobody edited it. The move is
    refused, with both versions still there."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    dav.fail_delete = True
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    newer = foreign_raw("t1", "Pack, and the charger")
    dav.put(f"{LIST_A}t1.ics", newer)
    _cache(svc._conn, LIST_A, "t1", newer)

    with pytest.raises(ConflictError):
        svc.move_task(LIST_A, LIST_B, "t1")
    assert dav.store[f"{LIST_A}t1.ics"][1] == newer
    assert f"{LIST_B}t1.ics" in dav.store


def test_a_copy_this_attempt_wrote_is_undone_with_its_cached_row(svc):
    """The source changed during the move, so the copy this attempt wrote is
    undone, cached row and all, and the retry the error asks for goes straight
    through instead of reading the undone copy as a clash."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    dav.delete_412 = True
    with pytest.raises(ConflictError, match="changed during the move"):
        svc.move_task(LIST_A, LIST_B, "t1")
    assert f"{LIST_B}t1.ics" not in dav.store
    assert svc.get_task(LIST_B, "t1") is None

    svc.move_task(LIST_A, LIST_B, "t1")
    assert sorted(dav.store) == [f"{LIST_B}t1.ics"]


def test_a_copy_an_earlier_attempt_left_is_not_undone(svc):
    """Found in place rather than written now, the copy may be an identical
    twin that was there before any move, so a 412 on the source leaves it be.
    The task stays as it was before this attempt, and the retry finishes."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    dav.fail_delete = True
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    _sync_copy(svc, dav, f"{LIST_B}t1.ics")
    dav.delete_412 = True
    with pytest.raises(ConflictError, match="changed during the move"):
        svc.move_task(LIST_A, LIST_B, "t1")
    assert f"{LIST_B}t1.ics" in dav.store and f"{LIST_A}t1.ics" in dav.store

    svc.move_task(LIST_A, LIST_B, "t1")
    assert sorted(dav.store) == [f"{LIST_B}t1.ics"]


def test_a_task_already_in_the_destination_under_another_name_is_a_clash(svc):
    """Not our copy: the precheck refuses before anything is written."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    elsewhere = foreign_raw("t1", "Pack, elsewhere")
    dav.store[f"{LIST_B}other.ics"] = ('"1"', elsewhere)
    store.upsert_item(svc._conn, LIST_B, Item(f"{LIST_B}other.ics", '"1"', elsewhere),
                      extract_from_raw(elsewhere))
    with pytest.raises(ConflictError):
        svc.move_task(LIST_A, LIST_B, "t1")
    assert sorted(dav.store) == sorted([f"{LIST_A}t1.ics", f"{LIST_B}other.ics"])


@pytest.mark.parametrize("before", ["nothing", "refused_put"])
def test_a_same_uid_task_at_the_same_filename_is_never_overwritten(svc, before):
    """Smylte names a task's file after its UID, so a different task with the
    same UID in the destination sits exactly where the move would write. Not
    cached yet, it gets past the precheck; the engine must still refuse it,
    every time, however earlier attempts ended (one whose PUT was refused
    outright used to leave a record that made the next attempt adopt it)."""
    dav, _ = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    if before == "refused_put":
        dav.fail_put = f"{LIST_B}t1.ics"
        with pytest.raises(DavError):
            svc.move_task(LIST_A, LIST_B, "t1")
    twin = foreign_raw("t1", "Someone else's task")
    dav.store[f"{LIST_B}t1.ics"] = ('"1"', twin)
    for _ in range(2):
        with pytest.raises(ConflictError):
            svc.move_task(LIST_A, LIST_B, "t1")
    assert dav.store[f"{LIST_B}t1.ics"][1] == twin
    assert f"{LIST_A}t1.ics" in dav.store


def test_a_task_move_that_fails_part_way_announces_what_moved(svc):
    """The subtask moves first and the parent's copy then fails. The subtask
    really is in the new list, so it is announced (nothing else would tell a
    client), and a retry brings the parent across to rejoin it."""
    dav, published = _two_lists(svc, {
        f"{LIST_A}p.ics": foreign_raw("p", "Trip"),
        f"{LIST_A}c.ics": foreign_raw("c", "Charger", extra=("RELATED-TO;RELTYPE=PARENT:p",)),
    })
    dav.fail_put = f"{LIST_B}p.ics"
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "p")
    assert {(e["type"], e["uid"]) for e in published} == {
        ("task_deleted", "c"), ("task_created", "c")}
    assert svc.get_task(LIST_B, "c") is not None and svc.get_task(LIST_A, "p") is not None

    svc.move_task(LIST_A, LIST_B, "p")
    assert svc.get_task(LIST_B, "p")["children"] == ["c"]
    assert sorted(dav.store) == [f"{LIST_B}c.ics", f"{LIST_B}p.ics"]


def test_a_task_move_whose_reread_fails_still_moves_what_smylte_keeps(svc):
    """Copy and delete both landed and only the re-read of the copy failed.
    The task has moved, so its sidecar moves too, rather than sitting orphaned
    in the old list until GC deletes it; the next sync caches the copy."""
    dav, published = _two_lists(svc, {f"{LIST_A}t1.ics": foreign_raw("t1", "Pack")})
    store.set_sidecar(svc._conn, LIST_A, "t1", pinned=1, estimated_minutes=20)
    dav.fail_get = f"{LIST_B}t1.ics"
    with pytest.raises(DavError):
        svc.move_task(LIST_A, LIST_B, "t1")
    side = store.get_sidecar(svc._conn, LIST_B, "t1")
    assert (side["pinned"], side["estimated_minutes"], side["orphaned_at"]) == (1, 20, None)
    assert store.get_sidecar(svc._conn, LIST_A, "t1") is None
    assert ("task_created", "t1") in {(e["type"], e["uid"]) for e in published}


# ── #9  add_day_entry: a stated estimate never taught the task ───────────────

def test_an_estimate_stated_when_a_task_is_added_is_what_the_next_day_starts_from(svc):
    """`patch_day_entry` writes a task entry's estimate through to the sidecar
    ("estimating a task also teaches the task"); `add_day_entry` copied a stated
    estimate onto the row and taught nothing. `smylte_plan_day` is the one
    shipped caller that states one on create, and its description promises the
    next day "starts at whatever the same task took last time" — true only if
    the number arrived through a PATCH or a retry."""
    _task(svc._conn, LIST_A, "t1", "Write the report")
    today, tomorrow = _today(), (date.today() + timedelta(days=1)).isoformat()
    svc.add_day_entry(today, entry_id="e1", kind="task", list_id="work", uid="t1",
                      estimate_minutes=45)
    assert store.get_sidecar(svc._conn, LIST_A, "t1")["estimated_minutes"] == 45

    later = svc.add_day_entry(tomorrow, entry_id="e2", kind="task", list_id="work", uid="t1")
    assert later["estimate_minutes"] == 45


# ── #10  open_day: a day within the carry look-back of 0001-01-01 answered 500

@pytest.mark.parametrize("day", ["0001-01-15", "0001-01-01"])
def test_a_day_below_the_carry_lookback_opens_without_overflowing(svc, day):
    """`_carry_into` subtracted 30 days from the day key; for a real calendar
    date before 0001-01-31 that is an OverflowError, which no route maps — a
    500 where every other bad day key answers 422, on POST /api/day/{day}/open
    and on `preview_day`. Saturated at the calendar's floor, the same way
    `review_day` clamps at its ceiling."""
    assert svc.preview_day(day) == []
    assert svc.open_day(day, create=True)["planned"] is True


# ── #11  book_slot: a client_id whose event sits at another instant ──────────

def _orphan(svc, cid: str) -> None:
    raw = foreign_event_raw(f"{cid}@tasksd", "Chat — Visitor",
                            dtstart="20260713T140000Z", dtend="20260713T150000Z")
    _cache(svc._conn, CAL_A, f"{cid}@tasksd", raw)


def _stub_create(svc):
    def fake(href, summary, *, dtstart, dtend=None, edit=None, client_id=None):
        return {"uid": f"{client_id or 'x'}@tasksd"}
    svc.create_event = fake


def test_a_client_id_whose_event_sits_at_another_instant_is_refused(svc):
    """`_recover_orphaned_booking`'s docstring: "Anything else falls through
    to the 'client_id already used' refusal below". It did not — an instant
    mismatch returned None, `book_slot` treated None as "no prior booking" and
    went on to a fresh create, and the engine's `_put_new` treats a 412 whose
    occupant carries the same UID as success without writing. The result was a
    ledger row, a charged ceiling and a 201 for a time no event occupies."""
    t_a, t_b = _make_link(svc, title="Link A"), _make_link(svc, title="Link B")
    cid = "c" * 32
    _orphan(svc, cid)                          # PUT landed at 09:00 local, no ledger row
    _stub_create(svc)

    with pytest.raises(ValueError, match="client_id already used"):
        svc.book_slot(t_b, start_iso="2026-07-13T15:00:00-05:00",
                      name="Mallory", email="m@x.co", client_id=cid, now=NOW)
    with pytest.raises(ValueError, match="client_id already used"):
        svc.book_slot(t_a, start_iso="2026-07-13T15:00:00-05:00",
                      name="Visitor", email="v@x.co", client_id=cid, now=NOW)
    assert svc.list_bookings() == []


def test_a_same_instant_retry_still_recovers_its_own_booking(svc):
    """CONTROL for the recovery the hook exists for: the visitor's page keeps
    the client_id stable for the chosen slot, so a retry names the orphan's
    instant and is answered from it — not created, not charged."""
    token = _make_link(svc, title="Link A")
    cid = "c" * 32
    _orphan(svc, cid)
    _stub_create(svc)
    confirmation, created = svc.book_slot(
        token, start_iso="2026-07-13T09:00:00-05:00",
        name="Visitor", email="v@x.co", client_id=cid, now=NOW)
    assert created is False
    assert confirmation["start"] == "2026-07-13T09:00:00-05:00"
    assert [b["event_uid"] for b in svc.list_bookings()] == [f"{cid}@tasksd"]


# ── Smylte rename: booking replay must survive BOTH uid suffixes ────────────

def _orphan_with(svc, cid: str, suffix: str) -> None:
    uid = f"{cid}{suffix}"
    raw = foreign_event_raw(uid, "Chat — Visitor",
                           dtstart="20260713T140000Z", dtend="20260713T150000Z")
    _cache(svc._conn, CAL_A, uid, raw)


@pytest.mark.parametrize("suffix", [ical.UID_SUFFIX, ical.UID_SUFFIX_LEGACY])
def test_booking_replay_is_found_under_either_uid_suffix(svc, suffix):
    """`_recover_orphaned_booking` rebuilds the event UID from the visitor's
    client_id rather than reading it back, so it has to know how UIDs are spelt
    — and after the tasksd -> smylted rename there are two spellings in the
    wild. A booking made before the rename carries the old one and is only
    findable under it; one made after carries the new.

    Getting this wrong is not a cosmetic bug. An unfound replay is not treated
    as "no booking": `book_slot` refuses it with "client_id already used", or
    goes on to create a second event for a visitor who already holds the slot.
    The other tests in this file all build their orphan with the legacy suffix,
    so without this the new spelling — the one every future booking uses — has
    no coverage at all."""
    token = _make_link(svc, title="Link A")
    cid = "c" * 32
    _orphan_with(svc, cid, suffix)

    def fake(href, summary, *, dtstart, dtend=None, edit=None, client_id=None):
        return {"uid": f"{client_id or 'x'}{suffix}"}
    svc.create_event = fake

    confirmation, created = svc.book_slot(
        token, start_iso="2026-07-13T09:00:00-05:00",
        name="Visitor", email="v@x.co", client_id=cid, now=NOW)
    assert created is False, "the replay was treated as a fresh booking"
    assert confirmation["start"] == "2026-07-13T09:00:00-05:00"
    assert [b["event_uid"] for b in svc.list_bookings()] == [f"{cid}{suffix}"]


# ── #12  list_bookings: ordered by the offset-bearing string ─────────────────

def test_bookings_from_links_in_different_zones_list_in_chronological_order(svc):
    """`bookings.start_at` is written WITH the link's own offset and the store
    did `ORDER BY start_at` — a string compare, i.e. wall-clock order. A
    09:00-07:00 booking (16:00Z) listed before a 10:00+02:00 one (08:00Z) in
    Settings > Bookings and in the first page of `smylte_list_bookings`."""
    la = _make_link(svc, title="LA", timezone="America/Los_Angeles")
    be = _make_link(svc, title="Berlin", timezone="Europe/Berlin")
    store.insert_booking(svc._conn, id="la1", link_token=la, calendar_href=CAL_A,
                         event_uid="la1@tasksd", client_name="A", client_email="a@x.co",
                         notes=None, start_at="2026-09-04T09:00:00-07:00",
                         end_at="2026-09-04T10:00:00-07:00")
    store.insert_booking(svc._conn, id="be1", link_token=be, calendar_href=CAL_A,
                         event_uid="be1@tasksd", client_name="B", client_email="b@x.co",
                         notes=None, start_at="2026-09-04T10:00:00+02:00",
                         end_at="2026-09-04T11:00:00+02:00")
    # And the single-zone variant: across a fall-back the offset changes
    # within one link, so 01:00-08:00 (09:00Z) string-sorts before 01:30-07:00.
    store.insert_booking(svc._conn, id="dst2", link_token=la, calendar_href=CAL_A,
                         event_uid="dst2@tasksd", client_name="C", client_email="c@x.co",
                         notes=None, start_at="2026-11-01T01:00:00-08:00",
                         end_at="2026-11-01T02:00:00-08:00")
    store.insert_booking(svc._conn, id="dst1", link_token=la, calendar_href=CAL_A,
                         event_uid="dst1@tasksd", client_name="D", client_email="d@x.co",
                         notes=None, start_at="2026-11-01T01:30:00-07:00",
                         end_at="2026-11-01T02:30:00-07:00")

    assert [b["id"] for b in svc.list_bookings()] == ["be1", "la1", "dst1", "dst2"]
    assert [b["id"] for b in svc.list_bookings(la)] == ["la1", "dst1", "dst2"]


# ── the booking-link DTO: an absolute URL for "Copy link" ────────────────────

def test_a_booking_link_carries_its_absolute_url_when_the_deployment_knows_its_origin():
    """The Windows client's "Copy link" needs an absolute URL and only has the
    token; `settings.public_url` is the one place the deployment's origin is
    configured (config.py normalizes it, no trailing slash)."""
    s = SmylteService(_settings(public_url="https://tasks.example.test"))
    try:
        store.upsert_collection(
            s._conn, CollectionInfo(href=CAL_A, displayname="Meetings", components={"VEVENT"}))
        link = s.list_booking_links_one(_make_link(s))
        assert link["url"] == f"https://tasks.example.test/book/{link['token']}"
        assert [l["url"] for l in s.list_booking_links()] == [link["url"]]
    finally:
        s.close()


def test_a_booking_link_has_no_url_when_the_origin_is_not_configured(svc):
    link = svc.list_booking_links_one(_make_link(svc))
    assert "url" in link and link["url"] is None


# ── the display DTO: the same absolute URL, for the same client ─────────────

def test_a_display_carries_its_absolute_url_when_the_deployment_knows_its_origin():
    """Filed during remediation: the display row had the defect "Copy link" was
    fixed for — inside the Windows client `location.origin` is localhost. The
    url rides only with the token, since a frame must not carry its credential."""
    s = SmylteService(_settings(public_url="https://tasks.example.test"))
    try:
        d = s.create_display({"name": "Hallway", "mode": "calendar"})
        assert d["url"] == f"https://tasks.example.test/display/{d['token']}"
        assert "url" not in s.display_frame(d["token"])["display"]
    finally:
        s.close()


def test_a_display_has_no_url_when_the_origin_is_not_configured(svc):
    d = svc.create_display({"name": "Hallway", "mode": "calendar"})
    assert "url" in d and d["url"] is None
