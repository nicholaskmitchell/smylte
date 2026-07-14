"""Booking-surface service tests with no Radicale: the public read path
(public_link_info) is pure SQL + slot math, and book_slot's write is stubbed
at the service seam so its validation/replay/timezone behavior is testable
anywhere. HTTP-level coverage lives in test_scheduling.py (radicale-marked).
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from helpers import foreign_event_raw

from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import extract_from_raw
from tasksd.service import TaskService

TZ = ZoneInfo("America/Chicago")
# A Monday morning, link-local (CDT, -05:00).
NOW = datetime(2026, 7, 13, 8, 0, tzinfo=TZ)
CAL_A, CAL_B = "/u/meetings/", "/u/personal/"


def _settings() -> Settings:
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=":memory:", sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


def _seed_event(conn, cal: str, uid: str, start: str, end: str) -> None:
    raw = foreign_event_raw(uid, "Busy", dtstart=start, dtend=end)
    store.upsert_item(conn, cal, Item(f"{cal}{uid}.ics", '"1"', raw), extract_from_raw(raw))


@pytest.fixture
def svc():
    s = TaskService(_settings())
    for href, name in ((CAL_A, "Meetings"), (CAL_B, "Personal")):
        store.upsert_collection(
            s._conn, CollectionInfo(href=href, displayname=name, components={"VEVENT"})
        )
    # Monday 10:00–11:00 on the OTHER calendar; 13:00–14:00 on the link's own.
    _seed_event(s._conn, CAL_B, "other", "20260713T100000", "20260713T110000")
    _seed_event(s._conn, CAL_A, "own", "20260713T130000", "20260713T140000")
    yield s
    s.close()


def _make_link(svc, **over):
    fields = dict(
        title="Chat", description=None, calendar_href=CAL_A, duration_minutes=60,
        timezone="America/Chicago", availability={"0": ["09:00-17:00"]},
        show_busy=True, buffer_minutes=0, min_notice_hours=0, horizon_days=1,
        enabled=True,
    )
    fields.update(over)
    return svc.create_booking_link(fields)["token"]


def test_public_busy_is_scoped_to_the_links_calendar(svc):
    info = svc.public_link_info(_make_link(svc), now=NOW)
    # Displayed busy: the link's own calendar only — the personal calendar's
    # 10:00 block must not leak to anyone holding the URL...
    assert info["busy"] == [
        {"start": "2026-07-13T13:00:00-05:00", "end": "2026-07-13T14:00:00-05:00"}
    ]
    # ...but conflict-checking stays global: no offered slot may overlap EITHER
    # event (10:00 from the other calendar included).
    for blocked in ("2026-07-13T10:00", "2026-07-13T13:00"):
        for s in info["slots"]:
            assert not (s["start"] <= f"{blocked}:00-05:00" < s["end"])
    starts = {s["start"] for s in info["slots"]}
    assert "2026-07-13T09:00:00-05:00" in starts
    assert "2026-07-13T10:00:00-05:00" not in starts


def _stub_create_event(svc):
    captured: dict = {}

    def fake(href, summary, *, dtstart, dtend=None, edit=None, client_id=None):
        captured.update(href=href, dtstart=dtstart, dtend=dtend)
        return {"uid": f"{client_id or 'x'}@tasksd"}

    svc.create_event = fake
    return captured


def test_book_slot_writes_zone_aware_utc(svc):
    token = _make_link(svc)
    captured = _stub_create_event(svc)
    res = svc.book_slot(
        token, start_iso="2026-07-13T09:00:00-05:00", name="N", email="n@x.co", now=NOW
    )
    assert res is not None
    # The VEVENT is written as an absolute UTC instant, not floating local —
    # floating would be re-read relative to whichever link zone parses it next,
    # so links in different zones wouldn't block each other's bookings.
    assert captured["dtstart"] == datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    assert captured["dtend"] == datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc)
    assert captured["dtstart"].tzinfo is timezone.utc


def test_booking_replay_is_scoped_to_its_link(svc):
    t1, t2 = _make_link(svc), _make_link(svc, title="Other link")
    _stub_create_event(svc)
    cid = "a" * 32
    first = svc.book_slot(
        t1, start_iso="2026-07-13T09:00:00-05:00", name="N", email="n@x.co",
        client_id=cid, now=NOW,
    )
    # Same link + same client_id = replay: the original confirmation returns.
    again = svc.book_slot(
        t1, start_iso="2026-07-13T09:00:00-05:00", name="N", email="n@x.co",
        client_id=cid, now=NOW,
    )
    assert again["id"] == first["id"] and again["start"] == first["start"]
    # A different link must not treat it as a replay (nor leak the other
    # booking's confirmation): clean 422-shaped rejection.
    with pytest.raises(ValueError):
        svc.book_slot(
            t2, start_iso="2026-07-13T15:00:00-05:00", name="M", email="m@x.co",
            client_id=cid, now=NOW,
        )
