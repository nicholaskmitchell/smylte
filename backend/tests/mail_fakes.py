"""Test doubles for the mail pipeline: a mailbox, a model, a Jev, and a service.

`FakeMailSource` is an in-memory `MailSource`; `FakeLlm` and `FakeJev` answer
from scripts and record what they were asked; `make_llm_client` builds the REAL
`LlmClient` over a fake SDK so a test can assert on the actual request. The
service is a real `SmylteService` pointed at a closed port: staging only
touches the sidecar tables, so nothing here needs Radicale.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date, datetime, timezone
from email import message_from_bytes
from email.policy import compat32
from types import SimpleNamespace
from typing import Any

from smylted.db import store
from smylted.mail.imap import FetchedMessage, FolderInfo, FolderState
from smylted.mail.jev import JevError, JevMatch, KindVerdict
from smylted.mail.llm import EXTRACT_TOOL_NAME, MATCH_TOOL_NAME, Extraction, LlmClient, Match
from smylted.mail.secrets import EncryptedFileBackend, KeyringBackend, SecretStore
from smylted.mail.settings import MAIL_SETTINGS_KEY
from tests.conftest import api_settings

TEST_API_KEY = "sk-ant-api03-TESTKEYTESTKEY"
TEST_PASSWORD = "bridge-pass-1234"
TEST_TYPESAFE_KEY = "ts-live-TESTKEYTESTKEY"


# ── mailbox ──

class FakeMailSource:
    """`MailSource` over `{name: {"flags", "uidvalidity", "messages", "dates"}}`.

    The folder dicts are live: a test may renumber messages or change the
    uidvalidity between runs. `calls` records `(method, argument)` pairs.
    """

    def __init__(self, folders: dict[str, dict]):
        self.folders = folders
        self.calls: list[tuple[str, Any]] = []
        self.selected: str | None = None
        self.closed = False

    def _folder(self) -> dict:
        assert self.selected is not None, "select a folder first"
        return self.folders[self.selected]

    def list_folders(self) -> list[FolderInfo]:
        self.calls.append(("list_folders", None))
        return [FolderInfo(name=name, raw=name,
                           flags=frozenset(f.lower() for f in spec.get("flags", ())),
                           delimiter="/")
                for name, spec in self.folders.items()]

    def select(self, folder: FolderInfo) -> FolderState:
        self.calls.append(("select", folder.name))
        self.selected = folder.name
        spec = self._folder()
        msgs = spec.get("messages", {})
        return FolderState(uidvalidity=spec["uidvalidity"],
                           uidnext=spec.get("uidnext", max(msgs, default=0) + 1),
                           exists=len(msgs))

    def search_uids(self, *, after_uid: int | None = None, since: date | None = None) -> list[int]:
        self.calls.append(("search_uids", {"after_uid": after_uid, "since": since}))
        spec = self._folder()
        dates = spec.get("dates", {})
        out = []
        for uid in sorted(spec.get("messages", {})):
            if after_uid is not None and uid <= after_uid:
                continue
            if since is not None and uid in dates and dates[uid].date() < since:
                continue
            out.append(uid)
        return out

    def fetch(self, uids, *, max_bytes: int):
        self.calls.append(("fetch", list(uids)))
        spec = self._folder()
        for uid in sorted(set(uids)):
            raw = spec.get("messages", {}).get(uid)
            if raw is None:
                continue
            yield FetchedMessage(uid=uid, raw=raw if len(raw) <= max_bytes else None,
                                 size=len(raw), internaldate=spec.get("dates", {}).get(uid))

    def fetch_header_fields(self, uid: int, fields) -> bytes:
        self.calls.append(("fetch_header_fields", uid))
        raw = self._folder()["messages"][uid]
        wanted = {f.lower() for f in fields}
        msg = message_from_bytes(raw, policy=compat32)
        lines = [f"{k}: {v}" for k, v in msg.items() if k.lower() in wanted]
        return ("\r\n".join(lines) + "\r\n\r\n").encode()

    def close(self) -> None:
        self.calls.append(("close", None))
        self.closed = True

    def selected_names(self) -> list[str]:
        return [arg for name, arg in self.calls if name == "select"]


def source_factory(source: FakeMailSource) -> Callable:
    """A `source_factory` for `Ingestor` that hands back `source` and records the login."""
    def factory(cfg, password):
        source.calls.append(("connect", (cfg.host, cfg.username)))
        return source
    return factory


# ── model ──

def extraction(title: str = "", *, actionable: bool = True, kind: str = "task", notes: str = "",
               due: date | None = None, event_start=None, event_end=None, location: str = "",
               confidence: float = 0.9) -> Extraction:
    if not actionable:
        return Extraction(is_actionable=False, kind="task", title="", notes="", due=None,
                          event_start=None, event_end=None, location="", confidence=confidence)
    return Extraction(is_actionable=True, kind=kind, title=title, notes=notes, due=due,
                      event_start=event_start, event_end=event_end, location=location,
                      confidence=confidence)


def _answer(script, *args):
    if callable(script):
        result = script(*args)
    elif isinstance(script, list):
        assert script, "the fake was called more often than the test scripted"
        result = script.pop(0)
    else:
        result = script
    if isinstance(result, BaseException):
        raise result
    return result


class FakeLlm:
    """`extract` / `match` answered from scripts: a callable, a list (a queue,
    one entry per call; an exception entry is raised) or a single value."""

    def __init__(self, extract=None, match=None, *, model_provider: Callable[[], str] | None = None):
        self.extract_script = extract if extract is not None else extraction(actionable=False)
        self.match_script = match if match is not None else Match("new", None)
        self.model_provider = model_provider
        self.extract_calls: list = []
        self.match_calls: list = []
        self.models: list[str | None] = []

    def _model(self) -> str | None:
        m = self.model_provider() if self.model_provider else None
        self.models.append(m)
        return m

    def extract(self, email):
        self._model()
        self.extract_calls.append(email)
        return _answer(self.extract_script, email)

    def match(self, item, candidates):
        self._model()
        self.match_calls.append((item, list(candidates)))
        return _answer(self.match_script, item, candidates)


class FakeSdk:
    """Just enough of `anthropic.Anthropic` for `LlmClient`: `messages.create`
    returns the scripted responses and records every request's kwargs."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[dict] = []
        self.factory_calls: list[tuple] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _answer(self.responses, kwargs)


