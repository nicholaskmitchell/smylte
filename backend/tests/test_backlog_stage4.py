"""Stage 4 of the audit backlog: user-visible correctness and rendering.

Most of this stage is the SPA, pinned in frontend/src/backlog.stage4.test.tsx.
This is the one server-rendered page in it: the OAuth consent screen.

**Stage 4 is CLOSED** — this began as an xfail(strict=True) pin and is now an
ordinary regression test that must stay green. The SPA half lives in
frontend/src/backlog.stage4.test.tsx.
"""
from __future__ import annotations

import dataclasses
import re
import threading

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.db import store
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage4]

ISSUER = "https://tasks.example.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class _StubService:
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
        api_settings(str(tmp_path / "b4.db")), mcp_enabled=True, public_url=ISSUER)
    app = create_app(settings)
    app.state.service = _StubService()
    return TestClient(app)


# ── AUDIT: the consent screen forgets which app it is for ─────────────────

def test_the_consent_screen_still_names_the_app_after_a_bad_password(mcp):
    """`verify_request` rebuilds the AuthRequest from the signed blob, which
    carries client_id but not client_name — so it hardcodes `client_name=""` and
    `parse_authorize`'s "an application" fallback takes over.

    The first render said "Claude wants access"; mistype the password and the
    retry said "an application wants access". That is precisely the screen where
    the user is being asked to type their password and decide whether to trust a
    caller — and it stopped naming the caller at the moment they look hardest.
    Two independent finders reported this (filed twice in AUDIT.md, one problem).

    Fixed by re-resolving the name from the client_id the signed blob already
    carries, rather than widening the blob — which would have put an
    attacker-supplied name inside a signature.
    """
    r = mcp.post("/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none"})
    assert r.status_code == 201, r.text
    reg = r.json()

    first = mcp.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": "a" * 43,
        "code_challenge_method": "S256", "scope": "mcp:read",
        "resource": f"{ISSUER}/mcp"})
    assert first.status_code == 200
    assert "Claude" in first.text, "the first render should name the client"

    blob = re.search(r'name="request"\s+value="([^"]+)"', first.text).group(1)
    retry = mcp.post("/oauth/authorize", data={
        "request": blob, "action": "approve", "grant": "full",
        "username": "admin", "password": "wrong-on-purpose"})

    assert retry.status_code == 401
    assert "Claude" in retry.text, (
        "after a mistyped password the consent screen no longer names the "
        "application it is about to authorize"
    )
