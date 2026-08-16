"""HTTP wiring for the MCP endpoint and its authorization server.

Everything here is registered outside `/api` on purpose. That router carries
`Depends(require_auth)` — a cookie gate — and a test walks it asserting every
route behind it 401s without a session. These routes answer to a bearer token or
to nobody, so putting them under `/api` would mean either weakening that gate or
adding exceptions to it. A separate prefix says what is true: this is a second
front door, with its own lock.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import html
import json
import logging
from urllib.parse import parse_qsl, unquote

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..auth import RateLimiter, limiter_key
from .api import McpApi
from .oauth import OAuthError, OAuthServer, SCOPE_OFFLINE, SCOPE_READ, SCOPE_WRITE, scope_set, scope_str
from ..db.store import get_oauth_client as _get_oauth_client
from ..db.store import list_oauth_grants as _list_grants, revoke_oauth_family as _revoke_family
from .server import McpServer, parse_body, run_batch

log = logging.getLogger("tasksd.mcp")

# A POST to /oauth/authorize verifies a password, so it is throttled exactly
# like /api/login — same shape, separate budget, so a connector flow being
# fumbled cannot lock the owner out of the web app (or the reverse).
_CONSENT_LIMITER = dict(max_fails=8, window_s=900, lockout_s=900)
# ...and a separate, generous budget for POSTing the form at all. A decline
# spends only this one, so declining a connection a few times cannot lock the
# owner out of ever connecting. Shaped like _TOKEN_LIMITER: enough to stop the
# endpoint being hammered, nowhere near tight enough to matter to a person.
_CONSENT_POST_LIMITER = dict(max_fails=120, window_s=300, lockout_s=300)
# Registration and token exchange are cheap but unauthenticated; these bound
# what an anonymous caller can make the server do.
_REGISTER_LIMITER = dict(max_fails=20, window_s=3600, lockout_s=3600)
_TOKEN_LIMITER = dict(max_fails=120, window_s=300, lockout_s=300)

# The metadata documents are public and fetched cross-origin by browser-based
# clients. Set per response rather than by app-wide CORS middleware, which would
# be this app's first and would reach the cookie-gated surface too.
_PUBLIC_JSON = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=300",
}


def _oauth_error(exc: OAuthError) -> JSONResponse:
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if exc.status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="smylte"'
    return JSONResponse(body, status_code=exc.status, headers=headers)


def _basic_auth(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(" ", 1)[1], validate=True).decode()
        client_id, secret = raw.split(":", 1)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    return unquote(client_id), unquote(secret)


# What each of these endpoints could ever legitimately receive. A DCR
# registration and an OAuth form are both a few hundred bytes; the MCP cap is
# generous enough for a large batch and small enough to be harmless.
_MAX_FORM_BYTES = 64_000
_MAX_JSON_BYTES = 64_000
_MAX_RPC_BYTES = 1_000_000


async def _read_capped(request: Request, cap: int) -> bytes:
    """Read a body, refusing an oversized one *without* absorbing it first.

    `await request.body()` buffers the whole stream and only then hands it over,
    so checking the length afterwards means the memory has already been spent —
    on endpoints an unauthenticated caller can reach. Content-Length is checked
    first where it is offered, but a chunked request need not offer one, so the
    running total is what actually enforces the cap: the read stops at the first
    chunk that crosses it.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")
    return bytes(buf)


async def _form(request: Request) -> dict[str, str]:
    """Parse an `application/x-www-form-urlencoded` body.

    Hand-parsed rather than via `request.form()`, which pulls in python-multipart
    for a multipart path nothing here wants: RFC 6749 §4.1.3 specifies
    form-urlencoded and that is all these endpoints accept. A last value wins,
    matching every other form parser, so a duplicated key cannot smuggle a
    second reading of the same parameter past a check that saw the first.
    """
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/x-www-form-urlencoded":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "expected application/x-www-form-urlencoded",
        )
    raw = await _read_capped(request, _MAX_FORM_BYTES)
    try:
        pairs = parse_qsl(raw.decode(), keep_blank_values=True, strict_parsing=False)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed form body") from None
    return dict(pairs)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return None


