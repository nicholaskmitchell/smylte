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
from datetime import date, timedelta
import hashlib
import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.db import store
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


def test_the_connector_parks_and_un_parks_without_calling_it_done(mcp):
    """A model needs the neutral answer as much as the owner does. Asked to
    clear a backlog it would otherwise have exactly two verbs — complete, which
    is a lie, and cancel, which is a verdict — and both are worse than leaving
    the task alone.

    The thing this pins hardest is that parked is NOT done: the DTO has to keep
    saying `completed: false`, or a model reporting back to the owner will tell
    them work is finished that is only set aside."""
    token = _connect(mcp)["access_token"]
    list_id = _call(mcp, token, "smylte_create_list",
                    {"name": f"P-{uuid.uuid4().hex[:8]}"})["structuredContent"]["id"]
    made = _call(mcp, token, "smylte_create_task",
                 {"list_id": list_id, "summary": "Learn the harmonica"})["structuredContent"]

    parked = _call(mcp, token, "smylte_park_task",
                   {"list_id": list_id, "uid": made["uid"]})["structuredContent"]
    assert parked["parked"] is True
    assert parked["completed"] is False and parked["cancelled"] is False

    total = lambda **extra: _call(  # noqa: E731
        mcp, token, "smylte_list_tasks",
        {"list_id": list_id, **extra})["structuredContent"]["total"]
    assert total() == 0, "parked work is off the plate by default"
    assert total(include_parked=True) == 1, "…and still reachable when asked for"
    # NOT folded into include_done: a model given one flag for both would have
    # to report set-aside work as finished to see it at all.
    assert total(include_done=True) == 0

    _call(mcp, token, "smylte_park_task",
          {"list_id": list_id, "uid": made["uid"], "parked": False})
    assert total() == 1

    # An unknown uid is a not-found rather than a cheerful nothing — the sidecar
    # write is a silent no-op for a uid `items` does not hold.
    out = _call(mcp, token, "smylte_park_task", {"list_id": list_id, "uid": "nope"})
    assert out["isError"] is True and "nope" in out["content"][0]["text"]

    _call(mcp, token, "smylte_delete_list", {"list_id": list_id})


def test_the_connector_answers_the_week_with_a_number(mcp):
    """The cheap answer to "what did I get done". `smylte_review_day` with
    from + to returns the same week in full — every bucket, every entry, the
    task behind each row — and builds the whole task index to do it; asking it
    seven days\u2019 worth to arrive at one integer is the expensive way to answer
    the cheapest question the owner has."""
    token = _connect(mcp)["access_token"]
    out = _call(mcp, token, "smylte_review_week", {"week": "2026-08-19"})["structuredContent"]
    # Monday-first and half-open, which every other week in this app is.
    assert out["from"] == "2026-08-17" and out["to"] == "2026-08-24"
    assert isinstance(out["total"], int) and isinstance(out["days"], dict)


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
    # 204 again, not 404: disconnecting is idempotent (2026-08-19 finding 35).
    # This line used to assert the 404, which is how the behaviour survived —
    # `ConnectionsSection.disconnect` restores the optimistic removal on ANY
    # failure, so a retry after a lost response put the revoked grant back in
    # the owner's list of live connections and left it there.
    assert mcp.delete(f"/api/mcp/connections/{family}").status_code == 204


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


def test_a_non_finite_number_is_refused_at_the_mcp_door_like_the_http_one():
    """`allow_inf_nan=False` on the HTTP models had no counterpart here, and the
    two doors write the same rows.

    `server.parse_body`'s `parse_constant` blocks the bare `NaN`/`Infinity`
    literals, and its own comment says it does NOT catch `1e400` — an ordinary
    number literal `json.loads` overflows to `inf`. One of those reaching
    `day_plan.position` was stored in the app-only sidecar, the part of SQLite
    no resync can rebuild, and then made every later read of that day
    unrenderable: `JSONResponse` serializes with `allow_nan=False`, so the tool
    call 500s AFTER committing and both `smylte_get_today` and
    `GET /api/day/{day}` 500 from then on. The owner could not even read the
    entry back out to repair it.

    Enforced in the validator rather than per tool, so it holds for every
    `type: number` in the table."""
    from tasksd.mcp.validate import SchemaError, check_value

    for bad in (float("inf"), float("-inf"), float("nan"), 1e400):
        with pytest.raises(SchemaError, match="finite"):
            check_value(bad, {"type": "number"}, where="t.position")
        with pytest.raises(SchemaError):
            check_value(bad, {"type": "integer"}, where="t.n")

    # Ordinary values, including a very large finite one, still pass.
    for ok in (0, -3, 1.5, 1e300):
        check_value(ok, {"type": "number"}, where="t.position")


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


