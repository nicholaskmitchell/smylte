"""FastAPI application: HTTP + SSE over the service, plus the background sync loop.

Route reads are pure SQL (via the service); writes go straight through to
Radicale. The app owns one service instance (one DAV client, one SQLite conn, one
engine), created at startup and torn down at shutdown.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
from datetime import date, datetime

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
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .access import AccessVerifier
from .auth import Authenticator, hash_password
from .config import Settings
from .ical import EventEdit, TaskEdit, rrule_from_spec
from .service import TaskService, priority_from_label

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


class SettingsPatch(BaseModel):
    # Account-synced UI preferences. Extend with new keys as settings are added.
    theme: str | None = None          # 'light' | 'dark'


def _parse_datelike(s: str | None) -> date | datetime | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if "T" in s or " " in s:
        return datetime.fromisoformat(s.replace(" ", "T"))
    return date.fromisoformat(s)


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
        kw["status"] = req.status
    return TaskEdit(**kw)


def _event_dt(s: str | None, all_day: bool) -> date | datetime | None:
    if s is None:
        return None
    return date.fromisoformat(s.strip()) if all_day else _parse_datelike(s)


def _rrule_from_repeat(req: Repeat) -> dict | None:
    return rrule_from_spec(
        req.repeat,
        interval=req.repeat_interval,
        until=_parse_datelike(req.repeat_until),
        count=req.repeat_count,
    )


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
        kw["status"] = req.status
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

    async def require_auth(
        session: str | None = Cookie(default=None, alias="tasks_session"),
        cf_token: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ) -> None:
        if authenticator is not None and not authenticator.verify_session(session):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        verifier.verify(cf_token)  # optional extra layer; no-op unless access_required

    def _client_ip(request: Request) -> str:
        # Behind Cloudflare the real client is in CF-Connecting-IP; the socket peer
        # is just the tunnel. Fall back to the peer for local runs.
        return request.headers.get("CF-Connecting-IP") or (
            request.client.host if request.client else "unknown"
        )

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
        return await _run(
            _svc(request).create_task, href, body.summary,
            edit=_edit_from_create(body), parent_uid=body.parent,
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
        return await _run(_svc(request).events_in_range, href, start, end)

    @api.post("/calendars/{cal_id}/events", status_code=201)
    async def post_event(request: Request, cal_id: str, body: CreateEvent):
        href = _href(request, cal_id)
        return await _run(
            _svc(request).create_event, href, body.summary,
            dtstart=_event_dt(body.start, body.all_day),
            dtend=_event_dt(body.end, body.all_day),
            edit=_event_edit_from_create(body),
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
        dto = await _run(
            _svc(request).edit_event, href, uid, _event_edit_from_patch(body),
            recurrence_id=body.recurrence_id, scope=body.scope or "all",
        )
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
        await _run(
            _svc(request).delete_event, href, uid,
            recurrence_id=recurrence_id, scope=scope,
        )
        return JSONResponse(status_code=204, content=None)

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
        ip = _client_ip(request)
        if not authenticator.limiter.allowed(ip):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many attempts, try later",
                headers={"Retry-After": str(authenticator.limiter.retry_after(ip))},
            )
        ok = await asyncio.to_thread(
            authenticator.check_credentials, body.username, body.password
        )
        if not ok:
            authenticator.limiter.record_failure(ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        authenticator.limiter.record_success(ip)
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

    # -- internal change hook (localhost only, shared secret; NOT behind Access) --
    @app.post("/internal/changed", status_code=202)
    async def internal_changed(
        request: Request,
        secret: str | None = Header(default=None, alias="X-Tasks-Hook-Secret"),
    ):
        # Must return instantly — the Radicale hook fires this while the storage
        # is locked (spec §4). Just wake the sync loop.
        if secret != settings.hook_secret:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "bad hook secret")
        request.app.state.sync_trigger.set()
        return {"queued": True}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

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