def register(app, *, settings, authenticator, client_ip, run, login_hashes):
    """Mount the MCP endpoint and its authorization server onto `app`.

    Called from create_app before the static mount — that mount is a full-match
    catch-all, so anything registered after it is unreachable.
    """
    issuer = settings.public_url
    mcp_url = f"{issuer}/mcp"
    prm_doc = "/.well-known/oauth-protected-resource"

    def verify_password(username: str, password: str) -> bool:
        # With auth disabled there is no password to check, and the app is
        # already wide open — this refuses anyway rather than minting tokens for
        # anyone who asks, because a token outlives the dev posture that made it.
        if authenticator is None:
            return False
        return authenticator.check_credentials(username, password)

    oauth = OAuthServer(
        issuer=issuer, mcp_url=mcp_url,
        secret=settings.session_secret or "mcp-dev-secret",
        verify_password=verify_password,
    )
    consent_limiter = RateLimiter(**_CONSENT_LIMITER)
    consent_post_limiter = RateLimiter(**_CONSENT_POST_LIMITER)
    register_limiter = RateLimiter(**_REGISTER_LIMITER)
    token_limiter = RateLimiter(**_TOKEN_LIMITER)

    def _server(request: Request) -> McpServer:
        # Built lazily: create_app registers routes before the lifespan has made
        # the service, so the tool table cannot be built at registration time.
        srv = getattr(request.app.state, "mcp_server", None)
        if srv is None:
            srv = McpServer(McpApi(request.app.state.service))
            request.app.state.mcp_server = srv
        return srv

    def _throttle(request: Request, limiter: RateLimiter) -> None:
        key = limiter_key(client_ip(request))
        if not limiter.attempt(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "too many requests, try later",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )

    # ── discovery ────────────────────────────────────────────────────────────
    # Served at the bare well-known path and at the path-suffixed spelling RFC
    # 9728 defines for a resource with a path. A client probes one or the other
    # depending on its reading of the RFC, and answering both costs nothing.

    async def protected_resource(request: Request):
        return JSONResponse(oauth.protected_resource_metadata(), headers=_PUBLIC_JSON)

    async def auth_server(request: Request):
        return JSONResponse(oauth.authorization_server_metadata(), headers=_PUBLIC_JSON)

    for path in (prm_doc, f"{prm_doc}/mcp"):
        app.add_api_route(path, protected_resource, methods=["GET"], include_in_schema=False)
    for path in ("/.well-known/oauth-authorization-server",
                 "/.well-known/oauth-authorization-server/mcp",
                 # Some clients look for OIDC discovery first and fall back.
                 "/.well-known/openid-configuration"):
        app.add_api_route(path, auth_server, methods=["GET"], include_in_schema=False)

    # ── dynamic client registration ──────────────────────────────────────────

    @app.post("/oauth/register", include_in_schema=False)
    async def oauth_register(request: Request):
        _throttle(request, register_limiter)
        try:
            body = json.loads(await _read_capped(request, _MAX_JSON_BYTES))
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            return _oauth_error(OAuthError("invalid_client_metadata", "body must be JSON"))
        if not isinstance(body, dict):
            return _oauth_error(OAuthError("invalid_client_metadata", "body must be an object"))
        try:
            out = await run(request.app.state.service.oauth, oauth.register, body)
        except OAuthError as exc:
            return _oauth_error(exc)
        return JSONResponse(out, status_code=201, headers={"Cache-Control": "no-store"})

    # ── authorization endpoint ───────────────────────────────────────────────

    @app.get("/oauth/authorize", include_in_schema=False)
    async def authorize_form(request: Request):
        try:
            req = await run(request.app.state.service.oauth, oauth.parse_authorize,
                            dict(request.query_params))
        except OAuthError as exc:
            return _authorize_failure(exc, dict(request.query_params))
        return HTMLResponse(
            _consent_page(req, oauth.sign_request(req), issuer=issuer),
            headers={"Cache-Control": "no-store",
                     # The consent page is ours and frames nothing; a clickjacked
                     # approval button would be a real problem.
                     "X-Frame-Options": "DENY",
                     "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"},
        )

    @app.post("/oauth/authorize", include_in_schema=False)
    async def authorize_submit(request: Request):
        # Two limiters, because this endpoint guards two different things and
        # one counter could not do both. `consent_post_limiter` is the generous
        # one: it bounds how hard the endpoint can be hammered, and it is charged
        # here — before the body is read — because that read is unauthenticated
        # and used to happen with no limit in front of it at all.
        #
        # The password budget (`consent_limiter`, 8 per 15 min) is charged much
        # further down, only when a password is actually about to be verified.
        # Charging it here made a DECLINE cost a password guess, so eight "no
        # thanks" clicks locked the owner out of connecting for the window.
        #
        # Note what is deliberately NOT done: refunding the password budget on a
        # decline. `record_success` clears the counter outright, so an attacker
        # alternating guess/deny would never lock out — and registration is open,
        # so minting the signed blobs to do that is free. Splitting the counters
        # is what fixes the lockout without opening that door.
        _throttle(request, consent_post_limiter)
        form = await _form(request)
        try:
            req = oauth.verify_request(form.get("request", ""))
        except OAuthError as exc:
            return HTMLResponse(_notice_page(
                "That sign-in form expired",
                "Consent forms are only good for a few minutes. Start the "
                "connection again from your client.",
            ), status_code=400)

        if form.get("action") != "approve":
            return RedirectResponse(
                oauth.redirect_with(req.redirect_uri, _with_state(
                    {"error": "access_denied",
                     "error_description": "the request was declined"}, req.state)),
                status_code=303,
            )

        # Narrowing is allowed: the consent screen offers read-only, and a
        # granted scope can never exceed what the request asked for.
        granted = scope_set(req.scope)
        if form.get("grant") == "read":
            granted &= {SCOPE_READ, SCOPE_OFFLINE}
            # ...but a narrowing that grants nothing is not a narrowing. On a
            # write-only request the intersection is empty, and approving it
            # minted a code for a token that could do nothing at all — surfacing
            # later as an unexplained "not permitted" on every call, a long way
            # from the screen that caused it. The consent page no longer offers
            # the choice in that case; this refuses the POST, which is reachable
            # regardless of what the page rendered.
            if not (granted - {SCOPE_OFFLINE}):
                # Rendered, not redirected: this is a form POST a person is
                # looking at, and the sibling failure above (an expired form)
                # answers the same way. Bouncing them back to the client with
                # `error=invalid_scope` would hand a human a machine's error.
                return HTMLResponse(_notice_page(
                    "Read-only would grant nothing",
                    "This application asked for write access only, so limiting "
                    "it to read-only would leave it unable to do anything. "
                    "Start again and approve it in full, or decline it.",
                ), status_code=400)

        # The password budget is spent HERE — one unit per password actually
        # verified — and reserved before the await, which is the property
        # RateLimiter.attempt exists to provide.
        _throttle(request, consent_limiter)
        async with login_hashes:
            # scrypt is memory-hard (~16 MiB a call). /api/login bounds its
            # concurrency for exactly that reason and this runs the same hash on
            # the same unauthenticated surface, so it shares the same semaphore:
            # the budget being protected is the process's memory, not one
            # endpoint's throughput.
            ok = await run(oauth.check_password,
                           form.get("username", ""), form.get("password", ""))
        if not ok:
            return HTMLResponse(
                # Carrying the choice back: without it a mistyped password
                # re-armed "Full access", so retyping the password silently
                # granted write to someone who had deliberately picked
                # read-only. The screen exists for that choice.
                #
                # ...and carrying the NAME back too. `verify_request` rebuilds
                # the request from the signed blob, which holds client_id but
                # not client_name, so it hardcodes "" and parse_authorize's
                # "an application" fallback took over. The first render said
                # "Claude wants access"; one mistyped password and the retry
                # said "an application" — at the exact moment the user is being
                # asked to type a password and decide whether to trust the
                # caller. Re-resolved from the id rather than widening the blob,
                # which would put an attacker-supplied name inside a signature.
                _consent_page(await _named(request, req), form.get("request", ""), issuer=issuer,
                              grant=form.get("grant") or "full",
                              error="That username or password was not right."),
                status_code=401,
                headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
            )
        consent_limiter.record_success(limiter_key(client_ip(request)))

        code = await run(request.app.state.service.oauth, oauth.issue_code, req,
                         scope=scope_str(granted))
        log.info("mcp: granted %s to client %s", scope_str(granted), req.client_id)
        return RedirectResponse(
            oauth.redirect_with(req.redirect_uri, _with_state({"code": code}, req.state)),
            status_code=303, headers={"Cache-Control": "no-store"},
        )

    async def _named(request: Request, req):
        """`req` with the client's registered name filled back in."""
        if req.client_name:
            return req
        row = await run(request.app.state.service.oauth,
                        _get_oauth_client, req.client_id)
        name = (row or {}).get("client_name") if row is not None else None
        return dataclasses.replace(req, client_name=name or "") if name else req

    def _authorize_failure(exc: OAuthError, params: dict):
        """A failed authorization request.

        Only bounced back to the client once the client and its redirect_uri
        have been verified — otherwise this would be an open redirect, and an
        attacker could point it anywhere by inventing parameters.
        """
        if exc.redirectable and params.get("redirect_uri"):
            return RedirectResponse(
                oauth.redirect_with(params["redirect_uri"], _with_state(
                    {"error": exc.error, "error_description": exc.description},
                    params.get("state", ""))),
                status_code=303,
            )
        return HTMLResponse(
            _notice_page("That connection request was refused", exc.description or exc.error),
            status_code=exc.status,
        )

    # ── token + revocation ───────────────────────────────────────────────────

    @app.post("/oauth/token", include_in_schema=False)
    async def oauth_token(request: Request):
        _throttle(request, token_limiter)
        # RFC 6749 §4.1.3: form-encoded, and Claude sends exactly that.
        form = await _form(request)
        try:
            out = await run(request.app.state.service.oauth, oauth.token, form,
                            basic_auth=_basic_auth(request))
        except OAuthError as exc:
            return _oauth_error(exc)
        return JSONResponse(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @app.post("/oauth/revoke", include_in_schema=False)
    async def oauth_revoke(request: Request):
        _throttle(request, token_limiter)
        form = await _form(request)
        await run(request.app.state.service.oauth, oauth.revoke, form,
                  basic_auth=_basic_auth(request))
        # RFC 7009: always 200, so this never says whether the token was real.
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    # ── connections, for the owner ───────────────────────────────────────────
    # These two live on /api behind the cookie gate, unlike everything else in
    # this module: they are the owner managing their own grants from the web
    # app, not a client presenting a token. The consent screen promises this
    # exists, so it has to.

    @app.get("/api/mcp/connections", include_in_schema=False)
    async def list_connections(request: Request):
        _require_owner(request)
        import time as _time
        return {"connections": await run(
            request.app.state.service.oauth, _list_grants, now=_time.time())}

    @app.delete("/api/mcp/connections/{family_id}", include_in_schema=False)
    async def drop_connection(request: Request, family_id: str):
        _require_owner(request)
        dropped = await run(request.app.state.service.oauth, _revoke_family, family_id)
        if not dropped:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown connection")
        log.info("mcp: connection %s disconnected by the owner", family_id)
        return Response(status_code=204)

    def _require_owner(request: Request) -> None:
        """The cookie gate, applied by hand.

        `require_auth` is a router dependency and these routes are registered on
        the app rather than that router — so the check is explicit here rather
        than implied, which is also why it reads as its own named step.
        """
        if authenticator is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        if not authenticator.verify_session(request.cookies.get("tasks_session")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")

    # ── the MCP endpoint ─────────────────────────────────────────────────────

    def _unauthorized(description: str) -> JSONResponse:
        """A 401 the client can act on.

        `resource_metadata` is the pointer that starts the whole discovery
        dance; without it a client that has never seen this server has no way to
        learn where to authorize, and simply reports that it cannot connect.
        """
        return JSONResponse(
            {"error": "invalid_token", "error_description": description},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="smylte", '
                    f'resource_metadata="{issuer}{prm_doc}", '
                    f'scope="{SCOPE_READ} {SCOPE_WRITE} {SCOPE_OFFLINE}", '
                    f'error="invalid_token", error_description="{description}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/mcp", include_in_schema=False)
    async def mcp_endpoint(request: Request):
        # DNS-rebinding guard. Claude calls server-to-server and sends no Origin;
        # a browser always does, so a present-but-foreign Origin is a page trying
        # to drive this endpoint and is refused.
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != issuer:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")

        version = request.headers.get("mcp-protocol-version")
        if version and version not in ("2025-06-18", "2025-03-26", "2024-11-05",
                                       "2025-11-25", "2026-07-28"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"unsupported MCP-Protocol-Version: {version}")

        try:
            grant = await run(request.app.state.service.oauth,
                              oauth.verify_bearer, _bearer(request))
        except OAuthError as exc:
            return _unauthorized(exc.description or exc.error)

        raw = await _read_capped(request, _MAX_RPC_BYTES)
        try:
            payload = parse_body(raw)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "invalid JSON"}},
                status_code=400,
            )

        scopes = scope_set(grant["scope"])
        try:
            out = await run(run_batch, _server(request), payload, scopes=scopes)
        except OAuthError as exc:
            return _unauthorized(exc.description or exc.error)
        if out is None:
            # Notifications and responses get 202 with no body, per the spec.
            return Response(status_code=202)
        return JSONResponse(out)

    @app.get("/mcp", include_in_schema=False)
    @app.delete("/mcp", include_in_schema=False)
    async def mcp_no_stream(request: Request):
        # The spec's own answer for a server that offers no server-initiated
        # stream and holds no session to delete.
        return Response(status_code=405, headers={"Allow": "POST"})


