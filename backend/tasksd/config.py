"""Runtime configuration, read from the environment.

Dev defaults point at the **scratch** Radicale (127.0.0.1:5233), never
production. Production values are supplied via the systemd environment file at
deploy time (spec §9).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .limits import DEFAULT_MAX_BODY_BYTES


_TRUE = frozenset({"1", "true", "yes", "y", "on"})
_FALSE = frozenset({"0", "false", "no", "n", "off"})


def _bool(name: str, default: bool) -> bool:
    """Parse a boolean env var, refusing anything it does not recognise.

    Every caller here gates a security control — auth_enabled, cookie_secure,
    access_required — and treating an unrecognised value as "not true" made all
    three fail OPEN. `TASKS_AUTH_ENABLED=Y`, `=enabled`, or a plain typo turned
    off the whole API auth gate on an internet-facing deployment, silently and
    with no way to tell from the outside but to try it.

    An unusable value is now a startup error, which matches how the app already
    treats missing Access configuration: refuse to come up rather than come up
    unprotected.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(
        f"{name}={raw!r} is not a boolean; use one of "
        f"{sorted(_TRUE)} or {sorted(_FALSE)}"
    )


def normalize_dav_url(raw: str) -> str:
    """Where raw CalDAV lives, as clients must reach it. Path or absolute URL,
    always with a trailing slash (it is a collection, and RFC 6764 discovery
    redirects to a *context path*, not a file)."""
    v = (raw or "").strip() or "/dav/"
    if not v.startswith(("http://", "https://", "/")):
        v = "/" + v
    return v if v.endswith("/") else v + "/"


def normalize_public_url(raw: str) -> str:
    """This deployment's external origin, without a trailing slash.

    RFC 8707 defines the canonical form of a resource identifier, and RFC 9728's
    `resource` field has to match what the client was pointed at — so the two
    spellings of the same origin must not both be reachable. Trailing slash is
    dropped for the same reason the MCP spec asks clients to omit it.
    """
    v = (raw or "").strip().rstrip("/")
    if v and not v.startswith(("http://", "https://")):
        v = "https://" + v
    return v


