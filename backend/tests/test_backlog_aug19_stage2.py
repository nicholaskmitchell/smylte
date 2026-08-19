"""Audit backlog, 2026-08-19 sweep — stage 2: abuse and resource exhaustion.

Six findings from the sweep of 2026-08-19, all of them **OPEN**. Unlike the
stage1–5 files beside this one — whose findings are closed and whose tests are
now ordinary regression tests — every test here is an `xfail(strict=True)` pin:
it asserts the behaviour the code SHOULD have and fails against the code as it
stands. CI stays green while the finding is open and goes red the moment it is
fixed, which is the signal to drop the marker and tick the finding off. The
harness is described in docs/STAGES.md.

Four of the six share one shape — work whose *cost* is chosen by whoever writes
the input, on a path that holds the service lock or that an anonymous caller can
reach. Every guard that exists there measures the wrong quantity:
`_pathological_rule` bounds how many instances a rule *emits* rather than how
long the library searches for them; `_reconcile_overrides` bounds the *rule* it
probes with and not the attacker-supplied *anchor* it probes at; `service.search`
bounds nothing at all; and `MAX_CLIENTS` bounds the table by locking the owner
out of it. The fifth is the missing control all of them assume exists: rotating
the app password — what docs/DEPLOY.md calls "signing out everywhere" — does not
reach the OAuth grants at all, so the documented incident response leaves a
30-day read/write backdoor open. The sixth is a validator that admits a byte its
own message says it refuses, which turns the single unauthenticated write path
into an href disclosure.

Three of these are pinned by a wall-clock budget, which deserves a word. Timing
is the user-visible symptom — the whole finding is "this takes seconds" — and
the alternative, counting iterations or asserting that a particular guard was
called, is exactly the over-specific structural pin docs/STAGES.md records as
having failed to recognise its own fix. One budget (1 s) serves all three. It
sits several times below what today's code costs — measured on this machine:
4.2 s, 12.8 s, 2.9 s — and one to three orders of magnitude above what the same
work costs once it is bounded: 2 ms for the override probe when the anchor is
near DTSTART, 0.09 s for the same search with the children map built once per
collection. Nothing a slow runner or a fast one does moves an answer across
that gap.
"""
from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from datetime import date

import pytest

from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import EventEdit, extract_from_raw, rrule_from_spec
from tasksd.ical.edit import apply_event_changes
from tasksd.ical.recur import expand_occurrences
from tasksd.mcp import oauth as O
from tests.helpers import foreign_event_raw, foreign_raw

pytestmark = [pytest.mark.backlog, pytest.mark.stage2]

# What "prompt" means for the three CPU-exhaustion pins. Generous by design: the
# point of each finding is a multi-second stall, not a millisecond one.
BUDGET_S = 1.0


def _elapsed(fn, *a, **kw):
    """(seconds, result-or-None). A refusal counts as a result: declining to do
    the work is a perfectly good fix, and the pin must not insist on either."""
    t0 = time.monotonic()
    try:
        out = fn(*a, **kw)
    except ValueError:
        out = None
    return time.monotonic() - t0, out


# ── AUDIT: a never-matching RRULE iterates to year 9999 ────────────────────

@pytest.mark.xfail(strict=True, reason="both pathology guards measure yield, not "
                                       "search: a zero-yield RRULE walks to MAXYEAR")
