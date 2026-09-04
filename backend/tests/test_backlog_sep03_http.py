r"""The 2026-09-03 sweep: the HTTP core and the OAuth front door.

Ten findings, all on the edge of the process — `app.py`'s login and settings
routes, the MCP consent screen and its authorization server, the JSON-RPC
transport. What they share is that each is a request the server answers wrongly
in a way a caller can see: a 500 for a 400, a 429 that becomes a lockout, a
route that was never reachable, a label that silently means "none".

One test per finding, named for the CORRECT behaviour and confirmed to fail
against the code as it stood before each fix. Each is Radicale-free where the
route allows it: the login and consent pins build the app without entering its
lifespan and stand a stub service on `app.state.service` (the pattern
test_backlog_aug19_stage45.py uses for the same routes), and the model and
transport pins never open a socket at all. The three that need a real collection
— a settings blob, an event's reminder, a task's priority — carry the `radicale`
marker and use the shared `client` fixture.

Test DATA below carries real lone surrogates, deliberately: a `"\ud800"` that
was escaped on the way in would test nothing. test_source_encodable.py exempts
data and forbids them in docstrings, which is why this docstring is raw and the
literals live in the test bodies.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import threading
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tasksd import app as app_module
from tasksd.app import create_app
from tasksd.auth import HashBudget
from tasksd.db import store
from tasksd.mcp import oauth as O
from tasksd.mcp import routes as R
from tasksd.mcp.server import INVALID_PARAMS, McpServer
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog]

ISSUER = "https://tasks.example.test"
MCP_URL = f"{ISSUER}/mcp"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "testpass123"
LONE_SURROGATE = "\ud800"


# ── a connector app with no CalDAV server behind it ──────────────────────────

class _StubService:
    """Enough TaskService for the OAuth endpoints: they only ever touch the
    SQLite side, through `oauth()`."""

    def __init__(self) -> None:
        self._conn = store.connect(":memory:")
        store.init_db(self._conn)
        self._lock = threading.RLock()

    def oauth(self, fn, *a, **kw):
        with self._lock:
            return fn(self._conn, *a, **kw)


def _mcp_app(tmp_path):
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "sep03.db")), mcp_enabled=True, public_url=ISSUER)
    app = create_app(settings)
    app.state.service = _StubService()
    return app


@pytest.fixture
def mcp(tmp_path):
    """`raise_server_exceptions=False`: half of these pins are about a 500 that
    must become a 4xx, and the default would turn the 500 into a traceback in
    the test instead of a status code to assert on. The peer is loopback so
    `_client_ip` honours `X-Real-IP`, the way it does behind Caddy."""
    return TestClient(_mcp_app(tmp_path), raise_server_exceptions=False,
                      client=("127.0.0.1", 40000))


def _pkce() -> tuple[str, str]:
    import base64
    import hashlib
    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(client, **over) -> dict:
    body = {"client_name": "Claude", "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none", **over}
    r = client.post("/oauth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _authorize_params(reg, challenge, **over) -> dict:
    return {
        "response_type": "code", "client_id": reg["client_id"],
        "redirect_uri": CALLBACK, "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "xyz",
        "scope": "mcp:read mcp:write offline_access", "resource": MCP_URL, **over,
    }


def _signed_request(page_text: str) -> str:
    return re.search(r'name="request" value="([^"]+)"', page_text).group(1)


def _consent(client, reg, challenge, *, password=PASSWORD, headers=None):
    page = client.get("/oauth/authorize", params=_authorize_params(reg, challenge))
    assert page.status_code == 200, page.text
    return client.post("/oauth/authorize", data={
        "request": _signed_request(page.text), "action": "approve", "grant": "full",
        "username": "admin", "password": password,
    }, follow_redirects=False, headers=headers or {})


def _json_ascii(client, method: str, path: str, body) -> httpx.Response:
    """Send `body` ASCII-escaped, which is what `json.dumps` does by default and
    what a hand-rolled client sends. httpx's `json=` renders with
    `ensure_ascii=False` and would refuse the surrogate client-side, which is
    the wrong side to refuse it on for a test of the server."""
    return client.request(method, path, content=json.dumps(body),
                          headers={"content-type": "application/json"})


# ── AUDIT #1: a drained hash budget locks the owner out for 15 minutes ────────

@pytest.mark.stage2
def test_a_drained_hash_budget_never_turns_a_correct_password_into_a_lockout(tmp_path, monkeypatch):
    """`HashBudget`'s docstring is the invariant: a bucket rather than a counter,
    so that "the owner may meet a 429 and retry a few seconds later, and never a
    fifteen-minute wall". The login route broke it one line later — it reserves
    a per-client failure with `limiter.attempt` BEFORE the global `take()`, and
    when the bucket is empty it raises 429 without handing the reservation back.
    No hash ran, nothing was proved, but the caller is charged a guess. Five of
    those (the header says "retry in 10 s", so the owner obliges) and the
    per-client limiter locks the key for 900 s; the sixth correct password
    answers `Retry-After: 899` and stays refused after the attacker stops.

    Drives the exact scenario: twelve wrong guesses from twelve /64s empty the
    bucket, then six correct passwords from one unrelated address. Every
    Retry-After must be the bucket's (at most `refill_s`), never the limiter's
    lockout, and once the bucket has refilled the same address signs in.
    """
    app = create_app(api_settings(str(tmp_path / "login.db")))
    transport = httpx.ASGITransport(app=app)
    owner = {"X-Real-IP": "203.0.113.7"}
    right = {"username": "admin", "password": PASSWORD}

    async def drain_then_sign_in() -> list[tuple[int, str | None]]:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            for block in range(12):
                await c.post("/api/login", json={"username": "admin", "password": "wrong"},
                             headers={"X-Real-IP": f"2001:db8:0:{block:x}::1"})
            out = []
            for _ in range(6):
                r = await c.post("/api/login", json=right, headers=owner)
                out.append((r.status_code, r.headers.get("Retry-After")))
            return out

    seen = asyncio.run(drain_then_sign_in())
    ceiling = HashBudget().refill_s
    for code, retry in seen:
        assert code in (200, 429), seen
        if code == 429:
            assert int(retry) <= ceiling, (
                f"Retry-After {retry} on a CORRECT password: the global 429 charged "
                f"the owner a guess and the per-client limiter locked them out — {seen}"
            )

    # ...and the wall really is not there: once the bucket has refilled, the
    # same address logs in. Advanced rather than slept, and in a fresh loop so
    # the offset is in place before anything reads the clock.
    import time as _time
    base = _time.monotonic
    monkeypatch.setattr(_time, "monotonic", lambda: base() + ceiling * 2)

    async def sign_in() -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return (await c.post("/api/login", json=right, headers=owner)).status_code

    assert asyncio.run(sign_in()) == 200, "the owner is still locked out after the bucket refilled"


@pytest.mark.stage2
def test_a_drained_hash_budget_never_locks_the_owner_out_of_the_consent_screen(mcp):
    """The consent POST shares `hash_budget` with /api/login and has the same
    reserve-then-global-check ordering, so it has the same hole: a drained
    bucket charges `consent_limiter` (8 per 15 min) for a password that was
    never checked. Drained through /api/login here — that is how an attacker
    would do it, the budget being global — and then ten correct passwords on
    the consent form from one address. None may meet the limiter's lockout."""
    reg = _register(mcp)
    _, challenge = _pkce()
    for block in range(12):
        mcp.post("/api/login", json={"username": "admin", "password": "wrong"},
                 headers={"X-Real-IP": f"2001:db8:0:{block:x}::1"})
    owner = {"X-Real-IP": "203.0.113.7"}
    seen = []
    for _ in range(10):
        r = _consent(mcp, reg, challenge, headers=owner)
        seen.append((r.status_code, r.headers.get("Retry-After")))
    ceiling = HashBudget().refill_s
    for code, retry in seen:
        assert code in (303, 429), seen
        if code == 429:
            assert int(retry) <= ceiling, (
                f"Retry-After {retry} on a CORRECT password at the consent screen — {seen}"
            )


