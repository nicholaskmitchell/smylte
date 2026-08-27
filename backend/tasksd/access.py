"""Cloudflare Access enforcement (spec §9) — an OPTIONAL second layer.

The app's own username/password login (`tasksd/auth.py`) is the primary gate and
the one production actually runs on: `TASKS_AUTH_ENABLED` defaults to true, and
`create_app` refuses to start with auth enabled and no password configured.

This module adds a layer in front of that, off by default
(`TASKS_ACCESS_REQUIRED`, `config.py`). When it IS on, every `/api` request must
also carry a valid, signed `Cf-Access-Jwt-Assertion`, and turning it on without
`TASKS_ACCESS_TEAM_DOMAIN` / `TASKS_ACCESS_AUD` is a startup error rather than a
silent downgrade. With it off, `verify()` returns immediately and the session
cookie is the whole check.

This docstring used to describe the original design — "the app does no user auth
itself", Access "REQUIRED" in production, and the app refusing to start without
it — which has been the inverse of the truth since the password gate landed. It
is corrected here rather than deleted because a security module whose own
docstring claims an edge gate is mandatory invites a maintainer to treat the
password login as redundant. Note that `deploy/tasks.service` would actively
break under the old description: it sets `IPAddressDeny=any`, and the comment
there says those lines must be removed before Access can be enabled at all,
since the JWKS fetch needs outbound HTTPS.
"""
from __future__ import annotations

import asyncio
import time

import jwt
from fastapi import HTTPException, status

from .config import Settings

# How long the cached key set is used without asking again, and the shortest
# interval between two fetches however badly one is wanted. See `_key_set` for
# why the bound has to be on the FETCH rather than on the `kid`.
_KEYSET_TTL_S = 300.0
_REFRESH_COOLDOWN_S = 60.0


class AccessVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks: jwt.PyJWKClient | None = None
        # The key set and when it was last ASKED for — stamped on every attempt,
        # success or failure. PER INSTANCE, deliberately: a module-level clock
        # would let one verifier's refusal decide another's, and the
        # fail-closed-during-an-outage test builds a second verifier precisely to
        # check that it makes its own answer.
        self._keys: list | None = None
        self._fetched_at: float | None = None
        if settings.access_required:
            self._jwks = jwt.PyJWKClient(
                f"https://{settings.access_team_domain}/cdn-cgi/access/certs"
            )

    async def verify(self, token: str | None) -> None:
        """Refuse unless `token` is a valid Access assertion for this deployment.

        AWAITABLE, and the JWKS work runs in a thread. PyJWT's client is
        `urllib.request.urlopen` with a 30 s default timeout, and this is called
        from `require_auth`, which is `async def` — so a slow or black-holed
        `cdn-cgi/access/certs` stalled every other request on the process,
        `/healthz` and the SSE keepalives included. Measured before this change:
        a 1.5 s fetch produced a 1.55 s gap between ticks of a 50 ms ticker. It is
        the same total-outage shape `_href` was fixed for on the service lock,
        one layer earlier — before any session exists.
        """
        if not self.settings.access_required:
            return
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Cf-Access-Jwt-Assertion")
        await asyncio.to_thread(self._verify_blocking, token)

    def _verify_blocking(self, token: str) -> None:
        """The verification itself. Runs in a worker thread; never on the loop."""
        try:
            key = self._signing_key(token)
            jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.settings.access_aud,
                issuer=f"https://{self.settings.access_team_domain}",
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"invalid Access token: {e}") from e

    def _key_set(self, *, force: bool) -> list:
        """The signing keys, fetching at most once per `_REFRESH_COOLDOWN_S`.

        This is the bound, and it is on the FETCH rather than on the `kid` — the
        subtlety the first attempt at this fix got wrong. `kid` is a header field
        the caller writes, so an attacker rotates it: remembering which kids were
        refused is free to defeat by never repeating one, and a per-kid cache
        bought exactly nothing (measured: still one fetch per request over ten
        distinct kids). What has to be bounded is how often a miss may go and ask.

        PyJWT bounds it nowhere. `get_signing_key` answers an unrecognised kid
        with `get_signing_keys(refresh=True)`, which deliberately bypasses the
        300 s `lifespan` cache; its other knob, `cache_keys`, is an `lru_cache`
        over the RETURN value and never memoizes the exception a miss raises. So
        every request carrying a `kid` the set does not hold bought one outbound
        HTTPS round trip, unauthenticated, ahead of every limit the app has —
        measured at five fetches for five requests, eleven for ten.

        The clock is stamped on every ATTEMPT, not on every success. An
        unreachable endpoint would otherwise be its own amplifier: no key set is
        ever cached, so every request would try again. The cost is that for up to
        a minute after an outage clears, a legitimate token is still refused —
        which fails CLOSED, on a layer whose fallback is the session cookie.
        """
        now = time.monotonic()
        fresh = self._keys is not None and now - (self._fetched_at or 0.0) < _KEYSET_TTL_S
        if fresh and not force:
            return self._keys                       # type: ignore[return-value]
        if self._fetched_at is not None and now - self._fetched_at < _REFRESH_COOLDOWN_S:
            if self._keys is not None:
                return self._keys                   # stale, but not stale enough to pay for
            raise jwt.PyJWKClientError(
                "no Access signing keys are cached and the JWKS refresh cooldown "
                "has not elapsed")
        self._fetched_at = now
        self._keys = self._jwks.get_signing_keys(refresh=True)   # type: ignore[union-attr]
        return self._keys

    def _signing_key(self, token: str):
        """The signing key for `token`, without letting a stranger's `kid` buy a
        network round trip.

        PyJWT's own two-tier lookup — cached set, then one refresh on a miss —
        reimplemented over its own primitives so that nothing about HOW the set
        is fetched changes (`fetch_data` is still the only thing that touches the
        network), and so that both tiers answer to `_key_set`'s cooldown.

        A key that ROTATES legitimately still resolves within the cooldown, and
        Cloudflare publishes new keys well ahead of signing with them.
        """
        kid = self._kid_of(token)
        if kid is None:
            # No refresh can produce a match for a token that names no key, so
            # refusing here saves the fetch rather than spending it to learn
            # what is already known.
            raise jwt.PyJWKClientError("the Access token names no signing key")
        keys = self._key_set(force=False)
        found = self._jwks.match_kid(keys, kid)      # type: ignore[union-attr]
        if found is None:
            keys = self._key_set(force=True)         # cooled down inside
            found = self._jwks.match_kid(keys, kid)  # type: ignore[union-attr]
            if found is None:
                raise jwt.PyJWKClientError(
                    f'Unable to find a signing key that matches: "{kid}"')
        return found.key

    @staticmethod
    def _kid_of(token: str) -> str | None:
        """The token's `kid` header, or None if it has none we can read.

        Unverified by construction — it is the lookup key for the very signature
        check that has not happened yet — so it is used ONLY to find a candidate
        key, never to decide anything. A token with no readable header (or none
        at all) matches nothing and is refused by the same path as a token whose
        kid is simply unknown.
        """
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except Exception:  # noqa: BLE001 — an unreadable header is not our verdict to give
            return None
        return kid if isinstance(kid, str) else None