def test_a_rule_that_can_never_match_is_expanded_promptly():
    """`_pathological_rule` has two bounds and both count instances *emitted*:
    `_per_day` (density) and `_instances_before` (density x days to the window).
    Neither bounds the work dateutil does *looking* for an instance, so a rule
    whose BY* parts can never be satisfied scores as maximally safe — per_day 1,
    total ~212 — and then `rrule.between()` steps one day at a time from DTSTART
    to `datetime.MAXYEAR`, because "nothing ever matched" is dateutil's only
    other termination condition.

    FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30 is the shape (February has no 30th), and
    a foreign client can write it into the shared collection in 237 bytes. The
    cost does not depend on the window — this is a ONE-DAY query — and it is
    charged per RRULE and per VEVENT with no aggregate cap. Both public booking
    routes reach it through `_link_busy`, which holds the service lock across
    every VEVENT collection, so /api/lists, the calendar grid and /healthz all
    queue behind an anonymous GET.

    Measured against today's code: 4.18 s to return zero occurrences. This is a
    third axis distinct from the two closed guards — those refuse rules that
    emit too much; this one emits nothing at all.

    One measurement for whoever fixes it, because it rules out the obvious
    repair: clamping the rule's horizon to the window does NOT bound this.
    dateutil consults UNTIL and COUNT only when a candidate instance is
    produced, so with nothing ever matching it walks to MAXYEAR regardless —
    `FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30` costs 4.21 s bare, 4.12 s with
    `UNTIL=20260802T000000Z`, and 4.19 s with `COUNT=5`. The bound has to be on
    the search (a step or time budget, or a shape check that spots a BY* set
    that can never be satisfied), not on the yield. The pin asserts neither: any
    of them satisfies it.
    """
    raw = foreign_event_raw(
        "never@x", "Never", dtstart="20260101T090000Z", dtend="20260101T093000Z",
        rrule="FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30",
    )
    elapsed, occurrences = _elapsed(
        expand_occurrences, raw, date(2026, 8, 1), date(2026, 8, 2))

    # Either answer is correct — no occurrences, or a refusal to expand. What is
    # not correct is taking seconds to arrive at one.
    assert occurrences in (None, []), (
        f"a rule that can never match produced occurrences: {occurrences}")
    assert elapsed < BUDGET_S, (
        f"a one-day expansion of a zero-yield RRULE took {elapsed:.2f}s "
        f"(budget {BUDGET_S}s) — the search ran to year 9999. Both public "
        f"booking routes pay this, under the service lock, per RRULE and per "
        f"VEVENT in the resource."
    )


# ── AUDIT: _reconcile_overrides probes with an unbounded dateutil walk ──────

@pytest.mark.xfail(strict=True, reason="the override's RECURRENCE-ID is the probe "
                                       "target and is unbounded: ~2.9M iterations each")
def test_changing_the_repeat_is_prompt_with_a_far_future_override():
    """`_reconcile_overrides` documents its own cost guard — it whitelists FREQ
    to our own vocabulary because probing a foreign rule "means letting dateutil
    iterate from its DTSTART". That bounds the rule and not the probe *target*:
    `rr.between(at, at, inc=True)` is called once per override at `at` = the
    override's RECURRENCE-ID, which is attacker-controlled and unbounded. A
    far-future RECURRENCE-ID on a daily rule is ~2.9M iterations, and a foreign
    client can put any number of ~120-byte override components in one resource.

    The trigger is an ordinary action by the owner or an MCP agent: PATCH
    /api/calendars/{cal}/events/{uid} {"repeat":"daily"}. It runs inside the
    service's global lock, so every other request — /healthz and /api/login
    included — waits for it, and every retry pays again.

    Measured against today's code: 12.70 s for TWO overrides. `recur`'s guard
    exists to refuse exactly this class on the read path; the write path has no
    equivalent.
    """
    raw = foreign_event_raw(
        "s1@x", "Std", dtstart="20260106T090000Z", dtend="20260106T093000Z",
        rrule="FREQ=WEEKLY;COUNT=4",
        overrides=(
            ("RECURRENCE-ID:99991001T090000Z", "DTSTART:99991001T100000Z",
             "DTEND:99991001T103000Z", "SUMMARY:far one"),
            ("RECURRENCE-ID:99991002T090000Z", "DTSTART:99991002T100000Z",
             "DTEND:99991002T103000Z", "SUMMARY:far two"),
        ),
    )
    elapsed, out = _elapsed(
        apply_event_changes, raw, EventEdit(rrule=rrule_from_spec("daily")))

    # The edit must still have happened — a pin on time alone would be satisfied
    # by a version that gave up and wrote nothing.
    assert out is not None and b"FREQ=DAILY" in out, (
        "the repeat change did not land on the master")
    assert elapsed < BUDGET_S, (
        f"changing the repeat on an event carrying two far-future overrides "
        f"took {elapsed:.2f}s (budget {BUDGET_S}s) — ~6.4s per override, under "
        f"the global service lock. 100 override components is ~11 minutes."
    )


