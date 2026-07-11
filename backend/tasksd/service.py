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
import logging
import threading
from datetime import date, datetime
from typing import Any

from .config import Settings
from .dav import xml as davxml
from .dav.client import DavClient
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

    def close(self) -> None:
        with self._lock:
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
        with self._lock:
            self._engine.discover()
            for row in store.get_collections(self._conn):
                self._engine.sync(row["href"])

    def sync_all(self) -> list[SyncStats]:
        with self._lock:
            self._engine.discover()
            stats = [self._engine.sync(r["href"]) for r in store.get_collections(self._conn)]
        if any(s.upserted or s.removed for s in stats):
            self._publish({"type": "sync"})
        return stats

    # ── list queries ─────────────────────────────────────────────────────────
    def list_lists(self) -> list[dict[str, Any]]:
        # The Tasks tab shows VTODO-capable collections only; VEVENT-only
        # calendars belong to the Calendar tab (list_calendars).
        with self._lock:
            rows = store.get_collections(self._conn)
            return [self._list_dto(r) for r in rows if "VTODO" in (r["components"] or "")]

    def _list_dto(self, row) -> dict[str, Any]:
        comps = [c for c in (row["components"] or "").split(",") if c]
        items = store.get_items(self._conn, row["href"])
        task_items = [i for i in items if i["component"] == "VTODO"]
        open_count = sum(1 for i in task_items if i["status"] not in ("COMPLETED", "CANCELLED"))
        event_count = sum(1 for i in items if i["component"] == "VEVENT")
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
            "open_count": open_count,
            "task_count": len(task_items),
            "event_count": event_count,
            "total": len(items),
            "folder": settings_row["folder"] if settings_row else None,
            "sort_mode": settings_row["sort_mode"] if settings_row else None,
        }

    def resolve_list(self, list_id: str) -> str | None:
        """Accept either a full href or the short slug; return the href."""
        with self._lock:
            for row in store.get_collections(self._conn):
                if list_id in (row["href"], _slug(row["href"])):
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
        return dtos

    @staticmethod
    def _children_map(items) -> dict[str, list]:
        children: dict[str, list] = {}
        for it in items:
            if it["related_parent"]:
                children.setdefault(it["related_parent"], []).append(it)
        return children

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
            "list": it["collection_href"],
            "summary": it["summary"],
            "notes": it["description"],
            "status": status,
            "completed": status == "COMPLETED",
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
                    by_col[col] = (
                        store.get_all_categories(self._conn, col),
                        store.get_all_sidecar(self._conn, col),
                        [i for i in store.get_items(self._conn, col) if i["component"] == "VTODO"],
                    )
        out = []
        for r in rows:
            cats, side, items = by_col[r["collection_href"]]
            out.append(self._task_dto(r, cats, side, self._children_map(items)))
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
        self._publish({"type": "list_deleted", "list": _slug(href)})

    def create_task(self, href: str, summary: str, *, edit: TaskEdit | None = None,
                    parent_uid: str | None = None) -> dict[str, Any]:
        with self._lock:
            uid = self._engine.create_task(href, summary, edit=edit, parent_uid=parent_uid)
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

    def set_sidecar(self, href: str, uid: str, **fields: object) -> dict[str, Any] | None:
        with self._lock:
            store.set_sidecar(self._conn, href, uid, **fields)
        self._publish({"type": "task_updated", "list": _slug(href), "uid": uid})
        return self.get_task(href, uid)

    # ── calendars / events ───────────────────────────────────────────────────
    def list_calendars(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = store.get_collections(self._conn)
            return [self._list_dto(r) for r in rows if "VEVENT" in (r["components"] or "")]

    def events_in_range(self, href: str, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
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
                out.append(self._event_dto(r, cats))
        return out

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
                     edit: EventEdit | None = None) -> dict[str, Any] | None:
        with self._lock:
            uid = self._engine.create_event(href, summary, dtstart=dtstart, dtend=dtend, edit=edit)
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
