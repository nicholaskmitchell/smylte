"""Cloudflare Access enforcement (spec §9).

The app does no user auth itself; it trusts that Cloudflare Access sits in front
and stamps every request with a signed `Cf-Access-Jwt-Assertion`. In production
this is REQUIRED — the app refuses to start if Access isn't configured, and every
API request without a valid JWT is rejected. On scratch/dev it's disabled.
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