# ── AUDIT: service.search rebuilds the children map once per result row ────

def _svc_with_tasks(n: int, extra: tuple[tuple[str, str | None], ...] = ()):
    """A TaskService with no network: `search` is pure SQL plus DTO assembly.
    Same construction stage3's reorder pin uses."""
    from tasksd import service as service_mod

    svc = service_mod.TaskService.__new__(service_mod.TaskService)
    svc._conn = store.connect(":memory:")
    store.init_db(svc._conn)
    svc._lock = threading.RLock()
    svc._listeners, svc._loop = set(), None
    col = "/u/inbox/"
    store.upsert_collection(svc._conn, CollectionInfo(
        href=col, displayname="Inbox", components={"VTODO"}))

    def _add(uid: str, summary: str, parent: str | None = None) -> None:
        raw = foreign_raw(uid, summary,
                          extra=((f"RELATED-TO;RELTYPE=PARENT:{parent}",) if parent else ()))
        store.upsert_item(svc._conn, col, Item(f"{col}{uid}.ics", '"1"', raw),
                          extract_from_raw(raw))

    svc._conn.execute("BEGIN")
    for i in range(n):
        _add(f"t-{i}", f"alpha task {i}")
    for uid, parent in extra:
        _add(uid, f"zeta {uid}", parent)
    svc._conn.execute("COMMIT")
    return svc


@pytest.mark.xfail(strict=True, reason="_children_map is rebuilt inside the result "
                                       "loop, so search is O(rows x items)")
def test_searching_a_large_list_is_not_quadratic_in_the_lists_size():
    """`store.search` has no LIMIT, and `TaskService.search` calls
    `self._children_map(items)` *inside* the loop over the matching rows, where
    `items` is every VTODO in that row's collection. The map is a pure
    O(len(items)) rebuild with no memoisation, so the whole call is
    rows x items — quadratic in the size of the user's largest list, for a
    result the caller then paginates away. The per-collection `by_col` tuple was
    built to hoist exactly this kind of work out of the loop; categories,
    sidecar and items are all fetched once, and the children map is the one
    piece left inside.

    /api/search is reachable from `smylte_search_tasks`, which a READ-ONLY MCP
    grant may call, and mcp/tools.py paginates only after every DTO is built —
    so `limit=5` bounds nothing. A single-character query matches most of a
    list.

    Measured on this machine, one list of 3000 VTODOs: 2.87 s, against 0.09 s
    for the same work with the map computed once per collection (and 0.02 s for
    the FTS query itself). At 10 000 tasks the same call is ~33 s.

    The pin does not care HOW the result is bounded — hoisting the map, adding a
    LIMIT, or pushing the paging into SQL all satisfy it — so it asserts only
    that the answer arrives promptly and is still right about parent/child
    counts.
    """
    svc = _svc_with_tasks(3000, extra=(("zeta-parent", None),
                                       ("zeta-kid-1", "zeta-parent"),
                                       ("zeta-kid-2", "zeta-parent")))
    try:
        # Correctness first, on a query small enough that any LIMIT still
        # returns it: the children map must survive whatever bounds the cost.
        by_uid = {r["uid"]: r for r in svc.search("zeta")}
        assert by_uid["zeta-parent"]["child_count"] == 2, (
            f"the parent's children were lost: {by_uid['zeta-parent']}")

        elapsed, rows = _elapsed(svc.search, "alpha")
        assert rows, "the FTS query matched nothing — has the seed changed?"
        assert elapsed < BUDGET_S, (
            f"searching a 3000-task list took {elapsed:.2f}s (budget "
            f"{BUDGET_S}s) for {len(rows)} rows; the FTS query itself is ~0.02s. "
            f"An MCP connector with read-only scope can spend this per call."
        )
    finally:
        svc._conn.close()


