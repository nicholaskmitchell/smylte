"""The 2026-09-03 sweep, group be-c: the MCP adapter, the notifier, and the
Telegram transport.

Six findings, and what they share is a promise a comment makes that the code
under it does not keep. `find_free_time` says it reports the owner's free hours
and computes them in the server's zone; the digest says it lists "today's
events" and lists four days of all-day ones; `smylte_update_day_entry` reports
success on a call half of which it threw away; `TelegramSender.send` says "Never
raises" and raises; `MAX_LOUD_PER_DAY` says it counts notifications that BUZZ
and counts ledger rows; and the tool table's scope invariant was true by
inspection rather than by test.

Every pin here is in-process — a stub service, or a real `TaskService` over an
in-memory SQLite with a DAV URL that points at a closed port — so nothing
carries `@pytest.mark.radicale`. Where the cheap over-correction is a guard that
refuses everything, the test carries its own CONTROL proving the live path
still works.

The firmware finding from the same group (the panel never re-joins wifi) is
pinned in `test_firmware_example.py`, beside the other contract tests that parse
`main.py` under CPython.

Run just this file with `pytest tests/test_backlog_sep03_mcp_notify.py`.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from helpers import foreign_event_raw

from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import extract_from_raw
from tasksd.mcp.api import McpApi
from tasksd.mcp.oauth import SCOPE_READ, SCOPE_WRITE
from tasksd.mcp.server import McpServer
from tasksd.mcp.tools import ToolError, build_tools
from tasksd.notify import rules as R
from tasksd.notify import telegram as tg
from tasksd.notify.scheduler import MAX_LOUD_PER_DAY, Notifier
from tasksd.service import TaskService

from tests.test_notify_rules import NY, NullLog, StubSender, StubSvc, _event

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

CHICAGO = ZoneInfo("America/Chicago")
CAL = "/u/cal/"


def _offline() -> Settings:
    # The DAV URL points at a closed port on purpose: nothing here may reach the
    # wire, and a test that starts trying will fail rather than hang.
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


@pytest.fixture
def svc():
    s = TaskService(_offline())
    store.upsert_collection(
        s._conn, CollectionInfo(href=CAL, displayname="Cal", components={"VEVENT"})
    )
    yield s
    s.close()


def _seed(svc: TaskService, uid: str, summary: str, **kw) -> None:
    raw = foreign_event_raw(uid, summary, **kw)
    store.upsert_item(svc._conn, CAL, Item(f"{CAL}{uid}.ics", '"1"', raw),
                      extract_from_raw(raw))


@pytest.fixture
def server_in_utc(monkeypatch):
    """The ordinary deployment: the process in UTC, the owner somewhere else.

    Restored on teardown — `monkeypatch` puts the variable back but `tzset` has
    to be called again for the C library to notice.
    """
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


# ── find_free_time: the owner's zone, not the server's ───────────────────────

class _EventsSvc:
    """The narrowest stand-in `find_free_time` needs, WITH a home timezone —
    every existing stub on this path has none, which is exactly why the
    server-local fallback was the only frame the suite ever exercised."""

    def __init__(self, rows, zone="America/Chicago"):
        self._rows = rows
        self._zone = zone

    def get_settings(self):
        return {"home_timezone": self._zone}

    def list_calendars(self):
        return [{"href": CAL, "components": {"VEVENT"}}]

    def events_in_range(self, href, s, e):
        return list(self._rows)

    def resolve_list(self, list_id, component=None):
        return CAL


def _row(uid, start, end):
    return {"uid": uid, "summary": uid, "start": start, "end": end, "duration": None,
            "status": None, "all_day": False, "start_is_date": False,
            "end_is_date": False, "calendar": CAL, "busy": True}


def test_find_free_time_answers_in_the_owners_zone_and_says_so(server_in_utc):
    """With TZ=UTC and home_timezone=America/Chicago: a floating 10:30-11:30
    (the shape this app's own writes produce, read as the OWNER's wall clock
    everywhere else — `scheduling.parse_event_time`, closed #24/#163) and a
    foreign 15:00Z-16:00Z (10:00-11:00 CDT). The owner is busy 10:00-11:30 CDT
    and free 09:00-10:00 and 11:30-17:00.

    Computed in the server's frame the two events sit five hours apart, the
    window covers 04:00-12:00 Chicago, and the answer is naive text a model
    reads as the owner's hours — so it proposes 10:00, which is the middle of
    the meeting. The slots must carry the offset so that reading is not a guess.
    """
    api = McpApi(_EventsSvc([
        _row("floating", "2026-09-08T10:30:00", "2026-09-08T11:30:00"),
        _row("foreign", "2026-09-08T15:00:00+00:00", "2026-09-08T16:00:00+00:00"),
    ]))
    free = api.find_free_time("2026-09-08", "2026-09-09", minutes=30)

    slots = [(datetime.fromisoformat(f["start"]), datetime.fromisoformat(f["end"]))
             for f in free]
    assert all(a.tzinfo is not None and b.tzinfo is not None for a, b in slots), (
        f"slots carry no offset, so 10:00 here is whichever zone the reader "
        f"assumes: {free}"
    )
    local = [(a.astimezone(CHICAGO).strftime("%H:%M"), b.astimezone(CHICAGO).strftime("%H:%M"))
             for a, b in slots]
    assert local == [("09:00", "10:00"), ("11:30", "17:00")], free

    # `_event_order` shares the frame: the floating 10:30 CDT is 15:30Z and
    # genuinely SECOND, but read as 10:30 server time it sorted first — and
    # tools.py pages this list, so `limit: 1` handed the model the later one.
    assert [r["uid"] for r in api.list_events("2026-09-08", "2026-09-09")] == [
        "foreign", "floating"]


def test_find_free_time_without_a_home_zone_still_answers_in_local_time(server_in_utc):
    """CONTROL: an account that never set home_timezone keeps the server-local
    answer every existing test on this path pins, naive text included."""
    api = McpApi(_EventsSvc([_row("m", "2026-09-08T10:00:00", "2026-09-08T11:00:00")],
                            zone=None))
    free = api.find_free_time("2026-09-08", "2026-09-09", minutes=30)
    assert [(f["start"], f["end"]) for f in free] == [
        ("2026-09-08T09:00", "2026-09-08T10:00"),
        ("2026-09-08T11:00", "2026-09-08T17:00"),
    ]


# ── the digest lists TODAY's all-day events ──────────────────────────────────

def _sweep_at(svc, now: datetime) -> R.Sweep:
    tz = svc._home_tz()
    return R.Sweep(svc=svc, now=now, tz=tz, day=now.astimezone(tz).date().isoformat(),
                   prefs=svc.get_settings(), interval_s=60.0)


MORNING = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)   # 07:30 in New York


def test_the_digest_names_only_the_all_day_events_that_fall_on_today(svc):
    """Through the REAL `events_in_range`, not `StubSvc`'s — the stub ignores
    the window, which is why no digest test could see this. `_occurrences`
    widens the SQL bounds by a day on each side and leaves the precise filter
    to Python, and the all-day branch of `_todays_events` never applied it:
    yesterday (with the DTEND every client writes), tomorrow and the day after
    all landed under today's headline, and in its count."""
    svc.update_settings({"home_timezone": "America/New_York",
                         "notify_digest_time": "07:30"})
    _seed(svc, "d0", "YESTERDAY", dtstart="20260830", dtend="20260831", all_day=True)
    _seed(svc, "d1", "TODAY", dtstart="20260831", dtend="20260901", all_day=True)
    _seed(svc, "d2", "TOMORROW", dtstart="20260901", dtend="20260902", all_day=True)
    _seed(svc, "d3", "TWO DAYS OUT", dtstart="20260902", dtend="20260903", all_day=True)

    text = R._digest_text(_sweep_at(svc, MORNING))

    assert text == "Mon 31 Aug: 1 event.\nall day  TODAY", text


def test_a_multi_day_all_day_event_is_still_today_on_its_middle_day(svc):
    """CONTROL for the obvious over-correction (keep only rows whose DTSTART is
    today): a three-day trip that started yesterday IS today's event, and the
    07:30 digest is the one place the owner expects to be reminded of it."""
    svc.update_settings({"home_timezone": "America/New_York",
                         "notify_digest_time": "07:30"})
    _seed(svc, "trip", "Berlin trip", dtstart="20260830", dtend="20260902", all_day=True)
    _seed(svc, "gone", "Ended yesterday", dtstart="20260830", dtend="20260831", all_day=True)

    text = R._digest_text(_sweep_at(svc, MORNING))

    assert text == "Mon 31 Aug: 1 event.\nall day  Berlin trip", text


# ── smylte_update_day_entry: move_to with anything else ──────────────────────

def test_move_to_refuses_the_fields_it_would_otherwise_silently_drop(svc):
    """`move_to` was guarded against `done` and `dropped` only; sent with
    `estimate_minutes` or `position` the call took the roll branch, returned
    the stamped source row, and neither value reached either day. The house
    rule (closed finding on `plan_day`, AUDIT.md: "either sent or refused,
    never silently dropped") is that a stated field is applied or the call is
    refused — a successful reply over a half-applied call is the defect."""
    api = McpApi(svc)
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    svc.open_day(today, create=True)
    entry = svc.add_day_entry(today, entry_id=uuid.uuid4().hex, kind="note",
                              title="Ring the bank", estimate_minutes=10)

    for extra in ({"estimate_minutes": 30}, {"position": 0.5}):
        with pytest.raises(ToolError) as caught:
            api.update_day_entry(entry["entry_id"], day=today, move_to=tomorrow, **extra)
        assert "on its own" in str(caught.value), extra

    # Refused BEFORE anything was written: the source row is not stamped and
    # tomorrow has no copy.
    src = next(e for e in svc.open_day(today, create=False)["entries"]
               if e["entry_id"] == entry["entry_id"])
    assert src["rolled_to"] is None and src["estimate_minutes"] == 10
    assert svc.open_day(tomorrow, create=False)["entries"] == []

    # CONTROL: on its own the move still lands, and the estimate can then be
    # set on the row that arrived.
    moved = api.update_day_entry(entry["entry_id"], day=today, move_to=tomorrow)
    assert moved["rolled_to"] == tomorrow
    landed = svc.open_day(tomorrow, create=False)["entries"]
    assert [e["title"] for e in landed] == ["Ring the bank"]
    assert api.update_day_entry(landed[0]["entry_id"], day=tomorrow,
                                estimate_minutes=30)["estimate_minutes"] == 30


# ── the tool table: every tool that writes needs mcp:write ───────────────────

# The tools a read-only grant may reach, by name. EXPLICIT rather than derived
# from the table, because the likelier slip is not "read_only=False without
# scope=SCOPE_WRITE" — it is a new mutating tool registered with BOTH defaults
# left alone, which the derived invariant cannot see. A new tool has to be
# added here to be callable without write access, and adding it is the moment
# to ask whether it should be.
READ_TOOLS = frozenset({
    "smylte_list_lists", "smylte_list_calendars", "smylte_list_tasks",
    "smylte_get_task", "smylte_search_tasks", "smylte_list_tags",
    "smylte_list_events", "smylte_get_event", "smylte_find_free_time",
    "smylte_list_booking_links", "smylte_list_bookings",
    "smylte_get_today", "smylte_review_day",
})


class _NoSvc:
    """The handlers never run: scope is checked before arguments are read."""


def test_every_tool_outside_the_read_allowlist_needs_write_access():
    """Three layers, because `Tool.scope` and `Tool.read_only` are independent
    defaults and `McpServer._call` consults only the first: the table agrees
    with itself, the table agrees with the allowlist, and the dispatcher
    actually refuses a read-only grant for every write tool — the last is the
    security-relevant one (adversary (3) in the trust model), and 10 of the 18
    write tools had no refusal test at all."""
    api = McpApi(_NoSvc())
    tools = build_tools(api)
    assert READ_TOOLS <= set(tools), "an allowlisted tool no longer exists"

    for t in tools.values():
        assert (t.scope == SCOPE_WRITE) == (not t.read_only), \
            f"{t.name}: scope={t.scope!r} but read_only={t.read_only!r}"
        assert not (t.destructive and t.read_only), f"{t.name}: destructive yet read-only"
        assert (t.name in READ_TOOLS) == (t.scope == SCOPE_READ), \
            f"{t.name}: scope={t.scope!r} disagrees with the read allowlist"

    server = McpServer(api)
    write_tools = [t.name for t in tools.values() if t.name not in READ_TOOLS]
    assert len(write_tools) >= 18
    for name in write_tools:
        reply = server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": {}}},
            scopes={SCOPE_READ},
        )
        assert "write access" in reply.get("error", {}).get("message", ""), (name, reply)


