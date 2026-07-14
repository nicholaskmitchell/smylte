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
        # Lock per collection, not for the whole sweep: interactive requests
        # (which serialize on the same lock) interleave between slices instead
        # of stalling for the full background pass every poll interval.
        with self._lock:
            self._engine.discover()
            hrefs = [r["href"] for r in store.get_collections(self._conn)]
        stats: list[SyncStats] = []
        for href in hrefs:
            with self._lock:
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
            # The list's short id (same key as List.id and the SSE payloads), so
            # the combined "All lists" view can map a task back to its list for
            # color and visibility. resolve_list still accepts the full href too.
            "list": _slug(it["collection_href"]),
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
                events.extend(self.events_in_range(row["href"], start_iso, end_iso))
        return scheduling.busy_intervals(events, tz)

    def public_link_info(self, token: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """The public booking page payload, or None for an unknown OR disabled
        link (the route maps both to the same 404 — no probing oracle). Nothing
        beyond title/description/duration/timezone/slots (+ redacted busy) ever
        leaves the server here."""
        with self._lock:
            link = store.get_booking_link(self._conn, token)
            if link is None or not link["enabled"]:
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
    ) -> dict[str, Any] | None:
        """Book a slot: re-validate under the lock, write the VEVENT, record the
        booking. Returns None for unknown/disabled links; raises ValueError for
        a malformed start (→ 422) and scheduling.SlotTaken when the requested
        time isn't an open slot (→ 409)."""
        with self._lock:
            link = store.get_booking_link(self._conn, token)
            if link is None or not link["enabled"]:
                return None
            # Replay (same client_id ⇒ same event UID): return the original
            # confirmation instead of failing the re-validation as taken. Only
            # for THIS link — a client_id reused against a different link is
            # not a replay of anything and must not disclose the other
            # booking's times (nor collide with its event resource).
            if client_id:
                prior = store.get_booking_by_event(self._conn, f"{client_id}@tasksd")
                if prior is not None:
                    if prior["link_token"] == token:
                        return self._confirmation(link, prior)
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
            if not any(s.start == req for s in slots):
                raise scheduling.SlotTaken("that time is not available")

            end = req + timedelta(minutes=link["duration_minutes"])
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
        }

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
