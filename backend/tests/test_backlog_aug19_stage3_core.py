"""The 2026-08-19 sweep, stage 3: silent wrong results in the core.

The dangerous class again, and this time it is spread across every layer that
answers a question: the service, the SQLite projection, the MCP adapter and the
HTTP routes. Nothing raises, nothing is logged, the status code is 200 — and the
answer is wrong. A page that is an arbitrary subset of the truth, a booking that
becomes two, an occurrence that is invisible to the grid *and* to the
double-booking check, a task written into a calendar where no reader will ever
find it again, a connections screen naming a capability the grant no longer has.

**These findings are OPEN.** Unlike test_backlog_stage1.py … stage5.py — which
are closed and carry no markers — every test here is an `xfail(strict=True)`
pin: it asserts the CORRECTED behaviour and fails against the code as it stands.
CI stays green while the bug is open and goes red the moment it is fixed. See
docs/STAGES.md for the harness and why that second half is the point.

Every pin is behavioural. Each drives the real service, the real store query,
the real tool handler or the real HTTP route and asserts the answer a caller
receives — never the shape of the source, because a pin that only accepts the
repair its author imagined is not a regression test. Where a finding names two
acceptable repairs, the assertion is written to be satisfied by both: what is
pinned is the outcome the caller is owed, not the branch that delivers it.

Run just this file with

    SCRATCH_STORAGE=... pytest tests/test_backlog_aug19_stage3_core.py -rxX
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import re
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
import time
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tasksd import scheduling
from tasksd.app import create_app
from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.dav.errors import DavError
from tasksd.db import store
from tasksd.ical import extract_from_raw
from tasksd.mcp.api import McpApi
from tasksd.mcp.server import McpServer
from tasksd.mcp.tools import build_tools
from tasksd.service import TaskService
from tests.conftest import api_settings
from tests.helpers import foreign_event_raw

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]


# ── harnesses ───────────────────────────────────────────────────────────────

def _offline_settings() -> Settings:
    """Settings pointed at a port nothing listens on.

    The pins below that use it never reach CalDAV: they exercise the SQLite
    projection and the pure-Python layers above it, which is where each of those
    findings lives. Same shape test_service_unit.py uses.
    """
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


class _StubService:
    """The narrowest stand-in for TaskService that `McpApi.list_tasks` needs:
    the lists it fans out over, and the rows in each. Everything about ordering
    happens above this line, in `_display_order` and the sort in list_tasks."""

    def __init__(self, tasks: dict[str, list[dict]]):
        self._tasks = tasks

    def list_lists(self):
        return [{"href": h} for h in self._tasks]

    def list_tasks(self, href, *, include_done=True):
        return list(self._tasks[href])


def _task(uid, *, due=None, sort_order=None, summary=None):
    return {"uid": uid, "summary": summary or uid, "due": due,
            "sort_order": sort_order, "priority": None, "tags": [],
            "completed": False, "cancelled": False}


# The connector's own app, with no session cookie anywhere — the same shape
# test_mcp.py uses, kept local so the two files cannot drift into each other.
ISSUER = "https://tasks.example.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "testpass123"


@pytest.fixture
def mcp_app(_scratch_up, tmp_path):
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "mcp-aug19.db")),
        mcp_enabled=True, public_url=ISSUER,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _connect(client) -> dict:
    """Register, consent with the owner's password, exchange the PKCE code —
    the whole happy path a Claude custom connector performs, so the pins below
    start from a grant the server itself minted."""
    reg = client.post("/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
    })
    assert reg.status_code == 201, reg.text
    reg = reg.json()

    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    page = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "xyz",
        "scope": "mcp:read mcp:write offline_access", "resource": f"{ISSUER}/mcp",
    })
    assert page.status_code == 200, page.text
    signed = re.search(r'name="request" value="([^"]+)"', page.text).group(1)
    redirect = client.post("/oauth/authorize", data={
        "request": signed, "action": "approve", "grant": "full",
        "username": "admin", "password": PASSWORD}, follow_redirects=False)
    code = parse_qs(urlsplit(redirect.headers["location"]).query)["code"][0]

    r = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
        "client_id": reg["client_id"], "code_verifier": verifier,
        "resource": f"{ISSUER}/mcp"})
    assert r.status_code == 200, r.text
    return {"reg": reg, **r.json()}


# ── AUDIT: _display_order copies compareTasks, the comparator order.ts names
#          as NOT how a list is ordered ──────────────────────────────────────

def test_a_task_created_after_a_drag_is_not_sunk_below_the_whole_account():
    """`_display_order` sorts `(order is None, order or 0)` first — nulls LAST.
    Its docstring says it mirrors `frontend/src/order.ts`, but order.ts exports
    two comparators and this is the one order.ts documents as wrong: `compareTasks`
    says of itself "this is NOT how a list is ordered — see `sortTasks`, which is
    what every view calls".

    The difference is the whole finding. One drag renumbers the entire account
    (ReorderTasks: "nothing left null once a drag lands"), so afterwards a null
    position means "created since the last drag" — from smylte_create_task, or
    from DAVx5/Tasks.org, whose tasks can never carry one at all. Sinking those
    below every placed task is what `sortTasks` exists to avoid, and this is the
    ONE thing deciding which rows `page()` slices into the model's first page:
    with 200 placed tasks and limit=50, tomorrow's deadline is never seen.
    docs/AUDIT.md already closed this once on the frontend; this is the same
    defect reintroduced on the MCP surface.

    Asserted as the user-visible outcome — the soonest deadline is on the first
    page — so any correct port of `sortTasks` satisfies it, whatever shape it
    takes.
    
    **Fixed** by porting `sortTasks` instead of `compareTasks` — the effective-
    position algorithm, not the pairwise comparator, because order.ts explains
    that the pairwise form is not transitive across the placed/unplaced boundary
    (P1 pos 1 due Dec, P2 pos 2 due Jan, U due Jun gives P1 < P2 < U < P1) and
    sorting on an inconsistent comparator is undefined. `due` is now parsed to an
    instant rather than compared lexically, mirroring `dueAt`, and `_title_key`
    reproduces `localeCompare`'s tertiary case rule.

    The port was cross-checked by RUNNING order.ts over 402 generated task sets
    and comparing outputs; a sample of those is pinned below as
    `CROSS_CHECKED`, since CI has no node.
    """
    placed = [_task(f"placed-{i}", due=f"2027-12-{i:02d}", sort_order=i)
              for i in range(1, 21)]
    unplaced = _task("pay-tax-bill", due="2026-08-20", summary="Pay tax bill")
    api = McpApi(_StubService({"/u/inbox/": [*placed, unplaced]}))

    rows = api.list_tasks(include_done=True)
    first_page = [r["uid"] for r in rows[:5]]

    assert "pay-tax-bill" in first_page, (
        f"the only task due this year is at position {rows.index(unplaced) + 1} "
        f"of {len(rows)}, below every manually placed task; the first page is "
        f"{first_page}. A model asked \"what's due next?\" never sees it."
    )


# The oracle for the port above, and the reason it can be trusted across two
# languages: `frontend/src/order.ts` was RUN over 402 generated task sets —
# random dues (date-only and timed), priorities including 0, titles differing
# only by case, duplicate and gapped sort_orders, a uid copied into a second list
# in 40% of them, and two degenerate sets where every task is identical but for
# its list — and the Python port reproduced its output on all 402. These eight
# are the ones that exercise the most.
#
# They discriminate: with the pre-fix uid-only keying (finding 22, which the port
# inherited) the corpus drops to 300/402.
#
# Pinned as a table rather than as a live cross-check because CI has no node.
# Regenerate by running order.ts over the cases if the comparator ever changes;
# if these ever disagree, order.ts is right and this port is wrong.
# (tasks, expected order as 'list/uid') — produced by RUNNING order.ts.
CROSS_CHECKED = [
    (
        [
            {'uid': 'u00', 'list': 'home', 'sort_order': 2.0, 'due': '2026-01-05', 'priority': None, 'summary': 'Beta'},
            {'uid': 'u01', 'list': 'inbox', 'sort_order': None, 'due': '2026-01-05T00:00', 'priority': None, 'summary': 'Alpha'},
            {'uid': 'u02', 'list': 'inbox', 'sort_order': 100.0, 'due': '2027-03-03T18:30', 'priority': 5, 'summary': 'gamma'},
            {'uid': 'u03', 'list': 'work', 'sort_order': 1.0, 'due': '2026-06-01T09:00', 'priority': 1, 'summary': 'alpha'},
            {'uid': 'u04', 'list': 'work', 'sort_order': 100.0, 'due': '2026-06-01T09:00', 'priority': 9, 'summary': 'gamma'},
            {'uid': 'u05', 'list': 'inbox', 'sort_order': 7.0, 'due': '2026-01-05T00:00', 'priority': None, 'summary': 'Beta'},
            {'uid': 'u06', 'list': 'home', 'sort_order': 1.0, 'due': '2026-01-05T00:00', 'priority': 5, 'summary': ''},
            {'uid': 'u07', 'list': 'home', 'sort_order': 7.0, 'due': '2027-03-03T18:30', 'priority': 9, 'summary': 'alpha'},
            {'uid': 'u05', 'list': 'work', 'sort_order': 1.0, 'due': '2026-01-05T00:00', 'priority': None, 'summary': 'Beta'},
        ],
        ['home/u06', 'inbox/u01', 'work/u05', 'work/u03', 'home/u00', 'inbox/u05', 'home/u07', 'work/u04', 'inbox/u02'],
    ),
    (
        [
            {'uid': 'u00', 'list': 'home', 'sort_order': 100.0, 'due': '2026-12-31', 'priority': 0, 'summary': 'Beta'},
            {'uid': 'u01', 'list': 'work', 'sort_order': 2.5, 'due': '2026-01-05T00:00', 'priority': 9, 'summary': ''},
            {'uid': 'u02', 'list': 'inbox', 'sort_order': 100.0, 'due': '2026-01-05T00:00', 'priority': None, 'summary': 'Alpha'},
            {'uid': 'u03', 'list': 'inbox', 'sort_order': None, 'due': '2027-03-03T18:30', 'priority': None, 'summary': 'alpha'},
            {'uid': 'u04', 'list': 'home', 'sort_order': 100.0, 'due': '2026-01-05', 'priority': None, 'summary': 'Beta'},
            {'uid': 'u04', 'list': 'inbox', 'sort_order': 100.0, 'due': '2026-01-05', 'priority': None, 'summary': 'Beta'},
        ],
        ['work/u01', 'inbox/u02', 'home/u04', 'inbox/u04', 'home/u00', 'inbox/u03'],
    ),
    (
        [
            {'uid': 'u00', 'list': 'home', 'sort_order': 7.0, 'due': None, 'priority': 0, 'summary': 'gamma'},
            {'uid': 'u01', 'list': 'home', 'sort_order': 2.0, 'due': None, 'priority': 1, 'summary': None},
            {'uid': 'u02', 'list': 'inbox', 'sort_order': 7.0, 'due': None, 'priority': 1, 'summary': ''},
            {'uid': 'u03', 'list': 'inbox', 'sort_order': 1.0, 'due': '2026-12-31', 'priority': None, 'summary': 'Alpha'},
            {'uid': 'u04', 'list': 'work', 'sort_order': None, 'due': '2027-03-03T18:30', 'priority': 9, 'summary': ''},
            {'uid': 'u05', 'list': 'home', 'sort_order': 7.0, 'due': '2026-12-31', 'priority': 9, 'summary': 'Beta'},
            {'uid': 'u06', 'list': 'inbox', 'sort_order': 2.0, 'due': None, 'priority': 9, 'summary': 'alpha'},
            {'uid': 'u07', 'list': 'inbox', 'sort_order': 2.5, 'due': '2026-06-01T09:00', 'priority': 5, 'summary': None},
            {'uid': 'u00', 'list': 'inbox', 'sort_order': 2.0, 'due': None, 'priority': 0, 'summary': 'gamma'},
        ],
        ['inbox/u03', 'work/u04', 'home/u01', 'inbox/u06', 'inbox/u00', 'inbox/u07', 'home/u05', 'inbox/u02', 'home/u00'],
    ),
    (
        [
            {'uid': 'u00', 'list': 'inbox', 'sort_order': 2.0, 'due': '2027-03-03T18:30', 'priority': None, 'summary': 'Alpha'},
            {'uid': 'u01', 'list': 'home', 'sort_order': None, 'due': None, 'priority': 0, 'summary': 'alpha'},
            {'uid': 'u02', 'list': 'work', 'sort_order': 100.0, 'due': None, 'priority': 5, 'summary': 'alpha'},
            {'uid': 'u03', 'list': 'work', 'sort_order': 100.0, 'due': '2026-06-01T09:00', 'priority': 1, 'summary': 'alpha'},
            {'uid': 'u04', 'list': 'work', 'sort_order': 7.0, 'due': '2026-12-31', 'priority': 5, 'summary': 'Alpha'},
            {'uid': 'u02', 'list': 'inbox', 'sort_order': 100.0, 'due': None, 'priority': 5, 'summary': 'alpha'},
        ],
        ['inbox/u00', 'work/u04', 'work/u03', 'work/u02', 'inbox/u02', 'home/u01'],
    ),
    (
        [
            {'uid': 'u00', 'list': 'inbox', 'sort_order': 7.0, 'due': '2027-03-03T18:30', 'priority': 9, 'summary': 'Alpha'},
            {'uid': 'u01', 'list': 'inbox', 'sort_order': 1.0, 'due': '2026-12-31', 'priority': 1, 'summary': 'alpha'},
            {'uid': 'u02', 'list': 'work', 'sort_order': None, 'due': '2026-12-31', 'priority': 0, 'summary': None},
            {'uid': 'u03', 'list': 'inbox', 'sort_order': 2.5, 'due': '2026-12-31', 'priority': 1, 'summary': 'gamma'},
            {'uid': 'u04', 'list': 'work', 'sort_order': 7.0, 'due': '2027-03-03T18:30', 'priority': None, 'summary': 'gamma'},
            {'uid': 'u03', 'list': 'work', 'sort_order': 2.5, 'due': '2026-12-31', 'priority': 1, 'summary': 'gamma'},
        ],
        ['inbox/u01', 'inbox/u03', 'work/u03', 'work/u02', 'inbox/u00', 'work/u04'],
    ),
    (
        [
            {'uid': 'u00', 'list': 'home', 'sort_order': 2.0, 'due': '2027-03-03T18:30', 'priority': None, 'summary': 'alpha'},
            {'uid': 'u01', 'list': 'work', 'sort_order': 100.0, 'due': '2027-03-03T18:30', 'priority': 5, 'summary': 'Beta'},
            {'uid': 'u02', 'list': 'work', 'sort_order': 2.5, 'due': '2026-06-01T09:00', 'priority': 1, 'summary': None},
            {'uid': 'u03', 'list': 'work', 'sort_order': 2.0, 'due': '2027-03-03T18:30', 'priority': 1, 'summary': 'alpha'},
            {'uid': 'u04', 'list': 'work', 'sort_order': None, 'due': '2026-01-05T00:00', 'priority': 5, 'summary': 'Alpha'},
            {'uid': 'u05', 'list': 'inbox', 'sort_order': 2.5, 'due': None, 'priority': 1, 'summary': 'Beta'},
            {'uid': 'u06', 'list': 'home', 'sort_order': 100.0, 'due': None, 'priority': None, 'summary': 'alpha'},
            {'uid': 'u07', 'list': 'work', 'sort_order': 1.0, 'due': '2026-06-01T09:00', 'priority': 1, 'summary': 'gamma'},
            {'uid': 'u03', 'list': 'inbox', 'sort_order': 1.0, 'due': '2027-03-03T18:30', 'priority': 1, 'summary': 'alpha'},
        ],
        ['work/u04', 'work/u07', 'inbox/u03', 'work/u03', 'home/u00', 'work/u02', 'inbox/u05', 'work/u01', 'home/u06'],
    ),
    (
        [
            {'uid': 'shared', 'list': 'inbox', 'sort_order': 1.0, 'due': '2027-12-31', 'priority': None, 'summary': 'dragged into place'},
            {'uid': 'shared', 'list': 'work', 'sort_order': None, 'due': '2026-01-01', 'priority': None, 'summary': 'dragged into place'},
            {'uid': 'other', 'list': 'inbox', 'sort_order': 2.0, 'due': '2026-06-06', 'priority': None, 'summary': 'other'},
        ],
        ['work/shared', 'inbox/shared', 'inbox/other'],
    ),
    (
        [
            {'uid': 't', 'list': 'inbox', 'sort_order': None, 'due': None, 'priority': None, 'summary': 'same'},
            {'uid': 't', 'list': 'work', 'sort_order': None, 'due': None, 'priority': None, 'summary': 'same'},
            {'uid': 't', 'list': 'home', 'sort_order': None, 'due': None, 'priority': None, 'summary': 'same'},
        ],
        ['inbox/t', 'work/t', 'home/t'],
    ),
]


@pytest.mark.parametrize("tasks, expected", CROSS_CHECKED)
def test_the_port_agrees_with_order_ts(tasks, expected):
    from tasksd.mcp.api import _in_display_order

    assert [f"{t['list']}/{t['uid']}" for t in _in_display_order(tasks)] == expected


def test_the_title_key_reproduces_localecompares_case_rule():
    """`localeCompare` is a collation: case is a TERTIARY difference and
    lowercase sorts BEFORE uppercase. Python's `<` is codepoint order ("Alpha" <
    "alpha") and `casefold` alone calls them equal — the first attempt at this
    port used casefold and disagreed with order.ts on exactly the six of 402
    cases where two tasks tied on due and priority and differed only in case."""
    from tasksd.mcp.api import _title_key

    assert _title_key("alpha") < _title_key("Alpha")
    assert _title_key("alpha") < _title_key("beta")
    assert _title_key("Alpha") < _title_key("beta")
    assert _title_key("") < _title_key("a")


# ── AUDIT: the booking ledger row is written after the CalDAV PUT ───────────

def test_a_booking_retried_after_a_failed_write_is_not_a_conflict_with_itself():
    """The replay hook keys entirely on the ledger — `get_booking_by_event`
    (service.py:864) — but the ledger row is inserted at line 919, *after*
    `create_event` at 911 has already PUT the VEVENT. `create_event` then makes
    a second round trip (`_refresh_from_wire`: GET, extract, upsert), and any
    part of it can raise DavError, as can a restart between the two statements.

    Modelled exactly: the PUT lands (the event is on the owner's calendar and
    the sync loop caches it) and then the write raises. The visitor's page keeps
    phase='confirm', the slot, and the SAME client_id, and they press Confirm
    again. Today `get_booking_by_event` finds nothing, `_link_busy` sees the
    orphan, `generate_slots` drops the slot and book_slot raises SlotTaken — the
    visitor is told "that time was just taken" about their own booking, picks
    another, and the owner ends up with two events for one person, one of them
    invisible in Settings › Bookings and uncounted in `booking_count`.

    The assertion is that the retry is honoured and the account holds exactly
    one booking, which both named repairs satisfy: writing the ledger row before
    the PUT, or looking `{client_id}@tasksd` up in the link's calendar before
    raising SlotTaken.
    
    **Fixed** by making the replay hook independent of the ledger rather than by
    reordering the writes — writing the ledger first would trade this for a row
    describing an event that was never created. `_recover_orphaned_booking` looks
    the client_id's event up in the link's own calendar and rebuilds the missing
    row from it, in the link's timezone so the confirmation names the time the
    visitor picked. Scoped to the link's calendar, so a client_id reused against
    a DIFFERENT link still raises rather than disclosing the other booking.
    """
    tz = ZoneInfo("America/Chicago")
    now = datetime(2026, 7, 13, 8, 0, tzinfo=tz)          # a Monday, link-local
    cal = "/u/meetings/"
    cid = "b" * 32

    svc = TaskService(_offline_settings())
    try:
        store.upsert_collection(svc._conn, CollectionInfo(
            href=cal, displayname="Meetings", components={"VEVENT"}))
        token = svc.create_booking_link({
            "title": "Chat", "description": None, "calendar_href": cal,
            "duration_minutes": 60, "timezone": "America/Chicago",
            "availability": {"0": ["09:00-17:00"]}, "show_busy": False,
            "buffer_minutes": 0, "min_notice_hours": 0, "horizon_days": 1,
            "enabled": True,
        })["token"]

        def put_then_die(href, summary, *, dtstart, dtend=None, edit=None,
                         client_id=None):
            # _put_new succeeded: the VEVENT is on the server, and by the time
            # the visitor retries the sync sweep has pulled it into the cache.
            uid = f"{client_id}@tasksd"
            raw = foreign_event_raw(uid, summary, dtstart="20260713T140000Z",
                                    dtend="20260713T150000Z")
            store.upsert_item(svc._conn, cal, Item(f"{cal}{client_id}.ics", '"1"', raw),
                              extract_from_raw(raw))
            raise DavError("connection reset while re-reading the stored resource")

        svc.create_event = put_then_die
        with pytest.raises(DavError):
            svc.book_slot(token, start_iso="2026-07-13T09:00:00-05:00",
                          name="Visitor", email="v@x.co", client_id=cid, now=now)

        # The retry: same slot, same client_id, and the create is idempotent on
        # the server (_put_new: same slug → same href → same UID → success).
        svc.create_event = lambda href, summary, *, dtstart, dtend=None, edit=None, \
            client_id=None: {"uid": f"{client_id}@tasksd"}

        try:
            result = svc.book_slot(token, start_iso="2026-07-13T09:00:00-05:00",
                                   name="Visitor", email="v@x.co", client_id=cid,
                                   now=now)
        except scheduling.SlotTaken as exc:
            pytest.fail(
                f"the visitor's retry was refused as taken ({exc}) — by their own "
                f"orphaned event. They will book a second slot and the owner gets "
                f"two meetings for one person."
            )

        assert result is not None
        confirmation, _created = result
        assert confirmation["start"] == "2026-07-13T09:00:00-05:00"
        assert len(svc.list_bookings(token)) == 1, (
            "the retry landed a second booking rather than being recognised as "
            "the same one"
        )
        # Recognised as a REPLAY, not as a fresh booking: `created` is what the
        # route charges against the link's per-link ceiling, and charging a
        # replay put the published-link denial-of-service back the last time.
        assert _created is False, (
            "the recovered booking was reported as newly created, so the retry "
            "spends another unit of the link's booking budget")
    finally:
        svc.close()


# ── AUDIT: get_events_in_range gates recurring rows on the master DTSTART ───

def test_an_occurrence_moved_before_its_series_start_is_still_in_the_window():
    """The candidate query admits recurring rows on the upper bound alone
    (`dtstart <= end_iso`) because a master "projects occurrences *forward*".
    That is only half of it: `recurring_ical_events` applies RECURRENCE-ID
    overrides, so a resource's recurrence set can contain instants *before* the
    cached master DTSTART — and `items.dtstart` is the master's. Any window
    ending before it drops the whole resource, occurrence included, so
    `expand_occurrences` is never given the chance to place it.

    Smylte itself writes this shape: `apply_occurrence_override` (edit.py:628)
    gives the override a new DTSTART and deliberately leaves the master rule
    alone, so dragging the FIRST occurrence of a series earlier is enough.
    Reproduced by hand against the real schema and the real extract/expand:
    `expand_occurrences` returns the moved 24 Aug occurrence, while
    `get_events_in_range` over the same window returns [].

    Three readers lose it, in order of seriousness: `_link_busy` queries ±1 day
    around the requested day, so the moved meeting contributes no busy interval
    and an anonymous visitor books straight over it; `smylte_find_free_time`
    reports the occupied hour as free; and the six-week grid loses the
    occurrence from the month the owner just dragged it into.

    Driven through `TaskService.events_in_range`, the method all three go
    through, so any fix — relaxing the lower gate for recurring rows, or caching
    a `min_occurrence` column — satisfies it.
    
    **Fixed** by admitting recurring rows unconditionally and letting
    `expand_occurrences` do the precise filtering it already does. The lower
    bound was as wrong as the upper one for the same reason, and the docstring
    justifying it was half right: a recurrence set projects backwards as well as
    forwards. The extra candidate rows cost one expansion each, bounded by the
    stage-2 search budget; the controls below hold that the query still filters.
    """
    cal = "/u/cal/"
    raw = foreign_event_raw(
        "series-1", "Standup", dtstart="20260907T090000Z", dtend="20260907T093000Z",
        rrule="FREQ=WEEKLY;COUNT=5",
        overrides=(("RECURRENCE-ID:20260907T090000Z", "DTSTART:20260824T090000Z",
                    "DTEND:20260824T093000Z", "SUMMARY:Standup (moved)"),),
    )

    svc = TaskService(_offline_settings())
    try:
        store.upsert_collection(svc._conn, CollectionInfo(
            href=cal, displayname="Cal", components={"VEVENT"}))
        store.upsert_item(svc._conn, cal, Item(f"{cal}series-1.ics", '"1"', raw),
                          extract_from_raw(raw))

        # The booking window book_slot builds for a 24 Aug request, widened ±1
        # day by _link_busy — and inside the August grid window too.
        found = svc.events_in_range(cal, "2026-08-23T00:00:00", "2026-08-26T00:00:00")

        starts = sorted(e["start"] for e in found)
        assert any(str(e["start"]).startswith("2026-08-24T09:00") for e in found), (
            f"the occurrence dragged to 24 Aug is not in a window that contains "
            f"it (got {starts}); its master DTSTART is 7 Sep, so the row never "
            f"reaches expand_occurrences. The booking page will offer that hour."
        )

        # The control: widening the candidate query must not stop it FILTERING.
        # A non-recurring event outside the window still has to be absent, and a
        # recurring series whose every occurrence is outside it must expand to
        # nothing rather than leaking a phantom row into the grid.
        far = foreign_event_raw("far-1", "Far", dtstart="20271201T090000Z",
                                dtend="20271201T093000Z")
        store.upsert_item(svc._conn, cal, Item(f"{cal}far-1.ics", '"1"', far),
                          extract_from_raw(far))
        elsewhere = foreign_event_raw(
            "series-2", "Elsewhere", dtstart="20270301T090000Z",
            dtend="20270301T093000Z", rrule="FREQ=WEEKLY;COUNT=3")
        store.upsert_item(svc._conn, cal, Item(f"{cal}series-2.ics", '"1"', elsewhere),
                          extract_from_raw(elsewhere))

        again = svc.events_in_range(cal, "2026-08-23T00:00:00", "2026-08-26T00:00:00")
        summaries = {e["summary"] for e in again}
        assert "Far" not in summaries, (
            f"a non-recurring event 15 months away is in the window: {summaries}")
        assert "Elsewhere" not in summaries, (
            f"a series with no occurrence in the window leaked into it: {summaries}")
        assert len(again) == len(found), (
            f"the window gained rows it should not have: {again}")
    finally:
        svc.close()


# ── AUDIT: the task tools accept a calendar id and vice versa ───────────────

def test_a_calendar_id_is_refused_by_the_task_tools():
    """`McpApi._href` resolves ids through `TaskService.resolve_list`, which
    matches any non-deleted collection by href or slug and never looks at
    `components`. The `kind` argument only changes the wording of the not-found
    sentence. Task lists and calendars share one slug namespace, and the MCP
    server's own `instructions` anticipate the confusion — "task tools need a
    list id from smylte_list_lists; event tools need a calendar id from
    smylte_list_calendars" — but nothing enforces it.

    That makes a wrong-TYPE id worse than a wrong id: a misspelling gets a
    helpful ToolError naming the discovery tool, while a calendar id succeeds
    silently. `smylte_delete_list` is annotated destructiveHint with the
    description "Delete a task list AND every task in it", and it will DELETE a
    whole calendar and every event on it, answering `{"deleted": "<id>"}`. The
    read side lies more quietly: `smylte_list_tasks` on a calendar id filters
    component == 'VTODO' and answers `{"total": 0, "tasks": []}`, so the model
    reports "that list is empty" about a calendar holding 900 events.

    Both tools are driven for real, over a real `TaskService` and its real
    resolver; only the DAV client's own `delete_collection` is replaced, by a
    recorder, so what a calendar id costs is observable without destroying
    anything. What is asserted is the outcome — the calendar is not deleted, and
    the model is not handed an ordinary-looking empty page — so a guard in
    `_href`, in `resolve_list` or in `service.delete_collection` all satisfy it.
    
    **Fixed** at `service.resolve_list`, which now takes the component it is
    resolving for — so this closes with the HTTP-layer finding rather than
    separately. `mcp/api._href` already carried a `kind`; it just never reached
    the resolver. `update_collection`/`delete_collection` needed `kind` threaded
    through too, since one pair of methods backs both the list and the calendar
    tools.
    """
    svc = TaskService(_offline_settings())
    try:
        store.upsert_collection(svc._conn, CollectionInfo(
            href="/u/errands/", displayname="Errands", components={"VTODO"}))
        store.upsert_collection(svc._conn, CollectionInfo(
            href="/u/personal-2f1a/", displayname="Personal", components={"VEVENT"}))

        deleted: list[str] = []
        svc._dav.delete_collection = deleted.append     # the DELETE, made visible
        svc._engine.discover = lambda: None             # …and nothing else on the wire

        tools = build_tools(McpApi(svc))

        try:
            answer = tools["smylte_delete_list"].handler(list_id="personal-2f1a")
        except Exception as exc:                        # noqa: BLE001 — any refusal
            answer = f"refused ({type(exc).__name__}: {exc})"
        assert deleted == [], (
            f"smylte_delete_list — annotated destructiveHint, described as "
            f"deleting \"a task list AND every task in it\" — issued a collection "
            f"DELETE against {deleted} for a CALENDAR id, and answered {answer!r}. "
            f"Every event on it is gone, from Radicale and from every other CalDAV "
            f"client on the account."
        )

        try:
            rows = tools["smylte_list_tasks"].handler(list_id="personal-2f1a")
        except Exception:                               # noqa: BLE001 — any refusal
            pass
        else:
            pytest.fail(
                f"smylte_list_tasks answered {rows} for a CALENDAR id — the model "
                f"is told the list is empty, where a merely misspelled id would "
                f"have got the ToolError naming the right discovery tool."
            )

        # THE MIRROR, and it is half the finding: "every task tool accepts a
        # calendar id AND every calendar tool accepts a task-list id". Driving
        # only the first direction leaves `_COMPONENT` half-mapped and this test
        # green — verified: dropping `"calendar": "VEVENT"` from that dict passes
        # everything above while `smylte_delete_calendar(<a task list>)` still
        # deletes the list and every task on it. The HTTP twin (the next test)
        # drives both directions; this one did not copy that discipline.
        try:
            answer = tools["smylte_delete_calendar"].handler(calendar_id="errands")
        except Exception as exc:                        # noqa: BLE001 — any refusal
            answer = f"refused ({type(exc).__name__}: {exc})"
        assert deleted == [], (
            f"smylte_delete_calendar issued a collection DELETE against {deleted} "
            f"for a TASK-LIST id, and answered {answer!r}. Every task on it is "
            f"gone, from Radicale and from every other client on the account."
        )

        try:
            rows = tools["smylte_list_events"].handler(calendar_id="errands")
        except Exception:                               # noqa: BLE001 — any refusal
            pass
        else:
            pytest.fail(
                f"smylte_list_events answered {rows} for a TASK-LIST id — the "
                f"model is told the calendar is empty rather than that it named "
                f"the wrong kind of collection."
            )
    finally:
        svc.close()


# ── AUDIT: resolve_list ignores the collection's component set ──────────────

@pytest.mark.radicale
def test_a_task_cannot_be_written_into_an_event_only_calendar(client):
    """The READ side of this service is strictly segregated by component:
    `list_lists` filters "VTODO", `list_calendars` filters "VEVENT",
    `get_task`/`list_tasks` filter component == "VTODO", `_link_busy` skips any
    collection without VEVENT, and `test_tabs_are_separated` asserts the
    separation is intentional. The WRITE side has no such check: `resolve_list`
    matches href-or-slug alone and is the sole resolver behind every
    `/api/lists/...` and `/api/calendars/...` route (app.py `_href`) and behind
    both MCP resolvers. `SyncEngine`'s guard is `store.has_collection`, which
    checks existence and `deleted=0` and nothing about components. The one place
    that does check is `_normalize_link_fields`: "calendar must be an existing
    event calendar" — so the need for the check was recognised, and applied to
    exactly one caller.

    Written into a VEVENT-only calendar, a VTODO is invisible to `list_lists()`
    and therefore to the Tasks tab and to `smylte_list_tasks`' fan-out; the
    Calendar tab shows the calendar reading "1 open" with no events on it.
    Symmetrically a VEVENT in a VTODO-only list is invisible to the Calendar
    grid AND to `_link_busy`, so the public booking page offers that hour as
    free.

    Asserted as "the write is refused" (any 4xx — the status is not the point),
    against the real routes and the real Radicale, because a create that answers
    201 and then cannot be read back is the worst of the two outcomes.
    
    **Fixed** by giving `resolve_list` a `component` argument and passing it from
    every item route: VTODO from `/api/lists/{id}/tasks*`, VEVENT from
    `/api/calendars/{id}/events*` and from `move`'s destination. The routes that
    deliberately span both kinds — collection rename, delete and reorder, which
    the SPA drives from either tab — pass nothing and keep the old behaviour;
    the controls below hold that line, because a filter applied too widely takes
    the app offline rather than closing a hole.
    """
    lst = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()
    cal = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}"}).json()
    try:
        into_calendar = client.post(f"/api/lists/{cal['id']}/tasks",
                                    json={"summary": "buy milk"})
        into_list = client.post(f"/api/calendars/{lst['id']}/events", json={
            "summary": "Standup", "start": "2026-07-10T14:00:00",
            "end": "2026-07-10T15:00:00"})

        assert into_calendar.status_code >= 400, (
            f"POST /api/lists/<calendar id>/tasks answered "
            f"{into_calendar.status_code}: a VTODO now lives in a VEVENT-only "
            f"calendar, where list_lists() — and so the Tasks tab and "
            f"smylte_list_tasks — will never return it again."
        )
        assert into_list.status_code >= 400, (
            f"POST /api/calendars/<task list id>/events answered "
            f"{into_list.status_code}: a VEVENT now lives in a VTODO-only list, "
            f"invisible to the calendar grid and to _link_busy, so the public "
            f"booking page will offer that hour as free."
        )
        # The control, and it carries the whole risk of this fix: `resolve_list`
        # is behind EVERY /api/lists and /api/calendars route, so a component
        # filter applied too widely takes the app offline rather than closing a
        # hole. The matching pairs must still work…
        assert client.post(f"/api/lists/{lst['id']}/tasks",
                           json={"summary": "buy milk"}).status_code == 201
        assert client.post(f"/api/calendars/{cal['id']}/events", json={
            "summary": "Standup", "start": "2026-07-10T14:00:00",
            "end": "2026-07-10T15:00:00"}).status_code == 201
        # …and so must the routes that DELIBERATELY span both kinds: the SPA
        # renames and reorders collections from either tab through these.
        assert client.patch(f"/api/calendars/{lst['id']}",
                            json={"name": "renamed"}).status_code == 200
        assert client.post("/api/calendars/reorder",
                           json={"ids": [lst["id"], cal["id"]]}).status_code in (200, 204)
    finally:
        client.delete(f"/api/lists/{lst['id']}")
        client.delete(f"/api/calendars/{cal['id']}")


# ── AUDIT: POST /api/tasks/reorder writes sidecar rows for unknown uids ─────

@pytest.mark.radicale
def test_a_reorder_naming_an_unknown_uid_writes_no_sidecar_row(client):
    """`reorder_tasks` validates that each entry's *list* resolves (404) and
    that no `(href, uid)` pair repeats (422). The uid itself is unbounded
    free text checked against nothing, and `store.set_sort_orders` then does an
    upsert that creates a row with `orphaned_at IS NULL` for any uid at all.
    `orphan_sidecar` only fires when a *known* item is deleted or a collection
    is soft-deleted, and `gc_orphans` sweeps only `WHERE orphaned_at IS NOT
    NULL` — so the row can never be reclaimed for the life of the list.

    This is the defect the 2026-08-07 sweep closed for `PUT .../sidecar`, whose
    guard now carries a nine-line comment explaining that sidecar rows are the
    one thing a resync cannot rebuild. `reorder_tasks` reaches the same table
    through a different door, with `ReorderTasks.items` allowing 20 000 entries
    a request.

    The realistic trigger needs no attacker: the phone deletes a task, the next
    sync purges it and orphans its sidecar row, then the user drags any row and
    the SPA sends its whole in-memory array — still containing the dead task —
    resurrecting the orphan permanently.

    Asserted exactly as the sibling route's test does (test_api.py:895): the
    sidecar count is unchanged. Dropping the entry and rejecting the request
    both satisfy that, so the status code is deliberately not asserted.
    
    **Fixed** in `store.set_sort_orders` rather than in the route, so every door
    into that table passes the same guard: the INSERT is now
    `SELECT ... WHERE EXISTS (SELECT 1 FROM items ...)`. The sibling
    `PUT .../sidecar` got a `has_task` check in the 2026-08-07 sweep and this
    path was written to the same table without one.
    """
    lst = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()
    svc = client.app.state.service

    def sidecar_rows() -> int:
        with svc._lock:
            return svc._conn.execute("SELECT count(*) FROM sidecar").fetchone()[0]

    other = client.post("/api/lists", json={"name": f"O-{uuid.uuid4().hex[:8]}"}).json()
    try:
        real = client.post(f"/api/lists/{lst['id']}/tasks",
                           json={"summary": "still here"}).json()
        # A REAL task, in a DIFFERENT list. The guard has to be scoped to the
        # collection, not just to the uid: the message below says "not in this
        # collection", and a check written as `WHERE uid=?` satisfies the
        # unknown-uid case while still minting an unreclaimable row under the
        # wrong collection_href — verified to pass this test before this line
        # existed.
        elsewhere = client.post(f"/api/lists/{other['id']}/tasks",
                                json={"summary": "belongs to the other list"}).json()
        before = sidecar_rows()
        client.post("/api/tasks/reorder", json={"items": [
            {"list": lst["id"], "uid": real["uid"]},
            {"list": lst["id"], "uid": "ghost-deleted-on-the-phone"},
            {"list": lst["id"], "uid": elsewhere["uid"]},
        ]})
        assert sidecar_rows() == before + 1, (
            f"the reorder minted {sidecar_rows() - before} sidecar rows for 1 live "
            f"task in this list: a row for a uid that is not in this collection, "
            f"with orphaned_at IS NULL, which gc_orphans can never reclaim."
        )
        # …and the one legitimate row is the one that was asked for. Scoped to
        # THIS list: the service is session-scoped, so an unscoped query picks up
        # every other test's sidecar rows and fails only in a full-suite run.
        with svc._lock:
            placed = svc._conn.execute(
                "SELECT uid FROM sidecar WHERE collection_href=? "
                "AND sort_order IS NOT NULL",
                (svc.resolve_list(lst["id"], component="VTODO"),)
            ).fetchall()
        assert [r["uid"] for r in placed] == [real["uid"]], (
            f"the wrong task was given a position: {[dict(r) for r in placed]}")
    finally:
        client.delete(f"/api/lists/{lst['id']}")
        client.delete(f"/api/lists/{other['id']}")


# ── AUDIT: move_event maps a no-uid-conflict 409 to "server unavailable" ────

@pytest.mark.radicale
def test_a_move_into_a_calendar_holding_that_uid_is_a_conflict_not_an_outage(client):
    """The destination PUT is guarded only against `PreconditionFailed`, which
    covers an occupied destination *href*. Radicale also enforces UID uniqueness
    per collection and answers a duplicate-UID PUT with 409 `C:no-uid-conflict`,
    which raises `dav.errors.Conflict` — a plain `DavError`. It sails past the
    `except PreconditionFailed`, past every specific handler, and lands on the
    `DavError` catch-all (app.py:852) as a 502 "calendar server unavailable, try
    again shortly". That is wrong on both counts: the server is fine, and
    retrying can never succeed. The correct sentence — "event {uid} already
    exists in the target calendar" — is two lines below the branch that misses.

    The shape is ordinary: a foreign client (Thunderbird, DAVx5) copied the
    event into the destination under its own filename. Set up here by putting
    the same UID at a second href in the destination, through the app's own DAV
    client, and then asking the real route to move it. No test covers any move
    failure path — test_api.py:262 covers the happy path and an unknown
    destination id.

    Asserted as the status the caller receives, not the exception class: 409,
    which is what ConflictError already maps to.
    
    **Fixed** by catching `Conflict` alongside `PreconditionFailed` on the
    destination PUT. The engine already had the right words two lines below; they
    just never fired for this spelling of the same condition.
    """
    src = client.post("/api/calendars", json={"name": f"S-{uuid.uuid4().hex[:8]}"}).json()
    dst = client.post("/api/calendars", json={"name": f"D-{uuid.uuid4().hex[:8]}"}).json()
    svc = client.app.state.service
    try:
        ev = client.post(f"/api/calendars/{src['id']}/events", json={
            "summary": "Standup", "start": "2026-07-10T14:00:00",
            "end": "2026-07-10T15:00:00"}).json()

        # A foreign client already copied it into the destination, under its own
        # filename — same UID, different href.
        with svc._lock:
            src_href = svc.resolve_list(src["id"])
            dst_href = svc.resolve_list(dst["id"])
            row = store.get_item(svc._conn, src_href, ev["uid"])
            body = svc._dav.get(row["href"]).data
            svc._dav.put(f"{dst_href}copy-of-standup.ics", body, if_none_match="*")

        moved = client.post(f"/api/calendars/{src['id']}/events/{ev['uid']}/move",
                            json={"calendar": dst["id"]})

        assert moved.status_code == 409, (
            f"the move answered {moved.status_code} {moved.text!r}: the caller is "
            f"told the calendar server is unavailable and to try again shortly, "
            f"for a conflict that no retry can clear and that the engine already "
            f"has the sentence for."
        )
    finally:
        client.delete(f"/api/calendars/{src['id']}")
        client.delete(f"/api/calendars/{dst['id']}")


# ── AUDIT: list_oauth_grants reads a bare column in a multi-aggregate GROUP BY

def test_a_grants_scope_does_not_depend_on_row_order():
    """The query groups `oauth_tokens` by `family_id` and selects `t.scope` as a
    bare column alongside three aggregates. SQLite's bare-column rule only pins
    the value to a particular row when the query has exactly ONE min()/max();
    with three, it comes from an arbitrary row of the group. Scope is not
    constant within a family: `_grant_refresh` implements RFC 6749 §6 narrowing
    and reissues into the SAME family, while the previous wide access token
    stays live for the rest of its hour and the previous wide refresh row is
    deliberately kept until it expires ("A used refresh token is kept until it
    expires", store.py:857).

    So `GET /api/mcp/connections` — the owner's only view of what each connector
    may do, and the screen they act on to disconnect one — can name a capability
    the grant's live tokens do not match, in either direction.

    Pinned as determinism rather than as one particular answer, because the
    finding names two acceptable repairs that disagree about the answer (the
    union of live scopes; the newest live token's scope) and both make it
    deterministic. Two families here hold exactly the same four tokens, with the
    same scopes, the same created_at and the same expiry — they differ only in
    the order the rows were inserted, which is nothing the owner can see. Today
    that alone decides what the screen says.
    
    **Fixed** with a correlated subquery for the newest live token's scope, so
    the connections screen reports what the family can still actually do rather
    than a value SQLite chose by scan order.
    """
    wide, narrow = "mcp:read mcp:write offline_access", "mcp:read offline_access"
    rows = [("access", wide, 100.0), ("refresh", wide, 100.0),
            ("access", narrow, 200.0), ("refresh", narrow, 200.0)]

    conn = store.connect(":memory:")
    store.init_db(conn)
    try:
        for family, order in (("f-a", rows), ("f-b", list(reversed(rows)))):
            for i, (kind, scope, created) in enumerate(order):
                store.create_oauth_token(
                    conn, token_hash=f"{family}-{i}", kind=kind, client_id="c1",
                    scope=scope, resource="https://t.test/mcp", family_id=family,
                    expires_at=10_000.0, now=created)

        by_family = {g["family_id"]: g["scope"]
                     for g in store.list_oauth_grants(conn, now=0.0)}
        assert by_family["f-a"] == by_family["f-b"], (
            f"two identical grants report different capabilities — "
            f"f-a={by_family['f-a']!r}, f-b={by_family['f-b']!r} — because their "
            f"rows were inserted in a different order. The connections screen "
            f"names a capability level chosen by the scan, not by the grant."
        )
    finally:
        conn.close()


# ── AUDIT: a narrowing refresh without offline_access ends the grant ────────

@pytest.mark.radicale
def test_narrowing_scope_on_refresh_does_not_end_the_grant(mcp_app):
    """`_grant_refresh` lets a client narrow scope and passes the narrowed value
    to `_issue_pair`, which gates the new refresh token on it: `if SCOPE_OFFLINE
    in scope_set(scope)`. A client that sends `scope=mcp:read mcp:write` on
    refresh — an ordinary thing to do, since `offline_access` is a grant-shape
    scope rather than an API scope and the token response echoes scope back —
    gets 200, an access token, and NO refresh_token.

    RFC 6749 §6 is explicit that a client keeps its existing refresh token when
    the response omits one, so the honest client re-presents the old one next
    time. `use_refresh_token` reports "replayed", `revoke_oauth_family` deletes
    every token in the family, and the grant is destroyed: the current access
    token dies instantly and the owner must re-type the app password at the
    consent screen with no explanation anywhere. The server's reuse detector
    fires on a client doing exactly what the spec tells it to.

    The assertion is that the grant SURVIVES a legal narrowing — the client
    refreshes again with whatever the server left it holding (the rotated token
    if one came back, otherwise the one it kept). Both named repairs satisfy
    that, and so does any third that keeps the client able to refresh.

    No existing test covers narrowing at refresh time: test_a_refresh_cannot_
    widen_scope covers only the rejection, and test_no_refresh_token_without_
    offline_access only the authorization-code path.
    
    **Fixed** by keeping `offline_access` from the FAMILY's granted scope when
    reissuing. It is a grant shape, not an API capability, so narrowing the API
    scopes is not a request to stop refreshing — and the alternative reading cost
    the user their whole grant with no explanation anywhere.
    """
    grant = _connect(mcp_app)
    held = grant["refresh_token"]

    narrowed = mcp_app.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": held,
        "client_id": grant["reg"]["client_id"], "scope": "mcp:read mcp:write"})
    assert narrowed.status_code == 200, narrowed.text

    # RFC 6749 §6: "the client MUST retain the existing refresh token" when the
    # response omits one. So this is what a correct client presents next.
    held = narrowed.json().get("refresh_token") or held

    again = mcp_app.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": held,
        "client_id": grant["reg"]["client_id"]})
    assert again.status_code == 200, (
        f"the next refresh answered {again.status_code} {again.text!r}. Narrowing "
        f"the API scopes returned no refresh token "
        f"(refresh_token in response: {'refresh_token' in narrowed.json()}), so "
        f"the client re-presented the one it was told to keep and the reuse "
        f"detector revoked the whole grant."
    )
    assert "access_token" in again.json()


# ── AUDIT: disconnecting a connector is not idempotent ─────────────────────

@pytest.mark.radicale
def test_disconnecting_a_connection_twice_is_not_an_error(mcp_app):
    """`drop_connection` treats an already-gone family as an error, and
    `ConnectionsSection.disconnect` treats ANY failure as "the disconnect did
    not happen" and restores the optimistically removed row — `makeGuard`
    returns `undefined` for both a dropped connection and an HttpError, so the
    two are indistinguishable to the caller.

    Together they lie to the owner about the state of a security control. The
    DELETE reaches the server, every token in the family is deleted and
    committed, then the tunnel drops the response; the row comes back with a
    toast. The owner clicks Disconnect again, the server now finds 0 rows and
    answers 404 "unknown connection", the row is restored a second time and the
    toast now reads "unknown connection". The section is loaded once in a
    `useEffect` with an empty dep list and never refetched, so a Connected-apps
    list still showing a grant that is already dead persists for as long as the
    panel stays open.

    Pinned on the backend half, which is where the finding is filed: the DELETE
    is a request for absence, and absence is already achieved. There is no
    information leak either — the endpoint is cookie-gated to the owner.
    `test_connections_are_listed_and_can_be_disconnected` (test_mcp.py:653)
    asserts today's 404, so the suite pins the behaviour rather than catching
    it; that assertion is the one to update when this is fixed. The finding also
    names a frontend-only remedy (treat a 404 as success in
    `ConnectionsSection`); if that is chosen instead, this pin reclassifies
    rather than fails.
    
    **Fixed** by answering 204 whether or not a family was found. A connection
    that is already gone is the state the caller asked for. Nothing leaks: the
    route is cookie-gated to the owner.
    """
    _connect(mcp_app)
    # These two routes are the owner managing their own grants, so they are
    # cookie-gated like the rest of /api — the bearer must not reach them.
    assert mcp_app.post("/api/login", json={
        "username": "admin", "password": PASSWORD}).status_code == 200
    family = mcp_app.get("/api/mcp/connections").json()["connections"][0]["family_id"]

    first = mcp_app.delete(f"/api/mcp/connections/{family}")
    assert first.status_code < 400, first.text
    assert mcp_app.get("/api/mcp/connections").json()["connections"] == []

    retry = mcp_app.delete(f"/api/mcp/connections/{family}")
    assert retry.status_code < 400, (
        f"the retry answered {retry.status_code} {retry.text!r}. The grant is "
        f"already dead, but the SPA cannot tell that from a failed disconnect: "
        f"it restores the row and shows the error, so the owner is looking at a "
        f"Connected-apps list that still lists a revoked connector."
    )


# ── AUDIT: a notifications/ method carrying an id gets no reply at all ──────

def test_a_notification_method_sent_with_an_id_gets_a_reply():
    """`handle` computes `is_notification = "id" not in message` and honours it
    on every other branch — `tools/call`, unknown methods, the ToolError path
    and the generic exception path all read `return None if is_notification else
    ...`. The `notifications/` branch alone returns an unconditional `None`,
    discarding the id. The transport then answers 202 with an empty body, or
    omits the entry from a batch array, so a client that sent `{"id": N,
    "method": "notifications/initialized"}` holds a promise for id N that is
    never settled — a silent hang during handshake rather than a readable error.

    JSON-RPC 2.0 requires a response for any message carrying an `id`, and
    shipping MCP clients have gotten this wrong in exactly this way.
    `test_a_batch_answers_each_request_and_keeps_its_ids` documents matching
    replies by id as the contract; `test_notifications_get_202_and_no_body`
    sends only the id-less form.

    Asserted as "there is a reply and it carries the id", which both a friendly
    empty result and a strict INVALID_REQUEST error satisfy. The id-less form is
    checked alongside so a fix cannot start replying to genuine notifications.
    
    **Fixed** by honouring `is_notification` in that branch like every other one.
    An empty result is the friendlier of the two legal answers.
    """
    srv = McpServer(object())

    reply = srv.handle(
        {"jsonrpc": "2.0", "id": 5, "method": "notifications/initialized"},
        scopes={"mcp:read"})

    assert reply is not None, (
        "a JSON-RPC request carrying id 5 got no reply at all; the client waits "
        "on an id that never resolves"
    )
    assert reply.get("id") == 5, f"the reply does not carry the id: {reply}"

    # A real notification — no id — must still get no reply.
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"},
                      scopes={"mcp:read"}) is None


# ── Filed by the Stage 3 adversarial review — OPEN when written ─────────────


@pytest.mark.radicale
def test_a_refresh_with_an_over_wide_scope_does_not_burn_the_token(mcp_app):
    """`use_refresh_token` is called before the `asked - granted` widening check,
    and a refresh token is single-use.

    So a client that sends one over-wide scope — a misconfigured connector, or
    one that simply repeats the scope string it was first issued — has its token
    consumed on a request that is refused anyway. Its next ORDINARY refresh then
    presents a token already marked used, which is the replay signature:
    `revoke_oauth_family` destroys the whole grant and the owner is told "this
    refresh token was already used". That is an alarm about a theft that did not
    happen, for what is really a client bug — and it desensitises the one alarm
    that should mean a stolen token.

    `oauth.py` argues this exact principle nine lines earlier for `_check_cv`
    ("checking after would burn the one use on a request we were going to refuse
    anyway"). It was simply not applied one branch over.

    Same shape as `test_a_refused_refresh_does_not_burn_the_token_or_kill_the_family`
    in the stage-2 file, which pins the `_check_cv` half.
    """
    granted = _connect(mcp_app)
    body = {"grant_type": "refresh_token", "refresh_token": granted["refresh_token"],
            "client_id": granted["reg"]["client_id"]}

    refused = mcp_app.post("/oauth/token", data={**body, "scope": "mcp:read mcp:admin"})
    assert refused.status_code != 200, refused.text
    assert "already used" not in refused.text, (
        f"a refused refresh was reported as a REPLAY: {refused.text[:200]}"
    )

    # The client's next ordinary refresh, with the same token it was never told
    # had been spent.
    again = mcp_app.post("/oauth/token", data=body)
    assert again.status_code == 200, (
        f"the refused attempt consumed the refresh token or revoked its family: "
        f"{again.status_code} {again.text[:200]}"
    )
    assert again.json().get("access_token")


def test_a_grant_reports_what_any_live_token_can_still_do():
    """The Connected-apps screen answers "what can this connection still do", and
    the honest answer is the UNION of the live tokens' scopes.

    Reporting the NEWEST live token's scope is deterministic — which is what the
    earlier fix was after — but systematically wrong in the UNSAFE direction. A
    refresh may narrow scope (RFC 6749 §6) and reissues into the same family,
    while the PREVIOUS wide-scoped access token stays live for the rest of its
    hour. So straight after a narrowing refresh the screen reads "read-only"
    while the connector goes on writing, and a scoped MCP token can trigger that
    deliberately by refreshing with `scope=mcp:read` right after the code
    exchange.

    Revocation still works, so this is deception rather than escalation — but the
    screen exists to be acted on, and it is the only view the owner has.
    """
    conn = store.connect(":memory:")
    store.init_db(conn)
    wide = "mcp:read mcp:write offline_access"
    narrow = "mcp:read offline_access"
    # The wide access token still has an hour to run when the narrowing refresh
    # reissues; both are live at `now`.
    store.create_oauth_token(conn, token_hash="a-wide", kind="access", client_id="c1",
                             family_id="fam", scope=wide, resource=f"{ISSUER}/mcp",
                             expires_at=10_000.0, now=100.0)
    store.create_oauth_token(conn, token_hash="r-narrow", kind="refresh", client_id="c1",
                             family_id="fam", scope=narrow, resource=f"{ISSUER}/mcp",
                             expires_at=10_000.0, now=200.0)

    grants = store.list_oauth_grants(conn, now=0.0)
    assert len(grants) == 1, grants
    reported = set(grants[0]["scope"].split())
    assert "mcp:write" in reported, (
        f"the screen reported {grants[0]['scope']!r} while a live token still "
        f"carried mcp:write"
    )


def test_a_grant_does_not_report_what_an_expired_token_could_do():
    """The control, and the one this repair actually needs.

    "Union of live tokens" is one step from "union of every token ever issued",
    which over-reports in the same direction the old behaviour under-reported:
    the screen would say a connector can write for the rest of the grant's life
    because it could an hour ago. The pin above cannot tell those apart — it has
    no expired rows — so the boundary is asserted here.
    """
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.create_oauth_token(conn, token_hash="a-old", kind="access", client_id="c1",
                             family_id="fam", scope="mcp:read mcp:write",
                             resource=f"{ISSUER}/mcp", expires_at=50.0, now=10.0)
    store.create_oauth_token(conn, token_hash="r-now", kind="refresh", client_id="c1",
                             family_id="fam", scope="mcp:read offline_access",
                             resource=f"{ISSUER}/mcp", expires_at=10_000.0, now=200.0)

    grants = store.list_oauth_grants(conn, now=100.0)      # the wide one has lapsed
    assert len(grants) == 1, grants
    reported = set(grants[0]["scope"].split())
    assert "mcp:write" not in reported, (
        f"the screen reported {grants[0]['scope']!r}, crediting a token that "
        f"expired at 50.0"
    )
    assert reported == {"mcp:read", "offline_access"}


def test_task_order_matches_the_browser_when_the_server_is_in_another_zone(monkeypatch):
    """`_in_display_order` promises to be the port of `sortTasks`, and the 402-case
    cross-check next door cannot see this: both implementations run in one
    process, so they share a zone. It is the same blind spot the uid-only keying
    had before duplicates were added to the corpus.

    `_as_dt` did `value.astimezone().replace(tzinfo=None)` — the SERVER's local
    wall clock — while `dueAt` resolves a date-only due against BROWSER-local
    midnight. With the server in UTC and the reader in America/Chicago (the
    ordinary Docker deployment), a task due 23:00 Chicago on the 5th and an
    all-day task on the 6th swap places: in UTC the timed one is already the 6th
    at 05:00, so it sorts AFTER the all-day one; in Chicago it is still the 5th
    and sorts before.

    This ordering is the one thing that decides which rows `limit` keeps, so the
    swap can push the soonest deadline off a page that looks ordered.

    Driven through the zone the owner actually reads in, which is what the fix
    threads down from `home_timezone`.
    """
    # The server's zone is pinned, not assumed: the defect is a DISAGREEMENT
    # between two zones, so a run that happened to be in America/Chicago would
    # pass against the bug.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()

    chicago = ZoneInfo("America/Chicago")
    tasks = [
        _task("a", summary="Late call", due="2026-01-05T23:00:00-06:00"),
        _task("b", summary="All-day thing", due="2026-01-06"),
    ]
    from tasksd.mcp.api import _in_display_order
    got = [t["uid"] for t in _in_display_order(tasks, chicago)]
    assert got == ["a", "b"], (
        f"a task due 23:00 on the 5th in the reader's zone sorted after an "
        f"all-day task on the 6th: {got}"
    )


def test_task_order_without_a_zone_is_unchanged():
    """The control for the signature change. Every caller that has no service
    handle — the 402-case corpus check above, and any direct use — passes no
    zone, and must keep getting exactly the ordering it got before: resolved
    against the server's own local clock. A fix that made the zone mandatory, or
    that defaulted it to UTC, would move that corpus silently."""
    tasks = [
        _task("a", summary="One", due="2026-01-05"),
        _task("b", summary="Two", due="2026-01-06"),
        _task("c", summary="Three"),
    ]
    from tasksd.mcp.api import _in_display_order
    assert [t["uid"] for t in _in_display_order(tasks)] == ["a", "b", "c"]
