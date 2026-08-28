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
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

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
from .auth import Authenticator, HashBudget, RateLimiter, hash_password, limiter_key
from .config import Settings, normalize_dav_url
from .dav.errors import AuthError as DavAuthError
from .dav.errors import DavError
from .dav.errors import NotFound as DavNotFound
from .dav.xml import XML_SAFE_PATTERN_SCALAR, clean_color
from .ical.read import normalize_offset
from .ical import EventEdit, TaskEdit, rrule_from_spec
from .csp import CSPMiddleware, policy_for_index
from .limits import BodySizeLimitMiddleware
from .scheduling import SlotTaken
from .service import (
    TaskService, day_key, priority_from_label,
    # The weekday vocabulary, imported rather than restated. `service._WEEKDAYS`
    # is documented as the ONE place those names and Python's numbering meet, and
    # a copy of the seven strings at this edge is exactly the second mapping that
    # comment forbids — it would drift the first time one of them was touched.
    _WEEKDAYS as _WEEKDAY_NAMES,
)
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
# body, and lxml refuses what XML cannot carry at assignment time with a bare
# ValueError (or a UnicodeEncodeError) — outside the DavError taxonomy, so it
# escaped every handler and came back as a 500. JSON happily carries them, and
# these names are routinely pasted from other CalDAV clients, so reject them here
# where the client still gets an answer it can act on. Length is bounded like
# every other model.
#
# The character class is dav.xml's, not a copy: the same rule has to hold at this
# edge, in the MCP tool schemas, and in the DAV backstop, and keeping three
# hand-written copies in step is what previously let them drift.
CollectionName = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=XML_SAFE_PATTERN_SCALAR),
]

# The same rule for item text. A collection name was guarded and a task summary
# was not, so the app could write a SUMMARY its OWN read path cannot parse:
# Radicale copies item bytes verbatim into <C:calendar-data>, and one U+FFFE
# there makes the multistatus unparseable. The sharpest way in is anonymous —
# PublicBook.name and .notes become the booked event's SUMMARY and DESCRIPTION.
# No length bound here: the callers set their own, which differ per field.
XmlSafeText = Annotated[str, Field(pattern=XML_SAFE_PATTERN_SCALAR)]


class CreateList(BaseModel):
    name: CollectionName
    color: str | None = None          # #RRGGBB or #RRGGBBAA


class EditList(BaseModel):
    name: CollectionName | None = None
    color: str | None = None          # explicit null clears the color


# A reorder carries every collection, so the bound is "more lists than anyone
# has". Unbounded, one request made the server resolve AND PROPPATCH once per
# element inside the write lock — the same reason ReorderTasks.items is bounded.
_MAX_REORDER_LISTS = 1_000


class ReorderLists(BaseModel):
    # every shown collection, in the new order
    ids: list[str] = Field(max_length=_MAX_REORDER_LISTS)


# A reorder carries every task on the account, so the bound is "more tasks than
# anyone has" rather than a page size. It exists so a hand-rolled request can't
# make the server walk an unbounded list inside the write lock.
_MAX_REORDER_TASKS = 20_000


class ReorderEntry(BaseModel):
    list: str                         # the list id the task lives in
    uid: str


class ReorderTasks(BaseModel):
    """Every task the client holds, in the order it wants them.

    The whole sequence rather than the moved task alone, and across every list
    rather than one at a time. The tasks pane has no single-list mode — it is
    always the merged view — so a manual order has to be comparable between
    lists, and the client already holds every task of every list. Sending only
    the visible ones would leave a hidden list's rows carrying stale positions
    that interleave arbitrarily the moment it is shown again.

    That also makes positions plain 1..N integers: no fractional midpoints to
    exhaust, no renormalization pass, and nothing left null once a drag lands.
    """

    items: list[ReorderEntry] = Field(max_length=_MAX_REORDER_TASKS)


def _check_color(color: str | None) -> None:
    # One pattern for both directions — see dav/xml.py. The read path used to
    # have no check at all, so the app refused to WRITE what it happily read
    # back and handed to the SPA's inline styles.
    if color is not None and clean_color(color) is None:
        raise HTTPException(422, "color must be #RRGGBB or #RRGGBBAA")


class CreateTask(BaseModel):
    summary: XmlSafeText
    notes: XmlSafeText | None = None
    priority: str | None = None       # none|low|medium|high
    due: str | None = None            # ISO date or datetime
    start: str | None = None
    tags: list[XmlSafeText] | None = None
    parent: str | None = None         # parent task UID (subtask/checklist item)
    client_id: str | None = None      # idempotency: a replayed create reuses the slug


# The client-supplied creation id becomes the resource's href slug, so it must
# stay in Radicale's canonical URL-safe form (plain hex — see engine.create_task).
#
# `fullmatch`, not `match`. Python's `$` matches at end-of-string OR just before
# a trailing newline, so `re.match(r"^[0-9a-f]{16,64}$", "0"*16 + "\n")` succeeds
# — a validator whose own message says "hex characters" admitting a control byte
# into a URL path. urlsplit then strips the newline, so the two ids address one
# resource while carrying different UIDs. See the pin for where that ends up.
_CLIENT_ID_RE = re.compile(r"[0-9a-f]{16,64}")


def _check_client_id(cid: str | None) -> None:
    if cid is not None and not _CLIENT_ID_RE.fullmatch(cid):
        raise HTTPException(422, "client_id must be 16-64 lowercase hex characters")


