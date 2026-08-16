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


# ── defects found by the adversarial review, pinned so they cannot return ────

def test_tool_arguments_are_checked_against_the_advertised_schema(mcp):
    """A client is not obliged to honour the schema and a compromised one will
    not, so the published contract has to be enforced rather than assumed.

    The concrete cost of not doing so: duration_minutes=0 reached the slot
    generator, whose cursor advances by that duration, and hung the process
    inside the service lock — from a value already written to disk.
    """
    token = _connect(mcp)["access_token"]

    def err(name, args):
        return _rpc(mcp, token, "tools/call",
                    {"name": name, "arguments": args}).json()["error"]["message"]

    assert "at least 5" in err("smylte_update_booking_link",
                               {"token": "t", "duration_minutes": 0})
    assert "at most 480" in err("smylte_update_booking_link",
                                {"token": "t", "duration_minutes": 99999})
    assert "must be an integer" in err("smylte_update_booking_link",
                                       {"token": "t", "duration_minutes": "long"})
    # bool is an int subclass — JSON `true` must not satisfy an integer field.
    assert "must be an integer" in err("smylte_list_tasks", {"limit": True})
    assert "one of" in err("smylte_create_task",
                           {"list_id": "x", "summary": "y", "priority": "urgent"})
    assert "must be a string" in err("smylte_get_task", {"list_id": 7, "uid": "u"})
    assert "expected format" in err("smylte_create_list",
                                    {"name": "ok", "color": "not-a-colour"})
    assert "at least 1 character" in err("smylte_create_list", {"name": ""})
    assert "must be an array" in err("smylte_create_task",
                                     {"list_id": "x", "summary": "y", "tags": "one"})
    assert "must be a string" in err("smylte_create_task",
                                     {"list_id": "x", "summary": "y", "tags": [1]})


def test_every_tool_schema_stays_inside_what_the_validator_enforces(mcp):
    """A schema keyword the validator does not implement would be advertised and
    silently unenforced — which is the exact shape of the bug above."""
    from tasksd.mcp.tools import build_tools
    from tasksd.mcp.validate import unsupported_keywords

    class _Stub:
        def __getattr__(self, _):
            return lambda *a, **k: None

    for name, tool in build_tools(_Stub()).items():
        assert not unsupported_keywords(tool.schema), name


def test_slot_generation_refuses_a_duration_that_cannot_advance():
    """Belt and braces for the same defect: whatever writes the value, the loop
    itself must not be the thing that trusts it."""
    from datetime import datetime, time, timezone
    from zoneinfo import ZoneInfo

    from tasksd import scheduling

    for bad in (0, -30):
        with pytest.raises(ValueError, match="positive"):
            scheduling.generate_slots(
                availability={0: [(time(9, 0), time(17, 0))]},
                duration_minutes=bad, busy=[], buffer_minutes=0,
                tz=ZoneInfo("UTC"), now=datetime(2026, 9, 1, tzinfo=timezone.utc),
                min_notice_hours=24, horizon_days=7,
            )


def test_oversized_bodies_are_refused_before_they_are_buffered(mcp):
    """Reading first and checking afterwards means the memory is already spent —
    on endpoints an unauthenticated caller can reach."""
    big = b"x" * 200_000
    # Declared length, refused on the header alone.
    assert mcp.post("/oauth/register", content=big,
                    headers={"Content-Type": "application/json"}).status_code == 413
    assert mcp.post("/oauth/token", content=big,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                    ).status_code == 413
    assert mcp.post("/oauth/authorize", content=big,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                    ).status_code == 413

    # Chunked, so there is no Content-Length to check: the running total is what
    # actually enforces the cap.
    def chunks():
        for _ in range(20):
            yield b"y" * 10_000

    assert mcp.post("/oauth/register", content=chunks(),
                    headers={"Content-Type": "application/json"}).status_code == 413

    # A normal body still works.
    assert mcp.post("/oauth/register",
                    json={"redirect_uris": [CALLBACK]}).status_code == 201


