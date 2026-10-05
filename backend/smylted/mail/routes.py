"""HTTP routes for email ingestion, registered onto the app's `/api` router.

They live here rather than in app.py because they are a feature with its own
state (`app.state.mail`, a `MailRuntime`) and their own vocabulary; app.py only
calls `register(api)`, before `include_router`, so every route below sits behind
`require_auth` like the rest of `/api`.

Three rules hold for every handler:

- **Nothing blocking on the event loop.** Settings reads, secret-store access,
  the IMAP and Anthropic checks and every service call go through
  `asyncio.to_thread`: the service lock can be held across CalDAV I/O for
  thirty seconds, and the secret store may wait on a keyring or a disk.
- **Credentials are write-only.** `PUT /mail/settings` accepts them; no
  response carries one back. The payload says whether each is set, a
  four-character hint and who supplied it (`SecretStore.statuses`).
- **Every error text is redacted** before it becomes an HTTP detail. The
  messages are built to be safe in the first place; `redact` is the backstop
  for an upstream error that quotes something it should not.

Settings are validated twice on purpose: the `check_*` validators refuse a bad
entry here, with a sentence naming it, while `settings.load` stays tolerant for
the unattended pipeline. One rule spans fields and is checked on the would-be
merged configuration: certificate checks may only be switched off for a
loopback host, because a Bridge on another machine is reached over a network
where a forged certificate is the attack the check exists for.

The stored Bridge password is bound to the server settings it was entered for
(`settings.connection_binding`). A save that changes the host, port,
encryption, certificate or username without a new password deletes a stored
one and clears the binding, so a session that can edit the settings cannot
point them at its own server and press "Test" to receive the password.

A password from the environment cannot be deleted, overrides any saved here,
and is bound again at every start (`runtime.build_runtime`) — and a deploy
restarts the service. Clearing its binding would therefore only last until the
next deploy, which would then bind it to whatever server the UI last named. So
while `SMYLTE_MAIL_IMAP_PASSWORD` is set the route refuses both a password
(which would never be used) and any save that changes the server settings;
bound fields resent unchanged, and every other setting, still save. The
operator changes the server by unsetting the variable, saving, setting it again
and restarting.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..db import store
from . import review, settings
from .imap import MailConnectError
from .jev import JevError
from .llm import LlmError
from .redact import redact
from .secrets import SecretStoreError
from .settings import DEFAULT_MODEL, MAIL_SETTINGS_KEY

# Write-only fields of the settings patch; each is also a SecretStore name.
_SECRET_FIELDS = ("anthropic_api_key", "imap_password", "typesafe_api_key")
# Fields where an explicit `null` means "back to the default". For every other
# field `null` is the same as leaving it out.
_NULLABLE = ("task_list", "event_calendar", "auto_accept_min_confidence")
_SUGGESTION_ID = re.compile(r"^[0-9a-f]{32}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_KILL_SWITCH = ("email ingestion is disabled for this deployment "
                "(SMYLTE_MAIL_ENABLED=false)")
_ENV_PASSWORD = ("the Bridge password is set by SMYLTE_MAIL_IMAP_PASSWORD, which overrides "
                 "one saved here; unset it to manage the password in Settings")
_ENV_SERVER = ("the server settings (host, port, encryption, certificate, username) are fixed "
               "while SMYLTE_MAIL_IMAP_PASSWORD is set; unset it, change them here, then set it "
               "again and restart")
_INSECURE_REMOTE = ("certificate checks can only be switched off for a loopback host "
                    "(127.0.0.1, ::1 or localhost)")


class MailSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    model: str | None = Field(default=None, max_length=100)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_username: str | None = Field(default=None, max_length=320)
    imap_tls: Literal["starttls", "ssl"] | None = None
    imap_cert_mode: Literal["system", "pinned", "insecure_localhost"] | None = None
    imap_pinned_cert: str | None = Field(default=None, max_length=20000)
    folders: list[str] | None = Field(default=None, max_length=50)
    self_addresses: list[str] | None = Field(default=None, max_length=100)
    always_parse: list[str] | None = Field(default=None, max_length=500)
    never_parse: list[str] | None = Field(default=None, max_length=500)
    capture_notes_to_self: bool | None = None
    poll_minutes: int | None = Field(default=None, ge=1, le=1440)
    body_max_chars: int | None = Field(default=None, ge=500, le=100000)
    backfill_days: int | None = Field(default=None, ge=0, le=90)
    task_list: str | None = Field(default=None, max_length=200)
    event_calendar: str | None = Field(default=None, max_length=200)
    trusted_authserv_ids: list[str] | None = Field(default=None, max_length=20)
    auto_accept_min_confidence: float | None = Field(default=None, ge=0, le=1)
    kind_decider: Literal["model", "jev", "rules"] | None = None
    kind_rules: list[str] | None = Field(default=None, max_length=100)
    dedup_decider: Literal["model", "jev"] | None = None
    jev_model: str | None = Field(default=None, max_length=100)
    anthropic_workspace_id: str | None = Field(default=None, max_length=100)
    # WRITE-ONLY. Non-empty stores, "" clears. Never returned by any endpoint.
    anthropic_api_key: str | None = Field(default=None, max_length=4096)
    imap_password: str | None = Field(default=None, max_length=4096)
    typesafe_api_key: str | None = Field(default=None, max_length=4096)

    @field_validator("model", "jev_model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        return None if v is None else settings.check_model(v)

    @field_validator("imap_host")
    @classmethod
    def _host(cls, v: str | None) -> str | None:
        return None if v is None else settings.check_host(v)

    @field_validator("imap_username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return None if v is None else settings.check_username(v)

    @field_validator("imap_pinned_cert")
    @classmethod
    def _pem(cls, v: str | None) -> str | None:
        return None if v is None else settings.check_pem(v)

    @field_validator("folders")
    @classmethod
    def _folders(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else settings.check_folders(v)

    @field_validator("self_addresses")
    @classmethod
    def _addresses(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else settings.check_addresses(v)

    @field_validator("always_parse", "never_parse")
    @classmethod
    def _patterns(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else settings.check_patterns(v)

    @field_validator("trusted_authserv_ids")
    @classmethod
    def _authserv(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else settings.check_authserv_patterns(v)

    @field_validator("kind_rules")
    @classmethod
    def _rules(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else settings.check_kind_rules(v)

    @field_validator("anthropic_workspace_id")
    @classmethod
    def _workspace(cls, v: str | None) -> str | None:
        return None if v is None else settings.check_workspace_id(v)

    @field_validator("task_list", "event_calendar")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        # "" is the form's "no choice": the same as null, back to the default.
        return (v.strip() or None) if isinstance(v, str) else v


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=5000)
    # YYYY-MM-DD; an explicit null clears the suggested date, absent keeps it.
    due: str | None = None
    list: str | None = Field(default=None, max_length=200)
    calendar: str | None = Field(default=None, max_length=200)

    @field_validator("due")
    @classmethod
    def _due(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        try:
            if not _ISO_DATE.match(v):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("due must be a date as YYYY-MM-DD") from None
        return v


def _rt(request: Request):
    rt = getattr(request.app.state, "mail", None)
    if rt is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "email ingestion is not initialised")
    return rt


def _conflict(exc: BaseException) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, redact(str(exc)))


def _require_deployment(rt) -> None:
    if not rt.deployment_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, _KILL_SWITCH)


def _wake(request: Request) -> None:
    # Read defensively, like notify_trigger in app.py: a test may build the
    # app without its lifespan and hand-wire app.state.
    trigger = getattr(request.app.state, "mail_trigger", None)
    if trigger is not None:
        trigger.set()


def _payload(rt) -> dict:
    """GET /mail/settings. Blocking (database, secret store): call in a thread."""
    cfg = rt.ingestor.config()
    return {
        "settings": settings.public(cfg),
        "secrets": rt.secrets.statuses(),
        "secrets_backend": rt.secrets.backend_status(),
        "pinned_cert_fingerprint": settings.pem_fingerprint(cfg.imap_pinned_cert),
        "deployment_enabled": rt.deployment_enabled,
        "defaults": {"model": DEFAULT_MODEL},
    }


def _insecure_remote(svc, data: dict) -> bool:
    """Would saving `data` leave certificate checks off for a non-loopback host?"""
    stored = svc.mail(store.get_meta_json, MAIL_SETTINGS_KEY)
    cfg = settings.load({**stored, **data})
    return (cfg.imap_cert_mode == "insecure_localhost"
            and not settings.is_loopback_host(cfg.imap_host))


def _bindings(svc, data: dict) -> tuple[str, str]:
    """The password binding of the stored settings, and of them with `data` saved."""
    stored = svc.mail(store.get_meta_json, MAIL_SETTINGS_KEY)
    return (settings.connection_binding(settings.load(stored)),
            settings.connection_binding(settings.load({**stored, **data})))


def _check_sid(sid: str) -> None:
    # Ids are uuid4().hex; anything else cannot exist, and refusing it here
    # keeps arbitrary path text out of the database query and the logs.
    if not _SUGGESTION_ID.match(sid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such suggestion")


def register(api: APIRouter) -> None:
    """Add the `/mail/...` routes to `api` (the auth-gated `/api` router)."""

    @api.get("/mail/settings")
    async def get_mail_settings(request: Request):
        rt = _rt(request)
        return await asyncio.to_thread(_payload, rt)

    @api.put("/mail/settings")
    async def put_mail_settings(request: Request, body: MailSettingsPatch):
        rt = _rt(request)
        svc = request.app.state.service
        data = body.model_dump(exclude_unset=True)
        secrets = {name: data.pop(name) for name in _SECRET_FIELDS if name in data}
        # `null` is "back to the default" only where a default is a choice of
        # its own; anywhere else it means "not mentioned".
        data = {k: v for k, v in data.items() if v is not None or k in _NULLABLE}
        # Refused before anything is written, credentials included, so a 422
        # leaves the stored state exactly as it was.
        if data and await asyncio.to_thread(_insecure_remote, svc, data):
            raise HTTPException(422, _INSECURE_REMOTE)
        old, new = await asyncio.to_thread(_bindings, svc, data)
        password = secrets.get("imap_password")
        held = None
        if password is not None or new != old:
            held = await asyncio.to_thread(rt.secrets.status, "imap_password")
            # Refused before anything is written; see the module docstring.
            if held.source == "env":
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    _ENV_PASSWORD if password is not None else _ENV_SERVER)
        try:
            if password is not None:
                # A password saved now is for the server settings saved with it.
                data["imap_password_binding"] = new if password.strip() else ""
            elif new != old:
                # The server changed under a stored password: forget it rather
                # than send it somewhere it was never entered for.
                if held.source == "store":
                    await asyncio.to_thread(rt.secrets.delete, "imap_password")
                data["imap_password_binding"] = ""
            for name, value in secrets.items():
                if value is None:
                    continue
                await asyncio.to_thread(rt.secrets.set, name, value)
        except SecretStoreError as e:
            raise _conflict(e) from None
        if data:
            await asyncio.to_thread(svc.mail, store.merge_meta_json, MAIL_SETTINGS_KEY, data)
        # A new interval, folder list or credential applies now, not after the
        # current wait.
        _wake(request)
        await asyncio.to_thread(svc.publish_mail_changed)
        return await asyncio.to_thread(_payload, rt)

    @api.post("/mail/test/anthropic")
    async def test_mail_anthropic(request: Request):
        rt = _rt(request)
        _require_deployment(rt)
        try:
            detail = await asyncio.to_thread(rt.ingestor.llm.test_key)
        except (LlmError, SecretStoreError) as e:
            raise _conflict(e) from None
        return {"ok": True, "detail": redact(detail)}

    @api.post("/mail/test/typesafe")
    async def test_mail_typesafe(request: Request):
        rt = _rt(request)
        _require_deployment(rt)
        try:
            detail = await asyncio.to_thread(rt.ingestor.jev.test_key)
        except (JevError, SecretStoreError) as e:
            raise _conflict(e) from None
        return {"ok": True, "detail": redact(detail)}

    @api.post("/mail/test/imap")
    async def test_mail_imap(request: Request):
        rt = _rt(request)
        _require_deployment(rt)
        try:
            return await asyncio.to_thread(rt.ingestor.test_imap)
        except (MailConnectError, SecretStoreError) as e:
            raise _conflict(e) from None

    @api.get("/mail/models")
    async def get_mail_models(request: Request):
        rt = _rt(request)
        _require_deployment(rt)
        try:
            models = await asyncio.to_thread(rt.ingestor.llm.list_models)
        except (LlmError, SecretStoreError) as e:
            raise _conflict(e) from None
        return {"models": models}

    @api.get("/mail/status")
    async def get_mail_status(request: Request):
        rt = _rt(request)
        return await asyncio.to_thread(rt.ingestor.status)

    @api.post("/mail/scan", status_code=status.HTTP_202_ACCEPTED)
    async def post_mail_scan(request: Request):
        rt = _rt(request)
        _require_deployment(rt)
        cfg = await asyncio.to_thread(rt.ingestor.config)
        if not cfg.enabled:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "email ingestion is switched off in Settings")
        _wake(request)
        return {"queued": True}

    @api.get("/mail/suggestions")
    async def get_mail_suggestions(
        request: Request,
        status_: Literal["pending", "approved", "rejected", "all"] = Query("pending", alias="status"),
        limit: int = Query(100, ge=1, le=200),
    ):
        rt = _rt(request)
        svc = request.app.state.service

        def collect() -> dict:
            cfg = rt.ingestor.config()
            return {
                "enabled": cfg.enabled and rt.deployment_enabled,
                "suggestions": review.list_suggestions(
                    svc, status=None if status_ == "all" else status_, limit=limit),
                "pending_count": svc.mail(store.mail_count_suggestions, "pending"),
            }

        return await asyncio.to_thread(collect)

    @api.post("/mail/suggestions/{sid}/approve")
    async def approve_mail_suggestion(request: Request, sid: str, body: ApproveBody):
        rt = _rt(request)
        _check_sid(sid)
        svc = request.app.state.service
        fields = body.model_fields_set

        def approve() -> dict:
            return review.approve(
                svc, sid, config=rt.ingestor.config(),
                title=body.title, notes=body.notes,
                due=body.due if "due" in fields else review.UNSET_DUE,
                list_id=body.list, calendar_id=body.calendar,
            )

        try:
            return await asyncio.to_thread(approve)
        except review.ReviewError as e:
            raise HTTPException(e.status, redact(str(e))) from None

    @api.post("/mail/suggestions/{sid}/reject")
    async def reject_mail_suggestion(request: Request, sid: str):
        _rt(request)
        _check_sid(sid)
        svc = request.app.state.service
        try:
            return await asyncio.to_thread(review.reject, svc, sid)
        except review.ReviewError as e:
            raise HTTPException(e.status, redact(str(e))) from None
