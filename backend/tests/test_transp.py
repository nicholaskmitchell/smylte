"""TRANSP — "Busy" and "Free" as every other calendar client spells it.

RFC 5545 §3.8.2.7 gives a VEVENT two values for whether it consumes time:
OPAQUE (it does) and TRANSPARENT (it does not), with OPAQUE as the default when
the property is absent. Apple Calendar renders it as "Busy/Free", Google the
same, Thunderbird as "Show Time As" — so it is a control the owner has already
been offered by the clients sharing these collections, and one they may already
have used on events this app now reads.

It matters here because of what reads it: the busy set behind the PUBLIC booking
page. An event the owner marked Free is one they have said does not block, in as
many words, and a booking page that blocked it anyway would be the one reader on
the account overruling them. The tests below therefore run the whole way from a
raw VEVENT another client PUT to a slot being offered.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from helpers import foreign_event_raw

from tasksd import scheduling
from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import EventEdit, apply_event_changes, blocks_time, build_new_event
from tasksd.ical import extract_from_raw
from tasksd.service import TaskService

TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 7, 13, 8, 0, tzinfo=TZ)          # a Monday morning, link-local
CAL = "/u/meetings/"


# ── the default, decided once ───────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (None, True),                  # absent — RFC 5545's own default is OPAQUE
    ("", True),
    ("OPAQUE", True),
    ("TRANSPARENT", False),
    ("transparent", False),        # the property is case-insensitive on read
    ("  TRANSPARENT  ", False),    # …and a folded line can arrive padded
    ("MAYBE", True),               # a third word is a foreign client's bug
    ("TRANSPARENT-ISH", True),     # …and near-misses are not near-enough
])
def test_blocks_time_reads_the_spec_default(value, expected):
    """Every way of not knowing lands on BUSY.

    That is the direction the booking page needs: reading an unknown as free
    hands an anonymous visitor the owner's real appointment, and reading it as
    busy costs them one slot they could have offered.
    """
    assert blocks_time(value) is expected


# ── the read path ───────────────────────────────────────────────────────────

def test_extract_reads_transp_off_the_wire():
    raw = foreign_event_raw("free", extra=("TRANSP:TRANSPARENT",))
    assert extract_from_raw(raw).transp == "TRANSPARENT"

    raw = foreign_event_raw("busy", extra=("TRANSP:OPAQUE",))
    assert extract_from_raw(raw).transp == "OPAQUE"

    # Absent stays absent rather than being normalised on the way in: the column
    # says what the resource says, and `blocks_time` is where the default lives.
    assert extract_from_raw(foreign_event_raw("plain")).transp is None


def test_a_vtodo_never_carries_transp():
    """TRANSP is a VEVENT property. A task has no span to be transparent over,
    and the extractor's VEVENT arm is the only place it is read."""
    raw = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        "BEGIN:VTODO\r\nUID:t1\r\nSUMMARY:Task\r\nTRANSP:TRANSPARENT\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    ).encode()
    assert extract_from_raw(raw).transp is None


# ── the write path ──────────────────────────────────────────────────────────

def test_edit_writes_both_spellings_and_removes_on_none():
    raw = foreign_event_raw("e1")
    free = apply_event_changes(raw, EventEdit(busy=False)).decode()
    assert "TRANSP:TRANSPARENT" in free

    # Back to busy writes OPAQUE EXPLICITLY rather than dropping the line. The
    # owner has just touched a control every other client shows them; "I set
    # this back to Busy" reaching the wire as an absence is a change none of
    # them can see was made.
    back = apply_event_changes(free.encode(), EventEdit(busy=True)).decode()
    assert "TRANSP:OPAQUE" in back
    assert "TRANSP:TRANSPARENT" not in back

    # None is the one value that removes the property.
    gone = apply_event_changes(back.encode(), EventEdit(busy=None)).decode()
    assert "TRANSP" not in gone


def test_an_untouched_edit_leaves_a_foreign_transp_alone():
    """Invariant #2: a property another client authored is not ours to rewrite
    in passing. A rename that also stamped TRANSP would silently un-mark every
    event someone had marked Free in Apple Calendar."""
    raw = foreign_event_raw("e1", extra=("TRANSP:TRANSPARENT",))
    out = apply_event_changes(raw, EventEdit(summary="Renamed")).decode()
    assert "SUMMARY:Renamed" in out
    assert "TRANSP:TRANSPARENT" in out


def test_build_new_event_writes_transp_only_when_asked():
    plain = build_new_event("u1", summary="Chat", dtstart=datetime(2026, 7, 13, 9, 0)).decode()
    # No opinion, no line — and an absent TRANSP is OPAQUE, so the event this
    # app has always written means exactly what it always meant.
    assert "TRANSP" not in plain

    free = build_new_event(
        "u2", summary="Hold", dtstart=datetime(2026, 7, 13, 9, 0),
        edit=EventEdit(busy=False),
    ).decode()
    assert "TRANSP:TRANSPARENT" in free


# ── the DTO ─────────────────────────────────────────────────────────────────