def test_free_time_reads_a_duration_only_event(mcp, monkeypatch):
    """An event may carry DURATION instead of DTEND. Missing it made a two-hour
    meeting look like a half-hour one and offered the rest as free."""
    from tasksd.mcp.api import McpApi, parse_duration

    assert parse_duration("PT2H") is not None

    api = McpApi(mcp.app.state.service)
    monkeypatch.setattr(api, "list_events", lambda *a, **k: [{
        "start": "2026-09-07T10:00:00", "end": None, "duration": "PT2H",
        "all_day": False, "status": "CONFIRMED",
    }])
    free = api.find_free_time("2026-09-07", "2026-09-08", minutes=30)
    # 09:00-10:00 before it and 12:00-17:00 after — nothing inside the meeting.
    assert [f["start"] for f in free] == ["2026-09-07T09:00", "2026-09-07T12:00"]
    assert free[0]["end"] == "2026-09-07T10:00"


def test_free_time_can_be_paged(mcp):
    """It reported next_offset while its schema forbade sending one back."""
    token = _connect(mcp)["access_token"]
    out = _call(mcp, token, "smylte_find_free_time",
                {"start": "2026-09-01", "end": "2026-11-01", "limit": 10, "offset": 5})
    assert out["isError"] is False
    body = out["structuredContent"]
    assert body["offset"] == 5 and body["count"] <= 10
    if body.get("has_more"):
        assert body["next_offset"] == 15


def test_a_wrong_password_keeps_the_read_only_choice(mcp):
    """The screen exists for that choice, so a typo must not quietly re-arm
    full access for the retry."""
    reg = _register(mcp)
    _, challenge = _pkce()
    page = mcp.get("/oauth/authorize", params={
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": MCP_URL,
        "scope": "mcp:read mcp:write offline_access"})
    signed = re.search(r'name="request" value="([^"]+)"', page.text).group(1)

    retry = mcp.post("/oauth/authorize", data={
        "request": signed, "action": "approve", "grant": "read",
        "username": "admin", "password": "wrong"})
    assert retry.status_code == 401
    read_radio = re.search(r'value="read"([^>]*)>', retry.text).group(1)
    full_radio = re.search(r'value="full"([^>]*)>', retry.text).group(1)
    assert "checked" in read_radio and "checked" not in full_radio


# ── JSON-RPC batch framing ──────────────────────────────────────────────────
#
# AUDIT: `run_batch`'s list branch decides what a client gets back when it sends
# several messages at once, and nothing exercised it. Batching left the
# 2025-06-18 revision but earlier ones allow it and clients in the wild still
# send it, so the branch is live and every reply framing decision in it — 202 vs
# a body, which ids come back, what an over-long batch does — was untested.

def _batch(client, token, messages):
    return client.post("/mcp", json=messages, headers={
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": "2025-06-18",
    })


