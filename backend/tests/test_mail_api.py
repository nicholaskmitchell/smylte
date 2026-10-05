"""The email-ingestion HTTP surface: write-only credentials, validation, the
kill switch, auth on every route, and the background loop's shape.

No Radicale and no Anthropic: the app is built against a closed CalDAV port
(staging and review only touch the sidecar tables, and an unreachable server
makes the lifespan's bootstrap a logged no-op), the secret store is the
encrypted file under tmp_path, and the model is a fake SDK. The background
mail loop is replaced with a no-op for the route tests, so a scan it would
start on every settings save cannot race the assertions; the loop itself is
tested on its own at the bottom.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smylted import app as app_module
from smylted import config as cfg_module
from smylted.app import _mail_loop, create_app
from smylted.db import store
from smylted.mail import redact
from smylted.mail import settings as mail_settings
from smylted.mail.imap import FolderInfo
from tests.conftest import api_settings
from tests.imap_server import free_port, make_self_signed_cert, run_server
from tests.mail_fakes import FakeSdk, extraction_response

LOGIN = {"username": "admin", "password": "testpass123"}
KEY = "sk-ant-api03-" + "A" * 40 + "WXYZ"
CORPUS = Path(__file__).parent / "corpus" / "mail"
INBOX = FolderInfo(name="INBOX", raw="INBOX", flags=frozenset(), delimiter="/")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """A clean redaction registry, and no background scan during route tests."""
    async def _no_loop(app):
        return None

    monkeypatch.setattr(app_module, "_mail_loop", _no_loop)
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


def _settings(tmp_path, **over):
    base = dataclasses.replace(
        api_settings(str(tmp_path / "a.db")),
        radicale_url="http://127.0.0.1:9",
        secrets_backend="file",
        secrets_file=str(tmp_path / "s.enc"),
        secrets_key_file=str(tmp_path / "k.key"),
    )
    return dataclasses.replace(base, **over)


@contextlib.contextmanager
def _client(tmp_path, *, login: bool = True, **over):
    app = create_app(_settings(tmp_path, **over))
    with TestClient(app) as c:
        if login:
            assert c.post("/api/login", json=LOGIN).status_code == 200
        yield c


def _put(c, **fields):
    return c.put("/api/mail/settings", json=fields)


# ── credentials are write-only ───────────────────────────────────────────────

def test_saving_a_key_never_returns_it(tmp_path):
    with _client(tmp_path) as c:
        r = _put(c, anthropic_api_key=KEY)
        assert r.status_code == 200, r.text
        bodies = [r.text, c.get("/api/mail/settings").text, c.get("/api/settings").text,
                  c.get("/api/mail/status").text]
        for text in bodies:
            assert KEY not in text
        status = c.get("/api/mail/settings").json()["secrets"]["anthropic_api_key"]
        assert status == {"set": True, "hint": "…WXYZ", "source": "store"}

    for name in ("a.db", "a.db-wal", "s.enc"):
        path = tmp_path / name
        if path.exists():
            assert KEY.encode() not in path.read_bytes(), name
    assert (tmp_path / "s.enc").exists()


def test_clearing_a_key_with_an_empty_string(tmp_path):
    with _client(tmp_path) as c:
        assert _put(c, anthropic_api_key=KEY).status_code == 200
        r = _put(c, anthropic_api_key="")
        assert r.status_code == 200
        assert r.json()["secrets"]["anthropic_api_key"] == {
            "set": False, "hint": None, "source": None}
        # And with nothing stored the key check says so instead of calling out.
        r = c.post("/api/mail/test/anthropic")
        assert r.status_code == 409
        assert "no Anthropic API key" in r.json()["detail"]


def test_the_payload_has_three_secrets_and_the_defaults(tmp_path):
    with _client(tmp_path) as c:
        body = c.get("/api/mail/settings").json()
    assert set(body["secrets"]) == {"anthropic_api_key", "imap_password", "typesafe_api_key"}
    assert body["secrets_backend"]["name"] == "file"
    assert body["secrets_backend"]["available"] is True
    assert body["deployment_enabled"] is True
    assert body["defaults"] == {"model": "claude-haiku-4-5"}
    assert body["settings"]["enabled"] is False
    assert body["pinned_cert_fingerprint"] is None


def test_env_secrets_win_and_say_so(tmp_path):
    env_key = "sk-ant-api03-ENV" + "E" * 20 + "9876"
    with _client(tmp_path, anthropic_api_key=env_key) as c:
        r = c.get("/api/mail/settings")
    assert env_key not in r.text
    assert r.json()["secrets"]["anthropic_api_key"] == {
        "set": True, "hint": "…9876", "source": "env"}


def test_settings_keep_env_secrets_out_of_repr(monkeypatch):
    monkeypatch.setenv("SMYLTE_ANTHROPIC_API_KEY", "  " + KEY + "  ")
    monkeypatch.setenv("SMYLTE_MAIL_IMAP_PASSWORD", "bridge-secret-77")
    monkeypatch.setenv("SMYLTE_TYPESAFE_API_KEY", "ts-secret-key-1234")
    s = cfg_module.Settings.from_env()
    assert s.anthropic_api_key == KEY
    assert s.mail_imap_password == "bridge-secret-77"
    assert s.typesafe_api_key == "ts-secret-key-1234"
    text = repr(s)
    for secret in (KEY, "bridge-secret-77", "ts-secret-key-1234"):
        assert secret not in text


def test_an_unknown_secrets_backend_refuses_to_start(monkeypatch):
    monkeypatch.setenv("SMYLTE_SECRETS_BACKEND", "keyrnig")
    with pytest.raises(ValueError, match="SMYLTE_SECRETS_BACKEND"):
        cfg_module.Settings.from_env()
    monkeypatch.setenv("SMYLTE_SECRETS_BACKEND", " File ")
    assert cfg_module.Settings.from_env().secrets_backend == "file"
    monkeypatch.setenv("SMYLTE_MAIL_ENABLED", "false")
    assert cfg_module.Settings.from_env().mail_enabled is False


# ── IMAP: a failed login leaks the password nowhere ──────────────────────────

def test_failed_imap_login_logs_contain_no_password(tmp_path, caplog):
    wrong = "wrong-Bridge-pass-5309"
    cert_pem, key_pem = make_self_signed_cert()
    mailboxes = {"INBOX": {"flags": [], "uidvalidity": 1, "messages": {}}}
    caplog.set_level(logging.DEBUG)
    with run_server(mailboxes=mailboxes, user="owner@example.org", password="the-right-one-42",
                    tls_mode="starttls", cert_pem=cert_pem, key_pem=key_pem,
                    echo_password_on_failure=True) as server:
        host, port = server
        with _client(tmp_path) as c:
            r = _put(c, imap_host=host, imap_port=port, imap_username="owner@example.org",
                     imap_cert_mode="pinned", imap_pinned_cert=cert_pem, imap_password=wrong)
            assert r.status_code == 200, r.text
            assert r.json()["pinned_cert_fingerprint"]

            r = c.post("/api/mail/test/imap")
            assert r.status_code == 409
            assert wrong not in r.text
            assert redact.REDACTED in r.json()["detail"]     # the server did echo it

            assert _put(c, enabled=True, anthropic_api_key=KEY).status_code == 200
            report = c.app.state.mail.ingestor.run_once()
            assert report.ok is False
            assert report.error and wrong not in report.error

            status = c.get("/api/mail/status")
            assert status.json()["last_error"]
            assert wrong not in status.text

    assert "LOGIN" in " ".join(server.commands)          # the password did go out, wrongly
    fmt = logging.Formatter()
    assert not any(wrong in fmt.format(rec) for rec in caplog.records)


# ── the Bridge password is bound to the server it was entered for ────────────

_EMPTY_INBOX = {"INBOX": {"flags": [], "uidvalidity": 1, "messages": {}}}


def _logins(server) -> list[str]:
    return [cmd for cmd in server.commands if "LOGIN" in cmd.upper()]


def _stored_binding(c) -> str:
    stored = c.app.state.service.mail(store.get_meta_json, mail_settings.MAIL_SETTINGS_KEY)
    return stored.get("imap_password_binding", "")


@pytest.mark.parametrize("field", mail_settings.BOUND_FIELDS)
def test_changing_the_server_forgets_the_stored_password(tmp_path, field):
    # The reviewer's exploit: a session that can edit the settings repoints
    # one of them at its own server and presses "Test" to receive the password.
    cert_pem, key_pem = make_self_signed_cert()
    other_pem, _ = make_self_signed_cert()
    with run_server(mailboxes=_EMPTY_INBOX, user="x", password="y",
                    tls_mode="ssl", cert_pem=cert_pem, key_pem=key_pem) as server:
        reaches = {"imap_host": "127.0.0.1", "imap_port": server.port, "imap_tls": "ssl",
                   "imap_cert_mode": "insecure_localhost", "imap_username": "x"}
        # What the owner saved, differing from `reaches` in `field` alone,
        # and the one-field change that points it at the server.
        saved, change = {
            "imap_host": ({"imap_host": "localhost"}, {"imap_host": "127.0.0.1"}),
            "imap_port": ({"imap_port": free_port()}, {"imap_port": server.port}),
            "imap_tls": ({"imap_tls": "starttls"}, {"imap_tls": "ssl"}),
            "imap_cert_mode": ({"imap_cert_mode": "system"},
                               {"imap_cert_mode": "insecure_localhost"}),
            "imap_pinned_cert": ({"imap_cert_mode": "pinned", "imap_pinned_cert": other_pem},
                                 {"imap_pinned_cert": cert_pem}),
            "imap_username": ({"imap_username": "owner@proton.me"}, {"imap_username": "x"}),
        }[field]
        with _client(tmp_path) as c:
            r = _put(c, **{**reaches, **saved}, imap_password="Bridge-Generated-XYZ123")
            assert r.status_code == 200, r.text
            assert r.json()["secrets"]["imap_password"]["set"] is True
            assert _stored_binding(c)

            r = _put(c, **change)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["secrets"]["imap_password"] == {"set": False, "hint": None, "source": None}
            assert "imap_password_binding" not in body["settings"]
            assert _stored_binding(c) == ""

            r = c.post("/api/mail/test/imap")
            assert r.status_code == 409
        assert _logins(server) == []


def test_a_password_saved_with_the_server_is_bound_to_that_server(tmp_path):
    cert_pem, key_pem = make_self_signed_cert()
    with run_server(mailboxes=_EMPTY_INBOX, user="x", password="y",
                    tls_mode="ssl", cert_pem=cert_pem, key_pem=key_pem) as server:
        with _client(tmp_path) as c:
            r = _put(c, imap_host="localhost", imap_port=free_port(), imap_tls="ssl",
                     imap_cert_mode="insecure_localhost", imap_username="x", imap_password="y")
            assert r.status_code == 200, r.text
            r = _put(c, imap_host="127.0.0.1", imap_port=server.port, imap_password="y")
            assert r.status_code == 200, r.text
            cfg = c.app.state.mail.ingestor.config()
            assert _stored_binding(c) == mail_settings.connection_binding(cfg)
            assert mail_settings.password_binding_ok(cfg)
            # Settings outside the binding leave the password where it is.
            r = _put(c, folders=["INBOX"], poll_minutes=10)
            assert r.json()["secrets"]["imap_password"]["set"] is True
            r = c.post("/api/mail/test/imap")
            assert r.status_code == 200, r.text
            # Clearing the password clears its binding.
            assert _put(c, imap_password="").status_code == 200
            assert _stored_binding(c) == ""
    assert len(_logins(server)) == 1


def test_an_env_password_waits_for_a_restart_after_a_server_change(tmp_path):
    cert_pem, key_pem = make_self_signed_cert()
    with run_server(mailboxes=_EMPTY_INBOX, user="x", password="y",
                    tls_mode="ssl", cert_pem=cert_pem, key_pem=key_pem) as server:
        with _client(tmp_path, mail_imap_password="y") as c:
            r = _put(c, imap_host="127.0.0.1", imap_port=server.port, imap_tls="ssl",
                     imap_cert_mode="insecure_localhost", imap_username="x")
            assert r.status_code == 200, r.text
            # The env password cannot be deleted, so it stays set but unbound.
            assert r.json()["secrets"]["imap_password"]["source"] == "env"
            r = c.post("/api/mail/test/imap")
            assert r.status_code == 409
            assert r.json()["detail"] == mail_settings.PASSWORD_BINDING_MESSAGE
        assert _logins(server) == []

        # The restart is the operator's confirmation of the new server.
        with _client(tmp_path, mail_imap_password="y") as c:
            r = c.post("/api/mail/test/imap")
            assert r.status_code == 200, r.text
            assert len(_logins(server)) == 1
            assert _put(c, imap_username="someone-else").status_code == 200
            r = c.post("/api/mail/test/imap")
            assert r.status_code == 409
            assert r.json()["detail"] == mail_settings.PASSWORD_BINDING_MESSAGE
        assert len(_logins(server)) == 1


def test_the_binding_is_not_a_setting(tmp_path):
    with _client(tmp_path) as c:
        r = _put(c, imap_password_binding="a" * 64)
        assert r.status_code == 422
        assert "imap_password_binding" not in c.get("/api/mail/settings").json()["settings"]
        assert _stored_binding(c) == ""


# ── the model is read from Settings on every call ─────────────────────────────

def test_model_change_applies_without_restart(tmp_path):
    sdk = FakeSdk([extraction_response("", actionable=False),
                   extraction_response("", actionable=False)])
    with _client(tmp_path) as c:
        ingestor = c.app.state.mail.ingestor
        ingestor.llm.client_factory = lambda key, workspace: sdk
        assert _put(c, anthropic_api_key=KEY, model="claude-model-a").status_code == 200
        out = ingestor.process_message(INBOX, (CORPUS / "pipe_request.eml").read_bytes())
        assert out.outcome == "not_actionable", out
        assert _put(c, model="claude-model-b").status_code == 200
        out = ingestor.process_message(INBOX, (CORPUS / "pipe_injection.eml").read_bytes())
        assert out.outcome == "not_actionable", out
    assert [call["model"] for call in sdk.calls] == ["claude-model-a", "claude-model-b"]


# ── auth ─────────────────────────────────────────────────────────────────────

def test_mail_endpoints_require_auth(tmp_path):
    sid = uuid.uuid4().hex
    routes = [
        ("GET", "/api/mail/settings"),
        ("PUT", "/api/mail/settings"),
        ("POST", "/api/mail/test/anthropic"),
        ("POST", "/api/mail/test/typesafe"),
        ("POST", "/api/mail/test/imap"),
        ("GET", "/api/mail/models"),
        ("GET", "/api/mail/status"),
        ("POST", "/api/mail/scan"),
        ("GET", "/api/mail/suggestions"),
        ("POST", f"/api/mail/suggestions/{sid}/approve"),
        ("POST", f"/api/mail/suggestions/{sid}/reject"),
    ]
    with _client(tmp_path, login=False) as c:
        for method, path in routes:
            r = c.request(method, path, json={})
            assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


# ── the deployment kill switch ───────────────────────────────────────────────

def test_kill_switch_refuses_tests_and_scans(tmp_path):
    with _client(tmp_path, mail_enabled=False) as c:
        for path in ("/api/mail/test/anthropic", "/api/mail/test/typesafe",
                     "/api/mail/test/imap", "/api/mail/scan"):
            r = c.post(path)
            assert r.status_code == 409, path
            assert "SMYLTE_MAIL_ENABLED" in r.json()["detail"], path
        r = c.get("/api/mail/settings")
        assert r.status_code == 200
        assert r.json()["deployment_enabled"] is False
        assert _put(c, enabled=True).status_code == 200
        assert c.get("/api/mail/suggestions").json()["enabled"] is False
        assert c.get("/api/mail/status").json()["deployment_enabled"] is False


def test_kill_switch_refuses_the_model_list(tmp_path):
    with _client(tmp_path, mail_enabled=False) as c:
        assert _put(c, anthropic_api_key=KEY).status_code == 200
        r = c.get("/api/mail/models")
        assert r.status_code == 409
        assert "SMYLTE_MAIL_ENABLED" in r.json()["detail"]


# ── validation ───────────────────────────────────────────────────────────────

def test_a_bad_pattern_is_refused_by_name(tmp_path):
    with _client(tmp_path) as c:
        r = _put(c, always_parse=["school.example", "not a domain"])
        assert r.status_code == 422
        assert "not a domain" in r.text


def test_a_bad_rule_is_refused_with_its_number(tmp_path):
    with _client(tmp_path) as c:
        r = _put(c, kind_decider="rules", kind_rules=["subject:invoice -> task", "nonsense"])
        assert r.status_code == 422
        assert "rule 2" in r.text
        r = _put(c, kind_decider="rules", kind_rules=["subject:invoice -> task"])
        assert r.status_code == 200
        assert r.json()["settings"]["kind_rules"] == ["subject:invoice -> task"]
        assert _put(c, kind_decider="jev", jev_model="jev-preview").status_code == 200
        r = _put(c, dedup_decider="model")
        assert r.status_code == 200 and r.json()["settings"]["dedup_decider"] == "model"
        assert _put(c, dedup_decider="rules").status_code == 422


def test_insecure_tls_is_only_for_loopback(tmp_path):
    with _client(tmp_path) as c:
        r = _put(c, imap_host="mail.example.com", imap_cert_mode="insecure_localhost",
                 anthropic_api_key=KEY)
        assert r.status_code == 422
        assert "loopback" in r.json()["detail"]
        assert KEY not in r.text
        # Refused before anything was written, the credential included.
        body = c.get("/api/mail/settings").json()
        assert body["settings"]["imap_cert_mode"] == "system"
        assert body["secrets"]["anthropic_api_key"]["set"] is False
        # The rule reads the merged config: a later host change is refused too.
        assert _put(c, imap_cert_mode="insecure_localhost").status_code == 200
        assert _put(c, imap_host="mail.example.com").status_code == 422
        assert _put(c, imap_host="::1").status_code == 200


def test_unknown_fields_and_bad_values_never_echo_a_secret(tmp_path):
    with _client(tmp_path) as c:
        for extra in ({"bogus": 1}, {"imap_port": 0}, {"poll_minutes": 0},
                      {"imap_tls": "none"}, {"auto_accept_min_confidence": 2}):
            r = _put(c, anthropic_api_key=KEY, **extra)
            assert r.status_code == 422, extra
            assert KEY not in r.text, extra
        assert c.get("/api/mail/settings").json()["secrets"]["anthropic_api_key"]["set"] is False


def test_null_resets_only_where_it_means_default(tmp_path):
    with _client(tmp_path) as c:
        body = _put(c, task_list="work", enabled=True, auto_accept_min_confidence=0.7).json()
        assert body["settings"]["task_list"] == "work"
        assert body["settings"]["auto_accept_min_confidence"] == 0.7
        body = _put(c, task_list=None, enabled=None, auto_accept_min_confidence=None).json()
        assert body["settings"]["task_list"] is None
        assert body["settings"]["auto_accept_min_confidence"] is None
        assert body["settings"]["enabled"] is True            # null elsewhere: not mentioned
        assert _put(c, event_calendar="").json()["settings"]["event_calendar"] is None


# ── PUT answers with the payload and wakes the loop ─────────────────────────

def test_put_returns_the_payload_and_triggers_a_scan(tmp_path):
    with _client(tmp_path) as c:
        trigger = c.app.state.mail_trigger
        trigger.clear()
        r = _put(c, enabled=True, folders=["inbox", "Labels/School"], poll_minutes=10)
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"settings", "secrets", "secrets_backend",
                             "pinned_cert_fingerprint", "deployment_enabled", "defaults"}
        assert body["settings"]["folders"] == ["INBOX", "Labels/School"]
        assert body["settings"]["poll_minutes"] == 10
        assert trigger.is_set()

        trigger.clear()
        r = c.post("/api/mail/scan")
        assert r.status_code == 202
        assert r.json() == {"queued": True}
        assert trigger.is_set()

        assert _put(c, enabled=False).status_code == 200
        trigger.clear()
        r = c.post("/api/mail/scan")
        assert r.status_code == 409
        assert "switched off in Settings" in r.json()["detail"]
        assert not trigger.is_set()


# ── suggestions ──────────────────────────────────────────────────────────────

def _insert_suggestion(svc) -> str:
    sid = uuid.uuid4().hex
    svc.mail(store.mail_insert_suggestion, sid, {
        "kind": "task", "title": "Bring the snack list", "due": "2026-10-09",
        "confidence": 0.9, "sender": "coach@club.example", "sender_name": "Coach",
        "subject": "Snacks", "message_key": "mid:req-1@club.example",
        "message_id": "req-1@club.example", "thread_id": "req-1@club.example",
        "folder": "INBOX",
    })
    return sid


def test_suggestions_list_and_reject(tmp_path):
    with _client(tmp_path) as c:
        sid = _insert_suggestion(c.app.state.service)
        body = c.get("/api/mail/suggestions").json()
        assert body["pending_count"] == 1
        assert [s["id"] for s in body["suggestions"]] == [sid]
        assert body["suggestions"][0]["source"]["sender"] == "coach@club.example"

        r = c.post(f"/api/mail/suggestions/{sid}/reject")
        assert r.status_code == 200, r.text
        assert r.json()["suggestion"]["status"] == "rejected"
        assert c.get("/api/mail/suggestions").json()["suggestions"] == []
        rejected = c.get("/api/mail/suggestions", params={"status": "rejected"}).json()
        assert [s["id"] for s in rejected["suggestions"]] == [sid]
        assert len(c.get("/api/mail/suggestions", params={"status": "all"}).json()["suggestions"]) == 1

        assert c.post(f"/api/mail/suggestions/{sid}/reject").status_code == 409
        assert c.post(f"/api/mail/suggestions/{sid}/approve", json={}).status_code == 409


def test_approve_refuses_unknown_and_malformed_ids(tmp_path):
    with _client(tmp_path) as c:
        assert c.post(f"/api/mail/suggestions/{uuid.uuid4().hex}/approve",
                      json={}).status_code == 404
        assert c.post("/api/mail/suggestions/not-an-id/approve", json={}).status_code == 404
        assert c.post("/api/mail/suggestions/not-an-id/reject").status_code == 404
        sid = _insert_suggestion(c.app.state.service)
        assert c.post(f"/api/mail/suggestions/{sid}/approve",
                      json={"due": "9 October"}).status_code == 422
        assert c.post(f"/api/mail/suggestions/{sid}/approve",
                      json={"colour": "red"}).status_code == 422
        # No list exists (Radicale is unreachable): a refusal the owner can act on.
        r = c.post(f"/api/mail/suggestions/{sid}/approve", json={"due": None})
        assert r.status_code == 422
        assert "choose a list" in r.json()["detail"]
        assert c.get("/api/mail/suggestions").json()["pending_count"] == 1


def test_suggestion_query_is_validated(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/api/mail/suggestions", params={"status": "approving"}).status_code == 422
        assert c.get("/api/mail/suggestions", params={"limit": 0}).status_code == 422
        assert c.get("/api/mail/suggestions", params={"limit": 201}).status_code == 422


# ── the background loop ──────────────────────────────────────────────────────

def test_the_loop_exits_immediately_without_a_runtime():
    class App:
        class state:
            pass

    asyncio.run(asyncio.wait_for(_mail_loop(App()), timeout=1))


def test_the_loop_scans_first_and_again_when_poked():
    class Ingestor:
        def __init__(self):
            self.runs = 0
            self.ran = None

        def run_once(self):
            self.runs += 1
            self.ran.set()

        def poll_interval_s(self):
            return 3600.0

    ingestor = Ingestor()

    class App:
        class state:
            mail = type("Rt", (), {"ingestor": ingestor})()
            mail_trigger = None

    async def run():
        loop = asyncio.get_running_loop()
        ingestor.ran = _ThreadSafeEvent(loop)
        App.state.mail_trigger = asyncio.Event()
        task = asyncio.create_task(_mail_loop(App()))
        await asyncio.wait_for(ingestor.ran.wait(), timeout=2)
        assert ingestor.runs == 1                       # before any wait
        ingestor.ran.clear()
        App.state.mail_trigger.set()
        await asyncio.wait_for(ingestor.ran.wait(), timeout=2)
        assert ingestor.runs == 2                       # the trigger cut the hour short
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())


class _ThreadSafeEvent:
    """An asyncio.Event that a worker thread (where `run_once` runs) can set."""

    def __init__(self, loop):
        self._loop = loop
        self._event = asyncio.Event()

    def set(self):
        self._loop.call_soon_threadsafe(self._event.set)

    def clear(self):
        self._event.clear()

    async def wait(self):
        await self._event.wait()


def test_shutdown_stops_the_scan_and_waits_for_it_before_closing(tmp_path):
    """The lifespan asks a running scan to stop and waits for it, BEFORE the
    service closes: a scan cut off mid-message would otherwise settle into a
    closed database and leave its message for nobody."""
    seen = []
    with _client(tmp_path) as c:
        ing = c.app.state.mail.ingestor
        svc = c.app.state.service

        def wait_idle(timeout):
            seen.append((ing._stop.is_set(), svc._closed, timeout))
            return True

        ing.wait_idle = wait_idle
    assert seen == [(True, False, 20.0)]
    assert ing.run_once().skipped_reason == "stopping"
