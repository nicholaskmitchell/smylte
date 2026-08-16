"""Stage 2 of the audit backlog: abuse and resource exhaustion.

Work an adversary can make the server do out of proportion to what they spend,
plus one authorization defect that hands out the wrong grant. See the header of
test_backlog_stage1.py for how the xfail(strict=True) harness works, and
docs/STAGES.md for the staging.

These drive the real OAuth/MCP routes with the lifespan never entered and a stub
service standing in for the CalDAV side, so they need no scratch Radicale and run
everywhere the unit suite does.
"""
from __future__ import annotations

import dataclasses
import threading
import time

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.db import store
from tasksd.mcp.server import run_batch
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage2]

XFAIL = dict(strict=True)
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

@pytest.mark.xfail(reason="AUDIT open: server.py:228 unbounded batch", **XFAIL)
def test_a_json_rpc_batch_is_bounded():
    """_MAX_RPC_BYTES caps the BODY at 1 MB, but not the number of messages in
    it. `tools/list` is ~40 bytes of JSON, so one 1 MB POST is ~25 000 messages,
    each dispatched serially into the service — under the global lock — with
    every reply accumulated in one list before anything is sent."""
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

@pytest.mark.xfail(reason="AUDIT open: routes.py:234 decline burns the budget", **XFAIL)
def test_declining_consent_does_not_spend_the_password_budget(mcp):
    """`_throttle` runs before the action is even read, and only a SUCCESSFUL
    password calls `record_success`. Declining is not a failed guess — but it
    costs one, so a handful of "no thanks" clicks lock the owner out of
    connecting at all for the limiter's whole window."""
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

@pytest.mark.xfail(reason="AUDIT open: routes.py:255 empty granted scope", **XFAIL)
def test_read_only_on_a_write_only_request_does_not_mint_an_empty_scope(mcp):
    """The consent screen narrows with `granted &= {READ, OFFLINE}`. If the
    client asked for write only, that intersection is empty — so approving mints
    a code for a token that can do nothing at all, and the failure surfaces
    later as unexplained "not permitted" on every call. The request should be
    refused (or the choice not offered) rather than silently granting nothing."""
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

@pytest.mark.xfail(reason="AUDIT open: routes.py:259 unbounded scrypt concurrency", **XFAIL)
def test_the_consent_password_check_is_concurrency_bounded(mcp, monkeypatch):
    """scrypt is memory-hard (~16 MiB a call). /api/login bounds how many run at
    once with `login_hashes = asyncio.Semaphore(4)` (app.py:1169) for exactly
    that reason. The consent POST runs the same hash on the same unauthenticated
    surface with no such bound, so N concurrent posts are N x 16 MiB."""
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

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda b: mcp.post(
            "/oauth/authorize",
            data={"request": b, "action": "approve", "grant": "full",
                  "username": "admin", "password": "wrong"}), blobs))

    assert peak <= 4, (
        f"{peak} scrypt hashes ran concurrently on the unauthenticated consent "
        f"endpoint; /api/login bounds the same work at 4"
    )


# ── AUDIT: _list_dto materialises every item row to count four numbers ────

@pytest.mark.xfail(reason="AUDIT open: service.py:145 full scan per list", **XFAIL)
def test_listing_lists_does_not_materialise_every_item_body(monkeypatch):
    """`_list_dto` calls `store.get_items` — every column, `raw_ics` included —
    for every collection, purely to compute open_count / task_count /
    event_count / total. On an account with thousands of items that is the whole
    cache pulled into Python on every sidebar render, inside the global lock.

    Pinned by making the full-row read unavailable: counts should come from a
    COUNT query, so listing must not need it."""
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