def test_a_batch_answers_each_request_and_keeps_its_ids(mcp):
    token = _connect(mcp)["access_token"]
    r = _batch(mcp, token, [
        {"jsonrpc": "2.0", "id": "a", "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) == 2
    # Order is not guaranteed by JSON-RPC; identity by id is what a client uses
    # to match a reply to the message it sent.
    assert {m["id"] for m in body} == {"a", 7}
    assert all("result" in m for m in body)


def test_a_batch_of_only_notifications_gets_202_and_no_body(mcp):
    # A notification has no reply by definition, so a batch of them has no reply
    # at all. Answering `[]` would be a JSON-RPC violation and a client waiting
    # on ids it never sent could hang on it.
    token = _connect(mcp)["access_token"]
    r = _batch(mcp, token, [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ])
    assert r.status_code == 202 and not r.content


def test_a_mixed_batch_replies_only_to_the_requests(mcp):
    token = _connect(mcp)["access_token"]
    r = _batch(mcp, token, [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ])
    assert r.status_code == 200
    body = r.json()
    assert [m["id"] for m in body] == [1]


def test_one_bad_message_does_not_sink_the_rest_of_the_batch(mcp):
    # Per-message errors, not a per-batch one: a malformed third message must
    # not discard the results of the first two.
    token = _connect(mcp)["access_token"]
    r = _batch(mcp, token, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "1.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "no/such/method"},
    ])
    body = {m.get("id"): m for m in r.json()}
    assert "result" in body[1]
    assert "error" in body[None]        # not a 2.0 message; no id to answer with
    assert "error" in body[3]


def test_an_empty_batch_is_an_invalid_request(mcp):
    token = _connect(mcp)["access_token"]
    body = _batch(mcp, token, []).json()
    assert body["id"] is None and body["error"]["code"] == -32600
    assert "empty batch" in body["error"]["message"]


def test_an_oversized_batch_is_refused_whole(mcp):
    """Refused whole, not truncated. A caller that got results for the first N
    of its messages and silence for the rest cannot tell 'dropped' from
    'succeeded with no reply', and would carry on as though the writes landed."""
    from tasksd.mcp.server import MAX_BATCH

    token = _connect(mcp)["access_token"]
    r = _batch(mcp, token, [
        {"jsonrpc": "2.0", "id": i, "method": "tools/list"} for i in range(MAX_BATCH + 1)])
    body = r.json()
    assert isinstance(body, dict)                     # not a list of partial results
    assert body["error"]["code"] == -32600
    assert str(MAX_BATCH) in body["error"]["message"]

    # The control: exactly at the limit still works, so the cap is off-by-none.
    at_limit = _batch(mcp, token, [
        {"jsonrpc": "2.0", "id": i, "method": "tools/list"} for i in range(MAX_BATCH)])
    assert len(at_limit.json()) == MAX_BATCH


def test_a_bare_scalar_body_is_an_invalid_request(mcp):
    token = _connect(mcp)["access_token"]
    r = mcp.post("/mcp", json="hello", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["error"]["code"] == -32600


def test_a_batch_is_bounded_by_the_same_scopes_as_a_single_call(mcp):
    # The scope check lives in `handle`, which the batch branch calls per
    # message — so a read-only grant must not be able to smuggle a write in by
    # wrapping it in a list.
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, grant="read"))
    token = _token(mcp, reg, code, verifier).json()["access_token"]

    body = _batch(mcp, token, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "smylte_create_list", "arguments": {"name": "nope"}}}])
    assert "write access" in body.json()[0]["error"]["message"]


# ── the event write tools ───────────────────────────────────────────────────
#
# AUDIT: no MCP-level test drove smylte_create_event, smylte_update_event or
# smylte_delete_event, nor the `scope` argument that decides whether an edit
# touches one occurrence or rewrites a whole series. Getting that wrong is the
# expensive kind of wrong — a model asked to move next Tuesday's stand-up would
# silently move every stand-up there will ever be.

@pytest.fixture
def calendar(mcp):
    """A connected client and a real CalDAV calendar, torn down afterwards."""
    token = _connect(mcp)["access_token"]
    made = _call(mcp, token, "smylte_create_calendar",
                 {"name": f"MCP cal {uuid.uuid4().hex[:6]}"})["structuredContent"]
    yield mcp, token, made["id"]
    _call(mcp, token, "smylte_delete_calendar", {"calendar_id": made["id"]})


def test_an_event_round_trips_through_the_write_tools(calendar):
    client, token, cal = calendar

    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Dentist",
        "start": "2026-09-07T10:00", "end": "2026-09-07T11:00",
        "location": "High Street", "tags": ["health"],
    })["structuredContent"]
    assert made["summary"] == "Dentist"

    got = _call(client, token, "smylte_get_event",
                {"calendar_id": cal, "uid": made["uid"]})["structuredContent"]
    assert got["location"] == "High Street" and got["tags"] == ["health"]

    _call(client, token, "smylte_update_event", {
        "calendar_id": cal, "uid": made["uid"], "summary": "Dentist (moved)",
        "start": "2026-09-07T14:00", "end": "2026-09-07T15:00"})
    again = _call(client, token, "smylte_get_event",
                  {"calendar_id": cal, "uid": made["uid"]})["structuredContent"]
    assert again["summary"] == "Dentist (moved)"
    assert again["start"].startswith("2026-09-07T14:00")

    deleted = _call(client, token, "smylte_delete_event",
                    {"calendar_id": cal, "uid": made["uid"]})["structuredContent"]
    assert deleted["deleted"] == made["uid"]
    gone = _call(client, token, "smylte_get_event", {"calendar_id": cal, "uid": made["uid"]})
    assert gone["isError"] is True


