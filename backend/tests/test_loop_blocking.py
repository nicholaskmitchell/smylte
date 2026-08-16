"""The event loop must survive a service call that is stuck on the global lock.

`TaskService._lock` is one process-wide RLock held across CalDAV I/O — a sync
sweep, a write, a PROPPATCH — for as long as the 30 s DAV timeout allows. Every
route dispatches its service work to a worker thread through `_run`, so a slow
Radicale costs the caller and nothing else.

`_href` was the exception: it called `resolve_list` synchronously from inside an
`async def`, so it waited for that lock ON THE EVENT LOOP. One list request
during a stuck sync therefore froze the whole process — `/healthz` (which
touches nothing), `/api/login`, the SSE keepalives and the static SPA with it,
turning a Radicale outage into a total outage and blinding the health check an
operator would use to tell the two apart.

No Radicale here: the app is built but its lifespan is never entered, and a stub
service stands in so the lock is the only thing under test.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time

import httpx
import pytest

from tasksd import app as tasksd_app

from tasksd.app import create_app
from tests.conftest import api_settings

LOGIN = {"username": "admin", "password": "testpass123"}
HOLD_S = 3.0          # a Radicale call holding the lock; the real timeout is 30 s
TOLERANCE_S = 1.0     # generous: the failing shape stalls for the WHOLE hold


class _StubService:
    """Only what these routes touch, over the real lock discipline."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def resolve_list(self, list_id: str) -> str | None:
        with self._lock:
            return f"/u/{list_id}/"

    def list_tasks(self, href: str, **kw):
        with self._lock:
            return []


@pytest.fixture
def app(tmp_path):
    app = create_app(api_settings(str(tmp_path / "loop.db")))
    app.state.service = _StubService()      # lifespan never runs, so wire it here
    return app


def _hold_lock(svc: _StubService, seconds: float) -> threading.Event:
    """Take the global lock from a worker thread, as a CalDAV call does."""
    held = threading.Event()

    def hog() -> None:
        with svc._lock:
            held.set()
            time.sleep(seconds)

    threading.Thread(target=hog, daemon=True).start()
    held.wait()
    return held


def test_no_route_reaches_the_service_off_the_worker_thread():
    """The invariant, pinned at the source: every service call in a route goes
    through `_run` (`asyncio.to_thread`). Deterministic, and it fails the moment
    someone re-adds a synchronous one — including on a route this suite has no
    other reason to exercise."""
    import pathlib

    src = pathlib.Path(tasksd_app.__file__).read_text(encoding="utf-8")

    unawaited = [
        (n, line.strip())
        for n, line in enumerate(src.splitlines(), 1)
        if "_href(request," in line and "await _href(request," not in line
    ]
    assert not unawaited, f"_href called without await (blocks the event loop): {unawaited}"

    # `_svc(request).<call>` and `svc.<call>` are the two spellings used to reach
    # the service; both must be arguments to _run, never called directly — with
    # four deliberate exceptions, none of which can wait on the lock:
    #   bind_loop / subscribe / unsubscribe  take no lock at all (service.py:84-93).
    #       They manipulate the loop's own asyncio.Queue objects, so they are
    #       loop-affine BY DESIGN — threading them would be the bug.
    #   close  does take the lock, but only in lifespan teardown, after the
    #       server has stopped serving and there is no loop work left to starve.
    LOOP_AFFINE = {"bind_loop", "subscribe", "unsubscribe", "close"}

    direct = [
        (n, line.strip())
        for n, line in enumerate(src.splitlines(), 1)
        if (m := re.search(r"(?:_svc\(request\)|\bsvc)\.(\w+)\(", line))
        and m.group(1) not in LOOP_AFFINE
        and "_run(" not in line
        and "to_thread" not in line
    ]
    assert not direct, f"service called on the event loop: {direct}"


def test_the_loop_keeps_ticking_while_the_lock_is_held(app):
    """The behavioral assertion: a loop-resident timer (the SSE keepalive's
    shape) must keep firing while a route waits on the service lock. A blocked
    loop starves it even though it touches no service at all."""
    async def scenario():
        gaps: list[float] = []
        stop = asyncio.Event()

        async def ticker() -> None:
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.05)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            assert (await c.post("/api/login", json=LOGIN)).status_code == 200
            t = asyncio.create_task(ticker())
            await asyncio.sleep(0.2)

            _hold_lock(app.state.service, HOLD_S)
            await c.get("/api/lists/inbox/tasks")

            stop.set()
            await t
        return max(gaps, default=0.0)

    worst = asyncio.run(scenario())
    assert worst < TOLERANCE_S, (
        f"the event loop stalled for {worst:.2f}s while the service lock was "
        f"held — a coroutine touching no service at all was starved"
    )
