"""The delivery ledger — pure sqlite via the `db` fixture, no Radicale.

Everything here is about one property: a notification arrives at most once. The
scheduler re-evaluates the same window on every wake, so the ledger is the only
thing standing between "09:00 sweep" and "09:02 sweep after a restart" sending
the same message twice.
"""
from __future__ import annotations

from tasksd.db import store

TRIGGER = "event_starting"
KEY = "evt-abc:2026-08-31T09:00:00Z"


def test_the_first_claim_wins_and_the_second_does_not(db):
    assert store.claim_notification(db, TRIGGER, KEY) is True
    assert store.claim_notification(db, TRIGGER, KEY) is False


def test_a_claim_is_visible_before_it_is_settled(db):
    # This is the crash-safety property: a claimed-but-unsettled row counts as
    # sent, because the alternative is re-arming a message that may have landed.
    store.claim_notification(db, TRIGGER, KEY)
    assert store.notification_already_sent(db, TRIGGER, KEY)
    row = store.recent_notifications(db)[0]
    assert row["settled_at"] is None and row["ok"] == 0


def test_settling_records_the_outcome_without_freeing_the_key(db):
    store.claim_notification(db, TRIGGER, KEY)
    store.settle_notification(db, TRIGGER, KEY, ok=True, silent=True)
    row = store.recent_notifications(db)[0]
    assert row["ok"] == 1 and row["silent"] == 1 and row["settled_at"]
    assert store.claim_notification(db, TRIGGER, KEY) is False


def test_a_failed_send_is_recorded_and_not_retried(db):
    # The transport has already retried (notify/telegram.py). A "starting in 10
    # minutes" redelivered half an hour later is worse than silence.
    store.claim_notification(db, TRIGGER, KEY)
    store.settle_notification(db, TRIGGER, KEY, ok=False, error="HTTP 502: Bad Gateway")
    row = store.recent_notifications(db)[0]
    assert row["ok"] == 0 and row["error"] == "HTTP 502: Bad Gateway"
    assert store.claim_notification(db, TRIGGER, KEY) is False


def test_releasing_a_claim_re_arms_it(db):
    # Only for a send that never reached the transport at all.
    store.claim_notification(db, TRIGGER, KEY)
    store.release_notification(db, TRIGGER, KEY)
    assert store.claim_notification(db, TRIGGER, KEY) is True


def test_triggers_and_occasions_do_not_collide(db):
    store.claim_notification(db, TRIGGER, KEY)
    # A different rule about the same occasion is a different notification.
    assert store.claim_notification(db, "event_soon", KEY) is True
    # The same rule about a different occasion is too.
    assert store.claim_notification(db, TRIGGER, "evt-abc:2026-09-01T09:00:00Z") is True
    # And a different channel is a different delivery.
    assert store.claim_notification(db, TRIGGER, KEY, channel="email") is True


def test_the_sweep_drops_only_what_is_older_than_the_cutoff(db):
    store.claim_notification(db, TRIGGER, "old")
    db.execute(
        "UPDATE notification_deliveries SET claimed_at='2020-01-01T00:00:00.000Z' "
        "WHERE dedupe_key='old'"
    )
    store.claim_notification(db, TRIGGER, "fresh")
    assert store.gc_notifications(db, before="2021-01-01T00:00:00.000Z") == 1
    assert not store.notification_already_sent(db, TRIGGER, "old")
    assert store.notification_already_sent(db, TRIGGER, "fresh")


def test_recent_notifications_is_newest_first_and_bounded(db):
    for i in range(5):
        store.claim_notification(db, TRIGGER, f"k{i}")
        db.execute(
            "UPDATE notification_deliveries SET claimed_at=? WHERE dedupe_key=?",
            (f"2026-08-3{i}T09:00:00.000Z", f"k{i}"),
        )
    rows = store.recent_notifications(db, limit=3)
    assert [r["dedupe_key"] for r in rows] == ["k4", "k3", "k2"]
    # The limit is clamped rather than trusted — this feeds an API route.
    assert len(store.recent_notifications(db, limit=10_000)) == 5
