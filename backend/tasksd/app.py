"""FastAPI application: HTTP + SSE over the service, plus the background sync loop.

Route reads are pure SQL (via the service); writes go straight through to
Radicale. The app owns one service instance (one DAV client, one SQLite conn, one
engine), created at startup and torn down at shutdown.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import date, datetime
from typing import Literal

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .access import AccessVerifier
from .auth import Authenticator, RateLimiter, hash_password, limiter_key
from .config import Settings
from .dav.errors import AuthError as DavAuthError
from .dav.errors import DavError
from .dav.errors import NotFound as DavNotFound
from .ical import EventEdit, TaskEdit, rrule_from_spec
from .scheduling import SlotTaken
from .service import TaskService, priority_from_label
from .sync.engine import ConflictError

log = logging.getLogger("tasksd")


# ── request models ───────────────────────────────────────────────────────────

class Login(BaseModel):
    username: str
    password: str


class CreateList(BaseModel):
    name: str
    color: str | None = None          # #RRGGBB or #RRGGBBAA


class EditList(BaseModel):
    name: str | None = None
    color: str | None = None          # explicit null clears the color


class ReorderLists(BaseModel):
    ids: list[str]                    # every shown collection, in the new order


_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def _check_color(color: str | None) -> None:
    if color is not None and not _COLOR_RE.match(color):
        raise HTTPException(422, "color must be #RRGGBB or #RRGGBBAA")


class CreateTask(BaseModel):
    summary: str
    notes: str | None = None
    priority: str | None = None       # none|low|medium|high
    due: str | None = None            # ISO date or datetime
    start: str | None = None
    tags: list[str] | None = None
    parent: str | None = None         # parent task UID (subtask/checklist item)
    client_id: str | None = None      # idempotency: a replayed create reuses the slug


# The client-supplied creation id becomes the resource's href slug, so it must
# stay in Radicale's canonical URL-safe form (plain hex — see engine.create_task).
_CLIENT_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")


def _check_client_id(cid: str | None) -> None:
    if cid is not None and not _CLIENT_ID_RE.match(cid):
        raise HTTPException(422, "client_id must be 16-64 lowercase hex characters")


class EditTask(BaseModel):
    summary: str | None = None
    notes: str | None = None
    priority: str | None = None
    due: str | None = None
    start: str | None = None
    tags: list[str] | None = None
    status: str | None = None         # NEEDS-ACTION|IN-PROCESS|COMPLETED|CANCELLED


class Sidecar(BaseModel):
    pinned: bool | None = None
    kanban_column: str | None = None
    sort_order: float | None = None
    estimated_minutes: int | None = None
    repeat_from_completion: bool | None = None


class Repeat(BaseModel):
    # Structured recurrence — translated to an RFC 5545 RRULE server-side.
    repeat: str | None = None         # none|daily|weekly|monthly|yearly
    repeat_interval: int = 1          # every N periods
    repeat_until: str | None = None   # ISO date/datetime the series ends on
    repeat_count: int | None = None   # number of occurrences (exclusive with until)


class CreateEvent(Repeat):
    summary: str
    start: str                        # ISO date (all-day) or datetime
    end: str | None = None
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    client_id: str | None = None      # idempotency: a replayed create reuses the slug


class EditEvent(Repeat):
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None
    tags: list[str] | None = None
    status: str | None = None         # CONFIRMED|TENTATIVE|CANCELLED
    # Per-occurrence editing (Tier 3): which slice of a recurring series to touch.
    recurrence_id: str | None = None  # the occurrence anchor (original-slot ISO)
    scope: str | None = None          # all|this|thisandfuture (default: all)


class MoveEvent(BaseModel):
    calendar: str                     # destination calendar id


class CreateBookingLink(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    calendar: str                                     # calendar id or href
    duration_minutes: int = Field(default=30, ge=5, le=480)
    timezone: str = Field(min_length=1, max_length=64)   # IANA name
    availability: dict[str, list[str]] = Field(default_factory=dict)
    show_busy: bool = False
    buffer_minutes: int = Field(default=0, ge=0, le=240)
    min_notice_hours: int = Field(default=24, ge=0, le=720)
    horizon_days: int = Field(default=30, ge=1, le=180)
    enabled: bool = True


class EditBookingLink(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    calendar: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    availability: dict[str, list[str]] | None = None
    show_busy: bool | None = None
    buffer_minutes: int | None = Field(default=None, ge=0, le=240)
    min_notice_hours: int | None = Field(default=None, ge=0, le=720)
    horizon_days: int | None = Field(default=None, ge=1, le=180)
    enabled: bool | None = None


class PublicBook(BaseModel):
    start: str                                        # ISO datetime WITH offset
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    notes: str | None = Field(default=None, max_length=2000)
    client_id: str | None = None                      # idempotency, like event creates


# Deliberately modest — enough to catch typos without embedding RFC 5322.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SettingsPatch(BaseModel):
    # Account-synced UI preferences. Extend with new keys as settings are added.
    theme: Literal["light", "dark"] | None = None
    tasks_view: Literal["list", "day3", "week"] | None = None
    sidebar_collapsed: bool | None = None
    # Ids of calendars the user has hidden in the calendar view. Empty/absent
    # means every calendar is visible (the default) — an empty list is a real
    # value that clears the set, since the store merge only skips None.
    hidden_calendars: list[str] | None = None
    # Ids of calendars the user has archived: hidden from the calendar view but
    # NOT deleted on the wire (the collection stays intact on Radicale, so its
    # events are still viewable and it can be restored). Like hidden_calendars,
    # an empty list is a real value that clears the set.
    archived_calendars: list[str] | None = None


_SCOPES = ("all", "this", "thisandfuture")


def _check_scope(scope: str) -> None:
    if scope not in _SCOPES:
        raise HTTPException(422, f"scope must be one of {', '.join(_SCOPES)}")


# RFC 5545 STATUS vocabularies. Anything else would be written verbatim onto the
# wire and confuse other CalDAV clients, so reject it at the edge.
_TASK_STATUS = ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED")
_EVENT_STATUS = ("CONFIRMED", "TENTATIVE", "CANCELLED")


def _check_status(value: str | None, allowed: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    v = value.strip().upper()
    if v not in allowed:
        raise HTTPException(422, f"status must be one of {', '.join(allowed)}")
    return v


def _parse_datelike(s: str | None) -> date | datetime | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        if "T" in s or " " in s:
            return datetime.fromisoformat(s.replace(" ", "T"))
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(422, f"invalid date/datetime: {s!r}") from None


def _edit_from_create(req: CreateTask) -> TaskEdit | None:
    kw: dict = {}
    if req.notes is not None:
        kw["description"] = req.notes
    if req.priority is not None:
        kw["priority"] = priority_from_label(req.priority)
    if req.due is not None:
        kw["due"] = _parse_datelike(req.due)
    if req.start is not None:
        kw["dtstart"] = _parse_datelike(req.start)
    if req.tags is not None:
        kw["categories"] = req.tags
    return TaskEdit(**kw) if kw else None


def _edit_from_patch(req: EditTask) -> TaskEdit:
    fs = req.model_fields_set          # only fields the client actually sent
    kw: dict = {}
    if "summary" in fs:
        kw["summary"] = req.summary
    if "notes" in fs:
        kw["description"] = req.notes
    if "priority" in fs:
        kw["priority"] = priority_from_label(req.priority)
    if "due" in fs:
        kw["due"] = _parse_datelike(req.due)        # explicit null clears it
    if "start" in fs:
        kw["dtstart"] = _parse_datelike(req.start)
    if "tags" in fs:
        kw["categories"] = req.tags
    if "status" in fs:
        kw["status"] = _check_status(req.status, _TASK_STATUS)
    return TaskEdit(**kw)


def _event_dt(s: str | None, all_day: bool) -> date | datetime | None:
    if s is None:
        return None
    if not all_day:
        return _parse_datelike(s)
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise HTTPException(422, f"invalid date: {s!r} (all-day values are YYYY-MM-DD)") from None


def _rrule_from_repeat(req: Repeat) -> dict | None:
    try:
        return rrule_from_spec(
            req.repeat,
            interval=req.repeat_interval,
            until=_parse_datelike(req.repeat_until),
            count=req.repeat_count,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _event_edit_from_create(req: CreateEvent) -> EventEdit | None:
    kw: dict = {}
    if req.description is not None:
        kw["description"] = req.description
    if req.location is not None:
        kw["location"] = req.location
    if req.tags is not None:
        kw["categories"] = req.tags
    if req.repeat is not None:
        kw["rrule"] = _rrule_from_repeat(req)
    return EventEdit(**kw) if kw else None


def _event_edit_from_patch(req: EditEvent) -> EventEdit:
    fs = req.model_fields_set
    kw: dict = {}
    if "summary" in fs:
        kw["summary"] = req.summary
    if "description" in fs:
        kw["description"] = req.description
    if "location" in fs:
        kw["location"] = req.location
    if "start" in fs:
        kw["dtstart"] = _parse_datelike(req.start)
    if "end" in fs:
        kw["dtend"] = _parse_datelike(req.end)
    if "tags" in fs:
        kw["categories"] = req.tags
    if "status" in fs:
        kw["status"] = _check_status(req.status, _EVENT_STATUS)
    if "repeat" in fs:
        kw["rrule"] = _rrule_from_repeat(req)
    return EventEdit(**kw)


# ── background sync loop ──────────────────────────────────────────────────────

async def _sync_loop(app: FastAPI) -> None:
    svc: TaskService = app.state.service
    trigger: asyncio.Event = app.state.sync_trigger
    interval = svc.settings.sync_interval_s
    while True:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(trigger.wait(), timeout=interval)
        trigger.clear()
        try:
            await asyncio.to_thread(svc.sync_all)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("sync loop error: %s", e)


# ── app factory ───────────────────────────────────────────────────────────────

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.access_required and not (settings.access_team_domain and settings.access_aud):
        raise RuntimeError(
            "TASKS_ACCESS_REQUIRED is set but TASKS_ACCESS_TEAM_DOMAIN / TASKS_ACCESS_AUD "
            "are not configured — refusing to start unprotected."
        )
    verifier = AccessVerifier(settings)

    # Primary gate: the app's own username/password. Secure-by-default — with auth
    # enabled and no password configured, we refuse to start rather than run open.
    authenticator: Authenticator | None = None
    if settings.auth_enabled:
        password_hash = settings.auth_password_hash
        if not password_hash and settings.auth_password:
            password_hash = hash_password(settings.auth_password)
            log.warning(
                "auth: hashing TASKS_AUTH_PASSWORD (plaintext env) at startup. Prefer "
                "TASKS_AUTH_PASSWORD_HASH via `python -m tasksd hash-password` in production."
            )
        if not password_hash:
            raise RuntimeError(
                "auth enabled but no password set. Generate one with "
                "`python -m tasksd hash-password` and set TASKS_AUTH_PASSWORD_HASH "
                "(or TASKS_AUTH_PASSWORD for dev, or TASKS_AUTH_ENABLED=false to run open)."
            )
        session_secret = settings.session_secret or secrets.token_hex(32)
        if not settings.session_secret:
            log.warning(
                "auth: TASKS_SESSION_SECRET unset — using an ephemeral secret; sessions "
                "won't survive a restart. Set it in production."
            )
        elif len(settings.session_secret) < 32:
            log.warning(
                "auth: TASKS_SESSION_SECRET is under 32 bytes — use a longer random secret "
                "(e.g. `python -c 'import secrets;print(secrets.token_hex(32))'`)."
            )
        authenticator = Authenticator(
            user=settings.auth_user,
            password_hash=password_hash,
            secret=session_secret,
            ttl_s=settings.session_ttl_s,
        )
    elif not settings.access_required:
        # Deliberate dev/test posture, but loud: nothing gates /api at all.
        log.warning(
            "auth: TASKS_AUTH_ENABLED=false and TASKS_ACCESS_REQUIRED=false — "
            "the entire API is open to anyone who can reach this listener."
        )

    # The Radicale storage hook (POST /internal/changed) is gated by this secret.
    # Never accept the well-known dev default in a real deployment: fall back to an
    # ephemeral secret (fails CLOSED — the hook simply won't authenticate) rather
    # than leaving the endpoint open to anyone who knows the default.
    hook_secret = settings.hook_secret
    if not hook_secret or hook_secret == "dev-hook-secret":
        hook_secret = secrets.token_hex(32)
        log.warning(
            "hook: TASKS_HOOK_SECRET is unset or the insecure default — using an "
            "ephemeral secret; the Radicale storage hook won't authenticate until "
            "TASKS_HOOK_SECRET (and /etc/tasks/hook-secret) are set to match."
        )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = TaskService(settings)
        svc.bind_loop(asyncio.get_running_loop())
        app.state.service = svc
        app.state.sync_trigger = asyncio.Event()
        await asyncio.to_thread(svc.bootstrap)
        loop_task = asyncio.create_task(_sync_loop(app))
        try:
            yield
        finally:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
            svc.close()

    app = FastAPI(title="tasksd", version="0.1.0-phase1", lifespan=lifespan)

    # Domain exceptions → meaningful statuses. Starlette matches handlers by MRO,
    # so ConflictError/NotFound/AuthError win over the DavError catch-all.
    @app.exception_handler(ConflictError)
    async def _conflict(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(SlotTaken)
    async def _slot_taken(request: Request, exc: SlotTaken):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def _unknown_item(request: Request, exc: KeyError):
        # The engine raises KeyError for an unknown uid/collection on write paths.
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc.args[0]) if exc.args else "unknown resource"},
        )

    @app.exception_handler(DavNotFound)
    async def _dav_not_found(request: Request, exc: DavNotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DavAuthError)
    async def _dav_auth(request: Request, exc: DavAuthError):
        log.error("Radicale rejected our credentials: %s", exc)
        return JSONResponse(
            status_code=502, content={"detail": "calendar server rejected the backend credentials"}
        )

    @app.exception_handler(DavError)
    async def _dav_error(request: Request, exc: DavError):
        log.error("CalDAV error: %s", exc)
        return JSONResponse(
            status_code=502, content={"detail": "calendar server unavailable, try again shortly"}
        )

    async def require_auth(
        session: str | None = Cookie(default=None, alias="tasks_session"),
        cf_token: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ) -> None:
        if authenticator is not None and not authenticator.verify_session(session):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        verifier.verify(cf_token)  # optional extra layer; no-op unless access_required

    def _client_ip(request: Request) -> str:
        # The app binds 127.0.0.1 only (uvicorn host + host firewall), so the sole
        # socket peer is Caddy on loopback. Caddy OVERWRITES X-Real-IP with
        # Cloudflare's edge-verified CF-Connecting-IP — see deploy/Caddyfile.snippet:
        # `header_up X-Real-IP {http.request.header.CF-Connecting-IP}` — which
        # replaces any client-sent X-Real-IP, so a remote client cannot spoof it to
        # dodge the login/booking rate limiter. Trust it only when the peer is
        # loopback; otherwise fall back to the peer (defence in depth if the
        # loopback-bind invariant is ever broken).
        peer = request.client.host if request.client else "unknown"
        if peer in ("127.0.0.1", "::1"):
            real = request.headers.get("X-Real-IP")
            if real:
                return real.split(",")[0].strip()
        return peer

    api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

    def _svc(request: Request) -> TaskService:
        return request.app.state.service

    def _href(request: Request, list_id: str) -> str:
        href = _svc(request).resolve_list(list_id)
        if href is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown list {list_id}")
        return href

    async def _run(fn, *a, **kw):
        return await asyncio.to_thread(fn, *a, **kw)

    # -- lists --
    @api.get("/lists")
    async def get_lists(request: Request):
        return await _run(_svc(request).list_lists)

    @api.post("/lists", status_code=201)
    async def post_list(request: Request, body: CreateList):
        _check_color(body.color)
        return await _run(_svc(request).create_list, body.name, color=body.color)

    # -- collection management (shared by task lists and calendars) --
    @api.patch("/lists/{list_id}")
    @api.patch("/calendars/{list_id}")
    async def patch_list(request: Request, list_id: str, body: EditList):
        href = _href(request, list_id)
        fs = body.model_fields_set
        _check_color(body.color)
        return await _run(
            _svc(request).update_collection, href,
            name=body.name,
            color=body.color,
            clear_color="color" in fs and body.color is None,
        )

    @api.delete("/lists/{list_id}", status_code=204)
    @api.delete("/calendars/{list_id}", status_code=204)
    async def delete_list(request: Request, list_id: str):
        href = _href(request, list_id)
        await _run(_svc(request).delete_collection, href)
        return JSONResponse(status_code=204, content=None)

    @api.post("/lists/reorder")
    @api.post("/calendars/reorder")
    async def reorder_lists(request: Request, body: ReorderLists):
        hrefs = [_href(request, i) for i in body.ids]
        await _run(_svc(request).reorder_collections, hrefs)
        return {"ok": True}

    # -- tasks --
    @api.get("/lists/{list_id}/tasks")
    async def get_tasks(request: Request, list_id: str, include_done: bool = Query(True)):
        href = _href(request, list_id)
        return await _run(_svc(request).list_tasks, href, include_done=include_done)

    @api.post("/lists/{list_id}/tasks", status_code=201)
    async def post_task(request: Request, list_id: str, body: CreateTask):
        href = _href(request, list_id)
        _check_client_id(body.client_id)
        return await _run(
            _svc(request).create_task, href, body.summary,
            edit=_edit_from_create(body), parent_uid=body.parent,
            client_id=body.client_id,
        )

    @api.get("/lists/{list_id}/tasks/{uid}")
    async def get_one_task(request: Request, list_id: str, uid: str):
        href = _href(request, list_id)
        dto = await _run(_svc(request).get_task, href, uid)
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown task {uid}")
        return dto

    @api.patch("/lists/{list_id}/tasks/{uid}")
    async def patch_task(request: Request, list_id: str, uid: str, body: EditTask):
        href = _href(request, list_id)
        dto = await _run(_svc(request).edit_task, href, uid, _edit_from_patch(body))
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown task {uid}")
        return dto

    @api.post("/lists/{list_id}/tasks/{uid}/complete")
    async def complete_task(request: Request, list_id: str, uid: str, done: bool = Query(True)):
        href = _href(request, list_id)
        return await _run(_svc(request).complete_task, href, uid, done=done)

    @api.post("/lists/{list_id}/tasks/{uid}/cancel")
    async def cancel_task(request: Request, list_id: str, uid: str):
        href = _href(request, list_id)
        return await _run(_svc(request).cancel_task, href, uid)

    @api.delete("/lists/{list_id}/tasks/{uid}", status_code=204)
    async def delete_task(request: Request, list_id: str, uid: str):
        href = _href(request, list_id)
        await _run(_svc(request).delete_task, href, uid)
        return JSONResponse(status_code=204, content=None)

    @api.put("/lists/{list_id}/tasks/{uid}/sidecar")
    async def put_sidecar(request: Request, list_id: str, uid: str, body: Sidecar):
        href = _href(request, list_id)
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        return await _run(_svc(request).set_sidecar, href, uid, **fields)

    # -- calendars / events --
    @api.get("/calendars")
    async def get_calendars(request: Request):
        return await _run(_svc(request).list_calendars)

    @api.post("/calendars", status_code=201)
    async def post_calendar(request: Request, body: CreateList):
        _check_color(body.color)
        return await _run(_svc(request).create_calendar, body.name, color=body.color)

    @api.get("/calendars/{cal_id}/events")
    async def get_events(request: Request, cal_id: str,
                         start: str = Query(...), end: str = Query(...)):
        href = _href(request, cal_id)
        _parse_datelike(start), _parse_datelike(end)   # 422 on a bad window bound
        return await _run(_svc(request).events_in_range, href, start, end)

    @api.post("/calendars/{cal_id}/events", status_code=201)
    async def post_event(request: Request, cal_id: str, body: CreateEvent):
        href = _href(request, cal_id)
        _check_client_id(body.client_id)
        return await _run(
            _svc(request).create_event, href, body.summary,
            dtstart=_event_dt(body.start, body.all_day),
            dtend=_event_dt(body.end, body.all_day),
            edit=_event_edit_from_create(body),
            client_id=body.client_id,
        )

    @api.get("/calendars/{cal_id}/events/{uid}")
    async def get_one_event(request: Request, cal_id: str, uid: str):
        href = _href(request, cal_id)
        dto = await _run(_svc(request).get_event, href, uid)
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown event {uid}")
        return dto

    @api.patch("/calendars/{cal_id}/events/{uid}")
    async def patch_event(request: Request, cal_id: str, uid: str, body: EditEvent):
        href = _href(request, cal_id)
        _check_scope(body.scope or "all")
        try:
            dto = await _run(
                _svc(request).edit_event, href, uid, _event_edit_from_patch(body),
                recurrence_id=body.recurrence_id, scope=body.scope or "all",
            )
        except ValueError as e:
            # e.g. a series shift that would switch all-day <-> timed
            raise HTTPException(422, str(e)) from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown event {uid}")
        return dto

    @api.post("/calendars/{cal_id}/events/{uid}/move")
    async def move_event(request: Request, cal_id: str, uid: str, body: MoveEvent):
        src = _href(request, cal_id)
        dst = _href(request, body.calendar)
        dto = await _run(_svc(request).move_event, src, dst, uid)
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown event {uid}")
        return dto

    @api.delete("/calendars/{cal_id}/events/{uid}", status_code=204)
    async def delete_event(
        request: Request, cal_id: str, uid: str,
        recurrence_id: str | None = Query(default=None),
        scope: str = Query(default="all"),   # all|this|thisandfuture
    ):
        href = _href(request, cal_id)
        _check_scope(scope)
        await _run(
            _svc(request).delete_event, href, uid,
            recurrence_id=recurrence_id, scope=scope,
        )
        return JSONResponse(status_code=204, content=None)

    # -- scheduling (booking links; owner side) --
    _LINK_SIMPLE_FIELDS = ("title", "description", "duration_minutes", "timezone",
                           "availability", "show_busy", "buffer_minutes",
                           "min_notice_hours", "horizon_days", "enabled")

    @api.get("/scheduling/links")
    async def get_booking_links(request: Request):
        return await _run(_svc(request).list_booking_links)

    @api.post("/scheduling/links", status_code=201)
    async def post_booking_link(request: Request, body: CreateBookingLink):
        fields = {k: getattr(body, k) for k in _LINK_SIMPLE_FIELDS}
        fields["calendar_href"] = _href(request, body.calendar)
        try:
            return await _run(_svc(request).create_booking_link, fields)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.patch("/scheduling/links/{token}")
    async def patch_booking_link(request: Request, token: str, body: EditBookingLink):
        fs = body.model_fields_set          # only fields the client actually sent
        fields = {k: getattr(body, k) for k in _LINK_SIMPLE_FIELDS if k in fs}
        if "calendar" in fs:
            fields["calendar_href"] = _href(request, body.calendar)
        try:
            dto = await _run(_svc(request).update_booking_link, token, fields)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown booking link {token}")
        return dto

    @api.delete("/scheduling/links/{token}", status_code=204)
    async def delete_booking_link(request: Request, token: str):
        if not await _run(_svc(request).delete_booking_link, token):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown booking link {token}")
        return JSONResponse(status_code=204, content=None)

    @api.get("/scheduling/bookings")
    async def get_bookings(request: Request, link: str | None = Query(default=None)):
        return await _run(_svc(request).list_bookings, link)

    # -- settings (account-synced UI preferences) --
    @api.get("/settings")
    async def get_settings(request: Request):
        return await _run(_svc(request).get_settings)

    @api.put("/settings")
    async def put_settings(request: Request, body: SettingsPatch):
        return await _run(_svc(request).update_settings, body.model_dump(exclude_unset=True))

    # -- tags / search / sync --
    @api.get("/tags")
    async def get_tags(request: Request):
        return await _run(_svc(request).all_tags)

    @api.get("/search")
    async def search(request: Request, q: str = Query(min_length=1)):
        return await _run(_svc(request).search, q)

    @api.post("/sync")
    async def manual_sync(request: Request):
        stats = await _run(_svc(request).sync_all)
        return [{"list": s.collection_href, "upserted": s.upserted, "removed": s.removed,
                 "full_resync": s.full_resync} for s in stats]

    # -- live updates (SSE) --
    @api.get("/events")
    async def events(request: Request):
        svc = _svc(request)
        queue = svc.subscribe()

        async def gen():
            try:
                yield "retry: 3000\n\n"
                yield f"data: {json.dumps({'type': 'hello'})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                svc.unsubscribe(queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(api)

    # -- auth (login/logout/me are deliberately NOT behind require_auth) --
    @app.post("/api/login")
    async def login(request: Request, body: Login):
        if authenticator is None:
            return {"authenticated": True, "user": "dev", "auth_enabled": False}
        key = limiter_key(_client_ip(request))   # IPv6 collapses to its /64
        if not authenticator.limiter.allowed(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many attempts, try later",
                headers={"Retry-After": str(authenticator.limiter.retry_after(key))},
            )
        ok = await asyncio.to_thread(
            authenticator.check_credentials, body.username, body.password
        )
        if not ok:
            authenticator.limiter.record_failure(key)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        authenticator.limiter.record_success(key)
        resp = JSONResponse({"authenticated": True, "user": authenticator.user})
        resp.set_cookie(
            "tasks_session", authenticator.issue_session(),
            max_age=settings.session_ttl_s, httponly=True,
            secure=settings.cookie_secure, samesite="strict", path="/",
        )
        return resp

    @app.post("/api/logout")
    async def logout():
        resp = JSONResponse({"authenticated": False})
        resp.delete_cookie("tasks_session", path="/")
        return resp

    @app.get("/api/me")
    async def me(session: str | None = Cookie(default=None, alias="tasks_session")):
        if authenticator is None:
            return {"authenticated": True, "user": "dev", "auth_enabled": False}
        if not authenticator.verify_session(session):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
        return {"authenticated": True, "user": authenticator.user, "auth_enabled": True}

    # -- public booking pages (token-gated, deliberately NOT behind require_auth) --
    #
    # The token is the whole secret (token_urlsafe(16) = 128 bits — enumeration
    # is infeasible), and unknown vs disabled links are indistinguishable 404s.
    # Per-app limiter instances (not module globals) so tests don't share state.
    public_get_limiter = RateLimiter(max_fails=120, window_s=300, lockout_s=300)
    public_post_limiter = RateLimiter(max_fails=15, window_s=3600, lockout_s=3600)
    # Second layer for the write path: a per-LINK ceiling. The per-client
    # limiter keys on the /64 (limiter_key), but an attacker with many
    # prefixes/botnet nodes gets a fresh counter each — this cap bounds the
    # total junk-event rate a single link can produce regardless of source.
    # Generous for real clients (30 bookings/h on one personal link).
    public_post_link_limiter = RateLimiter(max_fails=30, window_s=3600, lockout_s=1800)

    def _throttle(key: str, limiter: RateLimiter) -> None:
        if not limiter.allowed(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests, try later",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )
        limiter.record_failure(key)   # every request counts: request-rate semantics

    def _public_throttle(request: Request, limiter: RateLimiter) -> None:
        _throttle(limiter_key(_client_ip(request)), limiter)

    @app.get("/api/public/booking/{token}")
    async def public_booking_info(request: Request, token: str):
        _public_throttle(request, public_get_limiter)
        info = await _run(_svc(request).public_link_info, token)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown booking link")
        return info

    @app.post("/api/public/booking/{token}/book", status_code=201)
    async def public_booking_book(request: Request, token: str, body: PublicBook):
        _public_throttle(request, public_post_limiter)
        _throttle(f"link:{token}", public_post_link_limiter)
        _check_client_id(body.client_id)
        if not _EMAIL_RE.match(body.email.strip()):
            raise HTTPException(422, "invalid email address")
        if not body.name.strip():
            raise HTTPException(422, "name is required")
        try:
            result = await _run(
                _svc(request).book_slot, token,
                start_iso=body.start, name=body.name.strip(),
                email=body.email.strip(), notes=body.notes,
                client_id=body.client_id,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown booking link")
        return result

    # -- internal change hook (localhost only, shared secret; NOT behind Access) --
    @app.post("/internal/changed", status_code=202)
    async def internal_changed(
        request: Request,
        secret: str | None = Header(default=None, alias="X-Tasks-Hook-Secret"),
    ):
        # Must return instantly — the Radicale hook fires this while the storage
        # is locked (spec §4). Just wake the sync loop. Constant-time compare so
        # the secret can't be recovered by timing the response; on bytes, since
        # compare_digest raises on non-ASCII str (a stray header byte would 500).
        if not (secret and hmac.compare_digest(secret.encode(), hook_secret.encode())):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "bad hook secret")
        request.app.state.sync_trigger.set()
        return {"queued": True}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    # -- public booking deep link: serve the SPA shell (StaticFiles only maps
    #    real paths, so /book/<token> needs an explicit route) --
    @app.get("/book/{token}")
    async def booking_spa(token: str):
        index = os.path.join(settings.static_dir, "index.html")
        if not os.path.isfile(index):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "frontend not built")
        return FileResponse(index)

    # -- static SPA (built frontend), mounted last so /api wins --
    if os.path.isdir(settings.static_dir):
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")
    else:
        @app.get("/")
        async def _no_ui():
            return JSONResponse(
                {"detail": f"frontend not built; expected {settings.static_dir}. API is at /api."}
            )

    return app


app = None  # created by uvicorn factory below


def make() -> FastAPI:
    return create_app()