def test_scope_this_touches_one_occurrence_and_leaves_the_series(calendar):
    """The argument that decides whether a model edits next Tuesday's stand-up or
    every stand-up there will ever be."""
    client, token, cal = calendar
    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Stand-up",
        "start": "2026-09-07T09:00", "end": "2026-09-07T09:15",
        "repeat": "daily", "repeat_count": 5,
    })["structuredContent"]

    days = _call(client, token, "smylte_list_events",
                 {"start": "2026-09-07", "end": "2026-09-14", "calendar_id": cal}
                 )["structuredContent"]["events"]
    assert len(days) == 5
    second = days[1]

    _call(client, token, "smylte_update_event", {
        "calendar_id": cal, "uid": made["uid"], "summary": "Stand-up (skipped)",
        "recurrence_id": second["recurrence_id"], "scope": "this"})

    after = _call(client, token, "smylte_list_events",
                  {"start": "2026-09-07", "end": "2026-09-14", "calendar_id": cal}
                  )["structuredContent"]["events"]
    assert [e["summary"] for e in after] == [
        "Stand-up", "Stand-up (skipped)", "Stand-up", "Stand-up", "Stand-up"]


def test_scope_thisandfuture_splits_the_series_at_that_point(calendar):
    client, token, cal = calendar
    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Stand-up",
        "start": "2026-10-05T09:00", "end": "2026-10-05T09:15",
        "repeat": "daily", "repeat_count": 5,
    })["structuredContent"]

    days = _call(client, token, "smylte_list_events",
                 {"start": "2026-10-05", "end": "2026-10-12", "calendar_id": cal}
                 )["structuredContent"]["events"]
    third = days[2]

    _call(client, token, "smylte_update_event", {
        "calendar_id": cal, "uid": made["uid"], "summary": "Stand-up (new format)",
        "recurrence_id": third["recurrence_id"], "scope": "thisandfuture"})

    after = _call(client, token, "smylte_list_events",
                  {"start": "2026-10-05", "end": "2026-10-12", "calendar_id": cal}
                  )["structuredContent"]["events"]
    # Everything before the split keeps the old summary; everything from it on
    # takes the new one — that is what "and future" has to mean.
    assert [e["summary"] for e in after] == [
        "Stand-up", "Stand-up",
        "Stand-up (new format)", "Stand-up (new format)", "Stand-up (new format)"]


def test_scope_all_is_the_default_and_rewrites_the_whole_series(calendar):
    # The control for the two above. `all` is the schema default, so an edit sent
    # without a scope has to reach every occurrence — a model that omits the
    # argument is asking for the ordinary thing.
    client, token, cal = calendar
    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Stand-up",
        "start": "2026-11-02T09:00", "end": "2026-11-02T09:15",
        "repeat": "daily", "repeat_count": 4,
    })["structuredContent"]

    _call(client, token, "smylte_update_event", {
        "calendar_id": cal, "uid": made["uid"], "summary": "Team sync"})

    after = _call(client, token, "smylte_list_events",
                  {"start": "2026-11-02", "end": "2026-11-09", "calendar_id": cal}
                  )["structuredContent"]["events"]
    assert [e["summary"] for e in after] == ["Team sync"] * 4


