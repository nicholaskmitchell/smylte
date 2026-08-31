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


# ── the deployment switch ────────────────────────────────────────────────────

def test_the_app_starts_with_nothing_configured(tmp_path):
    # Configuration lives in the account's settings now and can arrive at any
    # moment, so a boot-time credential check would refuse to start a perfectly
    # good deployment that simply has not been set up yet.
    app = create_app(_settings(tmp_path))
    assert app is not None


def test_the_env_flag_is_a_kill_switch_not_the_feature_switch(tmp_path):
    # Default is "allowed"; nothing sends until the ACCOUNT turns it on.
    assert _settings(tmp_path).notify_enabled is True
    app = create_app(_settings(tmp_path, notify_enabled=False))
    assert app is not None


def test_a_disabled_deployment_builds_no_notifier(tmp_path):
    app = create_app(_settings(tmp_path, notify_enabled=False))
    with TestClient(app) as c:
        assert getattr(c.app.state, "notifier", "missing") is None


def test_an_allowed_deployment_builds_one_even_with_no_credentials(tmp_path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as c:
        assert c.app.state.notifier is not None


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


# ── the bot token is write-only ──────────────────────────────────────────────

def test_the_token_is_accepted_but_never_read_back(api):
    # The settings blob is fetched on every page load. Echoing the token would
    # put a working bot in the DOM, in the network tab, and in any screenshot.
    r = api.put("/api/settings", json={
        "notifications_enabled": True,
        "notify_telegram_chat_id": "8517516151",
        "notify_telegram_bot_token": "123456789:AAHsecretsecretsecretsecret",
    })
    assert r.status_code == 200
    for body in (r.json(), api.get("/api/settings").json()):
        assert "notify_telegram_bot_token" not in body
        assert "AAHsecret" not in str(body)
        assert body["notify_telegram_bot_token_set"] is True
        # The bot id half is public — it names which bot without being able to
        # speak as it.
        assert body["notify_telegram_bot_id"] == "123456789"
        assert body["notify_telegram_chat_id"] == "8517516151"


def test_an_unset_token_reports_itself_as_unset(api):
    body = api.get("/api/settings").json()
    assert body["notify_telegram_bot_token_set"] is False
    assert body["notify_telegram_bot_id"] == ""


def test_the_stored_token_still_reaches_the_notifier(api):
    api.put("/api/settings", json={"notify_telegram_bot_token": "999:AAHtok"})
    # The service's own view is unredacted — the redaction is a property of the
    # HTTP surface, not of storage, because the sender has to reproduce it.
    stored = api.app.state.service.get_settings()
    assert stored["notify_telegram_bot_token"] == "999:AAHtok"


# ── the test-send ────────────────────────────────────────────────────────────

def test_a_test_send_with_no_token_says_what_is_missing(api):
    # Every misconfiguration fails identically and silently, so the value of
    # this endpoint is entirely in the sentence it hands back.
    r = api.post("/api/notifications/test")
    assert r.status_code == 409
    assert "bot token" in r.json()["detail"].lower()


def test_a_test_send_with_no_chat_id_says_that_instead(api):
    api.put("/api/settings", json={"notify_telegram_bot_token": "1:AAHtok"})
    r = api.post("/api/notifications/test")
    assert r.status_code == 409
    assert "chat id" in r.json()["detail"].lower()


def test_a_test_send_needs_auth(tmp_path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as anon:
        assert anon.post("/api/notifications/test").status_code == 401


def test_a_test_send_is_refused_when_the_deployment_forbids_notifications(tmp_path):
    app = create_app(_settings(tmp_path, notify_enabled=False))
    with TestClient(app) as c:
        c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        r = c.post("/api/notifications/test")
        assert r.status_code == 409 and "TASKS_NOTIFY_ENABLED" in r.json()["detail"]


# ── the per-item reminder ────────────────────────────────────────────────────

def test_the_reminder_field_is_bounded_on_both_sides():
    import pydantic

    from tasksd.app import Sidecar
    # -1 is the clear sentinel and the only negative allowed; a week is the cap,
    # past which the reminder is about a different day than the one it names.
    assert Sidecar(notify_minutes_before=-1).notify_minutes_before == -1
    assert Sidecar(notify_minutes_before=10080).notify_minutes_before == 10080
    for bad in (-2, 10081):
        with pytest.raises(pydantic.ValidationError):
            Sidecar(notify_minutes_before=bad)
