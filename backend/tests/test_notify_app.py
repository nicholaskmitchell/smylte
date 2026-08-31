"""The wiring: the startup gate, the settings surface, and the loop's lifecycle.

No Radicale and no network — the app is built and its state hand-wired, the way
tests/test_loop_blocking.py does, so the lifespan never reaches CalDAV.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from fastapi.testclient import TestClient

from tasksd.app import _notification_loop, create_app
from tasksd.db import store
from tasksd.notify.rules import TRIGGERS
from tests.conftest import api_settings


def _settings(tmp_path, **over):
    return dataclasses.replace(api_settings(str(tmp_path / "n.db")), **over)


# ── the startup gate ─────────────────────────────────────────────────────────

def test_notifications_are_off_unless_asked_for(tmp_path):
    # A deploy should never grow an outbound network surface on its own.
    s = _settings(tmp_path)
    assert s.notify_enabled is False
    app = create_app(s)
    assert app is not None


@pytest.mark.parametrize("over,missing", [
    ({}, "TASKS_TELEGRAM_BOT_TOKEN"),
    ({"telegram_bot_token": "t"}, "TASKS_TELEGRAM_CHAT_ID"),
    ({"telegram_chat_id": "5"}, "TASKS_TELEGRAM_BOT_TOKEN"),
])
def test_enabling_without_credentials_refuses_to_start(tmp_path, over, missing):
    # A scheduler with nowhere to send is a feature that silently does nothing,
    # and the owner could not tell that from "nothing was worth notifying about".
    with pytest.raises(RuntimeError) as caught:
        create_app(_settings(tmp_path, notify_enabled=True, **over))
    assert missing in str(caught.value)


def test_the_refusal_names_the_egress_problem_too(tmp_path):
    # The unit is loopback-only; without this line the first thing the owner
    # meets after fixing the token is a silent, retrying, never-arriving send.
    with pytest.raises(RuntimeError) as caught:
        create_app(_settings(tmp_path, notify_enabled=True))
    assert "api.telegram.org" in str(caught.value)


def test_a_fully_configured_app_builds(tmp_path):
    app = create_app(_settings(tmp_path, notify_enabled=True,
                               telegram_bot_token="t", telegram_chat_id="5"))
    assert app is not None


# ── the loop ─────────────────────────────────────────────────────────────────

def test_the_loop_exits_immediately_when_notifications_are_off():
    class App:
        class state:
            notifier = None

    # No task left running, no HTTP client opened, on the default deployment.
    asyncio.run(asyncio.wait_for(_notification_loop(App()), timeout=1))


def test_the_loop_sweeps_before_it_waits():
    """A restart is the ordinary case for a missed notification — the box came
    back at 07:32 and the digest was due at 07:30. A loop that waited first
    would hold that until the next tick."""
    swept = asyncio.Event()

    class Notifier:
        def sweep(self):
            swept.set()

    class Svc:
        settings = dataclasses.replace(
            api_settings("/tmp/x.db"), notify_interval_s=3600  # far longer than the test
        )

    class App:
        class state:
            notifier = Notifier()
            service = Svc()
            notify_trigger = None

    async def run():
        App.state.notify_trigger = asyncio.Event()
        task = asyncio.create_task(_notification_loop(App()))
        await asyncio.wait_for(swept.wait(), timeout=2)
        task.cancel()

    asyncio.run(run())


# ── the settings surface ─────────────────────────────────────────────────────

@pytest.fixture
def api(tmp_path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as c:      # lifespan runs; notifier is None so no loop work
        r = c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        assert r.status_code == 200
        yield c


def test_notification_preferences_round_trip(api):
    r = api.put("/api/settings", json={
        "notify_digest_time": "06:45",
        "notify_event_lead_minutes": 20,
        "notify_triggers": {"sync_stalled": False},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["notify_digest_time"] == "06:45"
    assert body["notify_event_lead_minutes"] == 20
    assert body["notify_triggers"] == {"sync_stalled": False}


def test_an_unknown_trigger_is_dropped_not_422(api):
    # A 422 rejects the WHOLE settings PUT, taking the theme and the dashboard
    # layout with it — see the tab_order comment in app.py.
    r = api.put("/api/settings", json={
        "theme": "dark",
        "notify_triggers": {"daily_digest": False, "from_the_future": True},
    })
    assert r.status_code == 200
    assert r.json()["notify_triggers"] == {"daily_digest": False}
    assert r.json()["theme"] == "dark"


def test_a_malformed_digest_time_is_refused(api):
    assert api.put("/api/settings", json={"notify_digest_time": "25:00"}).status_code == 422
    assert api.put("/api/settings", json={"notify_digest_time": "7:30"}).status_code == 422


def test_recent_notifications_needs_auth(tmp_path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as anon:
        assert anon.get("/api/notifications/recent").status_code == 401


def test_recent_notifications_reports_what_was_said(api):
    svc = api.app.state.service
    svc.notifications(store.claim_notification, "daily_digest", "2026-08-31")
    svc.notifications(store.settle_notification, "daily_digest", "2026-08-31",
                      ok=True, silent=True)

    body = api.get("/api/notifications/recent").json()
    assert body["triggers"] == list(TRIGGERS)
    row = body["deliveries"][0]
    assert row["trigger"] == "daily_digest" and row["ok"] == 1
    # `silent` on a rule that normally buzzes is how the owner sees what the
    # daily ceiling swallowed.
    assert row["silent"] == 1


def test_the_recent_limit_is_bounded(api):
    assert api.get("/api/notifications/recent?limit=0").status_code == 422
    assert api.get("/api/notifications/recent?limit=9999").status_code == 422
    assert api.get("/api/notifications/recent?limit=5").status_code == 200
