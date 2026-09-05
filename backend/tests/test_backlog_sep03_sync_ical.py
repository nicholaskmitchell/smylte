"""The 2026-09-03 sweep: the sync engine and the iCalendar edit path.

Four findings, all in the code that stands between the CalDAV wire and what
the app shows, and all of the same shape: a boundary case the read side had
already been taught to survive that the write side — or the *other* read path —
never learned. Each pin asserts the corrected behaviour and was confirmed to
fail against the code as found; each is behavioural and in-process, driving the
real `SyncEngine` against a token-aware DAV double or the real edit functions
over `tests/helpers` foreign resources, so none needs the scratch Radicale.

  * `_get_each`, the per-href GET fallback `_multiget` takes when one resource
    (a U+FFFE in a SUMMARY) makes the whole multistatus unparseable, swallowed
    every `DavError` but `NotFound`. A read timeout on one GET in that fallback
    dropped the href, counted nothing, recorded nothing, and let the sync token
    advance past a change that was never cached — so the app kept showing the
    old time of a meeting the owner had moved until the meeting was edited
    again, and `sync_health` reported the collection clean. On a cold rebuild
    the resource was never cached at all, and `gc_orphans` still ran off the
    incomplete enumeration. STAGE 3.
  * `_require_addressable` accepted an anchor equal to the master's own DTSTART
    before asking whether the resource repeats. Right for `shift_series`
    (scope='all' with a recurrence_id is a plain reschedule), wrong for the two
    per-occurrence writers: on a one-off event `exclude_occurrence` wrote an
    EXDATE beside no rule and `apply_occurrence_override` appended a
    RECURRENCE-ID component — both PUT fine, the route answered 200/204, and
    every read still showed the untouched master. STAGE 3, with the CONTROL that
    `shift_series` must keep accepting that anchor.
  * `_uids_in`, the textual UID scan that keeps a delete-and-recreated item in
    the cache when its new body cannot be parsed, matched one physical line, so
    a UID long enough to be folded (Outlook's 100+ hex characters) was read
    truncated and the guard it feeds swept the live item. STAGE 3.
  * `_stamp` and `apply_changes` bumped SEQUENCE with a bare `int()`, so the
    out-of-range or non-numeric SEQUENCE the read path was taught to read as
    absent made the resource permanently uneditable: every rename, drag,
    complete, exclude and split answered 422 with icalendar's internal message
    (or a 500 on the task routes). STAGE 4.

Run just this file with `pytest tests/test_backlog_sep03_sync_ical.py`.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from helpers import foreign_event_raw, foreign_raw

from tasksd import ical
from tasksd.dav.client import CollectionInfo, Item, SyncResult
from tasksd.dav.errors import DavError, MalformedResponse, NotFound
from tasksd.db import store
from tasksd.ical.edit import (
    EventEdit,
    TaskEdit,
    apply_changes,
    apply_event_changes,
    apply_occurrence_override,
    exclude_occurrence,
    shift_series,
    split_series,
)
from tasksd.ical.recur import expand_occurrences
from tasksd.sync import SyncEngine

pytestmark = [pytest.mark.backlog, pytest.mark.stage3]

COL = "/u/cal/"
POISON = f"{COL}poison.ics"
MEETING = f"{COL}meeting.ics"
WINDOW = (date(2026, 1, 1), date(2026, 3, 1))


def _db():
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.upsert_collection(
        conn, CollectionInfo(href=COL, displayname="Cal", components={"VTODO", "VEVENT"})
    )
    return conn


def _summary(conn, uid: str) -> str | None:
    row = store.get_item(conn, COL, uid)
    return None if row is None else row["summary"]


class _JournalDav:
    """A token-aware, read-only DAV double whose multistatus is always poisoned.

    The read-only fakes in the suite hand back one static collection state
    whatever token they are given, which cannot show this finding: the whole
    defect is that the token advances past a change and the NEXT incremental
    pass therefore never asks for it again. So `sync_collection` here answers
    the RFC 6578 question honestly — what changed since `token` — over a journal
    of published snapshots.

    `multiget` raises `MalformedResponse` unconditionally, standing in for what
    the real client does when one resource in the batch carries a character XML
    cannot represent (reproduced against the scratch Radicale with a SUMMARY
    containing U+FFFE): the engine then falls back to one GET per href, which is
    the path under test. `failing` names hrefs whose GET raises the bare
    `DavError` `DavClient._request` wraps every httpx transport failure in;
    `vanished` names hrefs whose GET 404s.
    """

    def __init__(self):
        self.snapshots: dict[str | None, dict[str, Item]] = {None: {}}
        self.token: str | None = None
        self.failing: set[str] = set()
        self.vanished: set[str] = set()

    def publish(self, token: str, items: list[Item]) -> None:
        self.snapshots[token] = {i.href: i for i in items}
        self.token = token

    def sync_collection(self, href: str, token: str | None) -> SyncResult:
        base = self.snapshots.get(token, {})
        latest = self.snapshots[self.token]
        changed = [Item(h, i.etag) for h, i in latest.items()
                   if h not in base or base[h].etag != i.etag]
        removed = [h for h in base if h not in latest]
        return SyncResult(token=self.token, changed=changed, removed=removed)

    def multiget(self, href: str, hrefs: list[str]) -> list[Item]:
        raise MalformedResponse("unparseable multistatus: PCDATA invalid Char value 65534")

    def get(self, href: str) -> Item:
        if href in self.failing:
            raise DavError(f"transport error on GET {href}: read timeout")
        item = self.snapshots[self.token].get(href)
        if item is None or href in self.vanished:
            raise NotFound(f"GET {href} -> 404")
        return item


def _poison(etag: str, summary: str = "groceries ￾") -> Item:
    return Item(POISON, etag, foreign_raw("poison@x", summary))


def _meeting(etag: str, summary: str) -> Item:
    return Item(MEETING, etag, foreign_event_raw("meeting@x", summary))


# ── _get_each ────────────────────────────────────────────────────────────────

def test_a_get_that_fails_in_the_multiget_fallback_does_not_advance_the_token_past_the_change():
    """The owner moves a meeting on the phone; the same poll window also carries
    a change to the poison resource, so the batch takes the per-href fallback;
    the meeting's GET times out. The next poll, once the network is back, MUST
    fetch the meeting — and the pass that lost it must say so in
    `sync_state.last_error`, which is what `sync_health` and the notifier's
    stale-sync rule read. Against the code as found the blip pass reported
    `last_error=None`, advanced the token, and three further polls upserted
    nothing: the calendar, the day view and the public booking page kept the old
    time until the meeting was edited again.

    The repair the pin accepts is any of: the token held so the href is asked
    for again, or the pass aborted so nothing commits and the next poll retries.
    Either way the healed poll must produce the new summary. Dropping the
    `except DavError` outright would also satisfy this, but re-creates the wedge
    the fallback exists to avoid for a resource the server permanently 5xxes on
    GET, so the engine holds the token and records the failure instead."""
    conn = _db()
    dav = _JournalDav()
    dav.publish("tok-1", [_poison('"p1"'), _meeting('"e1"', "Dentist 3pm")])
    engine = SyncEngine(dav, conn)
    first = engine.sync(COL)
    assert first.upserted == 2 and _summary(conn, "meeting@x") == "Dentist 3pm"

    dav.publish("tok-2", [_poison('"p2"', "groceries ￾ and milk"),
                          _meeting('"e2"', "Dentist MOVED to 9am")])
    dav.failing.add(MEETING)
    blip = engine.sync(COL)
    assert _summary(conn, "meeting@x") == "Dentist 3pm"        # nothing to cache yet

    dav.failing.clear()
    engine.sync(COL)
    assert _summary(conn, "meeting@x") == "Dentist MOVED to 9am", (
        "the sync token advanced past a change whose GET failed; the cache "
        "diverged from the server with no way back short of another edit")
    # And the pass that could not read the href must not have looked healthy.
    assert blip.last_error is not None and MEETING in blip.last_error
    assert store.get_sync_token(conn, COL) == "tok-2"          # healed pass committed


def test_a_cold_rebuild_that_could_not_read_a_resource_is_not_a_complete_enumeration():
    """Neighbour to the pin above, for the variant the verifier measured as
    worse: on a first sync or an invariant-#1 rebuild every href is in the
    fetch set, so the poisoned batch always takes the fallback, and a GET that
    fails there leaves the resource ABSENT rather than stale. It must be cached
    by the next healed pass, and the pass that missed it must count it skipped
    so `full_resync` does not run `gc_orphans` off an enumeration it knows is
    incomplete — the same gate the malformed-resource path already uses."""
    conn = _db()
    dav = _JournalDav()
    dav.publish("tok-1", [_poison('"p1"'), _meeting('"e1"', "Dentist 3pm")])
    dav.failing.add(MEETING)
    engine = SyncEngine(dav, conn)
    cold = engine.sync(COL)
    assert cold.full_resync and _summary(conn, "meeting@x") is None

    dav.failing.clear()
    engine.sync(COL)
    assert _summary(conn, "meeting@x") == "Dentist 3pm", (
        "a resource whose GET failed during the rebuild was never asked for again")
    assert cold.skipped >= 1 and cold.last_error is not None


def test_a_vanished_href_in_the_multiget_fallback_still_lets_the_token_advance():
    """CONTROL. The one `DavError` the fallback always tolerated — a 404, the
    resource deleted between the REPORT and the GET, which multiget would
    simply have omitted — must keep being a non-event: no error recorded, token
    advanced, the deletion arriving in `removed` on a later pass as usual."""
    conn = _db()
    dav = _JournalDav()
    dav.publish("tok-1", [_poison('"p1"'), _meeting('"e1"', "Dentist 3pm")])
    engine = SyncEngine(dav, conn)
    engine.sync(COL)

    dav.publish("tok-2", [_poison('"p2"'), _meeting('"e2"', "Dentist MOVED to 9am")])
    dav.vanished.add(MEETING)
    stats = engine.sync(COL)
    assert stats.last_error is None and stats.skipped == 0
    assert store.get_sync_token(conn, COL) == "tok-2"


# ── _require_addressable ─────────────────────────────────────────────────────

ONE_OFF_START = "2026-01-06T09:00:00+00:00"       # foreign_event_raw's default DTSTART


def test_a_per_occurrence_edit_on_a_one_off_event_is_refused_not_written_where_no_reader_looks():
    """`exclude_occurrence` and `apply_occurrence_override` on a resource with
    no RRULE and no RDATE, anchored at its own DTSTART — the only anchor that
    slipped through, since any other already got the 422. Both must raise the
    ValueError the routes map to 422 and the MCP tools to a ToolError. Against
    the code as found both succeeded: the first wrote `EXDATE:<DTSTART>` beside
    no rule (which also ate the first occurrence of any series the owner later
    made of it), the second appended a RECURRENCE-ID override that
    `find_component` never picks — and `has_rrule` stayed False, so
    `events_in_range` and `get_event` went on returning the untouched master.

    The message is `_require_occurrence`'s "does not repeat; use scope='all'":
    for these two callers scope='all' is exactly the right advice, which is the
    one case the guard's own comment says that sentence fits."""
    raw = foreign_event_raw("plain")                          # no RRULE, no RDATE
    with pytest.raises(ValueError, match="does not repeat"):
        exclude_occurrence(raw, ONE_OFF_START)
    with pytest.raises(ValueError, match="does not repeat"):
        apply_occurrence_override(raw, ONE_OFF_START, EventEdit(summary="renamed"))
    # A wrong anchor keeps its own, already-correct refusal.
    with pytest.raises(ValueError, match="does not name an occurrence"):
        exclude_occurrence(raw, "2026-01-07T09:00:00+00:00")


