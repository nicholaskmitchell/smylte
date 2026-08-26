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
import math
import secrets
import time
from collections.abc import Callable
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

    def attempt(self, key: str) -> bool:
        """Reserve one attempt up front; False if the key is already locked out.

        Use this, not ``allowed()``, whenever the thing being rate-limited is
        awaited. ``allowed()`` is a pure read — it reserves nothing — so with the
        verification behind an ``await`` every request that arrives during it
        passes the gate, and the counter only moves once the first one comes
        back. The window is the whole password hash, which is deliberately slow,
        so the bypass is wide: 200 concurrent guesses were all evaluated against
        a limit of 5. Recording before the await closes it.

        A correct password still clears the reservation via ``record_success``,
        so an honest user is never penalised for their own successful logins.
        """
        now = time.monotonic()
        self._maybe_sweep(now)
        until = self._locked.get(key)
        if until is not None:
            if now < until:
                return False
            del self._locked[key]
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        recent.append(now)
        if len(recent) >= self.max_fails:
            self._locked[key] = now + self.lockout
            # The window is kept rather than dropped, so release() can hand a
            # reservation back and know what the count was before it. At most
            # max_fails floats per locked key, and _sweep still evicts the key
            # once the lockout ends and the failures age out.
            self._fails[key] = recent
        else:
            self._fails[key] = recent
        return True

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._maybe_sweep(now)
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        recent.append(now)
        if len(recent) >= self.max_fails:
            self._locked[key] = now + self.lockout
            # The window is kept rather than dropped, so release() can hand a
            # reservation back and know what the count was before it. At most
            # max_fails floats per locked key, and _sweep still evicts the key
            # once the lockout ends and the failures age out.
            self._fails[key] = recent
        else:
            self._fails[key] = recent

    def release(self, key: str) -> None:
        """Hand back ONE reservation taken by ``attempt``.

        For a counter whose budget is spent on an *outcome* rather than on a
        request, the reservation still has to be taken before the awaited work —
        otherwise every request that arrives while the first is in flight sees a
        counter that has not moved yet, and they all pass the gate together.
        This is what makes that shape usable: reserve up front, release when the
        outcome did not happen.

        ``record_success`` is not a substitute. It clears the key entirely, so
        using it to undo one reservation would hand back the whole budget — on
        the per-link booking ceiling, one refused request would reset the hour.
        """
        now = time.monotonic()
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        if recent:
            recent.pop()
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        # Only the reservation that tripped it can lift a lockout, and only by
        # putting the count back under the limit.
        if len(recent) < self.max_fails:
            self._locked.pop(key, None)

    def record_success(self, key: str) -> None:
        self._fails.pop(key, None)
        self._locked.pop(key, None)


class HashBudget:
    """A global token bucket in front of the password hash.

    `RateLimiter` bounds a CLIENT and was being read as bounding the guess
    budget. It is keyed on `limiter_key(_client_ip(...))`, i.e. per source /64 —
    the right unit for one customer and the wrong one for a budget, because a
    routed /48 is 65 536 of them, each with its own fresh counter. Nothing else
    stood in front of `check_credentials`: `login_hashes` bounds CONCURRENCY
    (memory), never rate, so the real ceiling on guesses was the box's CPU.
    Measured: 56.4 ms a hash, four in flight, ~71/s, ~6.1 M/day against a limit
    advertised as five per fifteen minutes. Sustaining it needs ~860 source /64s
    in rotation, and one free /48 supplies 65 536.

    A bucket rather than a counter with a lockout, deliberately. A global
    counter is itself a denial of service: an attacker who burns it locks the
    OWNER out of their own account for the lockout window, and there is no key to
    exempt them by. A bucket throttles instead — the owner may meet a 429 and
    retry a few seconds later, and never a fifteen-minute wall.

    A verified password gives its token BACK. That is what makes the budget a
    guess budget rather than a login budget: logging in correctly costs nothing,
    and only wrong answers spend it. One token back, not a reset —
    `RateLimiter.record_success` clears its counter outright, and `release`'s
    docstring already records what that cost when it was used to undo a single
    reservation. Handing back the whole budget here would let an attacker
    alternate a known-good password with guesses and never run out.

    Per app, never a module global: every test in the suite builds a fresh app
    and expects a fresh budget, and `make_app`'s docstring says so.
    """

    def __init__(self, capacity: int = 10, refill_s: float = 10.0):
        self.capacity = capacity
        self.refill_s = refill_s
        self._tokens = float(capacity)
        self._at = time.monotonic()

    def _fill(self, now: float) -> None:
        if now > self._at:
            self._tokens = min(self.capacity, self._tokens + (now - self._at) / self.refill_s)
            self._at = now

    def take(self) -> bool:
        """Spend one token. False when the budget is empty.

        Called BEFORE the hash, like `RateLimiter.attempt` and for the same
        reason: the hash is awaited, so a check that reserved nothing would let
        every request arriving during it through on one credit.
        """
        now = time.monotonic()
        self._fill(now)
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def give_back(self) -> None:
        """Return the token a correct password spent."""
        self._fill(time.monotonic())
        self._tokens = min(self.capacity, self._tokens + 1.0)

    def retry_after(self) -> int:
        """Whole seconds until one token is available, for the `Retry-After`."""
        self._fill(time.monotonic())
        if self._tokens >= 1.0:
            return 0
        return max(1, math.ceil((1.0 - self._tokens) * self.refill_s))


