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