# ── the transport never raises, whatever is in the token ─────────────────────

def test_a_token_with_a_control_character_is_a_recorded_failure_not_a_crash(db):
    """httpx 0.28's `InvalidURL` is not an `HTTPError`, and it is raised for any
    non-printable ASCII in the URL — so a token pasted with an interior tab
    escaped `send()`'s "Never raises" contract. In `_dispatch` that happens
    AFTER every pending row is claimed, so each sweep claimed the day's digest
    and then died, the rows stayed unsettled (read as SENT), and nothing was
    ever delivered until the token was retyped."""
    bad = "123456789:AAH\tpasted-with-a-tab-from-a-chat-window"
    sender = tg.TelegramSender(
        bad, transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True})),
        sleep=lambda _s: None,
    )

    result = sender.send(555, "hello")            # must not raise
    assert result.ok is False and result.permanent is True
    assert result.error and "\t" not in result.error and "AAH" not in result.error

    # And the sweep that adopts that token settles what it claimed.
    svc = StubSvc(db, settings={"notifications_enabled": True, "notify_digest_time": "07:30",
                                "notify_telegram_bot_token": bad,
                                "notify_telegram_chat_id": "555"})
    out = Notifier(svc, sender, "555", log=NullLog(), token="env-token").sweep(MORNING)
    assert out.failed == 1 and out.sent == 0
    row = store.recent_notifications(db)[0]
    assert row["trigger"] == "daily_digest" and row["settled_at"] and row["ok"] == 0
    assert row["error"] and "AAH" not in row["error"]


