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
import ipaddress
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


def limiter_key(ip: str) -> str:
    """Normalise a client IP into a rate-limit key. IPv4 keys as-is; IPv6
    collapses to its /64 — the standard single-customer allocation — so an
    attacker rotating through their own 2^64 addresses shares one counter
    instead of getting a fresh limiter per request. An unparseable value
    (e.g. the 'unknown' placeholder) keys on itself."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None:      # ::ffff:a.b.c.d is really that IPv4 client
            return str(mapped)
        return str(ipaddress.ip_network((addr, 64), strict=False))
    return ip


class RateLimiter:
    """Per-key sliding-window failure counter with a fixed lockout.

    Keys are caller-supplied (a per-client-IP key), so the maps must stay
    bounded: an attacker rotating source IPs — or simply a large IPv6 range, or
    steady public traffic that never "succeeds" — would otherwise accumulate a
    permanent entry per key and exhaust memory. A periodic sweep drops keys with
    no live failures and no active lockout, so the maps are bounded by the
    *recently active* client set, not the total ever seen.
    """

    def __init__(self, max_fails: int = 5, window_s: int = 900, lockout_s: int = 900):
        self.max_fails = max_fails
        self.window = window_s
        self.lockout = lockout_s
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}
        self._last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Evict expired lockouts and keys whose failures have all aged out."""
        for key, until in list(self._locked.items()):
            if until <= now:
                del self._locked[key]
        horizon = now - self.window
        for key, times in list(self._fails.items()):
            recent = [t for t in times if t > horizon]
            if recent:
                self._fails[key] = recent
            elif key not in self._locked:
                del self._fails[key]
        self._last_sweep = now

    def _maybe_sweep(self, now: float) -> None:
        # Amortised: at most one O(n) pass per window, so the maps can't grow
        # past the active-client set no matter how many distinct keys arrive.
        if now - self._last_sweep >= self.window:
            self._sweep(now)

    def allowed(self, key: str) -> bool:
        now = time.monotonic()
        self._maybe_sweep(now)
        until = self._locked.get(key)
        if until is not None and until <= now:
            del self._locked[key]
            return True
        return not (until and now < until)

    def retry_after(self, key: str) -> int:
        until = self._locked.get(key)
        return max(0, int(until - time.monotonic())) if until else 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._maybe_sweep(now)
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        recent.append(now)
        if len(recent) >= self.max_fails:
            self._locked[key] = now + self.lockout
            self._fails.pop(key, None)      # tracked by _locked now; drop the list
        else:
            self._fails[key] = recent

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
        # Compare bytes: compare_digest raises TypeError on non-ASCII str, which
        # would turn a stray Unicode username into a 500 (skipping lockout
        # accounting) instead of a clean 401.
        user_ok = hmac.compare_digest((user or "").encode(), self._user.encode())
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