# ── AUDIT #2: a lone surrogate in a settings id poisons every later read ─────

@pytest.mark.stage1
@pytest.mark.radicale
def test_a_lone_surrogate_in_a_settings_id_is_refused_and_settings_stay_readable(client):
    """pydantic refuses a lone surrogate only for a `str` that carries a
    constraint — the Rust conversion path — and every id-carrying settings field
    was a bare `list[str]`. The write LANDED (the store escapes with
    `ensure_ascii=True`) and then every GET /api/settings, which the SPA does on
    boot, and every later PUT died in Starlette's renderer with
    UnicodeEncodeError until the poisoned key was overwritten wholesale.

    A theme token is the other door: `_clean_tokens` filters with Python `re`,
    which handles surrogates happily. There the contract is "filter, do not
    reject", so the token must be DROPPED and the write succeed."""
    try:
        r = _json_ascii(client, "PUT", "/api/settings", {"hidden_calendars": [LONE_SURROGATE]})
        assert r.status_code == 422, (r.status_code, r.text[:200])
        r = _json_ascii(client, "PUT", "/api/settings", {"appearance": {
            "active": "t",
            "themes": [{"id": "t", "name": "n", "light": {"--bg": LONE_SURROGATE}}]}})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        assert r.json()["appearance"]["themes"][0]["light"] == {}
        assert client.get("/api/settings").status_code == 200
        assert client.put("/api/settings", json={"theme": "dark"}).status_code == 200
    finally:
        # The `client` fixture is session-scoped: never leave the shared blob
        # poisoned for whatever runs next.
        client.put("/api/settings", json={"hidden_calendars": [], "appearance": None})


