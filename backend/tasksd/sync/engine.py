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

import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass

from icalendar import Calendar

from .. import ical
from ..ical.read import unfold
from ..dav.client import CollectionInfo, DavClient
from ..dav.errors import (Conflict, DavError, InvalidSyncToken, MalformedResponse,
                          NotFound, PreconditionFailed)
from ..db import store
from ..db.store import tx as _tx

log = logging.getLogger("tasksd.sync")

# UID lines, read textually. Only used for a resource whose extraction already
# failed: we still need to know which UIDs it claims so the resync sweep does
# not conclude they left the server. Deliberately cheap and forgiving — the body
# we cannot parse is exactly the one we cannot ask nicely.
#
# Matched against LOGICAL lines, after `unfold`. The scan used to run over the
# raw bytes one physical line at a time, and RFC 5545 §3.1 folds content lines
# at 75 octets — icalendar on our own writes, and Radicale on every read, so it
# does not matter which client wrote it. A UID past ~71 characters (Outlook's
# `040000008200E00074C5B7101A82E008...` is over a hundred) therefore arrived as
# `UID:<71 chars>\r\n <rest>`, the match captured the first line only, and the
# truncated string equalled no cached uid: the guard swept the live item in the
# one case it exists for. The optional parameter group is cheap tolerance for a
# `UID;X-FOO=bar:...` a foreign client may write.
_UID_RE = re.compile(r"^UID(?:;[^:]*)?:(.*)$")


def _uids_in(raw: bytes | None) -> set[str]:
    out: set[str] = set()
    for line in unfold(raw or b""):
        m = _UID_RE.match(line)
        if m and m.group(1).strip():
            out.add(m.group(1).strip())
    return out


def _restamp_uid(raw: bytes, uid: str) -> bytes:
    """`raw` with every component's UID replaced by `uid`.

    Used when a split has to be rebuilt against a fresher copy: the tail already
    exists on the server under the UID the first build minted, and a PUT that
    changes a resource's UID is a 409, not an update.
    """
    cal = Calendar.from_ical(raw)
    for comp in cal.walk("VEVENT"):
        if "UID" in comp:
            del comp["UID"]
        comp.add("UID", uid)
    return cal.to_ical()


class ConflictError(DavError):
    """A 412 that survived the refetch-and-retry merge — surface to the user."""


@dataclass
class SyncStats:
    collection_href: str
    upserted: int = 0
    removed: int = 0
    skipped: int = 0                  # resources left uncached this pass (malformed or unread)
    full_resync: bool = False
    last_error: str | None = None     # recorded in sync_state.last_error
    # Of `skipped`, the hrefs whose bytes never arrived (a GET in the per-href
    # fallback failed in transport). Unlike a malformed body, these are worth
    # asking for again, so a pass that has any holds its sync token.
    unread: int = 0


def _is_synced_collection(ci: CollectionInfo) -> bool:
    # Track anything that can hold tasks or events. An unspecified component set
    # is permissive (Radicale's default template includes both).
    return not ci.components or bool(ci.components & {"VTODO", "VEVENT"})