def _check_day(day: str) -> str:
    """A day-plan path parameter, or 422.

    `service.day_key` is imported rather than restated as a route-level pattern.
    A pattern could pin the SHAPE but not the day — "2026-02-30" is exactly four
    digits, two digits, two digits, and is not a date — so the calendar check has
    to run in Python regardless, and splitting one rule across a constraint and a
    function is how the edge and the store end up disagreeing about which strings
    name the same day. This string is a primary key; it gets one definition."""
    try:
        return day_key(day)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


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
    summary: XmlSafeText | None = None
    notes: XmlSafeText | None = None
    priority: str | None = None
    due: str | None = None
    start: str | None = None
    tags: list[XmlSafeText] | None = None
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
    summary: XmlSafeText
    start: str                        # ISO date (all-day) or datetime
    end: str | None = None
    all_day: bool = False
    location: XmlSafeText | None = None
    description: XmlSafeText | None = None
    tags: list[XmlSafeText] | None = None
    # Does this event consume the owner's time — iCalendar's TRANSP, and what
    # Apple Calendar calls Busy/Free. Omitted means "no opinion", and no TRANSP
    # is written at all: the RFC's default is OPAQUE, so an omitted field and an
    # explicit `true` describe the same event, and not writing the line keeps
    # this app's own resources as terse as they have always been.
    busy: bool | None = None
    client_id: str | None = None      # idempotency: a replayed create reuses the slug


class EditEvent(Repeat):
    summary: XmlSafeText | None = None
    description: XmlSafeText | None = None
    location: XmlSafeText | None = None
    start: str | None = None
    end: str | None = None
    tags: list[XmlSafeText] | None = None
    status: str | None = None         # CONFIRMED|TENTATIVE|CANCELLED
    # TRANSP, as on `CreateEvent`. Tri-state through `model_fields_set` like
    # every other field on this model: an omitted key leaves the property
    # exactly as its author wrote it, and an explicit null removes it.
    busy: bool | None = None
    # Per-occurrence editing (Tier 3): which slice of a recurring series to touch.
    recurrence_id: str | None = None  # the occurrence anchor (original-slot ISO)
    scope: str | None = None          # all|this|thisandfuture (default: all)


class MoveEvent(BaseModel):
    calendar: str                     # destination calendar id


class CreateDayEntry(BaseModel):
    """One thing the owner is putting on a day by hand.

    `entry_id` is client-generated, like `client_id` on a task create and for
    the same reason: a POST that is retried after a dropped response has to land
    on the row the first attempt made, not beside it. The service also matches on
    the task (or the note text), so a client that generates a fresh id per
    attempt still cannot double-add.
    """

    entry_id: str = Field(min_length=1, max_length=64)
    kind: Literal["task", "note"]
    # `list` + `uid` name a task; `title` carries a note. Which pair is required
    # follows from `kind`, and the service answers 422 for the wrong shape —
    # both are Optional here only so both shapes parse.
    list: str | None = Field(default=None, max_length=512)
    uid: str | None = Field(default=None, max_length=512)
    # Bounded and XML-safe like the other free text a client sends. A day note
    # lives only in SQLite, so this is not the XML boundary CollectionName
    # defends — it is the cheap bound on what a client may store, applied at the
    # same edge as every other text field so there is one rule to remember.
    title: XmlSafeText | None = Field(default=None, max_length=2000)
    # Minutes, and NOT tri-state: there is no clear sentinel here because there
    # is nothing yet to clear — omitting it is how an entry is created without
    # one. Bounded on both sides like every other duration this app takes; see
    # PatchDayEntry.estimate_minutes for why the ceiling is not cosmetic.
    #
    # A stated estimate wins over the one the task remembers, which is what
    # `add_day_entry` does with it.
    estimate_minutes: int | None = Field(default=None, ge=0, le=1440)


class PatchDay(BaseModel):
    """What the owner says about a day. Every field tri-state: None is "not
    sent", and the falsy values are real — `committed=false` re-opens a day
    begun by mistake, and `capacity_minutes=-1` un-states a capacity."""

    # Minutes, or -1 to CLEAR. Same sentinel, same bounds and the same reasoning
    # as PatchDayEntry.estimate_minutes — one spelling for a duration wherever
    # this app takes one. 0 is a real capacity ("not working today"), which is
    # why the clear cannot borrow falsiness.
    capacity_minutes: int | None = Field(default=None, ge=-1, le=1440)
    committed: bool | None = None
    shutdown: bool | None = None
    # Bounded and XML-safe like every other free text a client sends. Longer than
    # a note because this is prose about a day rather than a line on it, and an
    # emptied one clears rather than storing "" — so "nothing written" has one
    # representation.
    reflection: XmlSafeText | None = Field(default=None, max_length=4000)


class RollEntry(BaseModel):
    """Where an entry is being moved to. A day key, validated by the route's
    `_check_day` like every other one in the path."""

    to: str = Field(min_length=1, max_length=10)


class PatchDayEntry(BaseModel):
    # Tri-state on purpose: None means "not sent", and false is a real value
    # (un-tick, un-drop). The service only writes the fields that arrive.
    done: bool | None = None
    dropped: bool | None = None
    # Same guard, same reason, as Sidecar.sort_order: a non-finite float parses
    # out of JSON but cannot be serialized back into it, so one Infinity here
    # would 500 every later read of the whole day.
    position: float | None = Field(default=None, allow_inf_nan=False)
    # Minutes, or -1 to CLEAR. Bounded on both sides and neither bound is
    # cosmetic. The ceiling is a day, because a plan is a plan for one — above
    # that it is a typo, not an intention, and an unbounded int reaches SQLite
    # as an OverflowError, which is outside the taxonomy this module maps and so
    # a 500 rather than a 422 (the rule Sidecar's own ints were given bounds
    # for). The floor is -1 exactly so the clear sentinel is the only negative
    # that can arrive; the service turns it into NULL and nothing else may.
    estimate_minutes: int | None = Field(default=None, ge=-1, le=1440)


# A habit's `days`: "" (every day) or a comma list of mon,tue,wed,thu,fri,sat,sun.
# The bound is a shape bound only — the VOCABULARY is checked by
# `service.normalize_habit_days`, which also normalises the order and refuses an
# rrule-shaped value by name. That check is not restated as a route-level pattern
# for the reason `_check_day` gives: one rule, one place, or the edge and the
# store end up disagreeing about which strings mean the same schedule.
# Loose rather than exact: the canonical spelling of all seven days is 27
# characters, but `normalize_habit_days` also accepts the same list written with
# spaces and capitals ("Mon, Tue, …"), and a client sending that should get the
# service's own message about the vocabulary rather than a length error about a
# value it is allowed to write.
_HABIT_DAYS_MAX = 64