@pytest.mark.stage1
def test_every_id_carrying_field_refuses_a_lone_surrogate():
    """The same class on every other unconstrained id the finding lists. Those
    reach `resolve_list`/SQLite unencoded and 500 transiently rather than
    persistently, but the guard is the same one and it is cheap to pin them all
    in-process. `CustomTheme` is the exception by design: it filters."""
    S = LONE_SURROGATE
    cases = [
        (app_module.SettingsPatch, {"hidden_calendars": [S]}),
        (app_module.SettingsPatch, {"archived_calendars": [S]}),
        (app_module.SettingsPatch, {"hidden_lists": [S]}),
        (app_module.SettingsPatch, {"collapsed_groups": [S]}),
        (app_module.SettingsPatch, {"collapsed_tasks": [S]}),
        (app_module.SettingsPatch, {"calendar_task_lists": [S]}),
        (app_module.SettingsPatch, {"task_groups": [{"id": "g", "name": "n", "lists": [S]}]}),
        (app_module.ReorderLists, {"ids": [S]}),
        (app_module.ReorderEntry, {"list": S, "uid": "u"}),
        (app_module.ReorderEntry, {"list": "l", "uid": S}),
        (app_module.MoveEvent, {"calendar": S}),
        (app_module.EditDisplay, {"calendars": [S]}),
        (app_module.EditDisplay, {"lists": [S]}),
        (app_module.CreateDisplay, {"name": "n", "calendars": [S]}),
        (app_module.CreateDisplay, {"name": "n", "lists": [S]}),
        (app_module.CreateBookingLink, {"title": "t", "calendar": S, "timezone": "UTC"}),
        (app_module.CreateBookingLink, {"title": "t", "calendar": "c", "timezone": "UTC",
                                        "availability": {S: ["09:00-10:00"]}}),
        (app_module.CreateBookingLink, {"title": "t", "calendar": "c", "timezone": "UTC",
                                        "availability": {"mon": [S]}}),
        (app_module.EditBookingLink, {"calendar": S}),
        (app_module.EditBookingLink, {"availability": {"mon": [S]}}),
        (app_module.CreateTask, {"summary": "s", "parent": S}),
        (app_module.EditTask, {"parent": S}),
    ]
    accepted = []
    for model, kwargs in cases:
        try:
            model(**kwargs)
        except ValidationError:
            continue
        accepted.append((model.__name__, list(kwargs)))
    assert accepted == [], f"lone surrogate accepted by: {accepted}"
    # The filter, not the refusal: a theme keeps what it can.
    theme = app_module.CustomTheme(id="t", name="n", light={"--bg": S, "--fg": "#123456"})
    assert theme.light == {"--fg": "#123456"}


# ── AUDIT #3: PUT .../events/{uid}/reminder was never reachable ─────────────