def tool_use(name: str, inp: dict):
    return SimpleNamespace(type="tool_use", name=name, input=inp)


def response(*blocks, stop_reason: str = "tool_use"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


def extraction_response(title: str, *, kind: str = "task", due: str | None = None,
                        notes: str = "", confidence: float = 0.9, actionable: bool = True,
                        event_start: str | None = None):
    return response(tool_use(EXTRACT_TOOL_NAME, {
        "is_actionable": actionable, "kind": kind, "title": title, "notes": notes, "due": due,
        "event_start": event_start, "event_end": None, "location": "", "confidence": confidence,
    }))


def match_response(decision: str = "new", target: str = "none"):
    return response(tool_use(MATCH_TOOL_NAME, {"decision": decision, "target": target}))


def make_llm_client(responses, *, model_provider: Callable[[], str] = lambda: "claude-test",
                    api_key: str = TEST_API_KEY) -> tuple[LlmClient, FakeSdk]:
    """A real `LlmClient` whose SDK is a `FakeSdk` answering `responses`."""
    sdk = FakeSdk(responses)

    def factory(*args):
        sdk.factory_calls.append(args[1:])          # never record the key
        return sdk

    client = LlmClient(api_key_provider=lambda: api_key, model_provider=model_provider,
                       client_factory=factory, nonce_factory=lambda: "n0nce")
    return client, sdk


# ── Jev ──

class FakeJev:
    """`decide_kind` and `match` answered from scripts; records what each was asked."""

    def __init__(self, script=None, match=None):
        self.script = script if script is not None else JevError("not scripted", kind="config")
        self.match_script = match if match is not None else JevError("not scripted", kind="config")
        self.calls: list[dict] = []
        self.match_calls: list[tuple[dict, list[dict]]] = []

    def decide_kind(self, **kwargs) -> KindVerdict:
        self.calls.append(kwargs)
        return _answer(self.script, kwargs)

    def match(self, item, candidates) -> JevMatch:
        self.match_calls.append((item, list(candidates)))
        return _answer(self.match_script, item, candidates)

    def test_key(self) -> str:
        return "The TypeSafe key works; models: jev-latest."

    def close(self) -> None:
        pass


def verdict(kind: str, *, confidence: float = 0.9, agreed: bool = True,
            model: str = "jev-1.13.0") -> KindVerdict:
    other = "task" if kind == "event" else "event"
    return KindVerdict(kind=kind, confidence=confidence if agreed else 0.0,
                       probabilities={kind: 0.9, other: 0.1}, model=model, agreed=agreed)


def jev_match(target: str | None, p: float, *, changed: float | None = None,
              unsure: bool = False, model: str = "jev-1.13.0") -> JevMatch:
    return JevMatch(target=target, p=p, unsure=unsure, changed=changed, model=model)


# ── service, secrets, settings ──

def make_service(tmp_path):
    """A real service whose Radicale is unreachable on purpose; close it when done."""
    from smylted.service import SmylteService

    return SmylteService(dataclasses.replace(api_settings(str(tmp_path / "m.db")),
                                             radicale_url="http://127.0.0.1:9"))


def make_store(tmp_path, *, api_key: str | None = TEST_API_KEY,
               password: str | None = TEST_PASSWORD,
               typesafe_key: str | None = None) -> SecretStore:
    """A file-backed secret store under `tmp_path` holding the given secrets."""
    marker: dict[str, str] = {}
    secrets = SecretStore(
        choice="file",
        file_backend=EncryptedFileBackend(str(tmp_path / "secrets.enc"),
                                          str(tmp_path / "secrets.key")),
        keyring_backend=KeyringBackend(module=SimpleNamespace()),
        env=None,
        marker_get=lambda: marker.get("backend"),
        marker_set=lambda v: marker.__setitem__("backend", v),
    )
    for name, value in (("anthropic_api_key", api_key), ("imap_password", password),
                        ("typesafe_api_key", typesafe_key)):
        if value:
            secrets.set(name, value)
    return secrets


def set_config(svc, **fields) -> dict:
    return svc.mail(store.merge_meta_json, MAIL_SETTINGS_KEY, fields)


class SpyHost:
    """Wraps a service and records which of its methods were called."""

    def __init__(self, svc):
        self._svc = svc
        self.called: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._svc, name)
        if not callable(attr):
            return attr

        def spy(*args, **kwargs):
            self.called.append(name)
            return attr(*args, **kwargs)
        return spy


def at(year: int, month: int, day: int, hour: int = 9) -> datetime:
    """An aware UTC instant, for INTERNALDATEs and clocks."""
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)