# ── AUDIT: MAX_CLIENTS refuses new registrations instead of evicting ───────

@pytest.mark.radicale
@pytest.mark.xfail(strict=True, reason="a full oauth_clients table 429s the owner's "
                                       "own registration for a full CLIENT_IDLE_S")
def test_a_table_full_of_junk_clients_does_not_lock_the_owner_out(_scratch_up, tmp_path):
    """`register` sweeps with `gc_oauth` and then refuses outright at
    MAX_CLIENTS = 500. The cap is global but what it protects is not:
    `gc_oauth` only reclaims a client whose `last_used_at` is older than
    CLIENT_IDLE_S = 24 h, and `last_used_at` moves only in `touch_oauth_client`
    — which runs on code/token issue, i.e. only after somebody typed the app
    password. So 500 anonymous registrations pin the table for a full day, and
    for that day the OWNER cannot connect any MCP client at all: their own
    POST /oauth/register is 429 "too many registered clients".

    `_REGISTER_LIMITER` does not make this expensive to arrange — it is 20/hour
    per `limiter_key`, and `limiter_key` collapses IPv6 to a /64, so a /48 has
    65536 distinct keys. 500 rows a day is trivially cheap and repeatable.

    The seeded rows here hold no tokens, so any correct fix has something to
    reclaim — evicting the oldest token-less clients, scoping the cap per
    registrant, anything. The finding is not the cap, it is that the cap denies
    the feature to the legitimate user rather than to the registrant.

    Note this branch is uncovered today: `test_registration_is_capped` asserts
    only that *some* 429 appears within 40 requests, and instrumenting it shows
    the 429 arriving at request 21 from the rate limiter, with 20 client rows in
    the table. `count_oauth_clients(conn) >= MAX_CLIENTS` never executes.
    """
    from fastapi.testclient import TestClient

    from tasksd.app import create_app
    from tests.conftest import api_settings
    from tests.test_mcp import CALLBACK, ISSUER

    db = tmp_path / "cap.db"
    settings = dataclasses.replace(
        api_settings(str(db)), mcp_enabled=True, public_url=ISSUER)
    with TestClient(create_app(settings)) as c:
        # Fill the table the way an anonymous registrant would, via the store the
        # server itself uses. WAL: a second connection may write here.
        conn = store.connect(str(db))
        try:
            now = time.time()
            for i in range(O.MAX_CLIENTS):
                store.create_oauth_client(
                    conn, client_id=f"junk-{i}", client_secret_hash=None,
                    client_name="drive-by", redirect_uris=["https://x.test/cb"],
                    scope="mcp:read", now=now)
            assert store.count_oauth_clients(conn) >= O.MAX_CLIENTS
        finally:
            conn.close()

        r = c.post("/oauth/register", json={
            "client_name": "Claude", "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
        })

    assert r.status_code == 201, (
        f"the owner cannot register a client while the table is full of junk "
        f"that holds no tokens: {r.status_code} {r.text}"
    )
    assert r.json().get("client_id")


# ── AUDIT: rotating the app password does not revoke MCP grants ────────────

@pytest.mark.radicale
@pytest.mark.xfail(strict=True, reason="oauth_tokens carries no credential "
                                       "fingerprint, so no rotation reaches a grant")