def test_the_first_occurrence_of_a_series_and_a_one_off_reschedule_are_still_addressable():
    """CONTROL, guarding the over-correction. The DTSTART shortcut exists for
    `shift_series` — `scope='all'` with a `recurrence_id` on a one-off is a plain
    reschedule, pinned by `test_a_non_repeating_event_is_told_what_is_actually_wrong`
    — and the first occurrence of a real series (RRULE or RDATE-only) is a
    legitimate per-occurrence target. None of that may be refused."""
    raw = foreign_event_raw("plain")
    moved = shift_series(raw, ONE_OFF_START, EventEdit(dtstart=datetime(2026, 1, 6, 11, 0)))
    assert [o.start for o in expand_occurrences(moved, *WINDOW)] == [
        "2026-01-06T11:00:00+00:00"]

    weekly = foreign_event_raw("weekly", rrule="FREQ=WEEKLY;COUNT=3")
    trimmed = exclude_occurrence(weekly, ONE_OFF_START)
    assert [o.start for o in expand_occurrences(trimmed, *WINDOW)] == [
        "2026-01-13T09:00:00+00:00", "2026-01-20T09:00:00+00:00"]
    renamed = apply_occurrence_override(weekly, ONE_OFF_START, EventEdit(summary="first"))
    assert [o.summary for o in expand_occurrences(renamed, *WINDOW)] == [
        "first", "Event", "Event"]

    by_rdate = foreign_event_raw("rdates", rdate="20260113T090000Z")
    trimmed = exclude_occurrence(by_rdate, ONE_OFF_START)
    assert [o.start for o in expand_occurrences(trimmed, *WINDOW)] == [
        "2026-01-13T09:00:00+00:00"]