def _with_state(params: dict, state: str) -> dict:
    if state:
        params = {**params, "state": state}
    return params


# ── the pages ────────────────────────────────────────────────────────────────
# Deliberately self-contained: the SPA's stylesheet is content-hashed at build
# time and this has to render on a server whose frontend was never built.

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center;
  justify-content: center; padding: 24px;
  background: #faf8f5; color: #1a1714;
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
.card { width: 100%; max-width: 27rem; background: #fff; border: 1px solid #e4ded5;
  padding: 30px 30px 26px; }
h1 { margin: 0 0 6px; font: 600 25px/1.2 ui-serif, Georgia, serif; letter-spacing: -0.01em; }
.eyebrow { margin: 0 0 18px; font: 500 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0.14em; text-transform: uppercase; color: #8a7f72; }
p { margin: 0 0 14px; color: #4a423a; }
strong { color: #1a1714; }
.who { border: 1px solid #e4ded5; background: #faf8f5; padding: 12px 14px; margin: 0 0 18px; }
.who div + div { margin-top: 6px; }
.k { display: block; margin-bottom: 3px; font: 500 10px/1 ui-monospace, monospace;
  letter-spacing: 0.1em; text-transform: uppercase; color: #8a7f72; }
.v { display: block; word-break: break-word; }
ul { margin: 0 0 18px; padding-left: 18px; color: #4a423a; }
li { margin-bottom: 4px; }
label { display: block; margin-bottom: 12px; }
/* Field captions only — .choice wraps a span too, and this rule was turning
   its description into an uppercase mono micro-label. */
label:not(.choice) > span { display: block; margin-bottom: 5px;
  font: 500 10px/1 ui-monospace, monospace; letter-spacing: 0.1em;
  text-transform: uppercase; color: #8a7f72; }
input[type=text], input[type=password] { width: 100%; padding: 9px 11px;
  border: 1px solid #d6cec2; background: #fff; color: inherit; font: inherit; }
input:focus { outline: 2px solid #d9480f; outline-offset: -1px; }
.choice { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 14px;
  padding: 11px 13px; border: 1px solid #e4ded5; }
.choice input { margin-top: 3px; }
.choice > span { flex: 1; }
.choice em { display: block; margin-top: 2px; font-style: normal;
  color: #6b6157; font-size: 13px; }
.actions { display: flex; gap: 10px; margin-top: 20px; }
button { flex: 1; padding: 10px 14px; border: 1px solid #1a1714; background: #1a1714;
  color: #faf8f5; font: 500 14px/1 inherit; cursor: pointer; }
button.ghost { background: none; color: #1a1714; border-color: #d6cec2; }
.err { border: 1px solid #c0392b; color: #c0392b; padding: 9px 12px; margin: 0 0 16px;
  font-size: 14px; }
.foot { margin: 18px 0 0; padding-top: 14px; border-top: 1px solid #e4ded5;
  font-size: 12.5px; color: #8a7f72; }
@media (prefers-color-scheme: dark) {
  body { background: #14120f; color: #ece7e0; }
  .card { background: #1c1917; border-color: #332e28; }
  .who { background: #14120f; border-color: #332e28; }
  p, ul, li { color: #b8b0a6; }
  strong { color: #ece7e0; }
  input[type=text], input[type=password] { background: #14120f; border-color: #443d35; color: inherit; }
  .choice { border-color: #332e28; }
  button { background: #ece7e0; color: #14120f; border-color: #ece7e0; }
  button.ghost { background: none; color: #ece7e0; border-color: #443d35; }
  .foot { border-color: #332e28; }
}
"""


def _shell(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main class=\"card\">{body}</main></body></html>"
    )


def _consent_page(req, signed: str, *, issuer: str, grant: str = "full",
                  error: str = "") -> str:
    from urllib.parse import urlsplit

    scopes = scope_set(req.scope)
    where = urlsplit(req.redirect_uri)
    # The hostname is shown because it is the one thing that distinguishes a
    # genuine client from one that merely says it is Claude.
    host = where.hostname or req.redirect_uri
    name = html.escape(req.client_name or "An application")
    can = []
    if SCOPE_READ in scopes:
        can.append("Read your task lists, tasks, calendars, events and bookings")
    if SCOPE_WRITE in scopes:
        can.append("Create, change and <strong>delete</strong> tasks, lists, "
                   "calendars and events")
    if SCOPE_OFFLINE in scopes:
        can.append("Stay connected without asking you again, until you disconnect it")

    read_only_choice = ""
    # Offered only when there is something left after narrowing. A write-only
    # request has nothing: `granted &= {READ, OFFLINE}` empties it, so picking
    # read-only produced a token that could do nothing at all. Never render a
    # choice whose outcome is "no access" — the POST refuses it either way, but
    # a button that cannot work should not be there to press.
    if SCOPE_WRITE in scopes and SCOPE_READ in scopes:
        read = ' checked' if grant == "read" else ""
        full = "" if grant == "read" else " checked"
        read_only_choice = (
            f'<label class="choice"><input type="radio" name="grant" value="full"{full}>'
            "<span><strong>Full access</strong>"
            "<em>Read and change everything above.</em></span></label>"
            f'<label class="choice"><input type="radio" name="grant" value="read"{read}>'
            "<span><strong>Read-only</strong>"
            "<em>It can see your data but not change or delete anything.</em></span></label>"
        )

    return _shell(
        "Connect to Smylte",
        (
            '<p class="eyebrow">Smylte</p>'
            f"<h1>Connect {name}?</h1>"
            + (f'<div class="err">{html.escape(error)}</div>' if error else "")
            + '<div class="who">'
            f'<div><span class="k">Application</span><span class="v">{name}</span></div>'
            f'<div><span class="k">Will send you back to</span>'
            f'<span class="v">{html.escape(host)}</span></div></div>'
            "<p>If you did not just start this from that application, close this page.</p>"
            "<p><strong>It will be able to:</strong></p><ul>"
            + "".join(f"<li>{c}</li>" for c in can)
            + "</ul>"
            f'<form method="post" action="/oauth/authorize">'
            f'<input type="hidden" name="request" value="{html.escape(signed)}">'
            + read_only_choice
            + '<label><span>Username</span>'
            '<input type="text" name="username" autocomplete="username" '
            'autocapitalize="off" autocorrect="off" required autofocus></label>'
            '<label><span>Password</span>'
            '<input type="password" name="password" autocomplete="current-password" required></label>'
            '<div class="actions">'
            '<button type="submit" name="action" value="deny" class="ghost">Cancel</button>'
            '<button type="submit" name="action" value="approve">Connect</button>'
            "</div></form>"
            '<p class="foot">Signing in here grants this application a token for '
            "your tasks and calendar. You can disconnect it at any time from "
            "Settings &rsaquo; Connected apps.</p>"
        ),
    )


def _notice_page(title: str, detail: str) -> str:
    return _shell(title, (
        '<p class="eyebrow">Smylte</p>'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(detail)}</p>"
    ))