def test_rotating_the_credentials_ends_an_mcp_grant_too(_scratch_up, tmp_path):
    """docs/DEPLOY.md §"If the password leaks — signing out everywhere" names
    two levers and calls each total: change the password ("Every existing
    session is refused from that moment") and rotate TASKS_SESSION_SECRET
    ("Every session dies, including yours"). auth.py backs the first with
    `_credential_version` — a `cv` claim stamped into every session JWT and
    re-checked on each request — and the second by construction. NEITHER reaches
    the OAuth tables: `oauth_tokens` carries no credential fingerprint,
    `verify_bearer` checks only kind/expiry/resource, and nothing on a
    credential change touches `oauth_tokens` or `oauth_clients`.

    The MCP consent screen IS the app password, so whoever has the password can
    mint an `mcp:read mcp:write offline_access` grant and then survive the
    entire documented incident response with full read/write on every task,
    list, calendar, event and booking. The refresh token is the serious half:
    it does not merely outlive the rotation, it keeps rotating for
    REFRESH_TTL_S = 30 days, each rotation re-arming another 30.

    This applies BOTH remediations at once, in the order the runbook gives them,
    and checks the session lever still works as documented (it does — that
    assertion passes) before asking the same of the grant.

    Any binding satisfies the pin: a `cv` column on `oauth_tokens`, a startup
    sweep when the fingerprint changes, anything that stops a pre-rotation
    bearer and its refresh token from working afterwards.
    """
    from fastapi.testclient import TestClient

    from tasksd.app import create_app
    from tests.conftest import api_settings
    from tests.test_mcp import ISSUER, MCP_URL, PASSWORD, _connect, _rpc

    settings = dataclasses.replace(
        api_settings(str(tmp_path / "rotate.db")), mcp_enabled=True, public_url=ISSUER)

    with TestClient(create_app(settings)) as c:
        grant = _connect(c)
        assert _rpc(c, grant["access_token"], "ping").status_code == 200
        assert c.post("/api/login", json={
            "username": "admin", "password": PASSWORD}).status_code == 200
        assert c.get("/api/me").status_code == 200
        cookies = dict(c.cookies)

    # The documented response, to the letter: regenerate the credential, then
    # rotate the signing secret. Same database — only the credentials moved.
    rotated = dataclasses.replace(
        settings, auth_password="a-brand-new-password", session_secret="z" * 40)
    with TestClient(create_app(rotated)) as c2:
        c2.cookies.update(cookies)
        assert c2.get("/api/me").status_code == 401, (
            "the session lever itself is broken — this test is measuring the "
            "wrong thing")

        ping = _rpc(c2, grant["access_token"], "ping")
        refresh = c2.post("/oauth/token", data={
            "grant_type": "refresh_token", "refresh_token": grant["refresh_token"],
            "client_id": grant["reg"]["client_id"], "resource": MCP_URL,
        })

    assert ping.status_code == 401, (
        f"a pre-rotation MCP access token still works after BOTH documented "
        f"remedies: POST /mcp ping -> {ping.status_code}"
    )
    assert refresh.status_code != 200, (
        f"the pre-rotation refresh token still mints new access tokens after "
        f"both remedies: {refresh.status_code} {refresh.text[:200]} — the "
        f"attacker re-arms another {O.REFRESH_TTL_S // 86400} days on each use"
    )


# ── AUDIT: _CLIENT_ID_RE accepts a trailing newline ────────────────────────

@pytest.mark.radicale
@pytest.mark.xfail(strict=True, reason="`$` matches before a trailing newline, so a "
                                       "hex+\\n client_id reaches the href slug")
