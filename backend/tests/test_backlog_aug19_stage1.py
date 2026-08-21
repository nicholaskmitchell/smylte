"""The 2026-08-19 sweep, stage 1: crash paths.

Untrusted input reaching an unhandled exception — a 500 where a 4xx was owed.
Same shape as the (now closed) stage 1 of the 2026-08-16 backlog: a value an
adversary, a foreign CalDAV client, or merely an odd browser control chooses
reaches an exception type outside the taxonomy the handlers were built around,
so it escapes as a 500 the caller can neither read nor act on.

**Stage 1 is CLOSED.** These began as `xfail(strict=True)` pins, each failing
against the code as it stood. The seven findings are fixed and ticked in
docs/AUDIT.md, so the markers are gone and these are now ordinary regression
tests: they must stay green.

The docstrings deliberately keep the past tense and the original evidence — a
closed finding's value is the record of what the bug was and why it mattered,
and that is what stops it being reintroduced. Run just this stage with
`pytest -m stage1`.

Every one is behavioural: each drives the real endpoint, the real DAV client or
the real MCP server and asserts the answer a caller receives, not the shape of
the source. Each asserts the *class* of the corrected answer ("not a 500", "not
an outage sentence") rather than a particular repair, because a pin that only
accepts the fix its author imagined is not a regression test. That earned its
keep here: three of the seven were fixed in a different place from the one the
finding suggested, and every pin still recognised its own repair.

Written after reproducing each one by hand against the scratch Radicale on
:5233, so the evidence in the docstrings is observed, not inferred.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.dav.errors import DavError
from tests.conftest import PASSWORD, SCRATCH_URL, USER, api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage1]

OWNER_PASSWORD = "testpass123"          # what conftest.api_settings configures
ISSUER = "https://tasks.example.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"

# U+FFFE: a character an iCalendar body carries happily and an XML document
# cannot (XML 1.0 §2.2 Char forbids it and U+FFFF). A literal, because that is
# the only spelling every layer below reads identically.
FFFE = "￾"


# ── harness ──────────────────────────────────────────────────────────────────
# `raise_server_exceptions=False` everywhere: a 500 is the finding, so it has to
# be observable as a status code rather than re-raised into the test as if the
# request had never been made. That is also what a real client sees.


@pytest.fixture(scope="module")
def app_client(_scratch_up, tmp_path_factory):
    """The owner's HTTP API, logged in, against scratch Radicale."""
    db = tmp_path_factory.mktemp("aug19") / "api.db"
    with TestClient(create_app(api_settings(str(db))),
                    raise_server_exceptions=False) as c:
        r = c.post("/api/login", json={"username": "admin", "password": OWNER_PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture(scope="module")
def mcp_post(_scratch_up, tmp_path_factory):
    """The MCP endpoint plus a bearer minted through the real OAuth flow.

    The whole dance rather than a forged token: /mcp is reached only with a
    grant the authorization server actually issued, and the finding is about
    what a *connected* client can do to it.
    """
    db = tmp_path_factory.mktemp("aug19mcp") / "mcp.db"
    settings = dataclasses.replace(
        api_settings(str(db)), mcp_enabled=True, public_url=ISSUER,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        reg = c.post("/oauth/register", json={
            "client_name": "Claude", "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
        })
        assert reg.status_code == 201, reg.text
        reg = reg.json()

        verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        page = c.get("/oauth/authorize", params={
            "response_type": "code", "client_id": reg["client_id"],
            "redirect_uri": CALLBACK, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "xyz",
            "scope": "mcp:read mcp:write offline_access", "resource": f"{ISSUER}/mcp",
        })
        assert page.status_code == 200, page.text
        signed = re.search(r'name="request" value="([^"]+)"', page.text).group(1)
        approved = c.post("/oauth/authorize", data={
            "request": signed, "action": "approve", "grant": "full",
            "username": "admin", "password": OWNER_PASSWORD,
        }, follow_redirects=False)
        code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
        tok = c.post("/oauth/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": CALLBACK, "client_id": reg["client_id"],
            "code_verifier": verifier, "resource": f"{ISSUER}/mcp",
        })
        assert tok.status_code == 200, tok.text

        access = tok.json()["access_token"]

        def post(raw: str) -> httpx.Response:
            """POST a body EXACTLY as written — `json=` cannot express NaN."""
            return c.post("/mcp", content=raw.encode(), headers={
                "Authorization": f"Bearer {access}",
                "MCP-Protocol-Version": "2025-06-18",
                "Content-Type": "application/json",
            })

        yield post


@pytest.fixture(scope="module")
def mcp_stack(_scratch_up, tmp_path_factory):
    """The real tool table over a real TaskService, with one recurring event.

    No HTTP and no OAuth: that finding is about what the tool layer does with an
    argument, and this is the shortest path that still runs the genuine chain
    McpServer -> McpApi -> TaskService -> SyncEngine -> ical.edit.
    """
    from tasksd.mcp.api import McpApi
    from tasksd.mcp.server import McpServer
    from tasksd.mcp.tools import SCOPE_READ, SCOPE_WRITE
    from tasksd.service import TaskService

    db = tmp_path_factory.mktemp("aug19tools") / "tools.db"
    svc = TaskService(api_settings(str(db)))
    api = McpApi(svc)
    cal = api.create_calendar(name=f"C-{uuid.uuid4().hex[:8]}")
    try:
        event = api.create_event(cal["id"], summary="stand-up",
                                 start="2026-09-08T09:00", end="2026-09-08T09:30",
                                 repeat="daily", repeat_count=5)
        yield McpServer(api), cal["id"], event["uid"], {SCOPE_READ, SCOPE_WRITE}
    finally:
        try:
            api.delete_collection(cal["id"], kind="calendar")
        finally:
            svc.close()


def _new_calendar(client) -> dict:
    r = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def _foreign_put(collection_href: str, uid: str, body: str) -> str:
    """A resource written by ANOTHER CalDAV client — adversary #2, and the
    returned href is the one this app will see it at.

    Straight to Radicale over httpx, deliberately bypassing this app: the point
    of several of these findings is that the bytes never passed our own edge.
    """
    href = f"{collection_href.rstrip('/')}/{uid}.ics"
    r = httpx.put(f"{SCRATCH_URL}{href}", content=body.encode(), auth=(USER, PASSWORD),
                  headers={"Content-Type": "text/calendar; charset=utf-8"})
    assert r.status_code in (201, 204), f"foreign PUT failed: {r.status_code} {r.text}"
    return href


def _vevent(uid: str, *, dtstart: str, dtend: str, rrule: str) -> str:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign-client//EN\r\n"
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260101T000000Z\r\n"
        f"{dtstart}\r\n{dtend}\r\nSUMMARY:stand-up\r\nRRULE:{rrule}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


# ── AUDIT: a non-finite JSON-RPC id is echoed into a response that cannot ─────
# ── carry it, so the request 500s after the tool has already written ──────────

@pytest.mark.radicale
@pytest.mark.parametrize("label, body", [
    ("NaN", '{"jsonrpc":"2.0","id":NaN,"method":"ping"}'),
    ("-Infinity", '{"jsonrpc":"2.0","id":-Infinity,"method":"ping"}'),
    # Not a literal: 1e400 is an ordinary-looking number that json.loads
    # overflows to inf, so a client need not be hostile to send one.
    ("1e400", '{"jsonrpc":"2.0","id":1e400,"method":"ping"}'),
    ("one poisoned id in a batch", '[{"jsonrpc":"2.0","id":1,"method":"ping"},'
                                   '{"jsonrpc":"2.0","id":NaN,"method":"ping"}]'),
])
def test_a_non_finite_jsonrpc_id_gets_an_answer_not_a_500(mcp_post, label, body):
    """`json.loads` accepts the bare literals `NaN`, `Infinity` and `-Infinity`
    (and overflows `1e400` to `inf`), `McpServer.handle` echoed the id back
    verbatim, and Starlette renders with `json.dumps(..., allow_nan=False)` —
    which raises. Nothing caught ValueError there, so the request died as a
    500 with a traceback.

    Fixed in `handle`, which now refuses an id that is not a string, a finite
    number or null and answers against a null id — the shape `run_batch` already
    used when it cannot address the caller. `parse_body` also gained a
    `parse_constant` so the bare literals become the protocol's -32700 earlier;
    that is defence in depth, not the fix, since `1e400` is an ordinary number
    literal that `parse_float` overflows and `parse_constant` never sees.

    This is the exact trap app.py already documents one layer over, in
    `_invalid_request`: "A non-finite float round-trips through json.loads but
    not json.dumps, so rendering the 422 itself raised and the client got a 500
    instead." The MCP transport never got the same treatment — `_call` is
    careful to serialize the tool *result* with `default=str`, and the `id` half
    of the envelope is not sanitized at all.

    Observed, with a bearer from the real OAuth flow:

        POST /mcp  {"jsonrpc":"2.0","id":NaN,"method":"ping"}    -> 500
        POST /mcp  {"jsonrpc":"2.0","id":1e400,"method":"ping"}  -> 500
        POST /mcp  [{…id:1…},{…id:NaN…}]                         -> 500

    Two consequences past the status code. For `tools/call` the tool has ALREADY
    run when the envelope is serialized, so a real CalDAV write lands and the
    caller is told the call failed — a retry duplicates it (verified: an id of
    NaN on smylte_create_list 500s, and the list is there afterwards). And in a
    batch `run_batch` builds the whole list first, so one poisoned id discards
    all 50 replies, which is precisely what MAX_BATCH refuses over-long batches
    "whole, not truncated" to avoid.

    Asserted as "an answer a client can read", not as one particular repair:
    -32700 for the whole body, or a JSON-RPC error naming the id, or a reply
    addressed to null all satisfy this. A 500 does not.
    """
    r = mcp_post(body)

    assert r.status_code < 500, (
        f"a {label} id turned POST /mcp into {r.status_code}: {r.text[:200]!r}"
    )
    payload = r.json()                       # whatever it says, it must be JSON
    if r.status_code == 200:
        # A 200 is the protocol answering, so it has to be a JSON-RPC envelope.
        # A refusal (400 with -32700, or any 4xx document) is judged only on not
        # being a 500 — which shape it takes is the fix's business.
        messages = payload if isinstance(payload, list) else [payload]
        assert messages and all(
            isinstance(m, dict) and ("result" in m or "error" in m) for m in messages
        ), f"no JSON-RPC reply for a {label} id: {payload!r}"


# ── AUDIT: an explicit null on PATCH /api/scheduling/links/{token} ────────────

@pytest.mark.radicale
def test_a_null_booking_link_field_is_refused_not_a_half_applied_500(app_client):
    """FIXED. `EditBookingLink` types every field as `X | None` so it can be
    OMITTED, and the route selects by `model_fields_set` — so an explicitly-sent
    `null` WAS a *set* field whose value is None, forwarded verbatim. The route
    now refuses a null for the five NOT NULL columns, and `update_booking_link`
    runs inside `store.tx`, so a value the schema rejects can no longer leave
    the earlier fields committed. Originally: `_normalize_link_fields` rescues
    only `timezone`, `availability`, `show_busy` and `enabled`; `title`,
    `duration_minutes`, `buffer_minutes`, `min_notice_hours` and `horizon_days`
    pass through untouched and are all NOT NULL in db/schema.sql. SQLite raises
    `sqlite3.IntegrityError`, which is not a ValueError and matches none of the
    registered handlers, so it escapes as a 500 on an authenticated route.

    Worse, `store.update_booking_link` issues one UPDATE per field under
    `isolation_level=None` with no `store.tx()` around the loop — the discipline
    `reorder_tasks` adopted for exactly this reason — so every UPDATE before the
    failing one is already committed. Observed:

        PATCH /api/scheduling/links/T {"title":"Intro call","horizon_days":null}
          -> 500 Internal Server Error
        GET  /api/scheduling/links    -> title is now "Intro call", permanently

    The caller is told the request failed while half of it landed, and a retry
    of the same body 500s again forever. The MCP tool for the same operation is
    safe: its schema declares `"title": {"type": "string"}` and validate.py
    rejects a null before the service sees it — only the HTTP door has the hole.

    Deliberately not asserting WHICH 4xx, or even that it is a 4xx: dropping the
    nulls (a 200 that changes only the real fields) and refusing them (a 422
    that changes nothing) are both correct. What must hold either way is that
    the answer is not a 500, the row is still valid, and nothing was applied
    from a request that was refused.
    """
    cal = _new_calendar(app_client)
    r = app_client.post("/api/scheduling/links", json={
        "title": "Coffee chat", "calendar": cal["id"], "duration_minutes": 30,
        "timezone": "UTC", "availability": {"0": ["09:00-17:00"]},
        "min_notice_hours": 0, "horizon_days": 30,
    })
    assert r.status_code == 201, r.text
    token = r.json()["token"]

    def current() -> dict:
        links = app_client.get("/api/scheduling/links").json()
        return next(l for l in links if l["token"] == token)

    try:
        r = app_client.patch(f"/api/scheduling/links/{token}",
                             json={"title": "Intro call", "horizon_days": None})
        assert r.status_code < 500, (
            f"an explicit null horizon_days answered {r.status_code}: {r.text[:200]!r}"
        )
        after = current()
        assert isinstance(after["horizon_days"], int), (
            f"horizon_days is NOT NULL in the schema but the link now reads "
            f"{after['horizon_days']!r}"
        )
        if r.status_code >= 400:
            assert after["title"] == "Coffee chat", (
                "the PATCH was refused but the title changed anyway — the "
                "per-field UPDATE loop committed before it failed"
            )

        # The single-field form is a bare 500 on its own.
        r = app_client.patch(f"/api/scheduling/links/{token}",
                             json={"duration_minutes": None})
        assert r.status_code < 500, (
            f"an explicit null duration_minutes answered {r.status_code}: "
            f"{r.text[:200]!r}"
        )
    finally:
        app_client.delete(f"/api/scheduling/links/{token}")
        app_client.delete(f"/api/calendars/{cal['id']}")


# ── AUDIT: one U+FFFE in a calendar item kills the collection's sync ──────────

@pytest.mark.radicale
def test_a_body_xml_cannot_carry_stays_inside_the_dav_taxonomy(dav, collection):
    """Radicale copies a resource's iCalendar bytes verbatim into
    `<C:calendar-data>` with stdlib ElementTree, which does not validate
    characters. So a VTODO whose SUMMARY carries U+FFFE (or U+FFFF) produces a
    perfectly well-formed-looking 207 that lxml refuses — XML 1.0 §2.2 Char
    forbids exactly those two. `parse_multistatus` HAD no guard, so
    `lxml.etree.XMLSyntaxError` — not a `DavError` — came out of `multiget`,
    the only path that fetches bodies.

    Fixed in two halves, because the taxonomy wrap alone does not save the
    collection: `parse_multistatus` now parses with an explicit XMLParser and
    raises `DavError`, and `SyncEngine._multiget` refetches a failed batch one
    href at a time over GET, which parses no XML — so the poisoned resource
    costs one resource instead of the whole batch, reaches `_upsert_body`'s
    malformed-resource path, and the sync token advances again.

    That escapes the transport's own taxonomy, and lands past every place built
    to contain a bad resource: `SyncEngine._multiget` fails for the whole 50-item
    batch before `_upsert_body`'s explicit "one malformed foreign write must not
    wedge the collection's sync forever" guard can run, and `sync_all` swallows
    it per collection into `sync_state.last_error`, which nothing reads. The
    collection silently stops receiving any change from any client, forever.

    Reproduced here as it actually happens: a foreign client PUTs one ordinary
    VTODO, and this app's own DAV client cannot read it back —

        SUMMARY:groceries ￾          -> PUT 201 Created
        DavClient.multiget(...)     -> XMLSyntaxError: PCDATA invalid Char
                                       value 65534, line 7, column 19

    tests/test_dav_xml.py:184 pins the crash and reasons it away — "the callers
    all sit behind `_request`, which has already required a 207, so this only
    fires on a server that answered 207 with rubbish". That rationale is false:
    Radicale answers a valid 207 whose *payload* carries a character XML cannot.
    AUDIT.md:1420 closed this as a test gap asking for "whatever the chosen
    contract is — preferably a DavError, which requires wrapping
    etree.fromstring"; the wrap was never done, and AUDIT.md:1469 fixed this
    character class on the WRITE side only.

    Either contract passes here. A DavError is the transport saying "I could not
    read that", which callers already handle; a recovering parse that returns
    the batch (letting `_upsert_body` count the poisoned item as skipped) is
    strictly better. What must not happen is a foreign exception type escaping
    the DAV layer.
    """
    uid = uuid.uuid4().hex
    href = _foreign_put(collection.href, uid, (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign-client//EN\r\n"
        f"BEGIN:VTODO\r\nUID:{uid}\r\nDTSTAMP:20260101T000000Z\r\n"
        f"SUMMARY:groceries {FFFE}\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    ))

    try:
        items = dav.multiget(collection.href, [href])
    except DavError:
        return                      # in-taxonomy refusal: the caller can act
    except Exception as exc:        # noqa: BLE001 — the finding is the type
        pytest.fail(
            f"one U+FFFE in a foreign VTODO escaped the DAV taxonomy as "
            f"{type(exc).__name__}: {exc}"
        )
    assert isinstance(items, list)


# ── AUDIT: a boundary UNTIL overflows datetime instead of answering 4xx ───────

@pytest.mark.radicale
@pytest.mark.parametrize("case", ["foreign UNTIL=9999 dragged",
                                  "foreign UNTIL=9999 dragged a year",
                                  "repeat_until=9999-12-31"])
def test_a_boundary_until_answers_the_client_instead_of_overflowing(app_client, case):
    """FIXED. Two UNTIL writers added a timedelta or converted a zone with no
    range check; both now saturate to a representable bound first, and
    patch_event catches OverflowError beside the ValueError it already caught.
    Saturating rather than refusing is deliberate — refusing would leave a
    foreign 9999 series exactly as uneditable, only with a tidier status.
    Originally:

    `_shift_until` does `(until.astimezone(zone) + delta).astimezone(utc)`, so
    dragging a series whose rule carries `UNTIL=99991231T235959Z` — a real
    "forever" idiom written by Exchange/EWS exports and several CalDAV clients —
    steps past `datetime.max`. `_coerce_until` builds
    `datetime.combine(until, 23:59:59, tzinfo=dtstart.tzinfo)` and converts to
    UTC, so on any series anchored in a negative-offset zone (`TZID=America/
    Chicago`, i.e. most US users) "Repeat until 9999-12-31" converts to year
    10000 and overflows. `app._parse_datelike` accepts any date
    `date.fromisoformat` parses, and the SPA's "Repeat until" is an
    `<input type="date">` that happily yields 9999-12-31.

    `patch_event` maps only ValueError to 422 and OverflowError is not a
    ValueError, so both escape as a 500 — and because case 1's bad UNTIL is
    already stored, it reproduces on every retry: that series can never be
    dragged again. Observed end to end against scratch Radicale:

        foreign PUT RRULE:FREQ=YEARLY;UNTIL=99991231T235959Z    -> 201
        PATCH …/events/{uid} {"start":…+1d,"scope":"all",
                              "recurrence_id":…}                -> 500
        PATCH …/events/{uid} {"repeat":"weekly",
                              "repeat_until":"9999-12-31"}      -> 500
                              (on a DTSTART;TZID=America/Chicago series)

    The audit already fixed this class once — `smylte_find_free_time`'s
    OverflowError on the last representable day — and these two sites were
    missed. The mirror underflow is the same defect: `UNTIL=00010101T000000Z`
    dragged backwards hits "date value out of range" on the same lines.

    Asserted as "the caller gets an answer": clamping to datetime.max (a bound
    at the end of representable time IS "forever", which is what the writer
    meant) and refusing the date with a 422 are both correct, and both are the
    opposite of a traceback.
    """
    cal = _new_calendar(app_client)
    cal_href = f"/{USER}/{cal['id']}/"
    uid = uuid.uuid4().hex
    try:
        if case.startswith("foreign UNTIL=9999 dragged"):
            _foreign_put(cal_href, uid, _vevent(
                f"{uid}@tasksd",
                dtstart="DTSTART:20260106T090000Z", dtend="DTEND:20260106T093000Z",
                rrule="FREQ=YEARLY;UNTIL=99991231T235959Z",
            ))
            assert app_client.post("/api/sync").status_code == 200
            # A YEAR, not a day, for the second case. Saturating the INPUT
            # before the arithmetic survives only a delta smaller than the
            # guard, so a one-day drag passed against a half-fix while a real
            # reschedule still raised. The result is what has to be bounded.
            far = case.endswith("a year")
            body = {"start": "2027-01-07T09:00:00+00:00" if far
                             else "2026-01-07T09:00:00+00:00",
                    "end": "2027-01-07T09:30:00+00:00" if far
                           else "2026-01-07T09:30:00+00:00",
                    "scope": "all", "recurrence_id": "2026-01-06T09:00:00+00:00"}
        else:
            _foreign_put(cal_href, uid, _vevent(
                f"{uid}@tasksd",
                dtstart="DTSTART;TZID=America/Chicago:20260106T090000",
                dtend="DTEND;TZID=America/Chicago:20260106T093000",
                rrule="FREQ=WEEKLY;COUNT=6",
            ))
            assert app_client.post("/api/sync").status_code == 200
            body = {"repeat": "weekly", "repeat_until": "9999-12-31"}

        r = app_client.patch(f"/api/calendars/{cal['id']}/events/{uid}@tasksd", json=body)
        assert r.status_code < 500, (
            f"{case}: PATCH answered {r.status_code}: {r.text[:200]!r}"
        )
    finally:
        app_client.delete(f"/api/calendars/{cal['id']}")


# ── AUDIT: the XML-safe rule guards collection names but not item text ────────

@pytest.mark.radicale
def test_a_task_summary_cannot_carry_what_the_read_path_cannot_parse(app_client):
    """dav/xml.py states the XML-safe rule "has to hold in three places at once
    — the HTTP edge (app.CollectionName), the MCP tool schemas, and this
    backstop", because "widening it in one place silently drifted the others".
    It WAS enforced on exactly one field; the same alias now guards every field
    that reaches iCal, on both the HTTP and MCP surfaces. `CollectionName` carries
    `XML_SAFE_PATTERN_SCALAR` and the MCP collection-name schema carries
    `XML_SAFE_PATTERN`; `CreateTask.summary`/`notes`, `EditTask.*`,
    `CreateEvent.summary`/`location`/`description`, `tags` and the matching MCP
    schemas are bare strings with no pattern at all.

    The guard is on the field that could not do harm and absent from the ones
    that can. A collection name travels as PROPPATCH XML, where `_text` already
    backstops it and lxml would refuse it at build time. Task and event text is
    serialized into iCalendar and PUT as `text/calendar` — no XML, so no
    backstop fires — stored by Radicale, and read back inside
    `<C:calendar-data>`, where U+FFFE is unrepresentable and kills the parse for
    the whole collection (the companion parse_multistatus finding). That is what
    turns "a hostile foreign client can do this" into "the owner does it by
    pasting text out of a PDF".

    Observed:

        POST /api/lists/{id}/tasks {"summary": "notes ￾ pasted from a PDF"}
          -> 201, the task is created and visible, sync keeps succeeding
        …then, after the cache is rebuilt — which invariant #1 calls the
        documented recovery — that collection recovers 0 items.

    The same character in the list NAME is a 422, asserted below as the contrast
    the finding is about.

    Not asserting a status: refusing the character (a 422, matching what the
    collection name already does) and normalising it away are both fixes. What
    must not happen is the app storing, and echoing back, a value its own read
    path cannot carry.
    """
    r = app_client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    lst = r.json()
    try:
        # The contrast: the same character in the NAME — the harmless field.
        assert app_client.post("/api/lists", json={
            "name": f"L-{uuid.uuid4().hex[:8]}{FFFE}"
        }).status_code == 422

        r = app_client.post(f"/api/lists/{lst['id']}/tasks",
                            json={"summary": f"notes {FFFE} pasted from a PDF"})
        assert r.status_code < 500, r.text
        stored = r.json().get("summary", "") if r.status_code < 300 else ""
        assert FFFE not in stored, (
            f"POST /api/lists/{{id}}/tasks answered {r.status_code} and stored a "
            f"summary carrying U+FFFE, which no multistatus can carry back: "
            f"{stored!r}"
        )
    finally:
        # Delete the whole collection: while a poisoned item exists, every
        # subsequent read of this list is unparseable.
        app_client.delete(f"/api/lists/{lst['id']}")


@pytest.mark.radicale
def test_the_xml_safe_rule_refuses_only_what_xml_cannot_carry(app_client):
    """The control for the guard above, and the reason it is a character class
    rather than an ASCII whitelist.

    The rule excludes C0 controls (bar tab/LF/CR), surrogates and U+FFFE/U+FFFF —
    nothing else. A summary is the field people put emoji, accents and CJK in,
    and notes are multi-line by definition, so a guard that took any of those
    would be a worse bug than the one it fixed.
    """
    r = app_client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    lst = r.json()
    try:
        for label, text in [
            ("emoji", "Ship it 🚀"),
            ("ZWJ sequence", "👩‍💻 pair with 👨‍👩‍👧"),
            ("accents", "Café déjà vu — naïve"),
            ("CJK", "日本語のタスク"),
            ("RTL", "مهمة عربية"),
            ("newline", "line one\nline two"),
            ("tab", "a\tb"),
        ]:
            got = app_client.post(f"/api/lists/{lst['id']}/tasks",
                                  json={"summary": text})
            assert got.status_code == 201, f"{label} was refused: {got.text}"
            assert got.json()["summary"] == text, f"{label} did not round-trip"
    finally:
        app_client.delete(f"/api/lists/{lst['id']}")


@pytest.mark.radicale
def test_an_anonymous_booking_cannot_poison_the_target_calendar(app_client):
    """The sharpest instance of the same finding, and the one first missed.

    `PublicBook` is the only unauthenticated write path into the owner's
    calendar, and all three of its text fields reach the VEVENT: `name` and the
    link title become the SUMMARY, and `service.book` writes `f"Name: {name}"`
    and `f"Email: {email}"` into the DESCRIPTION. `email` was left a bare `str`
    when the guard first landed, on the assumption that `_EMAIL_RE` bounded it —
    it does not: the pattern only forbids `@` and whitespace, so
    `"ada\ufffe@example.com"` matches it happily.

    A stranger holding a booking link could therefore still write a character
    the app's own read path cannot parse, wedging that calendar's sync for every
    client. All three fields are asserted together because the guard is only
    worth anything if it has no gap.
    """
    cal = _new_calendar(app_client)
    r = app_client.post("/api/scheduling/links", json={
        "title": "Coffee", "calendar": cal["id"], "timezone": "UTC",
        "availability": {str(d): ["09:00-17:00"] for d in range(5)},
    })
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    try:
        for field, body in [
            ("email", {"name": "Ada", "email": f"ada{FFFE}@example.com"}),
            ("name", {"name": f"Ada{FFFE}", "email": "ada@example.com"}),
            ("notes", {"name": "Ada", "email": "ada@example.com",
                       "notes": f"see you {FFFE}"}),
        ]:
            got = app_client.post(f"/api/public/booking/{token}/book",
                                  json={"start": "2099-01-05T10:00:00+00:00", **body})
            assert got.status_code < 500, f"{field}: {got.text}"
            assert got.status_code != 201, (
                f"an anonymous booking wrote U+FFFE through {field!r} — that "
                f"calendar's sync is now unreadable to every client"
            )
    finally:
        app_client.delete(f"/api/calendars/{cal['id']}")


# ── AUDIT: smylte_delete_event skips the recurrence_id check HTTP performs ────

@pytest.mark.radicale
@pytest.mark.parametrize("bad", ["2026-09-08 09:00", "   ", "not-a-date"])
def test_a_malformed_recurrence_id_names_the_argument_not_the_server(mcp_stack, bad):
    """FIXED. `McpApi.delete_event` checked only that `recurrence_id` was
    non-empty; it now strips before that check and carries the `except
    ValueError -> ToolError` arm its sibling `update_event` already had.
    Originally: The
    HTTP route for the identical operation calls `_check_recurrence_id`, whose
    docstring spells out the missing half: "A non-ISO anchor is the other half:
    it reaches `date.fromisoformat` deep in the edit path, where the ValueError
    has no handler and escapes as a 500. Reject both here, where the client
    still gets a usable error." On the MCP path there is no ISO check and —
    unlike `update_event`, which wraps its service call in `except ValueError` —
    `delete_event` has no ValueError arm, so `_anchor_from_iso`'s ValueError
    reaches `McpServer._call`'s blanket handler.

    The mistake is not exotic: `_parse_dt`, the MCP API's own parser for every
    other date argument in the same file, deliberately accepts a space separator
    (`if "T" in s or " " in s`), so a model writing "2026-09-08 09:00" is
    following the convention the rest of the tool surface taught it. And
    `recurrence_id="   "` slips past `not recurrence_id` where HTTP uses
    `(recurrence_id or "").strip()`.

    Observed through the real tool table against a real daily series:

        tools/call smylte_delete_event {…,"scope":"this",
                                        "recurrence_id":"2026-09-08 09:00"}
        -> isError, "smylte_delete_event could not be completed (ValueError).
            The calendar server may be unreachable; try again shortly."

    That advice is wrong in the way that matters: the model is told to wait and
    retry an argument that will never work, forever. Over HTTP the identical
    anchor is a 422 saying `invalid recurrence_id`.

    Asserted as "the sentence is about the argument, not the backend" — an ISO
    check beside the scope guard, or the `except ValueError -> ToolError` arm
    update_event already has, both produce that; neither wording is required.
    """
    srv, cid, uid, scopes = mcp_stack
    reply = srv.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "smylte_delete_event", "arguments": {
            "calendar_id": cid, "uid": uid, "scope": "this", "recurrence_id": bad,
        }},
    }, scopes=scopes)

    blocks = (reply.get("result") or {}).get("content") or []
    text = " ".join(b.get("text", "") for b in blocks) + str(reply.get("error") or "")
    assert "calendar server" not in text.lower(), (
        f"recurrence_id={bad!r} was reported as a backend outage: {text!r}"
    )
    assert "recurrence" in text.lower() or bad.strip() in text, (
        f"recurrence_id={bad!r} was refused without saying which argument was "
        f"wrong: {text!r}"
    )


# ── AUDIT: the body-limit middleware's 413 is dead code on every route ────────

@pytest.mark.radicale
def test_a_chunked_oversized_body_is_a_413_through_the_real_app(_scratch_up, tmp_path):
    """`BodySizeLimitMiddleware` raises a private `_BodyTooLarge` out of
    `counting_receive` and catches it around the inner app to emit the 413. That
    `except` never fired for a FastAPI route: `get_request_handler` wraps the
    body read in `except Exception as e: raise HTTPException(400, "There was an
    error parsing the body")`, and `_BodyTooLarge` WAS an ordinary Exception. So
    the `started` flag, the `_too_large` fallback and its `Connection: close`
    were all unreachable on the router path.

    Fixed by making `_BodyTooLarge` an `HTTPException(413)`, which takes the
    `except HTTPException: raise` arm FastAPI keeps immediately above the
    generic one, commented "If a middleware raises an HTTPException, it should
    be raised again". The bare-ASGI path test_body_limit.py exercises still
    reaches the middleware's own handler.

    The memory bound itself still holds — the stream really is cut at the first
    over-cap chunk — so this is a contract defect rather than a hole. But the
    module docstring, `_too_large`'s comment ("The body was refused unread, so
    the connection cannot be reused") and tests/test_body_limit.py all assert a
    413 the app does not produce, and the connection is left reusable, so an
    attacker can pipeline oversized bodies down one socket.

    The test gap is why it survived. `test_a_chunked_body_is_cut_at_the_cap_not_
    buffered_whole` mounts the middleware over a bare `_echo_len` ASGI app, not
    over FastAPI, so it exercises a stack the app never runs; the only app-level
    test uses `json=`, which sets Content-Length and takes the cheap pre-check
    branch that never reaches the counting path. Nothing drives a chunked
    over-cap body through `create_app`. Observed:

        POST /api/login, chunked, no Content-Length, 200 x 64 KiB
          -> 400 {"detail":"There was an error parsing the body"}

    413 is the contract, and it is the assertion: raising an HTTPException(413)
    that FastAPI re-raises, or flagging the scope and emitting the response from
    the middleware, both satisfy it. The `Connection: close` header is
    deliberately NOT asserted — one of those repairs cannot carry it, and the
    status is what a client acts on.
    """
    cap = 4096
    settings = dataclasses.replace(api_settings(str(tmp_path / "cap.db")),
                                   max_body_bytes=cap)

    def chunks():
        for _ in range(20):                 # 20 x 64 KiB, no Content-Length
            yield b"x" * 65536

    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        r = c.post("/api/login", content=chunks(),
                   headers={"Content-Type": "application/json"})
        # The cap must not have broken ordinary logins in the process.
        ok = c.post("/api/login", json={"username": "admin", "password": OWNER_PASSWORD})

    assert ok.status_code == 200, ok.text
    assert r.status_code == 413, (
        f"a chunked over-cap body answered {r.status_code} {r.text[:120]!r} — the "
        f"middleware's 413 is unreachable behind FastAPI's body-parse handler"
    )
