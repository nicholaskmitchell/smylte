"""Client scheduling (booking links): pure slot-math/store tests that run
anywhere, plus HTTP integration tests against scratch Radicale (skipped when
:5233 is down, like the rest of the API suite)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
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


# ── DST: every emitted slot is exactly `duration` of ABSOLUTE time ──────────
# The previous assertion here was one-sided (`<= timedelta(hours=1)`), which a
# slot whose end instant *precedes* its start satisfies trivially — the exact
# defect it was written to guard. These assert equality, distinctness, and both
# transitions.

def _dst_slots(day: date, duration_minutes: int, window: str = "00:00-05:00"):
    av = scheduling.parse_availability({str(day.weekday()): [window]})
    return scheduling.generate_slots(
        availability=av, duration_minutes=duration_minutes, busy=[], buffer_minutes=0,
        tz=TZ, now=datetime(day.year, day.month, day.day, tzinfo=TZ) - timedelta(days=1),
        min_notice_hours=0, horizon_days=2, only_day=day,
    )


@pytest.mark.parametrize("label, day", [
    ("spring-forward", date(2026, 3, 8)),      # clocks jump 02:00 -> 03:00
    ("fall-back", date(2026, 11, 1)),          # clocks repeat 01:00 -> 02:00
    ("ordinary day", date(2026, 3, 15)),
])
@pytest.mark.parametrize("duration", [30, 60])
def test_dst_slots_are_exactly_the_advertised_length(label, day, duration):
    slots = _dst_slots(day, duration)
    assert slots, f"{label} produced no slots at all"
    for s in slots:
        actual = s.end.astimezone(UTC) - s.start.astimezone(UTC)
        assert actual == timedelta(minutes=duration), (
            f"{label}: {s.start.isoformat()} -> {s.end.isoformat()} is {actual}"
        )


@pytest.mark.parametrize("label, day", [
    ("spring-forward", date(2026, 3, 8)),
    ("fall-back", date(2026, 11, 1)),
])
def test_dst_slots_name_distinct_instants(label, day):
    # Spring-forward used to emit 08:00Z and 08:30Z twice each: two buttons at
    # the same clock time, one of which could never be booked.
    slots = _dst_slots(day, 30)
    starts = [s.start.astimezone(UTC) for s in slots]
    assert len(set(starts)) == len(starts), f"{label}: duplicate slot instants"


def test_fall_back_offers_the_repeated_hour():
    # 01:00-02:00 local happens twice; both passes are real bookable time and
    # wall-clock stepping skipped the second entirely.
    starts = {s.start.astimezone(UTC).isoformat() for s in _dst_slots(date(2026, 11, 1), 30)}
    assert "2026-11-01T07:00:00+00:00" in starts
    assert "2026-11-01T07:30:00+00:00" in starts


def test_dst_day_lengths_differ_by_the_transition():
    # A 25-hour day offers two more 30-minute slots than a 23-hour one, over the
    # same local window — the arithmetic check behind the cases above.
    spring = len(_dst_slots(date(2026, 3, 8), 30, "00:00-23:30"))
    fall = len(_dst_slots(date(2026, 11, 1), 30, "00:00-23:30"))
    assert fall - spring == 4


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
    other = _cal(client)          # conflict-checking is global; disclosure is not
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
    # The other calendar's event still blocks the slot (global conflict check)…
    assert taken not in [s["start"] for s in info2["slots"]]
    # …but is NOT disclosed: the public busy list is scoped to the link's own
    # calendar, so the time-shape of every other calendar stays private.
    t0 = datetime.fromisoformat(taken)
    t1 = t0 + timedelta(minutes=30)
    assert not any(datetime.fromisoformat(b["start"]) <= t0
                   and datetime.fromisoformat(b["end"]) >= t1 for b in info2["busy"])

    # An event on the link's OWN calendar does show, redacted to times only.
    own = info2["slots"][0]["start"]
    own_naive = own.replace("+00:00", "")
    r = client.post(f"/api/calendars/{cal['id']}/events", json={
        "summary": "SECRET own-cal", "start": own_naive,
        "end": (datetime.fromisoformat(own_naive) + timedelta(minutes=30)).isoformat(),
    })
    assert r.status_code == 201, r.text
    info3 = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    o0 = datetime.fromisoformat(own)
    o1 = o0 + timedelta(minutes=30)
    assert any(datetime.fromisoformat(b["start"]) <= o0
               and datetime.fromisoformat(b["end"]) >= o1 for b in info3["busy"])
    for b in info3["busy"]:
        assert set(b) == {"start", "end"}                 # redacted: times only
    assert "SECRET" not in str(info2) + str(info3)


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

    # The event landed on the owner's calendar with the client's details,
    # written as an absolute UTC instant (zone-aware, not floating local).
    day = slot["start"][:10]
    events = client.get(f"/api/calendars/{cal['id']}/events?start={day}&end={day}T23:59:59").json()
    match = [e for e in events if e["start"] == slot["start"]]
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


@pytest.mark.radicale
@pytest.mark.parametrize("start", [
    "9999-12-31T00:00:00+00:00",
    "9999-12-30T00:00:00+00:00",
    "0001-01-01T00:00:00+00:00",
    "0001-01-02T00:00:00+00:00",
])
def test_extreme_start_is_422_not_500(client, start):
    """The booking POST is the one write path an unauthenticated caller reaches,
    so it must not 500. These parse cleanly as ISO and only overflow in the tz
    conversion inside book_slot — and OverflowError is not a ValueError, so it
    escaped the handler that catches malformed starts."""
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    r = client.post(f"/api/public/booking/{link['token']}/book", headers=_NO_COOKIE,
                    json={"start": start, "name": "X", "email": "x@example.com"})
    # 422 where the conversion overflows, 409 where it does not and the instant
    # simply is not an open slot. Never a 5xx.
    assert r.status_code in (409, 422), (start, r.status_code, r.text)


@pytest.mark.radicale
def test_link_is_disabled_and_unbookable_once_its_calendar_is_deleted(client):
    """A link outliving its calendar kept advertising every slot as free, and a
    booking attempt failed at the DAV layer as a 502 'try again shortly' — a
    transient-sounding error for a permanent condition, so a booker would retry
    forever."""
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    tok = link["token"]

    before = client.get(f"/api/public/booking/{tok}", headers=_NO_COOKIE)
    assert before.status_code == 200 and before.json()["slots"]

    assert client.delete(f"/api/calendars/{cal['id']}").status_code == 204

    # Public surface: indistinguishable from an unknown or disabled link.
    dead = client.get(f"/api/public/booking/{tok}", headers=_NO_COOKIE)
    ghost = client.get("/api/public/booking/never-existed", headers=_NO_COOKIE)
    assert dead.status_code == ghost.status_code == 404
    assert dead.json() == ghost.json()

    booked = client.post(f"/api/public/booking/{tok}/book", headers=_NO_COOKIE, json={
        "start": before.json()["slots"][0]["start"],
        "name": "Mallory", "email": "m@example.com",
    })
    assert booked.status_code == 404, booked.text   # not a 502

    # Owner side: the link survives, disabled, and says why.
    mine = [x for x in client.get("/api/scheduling/links").json() if x["token"] == tok]
    assert len(mine) == 1
    assert mine[0]["enabled"] is False
    assert mine[0]["calendar_missing"] is True



# ── the per-link ceiling counts bookings, not requests ──────────────────────
# A booking link is meant to be published, so holding the token proves nothing.
# When every request spent the link's budget, anyone who received the link could
# exhaust it and keep every real visitor on a 429 — a denial of service against
# the owner, using only the URL they handed out. At ~1 request a minute, within
# reach of two or three addresses, the link stayed dead indefinitely.

@pytest.fixture
def many_ips(client):
    """A client whose requests each appear to come from a fresh address.

    The per-CLIENT limiter (15/h) would otherwise mask the per-LINK one. Varying
    the source is exactly the attacker's move the per-link cap exists to stop —
    the audit's scenario is two IPs, or two IPv6 /64s from one VPS."""
    from fastapi.testclient import TestClient

    # X-Real-IP is trusted only from a loopback peer (Caddy overwrites it), so
    # present as loopback and vary the header.
    with TestClient(client.app, client=("127.0.0.1", 1)) as c:
        n = 0

        def post(url, **kw):
            nonlocal n
            n += 1
            headers = {**_NO_COOKIE, "X-Real-IP": f"198.51.100.{n % 250}"}
            return c.post(url, headers=headers, **kw)

        yield post


