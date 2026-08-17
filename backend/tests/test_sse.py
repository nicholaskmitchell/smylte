"""GET /api/events — the SSE stream.

This endpoint had no backend test at all, which is how both defects here
survived. It is the only long-lived route in the app and the only one holding
unbounded per-connection state: `svc.subscribe()` adds an unbounded Queue to
`TaskService._listeners`, `_publish` fans every mutation into all of them, and
the only thing that removes one is the `finally` inside the generator.

Two properties are pinned:

  * the listener is registered on connect and drained on disconnect — a leak
    here is unbounded memory growth plus a fan-out that never stops;
  * the stream dies when its session is revoked. `require_auth` runs once, at
    connect time, so before the fix POST /api/logout — the only thing that makes
    a stolen cookie stop working — never reached a stream already open, and a
    revoked session kept receiving every task and event mutation indefinitely.
"""
from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tests.conftest import api_settings

pytestmark = pytest.mark.radicale

LOGIN = {"username": "admin", "password": "testpass123"}


@pytest.fixture
def make_app(_scratch_up, tmp_path):
    counter = 0

    def _make(**overrides):
        nonlocal counter
        counter += 1
        return create_app(
            dataclasses.replace(api_settings(str(tmp_path / f"sse{counter}.db")), **overrides)
        )

    return _make


def _drive_stream(app, cookie: str, messages: list[dict]) -> list[bytes]:
    """Run one /api/events request straight against the ASGI app.

    TestClient's transport does not reproduce an abrupt client disconnect, and
    that disconnect is precisely what the cleanup depends on — so the receive
    channel is scripted here instead.
    """
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/api/events", "raw_path": b"/api/events", "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
        "headers": [
            (b"host", b"testserver"),
            (b"cookie", f"tasks_session={cookie}".encode()),
        ],
    }
    pending = list(messages)
    chunks: list[bytes] = []

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    async def go():
        await asyncio.wait_for(app(scope, receive, send), timeout=10)

    asyncio.run(go())
    return chunks


def test_the_stream_opens_with_a_retry_hint_and_a_hello():
    """The SPA's EventSource reconnects on `retry:`, and `hello` is how the
    client knows the stream is live rather than merely accepted."""
    app = create_app(api_settings(":memory:"))
    with TestClient(app) as c:
        assert c.post("/api/login", json=LOGIN).status_code == 200
        cookie = c.cookies["tasks_session"]
        chunks = _drive_stream(app, cookie, [{"type": "http.disconnect"}])

    body = b"".join(chunks).decode()
    assert body.startswith("retry: 3000\n\n")
    assert 'data: {"type": "hello"}' in body


def test_an_abrupt_disconnect_drains_the_listener():
    """The regression guard. Whether the generator's `finally` runs on a client
    that vanishes is Starlette-version-specific behaviour the code cannot see,
    and a leak here grows without bound while `_publish` keeps fanning into it."""
    app = create_app(api_settings(":memory:"))
    with TestClient(app) as c:
        assert c.post("/api/login", json=LOGIN).status_code == 200
        cookie = c.cookies["tasks_session"]
        svc = app.state.service
        assert len(svc._listeners) == 0

        _drive_stream(app, cookie, [{"type": "http.disconnect"}])

        assert len(svc._listeners) == 0


def test_a_queued_event_is_delivered_to_an_open_stream():
    app = create_app(api_settings(":memory:"))
    with TestClient(app) as c:
        assert c.post("/api/login", json=LOGIN).status_code == 200
        cookie = c.cookies["tasks_session"]
        svc = app.state.service

        # subscribe() hands each connection its own Queue, so the publish has to
        # happen after the stream is up — and on the loop driving it. The stream
        # is then let go by disconnecting once the event has landed.
        async def go():
            chunks: list[bytes] = []
            delivered = asyncio.Event()

            async def receive():
                await delivered.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    chunks.append(body)
                    if b"task_created" in body:
                        delivered.set()

            scope = {
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1", "method": "GET", "scheme": "http",
                "path": "/api/events", "raw_path": b"/api/events", "query_string": b"",
                "root_path": "", "client": ("127.0.0.1", 1), "server": ("testserver", 80),
                "headers": [(b"host", b"testserver"),
                            (b"cookie", f"tasks_session={cookie}".encode())],
            }
            task = asyncio.ensure_future(app(scope, receive, send))
            while not svc._listeners:               # wait for the subscribe
                await asyncio.sleep(0.01)
            svc._loop = asyncio.get_running_loop()
            svc._publish({"type": "task_created", "list": "l", "uid": "u"})
            await asyncio.wait_for(task, timeout=10)
            return b"".join(chunks).decode()

        body = asyncio.run(asyncio.wait_for(go(), timeout=15))

    assert '"type": "task_created"' in body


def test_logging_out_closes_a_stream_that_is_already_open():
    """Logout revokes the session's jti. Every ordinary request from that cookie
    401s afterwards — but a stream opened before the logout kept delivering,
    which is the whole point of revoking.

    The client here never disconnects, so the only thing that can end this
    stream is the revocation check. A mutation is published after the logout:
    before the fix it was delivered to the revoked stream, which is the defect
    stated exactly."""
    app = create_app(api_settings(":memory:"))
    with TestClient(app) as c:
        assert c.post("/api/login", json=LOGIN).status_code == 200
        cookie = c.cookies["tasks_session"]
        svc = app.state.service

        async def go():
            chunks: list[bytes] = []

            async def receive():
                await asyncio.Event().wait()        # a client that never leaves

            async def send(message):
                if message["type"] == "http.response.body":
                    chunks.append(message.get("body", b""))

            scope = {
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1", "method": "GET", "scheme": "http",
                "path": "/api/events", "raw_path": b"/api/events", "query_string": b"",
                "root_path": "", "client": ("127.0.0.1", 1), "server": ("testserver", 80),
                "headers": [(b"host", b"testserver"),
                            (b"cookie", f"tasks_session={cookie}".encode())],
            }
            # Stream first, logout second — that ordering is the whole finding.
            task = asyncio.ensure_future(app(scope, receive, send))
            while not svc._listeners:
                await asyncio.sleep(0.01)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                cookies={"tasks_session": cookie},
            ) as ac:
                assert (await ac.post("/api/logout")).status_code == 200
                assert (await ac.get("/api/me")).status_code == 401

            # The mutation a revoked stream must not see.
            svc._loop = asyncio.get_running_loop()
            svc._publish({"type": "task_created", "list": "l", "uid": "u"})

            await task
            return b"".join(chunks).decode()

        # Returns instead of hanging: the revocation reached the open stream.
        body = asyncio.run(asyncio.wait_for(go(), timeout=10))
        assert len(svc._listeners) == 0

    assert "hello" in body            # it was a live, authorised stream…
    assert "task_created" not in body  # …that stopped delivering once revoked
