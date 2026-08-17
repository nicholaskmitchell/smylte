"""Content-Security-Policy: the bound over everything a page can fetch.

The app already validates the specific fields that reach the CSSOM — a
collection's `calendar-color` is checked at ingest (`dav/xml.py clean_color`)
and again on the client (`util.ts cssColor`), because a hostile one made a 3-5px
dot fetch `url(https://evil.example/x.png)` on every render. The appearance
tokens have their own allowlist for the same reason.

Those are allowlists over *named fields*. This is the bound over the rest: the
next value that reaches a style declaration, an `img` src or a script tag is
otherwise undefended in exactly the same way. It matters beyond the authed app —
`/book/<token>` is served to visitors who are not the account holder.

The policy is deliberately written down in ONE place. A second
`Content-Security-Policy` header on the same response is not "belt and braces":
browsers enforce the INTERSECTION of every policy present, so two sources that
drift produce a policy neither of them describes. `deploy/Caddyfile.snippet`
carries a comment saying so, and sets no header of its own.
"""
from __future__ import annotations

import base64
import hashlib
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A `<script>` that is not a `src=` reference, i.e. one with a body to hash.
# Deliberately not an HTML parser: this reads the one file we ship ourselves,
# and a regex that is too eager errs toward hashing something harmless while one
# that is too lax simply fails to whitelist our own script — which is loud (the
# app does not paint) rather than silent.
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.S | re.I)

# Where the Appearance font picker gets the families it does not bundle.
# `appearance.ts ensureFont` injects a stylesheet from the first at runtime, and
# that stylesheet pulls woff2 from the second. Allowed so the picker keeps
# working; the shipped defaults (Fraunces/Inter/JetBrains Mono) are local and
# need neither. Self-hosting the rest would let both of these go.
_FONT_CSS = "https://fonts.googleapis.com"
_FONT_FILES = "https://fonts.gstatic.com"

MODES = ("on", "report-only", "off")


def inline_script_hashes(html: str) -> list[str]:
    """`'sha256-…'` source expressions for every inline script in `html`.

    The hash covers the element's exact text content, so it has to be taken from
    the file actually SERVED, not from a copy. See `policy_for_index`.
    """
    return [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in _INLINE_SCRIPT.findall(html)
    ]


def build_policy(script_hashes: list[str]) -> str:
    """The policy, as one string.

    Two directives here are load-bearing in a way that is easy to undo by
    accident, so they are also asserted in tests/test_csp.py:

    * `script-src` must never gain `'unsafe-inline'`. It would be ignored while
      a hash is present (CSP3), and honoured the moment the hash goes away —
      i.e. it silently converts this from a real policy to a decorative one.
    * `style-src` must never gain a hash or a nonce. Either one makes browsers
      IGNORE `'unsafe-inline'`, and this SPA cannot live without it: every
      calendar and list color is an inline style, and the MCP consent screen is
      a `<style>` block. Adding a style hash blanks the app.
    """
    return "; ".join([
        "default-src 'self'",
        # Nothing here embeds, is embedded, or rewrites its own base URL.
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        # The MCP consent screen posts to /oauth/authorize; it then REDIRECTS to
        # the client's callback, which form-action does not govern.
        "form-action 'self'",
        # No data:/blob: — nothing in the app builds one (checked). The theme
        # export makes a blob URL for `<a download>`, which is a download rather
        # than a fetch and is governed by no directive.
        "img-src 'self'",
        # fetch() and EventSource('/api/events'), both same-origin.
        "connect-src 'self'",
        " ".join(["script-src 'self'", *script_hashes]),
        f"style-src 'self' 'unsafe-inline' {_FONT_CSS}",
        f"font-src 'self' {_FONT_FILES}",
    ])


def policy_for_index(index_html: str | None) -> str:
    """The policy for a deployment serving `index_html` (None if not built).

    The script hash is DERIVED from the served file rather than written down.
    Hardcoding it would put the same string in two places that must agree, and
    the failure mode when they stop agreeing is a blank page at the next deploy
    — the app's own pre-paint script blocked. It also could not be tested: CI
    runs `npm test` before `npm run build`, so no test ever sees the built HTML.

    The read happens once, at startup, which is the one operational cost: a
    frontend rebuild needs a service restart for the hash to follow it. That is
    called out in docs/DEPLOY.md.
    """
    return build_policy(inline_script_hashes(index_html) if index_html else [])


class CSPMiddleware:
    """Attach the policy to every response.

    Every response, not just HTML: it costs one header on a JSON body and means
    there is no route — present or future — that quietly escapes the policy.
    """

    def __init__(self, app: ASGIApp, policy: str = "", *, report_only: bool = False) -> None:
        self.app = app
        self.policy = policy
        self.header = (
            b"content-security-policy-report-only" if report_only
            else b"content-security-policy"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.policy:
            await self.app(scope, receive, send)
            return

        value = self.policy.encode()

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                # Never append a second one: two policies on a response are
                # enforced as their intersection, and a duplicate would be
                # indistinguishable from a deliberate tightening.
                if not any(k.lower() == self.header for k, _ in headers):
                    headers.append((self.header, value))
            await send(message)

        await self.app(scope, receive, send_with_policy)
