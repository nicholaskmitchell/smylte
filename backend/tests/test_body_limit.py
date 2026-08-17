"""The request-body bound (tasksd/limits.py).

The defect this pins: every guard the anonymous routes have — the login
limiter, the hash semaphore, the public booking throttles — lives inside the
endpoint function, and FastAPI buffers the whole pydantic body before the
endpoint is entered. So an anonymous caller could stream an arbitrary number of
megabytes into memory and the rate limiter, the intended defence, never ran.

Two properties matter and both are asserted below: the answer is 413, and the
bytes stop being read. A test that only checked the status would pass against a
middleware that buffered everything first and then complained.
"""
from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.limits import BodySizeLimitMiddleware
from tests.conftest import api_settings

CAP = 4096


async def _echo_len(scope, receive, send):
    """Reads the whole body, the way FastAPI's body-model resolution does."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    payload = str(len(body)).encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain"),
                            (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})


def _client() -> httpx.AsyncClient:
    app = BodySizeLimitMiddleware(_echo_len, max_bytes=CAP)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://limits.test"
    )


def _post(**kwargs) -> httpx.Response:
    async def go():
        async with _client() as c:
            return await c.post("/", **kwargs)

    return asyncio.run(go())


def test_a_body_under_the_cap_is_passed_through():
    r = _post(content=b"x" * (CAP - 1))
    assert r.status_code == 200
    assert r.text == str(CAP - 1)


def test_a_declared_oversized_body_is_refused_unread():
    """Content-Length is the cheap case: refuse before a byte is accepted."""
    r = _post(content=b"x" * (CAP + 1))
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]


def test_a_chunked_body_is_cut_at_the_cap_not_buffered_whole():
    """The slowloris shape: no Content-Length, so the only defence is counting
    the bytes off receive() and stopping. Before the fix the whole stream was
    buffered and RSS tracked it ~1:1."""
    produced = 0

    async def chunks():
        nonlocal produced
        for _ in range(1000):          # 1000 × 64 KiB = 64 MiB if never cut
            produced += 65536
            yield b"x" * 65536

    r = _post(content=chunks())

    assert r.status_code == 413
    # Cut within a chunk of the cap, not after reading all 64 MiB.
    assert produced <= CAP + 65536, produced


@pytest.mark.radicale
def test_a_huge_login_body_is_refused_before_the_route_runs():
    """/api/login is the reachable instance: unauthenticated, and its limiter
    sits behind the body parse. 413, not 422 — the route was never entered."""
    settings = dataclasses.replace(api_settings(":memory:"), max_body_bytes=CAP)
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/login", json={"username": "admin", "password": "x" * (CAP * 4)})
    assert r.status_code == 413


@pytest.mark.radicale
def test_an_ordinary_login_still_works_under_the_cap():
    settings = dataclasses.replace(api_settings(":memory:"), max_body_bytes=CAP)
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/login", json={"username": "admin", "password": "testpass123"})
    assert r.status_code == 200


def test_the_edge_carries_the_same_cap():
    """deploy/Caddyfile.snippet is the first line of this defence — the app-side
    middleware is the backstop for a direct connection to uvicorn. If the edge
    directive is dropped, the bytes reach the box again."""
    from pathlib import Path

    snippet = (
        Path(__file__).resolve().parents[2] / "deploy" / "Caddyfile.snippet"
    ).read_text()
    assert "request_body" in snippet
    assert "max_size 1MB" in snippet
