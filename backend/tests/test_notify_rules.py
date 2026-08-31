"""When each notification fires, and when it deliberately does not.

Pure sqlite via the `db` fixture plus a stub service — no Radicale, no network.
The stub is deliberately dumb: every rule reads the service through a handful of
methods, and the point of these tests is the PREDICATE, not the query behind it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tasksd.db import store
from tasksd.notify import rules as R
from tasksd.notify.scheduler import MAX_LOUD_PER_DAY, Notifier

NY = ZoneInfo("America/New_York")


class StubSvc:
    """The five reads the rules make, and the ledger borrow."""

    def __init__(self, conn, *, settings=None, tz=NY, events=(), tasks=(),
                 bookings=(), health=()):
        self._conn = conn
        self._settings = settings or {}
        self._tz = tz
        self._events = list(events)
        self._tasks = list(tasks)
        self._bookings = list(bookings)
        self._health = list(health)

    def get_settings(self):
        return dict(self._settings)

    def _home_tz(self):
        return self._tz

    def list_calendars(self):
        return [{"href": "/u/cal/"}]

    def events_in_range(self, href, start_iso, end_iso, *, blocking=False):
        return list(self._events)

    def list_lists(self):
        return [{"href": "/u/tasks/"}]

    def list_tasks(self, href, *, include_done=True):
        return list(self._tasks)

    def bookings_created_since(self, stamp):
        return [b for b in self._bookings if (b.get("created_at") or "") >= stamp]

    def sync_health(self):
        return list(self._health)

    def notifications(self, fn, *a, **kw):
        return fn(self._conn, *a, **kw)


class StubSender:
    configured = True

    def __init__(self, ok=True):
        self.sent = []
        self._ok = ok
        # Settable, like the real transport: the token can be edited in Settings
        # and is adopted per sweep rather than per process.
        self.token = "stub-token"


    def send(self, chat_id, text, *, silent=False, **kw):
        self.sent.append({"text": text, "silent": silent, "chat_id": chat_id})
        from tasksd.notify.telegram import SendResult
        return SendResult(self._ok, message_id=1 if self._ok else None,
                          error=None if self._ok else "HTTP 502: Bad Gateway")


class NullLog:
    def warning(self, *a, **kw): pass
    def info(self, *a, **kw): pass


def _sweep(svc, now, **kw):
    tz = svc._home_tz()
    return R.Sweep(svc=svc, now=now, tz=tz,
                   day=now.astimezone(tz).date().isoformat() if tz else now.date().isoformat(),
                   prefs=svc.get_settings(), interval_s=60.0, **kw)


def _event(start, *, summary="Design review", all_day=False, busy=True,
           status=None, uid="evt-1", cal="/u/cal/"):
    return {"uid": uid, "master_uid": uid, "calendar": cal, "summary": summary,
            "start": start, "all_day": all_day, "busy": busy, "status": status,
            "location": None, "start_is_date": all_day}


# ── daily_digest ─────────────────────────────────────────────────────────────

def test_the_digest_fires_at_the_hour_the_owner_set(db):
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"})
    at_730 = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)   # 07:30 in NY
    out = R._eval_digest(_sweep(svc, at_730))
    assert len(out) == 1 and out[0].trigger == "daily_digest"
    assert out[0].dedupe_key == "2026-08-31" and out[0].silent is False


def test_the_digest_does_not_fire_before_its_hour(db):
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"})
    at_729 = datetime(2026, 8, 31, 11, 29, tzinfo=timezone.utc)
    assert R._eval_digest(_sweep(svc, at_729)) == []


def test_a_digest_more_than_four_hours_late_is_skipped_not_sent(db):
    # The day is half over; it would be describing a morning that already
    # happened. Skip the day rather than send it.
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"})
    late = datetime(2026, 8, 31, 15, 31, tzinfo=timezone.utc)     # 11:31 NY
    assert R._eval_digest(_sweep(svc, late)) == []
    just_inside = datetime(2026, 8, 31, 15, 29, tzinfo=timezone.utc)
    assert len(R._eval_digest(_sweep(svc, just_inside))) == 1


def test_the_digest_refuses_to_fire_without_a_home_timezone(db):
    # "07:30" against a UTC server clock is 03:30 in California, and a digest
    # that lands in the middle of the night is how the whole channel gets muted.
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"}, tz=None)
    now = datetime(2026, 8, 31, 7, 30, tzinfo=timezone.utc)
    assert R._eval_digest(_sweep(svc, now)) == []


def test_the_digest_says_an_empty_day_is_empty(db):
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"})
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    text = R._eval_digest(_sweep(svc, now))[0].text
    assert "nothing scheduled" in text


def test_the_digest_counts_events_due_and_overdue(db):
    tasks = [
        {"summary": "Renew passport", "due": "2026-08-31", "due_is_date": True},
        {"summary": "Invoice Kramer", "due": "2026-08-20", "due_is_date": True},
        {"summary": "No deadline", "due": None, "due_is_date": False},
    ]
    svc = StubSvc(db, settings={"notify_digest_time": "07:30", "time_format": "24h"},
                  events=[_event("2026-08-31T14:00:00")], tasks=tasks)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    text = R._eval_digest(_sweep(svc, now))[0].text
    assert "1 event" in text and "1 due" in text and "1 overdue" in text
    assert "14:00  Design review" in text
    assert "· Renew passport" in text
    assert "No deadline" not in text          # undated is not "due today"


def test_the_digest_is_shape_capped_so_it_stays_readable(db):
    events = [_event(f"2026-08-31T{9 + i:02d}:00:00", summary=f"Mtg {i}", uid=f"e{i}")
              for i in range(8)]
    tasks = [{"summary": f"Task {i}", "due": "2026-08-31", "due_is_date": True}
             for i in range(9)]
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"}, events=events, tasks=tasks)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    text = R._eval_digest(_sweep(svc, now))[0].text
    assert "+3 more events" in text and "+4 more due" in text


# ── event_starting ───────────────────────────────────────────────────────────

def test_an_event_inside_the_lead_window_fires(db):
    svc = StubSvc(db, settings={"time_format": "24h"},
                  events=[_event("2026-08-31T10:00:00")])       # floating -> NY
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)    # 09:52 NY, 8 min out
    out = R._eval_event_starting(_sweep(svc, now))
    assert len(out) == 1
    assert "Design review at 10:00 — in 8 min." == out[0].text
    assert out[0].silent is False


def test_an_event_further_out_than_the_lead_does_not_fire(db):
    svc = StubSvc(db, events=[_event("2026-08-31T10:00:00")])
    now = datetime(2026, 8, 31, 13, 40, tzinfo=timezone.utc)    # 20 minutes out
    assert R._eval_event_starting(_sweep(svc, now)) == []


def test_an_event_that_has_already_started_is_never_announced(db):
    # If the box was down and the meeting began, saying so is noise. Nothing is
    # claimed either, so a later restart cannot resurrect it.
    svc = StubSvc(db, events=[_event("2026-08-31T10:00:00")])
    now = datetime(2026, 8, 31, 14, 1, tzinfo=timezone.utc)     # one minute late
    assert R._eval_event_starting(_sweep(svc, now)) == []


@pytest.mark.parametrize("kwargs", [
    {"all_day": True},
    {"busy": False},
    {"status": "CANCELLED"},
])
def test_all_day_free_and_cancelled_events_do_not_interrupt(db, kwargs):
    svc = StubSvc(db, events=[_event("2026-08-31T10:00:00", **kwargs)])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    assert R._eval_event_starting(_sweep(svc, now)) == []


def test_the_dedupe_key_is_the_instant_so_a_moved_meeting_re_arms(db):
    svc = StubSvc(db, events=[_event("2026-08-31T10:00:00")])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    first = R._eval_event_starting(_sweep(svc, now))[0].dedupe_key

    svc._events = [_event("2026-08-31T11:00:00")]               # moved an hour
    later = datetime(2026, 8, 31, 14, 52, tzinfo=timezone.utc)
    second = R._eval_event_starting(_sweep(svc, later))[0].dedupe_key
    assert first != second
    assert first.startswith("/u/cal/|evt-1|")                   # href, not slug


def test_the_lead_is_floored_so_it_cannot_undercut_the_pipeline(db):
    # sync poll (30s) + notify tick (60s) means a 2-minute lead would routinely
    # fire after the meeting had started, and then never fire at all.
    assert R.event_lead({"notify_event_lead_minutes": 1}) == timedelta(minutes=3)
    assert R.event_lead({"notify_event_lead_minutes": 45}) == timedelta(minutes=45)
    assert R.event_lead({"notify_event_lead_minutes": "nonsense"}) == timedelta(minutes=10)


# ── booking_created ──────────────────────────────────────────────────────────

def test_a_new_booking_is_announced_silently(db):
    booking = {"id": "bk1", "client_name": "Nina Bauer", "link_title": "Intro call",
               "start_at": "2026-09-02T14:00:00-04:00",
               "created_at": "2026-08-31T11:00:00.000Z"}
    svc = StubSvc(db, settings={"time_format": "24h"}, bookings=[booking])
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    out = R._eval_booking_created(_sweep(svc, now))
    assert len(out) == 1 and out[0].dedupe_key == "bk1"
    assert out[0].silent is True, "nothing can be done about a 3am booking at 3am"
    assert out[0].text == "Nina Bauer booked Intro call Wed 2 Sep at 14:00."


def test_a_booking_older_than_the_catch_up_window_is_not_announced(db):
    booking = {"id": "old", "client_name": "X", "link_title": "Call",
               "start_at": "2026-09-02T14:00:00-04:00",
               "created_at": "2026-08-29T11:00:00.000Z"}
    svc = StubSvc(db, bookings=[booking])
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    assert R._eval_booking_created(_sweep(svc, now)) == []


def test_a_booking_whose_link_was_deleted_still_announces(db):
    # The ledger has no FK to booking_links precisely so history survives.
    booking = {"id": "bk2", "client_name": "Nina", "link_title": None,
               "start_at": "2026-09-02T14:00:00-04:00",
               "created_at": "2026-08-31T11:00:00.000Z"}
    svc = StubSvc(db, bookings=[booking])
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    assert "booked time" in R._eval_booking_created(_sweep(svc, now))[0].text


# ── sync_stalled ─────────────────────────────────────────────────────────────

def test_a_standing_error_with_a_stale_last_sync_fires(db):
    health = [{"collection_href": "/u/cal/", "name": "Calendar",
               "last_error": "502 from Radicale",
               "last_sync_at": "2026-08-31T09:00:00.000Z"}]
    svc = StubSvc(db, health=health)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    out = R._eval_sync_stalled(_sweep(svc, now))
    assert len(out) == 1 and out[0].silent is True
    assert "Calendar" in out[0].text


def test_a_fresh_error_is_a_blip_and_does_not_fire(db):
    health = [{"collection_href": "/u/cal/", "name": "Calendar",
               "last_error": "502", "last_sync_at": "2026-08-31T11:20:00.000Z"}]
    svc = StubSvc(db, health=health)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    assert R._eval_sync_stalled(_sweep(svc, now)) == []


def test_the_sync_message_never_carries_the_error_text(db):
    # It comes from the DAV layer, it is unbounded, and the transport is a
    # postcard through two systems. Point at it; do not move it.
    secret = "https://user:hunter2@radicale.example.com/dav/"
    health = [{"collection_href": "/u/cal/", "name": "Calendar",
               "last_error": f"401 from {secret}", "last_sync_at": None}]
    svc = StubSvc(db, health=health)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    text = R._eval_sync_stalled(_sweep(svc, now))[0].text
    assert "hunter2" not in text and secret not in text
    assert "tasksd log" in text


def test_every_broken_collection_is_one_message_not_five(db):
    # Radicale being down means every collection fails at once, and five
    # identical messages is how a useful alert becomes a muted one.
    health = [{"collection_href": f"/u/c{i}/", "name": f"List {i}",
               "last_error": "down", "last_sync_at": None} for i in range(5)]
    svc = StubSvc(db, health=health)
    now = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)
    out = R._eval_sync_stalled(_sweep(svc, now))
    assert len(out) == 1 and out[0].dedupe_key == "2026-08-31"


# ── the trigger registry ─────────────────────────────────────────────────────

def test_an_absent_preference_means_the_rules_own_default(db):
    rule = R.RULES[0]
    assert R.trigger_enabled({}, rule) is rule.default_on
    assert R.trigger_enabled({"notify_triggers": {}}, rule) is rule.default_on
    assert R.trigger_enabled({"notify_triggers": {rule.id: False}}, rule) is False
    # A junk value is not a toggle.
    assert R.trigger_enabled({"notify_triggers": {rule.id: "yes"}}, rule) is rule.default_on
    assert R.trigger_enabled({"notify_triggers": "broken"}, rule) is rule.default_on


def test_the_registry_and_the_trigger_names_stay_in_step():
    assert tuple(r.id for r in R.RULES) == R.TRIGGERS
    assert len(set(R.TRIGGERS)) == len(R.TRIGGERS)


def test_loud_and_quiet_are_fixed_in_code():
    urgency = {r.id: r.silent for r in R.RULES}
    assert urgency == {"daily_digest": False, "event_starting": False,
                       "item_reminder": False, "booking_created": True,
                       "sync_stalled": True}


# ── item_reminder ────────────────────────────────────────────────────────────
#
# The rule that lets a task deadline earn a notification at all: not because the
# app decided a deadline is worth an interruption, but because the owner set a
# lead on that one item by hand.

def _task(summary="Renew passport", due="2026-08-31T10:00:00", *, is_date=False,
          notify=None, uid="t1", rrule=False):
    return {"uid": uid, "summary": summary, "due": due, "due_is_date": is_date,
            "notify_minutes_before": notify, "has_rrule": rrule}


def test_a_task_with_a_lead_fires_and_one_without_never_does(db):
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)   # 09:52 NY
    svc = StubSvc(db, settings={"time_format": "24h"},
                  tasks=[_task(notify=10), _task(summary="Silent one", uid="t2")])
    out = R._eval_item_reminder(_sweep(svc, now))
    assert len(out) == 1
    assert out[0].text == "Renew passport due 10:00 — in 8 min."
    assert out[0].trigger == "item_reminder" and out[0].silent is False


def test_a_task_outside_its_own_lead_does_not_fire(db):
    svc = StubSvc(db, tasks=[_task(notify=10)])
    early = datetime(2026, 8, 31, 13, 40, tzinfo=timezone.utc)   # 20 min out
    assert R._eval_item_reminder(_sweep(svc, early)) == []
    late = datetime(2026, 8, 31, 14, 1, tzinfo=timezone.utc)     # already due
    assert R._eval_item_reminder(_sweep(svc, late)) == []


def test_a_recurring_task_is_skipped_because_its_due_is_a_stale_master(db):
    # Nothing in this codebase expands a VTODO recurrence set, so items.due is
    # the master's deadline — reminding off it fires once on a date that stopped
    # being true months ago, and never again.
    svc = StubSvc(db, tasks=[_task(notify=10, rrule=True)])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    assert R._eval_item_reminder(_sweep(svc, now)) == []


def test_an_all_day_deadline_names_the_day_not_a_midnight_clock(db):
    # "due at 12:00 AM" is a time nobody set — it is midnight only because a
    # date has to resolve to something.
    svc = StubSvc(db, tasks=[_task(due="2026-09-01", is_date=True, notify=60)])
    now = datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc)      # 23:30 NY, 30m out
    out = R._eval_item_reminder(_sweep(svc, now))
    assert len(out) == 1 and "due Tue 1 Sep" in out[0].text
    assert "12:00" not in out[0].text


def test_an_event_with_its_own_lead_fires_from_the_reminder_rule(db):
    ev = _event("2026-08-31T10:00:00")
    ev["notify_minutes_before"] = 30
    svc = StubSvc(db, settings={"time_format": "24h"}, events=[ev])
    now = datetime(2026, 8, 31, 13, 35, tzinfo=timezone.utc)     # 25 min out
    out = R._eval_item_reminder(_sweep(svc, now))
    assert len(out) == 1 and out[0].text == "Design review at 10:00 — in 25 min."


def test_the_blanket_rule_yields_to_an_explicit_lead(db):
    # Otherwise the same meeting is announced twice, at two different times.
    ev = _event("2026-08-31T10:00:00")
    ev["notify_minutes_before"] = 30
    svc = StubSvc(db, events=[ev])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)     # inside BOTH windows
    assert R._eval_event_starting(_sweep(svc, now)) == []
    assert len(R._eval_item_reminder(_sweep(svc, now))) == 1


def test_a_lead_of_zero_means_tell_me_exactly_when_it_is_due(db):
    # 0 is a real answer, which is why the clear sentinel is -1 and not falsiness.
    svc = StubSvc(db, tasks=[_task(notify=0)])
    at_due = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    out = R._eval_item_reminder(_sweep(svc, at_due))
    assert len(out) == 1 and "in 0 min" in out[0].text


@pytest.mark.parametrize("junk", [None, True, False, -1, -5, 999_999, "10", 10.5])
def test_a_lead_that_is_not_a_usable_number_is_no_reminder(db, junk):
    svc = StubSvc(db, tasks=[_task(notify=junk)])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    assert R._eval_item_reminder(_sweep(svc, now)) == []


def test_the_dedupe_key_is_the_moment_so_rescheduling_re_arms(db):
    svc = StubSvc(db, tasks=[_task(notify=10)])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    first = R._eval_item_reminder(_sweep(svc, now))[0].dedupe_key

    svc._tasks = [_task(due="2026-08-31T11:00:00", notify=10)]
    later = datetime(2026, 8, 31, 14, 52, tzinfo=timezone.utc)
    assert R._eval_item_reminder(_sweep(svc, later))[0].dedupe_key != first


def test_changing_only_the_lead_does_not_re_send_a_reminder_already_out(db):
    # The key names the MOMENT, not the lead — so editing "30 minutes" to "45"
    # on an item whose reminder already went out is not a second occasion.
    svc = StubSvc(db, tasks=[_task(notify=10)])
    now = datetime(2026, 8, 31, 13, 52, tzinfo=timezone.utc)
    first = R._eval_item_reminder(_sweep(svc, now))[0].dedupe_key
    svc._tasks = [_task(notify=15)]
    assert R._eval_item_reminder(_sweep(svc, now))[0].dedupe_key == first
