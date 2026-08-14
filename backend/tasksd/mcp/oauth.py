"""OAuth 2.1 authorization server for the remote MCP endpoint.

Scope of this module: it is *both* the authorization server and the resource
server, because there is exactly one account here and no identity provider to
delegate to. The user's own app password is the credential; what this adds is a
way to hand a client a narrow, revocable, audience-bound token instead of that
password.

What the MCP specification requires of it, and where each lands:

  * RFC 9728 protected resource metadata, and a 401 carrying
    ``WWW-Authenticate: Bearer resource_metadata=...`` so a client can find it
    without being told  ................................  `protected_resource_metadata`
  * RFC 8414 authorization server metadata  ............  `authorization_server_metadata`
  * RFC 7591 dynamic client registration  ..............  `register`
  * PKCE S256, mandatory — no `plain`, no omission  ....  `authorize` / `token`
  * RFC 8707 resource indicators, so a token is bound to
    this server and useless anywhere else  .............  `_check_resource`, `verify_bearer`

Three decisions worth stating, because they are not the obvious ones:

**Tokens are opaque, not JWTs.** The app already signs session cookies with
HS256 and `session_claims` checks neither `aud` nor `iss` — so any HS256 token
minted with that key and a plausible `exp` would be accepted as a full session
cookie. A JWT access token would have had to carry a discriminator that both
sides agreed on forever. Random strings stored as SHA-256 hashes cannot be
confused with a session by construction, cannot be forged if the database leaks,
and are revocable without a denylist.

**The consent screen always asks for the password.** The session cookie is
`SameSite=Strict`, so it is not sent on a cross-site navigation from a client —
the user would look logged out here anyway. Rather than weaken the cookie, this
treats "grant an API token" as worth re-authenticating for, which it is.

**The consent POST is bound to a request this server issued.** Without that, a
phishing page could auto-submit its own form here with its own `client_id`: the
user would type their password into what looks like a login, and the code would
land on the attacker's redirect. `_sign_request` closes that — the POST only
counts if it carries a signature over parameters this server already validated
and rendered.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

# ── lifetimes ────────────────────────────────────────────────────────────────
# Short access tokens because the spec asks for them and refresh is cheap; a
# long refresh because reconnecting means re-typing a password. The consent
# request is a page the user is looking at, so ten minutes is generous.
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 24 * 3600
CODE_TTL_S = 60
CONSENT_TTL_S = 600
# A client that registered and never came back is junk (registration is open).
CLIENT_IDLE_S = 24 * 3600
# Bounds a hostile registrant; well above any real client's needs.
MAX_CLIENTS = 500
MAX_REDIRECT_URIS = 10

SCOPE_READ = "mcp:read"
SCOPE_WRITE = "mcp:write"
SCOPE_OFFLINE = "offline_access"
SUPPORTED_SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_OFFLINE)
DEFAULT_SCOPE = f"{SCOPE_READ} {SCOPE_WRITE} {SCOPE_OFFLINE}"


class OAuthError(Exception):
    """An RFC 6749 error. `redirectable` marks the ones the spec wants handed
    back to the client via its redirect_uri rather than rendered here — which is
    only ever true once the client and its redirect_uri have been verified."""

    def __init__(self, error: str, description: str = "", *,
                 status: int = 400, redirectable: bool = False):
        super().__init__(f"{error}: {description}" if description else error)
        self.error = error
        self.description = description
        self.status = status
        self.redirectable = redirectable


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def scope_set(scope: str | None) -> set[str]:
    return {s for s in (scope or "").split() if s}


def scope_str(scopes: set[str]) -> str:
    """Canonical order, so a granted scope string is comparable and stable."""
    return " ".join(s for s in SUPPORTED_SCOPES if s in scopes)


@dataclass(frozen=True)
class AuthRequest:
    """A validated authorization request, as rendered on the consent screen."""

    client_id: str
    client_name: str
    redirect_uri: str
    scope: str
    resource: str
    code_challenge: str
    state: str


class OAuthServer:
    """The authorization server, over the app's SQLite connection.

    Every method here is synchronous and expects to be called through the
    service's lock (the routes hop to a thread, as they do for everything else).
    """

    def __init__(self, *, issuer: str, mcp_url: str, secret: str,
                 verify_password, now=time.time):
        self.issuer = issuer.rstrip("/")
        # The canonical resource identifier, RFC 8707 §2: what a token is bound
        # to and what the client must name. One spelling only.
        self.mcp_url = mcp_url.rstrip("/")
        # Derived, not shared: this key only ever signs consent requests, so it
        # cannot be confused with the session key even though both trace back to
        # TASKS_SESSION_SECRET.
        self._key = hmac.new(secret.encode(), b"tasksd/mcp/oauth-request",
                             hashlib.sha256).digest()
        self._verify_password = verify_password
        self._now = now

    # ── metadata documents ───────────────────────────────────────────────────

    def protected_resource_metadata(self) -> dict:
        """RFC 9728. `resource` must equal the URL the user typed into the
        client, including the path — a mismatch is why a connector that reaches
        the server still fails to authorize."""
        return {
            "resource": self.mcp_url,
            "authorization_servers": [self.issuer],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "bearer_methods_supported": ["header"],
            "resource_name": "Smylte",
        }

    def authorization_server_metadata(self) -> dict:
        """RFC 8414. `token_endpoint_auth_methods_supported` leads with "none"
        because a connector registering through DCR is a public client — it has
        nowhere to keep a secret. A pre-registered confidential client may still
        post one, hence the other two."""
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/oauth/authorize",
            "token_endpoint": f"{self.issuer}/oauth/token",
            "registration_endpoint": f"{self.issuer}/oauth/register",
            "revocation_endpoint": f"{self.issuer}/oauth/revoke",
            "scopes_supported": list(SUPPORTED_SCOPES),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "none", "client_secret_post", "client_secret_basic",
            ],
            "revocation_endpoint_auth_methods_supported": [
                "none", "client_secret_post", "client_secret_basic",
            ],
            "service_documentation": "https://github.com/nicholaskmitchell/smylte",
        }

    # ── dynamic client registration (RFC 7591) ───────────────────────────────

    def register(self, conn, body: dict) -> dict:
        """Register a client. Open by design — the MCP spec wants a client to be
        able to connect with no prior setup, and a registration is worth nothing
        on its own: it cannot mint a token without the password at the consent
        screen. What it could do is fill the table, so registrations are capped
        and swept."""
        from ..db import store

        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris:
            raise OAuthError("invalid_redirect_uri", "redirect_uris is required")
        if len(uris) > MAX_REDIRECT_URIS:
            raise OAuthError("invalid_redirect_uri", "too many redirect_uris")
        clean: list[str] = []
        for u in uris:
            if not isinstance(u, str):
                raise OAuthError("invalid_redirect_uri", "redirect_uris must be strings")
            clean.append(_check_redirect_uri(u))

        store.gc_oauth(conn, now=self._now(), client_idle_s=CLIENT_IDLE_S)
        if store.count_oauth_clients(conn) >= MAX_CLIENTS:
            raise OAuthError("invalid_request", "too many registered clients",
                             status=429)

        requested = scope_set(body.get("scope")) or scope_set(DEFAULT_SCOPE)
        unknown = requested - set(SUPPORTED_SCOPES)
        if unknown:
            raise OAuthError("invalid_client_metadata",
                             f"unsupported scope: {' '.join(sorted(unknown))}")

        # "none" means a public client, which is what DCR clients are. Anything
        # else gets a secret; we only ever store its hash.
        auth_method = body.get("token_endpoint_auth_method") or "none"
        if auth_method not in ("none", "client_secret_post", "client_secret_basic"):
            raise OAuthError("invalid_client_metadata",
                             f"unsupported token_endpoint_auth_method: {auth_method}")

        client_id = secrets.token_urlsafe(24)
        secret_plain = None if auth_method == "none" else secrets.token_urlsafe(32)
        name = body.get("client_name")
        now = self._now()
        store.create_oauth_client(
            conn,
            client_id=client_id,
            client_secret_hash=sha256_hex(secret_plain) if secret_plain else None,
            client_name=str(name)[:200] if isinstance(name, str) else None,
            redirect_uris=clean,
            scope=scope_str(requested),
            now=now,
        )
        out = {
            "client_id": client_id,
            "client_id_issued_at": int(now),
            "redirect_uris": clean,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": auth_method,
            "scope": scope_str(requested),
        }
        if isinstance(name, str):
            out["client_name"] = str(name)[:200]
        if secret_plain:
            # The only time this value exists in the clear. Never expires — a
            # confidential client that loses it re-registers.
            out["client_secret"] = secret_plain
            out["client_secret_expires_at"] = 0
        return out

    # ── authorization endpoint ───────────────────────────────────────────────

    def parse_authorize(self, conn, params) -> AuthRequest:
        """Validate an authorization request.

        Order is deliberate. Until the client and its redirect_uri are known
        good, nothing may be sent to that URI — an unvalidated redirect is an
        open redirect, and OAuth 2.1 is explicit that these two failures are
        rendered locally rather than bounced back.
        """
        from ..db import store

        client_id = params.get("client_id") or ""
        client = store.get_oauth_client(conn, client_id) if client_id else None
        if client is None:
            raise OAuthError("invalid_client", "unknown client_id", status=400)

        redirect_uri = params.get("redirect_uri") or ""
        if not redirect_uri:
            # RFC 6749 allows defaulting to the sole registered URI; requiring it
            # is stricter and costs a compliant client nothing.
            raise OAuthError("invalid_request", "redirect_uri is required")
        if not _redirect_allowed(redirect_uri, client["redirect_uris"]):
            raise OAuthError("invalid_request", "redirect_uri is not registered")

        # Past this line the client is verified, so failures are redirectable.
        if (params.get("response_type") or "") != "code":
            raise OAuthError("unsupported_response_type",
                             "only response_type=code is supported", redirectable=True)

        challenge = params.get("code_challenge") or ""
        method = params.get("code_challenge_method") or ""
        if not challenge:
            raise OAuthError("invalid_request", "PKCE code_challenge is required",
                             redirectable=True)
        if method != "S256":
            raise OAuthError("invalid_request",
                             "code_challenge_method must be S256", redirectable=True)
        if not (43 <= len(challenge) <= 128):
            raise OAuthError("invalid_request", "malformed code_challenge",
                             redirectable=True)

        self._check_resource(params.get("resource"), redirectable=True)

        allowed = scope_set(client["scope"]) or scope_set(DEFAULT_SCOPE)
        requested = scope_set(params.get("scope")) or allowed
        unknown = requested - set(SUPPORTED_SCOPES)
        if unknown:
            raise OAuthError("invalid_scope",
                             f"unsupported scope: {' '.join(sorted(unknown))}",
                             redirectable=True)
        granted = requested & allowed
        if not (granted - {SCOPE_OFFLINE}):
            raise OAuthError("invalid_scope", "no usable scope requested",
                             redirectable=True)

        return AuthRequest(
            client_id=client_id,
            client_name=client["client_name"] or "an application",
            redirect_uri=redirect_uri,
            scope=scope_str(granted),
            resource=self.mcp_url,
            code_challenge=challenge,
            state=params.get("state") or "",
        )

    def sign_request(self, req: AuthRequest) -> str:
        """A short-lived signature over a request this server rendered.

        This is what makes the consent POST unforgeable: without it, a page
        elsewhere could post its own client_id here and collect the code after
        the user typed a password into what looked like a login form.
        """
        payload = {
            "c": req.client_id, "r": req.redirect_uri, "s": req.scope,
            "h": req.code_challenge, "t": req.state,
            "e": int(self._now()) + CONSENT_TTL_S,
        }
        raw = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        sig = _b64url(hmac.new(self._key, raw.encode(), hashlib.sha256).digest())
        return f"{raw}.{sig}"

    def verify_request(self, blob: str) -> AuthRequest:
        try:
            raw, sig = (blob or "").split(".", 1)
            expected = _b64url(hmac.new(self._key, raw.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected):
                raise ValueError("bad signature")
            payload = json.loads(_b64url_decode(raw))
        except Exception as exc:  # noqa: BLE001 — any malformation is one failure
            raise OAuthError("invalid_request", "invalid consent request") from exc
        if float(payload.get("e", 0)) < self._now():
            raise OAuthError("invalid_request", "the consent request expired")
        return AuthRequest(
            client_id=payload["c"], client_name="", redirect_uri=payload["r"],
            scope=payload["s"], resource=self.mcp_url,
            code_challenge=payload["h"], state=payload.get("t", ""),
        )

    def check_password(self, username: str, password: str) -> bool:
        return self._verify_password(username, password)

    def issue_code(self, conn, req: AuthRequest, *, scope: str) -> str:
        """Mint a one-shot authorization code for an approved request."""
        from ..db import store

        code = secrets.token_urlsafe(32)
        now = self._now()
        store.create_oauth_code(
            conn,
            code_hash=sha256_hex(code),
            client_id=req.client_id,
            redirect_uri=req.redirect_uri,
            scope=scope,
            resource=req.resource,
            code_challenge=req.code_challenge,
            expires_at=now + CODE_TTL_S,
            now=now,
        )
        store.touch_oauth_client(conn, req.client_id, now)
        return code

    @staticmethod
    def redirect_with(uri: str, params: dict[str, str]) -> str:
        """Append params to a redirect_uri, preserving any it already carries."""
        parts = urlsplit(uri)
        query = "&".join(x for x in (parts.query, urlencode(params)) if x)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))

    # ── token endpoint ───────────────────────────────────────────────────────

    def token(self, conn, form: dict, *, basic_auth: tuple[str, str] | None) -> dict:
        grant = form.get("grant_type") or ""
        if grant == "authorization_code":
            return self._grant_code(conn, form, basic_auth)
        if grant == "refresh_token":
            return self._grant_refresh(conn, form, basic_auth)
        raise OAuthError("unsupported_grant_type", f"unsupported grant_type: {grant!r}")

    def _authenticate_client(self, conn, form: dict,
                             basic_auth: tuple[str, str] | None) -> dict:
        from ..db import store

        client_id = (basic_auth[0] if basic_auth else None) or form.get("client_id") or ""
        secret = (basic_auth[1] if basic_auth else None) or form.get("client_secret")
        client = store.get_oauth_client(conn, client_id) if client_id else None
        if client is None:
            # 401 per RFC 6749 §5.2 — the client itself failed to authenticate.
            raise OAuthError("invalid_client", "unknown client", status=401)
        stored = client["client_secret_hash"]
        if stored:
            if not secret or not hmac.compare_digest(sha256_hex(secret), stored):
                raise OAuthError("invalid_client", "bad client credentials", status=401)
        elif secret:
            # A public client presenting a secret is a confused client, not an
            # authenticated one. Refuse rather than silently ignore it.
            raise OAuthError("invalid_client",
                             "this client is registered as public", status=401)
        return client

    def _grant_code(self, conn, form: dict, basic_auth) -> dict:
        from ..db import store

        client = self._authenticate_client(conn, form, basic_auth)
        code = form.get("code") or ""
        if not code:
            raise OAuthError("invalid_request", "code is required")
        row = store.take_oauth_code(conn, sha256_hex(code), now=self._now())
        if row is None:
            raise OAuthError("invalid_grant", "the code is unknown, used or expired")
        # A code issued to one client must not be redeemable by another, even
        # though both authenticated successfully as themselves.
        if not hmac.compare_digest(row["client_id"], client["client_id"]):
            raise OAuthError("invalid_grant", "the code was issued to another client")
        if not hmac.compare_digest(form.get("redirect_uri") or "", row["redirect_uri"]):
            raise OAuthError("invalid_grant", "redirect_uri does not match the request")

        verifier = form.get("code_verifier") or ""
        if not (43 <= len(verifier) <= 128):
            raise OAuthError("invalid_grant", "malformed code_verifier")
        digest = _b64url(hashlib.sha256(verifier.encode("ascii", "ignore")).digest())
        if not hmac.compare_digest(digest, row["code_challenge"]):
            raise OAuthError("invalid_grant", "code_verifier does not match the challenge")

        # A `resource` on the exchange is optional, but if sent it must agree
        # with what the code was bound to.
        if form.get("resource"):
            self._check_resource(form.get("resource"))
        return self._issue_pair(conn, client_id=client["client_id"], scope=row["scope"],
                                resource=row["resource"], family_id=secrets.token_hex(16))

    def _grant_refresh(self, conn, form: dict, basic_auth) -> dict:
        from ..db import store

        client = self._authenticate_client(conn, form, basic_auth)
        presented = form.get("refresh_token") or ""
        if not presented:
            raise OAuthError("invalid_request", "refresh_token is required")
        token_hash = sha256_hex(presented)
        row = store.get_oauth_token(conn, token_hash)
        if row is None or row["kind"] != "refresh":
            raise OAuthError("invalid_grant", "unknown refresh token")
        if not hmac.compare_digest(row["client_id"], client["client_id"]):
            raise OAuthError("invalid_grant", "the token was issued to another client")

        state = store.use_refresh_token(conn, token_hash, now=self._now())
        if state == "invalid":
            raise OAuthError("invalid_grant", "the refresh token has expired")
        if state == "replayed":
            # Two presentations of a single-use token means a copy is loose and
            # we cannot tell which holder is the legitimate one. End the grant.
            store.revoke_oauth_family(conn, row["family_id"])
            raise OAuthError("invalid_grant",
                             "this refresh token was already used; the grant has been revoked")

        # A refresh may narrow scope but never widen it (RFC 6749 §6).
        granted = scope_set(row["scope"])
        if form.get("scope"):
            asked = scope_set(form.get("scope"))
            if asked - granted:
                raise OAuthError("invalid_scope", "a refresh cannot widen scope")
            granted = asked
        return self._issue_pair(conn, client_id=client["client_id"],
                                scope=scope_str(granted), resource=row["resource"],
                                family_id=row["family_id"])

    def _issue_pair(self, conn, *, client_id: str, scope: str, resource: str,
                    family_id: str) -> dict:
        from ..db import store

        now = self._now()
        access = secrets.token_urlsafe(32)
        store.create_oauth_token(
            conn, token_hash=sha256_hex(access), kind="access", client_id=client_id,
            scope=scope, resource=resource, family_id=family_id,
            expires_at=now + ACCESS_TTL_S, now=now,
        )
        out = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL_S,
            "scope": scope,
        }
        # Only issue a refresh token if offline access was actually granted —
        # a client that did not ask for it should not silently get one.
        if SCOPE_OFFLINE in scope_set(scope):
            refresh = secrets.token_urlsafe(32)
            store.create_oauth_token(
                conn, token_hash=sha256_hex(refresh), kind="refresh",
                client_id=client_id, scope=scope, resource=resource,
                family_id=family_id, expires_at=now + REFRESH_TTL_S, now=now,
            )
            out["refresh_token"] = refresh
        store.touch_oauth_client(conn, client_id, now)
        store.gc_oauth(conn, now=now, client_idle_s=CLIENT_IDLE_S)
        return out

    # ── revocation (RFC 7009) ────────────────────────────────────────────────

    def revoke(self, conn, form: dict, *, basic_auth) -> None:
        """Revoke a token and, with it, its whole rotation family.

        RFC 7009 is explicit that an unknown token is a success, so this never
        reveals whether a value was real.
        """
        from ..db import store

        try:
            client = self._authenticate_client(conn, form, basic_auth)
        except OAuthError:
            return
        presented = form.get("token") or ""
        if not presented:
            return
        row = store.get_oauth_token(conn, sha256_hex(presented))
        if row and hmac.compare_digest(row["client_id"], client["client_id"]):
            store.revoke_oauth_family(conn, row["family_id"])

    # ── resource-server side ─────────────────────────────────────────────────

    def verify_bearer(self, conn, token: str | None) -> dict:
        """Resolve a bearer token to its grant, or raise.

        The audience check is the one the MCP spec is most insistent about: a
        token minted for some other resource must not work here, even if this
        server issued it. Since this server only ever issues for `mcp_url`, the
        check is cheap — but it is the difference between a bug and a breach if
        that ever stops being true.
        """
        from ..db import store

        if not token:
            raise OAuthError("invalid_token", "no access token", status=401)
        row = store.get_oauth_token(conn, sha256_hex(token))
        if row is None or row["kind"] != "access":
            raise OAuthError("invalid_token", "unknown access token", status=401)
        if row["expires_at"] <= self._now():
            raise OAuthError("invalid_token", "the access token has expired", status=401)
        if not hmac.compare_digest(row["resource"], self.mcp_url):
            raise OAuthError("invalid_token",
                             "this token was issued for another resource", status=401)
        return row

    def _check_resource(self, value: str | None, *, redirectable: bool = False) -> None:
        """RFC 8707. Absent is tolerated — older clients predate the requirement
        and this server has exactly one resource to bind to — but a *wrong* one
        is refused, because it means the client believes it is talking to
        something else."""
        if not value:
            return
        if _canonical_resource(value) != self.mcp_url:
            raise OAuthError("invalid_target",
                             f"resource must be {self.mcp_url}", redirectable=redirectable)


def _canonical_resource(value: str) -> str:
    """Normalise a resource identifier for comparison. Scheme and host are
    case-insensitive per RFC 3986, and the spec asks clients to accept either
    case for robustness; a trailing slash is dropped for the same reason."""
    parts = urlsplit(value.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
    )


def _check_redirect_uri(uri: str) -> str:
    """A registrable redirect URI: HTTPS, or a loopback address for a native
    client (RFC 8252). Anything else — http to a real host, a custom scheme, a
    fragment — is refused at registration so it can never be redirected to."""
    parts = urlsplit(uri.strip())
    if parts.fragment:
        raise OAuthError("invalid_redirect_uri", "redirect_uri must not carry a fragment")
    host = (parts.hostname or "").lower()
    if parts.scheme == "https":
        if not host:
            raise OAuthError("invalid_redirect_uri", "redirect_uri needs a host")
        return uri.strip()
    if parts.scheme == "http" and host in ("localhost", "127.0.0.1", "::1"):
        return uri.strip()
    raise OAuthError(
        "invalid_redirect_uri",
        "redirect_uri must use https, or http on a loopback address",
    )


def _redirect_allowed(presented: str, registered: list[str]) -> bool:
    """Exact match, except that a loopback redirect ignores the port.

    RFC 8252 §7.3 requires the port to be ignored for `127.0.0.1`, because a
    native client binds an ephemeral one it cannot know in advance. Claude Code
    registers `http://localhost/callback` and then arrives on a random port, so
    the same latitude is extended to `localhost` — deliberately, and only for
    loopback, where the alternative is that native clients simply cannot work.
    """
    for candidate in registered:
        if hmac.compare_digest(presented, candidate):
            return True
    p = urlsplit(presented)
    host = (p.hostname or "").lower()
    if p.scheme != "http" or host not in ("localhost", "127.0.0.1", "::1"):
        return False
    for candidate in registered:
        c = urlsplit(candidate)
        if (c.scheme == "http"
                and (c.hostname or "").lower() == host
                and c.path == p.path
                and c.query == p.query):
            return True
    return False
