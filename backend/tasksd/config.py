"""Runtime configuration, read from the environment.

Dev defaults point at the **scratch** Radicale (127.0.0.1:5233), never
production. Production values are supplied via the systemd environment file at
deploy time (spec §9).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            radicale_url=os.environ.get("RADICALE_URL", "http://127.0.0.1:5233").rstrip("/"),
            radicale_user=os.environ.get("RADICALE_USER", "testuser"),
            radicale_password=os.environ.get("RADICALE_PASSWORD", "testpass"),
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
        )