def _settings() -> Settings:
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


@pytest.fixture
def svc():
    s = TaskService(_settings())
    store.upsert_collection(
        s._conn, CollectionInfo(href=CAL, displayname="Meetings", components={"VEVENT"})
    )
    yield s
    s.close()


def _seed(svc, uid: str, raw: bytes) -> None:
    store.upsert_item(svc._conn, CAL, Item(f"{CAL}{uid}.ics", '"1"', raw), extract_from_raw(raw))


def test_the_event_dto_answers_busy(svc):
    _seed(svc, "free", foreign_event_raw(
        "free", dtstart="20260713T100000", dtend="20260713T110000",
        extra=("TRANSP:TRANSPARENT",)))
    _seed(svc, "busy", foreign_event_raw(
        "busy", dtstart="20260713T120000", dtend="20260713T130000",
        extra=("TRANSP:OPAQUE",)))
    _seed(svc, "plain", foreign_event_raw(
        "plain", dtstart="20260713T140000", dtend="20260713T150000"))

    got = {e["uid"]: e["busy"] for e in svc.events_in_range(CAL, "2026-07-13", "2026-07-14")}
    assert got == {"free": False, "busy": True, "plain": True}


def test_an_override_may_differ_from_its_series(svc):
    """"The standup is Free that one week" is a thing Apple Calendar can say, so
    the occurrence's own TRANSP wins over the master's — the same per-instance
    fallback `status`, `summary` and `location` already get."""
    raw = foreign_event_raw(
        "daily", "Standup",
        dtstart="20260713T090000", dtend="20260713T091500",
        rrule="FREQ=DAILY;COUNT=3",
        overrides=(("RECURRENCE-ID:20260714T090000",
                    "DTSTART:20260714T090000", "DTEND:20260714T091500",
                    "TRANSP:TRANSPARENT"),),
    )
    _seed(svc, "daily", raw)

    by_day = {
        e["start"][:10]: e["busy"]
        for e in svc.events_in_range(CAL, "2026-07-13", "2026-07-16")
        if e["start"]
    }
    assert by_day["2026-07-13"] is True          # the master's, inherited
    assert by_day["2026-07-14"] is False         # the override's own
    assert by_day["2026-07-15"] is True


# ── what it is for: the booking page ────────────────────────────────────────

def test_busy_intervals_skips_an_event_marked_free():
    base = {"start": "2026-07-13T10:00:00", "end": "2026-07-13T11:00:00",
            "duration": None, "status": None, "start_is_date": False, "all_day": False}
    assert scheduling.busy_intervals([{**base, "busy": False}], TZ) == []
    assert len(scheduling.busy_intervals([{**base, "busy": True}], TZ)) == 1


def test_a_dict_with_no_busy_key_still_blocks():
    """`is False`, not falsy and not `.get("busy", True)`.

    Every DTO carries the key, so arriving without one means some other caller
    built the dict — and reading a missing key as free would make all of their
    events silently bookable over. Every in-tree caller of `busy_intervals`
    predating this field is in exactly that position."""
    ev = {"start": "2026-07-13T10:00:00", "end": "2026-07-13T11:00:00",
          "duration": None, "status": None, "start_is_date": False, "all_day": False}
    assert len(scheduling.busy_intervals([ev], TZ)) == 1


def test_a_free_event_does_not_block_a_booking_slot(svc):
    """The whole point, end to end: a raw VEVENT another client marked Free,
    through the cache, the DTO and the busy set, to a slot the page offers."""
    token = svc.create_booking_link({
        "title": "Chat", "description": None, "calendar_href": CAL,
        "duration_minutes": 60, "timezone": "America/Chicago",
        "availability": {"0": ["09:00-17:00"]}, "show_busy": True,
        "buffer_minutes": 0, "min_notice_hours": 0, "horizon_days": 1, "enabled": True,
    })["token"]

    _seed(svc, "hold", foreign_event_raw(
        "hold", "Tentative hold", dtstart="20260713T100000", dtend="20260713T110000",
        extra=("TRANSP:TRANSPARENT",)))
    _seed(svc, "real", foreign_event_raw(
        "real", "Actual meeting", dtstart="20260713T130000", dtend="20260713T140000"))

    info = svc.public_link_info(token, now=NOW)
    starts = {s["start"] for s in info["slots"]}
    # The hold does not block…
    assert "2026-07-13T10:00:00-05:00" in starts
    # …and the real meeting still does.
    assert "2026-07-13T13:00:00-05:00" not in starts
    # Nor is the hold shown as busy on the public page, which reads the same set.
    assert info["busy"] == [
        {"start": "2026-07-13T13:00:00-05:00", "end": "2026-07-13T14:00:00-05:00"}
    ]