@pytest.mark.stage4
@pytest.mark.radicale
def test_an_existing_events_reminder_can_be_set_and_cleared_over_http(client):
    """`EventReminder` was a class local to `create_app`. With
    `from __future__ import annotations` the `body: EventReminder` annotation is
    a string FastAPI resolves against module globals, where the nested class
    does not exist — so `body` registered as a required QUERY parameter and every
    call, any body, any uid, answered 422 before the handler ran. This is the
    only route the SPA has for a reminder on an existing event."""
    cal = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}"}).json()
    cid = cal["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Standup", "start": "2026-09-07T09:00:00", "end": "2026-09-07T09:15:00",
    }).json()
    uid = ev["uid"]

    r = client.put(f"/api/calendars/{cid}/events/{uid}/reminder", json={"notify_minutes_before": 5})
    assert r.status_code == 200, r.text
    assert r.json()["notify_minutes_before"] == 5
    assert client.get(f"/api/calendars/{cid}/events/{uid}").json()["notify_minutes_before"] == 5

    r = client.put(f"/api/calendars/{cid}/events/{uid}/reminder", json={"notify_minutes_before": -1})
    assert r.status_code == 200, r.text
    assert r.json()["notify_minutes_before"] is None
    assert client.get(f"/api/calendars/{cid}/events/{uid}").json()["notify_minutes_before"] is None

    r = client.put(f"/api/calendars/{cid}/events/no-such-event/reminder",
                   json={"notify_minutes_before": 5})
    assert r.status_code == 404, r.text
    # ...and the body is still validated as a body: out of range is a 422.
    r = client.put(f"/api/calendars/{cid}/events/{uid}/reminder", json={"notify_minutes_before": 99999})
    assert r.status_code == 422, r.text


# ── AUDIT #4: urlsplit's ValueError escapes three OAuth endpoints ─────────────

