"""The sweep: claiming, the daily ceiling, batching, and what a failure does.

Reuses the stubs from test_notify_rules — the point here is the dispatcher, not
the predicates.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tasksd.db import store
from tasksd.notify import rules as R
from tasksd.notify.scheduler import MAX_LOUD_PER_DAY, Notifier

from tests.test_notify_rules import NY, NullLog, StubSender, StubSvc, _event

MORNING = datetime(2026, 8, 31, 11, 30, tzinfo=timezone.utc)   # 07:30 in NY


def _notifier(svc, sender=None):
    # "555" and the token stand in for the environment fallbacks; the account's
    # own settings win over both when it sets them.
    return Notifier(svc, sender or StubSender(), "555", log=NullLog(), token="env-token")


# The master switch is an ACCOUNT setting now and absent means off, so every
# stub that expects a send has to say it is on.
ON = {"notifications_enabled": True}


def _digest_svc(db, **kw):
    kw.setdefault("settings", {**ON, "notify_digest_time": "07:30"})
    return StubSvc(db, **kw)


# ── claiming ─────────────────────────────────────────────────────────────────

def test_a_sweep_sends_once_and_a_second_sweep_sends_nothing(db):
    svc = _digest_svc(db)
    sender = StubSender()
    n = _notifier(svc, sender)

    first = n.sweep(MORNING)
    assert first.sent == 1 and len(sender.sent) == 1

    # The 07:32 sweep sees exactly what the 07:30 sweep saw. The ledger is the
    # only thing that knows the difference.
    second = n.sweep(MORNING.replace(minute=32))
    assert second.sent == 0 and len(sender.sent) == 1


def test_a_restart_mid_send_counts_as_sent(db):
    # A claimed-but-unsettled row is what a crash between the API call and the
    # INSERT looks like. It must not re-arm.
    svc = _digest_svc(db)
    store.claim_notification(db, "daily_digest", "2026-08-31")
    result = _notifier(svc).sweep(MORNING)
    assert result.sent == 0


def test_the_outcome_of_every_send_reaches_the_ledger(db):
    svc = _digest_svc(db)
    _notifier(svc).sweep(MORNING)
    row = store.recent_notifications(db)[0]
    assert row["trigger"] == "daily_digest" and row["ok"] == 1
    assert row["settled_at"] and row["silent"] == 0


def test_a_failed_send_is_recorded_and_not_retried_next_sweep(db):
    svc = _digest_svc(db)
    sender = StubSender(ok=False)
    n = _notifier(svc, sender)
    result = n.sweep(MORNING)
    assert result.failed == 1 and result.sent == 0
    row = store.recent_notifications(db)[0]
    assert row["ok"] == 0 and "502" in row["error"]
    # The transport already retried. Re-sending a stale alert is worse.
    assert n.sweep(MORNING.replace(minute=32)).sent == 0
    assert len(sender.sent) == 1


# ── the daily ceiling ────────────────────────────────────────────────────────

def test_past_the_ceiling_messages_are_silenced_not_dropped(db):
    for i in range(MAX_LOUD_PER_DAY):
        store.claim_notification(db, "filler", f"f{i}")
        store.settle_notification(db, "filler", f"f{i}", ok=True, silent=False)

    svc = _digest_svc(db)
    sender = StubSender()
    result = _notifier(svc, sender).sweep(MORNING)

    assert result.sent == 1 and result.downgraded == 1
    assert sender.sent[0]["silent"] is True, "the cap must never cost information"
    assert store.recent_notifications(db)[0]["silent"] == 1


def test_below_the_ceiling_a_loud_message_stays_loud(db):
    for i in range(MAX_LOUD_PER_DAY - 1):
        store.claim_notification(db, "filler", f"f{i}")
        store.settle_notification(db, "filler", f"f{i}", ok=True, silent=False)
    sender = StubSender()
    _notifier(_digest_svc(db), sender).sweep(MORNING)
    assert sender.sent[0]["silent"] is False


def test_silent_messages_do_not_consume_the_loud_budget(db):
    for i in range(MAX_LOUD_PER_DAY + 5):
        store.claim_notification(db, "filler", f"f{i}")
        store.settle_notification(db, "filler", f"f{i}", ok=True, silent=True)
    sender = StubSender()
    _notifier(_digest_svc(db), sender).sweep(MORNING)
    assert sender.sent[0]["silent"] is False


def test_yesterdays_buzzes_do_not_count_against_today(db):
    for i in range(MAX_LOUD_PER_DAY):
        store.claim_notification(db, "filler", f"f{i}")
        db.execute("UPDATE notification_deliveries SET claimed_at=?, silent=0 "
                   "WHERE dedupe_key=?", ("2026-08-30T12:00:00.000Z", f"f{i}"))
    sender = StubSender()
    _notifier(_digest_svc(db), sender).sweep(MORNING)
    assert sender.sent[0]["silent"] is False


# ── batching ─────────────────────────────────────────────────────────────────

def test_a_burst_from_one_rule_becomes_one_message(db):
    # Three interruptions in a minute is how a channel gets muted.
    events = [_event("2026-08-31T07:38:00", summary=f"Mtg {i}", uid=f"e{i}")
              for i in range(3)]
    svc = StubSvc(db, settings={**ON, "notify_triggers": {"daily_digest": False},
                                "time_format": "24h"}, events=events)
    sender = StubSender()
    result = _notifier(svc, sender).sweep(MORNING)

    assert len(sender.sent) == 1, "one send, not three"
    assert result.sent == 3, "but all three occasions are accounted for"
    text = sender.sent[0]["text"]
    assert text.startswith("3 things starting soon.")
    assert "Mtg 0" in text and "Mtg 2" in text
    # Each occasion still holds its own ledger row, so dedupe is unchanged.
    assert len(store.recent_notifications(db)) == 3


def test_two_at_once_stay_two_messages(db):
    events = [_event("2026-08-31T07:38:00", summary=f"Mtg {i}", uid=f"e{i}")
              for i in range(2)]
    svc = StubSvc(db, settings={**ON, "notify_triggers": {"daily_digest": False}},
                  events=events)
    sender = StubSender()
    _notifier(svc, sender).sweep(MORNING)
    assert len(sender.sent) == 2


# ── isolation and ordering ───────────────────────────────────────────────────

def test_one_broken_rule_does_not_cost_the_others_their_sweep(db):
    class Boom(StubSvc):
        def sync_health(self):
            raise RuntimeError("store exploded")

    svc = Boom(db, settings={**ON, "notify_digest_time": "07:30"})
    result = _notifier(svc).sweep(MORNING)
    assert result.sent == 1, "a broken digest must not swallow a meeting alert"
    assert any("sync_stalled" in e for e in result.errors)


def test_the_meeting_keeps_its_buzz_when_the_ceiling_bites(db):
    # Urgency order decides who is downgraded first: the digest, not the meeting.
    for i in range(MAX_LOUD_PER_DAY - 1):
        store.claim_notification(db, "filler", f"f{i}")
        store.settle_notification(db, "filler", f"f{i}", ok=True, silent=False)

    svc = _digest_svc(db, events=[_event("2026-08-31T07:38:00")])
    sender = StubSender()
    _notifier(svc, sender).sweep(MORNING)

    # The digest LISTS today's events, so classify on the headline rather than
    # on the title appearing anywhere in the body.
    kinds = {("event" if s["text"].startswith("Design review") else "digest"): s["silent"]
             for s in sender.sent}
    assert kinds == {"event": False, "digest": True}, \
        "the meeting keeps its buzz; the digest is the one that loses it"


def test_a_disabled_trigger_is_never_evaluated(db):
    svc = _digest_svc(db, settings={**ON, "notify_digest_time": "07:30",
                                    "notify_triggers": {"daily_digest": False}})
    sender = StubSender()
    assert _notifier(svc, sender).sweep(MORNING).sent == 0
    assert sender.sent == []


def test_an_unconfigured_notifier_does_nothing_at_all(db):
    svc = _digest_svc(db)
    sender = StubSender()
    n = Notifier(svc, sender, "", log=NullLog(), token="")   # nothing anywhere
    assert n.configured is False
    assert n.sweep(MORNING).sent == 0 and sender.sent == []


def test_nothing_is_sent_until_the_account_switches_notifications_on(db):
    # Absent means OFF for the master switch, unlike the per-rule map. It is
    # what stands between a deploy that merely has a bot token in its env and
    # one whose owner asked to be messaged.
    svc = StubSvc(db, settings={"notify_digest_time": "07:30"})   # no ON
    sender = StubSender()
    assert _notifier(svc, sender).sweep(MORNING).sent == 0
    assert sender.sent == []


def test_the_accounts_own_credentials_win_over_the_environment(db):
    svc = _digest_svc(db, settings={**ON, "notify_digest_time": "07:30",
                                    "notify_telegram_chat_id": "999",
                                    "notify_telegram_bot_token": "account-token"})
    sender = StubSender()
    n = _notifier(svc, sender)
    n.sweep(MORNING)
    assert sender.sent[0]["chat_id"] == "999"
    assert sender.token == "account-token"


def test_the_environment_still_works_for_a_deployment_that_never_opens_the_ui(db):
    svc = _digest_svc(db)
    sender = StubSender()
    _notifier(svc, sender).sweep(MORNING)
    assert sender.sent[0]["chat_id"] == "555"
    assert sender.token == "env-token"


def test_a_token_typed_into_settings_takes_effect_without_a_restart(db):
    svc = _digest_svc(db)
    sender = StubSender()
    n = _notifier(svc, sender)
    n.sweep(MORNING)
    assert sender.token == "env-token"
    svc._settings["notify_telegram_bot_token"] = "typed-later"
    n.sweep(MORNING.replace(day=30))          # a different day, so a new digest
    assert sender.token == "typed-later"


# ── ledger housekeeping ──────────────────────────────────────────────────────

def test_the_sweep_prunes_the_ledger_as_it_goes(db):
    store.claim_notification(db, "old", "ancient")
    db.execute("UPDATE notification_deliveries SET claimed_at='2020-01-01T00:00:00.000Z' "
               "WHERE dedupe_key='ancient'")
    _notifier(_digest_svc(db)).sweep(MORNING)
    assert not store.notification_already_sent(db, "old", "ancient")
    assert store.notification_already_sent(db, "daily_digest", "2026-08-31")


def test_local_midnight_is_the_owners_midnight_not_the_servers(db):
    # 00:30 UTC on the 31st is still 20:30 on the 30th in New York, so "today's"
    # budget must start at the 30th's midnight.
    stamp = Notifier._local_midnight(datetime(2026, 8, 31, 0, 30, tzinfo=timezone.utc), NY)
    assert stamp.startswith("2026-08-30T04:00")
