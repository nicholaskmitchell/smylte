"""Application service: the seam between HTTP routes and the Phase-0 engine.

Owns exactly one DavClient + one SQLite connection + one SyncEngine, and
serializes every access behind a re-entrant lock — the app is single-user and
co-located, so a global lock is simpler and safer than a connection pool. Routes
call these methods via ``asyncio.to_thread`` so the event loop never blocks on
DAV or SQLite I/O.

Reads are always SQL against the cache (spec §4 — never calendar-query at request
time). Writes go through the engine (straight to Radicale, then cache refresh).
A tiny pub/sub pushes "changed" events to SSE subscribers after any mutation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import scheduling
from .config import Settings
from .dav import xml as davxml
from .dav.client import DavClient
from .dav.errors import NotFound as DavNotFound
from .db import store
from .display import frame as display_frame_mod
from .display import render as display_render
from .ical import PRIORITY, UNSET, EventEdit, TaskEdit, blocks_time, recur
from .sync import SyncEngine, SyncStats

log = logging.getLogger("tasksd.service")

# Reverse of ical.PRIORITY, bucketed to four levels (RFC 5545: 1 highest, 9 lowest).
_PRIORITY_LABEL = {0: "none", 1: "high", 5: "medium", 9: "low"}


def _priority_label(value: int | None) -> str:
    if not value:
        return "none"
    if value <= 4:
        return "high"
    if value <= 6:
        return "medium"
    return "low"


def _slug(href: str) -> str:
    return href.rstrip("/").rsplit("/", 1)[-1]


def _parse_window(s: str) -> date | datetime:
    """A calendar range bound: bare ISO date (all-day boundary) or ISO datetime."""
    s = s.strip()
    if "T" in s or " " in s:
        return datetime.fromisoformat(s.replace(" ", "T"))
    return date.fromisoformat(s)


# ── day keys ─────────────────────────────────────────────────────────────────
#
# A day key is the primary key of a day plan and half of every day_plan row, so
# it has exactly one spelling: YYYY-MM-DD. The regex is not redundant with the
# parse below it — since 3.11 `date.fromisoformat` also accepts the ISO *basic*
# format and week dates, so "20260821" and "2026-W34-1" both parse and both name
# a real day. Admitting them would give the same calendar day two different
# primary keys: a plan written under one is invisible to a read under the other,
# and the "has this day been opened?" guard silently answers no, re-snapshotting
# a day the owner has already arranged.
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# How far a range read may span. Bounded because the query is a range scan the
# caller chooses the width of, and a day plan is rendered a week or a month at a
# time — 190 days is two quarters plus slack, which is more than any view asks
# for and small enough that a hand-rolled `from=0001-01-01` cannot walk the
# whole table. The bound lives HERE, beside the query it protects: the route
# repeats neither the number nor the check, it just turns `day_range`'s
# ValueError into its 422 — which is how it answers every other bad argument.
DAY_RANGE_MAX_DAYS = 190

# How far back `open_day` looks for a plan to carry unfinished work from. It has
# to be bounded — an unbounded backwards search is a full scan of day_plan — and
# a month is a judgement call rather than a derived number: past that, yesterday's
# unfinished work is not carry-over, it is archaeology, and dragging a list the
# owner has not seen since spring into today would bury the day they asked for.
_CARRY_LOOKBACK_DAYS = 30


# ── habits ───────────────────────────────────────────────────────────────────
#
# A habit is A RULE THAT INSERTS ENTRIES. Its occurrences are ordinary day_plan
# rows (kind="habit", source="habit") and there is no second ledger — nothing
# here is ever PUT to Radicale, no RRULE is written for it, and the gated
# `completions` table is not involved (docs/recurrence-findings.md). Everything
# about WHICH days a habit runs on is decided in this section.

# The seven day names, indexed by Python's `date.weekday()` — 0=Monday. This
# tuple is the ONE place the names and the numbers meet: `habit_runs_on` indexes
# straight into it with a weekday derived from the day key, and
# `normalize_habit_days` orders by `index()`. 0=Monday is not a fresh choice —
# scheduling.py already keys booking availability "0" (Monday) .. "6" (Sunday) —
# and mon..sun is the order a week is written in. A SECOND mapping anywhere (a
# dict in the route layer, a lookup in the client) is how "wed" comes to mean
# Wednesday on one path and Thursday on the other, silently, for one weekday
# only; `test_habits.py` round-trips this tuple against `weekday()` for that
# reason.
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Tokens that mean the caller handed us a RECURRENCE RULE rather than a day
# list. Refused by name, with a message that points at the design note: "every
# second Tuesday", BYDAY=MO, FREQ=WEEKLY and friends are the request that turns
# a habit into VTODO recurrence, which is GATED and is deliberately not what
# this table implements. The two-letter iCal codes are in the set for the same
# reason — MO,WE,FR is neither a weekday name nor a typo of one, and a bare
# "unknown day 'mo'" would send the reader hunting for a spelling mistake
# instead of showing them the boundary they just walked into.
_RRULE_TOKENS = frozenset({
    "rrule", "freq", "byday", "bysetpos", "interval", "until", "count", "wkst",
    "daily", "weekly", "monthly", "yearly",
    "mo", "tu", "we", "th", "fr", "sa", "su",
})

# How far into the PAST a day may be and still be given habit occurrences — on
# either path that mints them, the first snapshot and the top-up alike. See
# `_habit_minting_allowed` for why it is not zero.
_HABIT_MINT_GRACE_DAYS = 1

# How far up a RELATED-TO chain one completion may close parents.
#
# A bound rather than a recursion to the root, and it is a safety rail rather
# than a judgement about how deep a checklist should be. `RELATED-TO` is free
# text with no existence check on either side of the wire, so another client can
# write a chain of any length — or a ring — and this walk runs under the global
# service lock on the write path. The `seen` set in `_close_finished_parents`
# catches a cycle; this catches a chain long enough to be pathological without
# being one. Eight is far past any real nesting: the SPA renders a tree, but a
# checklist inside a checklist inside a checklist is already unusual.
_CLOSE_PARENT_DEPTH = 8


def normalize_habit_days(value: str | None) -> str:
    """Validate a habit's `days` and return its canonical spelling. Raises
    ValueError (routes → 422).

    "" (and None) is every day — the common case, spelled as the absence of a
    restriction rather than as all seven names, so "every day" has exactly one
    representation.

    Otherwise a comma list of the seven names from `_WEEKDAYS`, re-ordered
    mon..sun. The order is normalised because "fri,mon" and "mon,fri" are ONE
    schedule: stored verbatim they would be two strings that compare unequal, so
    a client diffing the habit it just sent against the one it got back would see
    a change that did not happen, and any future group-by-schedule would split
    one rule into two.

    A duplicate is REFUSED rather than quietly collapsed. Silently accepting
    "mon,mon" would mean the value the client sent is not the value it gets back,
    with nothing to say why — and a duplicate is far more likely a client bug
    worth reporting than an intention worth guessing at.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    parts = [p.strip().lower() for p in raw.split(",")]
    if any(c in raw for c in "=;:") or any(p in _RRULE_TOKENS for p in parts):
        raise ValueError(
            f"days is a comma list of weekday names like 'mon,wed,fri' (or '' "
            f"for every day), not a recurrence rule — got {value!r}. A habit is "
            f"a rule that inserts day-plan entries, and never an RRULE: task "
            f"recurrence is gated, see docs/recurrence-findings.md."
        )
    out: list[str] = []
    for p in parts:
        if p not in _WEEKDAYS:
            raise ValueError(
                f"unknown day {p!r}; days is a comma list of "
                f"{', '.join(_WEEKDAYS)} (or '' for every day)"
            )
        if p in out:
            raise ValueError(f"day {p!r} is listed twice in {value!r}")
        out.append(p)
    return ",".join(sorted(out, key=_WEEKDAYS.index))


def habit_runs_on(days: str, day: str) -> bool:
    """Is a habit scheduled on `days` due to run on the day key `day`?

    The weekday is derived from the DAY KEY'S OWN CHARACTERS —
    `date.fromisoformat(day).weekday()` — and never from a clock. Three
    different ideas of "now" are in play at once (the browser's, `home_timezone`,
    and the server's, which is UTC in the ordinary deployment), and asking any of
    them what day it is would let the plan for Friday be filled with Thursday's
    habits whenever two of them disagree. A day key is a string that names one
    calendar day; taking the weekday from the string is zone-free by
    construction and is the only mechanical way to keep the three in step.

    `days` is assumed canonical (`normalize_habit_days` on the way in), so the
    membership test is exact rather than fuzzy.
    """
    if not days:
        return True                 # '' is every day
    return weekday_name(day) in days.split(",")


def weekday_name(day: str) -> str:
    """The `_WEEKDAYS` name for a day key: "2026-08-21" -> "fri".

    THE SAME DERIVATION `habit_runs_on` makes, factored out rather than copied,
    because a second reader of a weekday is exactly the second mapping the
    `_WEEKDAYS` comment forbids. Off the day key's own characters and never off
    a clock: three ideas of "now" are in play (the browser's, `home_timezone`,
    the server's), and asking any of them would let Friday's capacity be looked
    up under Thursday whenever two disagree.
    """
    return _WEEKDAYS[date.fromisoformat(day).weekday()]


def day_key(value: str) -> str:
    """Validate a day key and return it. Raises ValueError (routes → 422)."""
    s = (value or "").strip()
    if not _DAY_RE.fullmatch(s):
        raise ValueError(f"day must be YYYY-MM-DD, got {value!r}")
    try:
        date.fromisoformat(s)          # catches 2026-02-30 and friends
    except ValueError:
        raise ValueError(f"{value!r} is not a real calendar date") from None
    return s


def _due_day(due: str | None, *, is_date: bool, zone: ZoneInfo | None) -> str:
    """The calendar day a cached DUE falls on IN THE OWNER'S ZONE, or "" if it
    has none.

    The zone is the whole point. `dayKey` (frontend/src/util.ts) hands a due
    value to `Date` and reads local components back, so a task cached as
    `2026-08-22T00:00:00+00:00` — what `read._iso` makes of
    `DUE:20260822T000000Z` — is Wednesday the 22nd in UTC and Tuesday the 21st
    on a screen in America/New_York. Bucketing by the string's own first ten
    characters answered 2026-08-22, so the snapshot for the 21st omitted a task
    the very same screen was listing as due today.

    So a zone-carrying value is converted before its day is taken: into
    `home_timezone` when the owner has set one, and otherwise into this
    process's local zone — `astimezone(None)` — which is the nearest thing the
    server has to the browser's.

    Two shapes are deliberately NOT converted, because converting them would
    invent an instant the wire never named:

      * a DATE-valued DUE (`items.due_is_date`) — what "due Tuesday" is on the
        wire, and what this app's own date picker writes. It is already a bare
        calendar day. `is_date` is the ROW's own flag, not a guess from the
        string's shape, so a DATE value can never be mistaken for an instant.
      * a floating datetime — naive local wall time, which `dayKey` also reads
        as-is. Its day is the day it already spells.
    """
    if not due:
        return ""
    if is_date:
        return due[:10]
    try:
        value = datetime.fromisoformat(due)
    except ValueError:
        # A cached value this cannot parse is not worth dropping the task over:
        # fall back to the ten characters, which is what every value got before
        # the conversion existed. `_iso` writes `datetime.isoformat()`, so this
        # is unreachable for anything this app cached itself.
        return due[:10]
    if value.tzinfo is None:
        return value.date().isoformat()
    # `astimezone(zone)` with zone=None converts to the process's local zone,
    # which is exactly the unset-`home_timezone` fallback — no second branch.
    return value.astimezone(zone).date().isoformat()


def _snapshot_order(row) -> tuple[str, str, str, str]:
    """The order a first snapshot lays tasks out in, within one group."""
    return (row["due"] or "", row["summary"] or "", row["collection_href"], row["uid"])


def _stamp() -> str:
    """Now, in the exact shape the schema's DEFAULT writes — strftime's
    '%Y-%m-%dT%H:%M:%fZ' is seconds with milliseconds and a literal Z, which is
    what `isoformat(timespec="milliseconds")` produces once the +00:00 is folded
    back to Z. Matching it matters because done_at and created_at end up in the
    same column family and are compared as strings: one written '…+00:00' would
    sort after every Z-stamped row regardless of when it happened."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stamp_at(moment: datetime) -> str:
    """`_stamp` for a moment already in hand — the focus clock takes `now` once
    per transition and writes the same instant into every column it touches,
    so two stamps from one call cannot disagree by a millisecond."""
    return moment.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    """The inverse of `_stamp`: an aware UTC datetime from what the column holds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _passed_list(value: Any) -> list[str]:
    """The set-aside list off its JSON column. Anything that is not a list of
    strings — a hand-edited row, a NULL from an older schema — reads as empty
    rather than raising on every read of the session."""
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [p for p in parsed if isinstance(p, str)]


def _focus_now() -> datetime:
    """The focus clock's idea of now. A seam, so a test can move the clock
    without sleeping through a pomodoro; production reads the wall clock."""
    return datetime.now(timezone.utc)


# The focus clock's defaults, and the bounds a stored value is clamped to on
# the way out. `frontend/src/focus.ts::DEFAULT_FOCUS` is a mirror of this table
# and the two have to agree, for the reason `display/frame.py::fmt_duration`
# mirrors `fmtDuration`: a client that painted "25:00" while the server started
# a phase of a different length would be one app disagreeing with itself about
# the one number on the screen. The bounds are the edge model's
# (`app.SettingsPatch`), restated here because a settings blob is hand-editable
# and a phase of zero seconds would end before it began.
FOCUS_DEFAULTS: dict[str, Any] = {
    "focus_interval_minutes": 25,
    "focus_break_minutes": 5,
    "focus_long_break_minutes": 15,
    "focus_long_break_every": 4,
    "focus_auto_continue": False,
    "focus_cap_default": False,
    "focus_chime": True,
    "focus_notify": False,
}
_FOCUS_BOUNDS: dict[str, tuple[int, int]] = {
    "focus_interval_minutes": (1, 180),
    "focus_break_minutes": (1, 60),
    "focus_long_break_minutes": (1, 120),
    "focus_long_break_every": (0, 12),
}


def focus_settings(blob: dict[str, Any]) -> dict[str, Any]:
    """The focus keys of a settings blob, every one present and sane.

    Ints are clamped to their bounds, and anything that is not an int — JSON
    `true` included, which is an int subclass and would otherwise read as one
    minute, the same trap `_effective_capacity` guards against — falls back to
    the default. A bool takes only a real bool. Pure, so the rule can be
    tested without a service behind it.
    """
    out: dict[str, Any] = {}
    for key, default in FOCUS_DEFAULTS.items():
        value = blob.get(key)
        if isinstance(default, bool):
            out[key] = value if isinstance(value, bool) else default
        elif isinstance(value, int) and not isinstance(value, bool):
            lo, hi = _FOCUS_BOUNDS[key]
            out[key] = min(hi, max(lo, value))
        else:
            out[key] = default
    return out