# ── the loud ceiling counts buzzes, not rows ─────────────────────────────────

def _morning_tier(db, **kw):
    """The documented opt-in morning tier: digest + overdue + unplanned +
    overcommitted, which `_batches` combines into ONE message."""
    tasks = [{"uid": "t1", "summary": "Overdue thing", "due": "2026-08-01",
              "due_is_date": True, "notify_minutes_before": None, "has_rrule": False}]
    return StubSvc(db, settings={"notifications_enabled": True, "notify_digest_time": "07:30",
                                 "notify_triggers": {"task_overdue": True,
                                                     "day_unplanned": True,
                                                     "capacity_overcommitted": True}},
                   tasks=tasks,
                   day={"day": "2026-08-31", "planned": True, "capacity": 60,
                        "committed_at": None, "shutdown_at": None,
                        "entries": [{"kind": "task", "title": "x", "done_at": None,
                                     "dropped_at": None, "rolled_to": None,
                                     "estimate_minutes": 200}]}, **kw)


def _meeting_svc(db, uid: str, start: str):
    return StubSvc(db, settings={"notifications_enabled": True,
                                 "notify_triggers": {"daily_digest": False}},
                   events=[_event(start, summary=f"Meeting {uid}", uid=uid)])


def test_one_batched_buzz_spends_one_slot_of_the_daily_ceiling(db):
    """`MAX_LOUD_PER_DAY` is "the ceiling on notifications that BUZZ" and
    `_batches` promises "only the delivery is combined" — but the persisted
    budget counted ledger rows, and a batch settles one row per OCCASION. So the
    07:30 morning message (four occasions, one buzz) spent four of the eight
    slots, and a meeting alert lost its buzz on a day that had interrupted the
    owner only a handful of times — the very thing the urgency order exists to
    prevent.

    Written first as a strict xfail: the ledger had no column that could say
    which rows one message carried without lying somewhere else — `silent` is
    the field Settings shows the owner as "what the ceiling swallowed",
    `settled_at` collides across separate sends in the same millisecond, and
    the keys are the claim's identity. The honest fix was a `message_id`
    column (the transport's own id, written by `store.settle_notification` for
    every row of a batch) and a count of DISTINCT ids; it landed in the same
    sweep and the marker came off. The other half of the same accounting
    (failed sends spending slots) is pinned below."""
    sender = StubSender()
    n = Notifier(_morning_tier(db), sender, "555", log=NullLog(), token="env-token")
    assert n.sweep(MORNING).sent == 4 and len(sender.sent) == 1, "one buzz, four rows"

    midnight = Notifier._local_midnight(MORNING, NY)
    from tasksd.notify.scheduler import loud_deliveries_since
    assert db.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0] == 4
    assert loud_deliveries_since(db, midnight) == 1

    # Fill the day to one slot short of the ceiling, counting that batch as the
    # ONE interruption it was. The next meeting alert is the eighth buzz of
    # the day and keeps it; charged per row it would have been the eleventh.
    for i in range(MAX_LOUD_PER_DAY - 2):
        store.claim_notification(db, "filler", f"f{i}")
        store.settle_notification(db, "filler", f"f{i}", ok=True, silent=False)
    late = StubSender()
    at_13 = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    out = Notifier(_meeting_svc(db, "m1", "2026-08-31T13:08:00"), late, "555",
                   log=NullLog(), token="env-token").sweep(at_13)
    assert out.sent == 1 and out.downgraded == 0
    assert late.sent[0]["silent"] is False, "the eighth buzz of the day is still a buzz"

    # CONTROL: the ninth is not.
    later = StubSender()
    out = Notifier(_meeting_svc(db, "m2", "2026-08-31T14:08:00"), later, "555",
                   log=NullLog(), token="env-token").sweep(at_13 + timedelta(hours=1))
    assert out.downgraded == 1 and later.sent[0]["silent"] is True


def test_a_loud_send_telegram_refused_spends_no_slot(db):
    """The other half of the same accounting: the in-sweep counter charges a
    buzz only `if outcome.ok`, but a failed loud send still settled as a
    `silent=0` row and was charged on every later sweep."""
    for i in range(MAX_LOUD_PER_DAY):
        refused = StubSender(ok=False)
        Notifier(_meeting_svc(db, f"r{i}", "2026-08-31T07:38:00"), refused, "555",
                 log=NullLog(), token="env-token").sweep(MORNING)
        assert refused.sent and store.recent_notifications(db)[0]["ok"] == 0

    sender = StubSender()
    out = Notifier(_meeting_svc(db, "real", "2026-08-31T07:38:00"), sender, "555",
                   log=NullLog(), token="env-token").sweep(MORNING)
    assert out.sent == 1 and out.downgraded == 0
    assert sender.sent[0]["silent"] is False, \
        "eight refusals are not eight interruptions"
