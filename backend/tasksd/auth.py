"""Username/password authentication for public exposure.

The app is reachable from anywhere over the Cloudflare Tunnel (HTTPS at the edge),
so it defends itself:

  * passwords are stored only as a **scrypt** hash (stdlib, memory-hard) and
    verified in constant time;
  * a successful login mints a short-lived **HS256 JWT** carried in an
    HttpOnly + Secure + SameSite=Strict cookie (XSS can't read it; CSRF can't
    replay it cross-site);
  * login attempts are **rate-limited with lockout** per client IP;
  * the slow hash + rate limit make online brute force impractical.

No secrets are logged or written to SQLite. The session secret and password hash
come from the environment (systemd EnvironmentFile, mode 0600).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt

# scrypt work factors. 128*N*r*p ≈ 16 MiB of memory per hash — costly to attack,
# fine for the handful of logins a single user performs.
_N, _R, _P = 2**14, 8, 1
_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            maxmem=_MAXMEM,
            dklen=len(hash_hex) // 2,
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001 — any parse/format error is a failed verify
        return False


class RateLimiter:
    """Per-key sliding-window failure counter with a fixed lockout."""

    def __init__(self, max_fails: int = 5, window_s: int = 900, lockout_s: int = 900):
        self.max_fails = max_fails
        self.window = window_s
        self.lockout = lockout_s
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}

    def allowed(self, key: str) -> bool:
        until = self._locked.get(key)
        return not (until and time.monotonic() < until)

    def retry_after(self, key: str) -> int:
        until = self._locked.get(key)
        return max(0, int(until - time.monotonic())) if until else 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        recent.append(now)
        self._fails[key] = recent
        if len(recent) >= self.max_fails:
            self._locked[key] = now + self.lockout
            self._fails[key] = []

    def record_success(self, key: str) -> None:
        self._fails.pop(key, None)
        self._locked.pop(key, None)


class Authenticator:
    def __init__(self, *, user: str, password_hash: str, secret: str, ttl_s: int):
        self._user = user
        self._password_hash = password_hash
        self._secret = secret
        self._ttl = ttl_s
        self.limiter = RateLimiter()

    @property
    def user(self) -> str:
        return self._user

    def check_credentials(self, user: str, password: str) -> bool:
        # Always run the hash (even on a wrong username) to avoid a timing oracle.
        user_ok = hmac.compare_digest(user or "", self._user)
        pass_ok = verify_password(password or "", self._password_hash)
        return user_ok and pass_ok

    def issue_session(self) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {"sub": self._user, "iat": now, "exp": now + timedelta(seconds=self._ttl)},
            self._secret,
            algorithm="HS256",
        )

    def verify_session(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            jwt.decode(token, self._secret, algorithms=["HS256"])
            return True
        except Exception:  # noqa: BLE001
            return False
