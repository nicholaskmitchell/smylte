"""The sync engine: keeps SQLite in step with Radicale, and owns the write path.

Read side (poll every ~30s per collection):
  * incremental — sync-collection REPORT with the stored token (RFC 6578)
  * full resync — on first sync or an invalid token (invariant #6): enumerate the
    whole collection with an empty-token sync-collection (atomic list + fresh
    token — a race-free improvement over the spec's literal "PROPFIND Depth:1",
    which cannot hand back a token in the same round-trip), multiget bodies, and
    reconcile deletions.

Write side (synchronous, no outbox — spec §3):
  * create/edit/delete straight to Radicale with If-Match, then refresh the cache
    from the canonical stored form (Radicale re-serializes on write).
  * a 412 is expected (invariant #5): re-GET, re-apply the SAME field-level intent
    to the fresh copy, retry once, then surface a conflict.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from .. import ical
from ..dav.client import CollectionInfo, DavClient
from ..dav.errors import DavError, InvalidSyncToken, NotFound, PreconditionFailed
from ..db import store


class ConflictError(DavError):
    """A 412 that survived the refetch-and-retry merge — surface to the user."""


@dataclass
class SyncStats:
    collection_href: str
    upserted: int = 0
    removed: int = 0
    full_resync: bool = False


@contextmanager
def _tx(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _is_synced_collection(ci: CollectionInfo) -> bool:
    # Track anything that can hold tasks or events. An unspecified component set
    # is permissive (Radicale's default template includes both).
    return not ci.components or bool(ci.components & {"VTODO", "VEVENT"})


class SyncEngine:
    def __init__(self, dav: DavClient, conn, *, multiget_batch: int = 50):
        self.dav = dav
        self.conn = conn
        self.batch = multiget_batch

    # ── discovery ────────────────────────────────────────────────────────────
    def discover(self) -> list[CollectionInfo]:
        cols = [c for c in self.dav.list_collections() if _is_synced_collection(c)]
        live = {c.href for c in cols}
        with _tx(self.conn):
            for c in cols:
                store.upsert_collection(self.conn, c)
            for row in store.get_collections(self.conn):
                if row["href"] not in live:
                    store.mark_collection_deleted(self.conn, row["href"])
        return cols

    # ── read path ────────────────────────────────────────────────────────────
    def sync(self, collection_href: str) -> SyncStats:
        token = store.get_sync_token(self.conn, collection_href)
        if token is None:
            return self.full_resync(collection_href)
        try:
            result = self.dav.sync_collection(collection_href, token)
        except InvalidSyncToken:
            return self.full_resync(collection_href)
        return self._apply_incremental(collection_href, result)

    def _apply_incremental(self, collection_href: str, result) -> SyncStats:
        stats = SyncStats(collection_href)
        bodies = self._multiget(collection_href, [i.href for i in result.changed])
        with _tx(self.conn):
            for item in bodies:
                if self._upsert_body(collection_href, item):
                    stats.upserted += 1
            for href in result.removed:
                uid = store.delete_item_by_href(self.conn, collection_href, href)
                if uid:
                    store.orphan_sidecar(self.conn, collection_href, uid)
                    stats.removed += 1
            store.set_sync_token(self.conn, collection_href, result.token)
        return stats

    def full_resync(self, collection_href: str) -> SyncStats:
        stats = SyncStats(collection_href, full_resync=True)
        result = self.dav.sync_collection(collection_href, None)   # atomic all + fresh token
        wire = {i.href: i.etag for i in result.changed}
        known = store.known_etags(self.conn, collection_href)
        to_fetch = [h for h, etag in wire.items() if known.get(h) != etag]
        bodies = self._multiget(collection_href, to_fetch)
        with _tx(self.conn):
            for item in bodies:
                if self._upsert_body(collection_href, item):
                    stats.upserted += 1
            # After upserts, any cached href no longer on the wire is a real
            # deletion. A delete-and-recreated UID already moved to its new href,
            # so it is NOT swept here (invariant #4 / sidecar survival).
            for href, uid in store.href_uid_map(self.conn, collection_href).items():
                if href not in wire:
                    store.delete_item_by_href(self.conn, collection_href, href)
                    store.orphan_sidecar(self.conn, collection_href, uid)
                    stats.removed += 1
            store.set_sync_token(self.conn, collection_href, result.token, full=True)
            store.gc_orphans(self.conn)
        return stats

    def _upsert_body(self, collection_href: str, item) -> bool:
        """Extract + cache one resource. Returns False for non-VTODO resources
        (e.g. a VEVENT sharing a mixed collection) — they are simply not tracked."""
        if not item.data:
            return False
        fields = ical.extract_from_raw(item.data)
        if fields is None or not fields.uid:
            return False
        store.upsert_item(self.conn, collection_href, item, fields)
        return True

    def _multiget(self, collection_href: str, hrefs: list[str]) -> list:
        out: list = []
        for i in range(0, len(hrefs), self.batch):
            out.extend(self.dav.multiget(collection_href, hrefs[i : i + self.batch]))
        return out

    # ── write path ───────────────────────────────────────────────────────────
    def create_task(
        self,
        collection_href: str,
        summary: str,
        *,
        edit: ical.TaskEdit | None = None,
        parent_uid: str | None = None,
    ) -> str:
        if not store.has_collection(self.conn, collection_href):
            raise ValueError(f"collection {collection_href} is unknown; run discover() first")
        # The href SLUG is kept URL-safe (plain hex) so our own resource paths are
        # already in Radicale's canonical form — Radicale percent-encodes reserved
        # characters (e.g. '@' -> '%40'), which would otherwise make the href we
        # cache at create time differ from the one sync reports. The UID may still
        # carry '@'; it is the join key, never the href (invariant #4).
        slug = uuid.uuid4().hex
        uid = f"{slug}@tasksd"
        raw = ical.build_new(uid, summary=summary, edit=edit, related_parent=parent_uid)
        href = f"{collection_href}{slug}.ics"
        self.dav.put(href, raw, if_none_match="*")
        self._refresh_from_wire(collection_href, href)
        return uid

    def create_event(
        self,
        collection_href: str,
        summary: str,
        *,
        dtstart,
        dtend=None,
        edit: ical.EventEdit | None = None,
    ) -> str:
        if not store.has_collection(self.conn, collection_href):
            raise ValueError(f"collection {collection_href} is unknown; run discover() first")
        slug = uuid.uuid4().hex
        uid = f"{slug}@tasksd"
        raw = ical.build_new_event(uid, summary=summary, dtstart=dtstart, dtend=dtend, edit=edit)
        href = f"{collection_href}{slug}.ics"
        self.dav.put(href, raw, if_none_match="*")
        self._refresh_from_wire(collection_href, href)
        return uid

    def edit_task(self, collection_href: str, uid: str, edit: ical.TaskEdit) -> str:
        return self._edit(collection_href, uid, ical.apply_changes, edit, kind="task")

    def edit_event(self, collection_href: str, uid: str, edit: ical.EventEdit) -> str:
        return self._edit(collection_href, uid, ical.apply_event_changes, edit, kind="event")

    def override_event(
        self, collection_href: str, uid: str, recurrence_id: str, edit: ical.EventEdit
    ) -> str:
        """Edit a single occurrence ("this event") via a RECURRENCE-ID override."""
        return self._edit(
            collection_href, uid,
            lambda raw, e: ical.apply_occurrence_override(raw, recurrence_id, e),
            edit, kind="event",
        )

    def exclude_event_occurrence(
        self, collection_href: str, uid: str, recurrence_id: str
    ) -> str:
        """Delete a single occurrence ("this event") via an EXDATE on the master."""
        return self._edit(
            collection_href, uid,
            lambda raw, _e: ical.exclude_occurrence(raw, recurrence_id),
            None, kind="event",
        )

    def split_event(
        self,
        collection_href: str,
        uid: str,
        recurrence_id: str,
        edit: ical.EventEdit,
        *,
        delete_tail: bool = False,
    ) -> str:
        """"This and following": bound the existing series before `recurrence_id`
        and (unless deleting) write the remainder as a new resource. Head and tail
        are always derived from the same source revision so they stay consistent;
        a 412 re-derives both from the fresh copy (invariant #5)."""
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            raise KeyError(f"unknown event {uid} in {collection_href}")
        href = row["href"]

        def build(raw):
            return ical.split_series(raw, recurrence_id, edit)

        head, tail = build(row["raw_ics"])
        try:
            self.dav.put(href, head, if_match=row["etag"])
        except PreconditionFailed:
            fresh = self.dav.get(href)
            head, tail = build(fresh.data)
            try:
                self.dav.put(href, head, if_match=fresh.etag)
            except PreconditionFailed as e:
                raise ConflictError(f"edit conflict on {uid}: retry the change") from e
        self._refresh_from_wire(collection_href, href)
        if not delete_tail:
            slug = uuid.uuid4().hex
            tail_href = f"{collection_href}{slug}.ics"
            self.dav.put(tail_href, tail, if_none_match="*")
            self._refresh_from_wire(collection_href, tail_href)
        return uid

    def _edit(self, collection_href: str, uid: str, apply_fn, edit, *, kind: str) -> str:
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            raise KeyError(f"unknown {kind} {uid} in {collection_href}")
        href = row["href"]
        body = apply_fn(row["raw_ics"], edit)
        try:
            self.dav.put(href, body, if_match=row["etag"])
        except PreconditionFailed:
            # invariant #5: a concurrent write beat us. Re-GET, re-apply the same
            # field intent onto the fresh copy (preserving the other writer's
            # fields), retry exactly once, then surface a conflict.
            fresh = self.dav.get(href)
            merged = apply_fn(fresh.data, edit)
            try:
                self.dav.put(href, merged, if_match=fresh.etag)
            except PreconditionFailed as e:
                raise ConflictError(f"edit conflict on {uid}: retry the change") from e
        return self._refresh_from_wire(collection_href, href)

    def delete_task(self, collection_href: str, uid: str) -> None:
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            return
        href = row["href"]
        try:
            self.dav.delete(href, if_match=row["etag"])
        except PreconditionFailed:
            # Changed under us — delete the current revision instead of blind force.
            try:
                self.dav.delete(href, if_match=self.dav.head_etag(href))
            except NotFound:
                pass
        with _tx(self.conn):
            store.delete_item_by_href(self.conn, collection_href, href)
            store.orphan_sidecar(self.conn, collection_href, uid)

    def _refresh_from_wire(self, collection_href: str, href: str) -> str:
        """Radicale re-serializes on write, so pull the canonical stored form
        back and cache THAT — keeping raw_ics equal to what the next edit will
        GET (invariant #2)."""
        stored = self.dav.get(href)
        fields = ical.extract_from_raw(stored.data)
        if fields is None or not fields.uid:
            raise DavError(f"stored resource at {href} is not a task or event")
        with _tx(self.conn):
            store.upsert_item(self.conn, collection_href, stored, fields)
        return stored.etag
