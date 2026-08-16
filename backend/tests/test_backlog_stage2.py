"""Stage 2 of the audit backlog: abuse and resource exhaustion.

Work an adversary can make the server do out of proportion to what they spend,
plus one authorization defect that hands out a grant that cannot do anything.

**Stage 2 is CLOSED.** These began as xfail(strict=True) pins, each failing
against the code as it stood; the five findings are fixed and ticked in
docs/AUDIT.md, so the markers are gone and these are ordinary regression tests
that must stay green. The docstrings keep the past tense and the original
evidence, which is what stops the bug being reintroduced. See docs/STAGES.md.

These drive the real OAuth/MCP routes with the lifespan never entered and a stub
service standing in for the CalDAV side, so they need no scratch Radicale and run
everywhere the unit suite does.
"""
from __future__ import annotations

import asyncio
import dataclasses
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.db import store
from tasksd.mcp.server import run_batch
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage2]

ISSUER = "https://tasks.example.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "testpass123"


class _StubService:
    """`TaskService.oauth` is just "run this against the conn under the lock",
    so the OAuth store works with no CalDAV behind it at all."""

    def __init__(self) -> None:
        self._conn = store.connect(":memory:")
        store.init_db(self._conn)
        self._lock = threading.RLock()

    def oauth(self, fn, *a, **kw):
        with self._lock:
            return fn(self._conn, *a, **kw)


@pytest.fixture
def mcp(tmp_path):
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "b2.db")), mcp_enabled=True, public_url=ISSUER)
    app = create_app(settings)
    app.state.service = _StubService()      # no `with`: the lifespan never runs
    return TestClient(app)


def _register(client, **over) -> dict:
    r = client.post("/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none", **over})
    assert r.status_code == 201, r.text
    return r.json()


def _consent_blob(client, reg, *, scope, challenge="a" * 43) -> str:
    """The signed request the consent form posts back."""
    import re
    r = client.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "scope": scope, "resource": f"{ISSUER}/mcp",
    })
    assert r.status_code == 200, r.text
    m = re.search(r'name="request"\s+value="([^"]+)"', r.text)
    assert m, "no signed request on the consent page"
    return m.group(1)


# ── AUDIT: a JSON-RPC batch is unbounded ───────────────────────────────────

def test_a_json_rpc_batch_is_bounded():
    """_MAX_RPC_BYTES caps the BODY at 1 MB, but not the number of messages
    in it. `tools/list` is ~40 bytes of JSON, so one 1 MB POST WAS ~25 000
    messages, each dispatched serially into the service — under the global lock —
    with every reply accumulated in one list before anything was sent. Now capped
    at MAX_BATCH and refused whole rather than truncated."""
    class _CountingServer:
        def __init__(self) -> None:
            self.calls = 0

        def handle(self, message, *, scopes):
            self.calls += 1
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": {}}

    server = _CountingServer()
    huge = [{"jsonrpc": "2.0", "id": i, "method": "tools/list"} for i in range(25_000)]

    out = run_batch(server, huge, scopes={"mcp:read"})

    assert server.calls < len(huge), (
        f"all {server.calls} messages in a 25 000-message batch were dispatched; "
        f"a batch needs a length cap, not just a byte cap"
    )
    assert out is None or len(out) < len(huge)


# ── AUDIT: declining consent burns the password-guess budget ───────────────

def test_declining_consent_does_not_spend_the_password_budget(mcp):
    """`_throttle` ran before the action was even read, and only a SUCCESSFUL
    password calls `record_success`. Declining is not a failed guess — but it
    cost one, so a handful of "no thanks" clicks locked the owner out of
    connecting at all for the limiter's whole window.

    Fixed by splitting the counters, NOT by refunding on decline: `record_success`
    clears the whole budget, so refunding would have let an attacker alternate
    guess/deny and never lock out at all."""
    reg = _register(mcp)

    for _ in range(8):
        blob = _consent_blob(mcp, reg, scope="mcp:read mcp:write")
        r = mcp.post("/oauth/authorize",
                     data={"request": blob, "action": "deny"},
                     follow_redirects=False)
        assert r.status_code in (303, 400), r.status_code

    blob = _consent_blob(mcp, reg, scope="mcp:read mcp:write")
    r = mcp.post("/oauth/authorize",
                 data={"request": blob, "action": "approve", "grant": "full",
                       "username": "admin", "password": PASSWORD},
                 follow_redirects=False)
    assert r.status_code != 429, (
        "the owner is locked out of connecting after declining a few times; "
        "a decline is not a failed password guess"
    )