# ── _uids_in ─────────────────────────────────────────────────────────────────

# An Outlook/Exchange-style UID: 112 characters, well past the 71 that fit on
# the first physical line once `UID:` has been written.
LONG_UID = "040000008200E00074C5B7101A82E00800000000" + "A" * 60 + "@example.com"


def _fold(raw: bytes) -> bytes:
    """RFC 5545 §3.1 folding at 75 octets, as icalendar and Radicale both emit
    it. The engine reads whatever the server serves, and the server folds."""
    out: list[bytes] = []
    for line in raw.split(b"\r\n"):
        while len(line) > 75:
            out.append(line[:75])
            line = b" " + line[75:]
        out.append(line)
    return b"\r\n".join(out)


def test_a_recreated_item_with_a_folded_uid_survives_a_malformed_new_body():
    """`test_resync_keeps_a_recreated_item_whose_new_body_is_malformed` with a
    UID long enough to be folded — the exact sequence that test pins, which the
    guard lost for any UID over ~71 octets because `_uids_in` matched one
    physical line and compared a truncated string against the cached uid."""
    assert len(LONG_UID) > 71
    conn = _db()
    good = _fold(foreign_raw(LONG_UID, "Ship it"))
    engine = SyncEngine(_Static([Item(f"{COL}A.ics", '"e1"', good)]), conn)
    engine.sync(COL)
    assert store.get_item(conn, COL, LONG_UID) is not None
    store.set_sidecar(conn, COL, LONG_UID, kanban_column="doing", sort_order=2.5)

    # Another client delete-and-recreates it at a new href, with a body Radicale
    # accepts and `extract_from_raw` rejects (PRIORITY:HIGH).
    poison = _fold(foreign_raw(LONG_UID, "Ship it", extra=("PRIORITY:HIGH",)))
    engine2 = SyncEngine(_Static([Item(f"{COL}B.ics", '"e2"', poison)]), conn)
    stats = engine2.full_resync(COL)

    assert stats.skipped == 1
    assert stats.removed == 0, "a live item with a folded UID was swept out of the cache"
    assert store.get_item(conn, COL, LONG_UID) is not None
    sidecar = store.get_sidecar(conn, COL, LONG_UID)
    assert sidecar is not None and sidecar["orphaned_at"] is None


