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
from .ical import PRIORITY, UNSET, EventEdit, TaskEdit, recur
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
            self._engine.discover()
            collections_changed = self._engine.last_discovery_changed
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
    def list_tasks(self, href: str, *, include_done: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            items = [i for i in store.get_items(self._conn, href) if i["component"] == "VTODO"]
            cats = store.get_all_categories(self._conn, href)
            side = store.get_all_sidecar(self._conn, href)
        children = self._children_map(items)
        dtos = [self._task_dto(it, cats, side, children) for it in items]
        if not include_done:
            dtos = [d for d in dtos if not (d["completed"] or d["cancelled"])]
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
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

    def complete_task(self, href: str, uid: str, *, done: bool = True) -> dict[str, Any] | None:
        return self.edit_task(href, uid, TaskEdit(status="COMPLETED" if done else "NEEDS-ACTION"))

    def cancel_task(self, href: str, uid: str) -> dict[str, Any] | None:
        """Won't-do."""
        return self.edit_task(href, uid, TaskEdit(status="CANCELLED"))

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
            store.set_sidecar(self._conn, href, uid, **fields)
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

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
        win_start, win_end = _parse_window(start_iso), _parse_window(end_iso)
        out: list[dict[str, Any]] = []
        for r in rows:
            if not r["has_rrule"]:
                out.append(self._event_dto(r, cats))          # one row, one instance
                continue
            # Recurring: fan the cached raw_ics out into per-occurrence rows. A
            # single malformed resource must not blank the whole month — fall back
            # to showing its master row.
            try:
                for occ in recur.expand_occurrences(r["raw_ics"], win_start, win_end):
                    out.append(self._occurrence_dto(r, occ, cats))
            except Exception:  # noqa: BLE001
                log.warning("recurrence expansion failed for %s; showing master", r["uid"])
                if blocking:
                    out.append(self._opaque_span_dto(r, start_iso, end_iso, cats))
                else:
                    out.append(self._event_dto(r, cats))
        return out

    def _opaque_span_dto(
        self, row, start_iso: str, end_iso: str, cats
    ) -> dict[str, Any]:
        """A recurring resource we could not expand, as one interval covering the
        whole query window — "assume busy" rather than "assume free"."""
        dto = dict(self._event_dto(row, cats))
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
        return self._event_dto(row, cats)

    def _event_dto(self, it, cats) -> dict[str, Any]:
        uid = it["uid"]
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
            "tags": cats.get(uid, []),
            "has_rrule": bool(it["has_rrule"]),
            "href": it["href"],
            "etag": it["etag"],
            "created": it["created"],
            "last_modified": it["last_modified"],
        }

    def _occurrence_dto(self, it, occ: recur.Occurrence, cats) -> dict[str, Any]:
        """One expanded occurrence of a recurring series. Same keys as
        ``_event_dto`` (so the frontend stays uniform), but ``id`` is unique per
        instance and ``start``/``end`` are this occurrence's times; per-instance
        text falls back to the master's when an override omits a field. ``uid`` /
        ``href`` stay the base resource so series-level edit/delete still work."""
        uid = it["uid"]
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
            "tags": cats.get(uid, []),
            "has_rrule": True,
            "href": it["href"],
            "etag": it["etag"],
            "created": it["created"],
            "last_modified": it["last_modified"],
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
            else:
                self._engine.edit_event(href, uid, edit)
        self._publish({"type": "event_updated", "list": _slug(href), "uid": uid})
        return self.get_event(href, uid)

    def move_event(self, src_href: str, dst_href: str, uid: str) -> dict[str, Any] | None:
        if src_href == dst_href:
            return self.get_event(src_href, uid)
        with self._lock:
            self._engine.move_event(src_href, dst_href, uid)
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

    @staticmethod
    def _link_dto(row, counts: dict[str, int], names: dict[str, str]) -> dict[str, Any]:
        return {
            "token": row["token"],
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
            return None
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
            "position": row["position"],
            "done_at": row["done_at"],
            "dropped_at": row["dropped_at"],
            "created_at": row["created_at"],
        }

    def _day_plan_dto(self, day: str, entries, opened: bool) -> dict[str, Any]:
        """One day's plan. `planned` is the marker OR the presence of entries,
        because the two record different things: the marker says the automatic
        snapshot has been BUILT, an entry says the owner has put something on
        the day. A hand-add deliberately leaves the marker alone (see
        `add_day_entry`, and the day still owes itself one snapshot), so a day
        holding nothing but hand-added rows has no marker — and calling that day
        unplanned would draw it as untouched with its own entries on screen."""
        return {
            "day": day,
            "planned": opened or bool(entries),
            "entries": [self._day_entry_dto(r) for r in entries],
        }

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
        built once: what is due that day, what is already late, and what was
        left unfinished on the last day that had a plan. Afterwards the MARKER —
        and only the marker — makes this a read like any other, so re-opening
        never re-snapshots and never resurrects an entry the owner dropped.

        Entries already on the day do NOT stand in for the marker. They used to:
        the day's first hand-add called `mark_day_opened`, and short-circuiting
        on `entries` meant a day whose first write was an add never got its
        snapshot at all — due-today, overdue and carried rows suppressed for
        that day forever, from a client that offers the add box before the open
        has even answered. So the snapshot merges into what is there instead,
        skipping anything the day already holds (`_snapshot_for`).
        """
        day = day_key(day)
        with self._lock:
            entries = store.get_day_entries(self._conn, day)
            opened = store.day_is_opened(self._conn, day)
            if not create or opened:
                return self._day_plan_dto(day, entries, opened)
            pending = self._snapshot_for(day, entries)
            # Behind whatever the owner has already placed, computed the same
            # way `add_day_entry` appends. Rows that are already on the day keep
            # the positions they were given: a snapshot arriving late must not
            # renumber the arrangement it is joining.
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
                store.mark_day_opened(self._conn, day)
            entries = store.get_day_entries(self._conn, day)
            dto = self._day_plan_dto(day, entries, True)
        self._publish({"type": "day_updated", "day": day})
        return dto

    def preview_day(self, day: str) -> list[dict[str, Any]]:
        """What opening `day` WOULD put on it, without opening it.

        The same derivation `open_day(create=True)` inserts — due that day, then
        already late, then unfinished from the last planned day — run and thrown
        away. `_snapshot_for` writes nothing itself, so this costs one read and
        cannot leave a trace.

        It exists for the MCP connector, which has to answer "what is on today"
        for a day the owner has not opened yet. Reading is the only thing a
        connector may do to an unplanned day: a read that opened days would fill
        the log with plans nobody made, and freeze each of those days' snapshots
        at whatever happened to be due when something asked. So the honest
        answer is a preview, clearly not a plan, and the marker stays unset until
        a person opens the day themselves.

        Entries the day already holds are excluded, exactly as they are on a real
        open — so on a day that IS planned this returns what a snapshot would
        still add, which is [] for a day that has already had one.

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
                "position": None,
                "done_at": None,
                "dropped_at": None,
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

        Order is due-today, then overdue, then carried — the day's own work
        first, what is already late behind it, and yesterday's leftovers last.
        Within each group the sort key is (due, summary, collection_href, uid),
        which is total — a UID is unique per COLLECTION, not globally
        (invariant #4), so the href has to be in the key for two lists holding
        the same UID to have a defined order — and a total key is what makes the
        snapshot for a given cache reproducible.
        """
        # Resolved once for the whole scan rather than per task: it is a
        # settings read, and every DUE in the account buckets against the same
        # zone.
        home = self._home_tz()
        due_today: list[Any] = []
        overdue: list[Any] = []
        for col in store.get_collections(self._conn):
            if "VTODO" not in (col["components"] or ""):
                continue
            # Every task in every list, raw_ics and all — the same read
            # `list_tasks` does on each render. Affordable HERE because the
            # opened marker makes it happen at most once per day, rather than
            # once per view of the day.
            for it in store.get_items(self._conn, col["href"]):
                if it["component"] != "VTODO":
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
                if key == day:
                    due_today.append(it)
                elif key < day:
                    overdue.append(it)
        out: list[dict[str, Any]] = []
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
        for group in (due_today, overdue):
            for it in sorted(group, key=_snapshot_order):
                self._append_task_entry(out, seen, it["collection_href"], it["uid"], "auto")
        for row in self._carry_into(day):
            if row["kind"] == "note":
                if row["title"] in note_titles:
                    continue
                note_titles.add(row["title"])
                out.append({
                    "entry_id": uuid.uuid4().hex, "kind": "note",
                    "title": row["title"], "source": "carried",
                })
                continue
            self._append_task_entry(
                out, seen, row["collection_href"], row["uid"], "carried"
            )
        return out

    @staticmethod
    def _append_task_entry(
        out: list[dict[str, Any]], seen: set[tuple[str, str]],
        href: str, uid: str, source: str,
    ) -> None:
        """Add one task entry unless (collection, uid) is already in the plan.

        The dedupe is what stops a task appearing twice on the same day: an
        overdue task the owner also carried forward by hand qualifies under both
        rules, and two rows for one task means two checkboxes that disagree
        about whether it is done. (collection_href, uid) is the identity of a
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
        })

    def _carry_into(self, day: str) -> list[Any]:
        """Rows from the most recent prior plan that should follow the owner
        into `day`. Called under the lock.

        Only source=user entries carry. An auto entry re-derives itself from the
        wire every morning (it is still due, or still late, so the snapshot
        picks it up again), and a carried entry deliberately carries exactly
        once: a task the owner chose on Monday and then ignored on Tuesday has
        been declined, and following them all week is how a plan turns into a
        list nobody reads.

        Done and dropped entries stay behind, and a task entry whose task is no
        longer an open VTODO stays behind too — completed elsewhere, cancelled,
        or gone from the wire entirely. The ENTRY on its own day survives all of
        that (no FK, by design); what must not happen is carrying a finished or
        vanished task forward into a day it was never planned for.

        The most recent prior day is taken as-is, even when nothing survives the
        filter. Skipping an empty day to reach an older one would resurrect
        entries the owner already left behind once.
        """
        first = (date.fromisoformat(day) - timedelta(days=_CARRY_LOOKBACK_DAYS)).isoformat()
        planned = store.get_day_range(self._conn, first, day)   # `day` is exclusive
        if not planned:
            return []
        out = []
        for row in planned[max(planned)]:
            if row["source"] != "user" or row["done_at"] or row["dropped_at"]:
                continue
            if row["kind"] == "task":
                item = store.get_item(self._conn, row["collection_href"], row["uid"])
                if item is None or item["component"] != "VTODO":
                    continue
                if (item["status"] or "") in ("COMPLETED", "CANCELLED"):
                    continue
            out.append(row)
        return out

    def add_day_entry(
        self, day: str, *, entry_id: str, kind: str,
        list_id: str | None = None, uid: str | None = None, title: str | None = None,
    ) -> dict[str, Any]:
        """Put a task or a note on a day by hand (source=user).

        Idempotent three ways, because this is the one route a client retries:
        the same entry_id, the same task, or the same note text on the same day
        all return the entry that is already there rather than a second row. The
        task and note lookups skip DROPPED entries (see store.find_day_entry) —
        having dropped something this morning, adding it back this afternoon has
        to work.

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
            # a day whose first write was a hand-add never got its due-today,
            # overdue or carried rows at all — and the shipped client offers the
            # add box whether or not the open succeeded, so that was one failed
            # request away. The day still reports planned=true, through the
            # entries arm of `_day_plan_dto`.
            #
            # One statement, so no `tx`: the connection is in autocommit (see
            # store.tx) and a lone INSERT is atomic by itself.
            row = store.insert_day_entry(
                self._conn, day=day, entry_id=entry_id, kind=kind, source="user",
                collection_href=href, uid=uid, title=title, position=position,
            )
            dto = self._day_entry_dto(row)
        self._publish({"type": "day_updated", "day": day})
        return dto

    def patch_day_entry(
        self, day: str, entry_id: str, *,
        done: bool | None = None, dropped: bool | None = None,
        position: float | None = None,
    ) -> dict[str, Any] | None:
        """Tick, drop or reposition one entry. None for an entry_id this day does
        not have (the route turns that into a 404).

        Dropping stamps a column; it never deletes the row. "I did not do this"
        is the single most useful thing a past day can tell you, and a DELETE
        would erase exactly that. It also keeps the entry out of the next day's
        carry-over, which is the other half of what dropping means.

        done=False / dropped=False clear their stamps — the undo path — which is
        why these arrive as tri-state booleans rather than flags: None is "the
        client did not send this field", and only the fields it did send reach
        the UPDATE.

        `done` is a NOTE's field, and sending it for a task entry raises
        ValueError (routes → 422). Dropping and repositioning apply to every
        entry; doneness does not, because a task already has one answer that
        every client on the account can see.
        """
        day = day_key(day)
        fields: dict[str, object] = {}
        if done is not None:
            fields["done_at"] = _stamp() if done else None
        if dropped is not None:
            fields["dropped_at"] = _stamp() if dropped else None
        if position is not None:
            fields["position"] = float(position)
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
            # only answer there is. TodayView already routes a task row's
            # checkbox through `api.complete`; this closes the path rather than
            # leaving a column that silently records a lie.
            if done is not None and row["kind"] == "task":
                raise ValueError(
                    "done applies to a note entry; a task's doneness is its "
                    "VTODO STATUS — complete the task instead"
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
        with self._lock:
            planned = store.get_day_range(self._conn, start, end)
        # Every day the map holds is planned by definition: it is there because
        # it has a marker, entries, or both.
        return [self._day_plan_dto(d, rows, True) for d, rows in planned.items()]

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


def priority_from_label(label: str | None) -> int | None:
    return None if label is None else PRIORITY.get(label, 0)