# ── AUDIT: "Read-only" on a write-only request mints an empty scope ────────

def test_read_only_on_a_write_only_request_does_not_mint_an_empty_scope(mcp):
    """The consent screen narrows with `granted &= {READ, OFFLINE}`. If the
    client asked for write only that intersection is empty — so approving minted
    a code for a token that could do nothing at all, surfacing later as an
    unexplained "not permitted" on every call, a long way from the screen that
    caused it. The page no longer offers the choice when it would grant nothing,
    and the POST refuses it regardless of what the page rendered."""
    reg = _register(mcp, scope="mcp:read mcp:write offline_access")
    blob = _consent_blob(mcp, reg, scope="mcp:write")

    r = mcp.post("/oauth/authorize",
                 data={"request": blob, "action": "approve", "grant": "read",
                       "username": "admin", "password": PASSWORD},
                 follow_redirects=False)

    if r.status_code == 303 and "code=" in r.headers.get("location", ""):
        pytest.fail("approved a write-only request as read-only, granting an empty scope")
    assert r.status_code in (400, 401, 422)


# ── AUDIT: /oauth/authorize hashes without the login_hashes semaphore ──────

def test_the_consent_password_check_is_concurrency_bounded(mcp, monkeypatch):
    """scrypt is memory-hard (~16 MiB a call). /api/login bounds how many run
    at once with `login_hashes = asyncio.Semaphore(4)` for exactly that reason.
    The consent POST ran the same hash on the same unauthenticated surface with
    no such bound, so N concurrent posts were N x 16 MiB. It now shares that one
    semaphore — the budget protected is the process's memory, not either
    endpoint's throughput."""
    from tasksd.auth import Authenticator

    live = 0
    peak = 0
    guard = threading.Lock()

    def _slow_check(self, username, password):
        nonlocal live, peak
        with guard:
            live += 1
            peak = max(peak, live)
        time.sleep(0.15)                    # stand in for the scrypt cost
        with guard:
            live -= 1
        return False

    monkeypatch.setattr(Authenticator, "check_credentials", _slow_check)

    reg = _register(mcp)
    blobs = [_consent_blob(mcp, reg, scope="mcp:read") for _ in range(12)]

    # Concurrency is driven on ONE event loop, via ASGITransport + gather — the
    # shape test_security.py's login-concurrency test already uses, and the shape
    # uvicorn actually runs. Threads over a bare TestClient would NOT model this:
    # each request spins its own short-lived portal and loop, so an
    # asyncio.Semaphore waiter parks on one loop while the release happens on
    # another and the test deadlocks — an artifact of the harness, not of the
    # server.
    async def hammer():
        transport = httpx.ASGITransport(app=mcp.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            await asyncio.gather(*[
                c.post("/oauth/authorize",
                       data={"request": b, "action": "approve", "grant": "full",
                             "username": "admin", "password": "wrong"})
                for b in blobs
            ])

    asyncio.run(hammer())

    assert peak <= 4, (
        f"{peak} scrypt hashes ran concurrently on the unauthenticated consent "
        f"endpoint; /api/login bounds the same work at 4"
    )


# ── AUDIT: _list_dto materialises every item row to count four numbers ────

def test_listing_lists_does_not_materialise_every_item_body(monkeypatch):
    """`_list_dto` called `store.get_items` — every column, `raw_ics` included —
    for every collection, purely to compute open_count / task_count /
    event_count / total. On an account with thousands of items that was the whole
    cache pulled into Python on every sidebar render, inside the global lock.

    Pinned by making the full-row read unavailable: the counts come from a COUNT
    query now, so listing must not need it."""
    from tasksd import service as service_mod

    def _forbidden(*a, **kw):
        raise AssertionError("list rendering pulled full item rows (raw_ics included)")

    monkeypatch.setattr(service_mod.store, "get_items", _forbidden)

    svc = service_mod.TaskService.__new__(service_mod.TaskService)
    svc._conn = store.connect(":memory:")
    store.init_db(svc._conn)
    svc._lock = threading.RLock()
    store.upsert_collection(
        svc._conn,
        __import__("tasksd.dav.client", fromlist=["CollectionInfo"]).CollectionInfo(
            href="/u/inbox/", displayname="Inbox", components={"VTODO"}),
    )

    svc.list_lists()