def _book_body(slot, **over):
    body = {"start": slot["start"], "name": "Ada", "email": "ada@example.com",
            "client_id": uuid.uuid4().hex}
    body.update(over)
    return body


@pytest.mark.radicale
@pytest.mark.parametrize("label, bad, expected", [
    ("a start that is not an open slot", {"start": "2020-01-01T09:00:00+00:00"}, 409),
    ("a malformed email", {"email": "not-an-email"}, 422),
    ("a blank name", {"name": "  "}, 422),
])
def test_refused_bookings_do_not_spend_the_links_budget(client, many_ips, label, bad, expected):
    cal = _cal(client)
    link = _mklink(client, cal["id"])
    info = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    url = f"/api/public/booking/{link['token']}/book"

    # Well past the 30-booking ceiling, none of which is a booking.
    for i in range(40):
        r = many_ips(url, json=_book_body(info["slots"][0], **bad))
        assert r.status_code == expected, (label, i, r.status_code, r.text)

    # …and a real visitor can still book.
    r = many_ips(url, json=_book_body(info["slots"][0]))
    assert r.status_code == 201, (label, r.text)


@pytest.mark.radicale
def test_the_per_link_ceiling_still_bounds_real_bookings(client, many_ips):
    """The cap's actual job — bounding junk events written to the owner's
    calendar regardless of source — has to keep working."""
    cal = _cal(client)
    link = _mklink(client, cal["id"], duration_minutes=15)
    info = client.get(f"/api/public/booking/{link['token']}", headers=_NO_COOKIE).json()
    url = f"/api/public/booking/{link['token']}/book"

    codes = []
    for slot in info["slots"][:35]:
        codes.append(many_ips(url, json=_book_body(slot)).status_code)
    assert 429 in codes, "the per-link ceiling never engaged"
    assert codes.count(201) <= 30, codes
