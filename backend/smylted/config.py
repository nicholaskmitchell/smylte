"""Runtime configuration, read from the environment.

Dev defaults point at the **scratch** Radicale (127.0.0.1:5233), never
production. Production values are supplied via the systemd environment file at
deploy time (spec §9).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .limits import DEFAULT_MAX_BODY_BYTES


log = logging.getLogger("smylted.config")

_TRUE = frozenset({"1", "true", "yes", "y", "on"})
_FALSE = frozenset({"0", "false", "no", "n", "off"})

# Every setting below moved from TASKS_* to SMYLTE_* with the rename. The old
# spelling is still honoured, because the two halves of a deployment do not move
# at the same instant: autopull ships new code every minute, while the env file
# is rewritten by a human running deploy/migrate.sh. Without this fallback that
# window is not a graceful degradation — `auth_enabled` defaults ON, the hash
# reads empty, and the app REFUSES TO START. Downtime, from a rename.
#
# It is a transition, not a permanent alias: each stale name is named once at
# startup so the journal says exactly what to fix, and the fallback is deleted
# once deployments have migrated.
_NEW_PREFIX = "SMYLTE_"
_OLD_PREFIX = "TASKS_"

# Warn once per stale variable per process, not once per read.
_stale_warned: set[str] = set()


def _legacy(name: str) -> str | None:
    """The pre-rename spelling of a SMYLTE_* variable, or None if there isn't one.

    Guarded rather than a bare prefix swap: a caller passing an unprefixed name
    would otherwise have it mangled into a plausible-looking variable that is
    silently never found, which is the least debuggable outcome available.
    """
    if not name.startswith(_NEW_PREFIX):
        return None
    return _OLD_PREFIX + name[len(_NEW_PREFIX):]


def _raw(name: str) -> str | None:
    """The raw value for `name`, honouring the pre-rename TASKS_* spelling.

    Precedence is new-over-old and never merged: if both are set, the SMYLTE_*
    one wins outright. A half-rewritten env file is a real state to be in
    mid-migration, and quietly preferring the stale value would make the
    migration look applied when it was not.
    """
    v = os.environ.get(name)
    if v is not None:
        return v
    old = _legacy(name)
    if old is None:
        return None
    v = os.environ.get(old)
    if v is not None and old not in _stale_warned:
        _stale_warned.add(old)
        log.warning(
            "config: %s is the pre-rename name for %s and still works, but it is "
            "deprecated. Run deploy/migrate.sh to rewrite the environment file.",
            old, name,
        )
    return v


def _env(name: str, default: str) -> str:
    """A SMYLTE_* string setting, falling back to its TASKS_* predecessor."""
    v = _raw(name)
    return default if v is None else v


def _bool(name: str, default: bool) -> bool:
    """Parse a boolean env var, refusing anything it does not recognise.

    Every caller here gates a security control — auth_enabled, cookie_secure,
    access_required — and treating an unrecognised value as "not true" made all
    three fail OPEN. `SMYLTE_AUTH_ENABLED=Y`, `=enabled`, or a plain typo turned
    off the whole API auth gate on an internet-facing deployment, silently and
    with no way to tell from the outside but to try it.

    An unusable value is now a startup error, which matches how the app already
    treats missing Access configuration: refuse to come up rather than come up
    unprotected.
    """
    raw = _raw(name)
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
    auth_password_hash: str    # scrypt hash from `python -m smylted hash-password`
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
    # surface on its own. See smylted/mcp/.
    mcp_enabled: bool = False
    # This deployment's external origin, e.g. https://tasks.example.com. The
    # OAuth metadata documents have to state absolute URLs, and the `resource`
    # a token is bound to must match what the client was pointed at — so it is
    # configured rather than read off the Host header, which a caller controls.
    public_url: str = ""
    # Largest request body accepted, enforced ahead of the router — see
    # smylted/limits.py for why it cannot live in the routes themselves.
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    # ── outbound notifications ───────────────────────────────────────────────
    # An operator KILL SWITCH, not the feature's on/off. It defaults to
    # allowing, and nothing is sent regardless until the account turns
    # notifications on in Settings AND a bot token and chat id exist — so a
    # deploy still does not grow an outbound surface on its own, which is what
    # the MCP connector's opt-in was protecting against. Set it false to
    # guarantee a deployment can never message anyone, whatever the settings
    # blob says.
    #
    # Sending also needs egress: deploy/smylte.service is loopback-only
    # (`IPAddressDeny=any`), so the unit must be widened before a single
    # message can leave the box. See docs/DEPLOY.md.
    notify_enabled: bool = True
    # A FALLBACK for the account's own setting, for a deployment configured
    # entirely from /etc/smylte/smylte.env and never through the UI. Settings wins
    # when both are present.
    #
    # Worth knowing either way: a token set here stays out of smylte.db and so
    # out of every backup of it, which is what the schema header's promise about
    # reading that file is worth. One typed into Settings is stored in the clear
    # in `meta.app_settings`, like `booking_links.token` beside it — the app has
    # to be able to reproduce it to send, so it cannot be hashed. It is never
    # read back out over HTTP (see `_public_settings`).
    telegram_bot_token: str = ""
    # Where notifications go. Not a secret (it is an integer naming a chat), but
    # it is deployment configuration rather than a preference, and pairing it
    # with the token keeps "who this bot talks to" in one file.
    telegram_chat_id: str = ""
    # How often the notification scheduler wakes. Sixty seconds is the whole
    # resolution of the feature: an event alert can be up to this late, which is
    # why the lead time is floored well above it. Raise it on a small box —
    # `event_starting` re-expands every recurring resource on each pass.
    notify_interval_s: float = 60.0

    # Content-Security-Policy posture: "on" (enforce), "report-only" (log
    # violations in the browser console, block nothing) or "off". An escape
    # hatch rather than a knob: a policy that turns out to block something real
    # takes the app down to a blank page, and the fix should be a line in
    # /etc/smylte/smylte.env plus a restart, not a code change and a redeploy.
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
            # developer running `python -m smylted` has no /var/lib/smylte and no
            # systemd to create one. Production sets SMYLTE_DB explicitly, to
            # /var/lib/smylte/smylte.db, because the unit grants that and nothing
            # under /home — see deploy/smylte.service.
            db_path=_env("SMYLTE_DB", os.path.expanduser("~/smylte/backend/smylte.db")),
            sync_interval_s=float(_env("SMYLTE_SYNC_INTERVAL", "30")),
            request_timeout_s=float(_env("SMYLTE_HTTP_TIMEOUT", "30")),
            static_dir=_env(
                "SMYLTE_STATIC", os.path.expanduser("~/smylte/frontend/dist")
            ),
            hook_secret=_env("SMYLTE_HOOK_SECRET", "dev-hook-secret"),
            auth_enabled=_bool("SMYLTE_AUTH_ENABLED", True),
            auth_user=_env("SMYLTE_AUTH_USER", "admin"),
            auth_password_hash=_env("SMYLTE_AUTH_PASSWORD_HASH", ""),
            auth_password=_env("SMYLTE_AUTH_PASSWORD", ""),
            session_secret=_env("SMYLTE_SESSION_SECRET", ""),
            session_ttl_s=int(_env("SMYLTE_SESSION_TTL", str(7 * 24 * 3600))),
            cookie_secure=_bool("SMYLTE_COOKIE_SECURE", True),
            access_required=_bool("SMYLTE_ACCESS_REQUIRED", False),
            access_team_domain=_env("SMYLTE_ACCESS_TEAM_DOMAIN", ""),
            access_aud=_env("SMYLTE_ACCESS_AUD", ""),
            dav_public_url=normalize_dav_url(_env("SMYLTE_DAV_URL", "/dav/")),
            mcp_enabled=_bool("SMYLTE_MCP_ENABLED", False),
            public_url=normalize_public_url(_env("SMYLTE_PUBLIC_URL", "")),
            max_body_bytes=int(
                _env("SMYLTE_MAX_BODY_BYTES", str(DEFAULT_MAX_BODY_BYTES))
            ),
            csp_mode=_env("SMYLTE_CSP", "on").strip().lower() or "on",
            notify_enabled=_bool("SMYLTE_NOTIFY_ENABLED", True),
            telegram_bot_token=_env("SMYLTE_TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=_env("SMYLTE_TELEGRAM_CHAT_ID", "").strip(),
            notify_interval_s=float(_env("SMYLTE_NOTIFY_INTERVAL", "60")),
        )