class CreateHabit(BaseModel):
    """A rule that puts an entry on every day it schedules.

    Bounded and XML-safe like the other free text a client sends. A habit lives
    only in SQLite and never reaches the wire — no PUT, no RRULE — so this is not
    the XML boundary CollectionName defends; it is the same cheap bound applied
    at the same edge as every other text field, so there is one rule to remember.
    The title is COPIED onto each occurrence, which is what makes it worth
    bounding here rather than once it is already in a day.
    """

    title: XmlSafeText = Field(min_length=1, max_length=200)
    days: str = Field(default="", max_length=_HABIT_DAYS_MAX)
    # Same guard, same reason, as Sidecar.sort_order: a non-finite float parses
    # out of JSON but cannot be serialized back into it, so one Infinity here
    # would 500 every later read of the habits list.
    position: float | None = Field(default=None, allow_inf_nan=False)
    # How long one run of this takes, copied onto every occurrence at mint time
    # like the title.
    #
    # `ge=0` and NOT the -1 clear sentinel `EditHabit` takes, for the reason
    # `CreateDayEntry.estimate_minutes` gives: there is nothing to clear on a row
    # that does not exist yet, and omitting the field is already how a habit is
    # created without an estimate. This said `ge=-1` and `create_habit` had no
    # sentinel arm to match it — the only path that advertised the clear and did
    # not implement it — so a -1 was stored VERBATIM and copied onto every
    # occurrence the rule minted, making the day's planned total negative and
    # counting the row as estimated. Refusing it at the edge is the fix; a
    # service-side swallow would leave two spellings of "no estimate" in one
    # column.
    estimate_minutes: int | None = Field(default=None, ge=0, le=1440)


class EditHabit(BaseModel):
    title: XmlSafeText | None = Field(default=None, min_length=1, max_length=200)
    days: str | None = Field(default=None, max_length=_HABIT_DAYS_MAX)
    # Tri-state on purpose, like PatchDayEntry.done: None is "not sent", and
    # false is a real value — resuming a paused habit.
    paused: bool | None = None
    position: float | None = Field(default=None, allow_inf_nan=False)
    estimate_minutes: int | None = Field(default=None, ge=-1, le=1440)


class CreateBookingLink(BaseModel):
    title: XmlSafeText = Field(min_length=1, max_length=200)
    description: XmlSafeText | None = Field(default=None, max_length=2000)
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
    title: XmlSafeText | None = Field(default=None, min_length=1, max_length=200)
    description: XmlSafeText | None = Field(default=None, max_length=2000)
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
    name: XmlSafeText = Field(min_length=1, max_length=200)
    # Guarded like name and notes: _EMAIL_RE below rejects neither U+FFFE nor a
    # control byte (it only forbids @ and whitespace), and service.book writes
    # the address verbatim into the event DESCRIPTION — so this is the same
    # anonymous poisoning path, one field over.
    email: XmlSafeText = Field(min_length=3, max_length=320)
    notes: XmlSafeText | None = Field(default=None, max_length=2000)
    client_id: str | None = None                      # idempotency, like event creates


