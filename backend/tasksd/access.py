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

import jwt
from fastapi import HTTPException, status

from .config import Settings


class AccessVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwks: jwt.PyJWKClient | None = None
        if settings.access_required:
            self._jwks = jwt.PyJWKClient(
                f"https://{settings.access_team_domain}/cdn-cgi/access/certs"
            )

    def verify(self, token: str | None) -> None:
        if not self.settings.access_required:
            return
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Cf-Access-Jwt-Assertion")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key  # type: ignore[union-attr]
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