# ── the day plan ─────────────────────────────────────────────────────────────
#
# Two properties carry these tests. A READ must never create — the day plan is
# only worth keeping while it is an honest record of what the owner intended, and
# a connector that opened days would fill it with plans nobody made. And a
# model has no clock, so the day it gets must be the OWNER's, resolved
# server-side, never one it was asked to supply.

def _day_rows(tmp_path):
    """Both day tables, straight from the file. Reading through the service
    would go through the very code under test."""
    import sqlite3

    db = sqlite3.connect(str(tmp_path / "mcp.db"))
    try:
        return (db.execute("SELECT COUNT(*) FROM day_plan").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM day_plan_opened").fetchone()[0])
    finally:
        db.close()


def _a_task_due_today(mcp, token):
    """A list holding one task due today, in the owner's own day."""
    today = _call(mcp, token, "smylte_get_today")["structuredContent"]["day"]
    list_id = _call(mcp, token, "smylte_create_list",
                    {"name": f"Day {uuid.uuid4().hex[:6]}"})["structuredContent"]["id"]
    task = _call(mcp, token, "smylte_create_task", {
        "list_id": list_id, "summary": "Renew passport", "due": today,
    })["structuredContent"]
    return today, list_id, task


def test_get_today_previews_an_unplanned_day_and_writes_nothing(mcp, tmp_path):
    """The invariant the whole design rests on.

    A day nobody has opened answers planned=false WITH a preview of what opening
    it would derive — useful without being a lie — and leaves both tables exactly
    as empty as it found them. If this ever regresses, the log silently starts
    recording days the owner never looked at, and every later retrospective is
    built on plans that were never made.
    """
    token = _connect(mcp)["access_token"]
    today, _list_id, task = _a_task_due_today(mcp, token)
    assert _day_rows(tmp_path) == (0, 0), "setup must not have opened anything"

    out = _call(mcp, token, "smylte_get_today")["structuredContent"]
    assert out["day"] == today
    assert out["planned"] is False and out["entries"] == []
    # The preview is the useful half: the task really is proposed for today, and
    # it arrives joined to the task so a model needs no second call.
    #
    # `in`, not `==`: a day is account-wide, so the preview legitimately carries
    # whatever else on this scratch server is due or late. Pinning the exact list
    # would be asserting that no other test ever creates a dated task.
    mine = [e for e in out["preview"] if e["uid"] == task["uid"]]
    assert len(mine) == 1, out["preview"]
    assert mine[0]["task"]["summary"] == "Renew passport"
    assert mine[0]["source"] == "auto"

    # And the point of the whole test.
    assert _day_rows(tmp_path) == (0, 0), "a READ opened the day"
    # Twice, because a lazy "open once then serve" would still pass a single call.
    _call(mcp, token, "smylte_get_today")
    assert _day_rows(tmp_path) == (0, 0)


def test_review_day_never_creates_either(mcp, tmp_path):
    """The other read. It reaches arbitrary days, so it is the one that could
    fabricate a whole month rather than just today."""
    token = _connect(mcp)["access_token"]
    _a_task_due_today(mcp, token)
    out = _call(mcp, token, "smylte_review_day")["structuredContent"]
    assert out["planned"] is False
    _call(mcp, token, "smylte_review_day", {"from": "2026-01-01", "to": "2026-02-01"})
    assert _day_rows(tmp_path) == (0, 0)


def test_planning_a_task_is_safe_to_retry(mcp):
    """A model holds no id between calls, so the entry_id is minted server-side
    and cannot dedupe anything. The dedupe that DOES apply to this caller is on
    the task itself — without it, a retried call after a dropped response leaves
    two rows and two checkboxes that disagree about one task."""
    token = _connect(mcp)["access_token"]
    _today, list_id, task = _a_task_due_today(mcp, token)

    first = _call(mcp, token, "smylte_plan_day",
                  {"list_id": list_id, "uid": task["uid"]})["structuredContent"]
    again = _call(mcp, token, "smylte_plan_day",
                  {"list_id": list_id, "uid": task["uid"]})["structuredContent"]
    assert first["entry_id"] == again["entry_id"]
    assert first["source"] == "user", "a model putting this here is a CHOICE"

    day = _call(mcp, token, "smylte_get_today")["structuredContent"]
    assert day["planned"] is True
    assert len(day["entries"]) == 1
    # A day holding hand-added rows has not been SNAPSHOTTED, so it still owes
    # itself one — and the preview says what that would still add.
    assert "preview" not in day


def test_a_past_day_cannot_be_planned(mcp):
    """Planning tomorrow is stating an intention; writing to last Tuesday
    manufactures a record of one. The second is indistinguishable from the real
    thing afterwards, which is exactly what the log exists to rule out."""
    token = _connect(mcp)["access_token"]
    _today, list_id, task = _a_task_due_today(mcp, token)

    r = _call(mcp, token, "smylte_plan_day",
              {"day": "2020-01-01", "list_id": list_id, "uid": task["uid"]})
    assert r["isError"] is True
    said = r["content"][0]["text"]
    assert "past" in said and "2020-01-01" in said

    # Tomorrow is fine, and lands on the day asked for rather than on today.
    tomorrow = (date.fromisoformat(_today) + timedelta(days=1)).isoformat()
    ahead = _call(mcp, token, "smylte_plan_day",
                  {"day": tomorrow, "list_id": list_id, "uid": task["uid"]})
    assert ahead["structuredContent"]["day"] == tomorrow


def test_ticking_a_task_entry_points_at_complete_task(mcp):
    """A task's doneness is its VTODO STATUS, which Tasks.org and Thunderbird
    read too. Recording it on the day entry as well would give one question two
    answers that disagree the moment it is ticked anywhere else — so the tool
    refuses, and the refusal has to name the call that works."""
    token = _connect(mcp)["access_token"]
    _today, list_id, task = _a_task_due_today(mcp, token)
    entry = _call(mcp, token, "smylte_plan_day",
                  {"list_id": list_id, "uid": task["uid"]})["structuredContent"]

    r = _call(mcp, token, "smylte_update_day_entry",
              {"entry_id": entry["entry_id"], "done": True})
    assert r["isError"] is True
    assert "smylte_complete_task" in r["content"][0]["text"]

    # Dropping the same entry is allowed, and keeps the row rather than deleting
    # it — "planned it and did not do it" is the useful part of a look-back.
    dropped = _call(mcp, token, "smylte_update_day_entry",
                    {"entry_id": entry["entry_id"], "dropped": True})["structuredContent"]
    assert dropped["dropped_at"]

    review = _call(mcp, token, "smylte_review_day")["structuredContent"]
    assert [e["entry_id"] for e in review["dropped"]] == [entry["entry_id"]]
    assert review["chosen"] == []


def test_an_unknown_entry_id_is_an_answer_not_a_crash(mcp):
    token = _connect(mcp)["access_token"]
    r = _call(mcp, token, "smylte_update_day_entry", {"entry_id": "nope", "dropped": True})
    assert r["isError"] is True
    assert "smylte_get_today" in r["content"][0]["text"]


def test_review_day_refuses_a_day_and_a_range_together(mcp):
    """Answering one of the two silently would be worse than saying so."""
    token = _connect(mcp)["access_token"]
    r = _call(mcp, token, "smylte_review_day",
              {"day": "2026-08-21", "from": "2026-08-01", "to": "2026-09-01"})
    assert r["isError"] is True and "not both" in r["content"][0]["text"]


def test_review_day_reports_work_finished_off_plan(mcp):
    """Completions are read from each task's own COMPLETED stamp rather than
    from the plan, so a day answers even for work that was never planned — and
    for days before any of this existed."""
    token = _connect(mcp)["access_token"]
    today, list_id, task = _a_task_due_today(mcp, token)
    _call(mcp, token, "smylte_complete_task", {"list_id": list_id, "uid": task["uid"]})

    out = _call(mcp, token, "smylte_review_day")["structuredContent"]
    assert out["day"] == today
    # Account-wide, like the preview above: this asserts the task IS reported,
    # not that nothing else on the scratch server was finished today.
    assert task["uid"] in [t["uid"] for t in out["completed_that_day"]]
    # Never planned, so nothing to show on the other side of the ledger.
    assert out["planned"] is False and out["chosen"] == []


def test_a_range_review_includes_a_day_that_was_never_planned(mcp):
    """`day_range` omits unplanned days by design — they are not plans. But a day
    you finished five things on without planning any of them is exactly what a
    look-back is for, so the review has to union the two rather than iterate the
    plans alone."""
    token = _connect(mcp)["access_token"]
    today, list_id, task = _a_task_due_today(mcp, token)
    _call(mcp, token, "smylte_complete_task", {"list_id": list_id, "uid": task["uid"]})

    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    out = _call(mcp, token, "smylte_review_day",
                {"from": today, "to": tomorrow})["structuredContent"]
    day = next((d for d in out["days"] if d["day"] == today), None)
    assert day is not None, "the day vanished because nothing was planned on it"
    assert day["planned"] is False
    assert task["uid"] in [t["uid"] for t in day["completed_that_day"]]


def test_the_day_write_tools_need_write_scope(mcp):
    """Same guarantee every other write carries — a read-only consent must not
    be able to put anything on a day."""
    reg = _register(mcp)
    verifier, challenge = _pkce()
    code = _code_from(_authorize(mcp, reg, challenge, grant="read"))
    token = _token(mcp, reg, code, verifier).json()["access_token"]

    assert _call(mcp, token, "smylte_get_today")["isError"] is False
    for name, args in (
        ("smylte_plan_day", {"title": "sneak"}),
        ("smylte_update_day_entry", {"entry_id": "x", "dropped": True}),
    ):
        err = _rpc(mcp, token, "tools/call",
                   {"name": name, "arguments": args}).json()["error"]
        assert "write access" in err["message"], name


def test_today_is_the_owners_day_not_the_servers(mcp):
    """The defect `_home_zone` exists for. The server runs UTC in the ordinary
    deployment while the owner is somewhere else, and a model has no clock to
    correct with — so an hour either side of midnight it would be told the wrong
    day, and anything it planned would land on it."""
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service

    seen = set()
    for zone in ("Pacific/Kiritimati", "Pacific/Niue"):   # UTC+14 and UTC-11
        svc.update_settings({"home_timezone": zone})
        seen.add(_call(mcp, token, "smylte_get_today")["structuredContent"]["day"])
    # 25 hours apart: they cannot both be the server's own date, whatever the
    # clock says when this runs.
    assert len(seen) == 2, seen


# ── habits on the day ────────────────────────────────────────────────────────
#
# A habit is A RULE THAT INSERTS ENTRIES, and what reaches this connector is the
# entry: an ordinary day_plan row with kind="habit" carrying a copy of the
# habit's title. Every property the day plan already had has to keep holding for
# it — but one thing is genuinely different, and it is what these tests are
# about. A task's doneness is its VTODO STATUS, out on the wire where every
# client can see it, so a connector that loses or invents one is contradicted
# loudly. A habit's doneness is a single stamp in one table on one machine, so a
# connector that drops it from a review, or lets it be written after the fact,
# turns the record into a guess with nothing anywhere to disagree.
#
# Habits are DEFINED through the service in these fixtures rather than through a
# tool, because there deliberately is no tool: the rule is the owner's own
# standing decision. Opening a day goes through the service for the stronger
# reason — no tool here may open one at all.


def _a_habit_on(svc, day, *, title, days=""):
    """A habit, plus the occurrence a real open of `day` mints for it.

    Two service calls, standing in for the owner at the app: defining the rule,
    and opening the day. What the connector sees afterwards is exactly what it
    sees in production, which is the only way to build this fixture — no tool
    creates a habit, and no tool opens a day.

    The open runs with the service's today pinned to `day`, which is not a
    convenience: an occurrence only ever reaches a day ON that day, because
    `service._habit_minting_allowed` refuses a past one on BOTH the first
    snapshot and the top-up. So a caller wanting an occurrence on a day that is
    now PAST — the retrospective tests below — is staging history rather than
    forging it, and the row it gets is exactly the row that would have been
    written at the time. Without the pin those tests would build their fixture
    through a hole the service no longer has, and would keep passing while the
    thing they describe had become impossible.
    """
    habit = svc.create_habit(title=title, days=days)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(svc, "_today", lambda: day)
        plan = svc.open_day(day, create=True)
    entry = next(e for e in plan["entries"] if e["habit_id"] == habit["id"])
    return habit, entry


def test_a_habit_occurrence_is_in_the_review(mcp):
    """The review bucketed on three `==` tests over `source` — user, carried,
    auto — with no residual, so an occurrence carrying source="habit" matched
    none of them and fell out of the retrospective entirely. Silently: the day
    still answered and still looked complete, it simply had no habits in it. That
    is the half most worth reviewing, because whether a habit was kept is
    recorded nowhere else on the account.
    """
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    today = _call(mcp, token, "smylte_get_today")["structuredContent"]["day"]
    habit, occ = _a_habit_on(svc, today, title=f"Meditate {uuid.uuid4().hex[:6]}")

    out = _call(mcp, token, "smylte_review_day")["structuredContent"]
    assert out["day"] == today and out["planned"] is True
    mine = [e for e in out["habits"] if e["entry_id"] == occ["entry_id"]]
    assert len(mine) == 1, out["habits"]
    assert mine[0]["kind"] == "habit" and mine[0]["source"] == "habit"
    assert mine[0]["habit_id"] == habit["id"]
    # The COPY the occurrence took, not a join: that copy is what lets the row
    # keep reading correctly after the rule is renamed or deleted.
    assert mine[0]["title"] == habit["title"]
    # One arm, not several — the arms are a partition, not four filters that
    # happen to be disjoint today.
    for arm in ("chosen", "carried", "derived", "other", "dropped"):
        assert occ["entry_id"] not in [e["entry_id"] for e in out[arm]], arm


def test_no_entry_can_fall_out_of_the_review(mcp):
    """The shape rather than the habits arm. `habits` fixes the source that
    exists today; the residual is what stops the NEXT one disappearing the same
    way, because three equality tests were exhaustive only by luck.

    The unknown-source row is written through the store because nothing else can
    write one — that is the point of it. It stands in for a source added later,
    and the assertion is that the review reports it rather than swallowing it.
    """
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    today, _list_id, task = _a_task_due_today(mcp, token)
    _habit, occ = _a_habit_on(svc, today, title=f"Stretch {uuid.uuid4().hex[:6]}")
    chosen = _call(mcp, token, "smylte_plan_day",
                   {"title": f"Call the bank {uuid.uuid4().hex[:6]}"})["structuredContent"]
    odd = uuid.uuid4().hex
    store.insert_day_entry(
        svc._conn, day=today, entry_id=odd, kind="note", source="imported",
        title=f"From somewhere this code has never heard of {odd[:6]}",
        position=99.0,
    )

    out = _call(mcp, token, "smylte_review_day")["structuredContent"]
    arms = ("chosen", "carried", "derived", "habits", "other")
    bucketed = [e["entry_id"] for arm in arms for e in out[arm]]
    assert len(bucketed) == len(set(bucketed)), "an entry landed in two arms"
    live = {e["entry_id"] for e in
            _call(mcp, token, "smylte_get_today")["structuredContent"]["entries"]
            if not e["dropped_at"]}
    assert set(bucketed) == live, "an entry is on the day but in none of the arms"

    assert [e["entry_id"] for e in out["other"]] == [odd]
    # Self-describing, which is what makes the residual usable rather than a
    # mystery: the model can read the source it does not recognise.
    assert out["other"][0]["source"] == "imported"
    assert occ["entry_id"] in [e["entry_id"] for e in out["habits"]]
    assert chosen["entry_id"] in [e["entry_id"] for e in out["chosen"]]
    assert task["uid"] in [e["uid"] for e in out["derived"]]


def test_every_entry_has_the_same_shape_whatever_its_kind(mcp):
    """`task` was attached only to kind="task" rows, so a day mixing kinds came
    back in two record shapes and the missing key was the only thing separating
    them: a reader that reaches for row["task"] raises on the first habit, and
    one that tests `"task" in row` has learnt a rule that changes meaning the day
    a fourth kind exists.
    """
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    today, _list_id, task = _a_task_due_today(mcp, token)
    _habit, occ = _a_habit_on(svc, today, title=f"Read {uuid.uuid4().hex[:6]}")
    note = _call(mcp, token, "smylte_plan_day",
                 {"title": f"Water the plants {uuid.uuid4().hex[:6]}"})["structuredContent"]

    entries = _call(mcp, token, "smylte_get_today")["structuredContent"]["entries"]
    assert {"task", "habit", "note"} <= {e["kind"] for e in entries}
    assert all("task" in e for e in entries), "a kind came back without the key"

    by_id = {e["entry_id"]: e for e in entries}
    # Null on the kinds that name no task. Structural, not a failed join — which
    # is why `kind` has to be read alongside it.
    assert by_id[occ["entry_id"]]["task"] is None
    assert by_id[note["entry_id"]]["task"] is None
    # And the join still happens, which is the whole reason for the key.
    row = next(e for e in entries if e["kind"] == "task" and e["uid"] == task["uid"])
    assert row["task"]["summary"] == "Renew passport"


def test_a_habit_is_ticked_here_which_a_task_is_not(mcp):
    """A habit occurrence exists only in the day plan, so the stamp written here
    is the entire record that it was kept — there is no VTODO to contradict it,
    which is exactly why `done` is accepted for one and refused for a task."""
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    today = _call(mcp, token, "smylte_get_today")["structuredContent"]["day"]
    _habit, occ = _a_habit_on(svc, today, title=f"Push-ups {uuid.uuid4().hex[:6]}")

    ticked = _call(mcp, token, "smylte_update_day_entry",
                   {"entry_id": occ["entry_id"], "done": True})["structuredContent"]
    assert ticked["done_at"]
    review = _call(mcp, token, "smylte_review_day")["structuredContent"]
    mine = next(e for e in review["habits"] if e["entry_id"] == occ["entry_id"])
    assert mine["done_at"] == ticked["done_at"]


def test_a_past_day_can_be_tidied_but_not_re_ticked(mcp):
    """`update_day_entry` resolved its day with `_day_or_today`, so `done` could
    be set on ANY past day. On a note that is untidy; on a habit it is the whole
    value of the thing — a log that can be filled in on Friday for Tuesday
    measures nothing, and afterwards it is indistinguishable from one that was
    kept honestly.

    Dropping and repositioning stay allowed on the same day, and that difference
    is the point rather than an oversight: admitting a plan went unmet subtracts
    from the day, and an order is not a claim about what happened.
    """
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    today = _call(mcp, token, "smylte_get_today")["structuredContent"]["day"]
    past = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    _habit, occ = _a_habit_on(svc, past, title=f"Journal {uuid.uuid4().hex[:6]}")

    # Both directions: un-ticking erases a record made on the day as surely as
    # backfilling invents one.
    for done in (True, False):
        r = _call(mcp, token, "smylte_update_day_entry",
                  {"entry_id": occ["entry_id"], "day": past, "done": done})
        assert r["isError"] is True, done
        said = r["content"][0]["text"]
        assert past in said and "done" in said, said

    # And the refusal happened before anything was written.
    review = _call(mcp, token, "smylte_review_day", {"day": past})["structuredContent"]
    mine = next(e for e in review["habits"] if e["entry_id"] == occ["entry_id"])
    assert mine["done_at"] is None

    # The same entry, on the same past day: tidying, which is not falsifying.
    dropped = _call(mcp, token, "smylte_update_day_entry",
                    {"entry_id": occ["entry_id"], "day": past,
                     "dropped": True})["structuredContent"]
    assert dropped["dropped_at"]
    moved = _call(mcp, token, "smylte_update_day_entry",
                  {"entry_id": occ["entry_id"], "day": past,
                   "position": 0.5})["structuredContent"]
    assert moved["position"] == 0.5


def test_a_habit_on_an_unopened_day_is_visible_but_cannot_be_ticked(mcp, tmp_path):
    """The claim the tool descriptions make, pinned to the code that has to keep
    it true.

    On a day nobody has opened, a habit exists only as a PREVIEW row — an
    entry_id `preview_day` mints and throws away — and nothing in this toolset
    can open the day, because a read that opened days would fill the log with
    plans nobody made. So today's habits are visible here and UN-TICKABLE until
    the owner opens the app. A description that said otherwise would fail in the
    most expensive direction: a model reporting a habit done that was never
    recorded anywhere.
    """
    token = _connect(mcp)["access_token"]
    svc = mcp.app.state.service
    title = f"Walk the dog {uuid.uuid4().hex[:6]}"
    habit = svc.create_habit(title=title, days="")
    assert _day_rows(tmp_path) == (0, 0), "defining a habit must not touch a day"

    out = _call(mcp, token, "smylte_get_today")["structuredContent"]
    assert out["planned"] is False
    mine = [e for e in out["preview"] if e["habit_id"] == habit["id"]]
    assert len(mine) == 1, out["preview"]
    assert mine[0]["kind"] == "habit" and mine[0]["title"] == title
    # The preview carries the same record shape as a real entry, `task` included.
    assert mine[0]["task"] is None

    r = _call(mcp, token, "smylte_update_day_entry",
              {"entry_id": mine[0]["entry_id"], "done": True})
    assert r["isError"] is True
    assert "no entry" in r["content"][0]["text"]
    # And the attempt did not open the day on its way past.
    assert _day_rows(tmp_path) == (0, 0)


def test_a_lone_surrogate_anywhere_on_the_reply_path_cannot_kill_the_response():
    """`json.loads` accepts an unpaired surrogate and hands it back verbatim;
    Starlette renders with `ensure_ascii=False` and then `.encode("utf-8")`,
    which raises. That happens WHILE RENDERING — outside every exception handler
    — so it is a 500, and for `tools/call` it lands after the tool has already
    run: a real write committed while its caller was told the call failed, and in
    a batch one poisoned id discarded all 50 replies.

    Exactly the failure the non-finite-id guard was written for, which is why
    `_usable_id` now checks a string is encodable as well, and why every place
    that echoes caller-supplied text into a reply goes through `wire_safe`."""
    import json as _json

    from tasksd.mcp.oauth import wire_safe
    from tasksd.mcp.server import _usable_id

    def render(obj):                      # what starlette's JSONResponse does
        return _json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")

    assert _usable_id("\ud800") is False, "an unencodable id is not a reply address"
    assert _usable_id("req-1") and _usable_id(7) and _usable_id(None)

    assert wire_safe("a\ud800b") == "a?b"
    render({"jsonrpc": "2.0", "id": None, "error": {"message": wire_safe("\ud800")}})

    # The three other places caller-controlled text reaches a reply: an unknown
    # method name, an unknown argument name, and an unknown OAuth scope.
    for hostile in ("bad\ud800method", "\udfff", "ok"):
        render({"m": wire_safe(hostile)})


def test_merged_events_are_ordered_by_instant_not_by_iso_string():
    """`list_events` merged every calendar's rows and sorted lexically over
    `dt.isoformat()`, which carries whatever offset the WRITING client used.

    `_intrinsic_order`'s docstring in the same file already says why that is
    wrong — "lexical comparison happens to agree for ISO values of equal shape
    and stops agreeing the moment a date-only and a timed value meet, or an
    offset appears" — and the tasks path was fixed for it while the events path
    was not. So a Berlin-anchored 09:00 (07:00Z, genuinely FIRST) sorted after a
    plain 08:00Z, because "…T09:00" is lexically greater. tools.py pages this
    list, so `limit: 1` handed the model the LATER meeting and it never saw the
    earlier one.

    Undated and unreadable rows sort LAST now rather than first — they came off
    the wire from another client — and uid/recurrence_id make the order total."""
    from tasksd.mcp.api import _event_order

    rows = [
        {"uid": "utcone", "start": "2026-08-21T08:00:00+00:00", "summary": "B"},
        {"uid": "berlin", "start": "2026-08-21T09:00:00+02:00", "summary": "A"},
        {"uid": "nostart", "start": None, "summary": "C"},
        {"uid": "junk", "start": "(datetime.datetime(2026, 1, 1, 0, 0),)", "summary": "D"},
    ]
    assert [r["uid"] for r in sorted(rows, key=_event_order)] == [
        "berlin", "utcone", "nostart", "junk"]

    # Total: two rows sharing an instant and a summary still order stably.
    same = [{"uid": "b", "start": "2026-08-21T08:00:00+00:00", "summary": "x"},
            {"uid": "a", "start": "2026-08-21T10:00:00+02:00", "summary": "x"}]
    assert [r["uid"] for r in sorted(same, key=_event_order)] == ["a", "b"]