@pytest.mark.stage1
@pytest.mark.parametrize("bad", ["https://[abc/cb", "https://claude.ai／evil.example/cb"])
def test_an_unparseable_url_is_a_readable_oauth_error_not_a_500(mcp, bad):
    """CPython's `urlsplit` raises ValueError for an unmatched `[` in the netloc
    and for a host that changes under NFKC normalisation (a fullwidth solidus).
    `_check_redirect_uri`, `_redirect_allowed` and `_canonical_resource` all
    call it on wholly caller-supplied strings, and the routes catch only
    OAuthError — so registration, the unthrottled GET /oauth/authorize, and the
    token exchange each answered a bare 500. Worse on the token endpoint: the
    crash came AFTER `take_oauth_code` had consumed the one-shot code, so a
    client with a malformed `resource` lost its code to a 500 instead of being
    told `invalid_target`. The exchange now checks the resource before it
    consumes anything, so the code survives a readable refusal."""
    # Registration.
    r = mcp.post("/oauth/register", json={"redirect_uris": [bad]})
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert r.json()["error"] == "invalid_redirect_uri"

    # The authorization endpoint, both on redirect_uri and on resource.
    reg = _register(mcp)
    verifier, challenge = _pkce()
    r = mcp.get("/oauth/authorize", params=_authorize_params(reg, challenge, redirect_uri=bad),
                follow_redirects=False)
    assert r.status_code == 400, (r.status_code, r.text[:200])
    r = mcp.get("/oauth/authorize", params=_authorize_params(reg, challenge, resource=bad),
                follow_redirects=False)
    assert r.status_code in (303, 400), (r.status_code, r.text[:200])
    if r.status_code == 303:
        assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["invalid_target"]

    # The token endpoint: a readable error, and the code is still good.
    code = parse_qs(urlsplit(_consent(mcp, reg, challenge).headers["location"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
            "client_id": reg["client_id"], "code_verifier": verifier}
    r = mcp.post("/oauth/token", data={**form, "resource": bad})
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert r.json()["error"] == "invalid_target"
    r = mcp.post("/oauth/token", data={**form, "resource": MCP_URL})
    assert r.status_code == 200, (
        f"the code was burned by the malformed resource: {r.status_code} {r.text[:200]}")


# ── AUDIT #5: an unknown priority label silently means "none" ────────────────

@pytest.mark.stage3
@pytest.mark.radicale
def test_an_unknown_priority_label_is_refused_rather_than_clearing_the_priority(client):
    """`priority_from_label` is `PRIORITY.get(label, 0)`, so "urgent" or a typo
    became PRIORITY:0 on the wire — a task the owner marked high rewritten to
    none, answered 200. `status` on the same model is refused with 422 and the
    MCP schema pins an enum, so HTTP was the one door that accepted junk.

    Case is normalised the way `_check_status` normalises it: the contract is
    the four labels, and "HIGH" names one of them."""
    lid = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()["id"]
    task = client.post(f"/api/lists/{lid}/tasks", json={"summary": "x", "priority": "high"}).json()
    uid = task["uid"]
    assert task["priority_label"] == "high"

    for junk in ("urgent", "hgih", "", "  "):
        r = client.patch(f"/api/lists/{lid}/tasks/{uid}", json={"priority": junk})
        assert r.status_code == 422, (junk, r.status_code, r.text[:200])
    assert client.get(f"/api/lists/{lid}/tasks/{uid}").json()["priority_label"] == "high"

    r = client.post(f"/api/lists/{lid}/tasks", json={"summary": "y", "priority": "urgent"})
    assert r.status_code == 422, (r.status_code, r.text[:200])
    r = client.post(f"/api/lists/{lid}/tasks", json={"summary": "y", "priority": "HIGH"})
    assert r.status_code == 201 and r.json()["priority_label"] == "high", r.text[:200]
    # CONTROL: an explicit null on PATCH still clears, as it always did.
    r = client.patch(f"/api/lists/{lid}/tasks/{uid}", json={"priority": "none"})
    assert r.status_code == 200 and r.json()["priority_label"] == "none", r.text[:200]


# ── AUDIT #6: the 201 from /oauth/register echoes the raw client_name ────────

@pytest.mark.stage1
def test_registering_a_client_name_with_a_lone_surrogate_answers_201_with_the_stored_name(mcp):
    """The earlier fix made the two error strings and the STORED name
    `wire_safe`, and left the success body built from `str(name)[:200]` — the
    unmodified caller value. `create_oauth_client` had already committed, so an
    anonymous caller got a 500 for a client row that now exists and whose id
    they will never learn. The echo is the stored value, encodable by
    construction."""
    r = _json_ascii(mcp, "POST", "/oauth/register",
                    {"redirect_uris": [CALLBACK], "client_name": LONE_SURROGATE + "evil"})
    assert r.status_code == 201, (r.status_code, r.text[:200])
    body = r.json()
    stored = mcp.app.state.service.oauth(store.get_oauth_client, body["client_id"])
    assert body["client_name"] == stored["client_name"] == O.wire_safe(LONE_SURROGATE + "evil")


# ── AUDIT #7: the wrong-password retry drops the consent page's CSP ──────────

@pytest.mark.stage4
def test_the_consent_retry_carries_the_same_policy_as_the_first_render(mcp):
    """GET /oauth/authorize sets its own `default-src 'none'; style-src
    'unsafe-inline'`, which has no `form-action`. The 401 re-render after a
    mistyped password set only Cache-Control and X-Frame-Options, so
    `CSPMiddleware` filled in the SPA policy — with `form-action 'self'`.
    Chromium enforces form-action against the REDIRECT of a form submission
    (measured, not assumed: see the finding), so the correct retry's 303 to the
    client's callback was refused and the 60 s code lost. Only a fresh start
    from the client worked. One header set for every HTML answer in the flow."""
    reg = _register(mcp)
    _, challenge = _pkce()
    first = mcp.get("/oauth/authorize", params=_authorize_params(reg, challenge))
    assert first.status_code == 200
    policy = first.headers["content-security-policy"]
    assert "form-action" not in policy      # the premise: the first render is unconstrained

    retry = mcp.post("/oauth/authorize", data={
        "request": _signed_request(first.text), "action": "approve", "grant": "full",
        "username": "admin", "password": "wrong"})
    assert retry.status_code == 401
    assert retry.headers.get("content-security-policy") == policy, (
        f"the retry carries {retry.headers.get('content-security-policy')!r}")
    assert retry.headers.get("x-frame-options") == first.headers["x-frame-options"]

    # The notice pages on the same flow: same headers, so the three HTML
    # answers of one flow no longer carry three different sets.
    expired = mcp.post("/oauth/authorize", data={"request": "not-a-signed-blob", "action": "approve"})
    assert expired.status_code == 400
    assert expired.headers.get("content-security-policy") == policy
    assert expired.headers.get("x-frame-options") == first.headers["x-frame-options"]


# ── AUDIT #8: a non-object `params` is reported as an internal error ─────────

@pytest.mark.stage1
def test_a_non_object_params_is_invalid_params_without_a_traceback(caplog):
    """`message.get("params") or {}` substitutes a dict only for a FALSY value;
    a truthy list, string or number reached `params.get(...)`, raised
    AttributeError, and the generic handler logged a full traceback and told the
    client -32603 INTERNAL_ERROR — an error class it is entitled to retry, for a
    request that can never succeed. Every sibling shape error in the same
    function (`arguments`, `name`, the id) is a readable -32602/-32600."""
    srv = McpServer.__new__(McpServer)
    srv.tools = {}
    with caplog.at_level(logging.ERROR, logger="tasksd.mcp"):
        for method in ("tools/call", "initialize"):
            for params in ([1], "x", 5, True, [{"name": "smylte_list_lists"}]):
                out = srv.handle({"jsonrpc": "2.0", "id": 1, "method": method,
                                  "params": params}, scopes=set())
                assert out["error"]["code"] == INVALID_PARAMS, (method, params, out)
                assert "AttributeError" not in out["error"]["message"]
    assert not [r for r in caplog.records if r.exc_info], (
        "a caller's shape error was logged as a server failure with a traceback")
    # CONTROL: absent, null and an empty object are still the empty-params path.
    # (`[]` used to pass too, by the accident of being falsy; it is a non-object
    # like `[1]` and is now refused the same way.)
    for message in ({}, {"params": None}, {"params": {}}):
        out = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", **message},
                         scopes=set())
        assert "result" in out, (message, out)


# ── AUDIT #9: the consent page's mobile input, buttons and dark contrast ──────

def _contrast(fg: str, bg: str) -> float:
    def lum(hex6: str) -> float:
        def ch(c: int) -> float:
            v = c / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex6[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _rule(css: str, selector: str, *, dark: bool = False) -> str:
    """The declarations of `selector`'s block, in the light sheet or the dark
    media block. A small parser rather than a regex over the whole sheet, so the
    same selector can be read in both."""
    if dark:
        css = css[css.index("@media (prefers-color-scheme: dark)"):]
    else:
        css = css[:css.index("@media (prefers-color-scheme: dark)")]
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else ""


@pytest.mark.stage4
def test_the_consent_page_keeps_the_apps_mobile_input_and_contrast_rules():
    """The one server-rendered page a phone user hits when connecting, and none
    of the SPA's rules reach it. Three legs stand (the verifier refuted the
    light-mode caption contrast and the i18n leg — the server is documented as
    untranslated, and the captions are higher-contrast than the app's own):

    * inputs computed to 15 px, under the 16 px floor the SPA enforces at
      `@media (max-width: 720px)` so iOS Safari does not zoom on focus — the
      regression app.css calls "the third time this exact regression has
      shipped", on the page where the owner types their password;
    * the buttons were 37 px tall, AND `font: 500 14px/1 inherit` is invalid
      CSS (`inherit` is not a family name) so the whole shorthand was dropped
      and they rendered in Arial at 13.33 px;
    * `.choice em` — the two sentences the trust decision is made from — had no
      dark override: #6b6157 on the #1c1917 card is 2.89:1.
    """
    req = O.AuthRequest(client_id="c", client_name="Claude", redirect_uri=CALLBACK,
                        scope="mcp:read mcp:write offline_access", resource=MCP_URL,
                        code_challenge="x" * 43, state="s")
    page = R._consent_page(req, "signed", issuer=ISSUER)
    css = page[page.index("<style>") + len("<style>"):page.index("</style>")]

    inputs = _rule(css, "input[type=text], input[type=password]")
    assert re.search(r"font-size:\s*16px", inputs), f"inputs: {inputs.strip()!r}"

    button = _rule(css, "button")
    assert re.search(r"min-height:\s*44px", button), f"button: {button.strip()!r}"
    assert not re.search(r"\bfont:\s*[^;]*inherit", button), (
        "`font: ... inherit` is an invalid shorthand and is dropped whole")
    assert re.search(r"font-family:\s*inherit", button), f"button: {button.strip()!r}"

    em_dark = _rule(css, ".choice em", dark=True)
    m = re.search(r"color:\s*(#[0-9a-fA-F]{6})", em_dark)
    assert m, "no dark override for .choice em"
    card_dark = re.search(r"background:\s*(#[0-9a-fA-F]{6})", _rule(css, ".card", dark=True)).group(1)
    assert _contrast(m.group(1), card_dark) >= 4.5, (m.group(1), card_dark)


# ── AUDIT #10: guards nothing exercises ──────────────────────────────────────

def _server(now):
    conn = store.connect(":memory:")
    store.init_db(conn)
    srv = O.OAuthServer(issuer=ISSUER, mcp_url=MCP_URL, secret="s" * 40,
                        verify_password=lambda u, p: p == PASSWORD, now=now)
    return conn, srv


@pytest.mark.stage5
def test_an_expired_code_and_an_expired_access_token_are_both_refused():
    """`take_oauth_code`'s `expires_at > now` (CODE_TTL_S = 60 s) and
    `verify_bearer`'s `expires_at <= now` (ACCESS_TTL_S = 1 h) were never
    crossed by any test: the verifier deleted both and the suite stayed green.

    The clock is advanced, not the TTL shortened — the verifier's refinement.
    A negative ACCESS_TTL_S passes even with the expiry check deleted, because
    `_issue_pair` runs `gc_oauth`, which sweeps the already-expired row and the
    401 comes from "unknown access token" for the wrong reason."""
    clock = [1_700_000_000.0]
    conn, srv = _server(lambda: clock[0])
    reg = srv.register(conn, {"redirect_uris": [CALLBACK], "client_name": "Claude"})
    verifier, challenge = _pkce()
    req = O.AuthRequest(client_id=reg["client_id"], client_name="Claude", redirect_uri=CALLBACK,
                        scope="mcp:read mcp:write offline_access", resource=MCP_URL,
                        code_challenge=challenge, state="s")

    def exchange(code):
        return srv.token(conn, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
            "client_id": reg["client_id"], "code_verifier": verifier, "resource": MCP_URL,
        }, basic_auth=None)

    # CONTROL: inside the TTL the exchange works.
    code = srv.issue_code(conn, req, scope=req.scope)
    clock[0] += O.CODE_TTL_S - 1
    grant = exchange(code)
    assert srv.verify_bearer(conn, grant["access_token"])["client_id"] == reg["client_id"]

    # One second past the code's TTL: invalid_grant.
    code = srv.issue_code(conn, req, scope=req.scope)
    clock[0] += O.CODE_TTL_S + 1
    with pytest.raises(O.OAuthError) as e:
        exchange(code)
    assert e.value.error == "invalid_grant"

    # One second past the access token's TTL: 401, and for the RIGHT reason.
    clock[0] += O.ACCESS_TTL_S + 1
    with pytest.raises(O.OAuthError) as e:
        srv.verify_bearer(conn, grant["access_token"])
    assert e.value.status == 401 and "expired" in e.value.description


@pytest.mark.stage5
def test_a_registrants_client_name_cannot_plant_markup_on_the_password_prompt():
    """`_consent_page` renders an anonymous registrant's `client_name` into the
    `<h1>` and the "Application" row through `html.escape`, and no test ever
    registered a name containing `<`. The page's own CSP (`default-src 'none'`)
    keeps a `<script>` from running, but it declares no `form-action`, and the
    name is rendered BEFORE the real form — so an unescaped
    `<form action="https://evil/">` would swallow the username and password
    typed below it. Markup generally, not just `<script>`."""
    hostile = '<b>x</b><script>1</script><form action="https://evil.example/">'
    req = O.AuthRequest(client_id="c", client_name=hostile, redirect_uri=CALLBACK,
                        scope="mcp:read", resource=MCP_URL, code_challenge="x" * 43, state="")
    page = R._consent_page(req, "signed", issuer=ISSUER)
    assert "<script>" not in page and "evil.example/\">" not in page
    assert page.count("<form") == 1 and 'action="/oauth/authorize"' in page
    assert "&lt;form action=&quot;https://evil.example/&quot;&gt;" in page