@dataclass(frozen=True)
class Settings:
    radicale_url: str          # origin, e.g. http://127.0.0.1:5233 (no trailing slash)
    radicale_user: str
    radicale_password: str
    db_path: str               # SQLite cache file; disposable by construction (invariant #1)
    sync_interval_s: float     # background poll cadence (~30s per spec §4)
    request_timeout_s: float
    static_dir: str            # built frontend dist/ served by FastAPI
    hook_secret: str           # shared secret for POST /internal/changed (spec §4)
    # App username/password auth (the public gate). ON by default; refuses to
    # start with no password set. Tests/dev may disable it.
    auth_enabled: bool
    auth_user: str
    auth_password_hash: str    # scrypt hash from `python -m tasksd hash-password`
    auth_password: str         # plaintext, DEV ONLY — hashed at startup, logged as insecure
    session_secret: str        # HS256 signing key for session cookies (persist in prod)
    session_ttl_s: int
    cookie_secure: bool        # Secure flag; True in prod (HTTPS), False for local http
    # Cloudflare Access — now OPTIONAL defense-in-depth (off by default).
    access_required: bool
    access_team_domain: str
    access_aud: str
    # Where raw CalDAV is published for device clients (the reverse proxy's
    # /dav split, or an absolute URL if DAV lives on its own host). Only used
    # to answer RFC 6764 discovery — see the discovery routes in app.py.
    dav_public_url: str = "/dav/"
    # Remote MCP server (Claude connectors). OFF by default: turning it on adds
    # publicly reachable OAuth endpoints, and a deploy should never grow an auth
    # surface on its own. See tasksd/mcp/.
    mcp_enabled: bool = False
    # This deployment's external origin, e.g. https://tasks.example.com. The
    # OAuth metadata documents have to state absolute URLs, and the `resource`
    # a token is bound to must match what the client was pointed at — so it is
    # configured rather than read off the Host header, which a caller controls.
    public_url: str = ""
    # Largest request body accepted, enforced ahead of the router — see
    # tasksd/limits.py for why it cannot live in the routes themselves.
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    # ── outbound notifications (OPT-IN) ──────────────────────────────────────
    # Off by default for the same reason the MCP connector is: a deploy should
    # never grow an outbound network surface on its own. Turning this on is a
    # deliberate act with a deployment consequence — deploy/tasks.service is
    # loopback-only (`IPAddressDeny=any`), so the unit must be widened before a
    # single message can leave the box. See docs/DEPLOY.md.
    notify_enabled: bool = False
    # The bot token lives in the ENVIRONMENT, never in the settings blob, and so
    # never in tasks.db. The schema header promises that reading that file does
    # not yield a working credential — it hashes OAuth secrets for exactly this
    # reason — and a bot token in `meta.app_settings` would be the one plaintext
    # credential in a file that goes into every backup. /etc/tasks/tasks.env is
    # already 0600 and already holds the Radicale password.
    telegram_bot_token: str = ""
    # Where notifications go. Not a secret (it is an integer naming a chat), but
    # it is deployment configuration rather than a preference, and pairing it
    # with the token keeps "who this bot talks to" in one file.
    telegram_chat_id: str = ""

    # Content-Security-Policy posture: "on" (enforce), "report-only" (log
    # violations in the browser console, block nothing) or "off". An escape
    # hatch rather than a knob: a policy that turns out to block something real
    # takes the app down to a blank page, and the fix should be a line in
    # /etc/tasks/tasks.env plus a restart, not a code change and a redeploy.
    # Anything unrecognised is treated as "on" — this is a security control, so
    # a typo must not quietly disable it (same posture as _bool above, which
    # refuses to fail open).
    csp_mode: str = "on"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            radicale_url=os.environ.get("RADICALE_URL", "http://127.0.0.1:5233").rstrip("/"),
            radicale_user=os.environ.get("RADICALE_USER", "testuser"),
            radicale_password=os.environ.get("RADICALE_PASSWORD", "testpass"),
            # The fallback is a DEV path, and deliberately still under ~: a
            # developer running `python -m tasksd` has no /var/lib/tasks and no
            # systemd to create one. Production sets TASKS_DB explicitly, to
            # /var/lib/tasks/tasks.db, because the unit grants that and nothing
            # under /home — see deploy/tasks.service.
            db_path=os.environ.get("TASKS_DB", os.path.expanduser("~/tasks/backend/tasks.db")),
            sync_interval_s=float(os.environ.get("TASKS_SYNC_INTERVAL", "30")),
            request_timeout_s=float(os.environ.get("TASKS_HTTP_TIMEOUT", "30")),
            static_dir=os.environ.get(
                "TASKS_STATIC", os.path.expanduser("~/tasks/frontend/dist")
            ),
            hook_secret=os.environ.get("TASKS_HOOK_SECRET", "dev-hook-secret"),
            auth_enabled=_bool("TASKS_AUTH_ENABLED", True),
            auth_user=os.environ.get("TASKS_AUTH_USER", "admin"),
            auth_password_hash=os.environ.get("TASKS_AUTH_PASSWORD_HASH", ""),
            auth_password=os.environ.get("TASKS_AUTH_PASSWORD", ""),
            session_secret=os.environ.get("TASKS_SESSION_SECRET", ""),
            session_ttl_s=int(os.environ.get("TASKS_SESSION_TTL", str(7 * 24 * 3600))),
            cookie_secure=_bool("TASKS_COOKIE_SECURE", True),
            access_required=_bool("TASKS_ACCESS_REQUIRED", False),
            access_team_domain=os.environ.get("TASKS_ACCESS_TEAM_DOMAIN", ""),
            access_aud=os.environ.get("TASKS_ACCESS_AUD", ""),
            dav_public_url=normalize_dav_url(os.environ.get("TASKS_DAV_URL", "/dav/")),
            mcp_enabled=_bool("TASKS_MCP_ENABLED", False),
            public_url=normalize_public_url(os.environ.get("TASKS_PUBLIC_URL", "")),
            max_body_bytes=int(
                os.environ.get("TASKS_MAX_BODY_BYTES", str(DEFAULT_MAX_BODY_BYTES))
            ),
            csp_mode=os.environ.get("TASKS_CSP", "on").strip().lower() or "on",
            notify_enabled=_bool("TASKS_NOTIFY_ENABLED", False),
            telegram_bot_token=os.environ.get("TASKS_TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.environ.get("TASKS_TELEGRAM_CHAT_ID", "").strip(),
        )