def test_a_free_series_does_not_block_even_when_it_cannot_be_expanded(svc):
    """`_opaque_span_dto` reports an unexpandable series as covering the whole
    window — "assume busy" rather than "assume free". That fallback is about the
    SPAN, not about TRANSP: a series the owner marked Free is one they have said
    does not block, and failing to expand it says nothing about that."""
    raw = foreign_event_raw(
        "broken", "Free series",
        dtstart="20260713T100000", dtend="20260713T110000",
        rrule="FREQ=DAILY;COUNT=3", extra=("TRANSP:TRANSPARENT",),
    )
    _seed(svc, "broken", raw)
    # Force the expansion to fail the way a malformed resource does.
    store.upsert_item(
        svc._conn, CAL, Item(f"{CAL}broken.ics", '"2"', b"not a calendar"),
        extract_from_raw(raw),
    )

    day0 = datetime(2026, 7, 13, tzinfo=TZ)
    window = scheduling.Interval(day0, day0 + timedelta(days=1))
    assert svc._link_busy(TZ, window) == []


def test_an_unmarked_series_that_cannot_be_expanded_still_blocks(svc):
    """The control for the test above: the fallback is intact for everything
    that has not been marked Free."""
    raw = foreign_event_raw(
        "broken", "Opaque series",
        dtstart="20260713T100000", dtend="20260713T110000",
        rrule="FREQ=DAILY;COUNT=3",
    )
    _seed(svc, "broken", raw)
    store.upsert_item(
        svc._conn, CAL, Item(f"{CAL}broken.ics", '"2"', b"not a calendar"),
        extract_from_raw(raw),
    )

    day0 = datetime(2026, 7, 13, tzinfo=TZ)
    window = scheduling.Interval(day0, day0 + timedelta(days=1))
    assert svc._link_busy(TZ, window) != []


# ── the cache column ────────────────────────────────────────────────────────

def test_a_row_written_before_the_column_reads_as_busy(svc):
    """The migration's direction, asserted rather than assumed. A cache written
    by an older build has NULL here, which is the same answer an event with no
    TRANSP gives — so an un-resynced cache blocks exactly what it blocked
    before, and the only rows it is wrong about are ones marked Free, which it
    over-blocks. Over-blocking is the only direction a public booking page may
    be wrong in."""
    _seed(svc, "old", foreign_event_raw(
        "old", dtstart="20260713T100000", dtend="20260713T110000",
        extra=("TRANSP:TRANSPARENT",)))
    # Exactly what the ALTER leaves behind for a row upserted before it existed.
    svc._conn.execute("UPDATE items SET transp = NULL")

    (event,) = svc.events_in_range(CAL, "2026-07-13", "2026-07-14")
    assert event["busy"] is True


# ── the API's tri-state ─────────────────────────────────────────────────────

def test_the_patch_model_leaves_an_unmentioned_transp_alone():
    """`model_fields_set`, not a None check. `busy: false` and "no opinion" are
    both falsy, and telling them apart by value would make Free unsendable."""
    from tasksd.app import EditEvent, _event_edit_from_patch
    from tasksd.ical import UNSET

    assert _event_edit_from_patch(EditEvent(summary="x")).busy is UNSET
    assert _event_edit_from_patch(EditEvent(busy=False)).busy is False
    assert _event_edit_from_patch(EditEvent(busy=True)).busy is True
    # An explicit null removes the property — the one caller of that arm.
    assert _event_edit_from_patch(EditEvent(busy=None)).busy is None


def test_the_create_model_writes_nothing_unless_asked():
    """An omitted `busy` writes no TRANSP at all, which is already OPAQUE — so
    the resources this app has always written are unchanged, and a client that
    has never heard of the field cannot alter one."""
    from tasksd.app import CreateEvent, _event_edit_from_create

    plain = _event_edit_from_create(
        CreateEvent(summary="Chat", start="2026-07-13T09:00:00"))
    assert plain is None

    free = _event_edit_from_create(
        CreateEvent(summary="Hold", start="2026-07-13T09:00:00", busy=False))
    assert free is not None and free.busy is False


# ── the connector's own free-time search ───────────────────────────────────

def test_find_free_time_skips_an_event_marked_free():
    """The model-facing surface draws the same line as the booking page.

    Its all-day divergence stands — an all-day event blocks HERE and not there,
    because "what is my day like" and "what may a stranger book" are different
    questions — but what the owner has explicitly said does not consume time is
    not one of those differences."""
    from tasksd.mcp.api import McpApi

    api = McpApi.__new__(McpApi)                 # no service needed: list_events is stubbed
    meeting = {"start": "2026-09-07T10:00:00", "end": "2026-09-07T12:00:00",
               "all_day": False, "status": "CONFIRMED", "duration": None}

    api.list_events = lambda *a, **k: [meeting | {"busy": True}]
    assert [f["start"] for f in api.find_free_time("2026-09-07", "2026-09-08", minutes=30)] == [
        "2026-09-07T09:00", "2026-09-07T12:00"]

    api.list_events = lambda *a, **k: [meeting | {"busy": False}]
    # Nothing blocks, so the whole working window is one gap.
    assert [f["start"] for f in api.find_free_time("2026-09-07", "2026-09-08", minutes=30)] == [
        "2026-09-07T09:00"]