def test_deleting_one_occurrence_keeps_the_rest(calendar):
    client, token, cal = calendar
    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Gym",
        "start": "2026-12-07T18:00", "end": "2026-12-07T19:00",
        "repeat": "daily", "repeat_count": 3,
    })["structuredContent"]

    days = _call(client, token, "smylte_list_events",
                 {"start": "2026-12-07", "end": "2026-12-14", "calendar_id": cal}
                 )["structuredContent"]["events"]

    out = _call(client, token, "smylte_delete_event", {
        "calendar_id": cal, "uid": made["uid"],
        "recurrence_id": days[1]["recurrence_id"], "scope": "this"})["structuredContent"]
    assert out["scope"] == "this"

    left = _call(client, token, "smylte_list_events",
                 {"start": "2026-12-07", "end": "2026-12-14", "calendar_id": cal}
                 )["structuredContent"]["events"]
    assert [e["start"][:10] for e in left] == ["2026-12-07", "2026-12-09"]

    # And the control: scope='all' takes the series with it.
    _call(client, token, "smylte_delete_event",
          {"calendar_id": cal, "uid": made["uid"], "scope": "all"})
    assert _call(client, token, "smylte_list_events",
                 {"start": "2026-12-07", "end": "2026-12-14", "calendar_id": cal}
                 )["structuredContent"]["events"] == []


def test_an_occurrence_scope_without_a_recurrence_id_is_refused(calendar):
    # Not silently promoted to the whole series. This is the failure mode that
    # costs data: a model that forgot the recurrence_id must be told, not
    # quietly handed the destructive interpretation of its request.
    client, token, cal = calendar
    made = _call(client, token, "smylte_create_event", {
        "calendar_id": cal, "summary": "Standup",
        "start": "2027-01-04T09:00", "end": "2027-01-04T09:15",
        "repeat": "daily", "repeat_count": 3,
    })["structuredContent"]

    for scope in ("this", "thisandfuture"):
        out = _call(client, token, "smylte_update_event", {
            "calendar_id": cal, "uid": made["uid"], "summary": "nope", "scope": scope})
        assert out["isError"] is True, scope
        assert "recurrence_id" in out["content"][0]["text"]

    after = _call(client, token, "smylte_list_events",
                  {"start": "2027-01-04", "end": "2027-01-11", "calendar_id": cal}
                  )["structuredContent"]["events"]
    assert [e["summary"] for e in after] == ["Standup"] * 3


def test_moving_an_event_takes_its_whole_series(calendar):
    client, token, cal = calendar
    other = _call(client, token, "smylte_create_calendar",
                  {"name": f"MCP dest {uuid.uuid4().hex[:6]}"})["structuredContent"]
    try:
        made = _call(client, token, "smylte_create_event", {
            "calendar_id": cal, "summary": "Pilates",
            "start": "2027-02-01T07:00", "end": "2027-02-01T08:00",
            "repeat": "weekly", "repeat_count": 3,
        })["structuredContent"]

        _call(client, token, "smylte_move_event",
              {"calendar_id": cal, "uid": made["uid"], "to_calendar_id": other["id"]})

        assert _call(client, token, "smylte_list_events",
                     {"start": "2027-02-01", "end": "2027-03-01", "calendar_id": cal}
                     )["structuredContent"]["events"] == []
        moved = _call(client, token, "smylte_list_events",
                      {"start": "2027-02-01", "end": "2027-03-01", "calendar_id": other["id"]}
                      )["structuredContent"]["events"]
        assert len(moved) == 3
    finally:
        _call(client, token, "smylte_delete_calendar", {"calendar_id": other["id"]})


def test_the_event_write_tools_need_write_scope(mcp):
    # Every one of them is declared SCOPE_WRITE; a read-only connection must not
    # reach any of them.
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, grant="read"))
    token = _token(mcp, reg, code, verifier).json()["access_token"]

    for name, args in [
        ("smylte_create_event", {"calendar_id": "c", "summary": "x", "start": "2026-09-07T10:00"}),
        ("smylte_update_event", {"calendar_id": "c", "uid": "u", "summary": "x"}),
        ("smylte_delete_event", {"calendar_id": "c", "uid": "u"}),
        ("smylte_move_event", {"calendar_id": "c", "uid": "u", "to_calendar_id": "d"}),
    ]:
        err = _rpc(mcp, token, "tools/call",
                   {"name": name, "arguments": args}).json()["error"]
        assert "write access" in err["message"], name

    # The control: reading events is fine on the same token.
    assert _call(mcp, token, "smylte_list_events",
                 {"start": "2026-09-01", "end": "2026-09-08"})["isError"] is False
