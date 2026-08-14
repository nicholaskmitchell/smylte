"""The remote MCP connector: its OAuth authorization server and its transport.

These run the flow a Claude custom connector actually performs — discover,
register, authorize with a password, exchange a PKCE code, call a tool, refresh
— and then attack each step. The security assertions are the point: the whole
feature is a second front door onto the same data, so what must NOT work matters
more than what must.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tests.conftest import api_settings

pytestmark = pytest.mark.radicale

ISSUER = "https://tasks.example.test"
MCP_URL = f"{ISSUER}/mcp"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "testpass123"


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


@pytest.fixture
def mcp(_scratch_up, tmp_path):
    """A fresh app with the connector enabled, and no session cookie anywhere —
    every one of these routes has to stand on its own."""
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "mcp.db")),
        mcp_enabled=True, public_url=ISSUER,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _register(client, **over) -> dict:
    body = {
        "client_name": "Claude",
        "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        **over,
    }
    r = client.post("/oauth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _authorize(client, reg, challenge, *, scope="mcp:read mcp:write offline_access",
               grant="full", password=PASSWORD, follow=False):
    """Drive the consent screen the way a browser would."""
    params = {
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "xyz",
        "scope": scope, "resource": MCP_URL,
    }
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200, page.text
    signed = re.search(r'name="request" value="([^"]+)"', page.text).group(1)
    return client.post("/oauth/authorize", data={
        "request": signed, "action": "approve", "grant": grant,
        "username": "admin", "password": password,
    }, follow_redirects=follow)


def _code_from(resp) -> str:
    return parse_qs(urlsplit(resp.headers["location"]).query)["code"][0]


def _token(client, reg, code, verifier, **over) -> dict:
    form = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": CALLBACK, "client_id": reg["client_id"],
        "code_verifier": verifier, "resource": MCP_URL, **over,
    }
    return client.post("/oauth/token", data=form)


def _connect(client) -> dict:
    """The whole happy path, for tests that need a working token."""
    reg = _register(client)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(client, reg, challenge))
    r = _token(client, reg, code, verifier)
    assert r.status_code == 200, r.text
    return {"reg": reg, **r.json()}


def _rpc(client, token, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers={
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": "2025-06-18",
    })


def _call(client, token, name, args=None):
    r = _rpc(client, token, "tools/call", {"name": name, "arguments": args or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


# ── the endpoint is not there unless it is asked for ────────────────────────

def test_disabled_by_default(client):
    """The shared app fixture has no MCP settings, so nothing may be reachable —
    an upgrade must not open an auth surface on its own."""
    for path in ("/mcp", "/oauth/token", "/oauth/register"):
        assert client.post(path, json={}).status_code in (404, 405)
    assert client.get("/.well-known/oauth-protected-resource").status_code in (404, 405)


def test_refuses_to_start_without_what_it_needs(_scratch_up, tmp_path):
    base = dataclasses.replace(
        api_settings(str(tmp_path / "x.db")), mcp_enabled=True, public_url=ISSUER)
    # No public URL: the metadata would have to guess, from a header the caller sets.
    with pytest.raises(RuntimeError, match="TASKS_PUBLIC_URL"):
        create_app(dataclasses.replace(base, public_url=""))
    # No password: nothing at the consent screen proves you are the owner.
    with pytest.raises(RuntimeError, match="TASKS_AUTH_ENABLED"):
        create_app(dataclasses.replace(base, auth_enabled=False))
    # No session secret: consent signatures would not survive a restart.
    with pytest.raises(RuntimeError, match="TASKS_SESSION_SECRET"):
        create_app(dataclasses.replace(base, session_secret=""))


# ── discovery ────────────────────────────────────────────────────────────────

def test_protected_resource_metadata(mcp):
    for path in ("/.well-known/oauth-protected-resource",
                 "/.well-known/oauth-protected-resource/mcp"):
        doc = mcp.get(path)
        assert doc.status_code == 200, path
        body = doc.json()
        # Claude compares this to the URL the user typed; a mismatch is the
        # single most common reason a reachable server still fails to connect.
        assert body["resource"] == MCP_URL
        assert body["authorization_servers"] == [ISSUER]
        assert "mcp:read" in body["scopes_supported"]


def test_authorization_server_metadata(mcp):
    body = mcp.get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == ISSUER
    assert body["code_challenge_methods_supported"] == ["S256"]   # never 'plain'
    assert body["registration_endpoint"] == f"{ISSUER}/oauth/register"
    # Claude's DCR client is public, so it authenticates as "none" at the token
    # endpoint; without this advertised it will not attempt the flow.
    assert "none" in body["token_endpoint_auth_methods_supported"]
    assert "offline_access" in body["scopes_supported"]
    assert set(body["grant_types_supported"]) == {"authorization_code", "refresh_token"}


def test_unauthorized_mcp_points_at_the_metadata(mcp):
    """The 401 is the start of discovery. Without the resource_metadata pointer
    a client that has never seen this server cannot find the auth server."""
    r = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{ISSUER}/.well-known/oauth-protected-resource"' in challenge


# ── the happy path ───────────────────────────────────────────────────────────

def test_full_connector_flow(mcp):
    grant = _connect(mcp)
    assert grant["token_type"] == "Bearer"
    assert grant["expires_in"] == 3600
    assert "refresh_token" in grant

    init = _rpc(mcp, grant["access_token"], "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}}).json()["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "smylte"

    tools = _rpc(mcp, grant["access_token"], "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"smylte_list_lists", "smylte_create_task", "smylte_list_events",
            "smylte_find_free_time"} <= names
    # Every tool has to be self-describing enough to use without the app in view.
    for t in tools:
        assert t["name"].startswith("smylte_")
        assert len(t["description"]) > 40
        assert t["inputSchema"]["type"] == "object"
        assert "readOnlyHint" in t["annotations"]


def test_tools_round_trip_real_data(mcp):
    token = _connect(mcp)["access_token"]
    created = _call(mcp, token, "smylte_create_list",
                    {"name": f"MCP {uuid.uuid4().hex[:6]}"})
    list_id = created["structuredContent"]["id"]

    made = _call(mcp, token, "smylte_create_task", {
        "list_id": list_id, "summary": "Renew passport",
        "due": "2026-09-01", "priority": "high", "tags": ["admin"],
    })["structuredContent"]
    assert made["summary"] == "Renew passport" and made["priority_label"] == "high"

    listed = _call(mcp, token, "smylte_list_tasks", {"list_id": list_id})
    assert listed["structuredContent"]["total"] == 1

    found = _call(mcp, token, "smylte_search_tasks", {"query": "passport"})
    assert any(t["uid"] == made["uid"] for t in found["structuredContent"]["tasks"])

    done = _call(mcp, token, "smylte_complete_task",
                 {"list_id": list_id, "uid": made["uid"]})["structuredContent"]
    assert done["completed"] is True
    # Completed work drops out of the default view but is still there on request.
    assert _call(mcp, token, "smylte_list_tasks",
                 {"list_id": list_id})["structuredContent"]["total"] == 0
    assert _call(mcp, token, "smylte_list_tasks",
                 {"list_id": list_id, "include_done": True})["structuredContent"]["total"] == 1

    _call(mcp, token, "smylte_delete_list", {"list_id": list_id})


def test_a_tool_failure_is_an_answer_not_a_crash(mcp):
    """A model can act on a sentence; it can do nothing with a 500."""
    token = _connect(mcp)["access_token"]
    out = _call(mcp, token, "smylte_list_tasks", {"list_id": "no-such-list"})
    assert out["isError"] is True
    assert "no-such-list" in out["content"][0]["text"]
    assert "smylte_list_lists" in out["content"][0]["text"]   # says what to do instead


def test_unknown_tool_and_bad_arguments_are_readable(mcp):
    token = _connect(mcp)["access_token"]
    err = _rpc(mcp, token, "tools/call", {"name": "smylte_nope"}).json()["error"]
    assert "tools/list" in err["message"]
    err = _rpc(mcp, token, "tools/call",
               {"name": "smylte_list_lists", "arguments": {"bogus": 1}}).json()["error"]
    assert "bogus" in err["message"]
    err = _rpc(mcp, token, "tools/call",
               {"name": "smylte_get_task", "arguments": {"list_id": "x"}}).json()["error"]
    assert "uid" in err["message"]


def test_notifications_get_202_and_no_body(mcp):
    token = _connect(mcp)["access_token"]
    r = mcp.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 202 and not r.content


def test_get_and_delete_are_405(mcp):
    """No server-initiated stream and no session to end — which is also why the
    long-lived-stream auth problem cannot arise here."""
    token = _connect(mcp)["access_token"]
    for method in (mcp.get, mcp.delete):
        r = method("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 405 and r.headers["allow"] == "POST"


def test_protocol_version_is_negotiated(mcp):
    token = _connect(mcp)["access_token"]
    for asked in ("2025-06-18", "2025-03-26", "2024-11-05"):
        got = _rpc(mcp, token, "initialize",
                   {"protocolVersion": asked}).json()["result"]["protocolVersion"]
        assert got == asked
    # One we do not know: answer with ours rather than failing the handshake.
    got = _rpc(mcp, token, "initialize",
               {"protocolVersion": "1999-01-01"}).json()["result"]["protocolVersion"]
    assert got == "2025-06-18"
    # …but an unsupported version in the HTTP header is a 400, per the spec.
    bad = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                   headers={"Authorization": f"Bearer {token}",
                            "MCP-Protocol-Version": "1999-01-01"})
    assert bad.status_code == 400


# ── the password is the gate ─────────────────────────────────────────────────

def test_no_token_without_the_password(mcp):
    """The whole point of the feature: knowing the URL is not enough."""
    reg = _register(mcp)
    _, challenge = _pkce()
    denied = _authorize(mcp, reg, challenge, password="wrong-password")
    assert denied.status_code == 401
    assert "not right" in denied.text
    assert "code=" not in denied.text


def test_declining_sends_back_an_error_not_a_code(mcp):
    reg = _register(mcp)
    _, challenge = _pkce()
    page = mcp.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "xyz", "resource": MCP_URL,
    })
    signed = re.search(r'name="request" value="([^"]+)"', page.text).group(1)
    r = mcp.post("/oauth/authorize", data={"request": signed, "action": "deny"},
                 follow_redirects=False)
    query = parse_qs(urlsplit(r.headers["location"]).query)
    assert query["error"] == ["access_denied"] and "code" not in query


def test_consent_post_must_carry_a_request_this_server_issued(mcp):
    """Without this, a phishing page could post its own client_id here and take
    the code while the user believed they were signing in."""
    reg = _register(mcp)
    _, challenge = _pkce()
    forged = mcp.post("/oauth/authorize", data={
        "request": "not.a.signature", "action": "approve",
        "username": "admin", "password": PASSWORD,
    })
    assert forged.status_code == 400
    assert "location" not in forged.headers


def test_consent_screen_names_where_the_code_goes(mcp):
    """The redirect host is the one thing that distinguishes a real client from
    one that merely calls itself Claude."""
    reg = _register(mcp, client_name="Definitely Claude",
                    redirect_uris=["https://evil.example/cb"])
    _, challenge = _pkce()
    page = mcp.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": "https://evil.example/cb", "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": MCP_URL,
    })
    assert "evil.example" in page.text


# ── PKCE ─────────────────────────────────────────────────────────────────────

def test_pkce_is_mandatory_and_s256_only(mcp):
    reg = _register(mcp)
    _, challenge = _pkce()
    base = {"response_type": "code", "client_id": reg["client_id"],
            "redirect_uri": CALLBACK, "resource": MCP_URL}
    # No challenge at all.
    r = mcp.get("/oauth/authorize", params=base, follow_redirects=False)
    assert r.status_code == 303 and "code_challenge" in r.headers["location"]
    # 'plain' is refused: it offers no protection against a stolen code.
    r = mcp.get("/oauth/authorize", follow_redirects=False, params={
        **base, "code_challenge": challenge, "code_challenge_method": "plain"})
    assert r.status_code == 303 and "S256" in r.headers["location"]


def test_a_wrong_verifier_cannot_redeem_the_code(mcp):
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge))
    other, _ = _pkce()
    bad = _token(mcp, reg, code, other)
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # …and the code is spent regardless, so the real client cannot use it either.
    assert _token(mcp, reg, code, verifier).status_code == 400


def test_a_code_is_single_use(mcp):
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge))
    assert _token(mcp, reg, code, verifier).status_code == 200
    again = _token(mcp, reg, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_a_code_cannot_be_redeemed_by_another_client(mcp):
    victim = _register(mcp)
    attacker = _register(mcp, client_name="Someone else")
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, victim, challenge))
    stolen = _token(mcp, attacker, code, verifier)
    assert stolen.status_code == 400 and stolen.json()["error"] == "invalid_grant"


def test_the_redirect_uri_must_match_the_one_the_code_was_issued_for(mcp):
    reg = _register(mcp, redirect_uris=[CALLBACK, "https://claude.ai/other"])
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge))
    r = _token(mcp, reg, code, verifier, redirect_uri="https://claude.ai/other")
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


# ── redirect URI handling ────────────────────────────────────────────────────

def test_an_unregistered_redirect_is_never_redirected_to(mcp):
    """An unvalidated redirect_uri is an open redirect; these two failures have
    to be rendered here rather than bounced onward."""
    reg = _register(mcp)
    _, challenge = _pkce()
    r = mcp.get("/oauth/authorize", follow_redirects=False, params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": "https://evil.example/steal",
        "code_challenge": challenge, "code_challenge_method": "S256"})
    assert r.status_code == 400 and "location" not in r.headers

    r = mcp.get("/oauth/authorize", follow_redirects=False, params={
        "response_type": "code", "client_id": "nope",
        "redirect_uri": CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    assert r.status_code == 400 and "location" not in r.headers


@pytest.mark.parametrize("uri", [
    "http://evil.example/cb",          # plain http to a real host
    "javascript:alert(1)",             # not a URL we would ever send a browser to
    "ftp://example.com/cb",
    "https://example.com/cb#frag",     # a fragment would carry the code oddly
])
def test_registration_refuses_a_dangerous_redirect(mcp, uri):
    r = mcp.post("/oauth/register", json={"redirect_uris": [uri]})
    assert r.status_code == 400, uri
    assert r.json()["error"] == "invalid_redirect_uri"


def test_loopback_ignores_the_port_but_nothing_else_does(mcp):
    """RFC 8252: a native client binds an ephemeral port it cannot register.
    Claude Code depends on this; everything else still matches exactly."""
    reg = _register(mcp, redirect_uris=["http://localhost/callback"])
    _, challenge = _pkce()
    ok = mcp.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": "http://localhost:53118/callback",
        "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": MCP_URL})
    assert ok.status_code == 200
    # A different path on loopback is still a different URI.
    bad = mcp.get("/oauth/authorize", follow_redirects=False, params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": "http://localhost:53118/elsewhere",
        "code_challenge": challenge, "code_challenge_method": "S256"})
    assert bad.status_code == 400


# ── audience binding ─────────────────────────────────────────────────────────

def test_a_token_for_another_resource_is_refused(mcp):
    reg = _register(mcp)
    _, challenge = _pkce()
    r = mcp.get("/oauth/authorize", follow_redirects=False, params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": "https://elsewhere.example/mcp"})
    assert r.status_code == 303
    assert "invalid_target" in r.headers["location"]


def test_resource_is_compared_canonically(mcp):
    """Case in scheme and host, and a trailing slash, are the same resource —
    the spec asks servers to be robust about exactly this."""
    reg = _register(mcp)
    _, challenge = _pkce()
    for spelling in (MCP_URL, MCP_URL + "/", MCP_URL.replace("https", "HTTPS")):
        r = mcp.get("/oauth/authorize", params={
            "response_type": "code", "client_id": reg["client_id"],
            "redirect_uri": CALLBACK, "code_challenge": challenge,
            "code_challenge_method": "S256", "resource": spelling})
        assert r.status_code == 200, spelling


# ── scopes ───────────────────────────────────────────────────────────────────

def test_read_only_consent_blocks_every_write(mcp):
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, grant="read"))
    granted = _token(mcp, reg, code, verifier).json()
    assert "mcp:write" not in granted["scope"]
    token = granted["access_token"]

    assert _call(mcp, token, "smylte_list_lists")["isError"] is False
    err = _rpc(mcp, token, "tools/call", {
        "name": "smylte_create_list", "arguments": {"name": "nope"}}).json()["error"]
    assert "write access" in err["message"]


def test_a_refresh_cannot_widen_scope(mcp):
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, grant="read"))
    granted = _token(mcp, reg, code, verifier).json()
    r = mcp.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": granted["refresh_token"],
        "client_id": reg["client_id"], "scope": "mcp:read mcp:write"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"


def test_no_refresh_token_without_offline_access(mcp):
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, scope="mcp:read"))
    granted = _token(mcp, reg, code, verifier).json()
    assert "refresh_token" not in granted


# ── refresh rotation ─────────────────────────────────────────────────────────

def test_refresh_rotates_and_replay_kills_the_grant(mcp):
    """OAuth 2.1 requires rotation for public clients. A second use of a
    single-use token means a copy is loose — and since we cannot tell which
    holder is the thief, the safe move is to end the grant."""
    grant = _connect(mcp)
    first = grant["refresh_token"]
    r = mcp.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": first,
        "client_id": grant["reg"]["client_id"]})
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["refresh_token"] != first

    replay = mcp.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": first,
        "client_id": grant["reg"]["client_id"]})
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"       # the code Claude expects

    # The whole family is gone, including the token that was legitimately issued.
    dead = mcp.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": rotated["refresh_token"],
        "client_id": grant["reg"]["client_id"]})
    assert dead.status_code == 400
    assert _rpc(mcp, rotated["access_token"], "ping").status_code == 401


def test_revocation_ends_the_connection(mcp):
    grant = _connect(mcp)
    assert _rpc(mcp, grant["access_token"], "ping").status_code == 200
    r = mcp.post("/oauth/revoke", data={
        "token": grant["refresh_token"], "client_id": grant["reg"]["client_id"]})
    assert r.status_code == 200
    assert _rpc(mcp, grant["access_token"], "ping").status_code == 401
    # RFC 7009: an unknown token is still a success, so this is not an oracle.
    assert mcp.post("/oauth/revoke", data={
        "token": "never-existed", "client_id": grant["reg"]["client_id"]}).status_code == 200


# ── token handling ───────────────────────────────────────────────────────────

def test_a_session_cookie_is_not_an_mcp_token(mcp):
    """The two credentials must not be interchangeable in either direction —
    which is why access tokens are opaque rather than JWTs signed with the
    session key."""
    login = mcp.post("/api/login", json={"username": "admin", "password": PASSWORD})
    cookie = login.cookies["tasks_session"]
    assert _rpc(mcp, cookie, "ping").status_code == 401
    # …and the reverse: an access token is not a session.
    token = _connect(mcp)["access_token"]
    assert mcp.get("/api/me", headers={"Cookie": f"tasks_session={token}"}).status_code == 401


@pytest.mark.parametrize("token", ["", "garbage", "a" * 400, "Bearer nested"])
def test_bad_bearer_tokens_are_401_not_500(mcp, token):
    r = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_tokens_are_not_stored_in_the_clear(mcp, tmp_path):
    """A read of the database must not yield a working credential."""
    import sqlite3

    grant = _connect(mcp)
    db = sqlite3.connect(str(tmp_path / "mcp.db"))
    rows = db.execute("SELECT token_hash FROM oauth_tokens").fetchall()
    stored = {r[0] for r in rows}
    assert stored
    assert grant["access_token"] not in stored
    assert grant["refresh_token"] not in stored
    assert hashlib.sha256(grant["access_token"].encode()).hexdigest() in stored


# ── abuse ────────────────────────────────────────────────────────────────────

def test_the_consent_password_is_rate_limited(mcp):
    """Same protection /api/login has — the consent screen is a password prompt
    reachable by anyone who knows the URL."""
    reg = _register(mcp)
    _, challenge = _pkce()
    codes = {_authorize(mcp, reg, challenge, password="wrong").status_code
             for _ in range(12)}
    assert 429 in codes


def test_registration_is_capped(mcp):
    """Open registration is what lets a connector connect with no setup; the cap
    is what stops it being a way to fill the disk."""
    seen = set()
    for _ in range(40):
        r = mcp.post("/oauth/register", json={"redirect_uris": [CALLBACK]})
        seen.add(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in seen


def test_a_foreign_origin_is_refused(mcp):
    """DNS-rebinding guard. Claude sends no Origin at all; a browser always
    does, so a foreign one is a page trying to drive this endpoint."""
    token = _connect(mcp)["access_token"]
    r = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                 headers={"Authorization": f"Bearer {token}",
                          "Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": f"Bearer {token}", "Origin": ISSUER})
    assert ok.status_code == 200


def test_an_oversized_body_is_refused(mcp):
    token = _connect(mcp)["access_token"]
    r = mcp.post("/mcp", content=b"x" * 1_100_000,
                 headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"})
    assert r.status_code == 413


# ── the owner's own view of what is connected ────────────────────────────────

def test_connections_are_listed_and_can_be_disconnected(mcp):
    """The consent screen tells the user they can disconnect later, so that has
    to be true — and it is the only way to end a grant from the app side."""
    grant = _connect(mcp)
    mcp.post("/api/login", json={"username": "admin", "password": PASSWORD})

    listed = mcp.get("/api/mcp/connections")
    assert listed.status_code == 200
    rows = listed.json()["connections"]
    assert len(rows) == 1
    assert rows[0]["client_name"] == "Claude"
    assert "mcp:write" in rows[0]["scope"]
    # The grant is identified by its family, never by a token value.
    assert "token" not in str(rows[0]).lower()

    family = rows[0]["family_id"]
    assert mcp.delete(f"/api/mcp/connections/{family}").status_code == 204
    assert _rpc(mcp, grant["access_token"], "ping").status_code == 401
    assert mcp.get("/api/mcp/connections").json()["connections"] == []
    assert mcp.delete(f"/api/mcp/connections/{family}").status_code == 404


def test_connections_need_the_session_cookie(mcp):
    """This pair is the owner managing their own grants, so it is cookie-gated
    like the rest of /api — an access token must not reach it."""
    token = _connect(mcp)["access_token"]
    assert mcp.get("/api/mcp/connections", headers={"Cookie": ""}).status_code == 401
    assert mcp.get("/api/mcp/connections",
                   headers={"Cookie": "", "Authorization": f"Bearer {token}"}).status_code == 401