class SyncEngine:
    def __init__(self, dav: DavClient, conn, *, multiget_batch: int = 50):
        self.dav = dav
        self.conn = conn
        self.batch = multiget_batch
        # Whether the last discover() saw the live collection set move. Read by
        # TaskService.sync_all to decide whether the SPA needs telling.
        self.last_discovery_changed = False

    # ── discovery ────────────────────────────────────────────────────────────
    def discover(self) -> list[CollectionInfo]:
        """Reconcile the cached collection set with the server's.

        Sets `self.last_discovery_changed` to whether the live set actually
        moved — a collection appeared or vanished. `sync_all` publishes on it:
        collection-set changes are found here, not in the per-collection item
        counters, so when the owner deleted a list on their phone the projection
        was correctly purged but no `rev` bump ever reached the browser. The open
        tab kept rendering a dead list in the sidebar until some unrelated write
        happened, and clicking it 404'd. A new empty collection was equally
        invisible."""
        before = {row["href"] for row in store.get_collections(self.conn)}
        cols = [c for c in self.dav.list_collections() if _is_synced_collection(c)]
        # `live` is built from every collection the server listed, including any
        # we then fail to cache: the server says it exists, so it must not be
        # marked deleted (which would discard its sidecar state) just because one
        # of its properties is unusable.
        live = {c.href for c in cols}
        kept: list[CollectionInfo] = []
        with _tx(self.conn):
            for c in cols:
                # Per-collection tolerance. These all share one transaction, so
                # without this an unusable property on ONE collection rolls back
                # the enumeration of ALL of them — and since the property lives
                # on the server, it does so on every retry and every restart,
                # taking bootstrap() (and therefore startup) with it.
                try:
                    store.upsert_collection(self.conn, c)
                except Exception:  # noqa: BLE001 — one bad collection, not all
                    log.warning("skipping collection %s: could not be cached", c.href,
                                exc_info=True)
                    continue
                kept.append(c)
            for row in store.get_collections(self.conn):
                if row["href"] not in live:
                    store.mark_collection_deleted(self.conn, row["href"])
        after = {row["href"] for row in store.get_collections(self.conn)}
        self.last_discovery_changed = after != before
        return kept

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
        bodies = self._multiget(collection_href, [i.href for i in result.changed], stats)
        with _tx(self.conn):
            for item in bodies:
                if self._upsert_body(collection_href, item, stats):
                    stats.upserted += 1
            for href in result.removed:
                uid = store.delete_item_by_href(self.conn, collection_href, href)
                if uid:
                    store.orphan_sidecar(self.conn, collection_href, uid)
                    stats.removed += 1
            # A href whose GET failed in the fallback is a change we never saw.
            # Keeping the token we asked with makes the next REPORT list it
            # again; everything cached this pass stays cached, and the deletions
            # above are idempotent on replay. See `_get_each`.
            token = (store.get_sync_token(self.conn, collection_href)
                     if stats.unread else result.token)
            store.set_sync_token(self.conn, collection_href, token,
                                 error=stats.last_error)
        return stats

    def full_resync(self, collection_href: str) -> SyncStats:
        stats = SyncStats(collection_href, full_resync=True)
        result = self.dav.sync_collection(collection_href, None)   # atomic all + fresh token
        wire = {i.href: i.etag for i in result.changed}
        known = store.known_etags(self.conn, collection_href)
        to_fetch = [h for h, etag in wire.items() if known.get(h) != etag]
        bodies = self._multiget(collection_href, to_fetch, stats)
        skipped_uids: set[str] = set()
        with _tx(self.conn):
            for item in bodies:
                if self._upsert_body(collection_href, item, stats, skipped_uids):
                    stats.upserted += 1
            # After upserts, any cached href no longer on the wire is a real
            # deletion. A delete-and-recreated UID already moved to its new href,
            # so it is NOT swept here (invariant #4 / sidecar survival).
            #
            # That holds only if the move actually landed. A body we could not
            # extract leaves its row at the OLD href, and sweeping on href alone
            # then deleted a UID that is alive on the server — precisely the
            # delete-and-recreate case, with a malformed new body. So a UID any
            # skipped resource claims is treated as still present.
            for href, uid in store.href_uid_map(self.conn, collection_href).items():
                if href in wire or uid in skipped_uids:
                    continue
                store.delete_item_by_href(self.conn, collection_href, href)
                store.orphan_sidecar(self.conn, collection_href, uid)
                stats.removed += 1
            # An unread href is still on the wire (so the sweep above kept its
            # row, if any, at its old etag) but was never cached. Recording NO
            # token — rather than a fresh one — makes the next pass a full
            # resync again, whose etag comparison re-selects exactly that href;
            # and it is not a completed full resync, so `last_full_resync_at`
            # is not stamped. The error still lands in sync_state so the
            # collection reads as unhealthy meanwhile. See `_get_each`.
            if stats.unread:
                store.set_sync_token(self.conn, collection_href, None,
                                     error=stats.last_error)
            else:
                store.set_sync_token(self.conn, collection_href, result.token,
                                     full=True, error=stats.last_error)
            # gc_orphans is the only permanent deletion of non-derivable state in
            # the app — pins, kanban column, manual order, which no resync can
            # rebuild. Never run it off an incomplete enumeration, and only over
            # the collection this pass actually enumerated: `stats.skipped` is
            # scoped to that collection, so an unscoped sweep let ANY other
            # collection resyncing cleanly delete the orphans this guard exists
            # to protect.
            if not stats.skipped:
                store.gc_orphans(self.conn, collection_href)
        return stats

    def _drop_uncacheable(self, collection_href: str, href: str, stats: SyncStats) -> None:
        """Evict the cache row at ``href``, if the body we just read means we can
        no longer back it.

        A resource that is already cached and is then rewritten on the wire into
        something we cannot extract used to leave its row completely untouched —
        old summary, old raw_ics, and old etag. The href is still on the wire, so
        the resync sweep never removed it either: the cache diverged from the
        source of truth permanently, the incremental path advanced its token past
        the change, and every full resync re-fetched (etag mismatch) and
        re-skipped forever. The stale etag also made every write on it fail, and
        the merge path then re-applied the edit to a body with nothing to edit —
        an opaque 500 on a task the UI insisted existed.

        Scoped to this href on purpose. A delete-and-recreate leaves the cached
        row at the OLD href while the new body arrives at a new one, so there is
        nothing here to drop and the row keeps surviving via ``skipped_uids`` as
        designed. Dropping (rather than flagging the row stale) is what keeps
        invariant #1: a never-cached poison resource is not cached either, so a
        wiped DB replayed from scratch reaches the same state as this one."""
        uid = store.delete_item_by_href(self.conn, collection_href, href)
        if uid is None:
            return
        store.orphan_sidecar(self.conn, collection_href, uid)
        stats.removed += 1
        log.info("dropped cache row for %s: its body is no longer readable", href)

    def _upsert_body(self, collection_href: str, item, stats: SyncStats,
                     skipped_uids: set[str] | None = None) -> bool:
        """Extract + cache one resource. Returns False for non-VTODO resources
        (e.g. a VJOURNAL sharing a mixed collection) — they are simply not tracked.
        A resource that fails to parse is skipped the same way (logged + counted):
        one malformed foreign write must not wedge the collection's sync forever.
        The token still advances; the resource is re-attempted whenever its etag
        next changes, and the failure is visible in sync_state.last_error.

        Either way, anything we already cached for this href goes — see
        ``_drop_uncacheable``."""
        if not item.data:
            return False
        try:
            fields = ical.extract_from_raw(item.data)
        except Exception as e:  # noqa: BLE001 — foreign clients can PUT anything
            log.warning("skipping malformed resource %s: %s", item.href, e)
            stats.skipped += 1
            stats.last_error = f"malformed resource {item.href}: {e}"
            if skipped_uids is not None:
                skipped_uids |= _uids_in(item.data)
            self._drop_uncacheable(collection_href, item.href, stats)
            return False
        if fields is None or not fields.uid:
            # Not a failure: the resource simply is not a task or event any more.
            # A complete, understood enumeration, so `skipped` stays untouched and
            # gc_orphans is still allowed to run at the end of the pass.
            self._drop_uncacheable(collection_href, item.href, stats)
            return False
        try:
            store.upsert_item(self.conn, collection_href, item, fields)
        except (OverflowError, ValueError, TypeError, sqlite3.InterfaceError,
                sqlite3.IntegrityError, sqlite3.ProgrammingError) as e:
            # Inside the guard, not after it. `extract_from_raw` succeeding does
            # not mean every field it produced can be STORED: a SEQUENCE past
            # SQLite's 64-bit INTEGER raised OverflowError right here, outside
            # the try above, which aborted the enclosing `_tx`. The sync token
            # was then never advanced, so the next pass re-fetched the same
            # resource and failed the same way — one foreign resource freezing
            # the entire collection's sync, permanently, for every client.
            #
            # `_int` now clamps that particular value at the boundary, but the
            # general rule is what matters: a resource we cannot cache is a
            # SKIPPED RESOURCE, exactly like one we cannot parse, and never a
            # reason to abandon the pass and lose the batch beside it.
            #
            # NARROW on purpose. A bare `except Exception` here would also
            # swallow `OperationalError: database is locked`, `disk I/O error`
            # and `database or disk is full` — transient conditions where the
            # RESOURCE is fine — and dropping the cached row and letting the pass
            # complete would advance the sync token past a change that was never
            # stored. The item would then not be re-fetched until its etag next
            # moved, so a real meeting would stop contributing a busy interval
            # and the public page would offer its hour. Those must abort the
            # transaction and be retried, which is what letting them propagate
            # does. Listed here are the errors that mean "these bytes cannot be
            # represented", which re-running cannot fix.
            log.warning("skipping uncacheable resource %s: %s", item.href, e)
            stats.skipped += 1
            stats.last_error = f"uncacheable resource {item.href}: {e}"
            if skipped_uids is not None:
                skipped_uids |= _uids_in(item.data)
            self._drop_uncacheable(collection_href, item.href, stats)
            return False
        return True

    def _multiget(self, collection_href: str, hrefs: list[str],
                  stats: SyncStats | None = None) -> list:
        out: list = []
        for i in range(0, len(hrefs), self.batch):
            batch = hrefs[i : i + self.batch]
            try:
                out.extend(self.dav.multiget(collection_href, batch))
            except MalformedResponse as e:
                # Narrow on purpose: a transport failure must NOT become fifty
                # retries. One resource Radicale cannot represent in XML — a U+FFFE in a
                # SUMMARY another client wrote — poisons the WHOLE multistatus,
                # so the batch tells us nothing about the other 49. Refetch them
                # one at a time over GET, which returns raw bytes and parses no
                # XML at all: the poisoned href fails alone and reaches
                # `_upsert_body`, whose malformed-resource path counts it skipped
                # (suppressing gc_orphans) and lets the token advance. Without
                # this the collection re-fetches the same doomed batch forever
                # and silently stops receiving any change from any client.
                log.warning("multiget failed for %s (%d hrefs), refetching "
                            "singly: %s", collection_href, len(batch), e)
                out.extend(self._get_each(batch, stats))
        return out

    def _get_each(self, hrefs: list[str], stats: SyncStats | None) -> list:
        """Per-href GET fallback. A missing href is skipped the way multiget
        skips it; a body that arrives but cannot be read is left for
        `_upsert_body` to log.

        Any other `DavError` — a read timeout, a connection reset during a
        Radicale restart, a 5xx, a 401 mid-batch — is a href whose bytes we do
        NOT have. This used to log it and move on, which on the main path would
        be unthinkable: a transport failure in `multiget` propagates and the
        pass is retried next poll. Here it was swallowed, counted nowhere, and
        the pass then committed and advanced the sync token past the change.
        `_apply_incremental` only ever asks for what changed since the stored
        token, so the resource was not requested again until its etag next
        moved: the meeting the owner had just moved on their phone kept its old
        hour in the calendar, the day view and the public booking page's busy
        set indefinitely, and `sync_state.last_error` stayed NULL so neither
        `sync_health` nor the notifier's stale-sync rule had anything to say.
        On a cold rebuild the resource was never cached at all, and with
        `stats.skipped` untouched `gc_orphans` still ran off that enumeration.

        Re-raising would restore the main-path contract but recreate the wedge
        this fallback exists to break, for a resource the server permanently
        errors on. So the failure is recorded the way a malformed body is —
        counted in `skipped` (which gates `gc_orphans`) and named in
        `last_error` — and additionally in `unread`, on which the two commit
        sites HOLD the token so the href is asked for again next pass. With no
        `stats` to record against the error propagates, as on the main path.
        """
        out: list = []
        for href in hrefs:
            try:
                out.append(self.dav.get(href))
            except NotFound:
                continue
            except DavError as e:
                if stats is None:
                    raise
                log.warning("could not read resource %s, will retry next pass: %s", href, e)
                stats.skipped += 1
                stats.unread += 1
                stats.last_error = f"unreadable resource {href}: {e}"
        return out

    # ── write path ───────────────────────────────────────────────────────────
    def create_task(
        self,
        collection_href: str,
        summary: str,
        *,
        edit: ical.TaskEdit | None = None,
        parent_uid: str | None = None,
        slug: str | None = None,
    ) -> str:
        if not store.has_collection(self.conn, collection_href):
            raise ValueError(f"collection {collection_href} is unknown; run discover() first")
        # The href SLUG is kept URL-safe (plain hex) so our own resource paths are
        # already in Radicale's canonical form — Radicale percent-encodes reserved
        # characters (e.g. '@' -> '%40'), which would otherwise make the href we
        # cache at create time differ from the one sync reports. The UID may still
        # carry '@'; it is the join key, never the href (invariant #4).
        slug = slug or uuid.uuid4().hex
        uid = f"{slug}@tasksd"
        raw = ical.build_new(uid, summary=summary, edit=edit, related_parent=parent_uid)
        href = f"{collection_href}{slug}.ics"
        self._put_new(href, uid, raw)
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
        slug: str | None = None,
    ) -> str:
        if not store.has_collection(self.conn, collection_href):
            raise ValueError(f"collection {collection_href} is unknown; run discover() first")
        slug = slug or uuid.uuid4().hex
        uid = f"{slug}@tasksd"
        raw = ical.build_new_event(uid, summary=summary, dtstart=dtstart, dtend=dtend, edit=edit)
        href = f"{collection_href}{slug}.ics"
        self._put_new(href, uid, raw)
        self._refresh_from_wire(collection_href, href)
        return uid

    def _put_new(self, href: str, uid: str, raw: str) -> None:
        """First write of a new resource. With a caller-supplied slug the href is
        deterministic per logical create, so a replay (retry after a lost
        response, transport-level resend) finds the resource already on the
        server — that is the create succeeding, not a conflict, as long as the
        occupant is ours (same UID). A slug collision with someone else's
        resource is the only true conflict."""
        try:
            self.dav.put(href, raw, if_none_match="*")
        except PreconditionFailed as e:
            stored = self.dav.get(href)
            fields = ical.extract_from_raw(stored.data)
            if fields is None or fields.uid != uid:
                # The href names the Radicale user and the collection's UUID, and
                # `app.py` returns `str(exc)` verbatim as the 409 body — including
                # on POST /api/public/booking/{token}/book, the one write path an
                # anonymous caller reaches. `test_public_page_requires_no_auth_
                # and_leaks_nothing` asserts the public payload carries no hrefs;
                # this raise handed one over. Log it, answer without it — the
                # shape `SlotTaken` already uses on that route.
                log.warning("create collided with a foreign resource at %s", href)
                raise ConflictError(
                    "a different resource already exists with that client_id"
                ) from e

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

    def move_event(self, src_href: str, dst_href: str, uid: str) -> str:
        """Move a whole event resource (including any overrides) to another
        calendar. Copy-then-delete: the destination PUT is If-None-Match guarded
        so an existing resource is never clobbered, and the source delete is
        etag-guarded (invariant #2: the raw bytes move untouched).

        The bytes come off the WIRE, not the cache. The cache lags Radicale by up
        to one poll, and it is normal for another CalDAV client to edit an event
        inside that window — copying ``raw_ics`` wrote the pre-edit body to the
        destination. The source delete could not save it either: ``delete_task``
        answers its own 412 by re-reading the current etag and deleting anyway,
        which is right for an explicit user delete but here destroyed the only
        copy of the newer revision. Measured before this change: a foreign
        LOCATION + time change vanished and the move still returned 200.
        """
        if not store.has_collection(self.conn, dst_href):
            raise ValueError(f"collection {dst_href} is unknown; run discover() first")
        row = store.get_item(self.conn, src_href, uid)
        if row is None:
            raise KeyError(f"unknown event {uid} in {src_href}")
        basename = row["href"].rstrip("/").rsplit("/", 1)[-1]
        new_href = f"{dst_href}{basename}"
        current = self.dav.get(row["href"])      # NotFound => already gone; surfaces as 404
        try:
            self.dav.put(new_href, current.data, if_none_match="*")
        except (PreconditionFailed, Conflict) as e:
            # PreconditionFailed covers an occupied HREF. Radicale also enforces
            # UID uniqueness per collection and answers 409 `no-uid-conflict` when
            # the same UID already lives there under a different filename — the
            # same condition, a different spelling, and it sailed past this guard
            # onto app.py's DavError catch-all, telling the user "calendar server
            # unavailable, try again shortly" (502) about a conflict this line
            # already has the right words for. `Conflict`'s own docstring in
            # dav/errors.py lists MKCALENDAR cases and not this one, which is
            # what made the omission look deliberate.
            #
            # But the occupant is USUALLY OUR OWN COPY. `new_href` is
            # deterministic, so a retry after a lost DELETE reply lands on the
            # resource the previous attempt wrote — and answering that with a
            # terminal conflict left the event in both calendars with no way to
            # finish the move, while telling the caller (409 over HTTP, "try
            # again shortly" over MCP) something close to the opposite. This is
            # `_put_new`'s replay tolerance, applied to the same problem: read
            # the occupant, and only a resource that is NOT ours is a conflict.
            self._adopt_moved_copy(new_href, uid, current, e)
        try:
            self.dav.delete(row["href"], if_match=current.etag)
        except PreconditionFailed as e:
            # Edited again between our GET and the DELETE. Undo the copy and make
            # the caller retry rather than silently discarding that revision.
            try:
                self.dav.delete(new_href, if_match=None)
            except DavError:
                log.warning("move_event: could not roll back the copy at %s", new_href)
            raise ConflictError(f"event {uid} changed during the move; retry") from e
        except DavError:
            # A lost reply, a 403, a 423. The copy is NOT rolled back: unlike the
            # 412 above, this is precisely the case where the delete cannot be
            # proved not to have happened, and undoing it would risk destroying
            # the only remaining copy. The retry now completes the move (the
            # branch above adopts our own copy), so the duplicate is transient —
            # but only if someone retries, so say so loudly rather than letting a
            # silent second copy reach the calendar, the busy set and the
            # booking-conflict check.
            log.error(
                "move_event: %s was copied to %s but the source delete at %s failed; "
                "the event is in BOTH calendars until the move is retried",
                uid, new_href, row["href"], exc_info=True)
            raise
        with _tx(self.conn):
            store.delete_item_by_href(self.conn, src_href, row["href"])
            store.orphan_sidecar(self.conn, src_href, uid)
        return self._refresh_from_wire(dst_href, new_href)

    def _adopt_moved_copy(self, new_href: str, uid: str, current, cause: DavError) -> None:
        """The destination href is occupied. Treat it as the move's own earlier
        copy when it carries `uid`; raise `ConflictError` when it is a stranger's.

        The occupant is REFRESHED from `current` rather than merely accepted. The
        source can be edited by another client between the attempt that landed
        the copy and the retry that finds it, and the source is about to be
        deleted — so adopting the older bytes unchanged would discard that
        revision exactly as copying from the cache used to (see the docstring
        above). `if_match` keeps that write from clobbering a destination that
        moved underneath us in turn.

        A `Conflict` whose occupant is NOT at `new_href` (Radicale's
        `no-uid-conflict`: the same UID under a different filename) reads as a
        404 here and stays a conflict. That is the right answer either way — the
        UID is already in the destination and this engine did not put it there.
        """
        try:
            stored = self.dav.get(new_href)
            fields = ical.extract_from_raw(stored.data)
        except NotFound:
            fields = None
        if fields is None or fields.uid != uid:
            log.warning("move_event: %s is occupied by another resource", new_href)
            raise ConflictError(
                f"event {uid} already exists in the target calendar") from cause
        try:
            self.dav.put(new_href, current.data, if_match=stored.etag)
        except PreconditionFailed as e:
            raise ConflictError(f"event {uid} changed during the move; retry") from e

    def shift_event(
        self, collection_href: str, uid: str, recurrence_id: str, edit: ical.EventEdit
    ) -> str:
        """Reschedule a whole series ("all events" with a time change)."""
        return self._edit(
            collection_href, uid,
            lambda raw, e: ical.shift_series(raw, recurrence_id, e),
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
        # Write the tail BEFORE truncating the head: a crash or transport error
        # between the two PUTs then leaves visible, recoverable duplicate
        # occurrences instead of silently deleting every "following" one.
        tail_href: str | None = None
        if not delete_tail:
            tail_href = f"{collection_href}{uuid.uuid4().hex}.ics"
            self.dav.put(tail_href, tail, if_none_match="*")
            tail_uid = ical.extract_from_raw(tail).uid

        def write_head(ics: bytes | None, etag: str | None) -> None:
            # A head of None means the split left nothing before the anchor —
            # the anchor was the series' first occurrence. PUTting that husk
            # left a resource expanding to zero occurrences on the server
            # forever: nothing renders it, so nothing can delete it either, and
            # "delete this and following" from the first occurrence answered 204
            # while deleting nothing at all.
            if ics is None:
                self.dav.delete(href, if_match=etag)
            else:
                self.dav.put(href, ics, if_match=etag)

        # Whether the head write might have LANDED. The distinction is the whole
        # of the cleanup below: a 412 or a 409 is the server REFUSING, so the head
        # is provably untouched and the tail is safely removable — but a transport
        # error is a write whose outcome we do not know, and the commit may have
        # happened with only the reply lost. Deleting the tail then destroys the
        # only copy of every "following" occurrence, which is exactly what writing
        # the tail first (see above) exists to prevent.
        head_uncertain = False
        try:
            try:
                head_uncertain = True
                write_head(head, row["etag"])
                head_uncertain = False
            except PreconditionFailed:
                head_uncertain = False
                fresh = self.dav.get(href)
                head, tail = build(fresh.data)
                if tail_href is not None:
                    # `split_series` mints a fresh uuid4 UID for the tail on every
                    # call, so the rebuilt body carries a DIFFERENT UID than the
                    # resource already sitting at `tail_href` — and Radicale
                    # refuses exactly that with 409 `no-uid-conflict`. Which is
                    # `Conflict`, not `PreconditionFailed`, so it escaped the
                    # whole handler: the head was never truncated, the tail was
                    # never cleaned up, and the user was told the calendar server
                    # was unavailable. Re-stamping the first UID makes the
                    # replacement an ordinary overwrite of our own resource.
                    tail = _restamp_uid(tail, tail_uid)
                    self.dav.put(tail_href, tail)
                try:
                    head_uncertain = True
                    write_head(head, fresh.etag)
                    head_uncertain = False
                except PreconditionFailed as e:
                    head_uncertain = False
                    raise ConflictError(
                        f"edit conflict on {uid}: retry the change") from e
        except BaseException:
            # Wider than the inner `except PreconditionFailed` it replaced, which
            # covered ONE of the ways this can fail: a concurrent delete of the
            # master makes `self.dav.get(href)` raise NotFound, and a rebuild that
            # now refuses the anchor raises ValueError — both used to leave a
            # headless duplicate series on the owner's calendar under a UID
            # nothing else references.
            #
            # But NOT unconditional. `head_uncertain` means a head write was in
            # flight when this failed, so the truncation may have committed with
            # only the response lost; deleting the tail there destroys the later
            # occurrences and tells the user the operation failed. Leaving a
            # visible duplicate is the recoverable direction, and it is the one
            # this function's write-tail-first ordering was chosen for.
            if tail_href is not None and not head_uncertain:
                try:
                    self.dav.delete(tail_href)
                except DavError:
                    log.warning("split_event: could not clean up the tail at %s",
                                tail_href)
            elif tail_href is not None:
                log.error(
                    "split_event: a head write for %s was in flight when the split "
                    "failed, so it may have committed; leaving the tail at %s rather "
                    "than risk deleting the only copy of the later occurrences",
                    uid, tail_href,
                )
            raise
        if head is None:
            # The resource is gone from the wire, so there is nothing to read
            # back — purge the projection the way delete_task does.
            with _tx(self.conn):
                store.delete_item_by_href(self.conn, collection_href, href)
                store.orphan_sidecar(self.conn, collection_href, uid)
        else:
            self._refresh_from_wire(collection_href, href)
        if tail_href is not None:
            self._refresh_from_wire(collection_href, tail_href)
        return uid

    def _edit(self, collection_href: str, uid: str, apply_fn, edit, *, kind: str) -> str:
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            raise KeyError(f"unknown {kind} {uid} in {collection_href}")
        href = row["href"]
        # A body with no component left to edit is a conflict with what another
        # client did, not a bad request: someone rewrote the resource into
        # something that is no longer a task or an event between our last sync
        # and this write. Unhandled, the ValueError escaped as a 500. Only
        # NotEditable is remapped — the other ValueErrors from these helpers (an
        # all-day <-> timed series switch) are about the request and keep their 422.
        try:
            body = apply_fn(row["raw_ics"], edit)
        except ical.NotEditable as e:
            raise ConflictError(f"{kind} {uid} can no longer be edited: {e}") from e
        try:
            self.dav.put(href, body, if_match=row["etag"])
        except PreconditionFailed:
            # invariant #5: a concurrent write beat us. Re-GET, re-apply the same
            # field intent onto the fresh copy (preserving the other writer's
            # fields), retry exactly once, then surface a conflict.
            fresh = self.dav.get(href)
            try:
                merged = apply_fn(fresh.data, edit)
            except ical.NotEditable as e:
                raise ConflictError(f"{kind} {uid} can no longer be edited: {e}") from e
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
            # Changed under us. Deleting "the current revision" is only correct if
            # the current revision is still the resource we were asked to delete:
            # a href can start carrying a different UID (a foreign client
            # rewriting the body in place, or a restored .ics landing at an
            # existing path), and force-deleting then destroys somebody else's
            # live resource on a delete of ours. Re-read and check identity first.
            try:
                fresh = self.dav.get(href)
            except NotFound:
                fresh = None
            if fresh is not None:
                current = ical.extract_from_raw(fresh.data)
                if current is not None and current.uid != uid:
                    raise ConflictError(
                        f"{href} no longer holds {uid} (now {current.uid}); refusing to delete it"
                    )
                try:
                    self.dav.delete(href, if_match=fresh.etag)
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
