"""The delivery ledger — pure sqlite via the `db` fixture, no Radicale.

Everything here is about one property: a notification arrives at most once. The
scheduler re-evaluates the same window on every wake, so the ledger is the only
thing standing between "09:00 sweep" and "09:02 sweep after a restart" sending
the same message twice.
"""
from __future__ import annotations

import json

from smylted.db import store

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
    # The transport has already retried (notify/signal.py). A "starting in 10
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


# ── the move from Telegram to signal-bot ─────────────────────────────────────

def _raw_claim(db, trigger, key, channel):
    db.execute("INSERT INTO notification_deliveries (trigger, dedupe_key, channel) "
               "VALUES (?, ?, ?)", (trigger, key, channel))


def test_rows_told_on_telegram_are_cut_over_to_signal(db):
    # An occasion already told on Telegram must not be told again on Signal.
    _raw_claim(db, TRIGGER, KEY, "telegram")
    _raw_claim(db, "daily_digest", "2026-08-31", "telegram")
    _raw_claim(db, "daily_digest", "2026-08-31", "signal")     # both: keep one
    store.init_db(db)
    rows = db.execute("SELECT trigger, dedupe_key, channel FROM notification_deliveries "
                      "ORDER BY trigger").fetchall()
    assert [tuple(r) for r in rows] == [("daily_digest", "2026-08-31", "signal"),
                                        (TRIGGER, KEY, "signal")]
    assert store.claim_notification(db, TRIGGER, KEY) is False
    assert store.claim_notification(db, "daily_digest", "2026-08-31") is False
    store.init_db(db)                                       # idempotent
    assert db.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0] == 2


def test_the_old_telegram_settings_are_scrubbed_at_start(db):
    store.set_meta(db, "app_settings", json.dumps({
        "notify_telegram_bot_token": "123456789:AAHsecretsecretsecretsecret",
        "notify_telegram_chat_id": "8517516151",
        "theme": "dark"}))
    store.init_db(db)
    assert json.loads(store.get_meta(db, "app_settings")) == {"theme": "dark"}


def test_a_blob_without_them_is_left_byte_for_byte(db):
    raw = '{"theme":   "dark", "notify_digest_time": "07:30"}'
    store.set_meta(db, "app_settings", raw)
    store.init_db(db)
    assert store.get_meta(db, "app_settings") == raw
    store.set_meta(db, "app_settings", '["not", "an", "object"]')
    store.init_db(db)
    assert store.get_meta(db, "app_settings") == '["not", "an", "object"]'


def test_the_scrub_leaves_no_copy_of_the_token_on_disk(tmp_path):
    # Rewriting the row is not enough: every earlier save of the settings left
    # a copy of the blob in a page that is now free, and the write-ahead log
    # holds more. Overflow-sized blobs, so each save moves the blob to new pages.
    secret = "123456789:AAHscrubbedscrubbedscrubbedscrub"
    path = tmp_path / "smylte.db"
    wal = tmp_path / "smylte.db-wal"
    conn = store.connect(str(path))
    store.init_db(conn)
    for i in range(10):
        store.set_meta(conn, "app_settings", json.dumps({
            "notify_telegram_bot_token": secret, "theme": "dark", "pad": "p" * (5000 + 700 * i)}))
    conn.close()
    assert secret.encode() in path.read_bytes(), "the fixture must leave old copies on disk"

    def on_disk() -> bytes:
        return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")

    conn = store.connect(str(path))
    store.init_db(conn)
    assert "notify_telegram_bot_token" not in json.loads(store.get_meta(conn, "app_settings"))
    # While the connection is still open: nothing waits for a close to tidy up.
    assert secret.encode() not in on_disk()
    conn.close()
    assert secret.encode() not in on_disk()