class TaskService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._dav = DavClient(
            settings.radicale_url,
            settings.radicale_user,
            settings.radicale_password,
            timeout=settings.request_timeout_s,
        )
        self._conn = store.connect(settings.db_path)
        store.init_db(self._conn)
        self._engine = SyncEngine(self._dav, self._conn)
        self._lock = threading.RLock()
        self._listeners: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        # Set under the lock by `close()`, read under the lock by `sync_all`.
        # See `close()` for why a flag is needed and not just an ordering fix.
        self._closed = False

    def close(self) -> None:
        """Release the DAV client and the database.

        The flag exists because closing CANNOT be ordered against a running
        sweep from the outside. The lifespan cancels the asyncio task, but
        `_sync_loop` spends its time in `await asyncio.to_thread(svc.sync_all)`
        and `concurrent.futures.Future.cancel()` fails on an already-running
        work item — so `await loop_task` returns immediately while the worker
        thread is still inside `sync_all`. `sync_all` then deliberately releases
        the lock between collections, and `close()` acquires it in one of those
        gaps.

        Before the flag, the next slice ran `store.has_collection(self._conn, …)`
        against a closed connection. That call sits OUTSIDE the per-collection
        `try/except`, so the ProgrammingError escaped `sync_all` entirely: no
        collection recorded it, the remaining collections were never swept, and
        asyncio logged "exception was never retrieved" on every restart that
        landed mid-sweep.
        """
        with self._lock:
            if self._closed:
                return                    # idempotent: teardown can run twice
            self._closed = True
            self._dav.close()
            self._conn.close()

    # ── pub/sub for SSE ──────────────────────────────────────────────────────
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def _publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        for q in list(self._listeners):
            loop.call_soon_threadsafe(q.put_nowait, event)

    # ── sync ─────────────────────────────────────────────────────────────────
    def bootstrap(self) -> None:
        """First pass at startup. Tolerant by construction.

        Every failure here used to propagate out of the FastAPI lifespan, so
        uvicorn reported a startup failure and exited: one unreachable or
        vanished collection, or a transient Radicale hiccup, took down the whole
        listener — including /healthz, /api/login, the SPA and every read path,
        all of which are pure SQLite against the already-populated cache and
        would have worked fine. `sync_all` guards exactly these two failure
        modes deliberately ("one bad collection must not stall the rest of the
        sweep"); this had neither. `_sync_loop` retries after us, so nothing is
        lost by carrying on. Startup should only ever hard-fail on
        configuration, never on the state of the CalDAV server."""
        with self._lock:
            try:
                self._engine.discover()
            except Exception as e:  # noqa: BLE001
                log.warning("discovery failed at startup: %s; serving the cache", e)
            for row in store.get_collections(self._conn):
                href = row["href"]
                try:
                    self._engine.sync(href)
                except DavNotFound:
                    continue                     # gone from under us; discover next pass
                except Exception as e:  # noqa: BLE001
                    log.warning("initial sync failed for %s: %s", href, e)
                    store.set_sync_error(self._conn, href, str(e))

    def sync_all(self) -> list[SyncStats]:
        # Lock per collection, not for the whole sweep: interactive requests
        # (which serialize on the same lock) interleave between slices instead
        # of stalling for the full background pass every poll interval.
        with self._lock:
            if self._closed:
                return []
            try:
                self._engine.discover()
                collections_changed = self._engine.last_discovery_changed
            except Exception as e:  # noqa: BLE001
                # Discovery is the sweep's FIRST network call, so an outage
                # that starts after boot used to raise out of here on every
                # pass, before the per-collection loop — the only place a
                # running app ever calls `store.set_sync_error`. Nothing was
                # recorded, `sync_health()` stayed empty, and the notifier's
                # sync_stalled rule — the one written for "everything on
                # screen looks normal and the data is simply frozen" — could
                # not fire for the commonest freeze there is. Only a restart
                # during the outage (bootstrap, which guards this call the
                # same way) ever told the owner. Falling through to the loop
                # rather than returning: each collection's own sync then
                # records its own failure, and if discovery alone is broken
                # while the collections still answer, the items keep syncing.
                log.warning("discovery failed: %s; syncing the cached collections", e)
                collections_changed = False
            hrefs = [r["href"] for r in store.get_collections(self._conn)]
        stats: list[SyncStats] = []
        for href in hrefs:
            with self._lock:
                # Re-checked EVERY slice, not just once at the top: the whole
                # point of releasing the lock between collections is that
                # something else can take it, and `close()` is the something
                # else that matters. Checked inside the lock so the answer
                # cannot go stale between the check and the query below it.
                if self._closed:
                    break
                if not store.has_collection(self._conn, href):
                    continue
                try:
                    stats.append(self._engine.sync(href))
                except DavNotFound:
                    # Deleted from under us between slices; discover next pass.
                    continue
                except Exception as e:  # noqa: BLE001 — one bad collection must
                    # not stall the rest of the sweep; record it where /api/sync
                    # and future tooling can see it and move on.
                    log.warning("sync failed for %s: %s", href, e)
                    store.set_sync_error(self._conn, href, str(e))
        # A collection appearing or vanishing is a change the SPA has to hear
        # about, and it never shows up in the item counters: discover() handles
        # it separately, and its result used to be thrown away. So a list the
        # owner deleted on their phone was purged from the projection while the
        # open tab kept rendering it — and clicking it 404'd.
        if collections_changed or any(s.upserted or s.removed for s in stats):
            self._publish({"type": "sync"})
        return stats

    # ── list queries ─────────────────────────────────────────────────────────
    def list_lists(self) -> list[dict[str, Any]]:
        # The Tasks tab shows VTODO-capable collections only; VEVENT-only
        # calendars belong to the Calendar tab (list_calendars).
        with self._lock:
            rows = store.get_collections(self._conn)
            # One counts query for the whole set, not one per collection.
            counts = store.collection_counts(self._conn)
            return [self._list_dto(r, counts) for r in rows
                    if "VTODO" in (r["components"] or "")]

    def _list_dto(self, row, counts: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
        """One list/calendar row for the client.

        `counts` is the prefetched map from `store.collection_counts` — the two
        callers that render every collection pass it so the whole sidebar costs
        one query. Omitted, this counts the one collection itself, which is what
        the single-row callers (after a create or an update) want.
        """
        comps = [c for c in (row["components"] or "").split(",") if c]
        if counts is not None:
            # A GROUP BY yields no row for a collection with no items, so a
            # missing key means zero — not "unknown", and not a reason to fall
            # back to a query, which would put the per-collection round trip
            # straight back for every empty list.
            n = counts.get(row["href"]) or store.ZERO_COUNTS
        else:
            n = store.counts_for_collection(self._conn, row["href"])
        settings_row = self._conn.execute(
            "SELECT * FROM list_settings WHERE collection_href=?", (row["href"],)
        ).fetchone()
        return {
            "id": _slug(row["href"]),
            "href": row["href"],
            "name": row["displayname"],
            "components": comps,
            "color": (settings_row["color"] if settings_row else None) or row["color"],
            "is_task_list": "VTODO" in comps,
            "is_calendar": "VEVENT" in comps,
            "open_count": n["open_count"],
            "task_count": n["task_count"],
            "event_count": n["event_count"],
            "total": n["total"],
            "folder": settings_row["folder"] if settings_row else None,
            "sort_mode": settings_row["sort_mode"] if settings_row else None,
        }

    def resolve_list(self, list_id: str, *, component: str | None = None) -> str | None:
        """Accept either a full href or the short slug; return the href.

        `component` is what the caller is about to WRITE or READ there — "VTODO"
        for the task routes, "VEVENT" for the event ones — and a collection that
        does not hold it does not resolve.

        The read side of this service has always been segregated by component:
        `list_lists` filters on VTODO, `list_calendars` on VEVENT, `get_task` and
        `get_event` on the item's own component, and `_link_busy` skips any
        collection without VEVENT — `test_api.py::test_tabs_are_separated` says
        that is deliberate. The write side had no such check: this resolver
        matched on href-or-slug alone, and it sits behind every `/api/lists/...`
        route, every `/api/calendars/...` route and both MCP resolvers. So a
        VTODO could be written into an event-only calendar, where it landed on
        Radicale, occupied a UID, and was then invisible to every reader in this
        app — `smylte_delete_list` would happily delete a calendar, too.

        `_normalize_link_fields` already did this for one caller ("calendar must
        be an existing event calendar"), so the need was recognised and applied
        once. Callers that deliberately span both kinds — collection rename,
        delete and reorder, which the SPA uses from both tabs — pass nothing and
        keep the old behaviour.
        """
        with self._lock:
            for row in store.get_collections(self._conn):
                if list_id in (row["href"], _slug(row["href"])):
                    if component and component not in (row["components"] or ""):
                        return None
                    return row["href"]
        return None

    # ── task queries ─────────────────────────────────────────────────────────
    def list_tasks(
        self, href: str, *, include_done: bool = True, include_parked: bool = True,
    ) -> list[dict[str, Any]]:
        """Every VTODO in one collection, as DTOs.

        TWO FILTERS AND NOT ONE, because they answer different questions and a
        caller usually wants a different answer to each. `include_done` is about
        work that is over; `include_parked` is about work deliberately set aside,
        which is not over and must not be reported as though it were. Both
        default to True so a reader that has not thought about it sees
        everything — the SPA fetches the lot and decides on screen, which is what
        lets it offer a "Parked" view at all.
        """
        with self._lock:
            items = [i for i in store.get_items(self._conn, href) if i["component"] == "VTODO"]
            cats = store.get_all_categories(self._conn, href)
            side = store.get_all_sidecar(self._conn, href)
        children = self._children_map(items)
        dtos = [self._task_dto(it, cats, side, children) for it in items]
        if not include_done:
            dtos = [d for d in dtos if not (d["completed"] or d["cancelled"])]
        if not include_parked:
            dtos = [d for d in dtos if not d["parked"]]
        # Manual position first, then the due-then-summary order the SQL already
        # gave. Done here rather than in the query because the sidecar is
        # already in hand, so it costs no join.
        #
        # The client sorts again on render and that is what decides what a user
        # sees — its comparator is a total order, so no arrangement here can
        # change the screen. This is for whoever reads the API directly.
        dtos.sort(key=lambda d: (
            d["sort_order"] is None,
            d["sort_order"] or 0.0,
            d["due"] is None,
            d["due"] or "",
            d["summary"] or "",
        ))
        return dtos

    @staticmethod
    def _children_map(items) -> dict[str, list]:
        children: dict[str, list] = {}
        for it in items:
            if it["related_parent"]:
                children.setdefault(it["related_parent"], []).append(it)
        return children

    def has_task(self, href: str, uid: str) -> bool:
        """Is ``uid`` a VTODO in this collection? Asked before a create names it
        as a parent — ``RELATED-TO`` is written verbatim with no existence check
        of its own, so a wrong value is not a mispaint but an orphan persisted to
        CalDAV that every client reading the collection then has to cope with."""
        with self._lock:
            row = store.get_item(self._conn, href, uid)
        return row is not None and row["component"] == "VTODO"

    def get_task(self, href: str, uid: str) -> dict[str, Any] | None:
        with self._lock:
            row = store.get_item(self._conn, href, uid)
            if row is None or row["component"] != "VTODO":
                return None
            cats = store.get_all_categories(self._conn, href)
            side = store.get_all_sidecar(self._conn, href)
            items = [i for i in store.get_items(self._conn, href) if i["component"] == "VTODO"]
        return self._task_dto(row, cats, side, self._children_map(items))

    def _task_dto(self, it, cats, side, children) -> dict[str, Any]:
        uid = it["uid"]
        kids = children.get(uid, [])
        done_kids = sum(1 for k in kids if k["status"] == "COMPLETED")
        s = side.get(uid)
        status = it["status"]
        derived = round(100 * done_kids / len(kids)) if kids else None
        return {
            "uid": uid,
            # The list's short id (same key as List.id and the SSE payloads), so
            # the combined "All lists" view can map a task back to its list for
            # color and visibility. resolve_list still accepts the full href too.
            "list": _slug(it["collection_href"]),
            "summary": it["summary"],
            "notes": it["description"],
            "status": status,
            "completed": status == "COMPLETED",
            # The VTODO COMPLETED property, not a restatement of the flag above.
            # `completed` is derived from STATUS; this is the instant the wire
            # actually records, and the two can disagree — a foreign client may
            # set STATUS:COMPLETED and write no COMPLETED at all, so a reader
            # sorting by it needs a fallback rather than assuming it is there.
            # It was cached from the first sync (schema.sql's items.completed,
            # written by read.py) and simply never surfaced, which left every
            # "recently completed" view guessing from the due date instead.
            "completed_at": it["completed"],
            "cancelled": status == "CANCELLED",
            "priority": it["priority"],
            "priority_label": _priority_label(it["priority"]),
            "percent_complete": it["percent_complete"],
            "due": it["due"],
            "due_is_date": bool(it["due_is_date"]),
            "start": it["dtstart"],
            "start_is_date": bool(it["dtstart_is_date"]),
            "tags": cats.get(uid, []),
            "parent": it["related_parent"],
            "children": [k["uid"] for k in kids],
            "child_count": len(kids),
            "completed_child_count": done_kids,
            "derived_percent": derived,
            "pinned": bool(s["pinned"]) if s else False,
            "kanban_column": s["kanban_column"] if s else None,
            "sort_order": s["sort_order"] if s else None,
            # The estimate this task REMEMBERS, and the first thing to read a
            # column that has been writable and unread since the sidecar table
            # was created ("DURATION is exclusive with DUE; keep it here").
            # It is not the estimate of any particular day: planning a task
            # copies this onto that day's entry, and the entry is what the day
            # counts. This is only what the next plan will start from.
            #
            # No migration: a database old enough to lack this column predates
            # the table it is on.
            "estimated_minutes": s["estimated_minutes"] if s else None,
            # "Notify me this many minutes before." NULL on almost everything,
            # which is what "I did not ask to be told about this one" means —
            # and what keeps the reminder rule quiet by default. See
            # notify/rules.py::_eval_item_reminder.
            "notify_minutes_before": s["notify_minutes_before"] if s else None,
            # Set aside rather than finished or abandoned. Two keys and not one,
            # for the reason `completed` and `completed_at` are two: the flag is
            # what every filter tests, and the instant is a fact the flag cannot
            # carry. See `schema.sql`'s `parked_at` for why this is app-only.
            #
            # ORTHOGONAL TO STATUS, deliberately. A parked task is still whatever
            # the wire says it is, so nothing here is derived from `status` and
            # nothing about parking changes it. Readers that mean "work I might
            # do" ask for all three; readers that mean "finished" ask only the
            # first two, and `park_task` says which is which.
            "parked": bool(s["parked_at"]) if s else False,
            "parked_at": s["parked_at"] if s else None,
            "has_rrule": bool(it["has_rrule"]),
            "href": it["href"],
            "etag": it["etag"],
            "created": it["created"],
            "last_modified": it["last_modified"],
        }

    def all_tags(self) -> list[str]:
        with self._lock:
            return store.distinct_categories(self._conn)

    def search(self, query: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [r for r in store.search(self._conn, query) if r["component"] == "VTODO"]
            by_col: dict[str, tuple] = {}
            for r in rows:
                col = r["collection_href"]
                if col not in by_col:
                    items = [i for i in store.get_items(self._conn, col)
                             if i["component"] == "VTODO"]
                    by_col[col] = (
                        store.get_all_categories(self._conn, col),
                        store.get_all_sidecar(self._conn, col),
                        items,
                        # Built ONCE per collection, alongside the three lookups
                        # it belongs with. It used to be built inside the loop
                        # below, which made the whole function O(rows x items):
                        # `store.search` has no LIMIT, so a one-character FTS
                        # query over a 5 000-task list matched every row and
                        # rebuilt the map 5 000 times — 2.87 s, holding the
                        # global lock the whole way. `_children_map` is a pure
                        # staticmethod over `items`, so the hoisted map is
                        # bit-for-bit the one each iteration was recomputing.
                        self._children_map(items),
                    )
        out = []
        for r in rows:
            cats, side, _items, children = by_col[r["collection_href"]]
            out.append(self._task_dto(r, cats, side, children))
        return out

    # ── writes ───────────────────────────────────────────────────────────────
    def create_list(self, name: str, *, color: str | None = None) -> dict[str, Any]:
        return self._create_collection(name, ("VTODO",), color=color, event="list_created")

    def create_calendar(self, name: str, *, color: str | None = None) -> dict[str, Any]:
        return self._create_collection(name, ("VEVENT",), color=color, event="calendar_created")

    def _create_collection(
        self, name: str, components: tuple[str, ...], *, color: str | None, event: str
    ) -> dict[str, Any]:
        kw = {"color": color} if color else {}
        with self._lock:
            ci = self._dav.create_task_collection(name, components=components, **kw)
            self._engine.discover()
            row = self._conn.execute(
                "SELECT * FROM collections WHERE href=?", (ci.href,)
            ).fetchone()
            dto = self._list_dto(row)
        self._publish({"type": event, "list": dto["id"]})
        return dto

    def update_collection(
        self,
        href: str,
        *,
        name: str | None = None,
        color: str | None = None,
        clear_color: bool = False,
    ) -> dict[str, Any]:
        """Rename / recolor via PROPPATCH — the wire is the source of truth, so
        other CalDAV clients (Tasks.org, Thunderbird, …) see the change too."""
        props: dict[str, str | None] = {}
        if name is not None:
            props[davxml.DISPLAYNAME] = name
        if clear_color:
            props[davxml.CALENDAR_COLOR] = None
        elif color is not None:
            props[davxml.CALENDAR_COLOR] = color
        with self._lock:
            if props:
                self._dav.proppatch(href, props)
                self._engine.discover()
            row = self._conn.execute(
                "SELECT * FROM collections WHERE href=?", (href,)
            ).fetchone()
            dto = self._list_dto(row)
        self._publish({"type": "list_updated", "list": dto["id"]})
        return dto

    def reorder_collections(self, hrefs: list[str]) -> None:
        """Persist a manual order as apple calendar-order (0-based), on the wire."""
        with self._lock:
            for i, href in enumerate(hrefs):
                self._dav.proppatch(href, {davxml.CALENDAR_ORDER: str(i)})
            self._engine.discover()
        self._publish({"type": "list_reordered"})

    def delete_collection(self, href: str) -> None:
        with self._lock:
            self._dav.delete_collection(href)
            self._engine.discover()   # marks it deleted in the cache
            # Any booking link aimed here is now unbookable. Disable it rather
            # than leaving it advertising slots on a calendar that is gone — it
            # keeps its history and can be repointed.
            disabled = store.disable_links_for_collection(self._conn, href)
        if disabled:
            log.info("disabled %d booking link(s) for deleted collection %s", disabled, href)
            self._publish({"type": "booking_link_updated", "link": ""})
        self._publish({"type": "list_deleted", "list": _slug(href)})

    def create_task(self, href: str, summary: str, *, edit: TaskEdit | None = None,
                    parent_uid: str | None = None,
                    client_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            uid = self._engine.create_task(
                href, summary, edit=edit, parent_uid=parent_uid, slug=client_id
            )
        self._publish({"type": "task_created", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

    def edit_task(self, href: str, uid: str, edit: TaskEdit) -> dict[str, Any] | None:
        with self._lock:
            self._engine.edit_task(href, uid, edit)
            closed = self._close_finished_parents(href, uid)
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        # One event per parent this edit closed, and they are needed rather than
        # tidy: the SPA reconciles a write by replacing the ROW it wrote, so
        # without these the parent stays open on screen until something else
        # forces a refetch, and the owner sees a checklist that is finished
        # under a parent that is not.
        for parent_uid in closed:
            self._publish({"type": "task_updated", "list": _slug(href), "uid": parent_uid})
        return self.get_task(href, uid)

    def _close_finished_parents(self, href: str, uid: str) -> list[str]:
        """Complete any ancestor of `uid` that has nothing left in it. Called
        under the lock; returns the uids closed, innermost first.

        A parent with every step ticked is finished, and leaving it open is how
        a list keeps items nobody can act on: there is no work left in it, only
        a row to notice and skip. Closing it is the one change here that shrinks
        the list at zero cost to the record.

        THE PREDICATE IS "NOTHING LEFT", not "everything done". Every child must
        be COMPLETED **or CANCELLED** — a step declined is a step that is not
        happening, so it leaves nothing to do either. That deliberately differs
        from `_task_dto`'s `done_kids`, which counts only COMPLETED, and the two
        answer different questions: that number is a PROGRESS percentage, where
        counting a declined step as work done would flatter it, and this one
        asks whether anything remains. (The client's `progressOf` has always
        counted cancelled children as done — a pre-existing divergence, and not
        one this widens.)

        A PARKED child blocks the close, and it does so for free rather than by
        a clause of its own: parking does not touch STATUS, so a parked child is
        still NEEDS-ACTION and fails the test above. That is the right answer —
        parking is setting aside, not settling, so the work is still intended
        and the parent is not finished — and it is worth stating precisely
        because the free version is the one that stays correct. A child that is
        both COMPLETED and parked (parking survives completion by design) is
        settled, and a clause reading the flag directly would have blocked on
        it.

        ONLY THIS PATH, never the sync engine. Another client ticking the last
        child does not close the parent here, and that is deliberate: the sync
        engine's job is to project the wire, and a projection that writes back
        turns every incoming change into an outgoing one — including on a full
        resync, where every task looks new. The owner ticking that same child in
        this app gets the close; a foreign write does not.

        It walks UP, because closing a parent can finish its own parent, and it
        is bounded twice. `_CLOSE_PARENT_DEPTH` caps the climb, and a `seen` set
        catches a cycle: `RELATED-TO` is free text with no existence check on
        either side of the wire, so a ring is something another client can write
        and this must terminate on it rather than loop under the global lock.
        """
        # Default ON — the absent key is the default, like every other setting
        # here — but `is False` rather than a truth test, because the settings
        # blob is hand-editable and a string or a number there must not be read
        # as an instruction to stop writing to the owner's calendar server.
        # Only the value the switch actually stores turns this off.
        if store.get_settings(self._conn).get("auto_close_parents") is False:
            return []
        closed: list[str] = []
        seen: set[str] = {uid}
        child = store.get_item(self._conn, href, uid)
        for _ in range(_CLOSE_PARENT_DEPTH):
            parent_uid = child["related_parent"] if child is not None else None
            if not parent_uid or parent_uid in seen:
                return closed
            seen.add(parent_uid)
            parent = store.get_item(self._conn, href, parent_uid)
            # A parent in ANOTHER list is not this parent — a UID is unique per
            # collection (invariant #4) — and `related_parent` names no list, so
            # a cross-list pointer resolves to nothing here and the climb stops.
            if parent is None or parent["component"] != "VTODO":
                return closed
            if (parent["status"] or "") in ("COMPLETED", "CANCELLED"):
                return closed      # already settled; its own parent is not ours to judge
            if not self._nothing_left_in(href, parent_uid):
                return closed
            self._engine.edit_task(href, parent_uid, TaskEdit(status="COMPLETED"))
            closed.append(parent_uid)
            # Re-read rather than reusing `parent`: the edit rewrote the row, and
            # the climb continues from what is now on it.
            child = store.get_item(self._conn, href, parent_uid)
        return closed

    def _nothing_left_in(self, href: str, parent_uid: str) -> bool:
        """Has `parent_uid` at least one child, and is none of them still open?
        Called under the lock.

        At least one, because a task with no subtasks is an ordinary task and
        closing it the moment somebody edits it would be absurd — `len(kids)`
        of zero is not "all done".

        Open covers parked, without a clause for it: parking leaves STATUS
        alone, so a parked child reads NEEDS-ACTION here. See
        `_close_finished_parents`.
        """
        kids = [
            it for it in store.get_items(self._conn, href)
            if it["component"] == "VTODO" and it["related_parent"] == parent_uid
        ]
        return bool(kids) and all(
            (kid["status"] or "") in ("COMPLETED", "CANCELLED") for kid in kids
        )

    def complete_task(self, href: str, uid: str, *, done: bool = True) -> dict[str, Any] | None:
        return self.edit_task(href, uid, TaskEdit(status="COMPLETED" if done else "NEEDS-ACTION"))

    def cancel_task(self, href: str, uid: str) -> dict[str, Any] | None:
        """Won't-do."""
        return self.edit_task(href, uid, TaskEdit(status="CANCELLED"))

    def park_task(self, href: str, uid: str, *, parked: bool = True) -> dict[str, Any] | None:
        """Set a task aside, or bring it back. App-only; the wire never sees it.

        The fourth answer the task list needed. NEEDS-ACTION, COMPLETED and
        CANCELLED were the whole vocabulary, and cancelling reads as a verdict —
        so it never gets used, and nothing ever leaves. Parking is the neutral
        one: not done, not abandoned, just not now.

        A SIBLING OF `complete_task` AND `cancel_task` in shape but not in
        mechanism, and the difference is the point. Those two write a STATUS to
        Radicale; this writes a sidecar column, because RFC 5545 has no neutral
        fourth status and inventing one would put a value three other clients
        cannot read onto collections they share (`app.py::_TASK_STATUS` refuses
        exactly that at the edge). `schema.sql`'s `parked_at` carries the whole
        argument, including the cost: a task parked here still sits in
        Tasks.org's list.

        It goes to `store.set_sidecar` directly rather than through
        `self.set_sidecar`, which runs `_clear_sentinels` — that pass exists for
        the `-1`-means-clear convention the numeric sidecar fields use, and here
        the value being written IS None whenever the owner un-parks.

        NOTHING CLEARS THIS AUTOMATICALLY — not completing the task, not
        reopening it, not another client ticking it off. That is a decision
        rather than an omission: completion can arrive from Tasks.org or a
        phone, through the sync path, and a flag cleared on Smylte's own write
        but not on a foreign one would mean two tasks in the same state
        disagreeing about it. Un-parking is an act, exactly like parking. The
        combination is coherent anyway — a parked task that comes back
        COMPLETED is the honest record that it got done regardless.
        """
        with self._lock:
            store.set_sidecar(
                self._conn, href, uid, parked_at=_stamp() if parked else None
            )
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

    def delete_task(self, href: str, uid: str) -> None:
        with self._lock:
            self._engine.delete_task(href, uid)
        self._publish({"type": "task_deleted", "list": _slug(href), "uid": uid})

    def reorder_tasks(self, placed: list[tuple[str, str]]) -> None:
        """Persist a manual task order — (collection_href, uid) pairs, in order.

        App-only by nature: ``sort_order`` lives in the sidecar, which is
        deliberately not on the wire, so this order is Smylte's own and will not
        appear in Tasks.org, jtx Board or Thunderbird. It survives a cache
        rebuild because the sidecar is the one table sync never drops.

        Published as its own event rather than a task_updated per row: nothing
        about any task's iCalendar data changed, and N events would have every
        other tab refetch N times for one drag.
        """
        with self._lock:
            # A REAL transaction. `with self._conn:` looked like one and was not:
            # the connection is in autocommit (isolation_level=None), where
            # sqlite3's context manager only manages a transaction it opened
            # itself. So this method's documented all-or-nothing guarantee did
            # not exist — a failure part-way left some rows renumbered and some
            # not, and 20 000 rows were 20 000 separate commits under the lock.
            with store.tx(self._conn):
                store.set_sort_orders(self._conn, placed)
        self._publish({"type": "task_reordered"})

    def set_sidecar(self, href: str, uid: str, **fields: object) -> dict[str, Any] | None:
        with self._lock:
            store.set_sidecar(self._conn, href, uid, **_clear_sentinels(fields))
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

    def set_event_sidecar(self, href: str, uid: str, **fields: object) -> dict[str, Any] | None:
        """The same write for a VEVENT.

        Its own method rather than a flag on `set_sidecar`, for the two things
        that actually differ: the SSE event names an event, and the DTO returned
        is an event's. A calendar told `task_updated` refetches the wrong
        collection and paints nothing.
        """
        with self._lock:
            store.set_sidecar(self._conn, href, uid, **_clear_sentinels(fields))
        self._publish({"type": "event_updated", "list": _slug(href), "uid": uid})
        return self.get_event(href, uid)

    # ── calendars / events ───────────────────────────────────────────────────
    def list_calendars(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = store.get_collections(self._conn)
            # One counts query for the whole set, not one per collection.
            counts = store.collection_counts(self._conn)
            return [self._list_dto(r, counts) for r in rows
                    if "VEVENT" in (r["components"] or "")]

    def events_in_range(
        self, href: str, start_iso: str, end_iso: str, *, blocking: bool = False
    ) -> list[dict[str, Any]]:
        """Events in the window, recurring resources fanned out per occurrence.

        `blocking=True` is for the busy set behind the public booking page,
        where a series that could not be expanded means something different than
        it does on the calendar grid. The grid degrades to the master row, which
        is one visible row the owner can see and act on. The busy set has no
        such reader: dropping a series' occurrences there advertises the owner's
        real meetings as free time to an anonymous visitor, so an unexpandable
        series is reported as covering the whole window instead."""
        with self._lock:
            rows = store.get_events_in_range(self._conn, href, start_iso, end_iso)
            cats = store.get_all_categories(self._conn, href)
            # One query for the whole collection, like `cats` beside it — an
            # event's per-item reminder lives in the same sidecar row a task's
            # does, and a per-event lookup would be a round trip per row.
            side = store.get_all_sidecar(self._conn, href)
        win_start, win_end = _parse_window(start_iso), _parse_window(end_iso)
        out: list[dict[str, Any]] = []
        for r in rows:
            if not r["has_rrule"]:
                out.append(self._event_dto(r, cats, side))    # one row, one instance
                continue
            # Recurring: fan the cached raw_ics out into per-occurrence rows. A
            # single malformed resource must not blank the whole month — fall back
            # to showing its master row.
            try:
                for occ in recur.expand_occurrences(r["raw_ics"], win_start, win_end):
                    out.append(self._occurrence_dto(r, occ, cats, side))
            except Exception:  # noqa: BLE001
                log.warning("recurrence expansion failed for %s; showing master", r["uid"])
                if blocking:
                    out.append(self._opaque_span_dto(r, start_iso, end_iso, cats, side))
                else:
                    out.append(self._event_dto(r, cats, side))
        return out

    def _opaque_span_dto(
        self, row, start_iso: str, end_iso: str, cats, side=None
    ) -> dict[str, Any]:
        """A recurring resource we could not expand, as one interval covering the
        whole query window — "assume busy" rather than "assume free"."""
        dto = dict(self._event_dto(row, cats, side))
        dto["start"], dto["end"] = start_iso, end_iso
        dto["start_is_date"] = dto["end_is_date"] = False
        dto["duration"] = None
        return dto

    def get_event(self, href: str, uid: str) -> dict[str, Any] | None:
        with self._lock:
            row = store.get_item(self._conn, href, uid)
            if row is None or row["component"] != "VEVENT":
                return None
            cats = store.get_all_categories(self._conn, href)
            side = store.get_all_sidecar(self._conn, href)
        return self._event_dto(row, cats, side)

    def _event_dto(self, it, cats, side=None) -> dict[str, Any]:
        uid = it["uid"]
        s = (side or {}).get(uid)
        return {
            "uid": uid,
            "id": uid,                       # non-recurring: instance id == uid
            "master_uid": uid,
            "recurrence_id": None,
            "is_recurring": bool(it["has_rrule"]),
            "calendar": it["collection_href"],
            "summary": it["summary"],
            "description": it["description"],
            "location": it["location"],
            "start": it["dtstart"],
            "start_is_date": bool(it["dtstart_is_date"]),
            "end": it["dtend"],
            "end_is_date": bool(it["dtend_is_date"]),
            "duration": it["duration"],
            "all_day": bool(it["dtstart_is_date"]),
            "status": it["status"],
            # TRANSP as the question every reader actually asks. The wire has
            # three states — OPAQUE, TRANSPARENT, absent — and the third is
            # OPAQUE by RFC 5545 §3.8.2.7, so a boolean loses nothing; `raw_ics`
            # keeps the property itself, as it keeps everything.
            "busy": blocks_time(it["transp"]),
            "tags": cats.get(uid, []),
            "has_rrule": bool(it["has_rrule"]),
            "href": it["href"],
            "etag": it["etag"],
            "created": it["created"],
            "last_modified": it["last_modified"],
            # The same per-item reminder a task carries, on the same sidecar
            # row — an event's "notify me 20 minutes before" and a task's are
            # one feature, so they are one column and one rule.
            "notify_minutes_before": s["notify_minutes_before"] if s else None,
        }

    def _occurrence_dto(self, it, occ: recur.Occurrence, cats, side=None) -> dict[str, Any]:
        """One expanded occurrence of a recurring series. Same keys as
        ``_event_dto`` (so the frontend stays uniform), but ``id`` is unique per
        instance and ``start``/``end`` are this occurrence's times; per-instance
        text falls back to the master's when an override omits a field. ``uid`` /
        ``href`` stay the base resource so series-level edit/delete still work."""
        uid = it["uid"]
        s = (side or {}).get(uid)
        return {
            "uid": uid,
            "id": f"{uid}::{occ.recurrence_id}",
            "master_uid": uid,
            "recurrence_id": occ.recurrence_id,
            "is_recurring": True,
            "calendar": it["collection_href"],
            "summary": occ.summary if occ.summary is not None else it["summary"],
            "description": occ.description if occ.description is not None else it["description"],
            "location": occ.location if occ.location is not None else it["location"],
            "start": occ.start,
            "start_is_date": occ.start_is_date,
            "end": occ.end,
            "end_is_date": occ.end_is_date,
            "duration": None,
            "all_day": occ.start_is_date,
            "status": occ.status if occ.status is not None else it["status"],
            # The occurrence's own TRANSP when the override carries one, else
            # the master's — the same fallback every other per-instance field
            # here makes, and the reason `Occurrence` reads it at all: an
            # override may be Free on a week the series is Busy.
            "busy": blocks_time(
                occ.transp if occ.transp is not None else it["transp"]),
            "tags": cats.get(uid, []),
            "has_rrule": True,
            "href": it["href"],
            "etag": it["etag"],
            "created": it["created"],
            "last_modified": it["last_modified"],
            # The series' reminder, carried by every occurrence. The sidecar is
            # keyed on the RESOURCE (invariant #4), so a recurring event has one
            # reminder rather than one per instance — "notify me 20 minutes
            # before my standup" is a statement about the standup, not about
            # next Tuesday's.
            "notify_minutes_before": s["notify_minutes_before"] if s else None,
        }

    def create_event(self, href: str, summary: str, *, dtstart, dtend=None,
                     edit: EventEdit | None = None,
                     client_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            uid = self._engine.create_event(
                href, summary, dtstart=dtstart, dtend=dtend, edit=edit, slug=client_id
            )
        self._publish({"type": "event_created", "list": _slug(href), "uid": uid})
        return self.get_event(href, uid)

    def edit_event(
        self, href: str, uid: str, edit: EventEdit,
        *, recurrence_id: str | None = None, scope: str = "all",
    ) -> dict[str, Any] | None:
        with self._lock:
            if scope == "this" and recurrence_id:
                self._engine.override_event(href, uid, recurrence_id, edit)
            elif scope == "thisandfuture" and recurrence_id:
                self._engine.split_event(href, uid, recurrence_id, edit)
            elif scope == "all" and recurrence_id and edit.dtstart is not UNSET:
                # A time change with "all events" moves the whole series by the
                # same offset (the master edit below never touches times).
                self._engine.shift_event(href, uid, recurrence_id, edit)
            elif (scope == "all" and recurrence_id and edit.dtend is not UNSET
                    and self._is_recurring(href, uid)):
                # An END-only change anchored on an occurrence is a series
                # reschedule too ("extend every standup to 11:00"), and the
                # master edit below cannot be allowed to take it: it writes the
                # OCCURRENCE's absolute end as the master DTEND, so a weekly
                # 10:00-10:30 series from January became a series of
                # eight-month-long events — 39 September occurrences instead
                # of 4, and a booking page that showed the owner busy for the
                # rest of the year. `_check_event_span` waves it through
                # because the master DTSTART really is before that end.
                # `shift_series` measures its delta from the new START and has
                # no way to express "same slot, new duration" without it, so
                # the honest answer is a refusal that names what to send. The
                # SPA always pairs the two; the HTTP PATCH and
                # `smylte_update_event` are the callers that can reach this.
                raise ValueError(
                    "changing only the end of a whole series needs its start too: "
                    "pass start (the occurrence's current start) with end, or use "
                    "scope='this' to change one occurrence"
                )
            else:
                self._engine.edit_event(href, uid, edit)
        self._publish({"type": "event_updated", "list": _slug(href), "uid": uid})
        return self.get_event(href, uid)

    def _is_recurring(self, href: str, uid: str) -> bool:
        """Whether the cached resource repeats (an RRULE or an RDATE). Called
        under the lock. An unknown item is simply "not recurring" here — the
        engine is the one that reports it, with the KeyError the routes map."""
        row = store.get_item(self._conn, href, uid)
        return bool(row is not None and row["has_rrule"])

    def move_event(self, src_href: str, dst_href: str, uid: str) -> dict[str, Any] | None:
        if src_href == dst_href:
            return self.get_event(src_href, uid)
        with self._lock:
            # The sidecar is keyed on (collection_href, uid), and the engine
            # orphans the SOURCE row as part of the move — so the event's
            # reminder, which is deliberately app-only (no VALARM, see
            # schema.sql) and therefore restored by nothing on the wire, stayed
            # behind on a row GC would delete a week later while the
            # destination started with none. Read before the move, written
            # after `_refresh_from_wire` has cached the destination row, since
            # `set_sidecar` only writes for an item that exists there.
            prior = store.get_sidecar(self._conn, src_href, uid)
            lead = prior["notify_minutes_before"] if prior is not None else None
            self._engine.move_event(src_href, dst_href, uid)
            if lead is not None:
                store.set_sidecar(self._conn, dst_href, uid, notify_minutes_before=lead)
        # Both calendars changed: gone from one, appeared in the other.
        self._publish({"type": "event_deleted", "list": _slug(src_href), "uid": uid})
        self._publish({"type": "event_created", "list": _slug(dst_href), "uid": uid})
        return self.get_event(dst_href, uid)

    def delete_event(
        self, href: str, uid: str,
        *, recurrence_id: str | None = None, scope: str = "all",
    ) -> None:
        with self._lock:
            if scope == "this" and recurrence_id:
                self._engine.exclude_event_occurrence(href, uid, recurrence_id)
            elif scope == "thisandfuture" and recurrence_id:
                self._engine.split_event(href, uid, recurrence_id, EventEdit(), delete_tail=True)
            else:
                self._engine.delete_task(href, uid)   # whole resource (by href)
        self._publish({"type": "event_deleted", "list": _slug(href), "uid": uid})

    # ── scheduling (booking links) ─────────────────────────────────────────────
    def list_booking_links(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = store.list_booking_links(self._conn)
            counts = store.bookings_count_by_link(self._conn)
            names = {r["href"]: r["displayname"] for r in store.get_collections(self._conn)}
            return [self._link_dto(r, counts, names) for r in rows]

    def _public_page_url(self, path: str) -> str | None:
        """An absolute URL for a token-addressed page, or None when this
        deployment has not said what its origin is. `public_url` is the one
        configured statement of that origin (normalized, no trailing slash);
        a URL built off the Host header would be whatever the caller sent."""
        origin = self.settings.public_url
        return f"{origin}{path}" if origin else None

    def _link_dto(self, row, counts: dict[str, int], names: dict[str, str]) -> dict[str, Any]:
        return {
            "token": row["token"],
            # The page a visitor opens, absolute, for a client that has to put
            # it on a clipboard and has nothing but the token otherwise.
            "url": self._public_page_url(f"/book/{row['token']}"),
            "title": row["title"],
            "description": row["description"],
            "calendar": _slug(row["calendar_href"]),
            "calendar_name": names.get(row["calendar_href"]),
            # The target is gone from the server, so the link was disabled and
            # cannot be re-enabled until it is pointed at a calendar that exists.
            # Surfaced so Settings can say that instead of showing an inert toggle.
            "calendar_missing": row["calendar_href"] not in names,
            "duration_minutes": row["duration_minutes"],
            "timezone": row["timezone"],
            "availability": json.loads(row["availability"] or "{}"),
            "show_busy": bool(row["show_busy"]),
            "buffer_minutes": row["buffer_minutes"],
            "min_notice_hours": row["min_notice_hours"],
            "horizon_days": row["horizon_days"],
            "enabled": bool(row["enabled"]),
            "booking_count": counts.get(row["token"], 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _normalize_link_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Validate/canonicalize link fields. Raises ValueError (routes → 422)."""
        out = dict(fields)
        if "timezone" in out:
            try:
                ZoneInfo(out["timezone"])
            except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError, bad type, …
                raise ValueError(f"unknown timezone {out['timezone']!r}") from None
        if "availability" in out:
            parsed = scheduling.parse_availability(out["availability"])
            out["availability"] = json.dumps({
                str(day): [f"{s:%H:%M}-{e:%H:%M}" for s, e in ranges]
                for day, ranges in parsed.items()
            })
        if "calendar_href" in out:
            row = self._conn.execute(
                "SELECT components FROM collections WHERE href=? AND deleted=0",
                (out["calendar_href"],),
            ).fetchone()
            if row is None or "VEVENT" not in (row["components"] or ""):
                raise ValueError("calendar must be an existing event calendar")
        for k in ("show_busy", "enabled"):
            if k in out:
                out[k] = int(bool(out[k]))
        return out

    def create_booking_link(self, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            token = secrets.token_urlsafe(16)
            store.create_booking_link(self._conn, token, self._normalize_link_fields(fields))
        self._publish({"type": "booking_link_created", "link": token})
        return self.list_booking_links_one(token)

    def update_booking_link(self, token: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            row = store.update_booking_link(
                self._conn, token, self._normalize_link_fields(fields)
            )
            if row is None:
                return None
        self._publish({"type": "booking_link_updated", "link": token})
        return self.list_booking_links_one(token)

    def list_booking_links_one(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = store.get_booking_link(self._conn, token)
            if row is None:
                return None
            counts = store.bookings_count_by_link(self._conn)
            names = {r["href"]: r["displayname"] for r in store.get_collections(self._conn)}
            return self._link_dto(row, counts, names)

    def delete_booking_link(self, token: str) -> bool:
        with self._lock:
            ok = store.delete_booking_link(self._conn, token)
        if ok:
            self._publish({"type": "booking_link_deleted", "link": token})
        return ok

    def list_bookings(self, link_token: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = store.list_bookings(self._conn, link_token)
            titles = {r["token"]: r["title"] for r in store.list_booking_links(self._conn)}
        return [{
            "id": r["id"],
            "link": r["link_token"],
            "link_title": titles.get(r["link_token"]),
            "event_uid": r["event_uid"],
            "calendar": _slug(r["calendar_href"]),
            "name": r["client_name"],
            "email": r["client_email"],
            "notes": r["notes"],
            "start": r["start_at"],
            "end": r["end_at"],
            "created_at": r["created_at"],
        } for r in rows]

    def _link_busy(
        self, tz: ZoneInfo, window: scheduling.Interval, *, only_href: str | None = None
    ) -> list[scheduling.Interval]:
        """Busy intervals across ALL event calendars (double-booking prevention
        is global, not per target calendar), or across just ``only_href`` (the
        redacted busy shown publicly — see public_link_info). The SQL range scan
        compares ISO strings against mostly-naive dtstart values, so the bounds
        are naive link-local widened by ±1 day; scheduling.py then filters
        precisely."""
        start_iso = (window.start - timedelta(days=1)).replace(tzinfo=None).isoformat()
        end_iso = (window.end + timedelta(days=1)).replace(tzinfo=None).isoformat()
        events: list[dict[str, Any]] = []
        with self._lock:
            for row in store.get_collections(self._conn):
                if "VEVENT" not in (row["components"] or ""):
                    continue
                if only_href is not None and row["href"] != only_href:
                    continue
                events.extend(
                    self.events_in_range(row["href"], start_iso, end_iso, blocking=True)
                )
        return scheduling.busy_intervals(events, tz, naive_tz=self._home_tz())

    def _home_tz(self) -> ZoneInfo | None:
        """The zone the owner authors floating times in, if they have set one.

        None means "no better information than the link's zone", which is what
        the busy math falls back to."""
        with self._lock:
            name = store.get_settings(self._conn).get("home_timezone")
        if not isinstance(name, str) or not name:
            return None
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — a stored blob can hold anything
            return None

    def _link_is_live(self, link) -> bool:
        """Bookable at all? Disabled links and links whose target calendar has
        gone away are indistinguishable 404s to the public — an unbookable link
        must not advertise slots, and must not become an oracle for which of the
        two it is. Called under the lock."""
        return bool(link["enabled"]) and store.has_collection(
            self._conn, link["calendar_href"]
        )

    def public_link_info(self, token: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """The public booking page payload, or None for an unknown OR disabled
        link (the route maps both to the same 404 — no probing oracle). Nothing
        beyond title/description/duration/timezone/slots (+ redacted busy) ever
        leaves the server here."""
        with self._lock:
            link = store.get_booking_link(self._conn, token)
            if link is None or not self._link_is_live(link):
                return None
            tz = ZoneInfo(link["timezone"])
            now = now or datetime.now(timezone.utc)
            local_now = now.astimezone(tz)
            day0 = datetime.combine(local_now.date(), time.min, tzinfo=tz)
            window = scheduling.Interval(
                local_now, day0 + timedelta(days=link["horizon_days"] + 1)
            )
            busy = self._link_busy(tz, window)
            slots = scheduling.generate_slots(
                availability=scheduling.parse_availability(link["availability"]),
                duration_minutes=link["duration_minutes"],
                busy=busy,
                buffer_minutes=link["buffer_minutes"],
                tz=tz,
                now=now,
                min_notice_hours=link["min_notice_hours"],
                horizon_days=link["horizon_days"],
            )
        out: dict[str, Any] = {
            "token": token,
            "title": link["title"],
            "description": link["description"],
            "duration_minutes": link["duration_minutes"],
            "timezone": link["timezone"],
            "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots],
        }
        if link["show_busy"]:
            # Redacted: merged time ranges only — no titles, no counts, and no
            # buffer padding (that would leak the buffer setting). Scoped to the
            # link's OWN calendar: the conflict-check busy above is deliberately
            # global, but publishing that union would leak the time-shape of
            # every other calendar (personal, archived, …) to anyone with the
            # link URL.
            shown = self._link_busy(tz, window, only_href=link["calendar_href"])
            out["busy"] = [
                {"start": b.start.isoformat(), "end": b.end.isoformat()}
                for b in scheduling.clip(shown, window)
            ]
        return out

    def book_slot(
        self, token: str, *, start_iso: str, name: str, email: str,
        notes: str | None = None, client_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool] | None:
        """Book a slot: re-validate under the lock, write the VEVENT, record the
        booking. Returns None for unknown/disabled links; raises ValueError for
        a malformed start (→ 422) and scheduling.SlotTaken when the requested
        time isn't an open slot (→ 409).

        Returns `(confirmation, created)`. `created` is False for a replay — the
        same client_id coming back, answered from the booking already written.
        The caller needs to tell them apart: the per-link ceiling is a budget of
        BOOKINGS, and charging a replay for one that landed nothing put the
        published-link denial-of-service straight back."""
        with self._lock:
            link = store.get_booking_link(self._conn, token)
            if link is None or not self._link_is_live(link):
                return None
            # Replay (same client_id ⇒ same event UID): return the original
            # confirmation instead of failing the re-validation as taken. Only
            # for THIS link — a client_id reused against a different link is
            # not a replay of anything and must not disclose the other
            # booking's times (nor collide with its event resource).
            if client_id:
                prior = store.get_booking_by_event(self._conn, f"{client_id}@tasksd")
                if prior is None:
                    prior = self._recover_orphaned_booking(
                        link, token, client_id, start_iso, name=name, email=email)
                if prior is not None:
                    if prior["link_token"] == token:
                        return self._confirmation(link, prior), False
                    raise ValueError("client_id already used")
            tz = ZoneInfo(link["timezone"])
            req = datetime.fromisoformat(start_iso)
            if req.tzinfo is None:
                raise ValueError("start must be an ISO datetime with a UTC offset")
            req = req.astimezone(tz)
            now = now or datetime.now(timezone.utc)
            day0 = datetime.combine(req.date(), time.min, tzinfo=tz)
            busy = self._link_busy(tz, scheduling.Interval(day0, day0 + timedelta(days=1)))
            slots = scheduling.generate_slots(
                availability=scheduling.parse_availability(link["availability"]),
                duration_minutes=link["duration_minutes"],
                busy=busy,
                buffer_minutes=link["buffer_minutes"],
                tz=tz,
                now=now,
                min_notice_hours=link["min_notice_hours"],
                horizon_days=link["horizon_days"],
                only_day=req.date(),
            )
            # Match on the INSTANT. `s.start` and `req` share one ZoneInfo, so
            # `==` compares naive fields: on a fall-back day either pass of the
            # repeated hour matched the other, letting a visitor book an instant
            # that was never offered.
            req_utc = req.astimezone(timezone.utc)
            if not any(s.start.astimezone(timezone.utc) == req_utc for s in slots):
                raise scheduling.SlotTaken("that time is not available")

            # In UTC for the same reason generate_slots steps in UTC: adding a
            # timedelta to a zone-aware local time is wall-clock arithmetic, so
            # a booking made across a fall-back transition wrote a 90-minute
            # VEVENT for a 30-minute link.
            end = (req.astimezone(timezone.utc)
                   + timedelta(minutes=link["duration_minutes"])).astimezone(tz)
            desc = [f'Booked via scheduling link "{link["title"]}".', "",
                    f"Name: {name}", f"Email: {email}"]
            if notes:
                desc += ["", f"Notes: {notes}"]
            # Zone-aware on the wire (UTC — every client parses `Z`, no
            # VTIMEZONE needed): a booking is an absolute instant. Floating
            # local would be re-read relative to whichever link's zone next
            # parses it, so two links in different zones wouldn't reliably
            # block each other's booked slots.
            event = self.create_event(
                link["calendar_href"], f"{link['title']} — {name}",
                dtstart=req.astimezone(timezone.utc),
                dtend=end.astimezone(timezone.utc),
                edit=EventEdit(description="\n".join(desc)),
                client_id=client_id,
            )
            booking_id = uuid.uuid4().hex
            store.insert_booking(
                self._conn, id=booking_id, link_token=token,
                calendar_href=link["calendar_href"], event_uid=event["uid"],
                client_name=name, client_email=email, notes=notes,
                start_at=req.isoformat(), end_at=end.isoformat(),
            )
        self._publish({"type": "booking_created", "link": token})
        return {
            "id": booking_id,
            "start": req.isoformat(),
            "end": end.isoformat(),
            "title": link["title"],
            "duration_minutes": link["duration_minutes"],
            "timezone": link["timezone"],
        }, True

    def _recover_orphaned_booking(self, link, token: str, client_id: str,
                                  start_iso: str, *, name: str, email: str):
        """A ledger row rebuilt from an event this booking already wrote.

        The whole replay mechanism keys on the ledger, and the ledger row is
        inserted AFTER `create_event` has PUT the VEVENT to Radicale. Anything
        between the two — `_refresh_from_wire`'s second round trip raising
        DavError, a process restart — leaves the event on the owner's calendar
        with no ledger row. The visitor's retry, with the same client_id their
        page deliberately keeps stable for the chosen slot, is then not
        recognised as a replay; once the background sync pulls the orphan into
        the cache, `_link_busy` sees it, the slot disappears, and `book_slot`
        tells them "that time is not available" about their OWN booking. They
        pick another slot and the owner gets two events for one person, one of
        which is invisible in Settings -> Bookings and uncounted against the
        link's ceiling.

        So the hook does not depend on the ledger being there: the EVENT is the
        record, since `create_event` derives its UID from the client_id, and the
        ledger is rebuilt from it.

        It is NOT enough to scope this to the link's calendar, which is what the
        first version did while claiming that "a client_id reused against a
        different link still raises rather than disclosing the other booking's
        times". Two links on ONE calendar is the default shape of this feature,
        and there the calendar check passes for both: a caller of link B,
        presenting a client_id used on link A, was handed A's booking TIMES under
        B's title, and the ledger permanently recorded A's booking under B with
        the real booker's name and email erased.

        What proves intent without disclosing anything is the REQUEST: recover
        only when the orphaned event sits at the very instant this caller is
        asking for. That is exactly the shape finding 30 is about — the visitor's
        page keeps the client_id stable *for the chosen slot*, so a retry names
        the same instant — and it tells a caller nothing they did not already
        supply. Anything else falls through to the "client_id already used"
        refusal below, which is the honest answer: their earlier booking did land.

        Returns the new ledger row, or None if there is no such event.
        """
        row = store.get_item(self._conn, link["calendar_href"], f"{client_id}@tasksd")
        if row is None or row["component"] != "VEVENT":
            return None
        try:
            asked = datetime.fromisoformat(start_iso)
            found = datetime.fromisoformat(row["dtstart"] or "")
        except ValueError:
            return None
        if asked.tzinfo is None or found.tzinfo is None:
            return None
        if asked.astimezone(timezone.utc) != found.astimezone(timezone.utc):
            # Raised HERE, not left to the caller: `book_slot` reads None as
            # "no prior booking" and goes on to a fresh create, and the
            # engine's `_put_new` treats a 412 whose occupant carries our own
            # UID as success without writing — so the ledger gained a row, the
            # link's ceiling was charged and the visitor got a 201 for a time
            # no event occupies, while the calendar kept the orphan at the old
            # one. Their earlier booking did land; that is the honest answer.
            raise ValueError("client_id already used")
        # In the LINK's zone, the way the ordinary path writes it. The cached
        # row holds whatever the wire said (this app writes bookings in UTC), and
        # a confirmation that named the same instant in a different offset would
        # read to the visitor as a different time than the one they picked.
        tz = ZoneInfo(link["timezone"])

        def _local(value):
            if not value:
                return ""
            try:
                dt = datetime.fromisoformat(value)
            except ValueError:
                return value
            return (dt.astimezone(tz) if dt.tzinfo else dt).isoformat()

        booking_id = uuid.uuid4().hex
        store.insert_booking(
            self._conn, id=booking_id, link_token=token,
            calendar_href=link["calendar_href"], event_uid=row["uid"],
            # The caller's own, not blanks: we only get here when this request
            # names the instant the orphaned event occupies, which means this IS
            # the same visitor retrying the same slot.
            client_name=name, client_email=email, notes=None,
            start_at=_local(row["dtstart"]),
            end_at=_local(row["dtend"] or row["dtstart"]),
        )
        log.warning(
            "booking ledger row was missing for event %s on link %s; rebuilt from "
            "the calendar (a write failed between the PUT and the ledger insert)",
            row["uid"], token,
        )
        return store.get_booking_by_event(self._conn, row["uid"])

    @staticmethod
    def _confirmation(link, booking) -> dict[str, Any]:
        return {
            "id": booking["id"],
            "start": booking["start_at"],
            "end": booking["end_at"],
            "title": link["title"],
            "duration_minutes": link["duration_minutes"],
            "timezone": link["timezone"],
        }

    # ── day plan (the Today tab's snapshot) ──────────────────────────────────
    #
    # A day plan is app-only state (schema.sql says why), so everything here is
    # SQL under the service lock — no DAV, no engine. Every method that WRITES
    # publishes {"type": "day_updated", "day": …}: a plan is edited from one tab
    # and read in another, and unlike a task edit there is no task_updated event
    # for the other tab to notice, so without this the second tab shows
    # yesterday's arrangement until it is reloaded.

    @staticmethod
    def _day_entry_dto(row) -> dict[str, Any]:
        return {
            "entry_id": row["entry_id"],
            "day": row["day"],
            "kind": row["kind"],
            # The list's SHORT id, like `_task_dto`'s "list" and the SSE
            # payloads — never the href. The client joins a day entry back to
            # the task it names on (list, uid), and it only ever holds short ids.
            "list": _slug(row["collection_href"]) if row["collection_href"] else None,
            "uid": row["uid"],
            "title": row["title"],
            "source": row["source"],
            # habit entries: the rule that minted this occurrence, NULL for
            # everything else. Dangling by design once that habit is deleted —
            # the row keeps its copied title and stays readable. This line and
            # store.init_db's `habit_id` ALTER are one change: sqlite3.Row
            # raises IndexError for a column the table does not have, and
            # nothing maps IndexError, so shipping this half alone 500s every
            # read of every day.
            "habit_id": row["habit_id"],
            "position": row["position"],
            # What this entry was expected to take, on this day. NULL is "not
            # estimated" and stays NULL — the total is over the rows that carry
            # one, so an unestimated row costs the day nothing rather than
            # counting as zero-length work. Same one-change rule as `habit_id`
            # above and the same mechanical reason: this line and
            # store.init_db's `estimate_minutes` ALTER ship together or every
            # read of every day is a 500.
            "estimate_minutes": row["estimate_minutes"],
            "done_at": row["done_at"],
            "dropped_at": row["dropped_at"],
            # The day this was deliberately moved to, or null. Distinct from
            # `dropped_at`: "doing it Thursday" and "decided against it" are
            # different things for a day to remember. Same one-change rule as
            # the columns above — this line and the ALTER ship together.
            "rolled_to": row["rolled_to"],
            # Seconds a focus session actually spent on this row, or null when
            # no session ever did — a measurement, kept apart from the estimate
            # above, which is a guess. Same one-change rule as the columns
            # above: this line and store.init_db's ALTER ship together.
            "worked_seconds": row["worked_seconds"],
            # Whether a focus session stops at the estimate (true), runs until
            # the row is ticked (false), or follows the account's default (null,
            # "not said"). Same one-change rule.
            "capped": None if row["capped"] is None else bool(row["capped"]),
            "created_at": row["created_at"],
        }

    def _day_plan_dto(
        self, day: str, entries, opened: bool, *, ritual=UNSET, settings=None,
    ) -> dict[str, Any]:
        """One day's plan. `planned` is the marker OR the presence of entries,
        because the two record different things: the marker says the automatic
        snapshot has been BUILT, an entry says the owner has put something on
        the day. A hand-add deliberately leaves the marker alone (see
        `add_day_entry`, and the day still owes itself one snapshot), so a day
        holding nothing but hand-added rows has no marker — and calling that day
        unplanned would draw it as untouched with its own entries on screen.

        `ritual` and `settings` let a RANGE caller hand in what it already read
        for the whole window, instead of this doing two queries per day. A day
        with no ritual row is a legitimate `None`, which is why the default is a
        sentinel rather than None — see `day_range`."""
        if ritual is UNSET:
            ritual = store.get_day_ritual(self._conn, day)
        return {
            "day": day,
            "planned": opened or bool(entries),
            # What the owner SAID about this day, alongside what is on it.
            #
            # `capacity_minutes` is what they stated FOR THIS DAY and is null
            # until they do — deliberately not resolved through the settings
            # default here, because the two answer different questions. This one
            # is "did they say something about today"; `capacity` below is "what
            # number should the total be read against". Collapsing them would
            # make a day that merely inherited a weekday default indistinguishable
            # from one the owner actually looked at and set.
            "capacity_minutes": ritual["capacity_minutes"] if ritual else None,
            "capacity": self._effective_capacity(day, ritual, settings=settings),
            "committed_at": ritual["committed_at"] if ritual else None,
            "shutdown_at": ritual["shutdown_at"] if ritual else None,
            "reflection": ritual["reflection"] if ritual else None,
            "entries": [self._day_entry_dto(r) for r in entries],
        }

    def _effective_capacity(self, day: str, ritual=UNSET, *, settings=None) -> int | None:
        """How many minutes this day should be read against, or None.

        Four answers in order, and the last one is the important one:

          1. what the owner said for THIS day
          2. the default for this WEEKDAY, from settings
          3. the account-wide default, from settings
          4. NONE

        None is a real answer, not a zero. An account that has never stated a
        capacity must not be told it has overcommitted against a number it never
        gave — so every reader of this has to handle null rather than falling
        back to some assumed working day. That is the difference between a tool
        that helps you notice something and one that invents a standard for you.

        The weekday comes from the day key's own characters through
        `weekday_name`, so it is zone-free and agrees with habit scheduling by
        construction. The settings map is keyed by the SAME names habits use;
        anything else in it is ignored rather than guessed at, because a settings
        blob is hand-editable and a garbage key must not become a capacity.
        """
        # The SENTINEL, not None — a day with no ritual row is a legitimate None,
        # and treating it as "not supplied" re-queried exactly the days the batch
        # read was written to cover. `day_range` passes `rituals.get(d)`, which is
        # None for every planned day the owner never set a capacity on, so the
        # N+1 survived for all of them: up to 190 extra SELECTs under the lock.
        if ritual is UNSET:
            ritual = store.get_day_ritual(self._conn, day)
        if ritual and ritual["capacity_minutes"] is not None:
            return ritual["capacity_minutes"]
        # A range caller passes the settings blob it already read; the account
        # cannot change it mid-request, and re-reading and re-parsing it once
        # per day is the other half of the N+1 `day_range` used to run.
        if settings is None:
            settings = store.get_settings(self._conn)
        by_weekday = settings.get("day_capacity_by_weekday")
        if isinstance(by_weekday, dict):
            value = by_weekday.get(weekday_name(day))
            # `isinstance(x, bool)` first: bool is an int subclass, so JSON
            # `true` would otherwise read as one minute. The same guard
            # `_check_session_ttl` applies for the same reason.
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        default = settings.get("day_capacity_minutes")
        # `>= 0` because a negative stored value is the clear sentinel at rest.
        # `update_settings` merges shallowly and skips None, so "never said"
        # after once having said something is spelled as -1 rather than by
        # removing the key — and it has to read back as no capacity at all.
        if isinstance(default, int) and not isinstance(default, bool) and default >= 0:
            return default
        return None

    def _focus_settings(self) -> dict[str, Any]:
        """The account's focus clock, defaults filled and bounds applied."""
        return focus_settings(store.get_settings(self._conn))

    def open_day(self, day: str, *, create: bool) -> dict[str, Any]:
        """The plan for a day, optionally building it if it has never been built.

        `create` has no default on purpose. With create=False this is a pure
        read that writes NOTHING — not an entry, not even the opened marker —
        because GET is also how the app looks at a day it is not visiting:
        prefetching next week, or a range read landing on an empty day. A GET
        that quietly opened days would fill the log with plans the owner never
        made, freeze each of those days' snapshots at whatever was due when the
        prefetch happened, and — worst — make the marker lie about which days
        were actually planned.

        With create=True on a day that has never been opened, the snapshot is
        built once: what is due that day, and what was left unfinished on the
        last day that had a plan. What is already LATE is deliberately not among
        them — `_snapshot_for`'s docstring gives the argument, and the suggestion
        strip is where an overdue task is offered instead. Afterwards the MARKER —
        and only the marker — makes this a read like any other, so re-opening
        never re-snapshots and never resurrects an entry the owner dropped.

        Entries already on the day do NOT stand in for the marker. They used to:
        the day's first hand-add called `mark_day_opened`, and short-circuiting
        on `entries` meant a day whose first write was an add never got its
        snapshot at all — due-today and carried rows suppressed for
        that day forever, from a client that offers the add box before the open
        has even answered. So the snapshot merges into what is there instead,
        skipping anything the day already holds (`_snapshot_for`).

        HABITS are the one thing a marked day still receives. A habit is a rule,
        and a rule made this morning has to reach today — the alternative is that
        creating a habit does nothing visible until tomorrow, on the one screen it
        exists for. So an already-planned day gets a TOP-UP: an occurrence for
        each active habit scheduled on that weekday that has no row on the day
        yet, and nothing else. Tasks are never re-derived; the snapshot-once rule
        is untouched. Four cases, in full:

          * no marker, not past    — the full snapshot (habits first, then
                                     due-today, then carried) and the marker.
          * no marker, day in past — the same snapshot MINUS the habits: the
                                     tasks still derive (they are read off the
                                     wire and assert nothing about that day), but
                                     no occurrence is minted, because a habit
                                     occurrence exists nowhere but in the row.
          * marker, day not past   — habit top-up only.
          * marker, day in past    — nothing at all.

        The last two lines of that table are one rule, not two: a past day is the
        record of what was intended AT THE TIME, and writing today's rules into
        it is a forgery, however small. Both paths ask `_habit_entries_for`, and
        it is the one that refuses — first-open and top-up alike, with a one-day
        grace on "past" (see `_habit_minting_allowed`).
        """
        day = day_key(day)
        with self._lock:
            entries = store.get_day_entries(self._conn, day)
            opened = store.day_is_opened(self._conn, day)
            if not create:
                return self._day_plan_dto(day, entries, opened)
            if opened:
                # No pastness check here: `_habit_entries_for` makes it, for this
                # caller and for `_snapshot_for` both. Asking it HERE is what let
                # the first open of a past day mint habits — the same rule, spelt
                # at one of its two call sites.
                pending = self._habit_entries_for(day, entries)
                if not pending:
                    # The ordinary case for every re-open of a planned day.
                    # Returning here keeps it a pure read: no transaction, and no
                    # `day_updated` event for every other tab to refetch on —
                    # `patch_day_entry` draws the same line for the same reason.
                    return self._day_plan_dto(day, entries, True)
            else:
                pending = self._snapshot_for(day, entries)
            # Behind whatever the owner has already placed, computed the same
            # way `add_day_entry` appends. Rows that are already on the day keep
            # the positions they were given: a snapshot arriving late must not
            # renumber the arrangement it is joining, and neither must an
            # evening top-up — a habit added at 18:00 joins the end of the day
            # the owner has spent all day arranging, it does not jump to the top
            # of it. (Habits lead `pending`, never the day: on a first snapshot
            # of a day whose first write was a hand-add — `_snapshot_for` MERGES
            # with those rows rather than landing beside them — `base` is
            # non-zero, so the habits sit behind the hand-added rows too. They
            # read first only when the day was empty, which is the usual case
            # but not the rule.)
            base = max((r["position"] or 0.0 for r in entries), default=0.0)
            # One transaction for the whole snapshot INCLUDING the marker. The
            # connection is in autocommit (see store.tx), so without it a
            # failure part-way through would leave entries behind with no
            # marker — and the next open would treat the day as never opened and
            # snapshot it again, on top of the rows that did land.
            with store.tx(self._conn):
                for i, fields in enumerate(pending, start=1):
                    # A dense sequence from `base`: every row of a fresh
                    # snapshot gets a position, so nothing in the day is left
                    # unordered and the reading order does not depend on a
                    # tie-break. PATCH takes any float, so a client moving a row
                    # between two of these still has the whole interval to land
                    # in.
                    store.insert_day_entry(
                        self._conn, day=day, position=base + float(i), **fields
                    )
                # Unconditional, and a no-op on the top-up path: `mark_day_opened`
                # is INSERT OR IGNORE and keeps the ORIGINAL opened_at, so a day
                # that gains a habit occurrence in the evening still records when
                # it was first planned.
                store.mark_day_opened(self._conn, day)
            entries = store.get_day_entries(self._conn, day)
            dto = self._day_plan_dto(day, entries, True)
        self._publish({"type": "day_updated", "day": day})
        return dto

    def preview_day(self, day: str) -> list[dict[str, Any]]:
        """What opening `day` WOULD put on it, without opening it.

        The same derivation `open_day(create=True)` inserts — habits first, then
        due that day, then unfinished from the last planned day — run and thrown
        away. What is already late is in none of them, here for the same reason
        it is in no open: `_snapshot_for` derives it nowhere, so a preview that
        showed it would describe a day the open it stands in for would not
        produce. `_snapshot_for` writes nothing itself, so this
        costs one read and cannot leave a trace. A PAST day previews no habits,
        for the same reason opening one mints none (`_habit_entries_for`): a
        preview that showed them would describe a day the open it stands in for
        would not produce.

        It exists for the MCP connector, which has to answer "what is on today"
        for a day the owner has not opened yet. Reading is the only thing a
        connector may do to an unplanned day: a read that opened days would fill
        the log with plans nobody made, and freeze each of those days' snapshots
        at whatever happened to be due when something asked. So the honest
        answer is a preview, clearly not a plan, and the marker stays unset until
        a person opens the day themselves.

        Entries the day already holds are excluded, exactly as they are on a real
        open — a FIRST open, which is the one this previews and the only one it
        speaks for. On a day that has ALREADY been planned this is not a forecast
        of the next open and does not claim to be: `_snapshot_for` re-derives
        due-today from the wire as it stands now, while a re-open of a marked day
        tops up habits and nothing else. Probed: open a day, then
        give a task a DUE on it, and the preview names a task no open will ever
        add. (A habit created after the open does appear on both, because the
        top-up runs this same `_habit_entries_for`.)

        Which is why the emptiness this used to promise for a planned day was
        never a property of the code, and is not worth making into one. The one
        caller asks about days NOBODY HAS OPENED — `mcp/api.py::today` reaches
        for a preview only when `planned` is false — and on those the derivation
        and the open are the same derivation.

        Returned in the shape `_day_entry_dto` produces, so a caller has one
        entry shape to handle rather than two — with the row-only columns
        (`position`, `done_at`, `dropped_at`, `created_at`) null, because none of
        these is a row. The `entry_id`s are the ones a real open would have
        minted and are thrown away with the rest: nothing may be patched by them.
        """
        day = day_key(day)
        with self._lock:
            existing = store.get_day_entries(self._conn, day)
            pending = self._snapshot_for(day, existing)
        return [
            {
                "entry_id": f["entry_id"],
                "day": day,
                "kind": f["kind"],
                "list": _slug(f["collection_href"]) if f.get("collection_href") else None,
                "uid": f.get("uid"),
                "title": f.get("title"),
                "source": f["source"],
                # Present here for the same reason every other key is: this dict
                # is a SECOND hand-written spelling of `_day_entry_dto`, and the
                # docstring above promises a caller one entry shape rather than
                # two. A field added to one and not the other makes a preview
                # entry and a real entry differ in exactly the way that promise
                # says they do not.
                "habit_id": f.get("habit_id"),
                # A preview entry carries the estimate it WOULD be created with
                # — the one a task remembers in `sidecar` — because that is what
                # opening the day would actually write, and a preview that
                # under-reported the day's total would be answering a different
                # question from the one asked.
                "estimate_minutes": f.get("estimate_minutes"),
                "position": None,
                "done_at": None,
                "dropped_at": None,
                # Always null in a preview: nothing that has not been created
                # can have been moved. Present because this dict is a second
                # hand-written spelling of `_day_entry_dto` and the docstring
                # promises callers ONE entry shape.
                "rolled_to": None,
                # Both null in a preview, for the reason `rolled_to` is: a row
                # that does not exist has not been worked and has had nothing
                # decided about it. Present for the one-shape promise above.
                "worked_seconds": None,
                "capped": None,
                "created_at": None,
            }
            for f in pending
        ]

    def _snapshot_for(self, day: str, existing) -> list[dict[str, Any]]:
        """The entries a first open of `day` should create, in order. Called
        under the lock; writes nothing itself.

        `existing` is what the day already holds — a day whose first write was a
        hand-add is snapshotted on its first open all the same, so the snapshot
        has to MERGE with those rows rather than land beside them. Nothing here
        is proposed for a task or a note the day already carries.

        Order is habits, then due-today, then carried — what the owner does every
        day, the day's own work, and yesterday's leftovers last. A PAST day gets
        no habits at all and so leads with due-today; `_habit_entries_for` makes
        that call, not this function.

        WHAT IS ALREADY LATE IS NOT DERIVED, and that is the point of the
        function rather than an omission. A deadline you set for today is a
        commitment you made and the day is entitled to hold you to it; a deadline
        you have already missed is a decision you have NOT made yet, and putting
        it back on every morning makes the decision for you — badly, by deferring
        it another day at the cost of a row you read and skip. So an overdue task
        is offered rather than placed: `TodayView`'s suggestion strip picks it up
        the moment it is not on the day (its groups are built over the tasks the
        day does not already hold), and choosing it is then an act the owner
        performs. Nothing is lost — the task is still on its list, still overdue
        everywhere overdue is shown, and still one press from the day.

        The carry is untouched, and it is worth saying why it does not quietly
        put the same rows back. `_carry_into` takes only `source="user"` rows, so
        a task the OWNER chose yesterday and did not finish still follows them;
        one that merely landed on yesterday by derivation never did.

        Within the task group the sort key is (due, summary, collection_href,
        uid), which is total — a UID is unique per COLLECTION, not globally
        (invariant #4), so the href has to be in the key for two lists holding
        the same UID to have a defined order — and a total key is what makes the
        snapshot for a given cache reproducible.
        """
        # Resolved once for the whole scan rather than per task: it is a
        # settings read, and every DUE in the account buckets against the same
        # zone.
        home = self._home_tz()
        due_today: list[Any] = []
        for col in store.get_collections(self._conn):
            if "VTODO" not in (col["components"] or ""):
                continue
            # One sidecar read per COLLECTION, hoisted out of the row loop for
            # the reason `home` is hoisted out of the whole scan: it is the same
            # answer for every row, and asking per task would be one query per
            # task in every list under the global lock.
            side = store.get_all_sidecar(self._conn, col["href"])
            # Every task in every list, raw_ics and all — the same read
            # `list_tasks` does on each render. Affordable HERE because the
            # opened marker makes it happen at most once per day, rather than
            # once per view of the day.
            for it in store.get_items(self._conn, col["href"]):
                if it["component"] != "VTODO":
                    continue
                # Parked work is set aside, and a day that derived it anyway
                # would be putting back exactly what the owner took out — the
                # same failure narrowing the overdue rule fixed, with a worse
                # excuse, since parking is an explicit act rather than a
                # deadline slipping. `sqlite3.Row` has no `.get`, hence the
                # two-step.
                s = side.get(it["uid"])
                if s is not None and s["parked_at"]:
                    continue
                # Subtasks ride with their parent: a checklist item is not a
                # separate thing to plan, and admitting them would let one
                # parent task drag twenty rows into the day.
                if it["related_parent"]:
                    continue
                if (it["status"] or "") in ("COMPLETED", "CANCELLED"):
                    continue
                key = _due_day(it["due"], is_date=bool(it["due_is_date"]), zone=home)
                if not key:
                    continue            # undated work is chosen, never snapshotted
                # `!=` rather than a second bucket for `key < day`: what is
                # already late is offered by the suggestion strip, never placed
                # (see the docstring). An EQUALITY test also means a task due
                # next Tuesday and one that was due last Tuesday are refused by
                # the same line, which is the honest shape — neither is this
                # day's work until the owner says it is.
                if key != day:
                    continue
                due_today.append(it)
        # Habits lead the snapshot, ahead of due-today: they are what the owner
        # decided to do EVERY day, so they read first, before whatever
        # merely happens to fall due. Empty for a past day — this call is the
        # ONLY habit-minting path a first open has, so the refusal inside it is
        # what keeps `POST /api/day/2020-01-01/open` from writing today's rules
        # into 2020. They dedupe on `habit_id` inside `_habit_entries_for` rather
        # than through the `seen` set below — an occurrence names no task, so it
        # has no (collection_href, uid) to be identified by.
        out: list[dict[str, Any]] = self._habit_entries_for(day, existing)
        # Seeded from the rows the day already has, so the dedupe below covers
        # them too — otherwise a task hand-added this morning would get a second
        # row the moment the snapshot ran, and two rows for one task means two
        # checkboxes that disagree about whether it is done. DROPPED rows count:
        # the snapshot re-proposing something the owner just dropped is the very
        # resurrection the opened marker exists to prevent.
        seen: set[tuple[str, str]] = {
            (r["collection_href"], r["uid"]) for r in existing if r["kind"] == "task"
        }
        # Notes have no (list, uid) to be identified by — `add_day_entry` treats
        # the exact text as a note's identity on a day, so the carry below does
        # too.
        note_titles: set[str] = {r["title"] for r in existing if r["kind"] == "note"}
        for it in sorted(due_today, key=_snapshot_order):
            self._append_task_entry(out, seen, it["collection_href"], it["uid"], "auto")
        for row in self._carry_into(day):
            # Explicit per-kind dispatch, ending in a `continue` rather than in a
            # task. This was "note, and EVERYTHING ELSE IS A TASK", which is a
            # trap the moment a third kind exists: a habit occurrence reaching
            # the task arm is laundered into
            # {kind: "task", collection_href: None, uid: None} — a permanent
            # blank row nothing can join back to a task, on a day the owner
            # cannot explain — and it also puts (None, None) into `seen`, so the
            # NEXT such row is silently swallowed by the dedupe instead. One
            # unknown kind would therefore produce one corrupt row plus a
            # disappearance, and neither would raise anything to notice.
            #
            # `_carry_into` already keeps habit occurrences out (they are
            # source="habit", and only source="user" carries), so this is the
            # second of two guards that fail for different reasons: that one
            # states the rule "an occurrence never carries", this one states
            # "a kind this function does not understand is not a task".
            kind = row["kind"]
            if kind == "note":
                if row["title"] in note_titles:
                    continue
                note_titles.add(row["title"])
                out.append({
                    "entry_id": uuid.uuid4().hex, "kind": "note",
                    "title": row["title"], "source": "carried",
                    # A note has no task behind it and so nothing to remember an
                    # estimate for it — the row being carried is the only place
                    # yesterday's answer exists. Dropping it here would make the
                    # ritual ask again about the same jot every morning it
                    # survived.
                    "estimate_minutes": row["estimate_minutes"],
                })
                continue
            if kind == "task":
                self._append_task_entry(
                    out, seen, row["collection_href"], row["uid"], "carried",
                    estimate=row["estimate_minutes"],
                )
                continue
            # Everything else — a habit occurrence that somehow reached here, or
            # a kind added after this loop was written — carries nothing. This
            # arm is the point of the dispatch: it is what the task branch used
            # to swallow.
            continue
        return out

    def _remembered_estimate(self, href: str, uid: str) -> int | None:
        """The estimate this task remembers, from `sidecar`. Called under the lock.

        The sidecar is the task's LAST estimate, not any day's: planning a task
        copies this onto that day's entry (see `insert_day_entry`), and from
        then on the entry is what that day counts. So this only ever decides
        what a NEW entry starts at, which is the whole point — the ritual should
        not ask twice about a task that comes round every week.
        """
        row = store.get_sidecar(self._conn, href, uid)
        return row["estimated_minutes"] if row else None

    def _append_task_entry(
        self,
        out: list[dict[str, Any]], seen: set[tuple[str, str]],
        href: str, uid: str, source: str, estimate: int | None = None,
    ) -> None:
        """Add one task entry unless (collection, uid) is already in the plan.

        `estimate` is what the row should start at, and the two callers mean
        different things by it. A CARRIED row passes the estimate the entry it
        is carrying already had — the most direct reading of "this is the same
        piece of work, moved" — while a derived row passes nothing and falls
        back to what the task itself remembers.

        The dedupe is what stops a task appearing twice on the same day: a task
        due today that the owner also chose on the last planned day qualifies
        under both rules, and two rows for one task means two checkboxes that
        disagree about whether it is done. (collection_href, uid) is the identity of a
        task everywhere in this app — a UID is unique per COLLECTION, not
        globally (invariant #4) — so the same UID in two lists is two entries,
        deliberately.
        """
        key = (href, uid)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "entry_id": uuid.uuid4().hex, "kind": "task",
            "collection_href": href, "uid": uid, "source": source,
            "estimate_minutes": (
                estimate if estimate is not None
                else self._remembered_estimate(href, uid)
            ),
        })

    def _carry_into(self, day: str) -> list[Any]:
        """Rows from the most recent prior plan that should follow the owner
        into `day`. Called under the lock.

        Only source=user entries carry, and a carried entry deliberately carries
        exactly once: a task the owner chose on Monday and then ignored on
        Tuesday has been declined, and following them all week is how a plan
        turns into a list nobody reads.

        AN AUTO ENTRY DOES NOT CARRY, and the reason for that changed when
        overdue work stopped being derived. It used to be redundancy — the task
        was still due or still late, so the next morning's snapshot picked it up
        again, and carrying it as well would have given one task two rows on one
        day. Now nothing picks it up: a task due yesterday is overdue today, and
        `_snapshot_for` derives only what is due on the day itself. So the row
        neither follows the owner into today nor reappears on it; the suggestion
        strip offers it, with everything else that is late.

        That is the intended shape rather than a hole left by the change. An auto
        entry is a proposal the DAY made and the owner did not act on, and
        carrying it would be the day making the same proposal a second time
        without being asked — which is the behaviour narrowing the derivation
        exists to stop. Anything the owner actually CHOSE is source="user" and
        still follows them, so no decision is dropped by this rule.

        Done and dropped entries stay behind, and a task entry whose task is no
        longer an open VTODO stays behind too — completed elsewhere, cancelled,
        or gone from the wire entirely. The ENTRY on its own day survives all of
        that (no FK, by design); what must not happen is carrying a finished or
        vanished task forward into a day it was never planned for.

        The most recent prior day is taken as-is, even when nothing survives the
        filter. Skipping an empty day to reach an older one would resurrect
        entries the owner already left behind once.
        """
        start = date.fromisoformat(day)
        # Saturated at the calendar's floor rather than subtracted blindly:
        # `day_key` admits any real date, and for one within the look-back of
        # 0001-01-01 the subtraction is an OverflowError — not a ValueError, so
        # `_check_day` did not map it and POST /api/day/{day}/open answered 500
        # where every other bad day key answers 422. The same clamp
        # `review_day` makes at the ceiling.
        first = (
            (start - timedelta(days=_CARRY_LOOKBACK_DAYS)).isoformat()
            if start.toordinal() > _CARRY_LOOKBACK_DAYS else date.min.isoformat()
        )
        planned = store.get_day_range(self._conn, first, day)   # `day` is exclusive
        if not planned:
            return []
        out = []
        for row in planned[max(planned)]:
            # `rolled_to` alongside done and dropped, and it is load-bearing
            # rather than tidy: a row the owner deliberately moved to Thursday
            # has been decided about, and without this line the automatic carry
            # would ALSO pull it into tomorrow — so they would find two of it,
            # one from their decision and one from the safety net that exists
            # for when they make none.
            if (row["source"] != "user" or row["done_at"] or row["dropped_at"]
                    or row["rolled_to"]):
                continue
            if row["kind"] == "task":
                item = store.get_item(self._conn, row["collection_href"], row["uid"])
                if item is None or item["component"] != "VTODO":
                    continue
                if (item["status"] or "") in ("COMPLETED", "CANCELLED"):
                    continue
                # Parked since it was planned. Following the owner into today
                # would undo the setting-aside a day after they did it, which is
                # the one thing parking has to be proof against — and unlike the
                # tests above this is reversible, so the row comes back the
                # moment they un-park it. One `get_sidecar` per surviving row
                # rather than a per-collection read: this walks ONE prior day,
                # which holds a handful of rows spread over any number of lists.
                side = store.get_sidecar(self._conn, row["collection_href"], row["uid"])
                if side is not None and side["parked_at"]:
                    continue
            out.append(row)
        return out

    def _habit_entries_for(self, day: str, existing) -> list[dict[str, Any]]:
        """The habit occurrences `day` should be given, in habit order. Called
        under the lock; writes nothing itself.

        The whole rule lives here, in one place, so the first snapshot and every
        later top-up cannot drift apart: a day not already past
        (`_habit_minting_allowed`), an ACTIVE habit (`paused_at IS NULL`) whose
        `days` include this day key's weekday, and no row for that habit on the
        day yet. Pausing therefore hides a habit from FUTURE days only — the rows
        it already put on past days are ordinary day_plan entries and nothing
        here can reach them.

        THE PASTNESS GATE BELONGS TO THIS FUNCTION, not to the two callers. It
        used to sit at a call site, and only one of the two asked it: `open_day`
        gated its top-up branch, while the first snapshot of a never-opened day
        reached here through `_snapshot_for` and minted freely. So
        `POST /api/day/2020-01-01/open` wrote TODAY's rules into a day that had
        already happened. That is worse than it sounds: an occurrence's row is
        the ONLY record of it anywhere — no VTODO behind it to disagree — so
        afterwards nothing can tell a backfilled one from a kept one, and the
        phantom un-ticked rows read as MISSES in `review_day`'s habits arm and in
        the "n of m this week" the tab counts off these same rows. A first open
        of a past day still snapshots its TASKS — those re-derive from the wire
        and claim nothing about what the owner intended that day — but it mints
        no habits.

        Presence is read off `existing`, the rows the day already holds, and a
        DROPPED row COUNTS AS PRESENT — the same rule `_snapshot_for`'s `seen`
        set follows. A habit dropped this morning must not come back this
        afternoon: that is the resurrection the opened marker exists to prevent,
        and on the top-up path it would happen on every visit to the tab rather
        than once.
        """
        if not self._habit_minting_allowed(day):
            return []
        present = {r["habit_id"] for r in existing if r["habit_id"]}
        out: list[dict[str, Any]] = []
        for habit in store.list_habits(self._conn):
            # `list_habits` returns paused habits too — the screen that un-pauses
            # them needs to see them — so the filter belongs to this rule, not to
            # the query.
            if habit["paused_at"] or habit["id"] in present:
                continue
            if not habit_runs_on(habit["days"], day):
                continue
            out.append({
                "entry_id": uuid.uuid4().hex, "kind": "habit",
                # The title is COPIED onto the row, never joined at read time.
                # That copy is what lets the occurrence outlive its rule: delete
                # the habit and this day still says what the owner planned, with
                # only a dangling habit_id to show the rule is gone.
                "title": habit["title"], "habit_id": habit["id"],
                # Copied for the same reason the title is, and it is the reason
                # habits needed a column of their own: an occurrence has no wire
                # object to remember an estimate for it and never carries, so
                # without this the ritual would ask how long "Read" takes every
                # single morning.
                "estimate_minutes": habit["estimate_minutes"],
                # source="habit" is load-bearing, not a label. `_carry_into`
                # keeps only source="user" rows, so "an occurrence never carries
                # into the next day" falls out of this line for free —
                # tomorrow's occurrence is tomorrow's rule running again, never
                # today's leftover following the owner around.
                "source": "habit",
            })
        return out

    def set_day_ritual(
        self, day: str, *,
        capacity_minutes: int | None = None, committed: bool | None = None,
        shutdown: bool | None = None, reflection: str | None = None,
    ) -> dict[str, Any]:
        """Record what the owner says about a day: how long they will work, that
        they have begun, that they have finished, and how it went.

        REFUSED ON A PAST DAY, all four of them, and that is the same line
        `mcp/api.py::update_day_entry` draws for `done`. Every one of these is a
        statement about a day you can still act on: a capacity is a plan, and a
        shutdown performed on Thursday for Monday is not a record of Monday. A
        ritual that can be carried out afterwards is a form, not a boundary.

        It carries `_HABIT_MINT_GRACE_DAYS` of grace, and for exactly the reason
        habit minting does rather than as a softening of the rule: `home_timezone`
        is unset by default and the server is UTC in the ordinary deployment, so
        a browser in New York between 20:00 and midnight sends a key the server
        already calls yesterday. Without the grace the shutdown ritual would be
        refused every evening after dinner — which is when it is meant to happen.

        `committed` and `shutdown` are tri-state booleans for the reason
        `patch_day_entry`'s `done` is one: None means "not sent", and False is a
        real value that clears the stamp, which is how a day is re-opened after
        being closed too early.
        """
        day = day_key(day)
        if not self._ritual_writable(day):
            raise ValueError(
                f"{day} has already happened; a capacity, a start and a shutdown "
                "are statements about a day you can still act on"
            )
        fields: dict[str, object] = {}
        if capacity_minutes is not None:
            # -1 clears, the same sentinel and the same reason as an estimate: 0
            # is a real capacity ("I am not working today") and None already
            # means "not sent".
            fields["capacity_minutes"] = (
                None if capacity_minutes < 0 else int(capacity_minutes)
            )
        if committed is not None:
            fields["committed_at"] = _stamp() if committed else None
        if shutdown is not None:
            fields["shutdown_at"] = _stamp() if shutdown else None
        if reflection is not None:
            # An emptied reflection clears rather than storing "", so "nothing
            # written" has one representation.
            fields["reflection"] = reflection.strip() or None
        with self._lock:
            # The written row is deliberately not read back here: `_day_plan_dto`
            # reads the ritual itself, and an empty `fields` writes nothing at
            # all (see `store.set_day_ritual`) so there may be no row to read.
            store.set_day_ritual(self._conn, day, **fields)
            entries = store.get_day_entries(self._conn, day)
            opened = store.day_is_opened(self._conn, day)
            dto = self._day_plan_dto(day, entries, opened)
        # Only when something was written — a PATCH with an empty body is a read,
        # and an event for it would have every other tab refetch for nothing.
        if fields:
            self._publish({"type": "day_updated", "day": day})
        return dto

    def roll_entry(self, day: str, entry_id: str, to_day: str) -> dict[str, Any] | None:
        """Move one entry to another day. None for an entry_id this day lacks.

        MOVES NOTHING. It creates an entry on `to_day` and stamps this one with
        where it went — because the day that planned the work is still the day
        that planned it, and a log you can rewrite by rescheduling is not a log.
        `rolled_to` is deliberately not `dropped_at`: "doing it Thursday" and
        "decided against it" are different answers, and a look-back that can
        tell them apart is worth more than one that files both under abandoned.

        Idempotent, and for free: `add_day_entry` already answers with the row
        that is there for the same task, or the same note text, on the same day.
        So a retried roll lands on one entry, and a second roll of the same row
        to the same day changes nothing.

        FROM a past day is allowed. That manufactures no record of the past day
        — the new row lands on a day that has not happened — and the planning
        ritual's leftovers step needs exactly this when a shutdown was skipped.
        TO a past day is refused: an entry appearing on a finished day is the
        forgery every other rule here exists to prevent.

        A HABIT OCCURRENCE cannot be rolled. Tomorrow gets its own from the rule,
        so moving one would either duplicate it or fabricate an occurrence on a
        day the rule does not schedule — the thing `add_day_entry`'s kind check
        is the last line against. The refusal is explicit here so the message
        says why rather than surfacing that check's wording.
        """
        day = day_key(day)
        to_day = day_key(to_day)
        if to_day == day:
            raise ValueError(f"{entry_id} is already on {day}")
        if to_day < self._today():
            raise ValueError(
                f"{to_day} has already happened; work can only be moved forward"
            )
        with self._lock:
            row = store.find_day_entry(self._conn, day, entry_id=entry_id)
            if row is None:
                return None
            if row["kind"] == "habit":
                raise ValueError(
                    "a habit occurrence cannot be moved; tomorrow gets its own "
                    "from the rule"
                )
            if row["dropped_at"]:
                raise ValueError("a dropped entry has already been decided about")
        # OUTSIDE the lock, because `add_day_entry` takes it itself — and it is
        # the one that has to resolve the list, dedupe and publish. Nothing can
        # race in between that matters: a second roll of the same row finds the
        # entry already there and answers it.
        self.add_day_entry(
            to_day, entry_id=uuid.uuid4().hex, kind=row["kind"],
            list_id=_slug(row["collection_href"]) if row["collection_href"] else None,
            uid=row["uid"], title=row["title"],
            # The estimate travels with the work. A task's would arrive anyway
            # through the sidecar memory, but a NOTE remembers nothing — so
            # without this, "ring the bank, 15m" moved to Thursday arrives on
            # Thursday as an unestimated row, and the day it left is the only one
            # that ever knew how long it takes.
            estimate_minutes=row["estimate_minutes"],
        )
        with self._lock:
            moved = store.update_day_entry(
                self._conn, day, entry_id, rolled_to=to_day)
            dto = self._day_entry_dto(moved)
        self._publish({"type": "day_updated", "day": day})
        return dto

    def _ritual_writable(self, day: str) -> bool:
        """May the owner still make a statement about this day?

        Deliberately the same window as habit minting, sharing its constant. Two
        different pastness rules on one screen — one for what a day may be given
        and another for what may be said about it — would be two places to get
        the timezone reasoning right and one place to get it wrong.
        """
        return (
            date.fromisoformat(day)
            >= date.fromisoformat(self._today()) - timedelta(days=_HABIT_MINT_GRACE_DAYS)
        )

    def _habit_minting_allowed(self, day: str) -> bool:
        """May `day` be given habit occurrences at all?

        Today and later, plus one day of grace. Asked on BOTH paths that mint
        them — the first snapshot of a never-opened day and the top-up of an
        already-planned one — because it is asked from their single shared
        caller, `_habit_entries_for`. It used to be asked at one of the two call
        sites instead, and the other one wrote today's rules into days that had
        already happened.

        A past day is the record of what was intended at the time; writing
        today's rules into it is a forgery however small it is — and the same
        reason `mcp/api.py::_writable_day` refuses to plan a past day at all.

        The grace is deliberate and is not slack. `home_timezone` is unset by
        default and the server runs UTC in the ordinary deployment, so a browser
        in New York between 20:00 and midnight sends the key for a day the server
        already calls yesterday. Without the grace, habits would stop appearing
        every evening at 20:00 local and start again at midnight — a feature that
        dies every night, presenting as "habits are broken after dinner" rather
        than as the timezone bug it is. One day is enough for the case that
        matters: measured against the server's own UTC clock, a browser anywhere
        from UTC-12 to UTC+14 is never more than one calendar day behind it. And
        it costs only this — a genuinely stale tab, left open overnight, may add
        yesterday's habit rows to yesterday.
        """
        return (
            date.fromisoformat(day)
            >= date.fromisoformat(self._today()) - timedelta(days=_HABIT_MINT_GRACE_DAYS)
        )

    def _today(self) -> str:
        """The owner's calendar day, not necessarily the server's.

        `home_timezone` when they have set one; otherwise `datetime.now(None)`,
        this process's local clock, which is the honest fallback — it is what the
        deployment's own logs use and there is no better answer available when
        the setting is empty. `mcp/api.py::_today` answers the same question the
        same way for the connector.
        """
        return datetime.now(self._home_tz()).date().isoformat()

    def add_day_entry(
        self, day: str, *, entry_id: str, kind: str,
        list_id: str | None = None, uid: str | None = None,
        title: str | None = None, estimate_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Put a task or a note on a day by hand (source=user).

        Idempotent three ways, because this is the one route a client retries:
        the same entry_id, the same task, or the same note text on the same day
        all return the entry that is already there rather than a second row. The
        task and note lookups skip DROPPED entries (see store.find_day_entry) —
        having dropped something this morning, adding it back this afternoon has
        to work.

        kind="habit" is NOT accepted here, and that is the point of the check
        below rather than an omission. A habit occurrence is minted BY A RULE:
        `_habit_entries_for` decides which habits run on which day, from the day
        key's own weekday. A client able to hand one in could fabricate an
        occurrence on a day the rule does not schedule — a record of a habit
        having come round on a day it never did, indistinguishable afterwards
        from a real one, in the one table whose whole value is that it was
        written at the time.

        That check is the ONLY thing standing between an in-process caller and a
        forged occurrence. Nothing catches it further down, and this paragraph
        used to claim otherwise: it named `store.find_day_entry` as a second,
        cruder guard that "has no habit arm and would raise". Traced with the
        check removed, kind="habit" takes the else branch below, and
        `find_day_entry(conn, day, title=...)` queries the `kind='note' AND
        title=?` arm — it matches nothing and returns None, no exception — so
        control falls through to `insert_day_entry` and the bogus row LANDS,
        source="user" and habit_id=None, on a day no rule scheduled it for. The
        named fallback would have written the very thing it was credited with
        preventing. (`CreateDayEntry.kind` is a Literal, so an HTTP client is
        also refused at the edge — but the MCP tools and every other caller in
        this process arrive here directly, with only the line below in the way.)

        Raises ValueError (routes → 422) for a malformed day, an unknown kind,
        a task entry naming a list that does not resolve, an empty note, or an
        entry_id the day already uses for something else.
        """
        day = day_key(day)
        if kind not in ("task", "note"):
            raise ValueError(f"kind must be task or note, got {kind!r}")
        href: str | None = None
        if kind == "task":
            if not uid:
                raise ValueError("a task entry needs a uid")
            # Resolved, not trusted: an unresolvable list id would be stored as
            # a collection_href nothing can join back to, and the entry would
            # render forever as a task that cannot be opened, completed or
            # removed. `component="VTODO"` for the same reason every task route
            # passes it — an event calendar holds no task to point at.
            href = self.resolve_list(list_id, component="VTODO") if list_id else None
            if href is None:
                raise ValueError(f"unknown list {list_id!r}")
            # A task entry's text is the task's own SUMMARY, read live through
            # (list, uid). Storing a copy here would be a second title that goes
            # stale the moment the task is renamed.
            title = None
        else:
            title = (title or "").strip()
            if not title:
                raise ValueError("a note entry needs a title")
            uid = None
        with self._lock:
            existing = store.find_day_entry(self._conn, day, entry_id=entry_id)
            if existing is not None:
                # A replay presents the same entry again, so it matches and is
                # answered from the row that landed. A DIFFERENT entry under an
                # id this day already uses is a client bug, and both silent
                # answers to it are wrong: inserting collides with the primary
                # key (an IntegrityError, which no handler maps — a 500), and
                # handing back the row that is there tells the caller their task
                # was added when a different one was. Refused instead, the same
                # way and for the same reason as `book_slot`'s "client_id
                # already used".
                if (existing["kind"], existing["collection_href"],
                        existing["uid"], existing["title"]) != (kind, href, uid, title):
                    raise ValueError(f"entry_id {entry_id!r} is already used on {day}")
                return self._day_entry_dto(existing)
            existing = (
                store.find_day_entry(self._conn, day, collection_href=href, uid=uid)
                if kind == "task"
                else store.find_day_entry(self._conn, day, title=title)
            )
            if existing is not None:
                return self._day_entry_dto(existing)
            entries = store.get_day_entries(self._conn, day)
            # Appended at the end of the day. Computed from the rows already in
            # hand rather than with a MAX() query: a day holds a handful of
            # entries, and this call has just read all of them anyway.
            position = max((r["position"] or 0.0 for r in entries), default=0.0) + 1.0
            # Adding to a day does NOT mark it opened. The marker means "the
            # automatic snapshot has been built", and writing it here suppressed
            # that snapshot forever: `open_day` short-circuits on the marker, so
            # a day whose first write was a hand-add never got its due-today
            # or carried rows at all — and the shipped client offers the
            # add box whether or not the open succeeded, so that was one failed
            # request away. The day still reports planned=true, through the
            # entries arm of `_day_plan_dto`.
            #
            # A stated estimate also TEACHES the task, exactly as
            # `patch_day_entry` does for one typed later: the sidecar is the
            # only "what it took last time" there is, and `smylte_plan_day` —
            # the one shipped caller that states an estimate on create — promises
            # the next day starts from it. It used to hold only if the number
            # arrived through a PATCH or a retried plan. `set_sidecar` carries
            # the live-item guard, so a vanished task teaches nothing.
            if kind == "task" and estimate_minutes is not None and href and uid:
                store.set_sidecar(
                    self._conn, href, uid, estimated_minutes=int(estimate_minutes))
            # One statement, so no `tx`: the connection is in autocommit (see
            # store.tx) and a lone INSERT is atomic by itself.
            row = store.insert_day_entry(
                self._conn, day=day, entry_id=entry_id, kind=kind, source="user",
                collection_href=href, uid=uid, title=title, position=position,
                # A task entry starts at what its task remembers; a note has
                # nothing to remember one, so it starts unestimated and the
                # ritual asks. Copied at insert time rather than joined — see
                # `insert_day_entry`.
                #
                # An estimate STATED by the caller wins over the remembered
                # one. It is the fresher statement about this particular day,
                # and the memory exists to save typing rather than to overrule
                # somebody who has already typed.
                estimate_minutes=(
                    int(estimate_minutes) if estimate_minutes is not None
                    else self._remembered_estimate(href, uid)
                    if kind == "task" and href and uid else None
                ),
            )
            dto = self._day_entry_dto(row)
        self._publish({"type": "day_updated", "day": day})
        return dto

    def patch_day_entry(
        self, day: str, entry_id: str, *,
        done: bool | None = None, dropped: bool | None = None,
        position: float | None = None, estimate_minutes: int | None = None,
        capped: bool | None = None,
    ) -> dict[str, Any] | None:
        """Tick, drop, reposition, estimate or cap one entry. None for an
        entry_id this day does not have (the route turns that into a 404).

        Dropping stamps a column; it never deletes the row. "I did not do this"
        is the single most useful thing a past day can tell you, and a DELETE
        would erase exactly that. It also keeps the entry out of the next day's
        carry-over, which is the other half of what dropping means.

        done=False / dropped=False clear their stamps — the undo path — which is
        why these arrive as tri-state booleans rather than flags: None is "the
        client did not send this field", and only the fields it did send reach
        the UPDATE.

        `done` belongs to the entries whose doneness exists NOWHERE ELSE — a
        note, and a habit occurrence, both of which live only in this table.
        Sending it for a TASK entry raises ValueError (routes → 422): a task
        already has one answer, its VTODO STATUS, that every client on the
        account can see. Dropping and repositioning apply to every entry.
        """
        day = day_key(day)
        fields: dict[str, object] = {}
        if done is not None:
            fields["done_at"] = _stamp() if done else None
        if dropped is not None:
            fields["dropped_at"] = _stamp() if dropped else None
        if position is not None:
            fields["position"] = float(position)
        if estimate_minutes is not None:
            # -1 CLEARS. `done` and `dropped` spell their undo with a real
            # `False`, but an int has no spare falsy value to borrow: 0 is a
            # legitimate estimate ("not worth counting") and None already means
            # "the client did not send this field". So the sentinel is explicit
            # rather than smuggled, and the edge model's lower bound is -1
            # precisely so this is the only negative that can arrive.
            fields["estimate_minutes"] = (
                None if estimate_minutes < 0 else int(estimate_minutes)
            )
        if capped is not None:
            # A statement about how this row will be WORKED, so it belongs to a
            # day that can still be worked: refused on a day that has run, the
            # same fence `set_day_ritual` keeps and for the same reason — a cap
            # written afterwards describes nothing that happened. The route
            # maps the ValueError to 422, as it does for `done` on a task.
            if not self._ritual_writable(day):
                raise ValueError(
                    f"{day} has already happened, so whether to stop at the "
                    f"estimate cannot be decided for it any more"
                )
            fields["capped"] = 1 if capped else 0
        with self._lock:
            # Read before write, because the rule below needs the entry's KIND —
            # and this is also the 404 check now. Nothing can land in between:
            # the service owns the one connection and serialises every access
            # behind this lock.
            row = store.find_day_entry(self._conn, day, entry_id=entry_id)
            if row is None:
                return None
            # Whether a TASK is done is its VTODO STATUS — the single answer the
            # Tasks pane, a phone and Thunderbird all read and write. A done_at
            # on a task entry would be a second answer, and the two disagree the
            # moment the task is ticked anywhere else. A note is the opposite
            # case: it exists nowhere but in the day, so its own stamp is the
            # only answer there is — and a habit occurrence is a note in this
            # respect, since ticking today's run is a fact about today and about
            # nothing on the wire. TodayView already routes a task row's checkbox
            # through `api.complete`; this closes the path rather than leaving a
            # column that silently records a lie.
            if done is not None and row["kind"] == "task":
                raise ValueError(
                    "done applies to a note or habit entry; a task's doneness "
                    "is its VTODO STATUS — complete the task instead"
                )
            # Estimating a TASK also teaches the task, so the next day that
            # plans it starts from this answer instead of asking again. Only a
            # task: a note and a habit occurrence have no sidecar row to teach —
            # a note is remembered by the carry, a habit by its rule.
            #
            # WRITE-through, never read-through, and that asymmetry is the whole
            # of it. The entry is what its day counts; this only moves where the
            # NEXT entry starts. Joining instead would make re-estimating in
            # March rewrite what January's plan said the work would take, which
            # is the same mistake a habit occurrence avoids by copying its title.
            if ("estimate_minutes" in fields and row["kind"] == "task"
                    and row["collection_href"] and row["uid"]):
                store.set_sidecar(
                    self._conn, row["collection_href"], row["uid"],
                    estimated_minutes=fields["estimate_minutes"],
                )
            row = store.update_day_entry(self._conn, day, entry_id, **fields)
            dto = self._day_entry_dto(row)
        # Only when something was actually written: a PATCH with an empty body
        # is a read, and an SSE event for it would have every other tab refetch
        # for nothing.
        if fields:
            self._publish({"type": "day_updated", "day": day})
        return dto

    def day_range(self, from_day: str, to_day: str) -> list[dict[str, Any]]:
        """Every planned day in [from_day, to_day), oldest first. `to_day` is
        EXCLUSIVE, like the calendar window bounds elsewhere in this service.

        Unplanned days are absent rather than present-and-empty — that is what
        the client draws as "not planned yet", and it keeps a month query to the
        days that exist. Raises ValueError (routes → 422) past
        DAY_RANGE_MAX_DAYS."""
        start, end = day_key(from_day), day_key(to_day)
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if span > DAY_RANGE_MAX_DAYS:
            raise ValueError(f"range is bounded to {DAY_RANGE_MAX_DAYS} days, asked for {span}")
        # The DTOs are built INSIDE the lock, and this is the whole point of the
        # shape below. `_day_plan_dto` is not a pure formatter — it reads
        # `day_ritual`, and through `_effective_capacity` the settings blob — so
        # building the list after the `with` block released two queries per day
        # onto the one shared sqlite3 connection with nothing serializing them.
        # `store.connect` opens it `check_same_thread=False` on the explicit
        # promise that this class serializes every access, and the route reaches
        # here through `asyncio.to_thread`, so two concurrent GET /api/day calls
        # really were two threads inside one connection: measured 59 unlocked
        # reads for a 59-day window (DAY_RANGE_MAX_DAYS allows 190), and four
        # concurrent callers raised `sqlite3.InterfaceError: bad parameter or
        # other API misuse` within seconds. The quieter failure was worse — a
        # row fetched for one day handed to the reader for another, so a day
        # reported someone else's capacity, commit time or reflection with no
        # error at all.
        #
        # Holding the lock over the whole build is only affordable because the
        # per-day queries are gone: `get_day_rituals` is the range twin of
        # `get_day_range` (it was written for this and had no caller), and the
        # settings blob is read once instead of once per day.
        with self._lock:
            planned = store.get_day_range(self._conn, start, end)
            rituals = store.get_day_rituals(self._conn, start, end)
            settings = store.get_settings(self._conn)
            # Every day the map holds is planned by definition: it is there
            # because it has a marker, entries, or both.
            return [
                self._day_plan_dto(d, rows, True, ritual=rituals.get(d), settings=settings)
                for d, rows in planned.items()
            ]

    # ── habits (the rules that put entries on a day) ─────────────────────────
    #
    # Four methods, and between them they are a habit's entire lifecycle. None of
    # them writes to day_plan: an occurrence is minted by `_habit_entries_for`
    # when a day is opened, and a day already written is nobody's to rewrite.
    #
    # Every write publishes {"type": "day_updated", …} and NEVER
    # settings_updated. App.tsx ignores settings_updated for its `rev` bump on
    # purpose — a UI preference has nothing to say about task data, and treating
    # it as a reason to refetch turned one drag of an appearance slider into a
    # request storm — so a habit change announced that way would reach the Today
    # tab only on the next manual reload, which is the one screen the change
    # exists for. `day_updated` is also what TodayView re-opens the day on, and
    # re-opening is what runs the habit top-up: that is how a habit created at
    # noon shows up at noon rather than tomorrow.

    @staticmethod
    def _habit_dto(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "days": row["days"],
            "paused_at": row["paused_at"],
            "position": row["position"],
            # What one run of this is expected to take. Copied onto every
            # occurrence at mint time, exactly as the title is — so this only
            # ever decides what FUTURE days start at, and changing it leaves
            # last Tuesday saying what last Tuesday said.
            "estimate_minutes": row["estimate_minutes"],
            "created_at": row["created_at"],
        }

    def list_habits(self) -> list[dict[str, Any]]:
        """Every habit in position order, PAUSED ONES INCLUDED — this is the list
        the settings screen edits, not the subset today happens to schedule."""
        with self._lock:
            return [self._habit_dto(r) for r in store.list_habits(self._conn)]

    def create_habit(
        self, *, title: str, days: str | None = None, position: float | None = None,
        estimate_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Define a habit. Raises ValueError (routes → 422) for an empty title or
        a `days` that is not a canonical weekday list.

        Nothing is put on any day here. The habit takes effect when a day is next
        opened — today included, through the top-up — so creating one is a single
        write that cannot half-succeed into a day.
        """
        title = (title or "").strip()
        if not title:
            raise ValueError("a habit needs a title")
        days = normalize_habit_days(days)
        with self._lock:
            if position is None:
                # Appended to the end of the list, computed from the rows in hand
                # rather than with a MAX() query — the same shape as
                # `add_day_entry`, and an account holds a handful of habits.
                position = max(
                    (h["position"] or 0.0 for h in store.list_habits(self._conn)),
                    default=0.0,
                ) + 1.0
            row = store.create_habit(self._conn, uuid.uuid4().hex, {
                "title": title, "days": days, "position": float(position),
                "estimate_minutes": estimate_minutes,
            })
            dto = self._habit_dto(row)
        self._publish({"type": "day_updated", "day": self._today()})
        return dto

    def update_habit(
        self, habit_id: str, *, title: str | None = None, days: str | None = None,
        paused: bool | None = None, position: float | None = None,
        estimate_minutes: int | None = None,
    ) -> dict[str, Any] | None:
        """Rename, reschedule, pause/resume or reorder one habit. None for an id
        that does not exist (the route turns that into a 404).

        `paused` is a tri-state boolean for the reason `patch_day_entry`'s `done`
        is one: None means "the client did not send this field", and False is a
        real value — resuming. Pausing stamps `paused_at`, which hides the habit
        from FUTURE snapshots and top-ups only. The occurrences it has already put
        on past days are ordinary day_plan rows that nothing in this section can
        reach, so a paused habit's history reads exactly as it did.

        A rename works the same way, and deliberately: an occurrence copies the
        title at the moment it is minted, so yesterday's row still says what the
        owner actually planned yesterday. Only occurrences minted from now on
        carry the new name.
        """
        fields: dict[str, object] = {}
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("a habit needs a title")
            fields["title"] = title
        if days is not None:
            fields["days"] = normalize_habit_days(days)
        if paused is not None:
            fields["paused_at"] = _stamp() if paused else None
        if position is not None:
            fields["position"] = float(position)
        if estimate_minutes is not None:
            # -1 clears, the same sentinel `patch_day_entry` uses and for the
            # same reason: 0 is a real estimate and None already means "not
            # sent", so an int needs one spelled out.
            fields["estimate_minutes"] = (
                None if estimate_minutes < 0 else int(estimate_minutes)
            )
        with self._lock:
            row = store.update_habit(self._conn, habit_id, fields)
            if row is None:
                return None
            dto = self._habit_dto(row)
        # Only when something was actually written — a PATCH with an empty body
        # is a read, and an event for it would have every other tab refetch for
        # nothing (`patch_day_entry` draws the same line).
        if fields:
            self._publish({"type": "day_updated", "day": self._today()})
        return dto

    def delete_habit(self, habit_id: str) -> bool:
        """Delete the RULE, and only the rule. False for an unknown id (route →
        404).

        The occurrences this habit already put on past days stay exactly as they
        are — their copied title, their done/dropped stamps, and a habit_id that
        now points at nothing. That dangling id is the design, not debris: those
        rows are the record that the owner planned this on those days, and a
        habit deleted in September must not be able to rewrite August. Nothing in
        this app ever DELETEs from day_plan, and a "tidy up orphaned occurrences"
        sweep would erase precisely the history this preserves.
        """
        with self._lock:
            gone = store.delete_habit(self._conn, habit_id)
        if gone:
            self._publish({"type": "day_updated", "day": self._today()})
        return gone

    # ── session revocation (explicit logout) ─────────────────────────────────
    def revoke_session(self, jti: str, expires_at: float) -> None:
        with self._lock:
            store.revoke_session(self._conn, jti, expires_at)

    def live_revocations(self) -> dict[str, float]:
        # `time` here is datetime.time (imported for the scheduling maths), so
        # take the epoch from datetime rather than the shadowed module.
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            return store.live_revocations(self._conn, now=now)

    # ── OAuth / MCP ──────────────────────────────────────────────────────────
    def oauth(self, fn, *args, **kwargs):
        """Run an OAuth store operation under the service lock.

        The MCP layer needs the SQLite connection, and this is how it gets one
        without a second handle on the database or its own idea of when it is
        safe to write. Everything else in this class serialises the same way;
        the token endpoint has no business being the exception.
        """
        with self._lock:
            return fn(self._conn, *args, **kwargs)

    # ── notifications ─────────────────────────────────────────────────────────
    def notifications(self, fn, *args, **kwargs):
        """Run one store function against the connection, under the lock.

        The notifier needs the delivery ledger (claim/settle), and the ledger is
        in the same single SQLite connection everything else shares. This is the
        same borrow `oauth` performs and for the same reason: a second handle on
        the database, or a second idea of when it is safe to write, is how the
        `InterfaceError` in this file's other long comment happened.

        Deliberately NOT held across the send. The caller claims under this
        lock, releases it, does the HTTP, then settles under it again — network
        I/O inside a process-wide RLock blocks every API route for the length of
        an HTTP timeout.
        """
        with self._lock:
            return fn(self._conn, *args, **kwargs)

    def sync_health(self) -> list[dict[str, Any]]:
        """Collections with a sync error standing — see `store.sync_health`."""
        with self._lock:
            return [dict(r) for r in store.sync_health(self._conn)]

    def bookings_created_since(self, stamp: str) -> list[dict[str, Any]]:
        """Bookings whose row was written at or after `stamp`."""
        with self._lock:
            return [dict(r) for r in store.bookings_created_since(self._conn, stamp)]

    # ── displays (the passive screens) ────────────────────────────────────────
    #
    # CRUD shaped exactly like the booking links above, because the two are the
    # same kind of object: a row whose primary key is a token that reaches data
    # without a session. `display_frame` is the one addition, and it is the only
    # method here a token can reach.
    #
    # Every route into this section is READ-ONLY about the account's data. That
    # is not a convention to be careful about — it is the feature. A display
    # takes no input, so there is no write for a token to reach even if one
    # leaked, and the single write anywhere in the path (`touch_display`) writes
    # a timestamp onto the display's own row.
    _DISPLAY_MODES = ("calendar", "habits", "now")
    _DISPLAY_PALETTES = ("color", "eink")
    # Under a minute is not a refresh rate, it is a fault: a browser page doing
    # it is just heat. A day is the ceiling only in the sense that a display
    # asking for longer can simply be pointed at its own timer — the frame
    # reports what it was told and nothing enforces it on a device.
    _REFRESH_MIN_S = 60
    _REFRESH_MAX_S = 86_400
    # An EINK panel has a floor its glass imposes, and it is three minutes.
    # Waveshare's own documentation for these screens says to set the refresh
    # interval to at least 180 seconds, and to sleep or power the panel down
    # between refreshes — "otherwise the screen will remain in a high voltage
    # state for a long time, which will damage the e-Paper and cannot be
    # repaired". A minute was on offer here, which on that hardware is the app
    # recommending its own destruction.
    #
    # It is not a preference and so it is not a preference to set. A colour
    # display — an old tablet, an LCD in a hallway — has none of this and keeps
    # the 60s floor, because none of it is true of a backlight.
    _REFRESH_MIN_EINK_S = 180

    @staticmethod
    def _refresh_floor(palette: str | None) -> int:
        return (TaskService._REFRESH_MIN_EINK_S if palette == "eink"
                else TaskService._REFRESH_MIN_S)

    def list_displays(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._display_dto(r) for r in store.list_displays(self._conn)]

    def list_displays_one(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = store.get_display(self._conn, token)
            return None if row is None else self._display_dto(row)

    def _display_dto(self, row, *, with_token: bool = True) -> dict[str, Any]:
        """One display, as the settings screen sees it.

        The token IS returned here, unlike the notification bot token beside it,
        and the difference is what each one is FOR. A bot token is a credential
        the owner never needs to see again once it is stored; a display token is
        a URL they have to be able to read off the screen and type into a panel,
        and re-issuing it is the only alternative to showing it. It is therefore
        exactly as secret as the settings page it is drawn on.
        """
        dto = {
            "name": row["name"],
            "mode": row["mode"],
            "palette": row["palette"],
            "calendars": json.loads(row["calendars"] or "[]"),
            "lists": json.loads(row["lists"] or "[]"),
            "hide_done_habits": bool(row["hide_done_habits"]),
            "hide_done_tasks": bool(row["hide_done_tasks"]),
            # Clamped to the palette's floor on the way OUT, which is the
            # safety net rather than the policy. A display stored at 60s before
            # the eink floor existed would otherwise go on telling a panel to
            # refresh every minute forever; no migration reaches a row nobody
            # edits, and this does. The write path above is what makes the
            # number the owner sees agree with it.
            "refresh_seconds": max(
                row["refresh_seconds"],
                TaskService._refresh_floor(row["palette"])),
            "panel_width": row["panel_width"],
            "panel_height": row["panel_height"],
            "rotation": row["rotation"],
            # Whether a month grid is worth drawing at the panel size the owner
            # gave. Answered by the RENDERER's own predicate rather than by
            # arithmetic repeated here or in the browser — a 2.9" panel is a
            # 39px column, and a screen that draws seven of those looks broken
            # rather than misconfigured. Null when there is nothing to judge:
            # no size set, or a mode that has no grid to not fit.
            #
            # Asked about the canvas the grid is LAID OUT on, which for a
            # quarter turn is the panel transposed — `_compose` builds
            # `(height, width)` at 90 and 270 so the month is laid out the way a
            # reader sees it and rotated at the end. Asking about the raw
            # framebuffer instead let Settings call a portrait-mounted 4.2"
            # panel fine and the panel itself then draw "This screen is too
            # small for a month", which is the one disagreement this shared
            # predicate exists to prevent.
            "panel_too_small": (
                None if row["mode"] != "calendar"
                or not row["panel_width"] or not row["panel_height"]
                else not display_render.month_grid_fits(
                    *((row["panel_height"], row["panel_width"])
                      if row["rotation"] in (90, 270)
                      else (row["panel_width"], row["panel_height"])))
            ),
            "enabled": bool(row["enabled"]),
            "last_seen_at": row["last_seen_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if with_token:
            dto["token"] = row["token"]
            # The page a panel opens, absolute — the Windows client serves the
            # app from localhost and has nothing but the token otherwise. The
            # same rule as the booking link's `url`, and absent with the token
            # for the same reason: a frame must not carry its own credential.
            dto["url"] = self._public_page_url(f"/display/{row['token']}")
        return dto

    def _normalize_display_fields(
        self, fields: dict[str, Any], existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate/canonicalize display fields. Raises ValueError (routes → 422).

        `existing` is the display as it stands, for a PATCH: some rules depend
        on the row this write is landing on rather than on the write alone —
        see the refresh floor, which is a property of the palette the display
        ends up with.
        """
        out = dict(fields)
        if "name" in out:
            out["name"] = (out["name"] or "").strip()
            if not out["name"]:
                raise ValueError("a display needs a name")
        for key, allowed in (("mode", self._DISPLAY_MODES),
                             ("palette", self._DISPLAY_PALETTES)):
            if key in out and out[key] not in allowed:
                raise ValueError(f"{key} must be one of {', '.join(allowed)}")
        for key in ("calendars", "lists"):
            if key in out:
                ids = out[key] or []
                if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                    raise ValueError(f"{key} must be a list of collection ids")
                # Stored as given rather than resolved to hrefs. A display may
                # legitimately name a collection that does not exist yet or has
                # gone away — the same tolerance `hidden_calendars` has — and
                # resolving here would turn a rename on the wire into a display
                # that silently shows everything.
                out[key] = json.dumps(ids)
        # The floor depends on what the display will BE once this write lands,
        # not on what it is now — flipping a screen to eink is exactly the write
        # that has to start respecting the panel's own limit.
        palette = out.get("palette") or (existing or {}).get("palette") or "color"
        floor = self._refresh_floor(palette)
        if "refresh_seconds" in out:
            seconds = int(out["refresh_seconds"])
            if not floor <= seconds <= self._REFRESH_MAX_S:
                raise ValueError(
                    f"refresh_seconds must be between {floor} and "
                    f"{self._REFRESH_MAX_S}")
            out["refresh_seconds"] = seconds
        elif "palette" in out and existing:
            # Switching an existing display to eink, without saying anything
            # about its interval. Refusing the write would be refusing a change
            # the owner DID make because of a value they did not touch, so the
            # interval comes up to the floor as part of the same write and the
            # DTO reports it — Settings shows 3 minutes the moment the palette
            # flips, rather than a 422 about a field that is not on screen.
            if (existing.get("refresh_seconds") or 0) < floor:
                out["refresh_seconds"] = floor
        for key in ("panel_width", "panel_height"):
            if key in out and out[key] is not None:
                px = int(out[key])
                # The floor is legibility and the ceiling is memory: the image
                # renderer allocates width×height, and an unbounded pair here is
                # an out-of-memory on an authenticated route.
                if not 100 <= px <= 4096:
                    raise ValueError(f"{key} must be between 100 and 4096 pixels")
                out[key] = px
        if "rotation" in out:
            if int(out["rotation"]) not in (0, 90, 180, 270):
                raise ValueError("rotation must be 0, 90, 180 or 270")
            out["rotation"] = int(out["rotation"])
        for key in ("hide_done_habits", "hide_done_tasks", "enabled"):
            if key in out:
                out[key] = int(bool(out[key]))
        return out

    def create_display(self, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            token = secrets.token_urlsafe(32)
            store.create_display(
                self._conn, token, self._normalize_display_fields(fields))
        self._publish({"type": "display_created", "display": token})
        return self.list_displays_one(token)

    def update_display(self, token: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            # Read the row FIRST: the refresh floor is a property of the palette
            # the display ends up with, and a PATCH that flips it to eink says
            # nothing about the interval it is about to make illegal.
            current = store.get_display(self._conn, token)
            if current is None:
                return None
            row = store.update_display(
                self._conn, token,
                self._normalize_display_fields(fields, dict(current)))
            if row is None:
                return None
        self._publish({"type": "display_updated", "display": token})
        return self.list_displays_one(token)

    def rotate_display_token(self, token: str) -> dict[str, Any] | None:
        """Re-key a display whose URL got out, keeping the display itself."""
        with self._lock:
            row = store.rotate_display_token(
                self._conn, token, secrets.token_urlsafe(32))
            if row is None:
                return None
            dto = self._display_dto(row)
        self._publish({"type": "display_updated", "display": dto["token"]})
        return dto

    def delete_display(self, token: str) -> bool:
        with self._lock:
            ok = store.delete_display(self._conn, token)
        if ok:
            self._publish({"type": "display_deleted", "display": token})
        return ok

    def display_frame(self, token: str) -> dict[str, Any] | None:
        """Everything one display shows, right now. The only call a token reaches.

        None for an unknown OR a disabled display, deliberately collapsed into
        one answer: the route turns both into the same 404, so switching a
        display off is indistinguishable from never having made it. The
        alternative — 403 for disabled — tells whoever holds a revoked URL that
        it used to be real, which is the one fact they can act on.

        NOTHING here opens a day. `open_day(create=False)` is a pure read and
        `preview_day` writes nothing at all, so a screen on a wall polling every
        five minutes cannot manufacture a plan the owner never made. That is not
        an optimisation: the day plan is worth keeping only while it records
        what was actually intended, and a panel in a hallway intends nothing.
        The same rule the MCP connector is held to, for the same reason.
        """
        with self._lock:
            row = store.get_display(self._conn, token)
            if row is None or not row["enabled"]:
                return None
            display = self._display_dto(row, with_token=False)
            frame = self._build_display_frame(display)
            # Last, and inside the lock: a display that got its frame is a
            # display that was seen. It is deliberately not awaited on, checked
            # or allowed to fail the read — see `store.touch_display`.
            store.touch_display(self._conn, token)
        return frame

    def _build_display_frame(self, display: dict[str, Any]) -> dict[str, Any]:
        """The frame one display's settings produce. Caller holds the lock.

        Shared by the token route and by the developer preview, so the thing
        being previewed is the thing that ships rather than a second renderer
        that agrees with it today.
        """
        settings = store.get_settings(self._conn)
        day = self._today()
        language = settings.get("language") or "en"
        time_format = settings.get("time_format") or "12h"
        # ONE zone for the whole display. `_today` above already reads it — the
        # grid's own "today" has always been the owner's day — so an event
        # bucketed by anything else would be placed against a grid drawn in a
        # different zone. None means the process's own, exactly as in `_due_day`
        # and `_today`, which is why an account whose server is not in its own
        # zone wants `home_timezone` set.
        zone = self._home_tz()
        # `habits` and `now` are two faces of the same question — what is on
        # today — so they take the same rows, from the same reader, honouring the
        # same list allowlist. Only the shape of the answer differs, and that is
        # decided in `frame.build_frame` rather than here.
        if display["mode"] in ("habits", "now"):
            sources, rows, planned = self._display_day_rows(day, display)
            events = None
        else:
            sources, events = self._display_events(day, display, zone)
            rows, planned = None, True
        return display_frame_mod.build_frame(
            display=display, day=day, generated_at=_stamp(),
            language=language, time_format=time_format, zone=zone,
            sources=sources, events=events, rows=rows, planned=planned,
        )

    def preview_display_frame(self, fields: dict[str, Any]) -> dict[str, Any]:
        """A frame for a display that does not exist.

        For Settings → Developer, which draws every mode at every panel size so
        a layout can be checked against hardware nobody in the room owns.
        Making that use a real display would mean minting a live token — a
        credential that reaches this calendar with no session — in order to look
        at a layout, and then remembering to revoke it.

        So this is authed, takes the settings directly, and WRITES NOTHING: no
        row, no token, no `last_seen_at`. It reaches the same data the owner is
        already looking at on the screen that called it.

        The fields go through `_normalize_display_fields`, so a preview cannot
        ask for anything a real display could not be set to — including an
        interval under the e-ink floor.
        """
        settings = self._normalize_display_fields(dict(fields), existing=None)
        display = {
            "name": settings.get("name") or "Preview",
            "mode": settings.get("mode") or "calendar",
            "palette": settings.get("palette") or "color",
            "calendars": settings.get("calendars") or [],
            "lists": settings.get("lists") or [],
            "hide_done_habits": bool(settings.get("hide_done_habits", True)),
            "hide_done_tasks": bool(settings.get("hide_done_tasks", True)),
            "refresh_seconds": settings.get("refresh_seconds") or 300,
            "rotation": settings.get("rotation") or 0,
        }
        with self._lock:
            return self._build_display_frame(display)

    def _display_calendars(self, display: dict[str, Any]) -> list:
        """The collections one display draws from, honouring its allowlist.

        Empty means everything, matching `hidden_calendars`: a display made in
        March should show a calendar made in April without being edited. The
        account's ARCHIVED calendars are excluded either way — archiving is the
        owner saying a calendar is not part of their present, and a screen on
        the wall is as present as it gets.
        """
        wanted = set(display["calendars"])
        archived = set(store.get_settings(self._conn).get("archived_calendars") or [])
        out = []
        for row in store.get_collections(self._conn):
            if "VEVENT" not in (row["components"] or ""):
                continue
            slug = _slug(row["href"])
            if wanted and slug not in wanted:
                continue
            if slug in archived:
                continue
            out.append(row)
        return out

    def _display_events(
        self, day: str, display: dict[str, Any], zone: ZoneInfo | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The month grid's events, one record per day each one covers.

        A span is listed on every day it touches, exactly as `bucketByDay` does
        in the frontend: a conference that ran Monday to Friday is on the wall
        all week or it is misinformation by Tuesday. The walk is clipped to the
        grid at both ends, because another CalDAV client can trivially write an
        event that runs for years and stepping a day at a time to reach its
        DTEND would build records nothing draws.
        """
        grid = display_frame_mod.month_grid(day)
        first, last = grid[0][0], grid[-1][-1]
        # The QUERY window is wider than the grid; the DRAWN range below is not.
        #
        # `get_events_in_range` gates on a lexicographic compare of the stored
        # ISO string, so it selects by the day a value SPELLS while the bucketing
        # below places it by the day it means in the owner's zone. Those differ
        # by up to the offset gap, and the legal range runs from UTC+14
        # (Pacific/Kiritimati) to UTC-12 — 26 hours, which is two calendar days,
        # not one. Two days of slack at each end therefore covers every offset
        # that exists; the walk is still clamped to `first`/`last`, so nothing
        # outside the grid can be drawn and the extra rows cost only the
        # candidates they add.
        window_start = (date.fromisoformat(first) - timedelta(days=2)).isoformat()
        window_end = (date.fromisoformat(last) + timedelta(days=3)).isoformat()
        sources, out = [], []
        for row in self._display_calendars(display):
            href = row["href"]
            sources.append({
                "id": _slug(href),
                "name": row["displayname"] or _slug(href),
                "color": row["color"],
            })
            for ev in self.events_in_range(href, window_start, window_end):
                start_day = _event_day(
                    ev.get("start"), is_date=bool(ev.get("start_is_date")),
                    zone=zone)
                if not start_day:
                    continue
                end_day = _event_last_day(ev, start_day, zone=zone)
                cursor = max(start_day, first)
                stop = min(end_day, last)
                while cursor <= stop:
                    out.append({
                        "day": cursor,
                        "summary": ev.get("summary"),
                        "start": ev.get("start"),
                        "all_day": bool(ev.get("all_day")),
                        "source": _slug(href),
                        "continued": cursor != start_day,
                    })
                    cursor = (date.fromisoformat(cursor) + timedelta(days=1)).isoformat()
        return sources, out

    def _resolved_day_rows(self, day: str) -> tuple[list[dict[str, Any]], bool]:
        """Today's live rows with every task's title and doneness resolved off
        its VTODO, in plan order — and whether they are real or a preview.

        THE ONE RULE for "what is on the day, and is it done", shared by the
        wall display and the focus session so the two cannot disagree about a
        row. A task entry is a POINTER — the day plan stores no title and no
        done flag for one, because the VTODO is the single truth for both — so
        the join happens here, once, the same way `mcp/api.py::_entries_with_tasks`
        does it for the connector. COMPLETED and CANCELLED both count as done:
        neither is work left to do.

        Three kinds of row are left out, each for its own reason. Dropped and
        rolled rows are exactly what a day's RECORD needs and exactly what a
        queue does not — "I decided against this" is a thing to read in the
        look-back, not a line to work. And a task row whose VTODO has left the
        wire — completed and purged by another client, or its list deleted —
        outlives the task by design (there is no FK), but a row with no title
        is a blank line on a wall and an unnamed thing to focus on, so it is
        skipped rather than shown.

        Each row is the entry DTO plus `title` (resolved), `done` (resolved)
        and `href` (the task's collection, or None).
        """
        plan = self.open_day(day, create=False)
        planned = bool(plan["planned"])
        entries = plan["entries"] if planned else self.preview_day(day)
        out = []
        for entry in entries:
            if entry.get("dropped_at") or entry.get("rolled_to"):
                continue
            row = dict(entry)
            row["done"] = bool(entry.get("done_at"))
            row["href"] = None
            if entry["kind"] == "task":
                source_id = entry.get("list")
                href = self.resolve_list(source_id, component="VTODO") if source_id else None
                item = store.get_item(self._conn, href, entry["uid"]) if href else None
                if item is None:
                    continue
                row["title"] = item["summary"]
                row["done"] = item["status"] in ("COMPLETED", "CANCELLED")
                row["href"] = href
            out.append(row)
        return out, planned

    def _display_day_rows(
        self, day: str, display: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        """Today's rows as a wall draws them: `_resolved_day_rows` narrowed to
        the display's list allowlist and reduced to what a frame carries, plus
        the sources the chips are keyed by."""
        rows, planned = self._resolved_day_rows(day)
        wanted = set(display["lists"])
        # One read for every collection's name, not one per row: a day of twenty
        # entries would otherwise be twenty queries under the lock, on the app's
        # most frequently polled call.
        named = {r["href"]: (r["displayname"] or _slug(r["href"]))
                 for r in store.get_collections(self._conn)}
        names: dict[str, str] = {}
        out = []
        for row in rows:
            kind = row["kind"]
            source_id = row.get("list")
            if kind == "task":
                if wanted and source_id not in wanted:
                    continue
                names.setdefault(row["href"], named.get(row["href"]) or source_id)
            out.append({
                "kind": kind, "title": row["title"], "done": row["done"],
                "source_id": source_id if kind == "task" else None,
                "estimate_minutes": row.get("estimate_minutes"),
            })
        sources = [{"id": _slug(h), "name": n, "color": None} for h, n in names.items()]
        return sources, out, planned

    # ── focus: working the day's queue against a clock ────────────────────────
    #
    # The session is ANCHORS, NOT COUNTERS (schema.sql says why beside the
    # table). Every public method here does the same three things in the same
    # order — settle the running phase up to `now`, clamped to the phase's
    # remaining length; do what it was asked; write back and publish only if
    # something changed — and the settle is where the honesty lives: a phase
    # can credit at most its own length to a row, so a laptop closed overnight
    # records exactly one interval on the memo and not eight hours.
    #
    # The queue is the day's own order — habit rows first, then the rest, each
    # in plan order, which is the order the Today tab paints — and the cursor
    # is the row the session names as long as that row is still open. The
    # client paints what the server names and never substitutes its own idea
    # of "current": a tick on a phone moves the cursor here on the next
    # transition, and the surface asks for one (`sync`) when it sees the row it
    # was showing has been finished elsewhere.

    _FOCUS_PHASE_KEY = {
        "focus": "focus_interval_minutes",
        "break": "focus_break_minutes",
        "long_break": "focus_long_break_minutes",
    }

    @staticmethod
    def _focus_dto(row) -> dict[str, Any]:
        return {
            "day": row["day"],
            "phase": row["phase"],
            "phase_length_s": row["phase_length_s"],
            "phase_elapsed_s": row["phase_elapsed_s"],
            "running_since": row["running_since"],
            "intervals_done": row["intervals_done"],
            "entry_id": row["entry_id"],
            "passed": _passed_list(row["passed"]),
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "updated_at": row["updated_at"],
        }

    def _focus_load(self, day: str) -> dict[str, Any] | None:
        row = store.get_focus_session(self._conn, day)
        if row is None:
            return None
        s = {k: row[k] for k in row.keys()}
        s["passed"] = _passed_list(s["passed"])
        return s

    @staticmethod
    def _focus_snapshot(s: dict[str, Any]) -> tuple:
        return (
            s["phase"], s["phase_length_s"], s["phase_elapsed_s"], s["running_since"],
            s["intervals_done"], s["entry_id"], tuple(s["passed"]), s["ended_at"],
        )

    def _focus_store(self, day: str, before: tuple, s: dict[str, Any]):
        """Write the session back if it moved; either way, return the row."""
        if self._focus_snapshot(s) == before:
            return store.get_focus_session(self._conn, day)
        return store.update_focus_session(
            self._conn, day,
            phase=s["phase"], phase_length_s=s["phase_length_s"],
            phase_elapsed_s=s["phase_elapsed_s"], running_since=s["running_since"],
            intervals_done=s["intervals_done"], entry_id=s["entry_id"],
            passed=json.dumps(s["passed"]), ended_at=s["ended_at"],
        )

    @staticmethod
    def _focus_complete(s: dict[str, Any]) -> bool:
        return s["phase_elapsed_s"] >= s["phase_length_s"]

    def _focus_settle(
        self, day: str, s: dict[str, Any], now: datetime, *, keep_running: bool = False,
    ) -> int:
        """Credit the running phase up to `now` and stop the clock — or, with
        `keep_running`, re-anchor it at `now` so the clock carries on with the
        time so far banked. Returns the seconds credited to a ROW, which is
        zero on a break, on a paused session, and on an empty queue.

        THE CLAMP IS THE WHOLE FEATURE. The time since the anchor is capped at
        what the phase has left, so a phase credits at most its own length
        however long ago the anchor was set: closing the laptop mid-interval
        and coming back tomorrow credits the rest of that one interval and
        nothing more. There is no other guard against an inflated figure and
        there does not need to be.
        """
        since = s["running_since"]
        if not since:
            return 0
        elapsed = max(0, int((now - _parse_stamp(since)).total_seconds()))
        room = max(0, s["phase_length_s"] - s["phase_elapsed_s"])
        delta = min(elapsed, room)
        s["phase_elapsed_s"] += delta
        s["running_since"] = (
            _stamp_at(now) if keep_running and not self._focus_complete(s) else None
        )
        credited = 0
        if s["phase"] == "focus" and s["entry_id"] and delta > 0:
            if store.add_worked_seconds(self._conn, day, s["entry_id"], delta) is not None:
                credited = delta
        return credited

    def _focus_queue(self, day: str, s: dict[str, Any]) -> list[str]:
        """The open rows this session could work, in the order it would: habit
        rows first, then the rest, each in plan order; done and set-aside rows
        skipped. No second sort — the plan's order is the queue, exactly as
        `display/frame.py::build_now` has it, so reordering Today reorders the
        surface."""
        rows, _planned = self._resolved_day_rows(day)
        passed = set(s["passed"])
        live = [r for r in rows if not r["done"] and r["entry_id"] not in passed]
        habits = [r["entry_id"] for r in live if r["kind"] == "habit"]
        rest = [r["entry_id"] for r in live if r["kind"] != "habit"]
        return habits + rest

    def _focus_cursor(self, day: str, s: dict[str, Any]) -> str | None:
        queue = self._focus_queue(day, s)
        if s["entry_id"] in queue:
            return s["entry_id"]
        return queue[0] if queue else None

    def _focus_next_phase(
        self, s: dict[str, Any], now: datetime, *, skip_break: bool,
    ) -> None:
        """Finish the phase and start the next one, from `now`. Lengths are
        read from settings at THIS moment and frozen onto the row, so a
        preference changed mid-phase moves the next phase and never the one
        running. A long break comes round every N focus phases; N of 0 means
        never; and `skip_break` ("keep going") still counts the interval."""
        settings = self._focus_settings()
        if s["phase"] == "focus":
            s["intervals_done"] += 1
            every = settings["focus_long_break_every"]
            if skip_break:
                phase = "focus"
            elif every > 0 and s["intervals_done"] % every == 0:
                phase = "long_break"
            else:
                phase = "break"
        else:
            phase = "focus"
        s["phase"] = phase
        s["phase_length_s"] = 60 * settings[self._FOCUS_PHASE_KEY[phase]]
        s["phase_elapsed_s"] = 0
        s["running_since"] = _stamp_at(now)

    def get_focus(self, day: str) -> dict[str, Any] | None:
        """The day's session, ended or not, or None. A pure read."""
        day = day_key(day)
        with self._lock:
            row = store.get_focus_session(self._conn, day)
        return self._focus_dto(row) if row else None

    def start_focus(self, day: str) -> dict[str, Any]:
        """Begin working the day: a fresh session in its first focus phase,
        running from now, pointed at the first open row.

        Refused on a day that has run, on the ritual's own fence — a day is
        worked while it is running. And refused on a day nobody has planned: a
        session never opens a day, for the same reason a display and the
        connector never do (`_display_day_rows`, `mcp/api.py::_writable_day`)
        — the plan is worth keeping only while it records what was actually
        intended, and a clock intends nothing. Open it in Today first.

        Idempotent over a live session: a second Start — the other window, a
        retried request — returns the session that is running rather than
        resetting it. Only an ENDED session is replaced.
        """
        day = day_key(day)
        if not self._ritual_writable(day):
            raise ValueError(
                f"{day} has already happened; a day is worked while it is running"
            )
        now = _focus_now()
        with self._lock:
            existing = store.get_focus_session(self._conn, day)
            if existing is not None and not existing["ended_at"]:
                return self._focus_dto(existing)
            entries = store.get_day_entries(self._conn, day)
            if not (store.day_is_opened(self._conn, day) or entries):
                raise ValueError(f"{day} is not planned yet — open it in Today first")
            settings = self._focus_settings()
            store.put_focus_session(
                self._conn, day,
                phase="focus",
                phase_length_s=60 * settings["focus_interval_minutes"],
                phase_elapsed_s=0,
                running_since=_stamp_at(now),
                intervals_done=0,
                entry_id=None,
                passed="[]",
                started_at=_stamp_at(now),
                ended_at=None,
            )
            s = self._focus_load(day)
            assert s is not None
            row = store.update_focus_session(
                self._conn, day, entry_id=self._focus_cursor(day, s))
            dto = self._focus_dto(row)
        self._publish({"type": "focus_updated", "day": day})
        return dto

    def focus_clock(
        self, day: str, action: str, *,
        expect_phase: str | None = None, expect_intervals: int | None = None,
        skip_break: bool = False,
    ) -> dict[str, Any] | None:
        """Move the clock: pause, resume, next (finish this phase and start the
        one after), sync (bank the time so far and re-find the cursor, clock
        still running), or end. None for a day with no session.

        `next` takes what the caller EXPECTS the phase to be, and does nothing
        if the session has moved on — two windows both see an interval end and
        both ask for the next phase, and the second must not skip a break. A
        no-op writes nothing and publishes nothing, exactly as an empty PATCH
        on a day entry does; the other window learns nothing it did not know.

        An ended session takes no clock action at all: it is the record of a
        session, and Start is the way to a new one.
        """
        day = day_key(day)
        now = _focus_now()
        with self._lock:
            s = self._focus_load(day)
            if s is None:
                return None
            before = self._focus_snapshot(s)
            credited = 0
            if s["ended_at"]:
                pass
            elif action == "pause":
                credited = self._focus_settle(day, s, now)
            elif action == "resume":
                if not s["running_since"] and not self._focus_complete(s):
                    s["running_since"] = _stamp_at(now)
            elif action == "next":
                stale = (
                    (expect_phase is not None and expect_phase != s["phase"])
                    or (expect_intervals is not None
                        and expect_intervals != s["intervals_done"])
                )
                if not stale:
                    credited = self._focus_settle(day, s, now)
                    self._focus_next_phase(s, now, skip_break=skip_break)
                    s["entry_id"] = self._focus_cursor(day, s)
            elif action == "sync":
                credited = self._focus_settle(day, s, now, keep_running=True)
                s["entry_id"] = self._focus_cursor(day, s)
            elif action == "end":
                credited = self._focus_settle(day, s, now)
                s["ended_at"] = _stamp_at(now)
            else:
                raise ValueError(f"unknown clock action {action!r}")
            row = self._focus_store(day, before, s)
            dto = self._focus_dto(row)
            moved = self._focus_snapshot(s) != before
        if moved:
            self._publish({"type": "focus_updated", "day": day})
        if credited:
            self._publish({"type": "day_updated", "day": day})
        return dto

    def focus_cursor(
        self, day: str, action: str, *, entry_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Move the cursor: pass (set the current row aside — its cap spent, or
        "not now"), select (jump to an open row), or again (bring every
        set-aside row back). None for a day with no session.

        `pass` names the row it means to set aside and is a no-op if that row
        is no longer current — two windows both see a cap reached and both
        ask, and the second must not set aside the row that came next. The
        clock keeps running through all three: passing a row is not a pause.
        """
        day = day_key(day)
        now = _focus_now()
        with self._lock:
            s = self._focus_load(day)
            if s is None:
                return None
            before = self._focus_snapshot(s)
            credited = 0
            if s["ended_at"]:
                pass
            elif action == "pass":
                if entry_id is not None and entry_id == s["entry_id"]:
                    credited = self._focus_settle(day, s, now, keep_running=True)
                    if entry_id not in s["passed"]:
                        s["passed"].append(entry_id)
                    s["entry_id"] = self._focus_cursor(day, s)
            elif action == "select":
                if not entry_id:
                    raise ValueError("select needs the entry_id of an open row")
                rows, _planned = self._resolved_day_rows(day)
                if entry_id not in {r["entry_id"] for r in rows if not r["done"]}:
                    raise ValueError(f"{entry_id} is not an open row on {day}")
                credited = self._focus_settle(day, s, now, keep_running=True)
                s["passed"] = [p for p in s["passed"] if p != entry_id]
                s["entry_id"] = entry_id
            elif action == "again":
                credited = self._focus_settle(day, s, now, keep_running=True)
                s["passed"] = []
                s["entry_id"] = self._focus_cursor(day, s)
            else:
                raise ValueError(f"unknown cursor action {action!r}")
            row = self._focus_store(day, before, s)
            dto = self._focus_dto(row)
            moved = self._focus_snapshot(s) != before
        if moved:
            self._publish({"type": "focus_updated", "day": day})
        if credited:
            self._publish({"type": "day_updated", "day": day})
        return dto

    # ── app settings (account-synced) ─────────────────────────────────────────
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return store.get_settings(self._conn)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            settings = store.update_settings(self._conn, patch)
        # Notify other open tabs/devices so the change syncs live.
        self._publish({"type": "settings_updated"})
        return settings



def _event_day(value: str | None, *, is_date: bool, zone: ZoneInfo | None) -> str:
    """The calendar day an event's DTSTART falls on IN THE OWNER'S ZONE, or "".

    The same rule `_due_day` applies to a task's DUE, and for the same reason —
    the frontend's `dayKey` hands the value to `Date` and reads LOCAL components
    back, so an event another CalDAV client cached as
    `2026-09-01T02:00:00+00:00` is September 1st in UTC and August 31st on a
    screen in New York. Taking the string's own first ten characters put it in
    a different cell on the wall than in the app's calendar tab, and printed a
    different clock beside it.

    Two shapes are deliberately NOT converted, exactly as in `_due_day`, because
    converting them would invent an instant the wire never named:

      * a DATE-valued DTSTART — what an all-day event is on the wire. It is
        already a bare calendar day.
      * a floating datetime — naive local wall time, which `dayKey` also reads
        as-is. Its day is the day it already spells.

    `zone` is keyword-only and REQUIRED, matching `_due_day`. It has no default
    on purpose: `None` is a legitimate value meaning "the process's own zone",
    so a call site that forgot to thread the zone would be indistinguishable
    from one that meant it — and the only symptom would be a span's two ends
    resolved in two different zones.
    """
    if not value:
        return ""
    if is_date or "T" not in value:
        return value[:10]
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return value[:10]
    if stamp.tzinfo is None:
        return stamp.date().isoformat()
    try:
        # `astimezone(zone)` with zone=None converts to the process's local
        # zone, which is exactly the unset-`home_timezone` fallback — the same
        # one `_today` takes, so the grid and the chips inside it agree.
        return stamp.astimezone(zone).date().isoformat()
    except (OverflowError, OSError):
        # A value near datetime.min/max overflows here rather than raising
        # ValueError above. This runs on a route with no session, where an
        # unhandled exception is a 500 on every fetch of that display.
        return value[:10]


def _local_midnight(value: str, zone: ZoneInfo | None) -> bool:
    """Does `value` land exactly on midnight in the owner's zone?

    Ports `calendar.ts::endIsExclusive`, which tests
    `parseDate(e.end).getHours() === 0 && getMinutes() === 0` — the CONVERTED
    local clock, not the characters. Reading `end[11:16] == "00:00"` off the
    string called a DTEND of `2026-08-31T00:00:00+02:00` midnight, when in UTC
    it is 22:00 on the 30th and only Berlin sees midnight; the two surfaces then
    disagreed about whether the span spills into another day.
    """
    stamp = _event_stamp(value, zone)
    return stamp is not None and stamp.hour == 0 and stamp.minute == 0


def _event_stamp(value: str, zone: ZoneInfo | None) -> datetime | None:
    """`value` as a datetime in the owner's zone, or None if it is not one."""
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp
    try:
        return stamp.astimezone(zone)
    except (OverflowError, OSError):
        return None


def _event_last_day(ev: dict[str, Any], start_day: str, *,
                    zone: ZoneInfo | None) -> str:
    """The last day an event is visible on. Ports `calendar.ts::lastDayOf`.

    DTEND is EXCLUSIVE for an all-day event (RFC 5545 §3.6.1), and a timed event
    that ends at exactly midnight does not spill into the next day — both are
    the same rule from the reader's side: an event ends on the last day it has
    time on. Getting this wrong draws a Friday-to-Sunday trip through Monday.

    Both ends resolve in the SAME zone. Threading it to the day but not to the
    midnight test, or to DTSTART but not DTEND, is the subtle way to get this
    wrong: an event 16:00–22:00 on the 31st in New York, cached as
    `…T20:00:00+00:00`–`…T02:00:00+00:00`, would start on the 31st and end on
    the 1st, and the wall would draw a continuation chip on a day the event
    never touched.
    """
    end = ev.get("end")
    if not end:
        return start_day
    end_day = _event_day(end, is_date=bool(ev.get("end_is_date")), zone=zone)
    if not end_day:
        return start_day
    exclusive = bool(ev.get("end_is_date")) or (
        "T" in end and _local_midnight(end, zone))
    if exclusive:
        end_day = (date.fromisoformat(end_day) - timedelta(days=1)).isoformat()
    return max(end_day, start_day)


# Fields where -1 means CLEAR rather than a value. The same sentinel the day
# ritual and the day entry use, and for the same reason: 0 is a real answer for
# every one of them ("tell me exactly when it is due", "not working today"), so
# the clear cannot borrow falsiness. Mapped here, once, rather than in each
# route — `store.set_sidecar` writes what it is given and has no business
# knowing which integers are sentinels.
_CLEARABLE = ("notify_minutes_before",)


def _clear_sentinels(fields: dict[str, object]) -> dict[str, object]:
    return {k: (None if k in _CLEARABLE and v == -1 else v) for k, v in fields.items()}


def priority_from_label(label: str | None) -> int | None:
    return None if label is None else PRIORITY.get(label, 0)
