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
from typing import Annotated, Literal

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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .access import AccessVerifier
from .auth import Authenticator, RateLimiter, hash_password, limiter_key
from .config import Settings, normalize_dav_url
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
    # Bounded like every other model here. Unbounded, a rejected guess could
    # still make the server hash a multi-megabyte body — and this is the one
    # route an unauthenticated caller can drive.
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


# A collection name goes onto the wire as XML text in a PROPPATCH/MKCALENDAR
# body, and lxml refuses control characters at assignment time with a bare
# ValueError — outside the DavError taxonomy, so it escaped every handler and
# came back as a 500. JSON happily carries them, and these names are routinely
# pasted from other CalDAV clients, so reject them here where the client still
# gets an answer it can act on. Length is bounded like every other model.
CollectionName = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$"),
]


class CreateList(BaseModel):
    name: CollectionName
    color: str | None = None          # #RRGGBB or #RRGGBBAA


class EditList(BaseModel):
    name: CollectionName | None = None
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


# How long a session may live, as the Settings menu offers it. An allowlist
# rather than a range: this is a security-relevant field reachable through
# PUT /api/settings, and a bounds check still lets a hand-edited blob — or an
# older client — ask for a century. "Never" is a very long TTL rather than a
# token without `exp`: an exp-less JWT is immortal, and the revocation sweep
# retires entries by their token's own expiry, so logout would leak forever.
SESSION_TTL_NEVER = 10 * 365 * 24 * 3600
_SESSION_TTLS = frozenset({24 * 3600, 7 * 24 * 3600, 30 * 24 * 3600, SESSION_TTL_NEVER})


def _check_session_ttl(ttl: int | None) -> None:
    # `bool` is an int subclass, and JSON `true` would otherwise read as 1.
    if ttl is None:
        return
    if isinstance(ttl, bool) or ttl not in _SESSION_TTLS:
        raise HTTPException(422, f"session_ttl_s must be one of {sorted(_SESSION_TTLS)}")


class EditTask(BaseModel):
    summary: str | None = None
    notes: str | None = None
    priority: str | None = None
    due: str | None = None
    start: str | None = None
    tags: list[str] | None = None
    status: str | None = None         # NEEDS-ACTION|IN-PROCESS|COMPLETED|CANCELLED
    parent: str | None = None         # parent task UID; explicit null unparents


class Sidecar(BaseModel):
    pinned: bool | None = None
    kanban_column: str | None = None
    # Non-finite floats survive JSON parsing but not JSON *serialization*, so an
    # Infinity stored here 500ed every subsequent read of the whole list — the
    # sidecar is the one thing a cache drop cannot rebuild.
    sort_order: float | None = Field(default=None, allow_inf_nan=False)
    # Bounded for the same reason sort_order is: an integer past SQLite's INTEGER
    # range raises OverflowError inside the write, which is outside the DavError
    # taxonomy every handler is built around, so it surfaced as a 500 instead of
    # a 422. A minute count has no business being astronomical anyway.
    estimated_minutes: int | None = Field(default=None, ge=0, le=100_000_000)
    repeat_from_completion: bool | None = None


class Repeat(BaseModel):
    # Structured recurrence — translated to an RFC 5545 RRULE server-side.
    repeat: str | None = None         # none|daily|weekly|monthly|yearly
    # Bounded: these go straight into an RRULE. An out-of-range INTERVAL raised
    # on the way to the wire (a 500 rather than a 422), and a zero or negative
    # COUNT wrote a rule that yields nothing — RFC 5545 requires both to be
    # positive, so refuse them here where the client still gets an answer.
    repeat_interval: int = Field(default=1, ge=1, le=1000)
    repeat_until: str | None = None   # ISO date/datetime the series ends on
    repeat_count: int | None = Field(default=None, ge=1, le=10_000)


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


class TaskGroup(BaseModel):
    # A named, ordered grouping of task lists in the sidebar. Purely a UI
    # construct — lists stay first-class CalDAV collections; the group only
    # records which list ids sit under one collapsible header. `lists` is a
    # membership set (render order still comes from the global list order).
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    lists: list[str] = Field(default_factory=list)


# ── appearance customization ────────────────────────────────────────────────
# Mirrors frontend/src/appearance.ts. The client validates too, but that guard
# is for the person typing; this one is the boundary — the stored blob is read
# back by a pre-paint script that writes straight into the CSSOM, so a value
# that gets past here reaches a stylesheet on the next page load.