def test_a_client_id_with_a_trailing_newline_is_refused(client):
    """`_CLIENT_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")` is used with
    `re.match`, and Python's `$` matches at end-of-string OR just before a
    trailing newline — so "0123456789abcdef\\n" passes a validator whose message
    says "16-64 lowercase hex characters" and whose comment says the value must
    stay in Radicale's canonical URL-safe form.

    That value becomes the resource slug (`href = f"{collection_href}{slug}.ics"`)
    and the UID (`f"{slug}@tasksd"`), and CPython's urlsplit strips the newline
    out of the URL — so the PUT lands on the resource belonging to the newline-
    free client_id. On the one UNAUTHENTICATED write path this means:

      1. client_id X and X\\n address the same Radicale resource but carry
         different UIDs, so `_put_new` takes a 412, refetches, sees a UID
         mismatch and raises ConflictError("a different resource already exists
         at {href}") — which app.py hands to the anonymous caller verbatim as a
         409 body, disclosing the Radicale username and the target collection's
         href. test_public_page_requires_no_auth_and_leaks_nothing asserts the
         public payload carries no hrefs at all; this route hands one over.
      2. A raw control character reaches items.uid, bookings.event_uid and the
         ICS UID, and an items row is written for an href that does not exist on
         the server.

    The probe is free: the route's `except BaseException` releases the link's
    rate-limit credit, so a refused booking costs nothing.

    Pinned end-to-end because the leak is the interesting half. Any rejection
    satisfies it — `re.fullmatch`, `\\Z`, an explicit charset check — as long as
    the value never becomes a slug.
    """
    cal = client.post("/api/calendars",
                      json={"name": f"C-{uuid.uuid4().hex[:8]}"})
    assert cal.status_code == 201, cal.text
    cal = cal.json()
    try:
        # A wide horizon on purpose: busy-checking is global, so events other
        # test files leave on the shared scratch server eat a narrow window.
        link = client.post("/api/scheduling/links", json={
            "title": "Coffee chat", "calendar": cal["id"], "duration_minutes": 30,
            "timezone": "UTC",
            "availability": {str(d): ["00:00-23:30"] for d in range(7)},
            "min_notice_hours": 0, "horizon_days": 14,
        })
        assert link.status_code == 201, link.text
        token = link.json()["token"]

        no_cookie = {"Cookie": ""}
        info = client.get(f"/api/public/booking/{token}", headers=no_cookie).json()
        assert len(info["slots"]) >= 2, "the link offered fewer than two free slots"
        # The far END of the horizon, ~two weeks out: busy is global on the
        # shared scratch server, and a booking near today would compete for the
        # slots the tests with a 3-day horizon depend on.
        late, later = info["slots"][-1], info["slots"][-2]

        # Book from an address of our own so the two POSTs do not spend the
        # session-wide 15/hour anonymous budget every other test shares. Same
        # shape as test_scheduling.py's `many_ips`: a second transport onto the
        # already-running app (entering a TestClient would run the lifespan and
        # shut the session-scoped app down), presenting as loopback so the
        # X-Real-IP header is trusted.
        from fastapi.testclient import TestClient

        visitor = TestClient(client.app, client=("127.0.0.1", 1))
        headers = {**no_cookie, "X-Real-IP": "198.51.100.7"}

        cid = uuid.uuid4().hex[:16]
        first = visitor.post(
            f"/api/public/booking/{token}/book", headers=headers, json={
                "start": late["start"], "name": "Ada",
                "email": "ada@example.com", "client_id": cid,
            })
        assert first.status_code == 201, first.text

        second = visitor.post(
            f"/api/public/booking/{token}/book", headers=headers, json={
                "start": later["start"], "name": "Eve",
                "email": "eve@example.com", "client_id": cid + "\n",
            })
    finally:
        # The booking wrote a real VEVENT to the shared scratch server; dropping
        # the calendar takes it and the link with it.
        client.delete(f"/api/calendars/{cal['id']}")

    body = second.text
    assert second.status_code in (400, 422), (
        f"a client_id of 16 hex characters plus a newline was accepted as a "
        f"resource slug; the anonymous caller got {second.status_code} {body[:300]}"
    )
    assert ".ics" not in body and "/" not in body, (
        f"the 409 body hands an anonymous caller an internal CalDAV href: {body[:300]}"
    )
