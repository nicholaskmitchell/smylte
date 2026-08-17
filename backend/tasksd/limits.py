"""Request-body bound, applied before anything buffers the body.

This exists because every guard the anonymous routes have runs too late. FastAPI
resolves a pydantic body parameter — which awaits `request.json()` and therefore
reads the WHOLE body into memory — before the endpoint function is entered, and
`login`'s rate limiter, its hash semaphore and the public booking throttles all
live inside those function bodies. `Login.username`/`Login.password` carry
`max_length` bounds for exactly this reason, but pydantic only sees the string
once the body is already resident. So an anonymous caller could stream an
arbitrarily large body and pin that memory for as long as it kept the connection
open, with the rate limiter structurally unable to fire.

The bound therefore has to sit outside the router. `Content-Length` is refused up
front, which costs nothing; a chunked body declares no length, so bytes are
counted off `receive()` and the request is cut the moment it goes over.

`deploy/Caddyfile.snippet` carries the same cap at the edge. This one is the
in-process backstop: it holds for a direct connection to uvicorn, and it is what
the test suite can actually exercise.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 1 MiB. The largest thing any route legitimately accepts is the settings blob
# (appearance tokens, tab order, task groups), which is kilobytes.
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


class _BodyTooLarge(Exception):
    """Raised out of the wrapped receive() once the cap is passed."""


class BodySizeLimitMiddleware:
    """Answer 413 rather than buffering a body over `max_bytes`."""

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _too_large(send, self.max_bytes)
            return

        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    # Cut the stream here: returning the chunk would hand the
                    # oversized bytes to whatever is buffering them.
                    raise _BodyTooLarge
            return message

        async def watching_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, watching_send)
        except _BodyTooLarge:
            # A streaming route may already have committed a status; there is
            # nothing to say at that point, so let the connection close.
            if not started:
                await _too_large(send, self.max_bytes)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _too_large(send: Send, max_bytes: int) -> None:
    body = f'{{"detail":"request body exceeds {max_bytes} bytes"}}'.encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            # The body was refused unread, so the connection cannot be reused.
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": body})