_APPEARANCE_TOKENS = {
    "--bg", "--bg-elev", "--paper",
    "--fg", "--fg-muted", "--fg-faint",
    "--rule", "--rule-faint",
    "--accent", "--warn", "--ok",
    "--pri-high", "--pri-med", "--pri-low",
    "--serif", "--sans", "--mono",
    "--radius", "--fs-scale", "--gutter", "--row-y",
    "--label-case", "--tracking",
}
# url()/image() would let a stored theme beacon out to a third party on every
# load; the punctuation would let it break out of the property it is written
# into. Neither has any business in a color, length or font stack.
_TOKEN_VALUE_BAD = re.compile(
    r"url\(|image\(|expression\(|javascript:|@import|[;{}<>\\]|/\*", re.I
)
_MAX_TOKEN_VALUE = 120
_MAX_THEMES = 24
_MAX_DASHBOARD_MODULES = 40


def _clean_tokens(raw: dict[str, str]) -> dict[str, str]:
    """Drop every override that is not a known token with a safe value."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in _APPEARANCE_TOKENS or not isinstance(value, str):
            continue
        v = value.strip()
        if not v or len(v) > _MAX_TOKEN_VALUE or _TOKEN_VALUE_BAD.search(v):
            continue
        out[key] = v
    return out


class CustomTheme(BaseModel):
    # A user-authored palette. `light`/`dark` are sparse override maps — only
    # the tokens actually changed — so a theme never has to restate the design.
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    base: Literal["light", "dark"] = "light"
    light: dict[str, str] = Field(default_factory=dict)
    dark: dict[str, str] = Field(default_factory=dict)

    @field_validator("light", "dark")
    @classmethod
    def _validate_tokens(cls, v: dict[str, str]) -> dict[str, str]:
        # Filter rather than reject: a theme written by a newer client that
        # knows a token this build does not should still import what it can.
        return _clean_tokens(v)


class Appearance(BaseModel):
    # `active` is one of three things: null for the shipped Smylte design — the
    # default is not stored as a theme, it is the absence of one, which is what
    # makes reset lossless — `preset:<slug>` for a built-in theme, which is
    # shipped design resolved entirely client-side and so has no palette here
    # either, or the id of a theme in `themes` below.
    #
    # Deliberately not validated as to which. The client re-checks on read and
    # degrades an unresolvable `active` to the default, so the only thing a
    # check here would buy is rejecting a settings blob written by a newer
    # client that ships a preset this build has not heard of.
    active: str | None = Field(default=None, max_length=64)
    themes: list[CustomTheme] = Field(default_factory=list, max_length=_MAX_THEMES)


class DashboardModule(BaseModel):
    # One card on the Home tab's 12-column grid. Bounds mirror dashboard.ts;
    # they exist so a malformed layout cannot ask the client to lay out a
    # module a million rows tall.
    id: str = Field(min_length=1, max_length=64)
    kind: Literal[
        "today", "overdue", "upcoming", "mini_calendar",
        "completed", "booking_links", "bookings", "quick_add",
    ]
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0, le=200)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=40)


class SettingsPatch(BaseModel):
    # Account-synced UI preferences. Extend with new keys as settings are added.
    theme: Literal["light", "dark"] | None = None
    # Custom appearance: named themes plus which one is active. Absent means the
    # shipped design, which is never stored and so can never be edited away.
    appearance: Appearance | None = None
    # Home tab layout. An empty list is a real value (clears the arrangement
    # back to the stock one), same as the other list-valued settings below.
    dashboard: list[DashboardModule] | None = Field(
        default=None, max_length=_MAX_DASHBOARD_MODULES
    )
    # Top-nav tab strip: the order the tabs sit in, which one the app opens on
    # ("last" reopens wherever the user left off), and that remembered tab.
    # The client sanitizes the order on read — an unknown or missing entry there
    # is a display bug, not a data one — so this only bounds the blob's size.
    tab_order: list[Literal["home", "tasks", "calendar", "scheduling"]] | None = Field(
        default=None, max_length=8
    )
    start_tab: Literal["home", "tasks", "calendar", "scheduling", "last"] | None = None
    last_tab: Literal["home", "tasks", "calendar", "scheduling"] | None = None
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
    # Ids of task lists hidden from the combined "All lists" view — the tasks
    # analogue of hidden_calendars. A focused single-list view ignores this set;
    # it only filters the merged view. Empty is a real value (all lists shown).
    hidden_lists: list[str] | None = None
    # Named groupings of task lists shown in the tasks sidebar (see TaskGroup).
    # The whole array is replaced on each write; an empty list clears grouping.
    task_groups: list[TaskGroup] | None = None
    # Ids of task groups the user has collapsed in the sidebar (member lists
    # hidden from the rail until expanded). Empty means every group is expanded.
    collapsed_groups: list[str] | None = None
    # UIDs of tasks whose subtasks are folded away in the tasks view. Nesting is
    # arbitrarily deep, so this is how a large tree stays readable; empty means
    # everything is expanded. Pruned client-side against the tasks on hand.
    collapsed_tasks: list[str] | None = None
    # How long a login lasts before it has to be repeated, in seconds. Only the
    # values in _SESSION_TTLS are accepted. Absent means the deployment's own
    # TASKS_SESSION_TTL, which is what this used to be the only way to set.
    session_ttl_s: int | None = None
    # Whether completed/cancelled tasks show inline in the main tasks view.
    # Absent means the default (hidden); False is a real value the merge keeps,
    # so an explicit "show" survives. The "View completed" button ignores this.
    show_completed_tasks: bool | None = None
    # 12- or 24-hour clock for every time the app renders. Absent means "12h",
    # which is what the app did before this was settable. Only the app's own
    # displays follow it: the public booking page is rendered for visitors who
    # are not this account, so it stays on their own locale.
    time_format: Literal["12h", "24h"] | None = None


_SCOPES = ("all", "this", "thisandfuture")


def _check_scope(scope: str) -> None:
    if scope not in _SCOPES:
        raise HTTPException(422, f"scope must be one of {', '.join(_SCOPES)}")


def _check_recurrence_id(recurrence_id: str | None, scope: str) -> None:
    """A per-occurrence scope is only meaningful with an anchor to aim it at.

    The service dispatches on ``scope == "this" and recurrence_id``, so a missing
    or empty anchor falls through to the whole-resource branch: a request that
    says "delete this occurrence" would delete the *entire series*, and answer
    204. That is reachable — ``events_in_range`` falls back to the master DTO
    (``is_recurring`` true, ``recurrence_id`` null) whenever expansion fails on
    a resource another CalDAV client wrote, and the UI then offers the scope
    picker with no anchor to send.

    A non-ISO anchor is the other half: it reaches ``date.fromisoformat`` deep in
    the edit path, where the ValueError has no handler and escapes as a 500.
    Reject both here, where the client still gets a usable error.
    """
    if scope not in ("this", "thisandfuture"):
        return
    s = (recurrence_id or "").strip()
    if not s:
        raise HTTPException(422, f"recurrence_id is required for scope={scope}")
    try:
        datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)
    except ValueError:
        raise HTTPException(422, f"invalid recurrence_id: {s!r}") from None


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
    if "parent" in fs:
        kw["related_parent"] = req.parent           # explicit null unparents
    return TaskEdit(**kw)


def _event_dt(s: str | None, all_day: bool, *, required: bool = False) -> date | datetime | None:
    """Parse an event DTSTART/DTEND. ``required`` for DTSTART only: an empty or
    whitespace string is "unset" to ``_parse_datelike``, which is right for a
    cleared DTEND but not for a start — a None DTSTART reaches
    ``icalendar``'s ``add()`` and raises TypeError, which no handler maps, so the
    client sees a 500 where the all-day branch below already answers 422."""
    if s is None:
        if required:
            raise HTTPException(422, "start is required")
        return None
    if not all_day:
        dt = _parse_datelike(s)
        if dt is None and required:
            raise HTTPException(422, f"invalid date/datetime: {s!r}")
        return dt

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
    session_ttl: dict[str, int] = {"value": settings.session_ttl_s}

    def _refresh_session_ttl(stored: dict) -> None:
        """Adopt the stored session length, or fall back to the env default.

        Re-validated on the way in rather than trusted: the settings blob is a
        single JSON document that an older client, a restored backup or a hand
        edit can put anything into, and this one decides how long a login
        survives."""
        value = stored.get("session_ttl_s")
        ok = isinstance(value, int) and not isinstance(value, bool) and value in _SESSION_TTLS
        session_ttl["value"] = value if ok else settings.session_ttl_s
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
        # The session length is a setting, so the Authenticator reads it
        # through this rather than being handed a number at construction. Held
        # in memory — it is consulted on every authenticated request, and a
        # SQLite read per request to answer "how long is a session" would be a
        # poor trade. Seeded at startup, refreshed on every settings write.
        session_ttl["value"] = settings.session_ttl_s
        authenticator = Authenticator(
            user=settings.auth_user,
            password_hash=password_hash,
            secret=session_secret,
            ttl_s=lambda: session_ttl["value"],
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
        if authenticator is not None:
            # Sessions ended before this process started stay ended.
            authenticator.load_revocations(await asyncio.to_thread(svc.live_revocations))
            _refresh_session_ttl(await asyncio.to_thread(svc.get_settings))
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

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default handler echoes the offending input back in the body.
        # A non-finite float round-trips through json.loads but not json.dumps,
        # so rendering the 422 itself raised and the client got a 500 instead —
        # on a validation failure, of all things. Keep what a client can act on
        # (where it was and what was wrong) and drop the echoed value.
        return JSONResponse(
            status_code=422,
            content={"detail": [
                {"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")}
                for e in exc.errors()
            ]},
        )

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

    async def _check_parent(request: Request, href: str, parent: str | None,
                            *, uid: str | None = None) -> None:
        """Refuse a parent that names nothing in this collection.

        RELATED-TO goes onto the VTODO verbatim, so an unresolvable value is not
        a display bug a refetch repairs — it is a subtask orphaned in the
        collection for every client that reads it, ours included. That failure
        was silent, which is how it survived long enough to be reported as a UI
        bug. `_children_map` joins within one collection, so that is the scope
        the check uses."""
        if parent is None:
            return
        if uid is not None and parent == uid:
            raise HTTPException(422, "a task cannot be its own parent")
        if not await _run(_svc(request).has_task, href, parent):
            raise HTTPException(422, f"unknown parent task {parent}")

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
        # A bare Response, never JSONResponse: a 204 carries no body (RFC 9110
        # 6.4.1), and `content=None` renders b"null". uvicorn then aborts with
        # "Response content longer than Content-Length" and tears down the
        # connection, so every delete cost the client its keep-alive socket.
        # TestClient bypasses the protocol layer, which is why the suite is green
        # either way — check against a real server if you touch this.
        return Response(status_code=204)

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
        await _check_parent(request, href, body.parent)
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
        await _check_parent(request, href, body.parent, uid=uid)
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
        return Response(status_code=204)

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
        # 422 on a bad window bound. _parse_datelike reads "" as "unset", which
        # is right for an optional field but not for a required bound — the empty
        # string went straight through to the service and 500ed there.
        for name, value in (("start", start), ("end", end)):
            if _parse_datelike(value) is None:
                raise HTTPException(422, f"{name} is required (YYYY-MM-DD)")
        return await _run(_svc(request).events_in_range, href, start, end)

    @api.post("/calendars/{cal_id}/events", status_code=201)
    async def post_event(request: Request, cal_id: str, body: CreateEvent):
        href = _href(request, cal_id)
        _check_client_id(body.client_id)
        return await _run(
            _svc(request).create_event, href, body.summary,
            dtstart=_event_dt(body.start, body.all_day, required=True),
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
        _check_recurrence_id(body.recurrence_id, body.scope or "all")
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
        _check_recurrence_id(recurrence_id, scope)
        await _run(
            _svc(request).delete_event, href, uid,
            recurrence_id=recurrence_id, scope=scope,
        )
        return Response(status_code=204)

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
        return Response(status_code=204)

    @api.get("/scheduling/bookings")
    async def get_bookings(request: Request, link: str | None = Query(default=None)):
        return await _run(_svc(request).list_bookings, link)

    # -- settings (account-synced UI preferences) --
    @api.get("/settings")
    async def get_settings(request: Request):
        return await _run(_svc(request).get_settings)

    @api.put("/settings")
    async def put_settings(request: Request, body: SettingsPatch):
        _check_session_ttl(body.session_ttl_s)
        merged = await _run(_svc(request).update_settings, body.model_dump(exclude_unset=True))
        # Adopted straight away, so shortening the session takes effect on the
        # next request rather than the next restart.
        _refresh_session_ttl(merged)
        return merged

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
    # Caps concurrent password hashes. Per-app (not a module global) so tests
    # don't share it, matching the limiter instances below.
    login_hashes = asyncio.Semaphore(4)
    @app.post("/api/login")
    async def login(request: Request, body: Login):
        if authenticator is None:
            return {"authenticated": True, "user": "dev", "auth_enabled": False}
        key = limiter_key(_client_ip(request))   # IPv6 collapses to its /64
        # Reserve the attempt BEFORE the hash, not after the verdict: the hash is
        # awaited, so a read-only check would let every request that arrives
        # during it through on one credit. Same reserve-first shape the public
        # booking routes already use in _throttle.
        if not authenticator.limiter.attempt(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many attempts, try later",
                headers={"Retry-After": str(authenticator.limiter.retry_after(key))},
            )
        # scrypt is memory-hard by design (~16 MiB a call), so unbounded
        # concurrency is an unauthenticated memory amplifier — and every other
        # endpoint shares this thread pool.
        async with login_hashes:
            ok = await asyncio.to_thread(
                authenticator.check_credentials, body.username, body.password
            )
        if not ok:
            # The attempt is already recorded by attempt() above.
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        authenticator.limiter.record_success(key)
        resp = JSONResponse({"authenticated": True, "user": authenticator.user})
        resp.set_cookie(
            "tasks_session", authenticator.issue_session(),
            max_age=authenticator.ttl_s, httponly=True,
            secure=settings.cookie_secure, samesite="strict", path="/",
        )
        return resp

    @app.post("/api/logout")
    async def logout(
        request: Request,
        session: str | None = Cookie(default=None, alias="tasks_session"),
    ):
        # Clearing the cookie only asks the browser to forget the token; the
        # token itself stays valid for the rest of its TTL. Withdraw this one by
        # name so a copy of it is refused too — other devices keep their own.
        if authenticator is not None and session:
            claims = authenticator.session_claims(session)
            jti, exp = (claims or {}).get("jti"), (claims or {}).get("exp")
            if jti and exp:
                authenticator.revoke(jti, float(exp))
                await _run(_svc(request).revoke_session, jti, float(exp))
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
    #
    # It counts BOOKINGS, not requests. A booking link is meant to be published,
    # so holding the token is not evidence of anything: when every request spent
    # the budget, anyone who received the link could burn it down and — at about
    # one request a minute, within reach of a couple of addresses — keep it
    # locked out permanently, with the owner seeing nothing but 429s. Spending it
    # only on a booking that actually landed keeps the ceiling on what it was
    # written to bound (events written) and takes the denial-of-service away.
    public_post_link_limiter = RateLimiter(max_fails=30, window_s=3600, lockout_s=1800)

    def _gate(key: str, limiter: RateLimiter) -> None:
        """Refuse if the key is already locked out. Spends nothing."""
        if not limiter.allowed(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests, try later",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )

    def _throttle(key: str, limiter: RateLimiter) -> None:
        _gate(key, limiter)
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
        _gate(f"link:{token}", public_post_link_limiter)
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
        except OverflowError:
            # A syntactically valid but extreme ISO start (year 9999, year 1)
            # parses fine and only blows up in the tz conversion inside
            # book_slot. OverflowError is not a ValueError, so it escaped as a
            # 500 — on the one route an unauthenticated caller can reach.
            raise HTTPException(422, "start is out of range") from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown booking link")
        # Charged here: the booking landed on the owner's calendar.
        public_post_link_limiter.record_failure(f"link:{token}")
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

    # -- RFC 6764 CalDAV/CardDAV discovery (no auth: it precedes it) ----------
    # Raw CalDAV is published under a path (`/dav`), and a large share of DAV
    # clients cannot be pointed at one. Apple's is the sharp case: macOS and iOS
    # ask for a *Server Address*, accept a host (optionally :port) and nothing
    # else, so `radicale.example.com/dav` is simply untypeable. What they do
    # instead is probe the host root — `/.well-known/caldav` first, then bare
    # DAV verbs on `/` — and follow the redirect they expect to find there.
    # Without these routes both probes land on the SPA mount (405/404) and
    # account setup dead-ends with "cannot verify account settings".
    #
    # In production Caddy answers these before the app ever sees them (see
    # deploy/Caddyfile.snippet); these routes keep discovery working behind any
    # other proxy, and are what the tests exercise. They disclose only the DAV
    # base path, which is public deployment information — the collections behind
    # it still need Radicale credentials.
    dav_base = normalize_dav_url(settings.dav_public_url)
    # 301 per RFC 6764 §6, the code every DAV client in the wild understands;
    # `redirect_slashes` can't help here because the SPA mount at "/" swallows
    # unmatched paths, so the trailing-slash spellings are registered too.
    discovery_methods = ["GET", "HEAD", "OPTIONS", "PROPFIND", "REPORT"]

    async def dav_discovery():
        return RedirectResponse(dav_base, status_code=301)

    for _wk in ("/.well-known/caldav", "/.well-known/caldav/",
                "/.well-known/carddav", "/.well-known/carddav/"):
        app.add_api_route(
            _wk, dav_discovery, methods=discovery_methods, include_in_schema=False
        )

    # Clients that skip well-known and PROPFIND the root for DAV:current-user-
    # principal. Matching on METHOD is what keeps this off the web app: on a DAV
    # verb this route wins because it is registered ahead of the SPA mount, and
    # on GET/HEAD it is only a partial (path-but-not-method) match, which
    # Starlette discards in favour of the mount's full one.
    app.add_api_route(
        "/",
        dav_discovery,
        methods=["OPTIONS", "PROPFIND", "PROPPATCH", "REPORT"],
        include_in_schema=False,
    )

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
