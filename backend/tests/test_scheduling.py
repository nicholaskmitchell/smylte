"""Client scheduling (booking links): pure slot-math/store tests that run
anywhere, plus HTTP integration tests against scratch Radicale (skipped when
:5233 is down, like the rest of the API suite)."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tasksd import scheduling
from tasksd.auth import RateLimiter
from tasksd.db import store
from tasksd.scheduling import Interval

TZ = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")

# A Monday morning, link-local.
NOW = datetime(2026, 7, 13, 8, 0, tzinfo=TZ)


def _slots(**kw):
    defaults = dict(
        availability=scheduling.parse_availability({"0": ["09:00-12:00"]}),
        duration_minutes=30, busy=[], buffer_minutes=0, tz=TZ, now=NOW,
        min_notice_hours=0, horizon_days=0,
    )
    defaults.update(kw)
    return scheduling.generate_slots(**defaults)


def _iv(start_h, start_m, end_h, end_m, day=13):
    return Interval(datetime(2026, 7, day, start_h, start_m, tzinfo=TZ),
                    datetime(2026, 7, day, end_h, end_m, tzinfo=TZ))


# ── availability parsing ─────────────────────────────────────────────────────

def test_parse_availability_shapes():
    av = scheduling.parse_availability({"0": ["09:00-12:00", "13:00-17:00"], "4": []})
    assert av == {0: [(time(9), time(12)), (time(13), time(17))]}
    assert scheduling.parse_availability(None) == {}
    assert scheduling.parse_availability("{}") == {}
    # JSON string form (as stored)
    assert scheduling.parse_availability('{"6": ["10:00-11:00"]}') == {6: [(time(10), time(11))]}


@pytest.mark.parametrize("bad", [
    "not json",
    '["09:00-12:00"]',                       # not an object
    {"7": ["09:00-12:00"]},                  # weekday out of range
    {"monday": ["09:00-12:00"]},             # non-numeric key
    {"0": "09:00-12:00"},                    # ranges not a list
    {"0": ["9:00-12:00"]},                   # missing zero-pad
    {"0": ["09:00–12:00"]},                  # en-dash
    {"0": ["12:00-09:00"]},                  # inverted
    {"0": ["09:00-09:00"]},                  # empty range
    {"0": ["25:00-26:00"]},                  # invalid time
    {"0": ["09:00-12:00", "11:00-13:00"]},   # overlap within a day
])
def test_parse_availability_rejects(bad):
    with pytest.raises(ValueError):
        scheduling.parse_availability(bad)


# ── busy interval extraction ─────────────────────────────────────────────────

def _ev(**kw):
    base = {"start": None, "end": None, "duration": None, "status": None,
            "start_is_date": False, "all_day": False}
    base.update(kw)
    return base


def test_busy_intervals_naive_and_aware():
    naive = _ev(start="2026-07-13T10:00:00", end="2026-07-13T11:00:00")
    # 15:30Z == 10:30 in America/Chicago (CDT, UTC-5)
    aware = _ev(start="2026-07-13T15:30:00+00:00", end="2026-07-13T16:30:00+00:00")
    busy = scheduling.busy_intervals([naive, aware], TZ)
    # The two overlap once normalized into link tz → merged into one block.
    assert busy == [_iv(10, 0, 11, 30)]


def test_busy_intervals_skips_nonblocking():
    events = [
        _ev(start="2026-07-13", start_is_date=True, all_day=True),        # all-day
        _ev(start="2026-07-13T10:00:00", end="2026-07-13T11:00:00", status="CANCELLED"),
        _ev(start=None),                                                  # no start
        _ev(start="2026-07-13T10:00:00"),                                 # zero-length
        _ev(start="garbage", end="2026-07-13T11:00:00"),                  # malformed
    ]
    assert scheduling.busy_intervals(events, TZ) == []


def test_busy_intervals_duration_fallback():
    ev = _ev(start="2026-07-13T10:00:00", duration="PT1H")
    assert scheduling.busy_intervals([ev], TZ) == [_iv(10, 0, 11, 0)]


def test_busy_intervals_duration_from_real_ics():
    # Regression: a DURATION-only VEVENT (DAVx5/phone-client style) must block,
    # end-to-end through the same extraction the cache uses. str() of the parsed
    # property used to store a repr that busy_intervals silently skipped.
    from tasksd.ical import extract_from_raw

    f = extract_from_raw(
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:dur-1\r\nDTSTART:20260713T100000\r\n"
        b"DURATION:PT1H30M\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert f.duration == "PT1H30M"
    ev = _ev(start=f.dtstart, duration=f.duration, status=f.status,
             start_is_date=f.dtstart_is_date, all_day=f.dtstart_is_date)
    assert scheduling.busy_intervals([ev], TZ) == [_iv(10, 0, 11, 30)]


def test_merge_and_pad():
    ivs = [_iv(10, 0, 11, 0), _iv(10, 30, 11, 30), _iv(13, 0, 14, 0)]
    assert scheduling.merge(ivs) == [_iv(10, 0, 11, 30), _iv(13, 0, 14, 0)]
    # 60-minute pad bridges the 11:30→13:00 gap into one block.
    assert scheduling.pad(ivs, 60) == [_iv(9, 0, 15, 0)]


# ── slot generation ──────────────────────────────────────────────────────────

def test_slots_step_from_window_start():
    starts = [s.start for s in _slots()]
    assert starts == [datetime(2026, 7, 13, h, m, tzinfo=TZ)
                      for h, m in [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (11, 30)]]


def test_slots_anchor_survives_mid_window_busy():
    # A 10:15–10:45 busy block kills 10:00 and 10:30 but must NOT shift the
    # 11:00/11:30 slots off the half-hour grid.
    slots = _slots(busy=[_iv(10, 15, 10, 45)])
    starts = [(s.start.hour, s.start.minute) for s in slots]
    assert starts == [(9, 0), (9, 30), (11, 0), (11, 30)]


def test_slot_must_fit_window():
    # 09:00-10:00 window, 45-minute meetings: only 09:00 fits entirely.
    slots = _slots(availability=scheduling.parse_availability({"0": ["09:00-10:00"]}),
                   duration_minutes=45)
    assert [(s.start.hour, s.start.minute) for s in slots] == [(9, 0)]


def test_min_notice_trims_today():
    slots = _slots(min_notice_hours=2)     # now is 08:00 → nothing before 10:00
    assert [(s.start.hour, s.start.minute) for s in slots] == [(10, 0), (10, 30), (11, 0), (11, 30)]


def test_horizon_bounds_days():
    slots = _slots(horizon_days=7)         # two Mondays in range
    days = {s.start.date() for s in slots}
    assert days == {NOW.date(), NOW.date() + timedelta(days=7)}
    assert len(_slots(horizon_days=6)) == 6   # second Monday out of range


def test_buffer_widens_exclusion():
    # Busy 10:00-10:30; a 15-min buffer also kills the 09:30 and 10:30 slots.
    assert [(s.start.hour, s.start.minute) for s in _slots(busy=[_iv(10, 0, 10, 30)])] == \
        [(9, 0), (9, 30), (10, 30), (11, 0), (11, 30)]
    assert [(s.start.hour, s.start.minute)
            for s in _slots(busy=[_iv(10, 0, 10, 30)], buffer_minutes=15)] == \
        [(9, 0), (11, 0), (11, 30)]


def test_only_day_restricts_but_keeps_rules():
    monday_next = NOW.date() + timedelta(days=7)
    slots = _slots(horizon_days=7, only_day=monday_next)
    assert {s.start.date() for s in slots} == {monday_next}
    # only_day outside the horizon yields nothing.
    assert _slots(horizon_days=6, only_day=monday_next) == []


def test_dst_spring_forward_is_sane():
    # US DST 2026: clocks jump 02:00→03:00 on Sunday March 8. A window over the
    # gap must not crash; slots stay within the (shrunken) real window.
    av = scheduling.parse_availability({"6": ["01:00-04:00"]})
    now = datetime(2026, 3, 8, 0, 0, tzinfo=TZ)
    slots = scheduling.generate_slots(availability=av, duration_minutes=60, busy=[],
                                      buffer_minutes=0, tz=TZ, now=now,
                                      min_notice_hours=0, horizon_days=0)
    assert slots, "spring-forward day produced no slots at all"
    for s in slots:
        assert s.end.astimezone(UTC) - s.start.astimezone(UTC) <= timedelta(hours=1)


def test_empty_availability_no_slots():
    assert _slots(availability={}) == []


def test_max_slots_cap():
    av = scheduling.parse_availability({str(d): ["00:00-23:00"] for d in range(7)})
    slots = _slots(availability=av, duration_minutes=5, horizon_days=180, max_slots=50)
    assert len(slots) == 50


# ── redaction ────────────────────────────────────────────────────────────────

def test_clip_redacts_to_window():
    window = Interval(datetime(2026, 7, 13, 9, 0, tzinfo=TZ),
                      datetime(2026, 7, 13, 17, 0, tzinfo=TZ))
    busy = [_iv(8, 0, 10, 0), _iv(9, 30, 11, 0), _iv(18, 0, 19, 0)]
    assert scheduling.clip(busy, window) == [_iv(9, 0, 11, 0)]


# ── store CRUD (pure sqlite; `db` fixture from conftest) ─────────────────────

def _link_fields(cal="/u/cal1/", **kw):
    fields = dict(title="Intro call", calendar_href=cal, duration_minutes=30,
                  timezone="UTC", availability='{"0": ["09:00-17:00"]}')
    fields.update(kw)
    return fields


def test_store_link_crud(db):
    row = store.create_booking_link(db, "tok1", _link_fields())
    assert row["title"] == "Intro call" and row["enabled"] == 1
    assert store.get_booking_link(db, "nope") is None

    updated = store.update_booking_link(db, "tok1", {"enabled": 0, "duration_minutes": 45})
    assert updated["enabled"] == 0 and updated["duration_minutes"] == 45
    assert store.update_booking_link(db, "nope", {"enabled": 1}) is None

    with pytest.raises(ValueError):
        store.update_booking_link(db, "tok1", {"token": "hijack"})
    with pytest.raises(ValueError):
        store.create_booking_link(db, "tok2", _link_fields(bogus=1))

    assert store.delete_booking_link(db, "tok1") is True
    assert store.delete_booking_link(db, "tok1") is False


def test_store_bookings(db):
    store.create_booking_link(db, "tok1", _link_fields())
    store.insert_booking(db, id="b1", link_token="tok1", calendar_href="/u/cal1/",
                         event_uid="e1@tasksd", client_name="Ada", client_email="ada@example.com",
                         notes=None, start_at="2026-07-13T10:00:00+00:00",
                         end_at="2026-07-13T10:30:00+00:00")
    store.insert_booking(db, id="b2", link_token="other", calendar_href="/u/cal1/",
                         event_uid="e2@tasksd", client_name="Bob", client_email="bob@example.com",
                         notes="hi", start_at="2026-07-14T10:00:00+00:00",
                         end_at="2026-07-14T10:30:00+00:00")
    assert [r["id"] for r in store.list_bookings(db)] == ["b1", "b2"]
    assert [r["id"] for r in store.list_bookings(db, "tok1")] == ["b1"]
    assert [r["id"] for r in store.list_bookings(db, after="2026-07-14")] == ["b2"]
    assert store.get_booking_by_event(db, "e2@tasksd")["id"] == "b2"
    # Ledger survives link deletion.
    store.delete_booking_link(db, "tok1")
    assert store.bookings_count_by_link(db) == {"tok1": 1, "other": 1}


def test_rate_limiter_locks_out():
    rl = RateLimiter(max_fails=2, window_s=60, lockout_s=60)
    assert rl.allowed("ip")
    rl.record_failure("ip")
    assert rl.allowed("ip")
    rl.record_failure("ip")
    assert not rl.allowed("ip")
    assert rl.retry_after("ip") > 0


def test_rate_limiter_evicts_stale_keys():
    # Keys are client-supplied (per-IP); the limiter must not retain an entry
    # per key forever, or rotating source IPs would exhaust memory.
    import time as _t

    rl = RateLimiter(max_fails=5, window_s=100, lockout_s=100)
    for i in range(1000):
        rl.record_failure(f"ip-{i}")          # one failure each — none lock out
    assert len(rl._fails) == 1000
    # A sweep well past the window drops every stale, unlocked key.
    rl._sweep(_t.monotonic() + 10_000)
    assert rl._fails == {} and rl._locked == {}


def test_rate_limiter_keeps_locked_keys_through_sweep():
    import time as _t

    rl = RateLimiter(max_fails=2, window_s=100, lockout_s=10_000)
    rl.record_failure("ip")
    rl.record_failure("ip")                    # -> locked out
    # Past the fail window but inside the lockout: the key must survive the sweep.
    rl._sweep(_t.monotonic() + 500)
    assert not rl.allowed("ip")


# ── HTTP integration (scratch Radicale; session-scoped `client` fixture) ─────

pytestmark_http = pytest.mark.radicale


def _cal(client) -> dict:
    r = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def _mklink(client, cal_id, **kw) -> dict:
    body = {
        "title": "Coffee chat", "calendar": cal_id, "duration_minutes": 30,
        "timezone": "UTC",
        "availability": {str(d): ["09:00-17:00"] for d in range(7)},
        "min_notice_hours": 0, "horizon_days": 3,
    }
    body.update(kw)
    r = client.post("/api/scheduling/links", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# Requests with the session cookie stripped — proves the public endpoints
# genuinely require no auth.
_NO_COOKIE = {"Cookie": ""}


@pytest.mark.radicale
def test_owner_link_crud(client):
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    assert link["token"] and link["calendar"] == cal["id"]
    assert link["calendar_name"] == cal["name"]
    assert link["availability"]["0"] == ["09:00-17:00"]

    tokens = {l["token"] for l in client.get("/api/scheduling/links").json()}
    assert link["token"] in tokens

    patched = client.patch(f"/api/scheduling/links/{link['token']}",
                           json={"duration_minutes": 60, "show_busy": True}).json()
    assert patched["duration_minutes"] == 60 and patched["show_busy"] is True

    # validation → 422
    assert client.post("/api/scheduling/links", json={
        "title": "x", "calendar": cal["id"], "timezone": "Mars/Olympus",
    }).status_code == 422
    assert client.patch(f"/api/scheduling/links/{link['token']}",
                        json={"availability": {"0": ["12:00-09:00"]}}).status_code == 422
    # a task list is not a valid target calendar
    lst = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()
    assert client.post("/api/scheduling/links", json={
        "title": "x", "calendar": lst["id"], "timezone": "UTC",
    }).status_code == 422

    assert client.delete(f"/api/scheduling/links/{link['token']}").status_code == 204
    assert client.delete(f"/api/scheduling/links/{link['token']}").status_code == 404


@pytest.mark.radicale
def test_public_page_requires_no_auth_and_leaks_nothing(client):
    cal = _cal(client)
    link = _mklink(client, cal["id"])

    # Owner endpoints stay locked without the cookie…
    assert client.get("/api/scheduling/links", headers=_NO_COOKIE).status_code == 401
    # …but the public page works.
    r = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE)
    assert r.status_code == 200
    info = r.json()
    assert info["title"] == "Coffee chat" and info["duration_minutes"] == 30
    assert len(info["slots"]) > 0
    assert "+00:00" in info["slots"][0]["start"]          # offset on the wire
    assert "busy" not in info                             # show_busy defaults off
    # No hrefs, calendar names, or event details in the payload.
    assert set(info) <= {"token", "title", "description", "duration_minutes",
                         "timezone", "slots"}

    assert client.get("/api/public/booking/no-such-token",
                      headers=_NO_COOKIE).status_code == 404


@pytest.mark.radicale
def test_busy_event_blocks_slot_and_redacts(client):
    cal = _cal(client)
    other = _cal(client)          # busy comes from ALL calendars, not just the target
    link = _mklink(client, cal["id"], show_busy=True)

    info = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    taken = info["slots"][0]["start"]
    naive = taken.replace("+00:00", "")
    ev = client.post(f"/api/calendars/{other['id']}/events", json={
        "summary": "SECRET dentist", "start": naive,
        "end": (datetime.fromisoformat(naive) + timedelta(minutes=30)).isoformat(),
    })
    assert ev.status_code == 201, ev.text

    info2 = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    assert taken not in [s["start"] for s in info2["slots"]]
    # Redaction merges adjacent blocks (events from other suite tests share the
    # session app), so assert coverage of the event, not exact bounds.
    t0 = datetime.fromisoformat(taken)
    t1 = t0 + timedelta(minutes=30)
    assert any(datetime.fromisoformat(b["start"]) <= t0
               and datetime.fromisoformat(b["end"]) >= t1 for b in info2["busy"])
    for b in info2["busy"]:
        assert set(b) == {"start", "end"}                 # redacted: times only
    assert "SECRET" not in str(info2)


@pytest.mark.radicale
def test_book_flow_conflict_and_replay(client):
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    info = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    slot = info["slots"][0]

    cid = uuid.uuid4().hex
    r = client.post(f"/api/public/booking/{link['token']}/book", headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "Ada Lovelace", "email": "ada@example.com",
        "notes": "bring diagrams", "client_id": cid,
    })
    assert r.status_code == 201, r.text
    booked = r.json()
    assert booked["start"] == slot["start"] and booked["title"] == "Coffee chat"

    # The event landed on the owner's calendar with the client's details.
    naive = slot["start"].replace("+00:00", "")
    day = naive[:10]
    events = client.get(f"/api/calendars/{cal['id']}/events?start={day}&end={day}T23:59:59").json()
    match = [e for e in events if e["start"] == naive]
    assert match and match[0]["summary"] == "Coffee chat — Ada Lovelace"
    assert "ada@example.com" in match[0]["description"]
    assert "bring diagrams" in match[0]["description"]

    # Owner sees the booking in the ledger.
    bookings = client.get("/api/scheduling/bookings").json()
    assert any(b["email"] == "ada@example.com" and b["link"] == link["token"]
               for b in bookings)

    # Same client_id replay → the original confirmation, not a 409.
    replay = client.post(f"/api/public/booking/{link['token']}/book", headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "Ada Lovelace", "email": "ada@example.com",
        "client_id": cid,
    })
    assert replay.status_code == 201 and replay.json()["id"] == booked["id"]

    # A different client wanting the same slot → 409.
    r2 = client.post(f"/api/public/booking/{link['token']}/book", headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "Eve", "email": "eve@example.com",
    })
    assert r2.status_code == 409

    # The slot no longer shows on the page.
    info2 = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    assert slot["start"] not in [s["start"] for s in info2["slots"]]


@pytest.mark.radicale
def test_book_validation(client):
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    info = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    slot = info["slots"][0]
    url = f"/api/public/booking/{link['token']}/book"

    # off-grid / outside availability → 409 (not available), not a server error
    off = (datetime.fromisoformat(slot["start"]) + timedelta(minutes=7)).isoformat()
    assert client.post(url, headers=_NO_COOKIE, json={
        "start": off, "name": "X", "email": "x@example.com"}).status_code == 409
    # naive start → 422
    assert client.post(url, headers=_NO_COOKIE, json={
        "start": slot["start"].replace("+00:00", ""), "name": "X",
        "email": "x@example.com"}).status_code == 422
    # bad email / blank name → 422
    assert client.post(url, headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "X", "email": "not-an-email"}).status_code == 422
    assert client.post(url, headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "   ", "email": "x@example.com"}).status_code == 422
    # unknown token → 404
    assert client.post("/api/public/booking/nope/book", headers=_NO_COOKIE, json={
        "start": slot["start"], "name": "X", "email": "x@example.com"}).status_code == 404


@pytest.mark.radicale
def test_disabled_link_is_indistinguishable_404(client):
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    client.patch(f"/api/scheduling/links/{link['token']}", json={"enabled": False})

    dead = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE)
    ghost = client.get("/api/public/booking/never-existed", headers=_NO_COOKIE)
    assert dead.status_code == ghost.status_code == 404
    assert dead.json() == ghost.json()

    assert client.post(f"/api/public/booking/{link['token']}/book", headers=_NO_COOKIE, json={
        "start": "2026-07-14T09:00:00+00:00", "name": "X", "email": "x@example.com",
    }).status_code == 404