class _Static:
    """The one-state read-only double `test_sync_unit.py` uses, for the
    full_resync sweep where the token does not matter."""

    def __init__(self, items: list[Item]):
        self.items = items

    def sync_collection(self, href: str, token: str | None) -> SyncResult:
        return SyncResult(token="tok-1", changed=[Item(i.href, i.etag) for i in self.items],
                          removed=[])

    def multiget(self, href: str, hrefs: list[str]) -> list[Item]:
        return [i for i in self.items if i.href in hrefs]


# ── SEQUENCE ─────────────────────────────────────────────────────────────────

SEQ_ANCHOR = "2026-01-07T09:00:00+00:00"          # second of FREQ=DAILY;COUNT=5


@pytest.mark.stage4
@pytest.mark.parametrize("seq", ["99999999999999999999", "abc", "2147483647"])
def test_a_sequence_the_read_path_ignores_does_not_make_the_resource_uneditable(seq):
    """The write-side twin of `test_an_out_of_range_sequence_cannot_stall_the_collection`.
    The three shapes are the ones the audit established Radicale round-trips:
    past int64 (read as absent), non-numeric (read as absent), and the int32
    ceiling itself (read fine, but +1 is out of RFC 5545's range for icalendar).
    Every VEVENT writer funnels through `_stamp` and every VTODO writer through
    `apply_changes`; each must succeed and leave a SEQUENCE the read path can
    read back and other clients can parse."""
    raw = foreign_event_raw("seq", extra=(f"SEQUENCE:{seq}",), rrule="FREQ=DAILY;COUNT=5")
    renamed = apply_event_changes(raw, EventEdit(summary="y"))
    fields = ical.extract_from_raw(renamed)
    assert fields.summary == "y"
    assert fields.sequence is not None and 0 < fields.sequence <= 2**31 - 1
    exclude_occurrence(raw, SEQ_ANCHOR)
    apply_occurrence_override(raw, SEQ_ANCHOR, EventEdit(summary="y"))
    head, tail = split_series(raw, SEQ_ANCHOR, EventEdit(summary="y"))
    assert head is not None and tail is not None

    todo = foreign_raw("t", "task", extra=(f"SEQUENCE:{seq}",))
    try:
        ical.extract_from_raw(todo)
    except ValueError:
        # Measured, not assumed: icalendar 7.3 parses a bad SEQUENCE on a VEVENT
        # into a `vBroken` but RAISES for the same line on a VTODO, so the read
        # path rejects it too — a task in this shape is a skipped malformed
        # resource that never syncs, and there is no task write path to reach.
        # The verifier's "the VTODO twin fails identically" is true at the unit
        # level and unreachable in the app for these two values; only the int32
        # ceiling parses as a task, and that one is asserted below.
        return
    done = apply_changes(todo, TaskEdit(status="COMPLETED"))
    assert ical.extract_from_raw(done).status == "COMPLETED"
    assert ical.extract_from_raw(apply_changes(todo, TaskEdit(summary="z"))).summary == "z"


def test_an_ordinary_sequence_is_still_bumped_by_one():
    """CONTROL. The tolerance is for values that are not sequence numbers;
    a real one keeps counting, which is what tells other clients to re-read."""
    raw = foreign_event_raw("seq5", extra=("SEQUENCE:5",))
    assert ical.extract_from_raw(apply_event_changes(raw, EventEdit(summary="y"))).sequence == 6
    todo = foreign_raw("t5", "task", extra=("SEQUENCE:5",))
    assert ical.extract_from_raw(apply_changes(todo, TaskEdit(summary="z"))).sequence == 6