# Deliberately modest — enough to catch typos without embedding RFC 5322.
# `fullmatch` for the same reason as `_CLIENT_ID_RE`: `\s` in the negated classes
# does not save it, because `$` allows the trailing newline to sit OUTSIDE every
# group. The caller's `.strip()` currently hides that, and a caller's cleanup is
# not a property of the validator.
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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
    #
    # "today" (the fifth tab) has to be accepted here BEFORE the frontend ships
    # it, and the ordering is not a nicety. `sanitizeTabOrder` appends any
    # shipped tab a stored blob lacks (frontend/src/tabs.ts), so the first
    # settings write from a client that knows the Today tab PUTs "today" in
    # `tab_order` whether or not the user has touched the strip. A backend that
    # 422s it does not merely drop that one field: the write is rejected whole,
    # so the theme, the dashboard layout and everything else in the same PUT are
    # lost too — the exact failure `frontend/src/dashboard.ts` (lines ~60-66)
    # records for a module height the server would not take. Backend first,
    # frontend second; the reverse order breaks settings for anyone who deploys
    # them apart.
    tab_order: list[
        Literal["home", "tasks", "calendar", "scheduling", "today"]
    ] | None = Field(default=None, max_length=8)
    start_tab: Literal[
        "home", "tasks", "calendar", "scheduling", "today", "last"
    ] | None = None
    last_tab: Literal["home", "tasks", "calendar", "scheduling", "today"] | None = None
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
    # `taskKey`s — `list\0uid` — of tasks whose subtasks are folded away in the
    # tasks view. Not bare UIDs: a CalDAV UID is unique per COLLECTION, so the
    # same one can live in two lists and each copy folds independently. Bare
    # UIDs written by older clients are still honoured on read and retire as the
    # user toggles them, so this stays a plain list of opaque strings here.
    # Nesting is arbitrarily deep, so this is how a large tree stays readable;
    # empty means everything is expanded. Pruned client-side against the tasks
    # on hand.
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
    # Ids of task lists whose tasks are drawn on the calendar grid. An ALLOWLIST,
    # unlike hidden_calendars/hidden_lists above — those are denylists so a new
    # collection shows by default, which is right for a collection the user just
    # made. Tasks on the calendar are an overlay on a view that did not have
    # them, so nothing appears until a list is opted in. Empty is the default
    # and also a real value (clears the set).
    calendar_task_lists: list[str] | None = None
    # Whether completed/cancelled tasks stay on the calendar. Absent means the
    # default (hidden), matching show_completed_tasks; False is a real value.
    calendar_show_done_tasks: bool | None = None
    # How the month grid sizes itself. "fixed" splits the pane evenly between the
    # six week rows, so a busy day collapses into "+N more" rather than
    # stretching its whole week; "dynamic" grows each row to its busiest day and
    # scrolls. Absent means dynamic, which is what the grid did before this was
    # settable.
    calendar_fit: Literal["dynamic", "fixed"] | None = None
    # The IANA zone this account authors times in. The app writes non-all-day
    # events as FLOATING local wall time (`DTSTART:20260810T090000`), which
    # names no instant on its own — something has to say which clock it was.
    # The booking busy-set used to assume the *link's* zone, a per-link
    # free-text field, so a link published in another zone read every one of the
    # owner's own events at the wrong instant and offered their busy hours as
    # free. Absent means "assume the link's zone", the old behaviour. An empty
    # string clears it (the store merge only skips None).
    home_timezone: str | None = None
    # How many minutes the owner expects to work on an ordinary day, and the
    # per-weekday exceptions. Absent means "never said", which is a real answer
    # the whole capacity feature turns on: an account that has not stated one is
    # never told it has overcommitted (see service._effective_capacity).
    #
    # The map is SPARSE and keyed by the weekday NAMES habits already use —
    # {"mon": 300, "fri": 180} — never by index. service._WEEKDAYS is documented
    # as the one place those names and Python's numbering meet, and a second
    # mapping is how "wed" comes to mean Wednesday on one path and Thursday on
    # the other. A weekday absent from the map falls through to the default; a
    # key that is not a weekday name is ignored rather than guessed at, because
    # a settings blob is hand-editable.
    #
    # Bounded at a day on both, for the reason every int here is bounded: an
    # unbounded value reaches SQLite as an OverflowError, which is outside the
    # taxonomy this module maps and so a 500 rather than a 422.
    # `ge=-1` because -1 is the CLEAR sentinel, the same one this feature uses
    # on every other surface. It is needed here specifically: `update_settings`
    # merges shallowly and skips None, so without a sentinel an owner who once
    # set a default could never get back to "never said". 0 cannot be the clear
    # — "I do not work today" is a real capacity, and the null case existing at
    # all is what stops the app inventing a working day for people.
    day_capacity_minutes: int | None = Field(default=None, ge=-1, le=1440)
    day_capacity_by_weekday: dict[str, int] | None = Field(default=None, max_length=7)

    @field_validator("day_capacity_by_weekday")
    @classmethod
    def _check_capacity_map(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        """Keep only real weekday names carrying a sane number of minutes.

        FILTERS rather than rejects, the same call `_clean_tokens` makes for
        appearance tokens and for the same reason: a blob written by a newer
        client that knows something this build does not should still import what
        it can. The alternative — 422 — would reject the whole settings PUT and
        take the theme and the dashboard layout down with it.
        """
        if v is None:
            return None
        out: dict[str, int] = {}
        for name, minutes in v.items():
            if name not in _WEEKDAY_NAMES:
                continue
            # bool is an int subclass, so JSON `true` would otherwise store as
            # one minute — the same guard `_check_session_ttl` applies.
            if isinstance(minutes, bool) or not isinstance(minutes, int):
                continue
            if 0 <= minutes <= 1440:
                out[name] = minutes
        return out

    @field_validator("home_timezone")
    @classmethod
    def _known_zone(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        try:
            ZoneInfo(v)
        except Exception:  # noqa: BLE001
            raise ValueError(f"unknown timezone {v!r}") from None
        return v


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
            return normalize_offset(datetime.fromisoformat(s.replace(" ", "T")))
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
    if req.busy is not None:
        kw["busy"] = req.busy
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
    if "busy" in fs:
        kw["busy"] = req.busy
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
            # The configured credential, not the derived hash: the plaintext dev
            # path re-hashes with a fresh salt every startup, and sessions must
            # survive an ordinary restart while dying on a real change.
            credential_id=settings.auth_password_hash or settings.auth_password,
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

    # Ahead of the router, because that is the only place it works: FastAPI
    # buffers a pydantic body before the endpoint (and therefore before the
    # login limiter and the booking throttles) ever runs. See tasksd/limits.py.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)

    # Content-Security-Policy. The script hash is derived from the index.html
    # this deployment actually serves rather than written down, so the two
    # cannot drift into a blank page — see tasksd/csp.py. Read once, here: a
    # frontend rebuild therefore needs a restart, which docs/DEPLOY.md says.
    if settings.csp_mode != "off":
        index_path = os.path.join(settings.static_dir, "index.html")
        index_html: str | None = None
        try:
            with open(index_path, encoding="utf-8") as fh:
                index_html = fh.read()
        except OSError:
            # No frontend to protect (dev, tests, API-only). The policy still
            # ships for the API and the MCP pages; it just has no script hash.
            log.info("csp: no %s; serving the policy without a script hash", index_path)
        policy = policy_for_index(index_html)
        app.add_middleware(
            CSPMiddleware, policy=policy,
            report_only=settings.csp_mode == "report-only",
        )
        log.info(
            "csp: %s — %s",
            "report-only" if settings.csp_mode == "report-only" else "enforcing",
            policy,
        )

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
        # Logged in full, answered in general terms. `_raise_for` builds every
        # DavError message from `resp.request.url` — the fully resolved INTERNAL
        # URL, carrying the Radicale origin, the account name, the collection
        # UUID and the resource slug — and this was the one DAV handler that put
        # the raw message in the response body.
        #
        # That reaches the unauthenticated booking surface: any DAV round-trip
        # inside `book_slot` that 404s (the target calendar removed by another
        # client inside the sync interval, or the just-written resource deleted
        # between the PUT and the read-back) answered an anonymous visitor with
        # the owner's internal href. It is the sibling of the already-closed
        # "409 with the owner's internal CalDAV href", which was fixed by
        # rewording one ConflictError while this route kept shipping it.
        #
        # It was a poor answer for the owner too: deleting a task on a phone and
        # then ticking it complete in a still-open tab produced a toast reading
        # `GET http://127.0.0.1:5232/testuser/9f3e…/ab12cd.ics -> 404`.
        log.info("Radicale reported a missing resource: %s", exc)
        return JSONResponse(
            status_code=404,
            content={"detail": "that item no longer exists on the calendar server"},
        )

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
        # Awaited: `verify` does its JWKS work in a thread, because PyJWT's client
        # is a synchronous urlopen with a 30 s default timeout and this is the
        # first thing every /api request touches. No-op unless access_required.
        await verifier.verify(cf_token)

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

    async def _run(fn, *a, **kw):
        return await asyncio.to_thread(fn, *a, **kw)

    async def _href(request: Request, list_id: str, *, component: str | None = None) -> str:
        # Threaded like every other service call. `resolve_list` takes the global
        # service lock, which is held across CalDAV I/O (a sync sweep, a write,
        # a PROPPATCH) for as long as the 30 s DAV timeout allows. Called
        # synchronously it blocked the EVENT LOOP rather than a worker thread,
        # so one slow Radicale froze the whole process — /healthz, /api/login,
        # the SSE keepalives and the static SPA included.
        href = await _run(_svc(request).resolve_list, list_id, component=component)
        if href is None:
            kind = {"VTODO": "list", "VEVENT": "calendar"}.get(component or "", "list")
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown {kind} {list_id}")
        return href

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
        href = await _href(request, list_id)
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
        href = await _href(request, list_id)
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
        hrefs = [await _href(request, i) for i in body.ids]
        await _run(_svc(request).reorder_collections, hrefs)
        return {"ok": True}

    # -- tasks --
    @api.get("/lists/{list_id}/tasks")
    async def get_tasks(request: Request, list_id: str, include_done: bool = Query(True)):
        href = await _href(request, list_id, component="VTODO")
        return await _run(_svc(request).list_tasks, href, include_done=include_done)

    @api.post("/lists/{list_id}/tasks", status_code=201)
    async def post_task(request: Request, list_id: str, body: CreateTask):
        href = await _href(request, list_id, component="VTODO")
        _check_client_id(body.client_id)
        await _check_parent(request, href, body.parent)
        return await _run(
            _svc(request).create_task, href, body.summary,
            edit=_edit_from_create(body), parent_uid=body.parent,
            client_id=body.client_id,
        )

    @api.get("/lists/{list_id}/tasks/{uid}")
    async def get_one_task(request: Request, list_id: str, uid: str):
        href = await _href(request, list_id, component="VTODO")
        dto = await _run(_svc(request).get_task, href, uid)
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown task {uid}")
        return dto

    @api.patch("/lists/{list_id}/tasks/{uid}")
    async def patch_task(request: Request, list_id: str, uid: str, body: EditTask):
        href = await _href(request, list_id, component="VTODO")
        await _check_parent(request, href, body.parent, uid=uid)
        dto = await _run(_svc(request).edit_task, href, uid, _edit_from_patch(body))
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown task {uid}")
        return dto

    @api.post("/lists/{list_id}/tasks/{uid}/complete")
    async def complete_task(request: Request, list_id: str, uid: str, done: bool = Query(True)):
        href = await _href(request, list_id, component="VTODO")
        return await _run(_svc(request).complete_task, href, uid, done=done)

    @api.post("/lists/{list_id}/tasks/{uid}/cancel")
    async def cancel_task(request: Request, list_id: str, uid: str):
        href = await _href(request, list_id, component="VTODO")
        return await _run(_svc(request).cancel_task, href, uid)

    @api.delete("/lists/{list_id}/tasks/{uid}", status_code=204)
    async def delete_task(request: Request, list_id: str, uid: str):
        href = await _href(request, list_id, component="VTODO")
        await _run(_svc(request).delete_task, href, uid)
        return Response(status_code=204)

    @api.post("/tasks/reorder")
    async def reorder_tasks(request: Request, body: ReorderTasks):
        # Resolved before the write rather than inside it: an unknown list id is
        # a 404 for the whole request, so a reorder never half-lands.
        svc = _svc(request)
        placed: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        hrefs: dict[str, str] = {}
        for item in body.items:
            href = hrefs.get(item.list)
            if href is None:
                # Threaded, for the reason given on `_href`: this takes the
                # global service lock, and up to _MAX_REORDER_TASKS distinct
                # list ids can reach it in one request.
                resolved = await _run(svc.resolve_list, item.list, component="VTODO")
                if resolved is None:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND, f"unknown list {item.list}")
                href = hrefs[item.list] = resolved
            key = (href, item.uid)
            # A uid repeated in the body would get two positions, the last one
            # winning — silently reordering something the user never dragged.
            if key in seen:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{item.uid} listed twice")
            seen.add(key)
            placed.append(key)
        await _run(svc.reorder_tasks, placed)
        return {"ok": True}

    @api.put("/lists/{list_id}/tasks/{uid}/sidecar")
    async def put_sidecar(request: Request, list_id: str, uid: str, body: Sidecar):
        href = await _href(request, list_id, component="VTODO")
        # Check before writing, like every sibling route. This closed two things
        # and now closes one: `store.set_sidecar` used to do INSERT OR IGNORE
        # with no referential check, so an unknown uid answered 200 with a body
        # of `null` AND left a row behind with orphaned_at IS NULL — which
        # orphan_sidecar never sets (it only fires when a *known* item is
        # deleted) and gc_orphans therefore never reclaims.
        #
        # The ROW half now belongs to the store, which carries the same EXISTS
        # guard `set_sort_orders` does — a third door (the day-plan estimate
        # write-through) passed here unguarded and that is where the guard
        # belongs. This stays for the STATUS: without it the route returns
        # `get_task`'s None as a 200 with a `null` body, where every sibling
        # 404s the same uid. test_api.py asserts both halves.
        if not await _run(_svc(request).has_task, href, uid):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown task {uid}")
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        return await _run(_svc(request).set_sidecar, href, uid, **fields)

    # -- day plan (the Today tab) --
    @api.post("/day/{day}/open")
    async def post_day_open(request: Request, day: str):
        """Open a day, building its snapshot the first time. The only route that
        BUILDS a snapshot: GET below is a pure read, so a client prefetching a
        week cannot open six days it never showed anyone, and POST
        /day/{day}/entries puts a row on a day — which is enough to make it
        report planned — without ever deriving one."""
        return await _run(_svc(request).open_day, _check_day(day), create=True)

    @api.get("/day")
    async def get_day_range(
        request: Request,
        # `from` is a Python keyword, so the parameter carries the alias the
        # contract's query string actually uses.
        from_: str = Query(..., alias="from"),
        to: str = Query(...),
    ):
        """Planned days in [from, to) — `to` EXCLUSIVE. Days that were never
        opened are absent, so an empty list means "nothing planned in there",
        and a `to` at or before `from` is an empty range rather than an error.

        The span bound is enforced by the service (`DAY_RANGE_MAX_DAYS`), whose
        ValueError lands as the 422 below; the number lives next to the query it
        protects rather than being written out again here."""
        try:
            return await _run(_svc(request).day_range, _check_day(from_), _check_day(to))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.get("/day/{day}")
    async def get_day(request: Request, day: str):
        return await _run(_svc(request).open_day, _check_day(day), create=False)

    @api.patch("/day/{day}")
    async def patch_day(request: Request, day: str, body: PatchDay):
        """What the owner says about a day, as opposed to what is on it.

        A PATCH on the DAY rather than on an entry, because none of these belong
        to any row: they are the day's own facts. Refused on a past day by the
        service, which turns that into the 422 below — a capacity is a plan and a
        shutdown is a boundary, and neither can be performed after the fact."""
        try:
            return await _run(
                _svc(request).set_day_ritual, _check_day(day),
                capacity_minutes=body.capacity_minutes, committed=body.committed,
                shutdown=body.shutdown, reflection=body.reflection,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.post("/day/{day}/entries", status_code=201)
    async def post_day_entry(request: Request, day: str, body: CreateDayEntry):
        # 422 rather than the 404 the task routes answer for an unknown list.
        # The id is a field of the BODY here, not the path: a 404 on a POST whose
        # path exists would read as "there is no such day", which is never true —
        # every well-formed day exists, planned or not.
        checked = _check_day(day)
        try:
            return await _run(
                _svc(request).add_day_entry, checked,
                entry_id=body.entry_id, kind=body.kind,
                list_id=body.list, uid=body.uid, title=body.title,
                estimate_minutes=body.estimate_minutes,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.post("/day/{day}/entries/{entry_id}/roll")
    async def post_roll_entry(request: Request, day: str, entry_id: str, body: RollEntry):
        """Move one entry to another day.

        A POST rather than a PATCH because it CREATES: the entry on the target
        day is new, and this one is stamped with where it went. Nothing moves and
        nothing is deleted — see `service.roll_entry`."""
        try:
            dto = await _run(
                _svc(request).roll_entry, _check_day(day), entry_id, _check_day(body.to))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown day entry {entry_id}")
        return dto

    @api.patch("/day/{day}/entries/{entry_id}")
    async def patch_day_entry(request: Request, day: str, entry_id: str, body: PatchDayEntry):
        try:
            dto = await _run(
                _svc(request).patch_day_entry, _check_day(day), entry_id,
                done=body.done, dropped=body.dropped, position=body.position,
                estimate_minutes=body.estimate_minutes,
            )
        except ValueError as e:
            # `done` on a TASK entry: a task's doneness is its VTODO STATUS, not
            # a column here. 422 rather than 404 — the entry exists, the field
            # does not apply to it.
            raise HTTPException(422, str(e)) from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown day entry {entry_id}")
        return dto

    # -- habits (the rules that put entries on a day) --
    #
    # A habit is app-only state and never reaches Radicale, so these four are
    # SQL under the service lock like the day-plan routes above. They are also
    # deliberately NOT under /settings: the service publishes `day_updated` for
    # each of them (App.tsx ignores `settings_updated` for its refetch bump), and
    # a habit belongs to the day plan, not to UI preferences.
    @api.get("/habits")
    async def get_habits(request: Request):
        """Every habit in position order, paused ones included — the paused ones
        are exactly what the screen that resumes them has to show."""
        return await _run(_svc(request).list_habits)

    @api.post("/habits", status_code=201)
    async def post_habit(request: Request, body: CreateHabit):
        try:
            return await _run(
                _svc(request).create_habit,
                title=body.title, days=body.days, position=body.position,
                estimate_minutes=body.estimate_minutes,
            )
        except ValueError as e:
            # An empty title, or a `days` that is not a weekday list — including
            # an rrule-shaped one, whose message names
            # docs/recurrence-findings.md rather than leaving the caller to guess
            # why "FREQ=WEEKLY;BYDAY=MO" is not a schedule this app takes.
            raise HTTPException(422, str(e)) from None

    @api.patch("/habits/{habit_id}")
    async def patch_habit(request: Request, habit_id: str, body: EditHabit):
        # An explicit null is refused rather than ignored, the same way
        # _LINK_NOT_NULL refuses one on a booking link. None is how the service
        # spells "the client did not send this field", so a null would be
        # silently dropped and the caller told its edit landed when nothing was
        # written. There is no field here a null could sensibly mean anything for:
        # "every day" is "", and resuming is paused=false.
        nulled = sorted(k for k in body.model_fields_set if getattr(body, k) is None)
        if nulled:
            raise HTTPException(
                422, f"these fields cannot be null: {', '.join(nulled)}")
        try:
            dto = await _run(
                _svc(request).update_habit, habit_id,
                title=body.title, days=body.days,
                paused=body.paused, position=body.position,
                estimate_minutes=body.estimate_minutes,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown habit {habit_id}")
        return dto

    @api.delete("/habits/{habit_id}", status_code=204)
    async def delete_habit(request: Request, habit_id: str):
        """Delete the DEFINITION. Every occurrence this habit already put on a
        day stays there, with the title it copied at the time — that is the
        record of what the owner planned, and it is not a rule's to withdraw."""
        if not await _run(_svc(request).delete_habit, habit_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown habit {habit_id}")
        return Response(status_code=204)

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
        href = await _href(request, cal_id, component="VEVENT")
        # 422 on a bad window bound. _parse_datelike reads "" as "unset", which
        # is right for an optional field but not for a required bound — the empty
        # string went straight through to the service and 500ed there.
        for name, value in (("start", start), ("end", end)):
            if _parse_datelike(value) is None:
                raise HTTPException(422, f"{name} is required (YYYY-MM-DD)")
        return await _run(_svc(request).events_in_range, href, start, end)

    @api.post("/calendars/{cal_id}/events", status_code=201)
    async def post_event(request: Request, cal_id: str, body: CreateEvent):
        href = await _href(request, cal_id, component="VEVENT")
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
        href = await _href(request, cal_id, component="VEVENT")
        dto = await _run(_svc(request).get_event, href, uid)
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown event {uid}")
        return dto

    @api.patch("/calendars/{cal_id}/events/{uid}")
    async def patch_event(request: Request, cal_id: str, uid: str, body: EditEvent):
        href = await _href(request, cal_id, component="VEVENT")
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
        except OverflowError:
            # A boundary date parses fine and only blows up in the arithmetic
            # deep in the edit path. OverflowError is not a ValueError, so it
            # escaped as a 500 — the same trap the public booking route already
            # guards. The rule writer saturates now, so this is the backstop for
            # any other date arithmetic that reaches the edge.
            raise HTTPException(422, "date is out of range") from None
        if dto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown event {uid}")
        return dto

    @api.post("/calendars/{cal_id}/events/{uid}/move")
    async def move_event(request: Request, cal_id: str, uid: str, body: MoveEvent):
        src = await _href(request, cal_id, component="VEVENT")
        dst = await _href(request, body.calendar, component="VEVENT")
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
        href = await _href(request, cal_id, component="VEVENT")
        _check_scope(scope)
        _check_recurrence_id(recurrence_id, scope)
        try:
            await _run(
                _svc(request).delete_event, href, uid,
                recurrence_id=recurrence_id, scope=scope,
            )
        except ValueError as e:
            # The same mapping `patch_event` has, and for the same reasons — the
            # scoped delete reaches `split_series`, which now refuses an anchor
            # that names no occurrence. Without this the refusal escaped as a 500
            # where the sibling route answers a clean 422.
            raise HTTPException(422, str(e)) from None
        return Response(status_code=204)

    # -- scheduling (booking links; owner side) --
    _LINK_SIMPLE_FIELDS = ("title", "description", "duration_minutes", "timezone",
                           "availability", "show_busy", "buffer_minutes",
                           "min_notice_hours", "horizon_days", "enabled")

    # Every EditBookingLink field is Optional so it can be OMITTED, which makes an
    # explicit `null` indistinguishable from "leave alone" by type — only
    # `model_fields_set` tells them apart. These columns are NOT NULL, so a sent
    # null reached SQLite as an IntegrityError, which no handler maps: a 500, with
    # the fields updated before it already committed. (`description` is nullable;
    # `timezone`/`availability` already answer 422 from _normalize_link_fields;
    # `show_busy`/`enabled` coerce to 0.)
    _LINK_NOT_NULL = ("title", "duration_minutes", "buffer_minutes",
                      "min_notice_hours", "horizon_days")

    @api.get("/scheduling/links")
    async def get_booking_links(request: Request):
        return await _run(_svc(request).list_booking_links)

    @api.post("/scheduling/links", status_code=201)
    async def post_booking_link(request: Request, body: CreateBookingLink):
        fields = {k: getattr(body, k) for k in _LINK_SIMPLE_FIELDS}
        fields["calendar_href"] = await _href(request, body.calendar)
        try:
            return await _run(_svc(request).create_booking_link, fields)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @api.patch("/scheduling/links/{token}")
    async def patch_booking_link(request: Request, token: str, body: EditBookingLink):
        fs = body.model_fields_set          # only fields the client actually sent
        fields = {k: getattr(body, k) for k in _LINK_SIMPLE_FIELDS if k in fs}
        nulled = [k for k in _LINK_NOT_NULL if k in fields and fields[k] is None]
        if nulled:
            raise HTTPException(
                422, f"these fields cannot be null: {', '.join(sorted(nulled))}")
        if "calendar" in fs:
            fields["calendar_href"] = await _href(request, body.calendar)
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
    async def events(
        request: Request,
        session: str | None = Cookie(default=None, alias="tasks_session"),
    ):
        svc = _svc(request)
        queue = svc.subscribe()

        def still_authorised() -> bool:
            # require_auth ran once, at connect. This stream then outlives every
            # later check: POST /api/logout is the only thing that makes a stolen
            # cookie stop working, and it never reached a connection already open,
            # so a revoked session kept receiving every create/update/delete for
            # as long as it held the socket. The keepalive already wakes this loop
            # every 15s, so re-checking here retires a revoked — or simply expired
            # — stream within one interval and costs one HMAC verify.
            return authenticator is None or authenticator.session_claims(session) is not None

        async def gen():
            try:
                yield "retry: 3000\n\n"
                yield f"data: {json.dumps({'type': 'hello'})}\n\n"
                while True:
                    if await request.is_disconnected() or not still_authorised():
                        break
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if not still_authorised():
                        break
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
    # ...and caps the RATE, which the semaphore never did. `login_hashes` bounds
    # memory; `authenticator.limiter` bounds one client. Neither bounds the
    # guess budget, because the limiter's key is the caller's own address and a
    # routed /48 supplies 65 536 of them. Shared with the consent screen, which
    # runs the same hash on the same unauthenticated surface — see the semaphore
    # beside it and `HashBudget` for the sizing.
    hash_budget = HashBudget()
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
        # ...and the global budget, AFTER the per-client one. The order is
        # load-bearing: a client already over its own allowance must be turned
        # away by its own counter rather than spending from the shared pool, or
        # one address could empty the budget for everyone.
        if not hash_budget.take():
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many attempts, try later",
                headers={"Retry-After": str(hash_budget.retry_after())},
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
        # The right answer costs nothing: the budget is a GUESS budget, and the
        # owner logging in must not spend from the same pool their attacker is
        # draining. One token back, not a reset — see HashBudget.give_back.
        hash_budget.give_back()
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
        _check_client_id(body.client_id)
        if not _EMAIL_RE.fullmatch(body.email.strip()):
            raise HTTPException(422, "invalid email address")
        if not body.name.strip():
            raise HTTPException(422, "name is required")
        # Reserve the link's credit BEFORE the await, and give it back if
        # nothing landed. A read-only gate here was a check-then-act: book_slot
        # is awaited, so every request that arrived while earlier ones were
        # inside it saw a counter that had not moved, and an arbitrary number
        # passed the ceiling together simply by being sent in parallel. This is
        # the same reserve-first shape the login route uses; `release` is what
        # keeps the other half of the contract, that a request which wrote
        # nothing costs nothing.
        link_key = f"link:{token}"
        if not public_post_link_limiter.attempt(link_key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests, try later",
                headers={"Retry-After": str(public_post_link_limiter.retry_after(link_key))},
            )
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
            public_post_link_limiter.release(link_key)
            raise HTTPException(422, "start is out of range") from None
        except ValueError as e:
            public_post_link_limiter.release(link_key)
            raise HTTPException(422, str(e)) from None
        except BaseException:
            # SlotTaken (409) included: a refused booking wrote nothing, and the
            # ceiling counts events written.
            public_post_link_limiter.release(link_key)
            raise
        if result is None:
            public_post_link_limiter.release(link_key)
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown booking link")
        result, created = result
        if not created:
            # A replay: the confirmation came from the booking already on the
            # calendar, so no VEVENT was written and the budget is not spent.
            # Charging it made the replay path a denial-of-service against the
            # published link — the exact one this ceiling was rewritten to close.
            public_post_link_limiter.release(link_key)
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
    #
    # HEAD is registered explicitly, and has to be. `@app.get` builds a FastAPI
    # `APIRoute`, which registers `methods={"GET"}` and nothing else — Starlette's
    # plain `Route` derives HEAD from GET, `APIRoute` does not. So HEAD fell
    # through to the SPA mount, which looked for a file called `book/<token>`,
    # did not find one, and answered a bare JSON 404. HEAD is what link
    # checkers, mail-security scanners and chat unfurlers send FIRST, and
    # several treat a 404 as a dead link — so a live booking link got flagged or
    # stripped before any human clicked it, and the owner never heard about it.
    # Starlette drops the body for a HEAD itself; only the route has to exist.
    @app.api_route("/book/{token}", methods=["GET", "HEAD"], include_in_schema=False)
    async def booking_spa(token: str):
        index = os.path.join(settings.static_dir, "index.html")
        if not os.path.isfile(index):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "frontend not built")
        return FileResponse(index)

    # Both spellings, for the same reason the well-known routes above register
    # theirs: the SPA mount at "/" returns a FULL match for every path, so
    # Starlette hands `/book/<token>/` to the mount inside its route loop and
    # `redirect_slashes` — which only runs when the loop found nothing — never
    # executes. The mount looks for a file called `book/<token>`, does not find
    # one, and raises a bare JSON 404 that reads exactly like a dead link. The
    # SPA's own router accepts the slash (frontend/src/main.tsx), and a path
    # that looks like a folder invites one, typed by hand or added by a mail
    # client.
    app.add_api_route(
        "/book/{token}/", booking_spa, methods=["GET", "HEAD"],
        include_in_schema=False,
    )

    # -- remote MCP server + its OAuth authorization server (opt-in) --
    # Registered here, before the static mount, because that mount matches every
    # path and method — anything after it is unreachable. Off unless asked for:
    # this adds publicly reachable OAuth endpoints, and a deploy should never
    # grow an auth surface on its own.
    if settings.mcp_enabled:
        if not settings.public_url:
            raise RuntimeError(
                "TASKS_MCP_ENABLED is set but TASKS_PUBLIC_URL is not. The OAuth "
                "metadata has to state this deployment's absolute URL (e.g. "
                "https://tasks.example.com) and it cannot be read off the Host "
                "header, which the caller controls — refusing to start."
            )
        if authenticator is None:
            raise RuntimeError(
                "TASKS_MCP_ENABLED is set but TASKS_AUTH_ENABLED is false. The "
                "connector's consent screen is the app password — with no "
                "password there is nothing to prove you are the owner, and "
                "anyone reaching the server could mint a token. Refusing to start."
            )
        if not settings.session_secret:
            raise RuntimeError(
                "TASKS_MCP_ENABLED is set but TASKS_SESSION_SECRET is not. "
                "Consent requests are signed with a key derived from it; an "
                "ephemeral one would invalidate every in-flight connection on "
                "restart. Refusing to start."
            )
        from .mcp.routes import register as _register_mcp
        # `login_hashes` is shared, not duplicated: the consent POST runs the
        # same memory-hard scrypt as /api/login, and what the bound protects is
        # this process's memory rather than either endpoint's throughput.
        _register_mcp(app, settings=settings, authenticator=authenticator,
                      client_ip=_client_ip, run=_run, login_hashes=login_hashes,
                      hash_budget=hash_budget)
        log.info("mcp: remote connector enabled at %s/mcp", settings.public_url)

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