class Authenticator:
    def __init__(self, *, user: str, password_hash: str, secret: str,
                 ttl_s: int | Callable[[], int], credential_id: str | None = None):
        self._user = user
        self._password_hash = password_hash
        # What "the credentials changed" is judged against — see
        # credential_version. Not the hash itself: scrypt salts randomly, so
        # the dev plaintext path (TASKS_AUTH_PASSWORD, hashed at startup)
        # produces a different hash every restart and would sign everyone out
        # on each one. The caller passes the *configured* material instead,
        # which is stable across restarts and moves only when it is changed.
        self._credential_id = password_hash if credential_id is None else credential_id
        self._secret = secret
        # A callable rather than a number, because the session length is a
        # setting the user can change while signed in. Reading it at verify time
        # is what lets a *shortened* session take effect at once, on this device
        # and on any other: the JWT is stateless, so its own `exp` cannot be
        # moved once issued, but a token older than the current setting can be
        # refused. Lengthening still waits for the next login — nothing can
        # stretch a token past the `exp` already baked into it.
        self._ttl: Callable[[], int] = ttl_s if callable(ttl_s) else (lambda: ttl_s)
        self.limiter = RateLimiter()
        self._revoked: dict[str, float] = {}      # jti -> the token's own exp
        self._last_revoked_sweep = 0.0

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

    @property
    def ttl_s(self) -> int:
        """The session length in force right now."""
        return self._ttl()

    @property
    def credential_version(self) -> str:
        """A short fingerprint of the credentials a token was minted under.

        The signing secret is independent of the password, so before this the
        documented remedy for a compromise — regenerate the hash, update
        TASKS_AUTH_PASSWORD_HASH, restart — left every session the attacker had
        already minted valid for the rest of its TTL (7 days by default), and
        revocation could not reach them: logout withdraws a `jti` by name, and
        the owner never sees the jti of a session created on someone else's
        machine. Binding the token to the credentials makes changing the
        password a sign-out-everywhere, which is what an operator changing it
        under duress already believes it to be.

        Keyed with the signing secret rather than a bare digest: the credential
        material is a plaintext password on the dev path, and a truncated
        unkeyed hash of it would be offline-guessable by whoever holds the
        token. Anyone who knows the secret can already mint tokens, so keying it
        gives nothing away.

        Public because the MCP authorization server stamps the same value onto
        every OAuth token it issues and checks it on every request. That was the
        other half of "signing out everywhere": rotating the password ended every
        SESSION and left every MCP grant working, so docs/DEPLOY.md's documented
        incident response left a 30-day read/write backdoor open. One value
        covers both levers — it is keyed with the signing secret, so it moves
        when EITHER the password or TASKS_SESSION_SECRET does.
        """
        material = f"{self._user}\0{self._credential_id}".encode()
        return hmac.new(self._secret.encode(), material, hashlib.sha256).hexdigest()[:16]

    def issue_session(self) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": self._user,
                "iat": now,
                "exp": now + timedelta(seconds=self.ttl_s),
                # Names this session so logout can withdraw exactly it, and not
                # the ones on your other devices.
                "jti": secrets.token_hex(16),
                # Which credentials this was minted under; see credential_version.
                "cv": self.credential_version,
            },
            self._secret,
            algorithm="HS256",
        )

    def session_claims(self, token: str | None) -> dict | None:
        """The claims of a usable session cookie, else None — bad signature,
        expired, or withdrawn by an explicit logout."""
        if not token:
            return None
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
        except Exception:  # noqa: BLE001
            return None
        if self.is_revoked(claims.get("jti")):
            return None
        # Whose session this is, and under which credentials. `sub` was carried
        # but never checked, so a token signed with the same secret stayed valid
        # across a username change; `cv` does the same job for the password. A
        # token minted before this claim existed has no `cv` and is refused —
        # the conservative direction, and it costs one re-login at upgrade.
        if not hmac.compare_digest(str(claims.get("sub", "")).encode(), self._user.encode()):
            return None
        if not hmac.compare_digest(
            str(claims.get("cv", "")).encode(), self.credential_version.encode()
        ):
            return None
        # Shortening the session length has to bite immediately, including on
        # sessions opened elsewhere — which for a stateless token means judging
        # it against the current setting rather than only the `exp` it was
        # minted with. A token with no `iat` predates this and is left to `exp`.
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and time.time() - iat > self.ttl_s:
            return None
        return claims

    def verify_session(self, token: str | None) -> bool:
        return self.session_claims(token) is not None

    # ── revocation ────────────────────────────────────────────────────────────
    # A JWT is self-contained: clearing the cookie only asks the browser to
    # forget it, so a copy kept anywhere else stayed valid for the rest of the
    # TTL. Logout records the token id here instead, until its own exp makes the
    # point moot. Kept in memory so the check on every request stays a dict
    # lookup, and mirrored into SQLite so a restart cannot resurrect a session
    # the owner ended.

    def is_revoked(self, jti: str | None) -> bool:
        if not jti:
            return False        # pre-jti token: nothing to name, let exp retire it
        self._sweep_revoked()
        return jti in self._revoked

    def revoke(self, jti: str, expires_at: float) -> None:
        self._revoked[jti] = float(expires_at)

    def load_revocations(self, rows: dict[str, float]) -> None:
        self._revoked.update(rows)

    def _sweep_revoked(self) -> None:
        now = time.time()
        if now - self._last_revoked_sweep < 3600:
            return
        self._revoked = {j: e for j, e in self._revoked.items() if e > now}
        self._last_revoked_sweep = now
