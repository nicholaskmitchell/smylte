"""The sweep: evaluate the rules, claim what has not been said, send it, settle.

Three phases, and the split between them is not stylistic. `SmylteService._lock`
is one process-wide RLock that every API route waits on, so a send performed
while holding it blocks the whole app for the length of an HTTP timeout — up to
a minute, on a bad network, with retries. So:

    1. PLAN and CLAIM, under the lock (short reads and one INSERT each).
    2. SEND, holding nothing.
    3. SETTLE, under the lock again.

Claiming before sending rather than after is what makes a crash safe. A row
written afterwards leaves a window in which the process dies between signal-bot
accepting the message and the INSERT landing, and the next sweep sends it again.
A claimed-but-unsettled row is therefore read as SENT, which is the right way
round: a duplicate 3am alert costs more trust than a missed one.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from ..db import store
from ..mail.secrets import SecretStoreError
from . import rules as R
from .signal import OWNER, SignalSender
from .transport import clip

# The ceiling, per local day, on notifications that BUZZ. Past it, further
# messages are downgraded to silent — never dropped. Downgrade rather than drop
# because the cap guards against a pathological day (a calendar import, twelve
# back-to-back meetings), not against the information itself; and because a
# dropped message would have to be either re-armed later (a duplicate) or
# released (a lie in the ledger).
MAX_LOUD_PER_DAY = 8

# More than this many messages from ONE rule in ONE sweep is a burst, and three
# interruptions in a minute is how a channel gets muted. They collapse into one
# message with a line each. Each occasion still gets its own ledger row, so the
# dedupe guarantee is unchanged — only the delivery is combined.
BATCH_THRESHOLD = 3

# How long a delivery row is kept. It only has to outlive the longest dedupe
# window any rule uses (a day key), so a month is already generous; the sweep is
# opportunistic, like `gc_oauth`, rather than a timer of its own.
LEDGER_RETENTION = timedelta(days=30)

# The most time-critical rule first, so that when the ceiling bites it is the
# digest and the operational notes that lose their buzz rather than the meeting
# that starts in ten minutes.
#
# `item_reminder` outranks even that: the owner set a lead on that one item by
# hand, which is the strongest signal in the system that they want to be told.
# A rule nobody asked for should never silence one they did.
_URGENCY = {"item_reminder": 0, "event_starting": 1, "daily_digest": 2}


def loud_deliveries_since(conn, stamp: str) -> int:
    """How many BUZZES have gone out since `stamp` — the count behind the ceiling.

    Two things the ledger's row count gets wrong, both in the direction of
    silencing a meeting alert on a day that barely interrupted anyone.

    A loud send the transport refused settles `ok=0, silent=0`. Charged per row it
    spent a slot on every later sweep although `_dispatch` charges a buzz only
    `if outcome.ok` — eight refusals silenced the day. A row counts here when it
    went out, or when it is claimed and not yet settled (a crash mid-send, read
    as SENT because erring quieter is the right direction for a noise ceiling
    to be wrong in).

    A batch settles one row per OCCASION and `_batches` promises "only the
    delivery is combined" — but the 07:30 morning message (four occasions, one
    buzz) used to spend four of the eight slots. The ledger now records which
    delivery each row rode in (`message_id`, the transport's own id), so a
    combined message is one buzz here however many occasions it carried. A row
    with no id — settled before the column existed, or by a transport that
    returned none — counts alone, which is the per-row charge it always had.
    """
    row = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN ok = 1 AND message_id IS NOT NULL "
        "                          THEN message_id END) "
        "     + COALESCE(SUM(CASE WHEN (ok = 1 AND message_id IS NULL) "
        "                          OR settled_at IS NULL THEN 1 ELSE 0 END), 0) "
        "FROM notification_deliveries "
        "WHERE claimed_at >= ? AND silent = 0",
        (stamp,),
    ).fetchone()
    return int(row[0]) if row else 0


@dataclass
class SweepResult:
    considered: int = 0
    sent: int = 0
    downgraded: int = 0          # sent, but silenced by the ceiling
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.sent or self.failed)


class Notifier:
    """Owns one sender and the sweep over the rules. One per process."""

    def __init__(self, svc, sender: SignalSender, *, log,
                 token: Callable[[], str | None], interval_s: float = 60.0) -> None:
        self._svc = svc
        # How often sweep() runs (SMYLTE_NOTIFY_INTERVAL; the default is the
        # shipped one). The rules need it: it is the width of the window an
        # "at the time" reminder may go out in (rules.late_grace).
        self._interval_s = interval_s
        # When the last sweep evaluated the rules, so the next one's "at the
        # time" window starts exactly where that one's ended (rules.late_floor).
        self._last_swept: datetime | None = None
        self._sender = sender
        # Where the signal-bot token comes from: the secret store, with
        # SMYLTE_SIGNAL_TOKEN overriding it (see app._build_notifier). Called
        # once per sweep and per test send, so a token pasted into Settings
        # takes effect on the next tick rather than the next restart.
        self._token_provider = token
        self._log = log
        # Latched so a misconfiguration is stated once rather than every minute.
        self._warned_no_tz = False
        self._warned_store: str | None = None

    def _token(self) -> str:
        """The current token, stripped, or "" when there is none.

        An unusable secret store reads as "no token" — the sweep then sends
        nothing, which is what it would do anyway — and is said once per
        distinct reason rather than every minute. The error's str() is safe to
        log: SecretStoreError never carries a secret."""
        try:
            value = self._token_provider()
        except SecretStoreError as exc:
            reason = str(exc)
            if self._warned_store != reason:
                self._warned_store = reason
                self._log.warning("notify: the secret store is unavailable: %s", reason)
            return ""
        # Readable again: the next outage is a new one, and is said once too.
        self._warned_store = None
        return value.strip() if isinstance(value, str) else ""

    def enabled(self, prefs: dict) -> bool:
        """Whether the account has switched notifications on at all.

        Absent means OFF. Unlike the per-rule map, whose absent key means "that
        rule's default", the master switch has no safe default but off: it is
        what stands between a deploy that merely has a bot token lying in its
        env and one whose owner asked to be messaged.
        """
        return prefs.get("notifications_enabled") is True

    def close(self) -> None:
        """Release the HTTP connection pool. Called from the app's lifespan."""
        self._sender.close()

    def send_test(self) -> tuple[bool, str]:
        """Send one proof-of-life message. Returns (ok, a sentence to show).

        Every misconfiguration here fails the same silent way, so the value of
        this is entirely in the message it hands back — which is why the
        transport's redacted error is passed through rather than flattened to
        "failed".
        """
        # The provider directly rather than `_token()`: the owner pressed a
        # button and is waiting for an answer, so an unreadable store is said
        # here, not logged once and passed off as "no token". Its str() is safe
        # by contract: SecretStoreError never carries a secret.
        try:
            value = self._token_provider()
        except SecretStoreError as exc:
            return False, f"The secret store cannot be read: {exc}"
        token = value.strip() if isinstance(value, str) else ""
        if not token:
            return False, ("No signal-bot token is set. Add Smylte as a source on the bot "
                           "(signal-bot source add Smylte), then paste the token it prints.")
        self._sender.token = token
        # The local time in the text, because the bot refuses the same text
        # within a minute: a second press would otherwise be "refused" as a
        # duplicate of the first. No "Smylte: " here: the bot labels every
        # message with its source.
        tz = self._svc._home_tz() or timezone.utc
        at = datetime.now(timezone.utc).astimezone(tz).strftime("%H:%M:%S")
        result = self._sender.send(
            OWNER,
            f"Connected at {at}. This is the only message you will get that you "
            "asked for directly.",
            silent=True,
        )
        if result.ok:
            return True, "Sent."
        error = result.error or "the send failed"
        # One trailing full stop off before a hint goes on, so the two do not
        # read "..".
        stem = error[:-1] if error.endswith(".") else error
        if not result.permanent:
            where = urlsplit(self._sender.base_url).netloc
            return False, f"{stem}. Check that signal-bot is running and listening on {where}."
        if result.status in (401, 403):
            # The two that are almost always the cause, named rather than left
            # to an error string nobody should have to interpret.
            return False, f"{stem}. Check the token, and that the Smylte source is enabled on the bot."
        # Any other refusal (a 422 above all) gets no hint: the bot's own
        # sentence says why it refused.
        return False, error

    def sweep(self, now: datetime | None = None) -> SweepResult:
        """One pass. Never raises — the caller is a background loop."""
        result = SweepResult()
        now = now or datetime.now(timezone.utc)

        prefs = self._svc.get_settings()
        if not self.enabled(prefs):
            return result
        token = self._token()
        if not token:
            return result
        # Adopted per sweep, not per process: the token can be pasted into
        # Settings and must take effect on the next tick rather than the next
        # restart.
        self._sender.token = token
        # Same-package private on purpose: the alternative is a second reading
        # of `home_timezone`, and a second reading is how two parts of this app
        # end up disagreeing about what day it is.
        tz = self._svc._home_tz()
        day = now.astimezone(tz).date().isoformat()
        # Only an earlier `now` counts: a test (or a clock step) sweeping
        # backwards must not get a window that ends before it starts.
        since = self._last_swept if self._last_swept and self._last_swept < now else None
        sweep = R.Sweep(svc=self._svc, now=now, tz=tz, day=day, prefs=prefs,
                        interval_s=self._interval_s, since=since)
        self._last_swept = now

        if tz is None and not self._warned_no_tz:
            self._warned_no_tz = True
            self._log.warning(
                "notify: home_timezone is unset, so the daily digest will not "
                "fire — an hour resolved against the server clock (UTC in the "
                "ordinary deploy) is not the hour anyone chose. Set it in "
                "Settings > General."
            )

        pending = self._plan(sweep, result)
        if not pending:
            return result
        self._dispatch(pending, now, tz, result)
        self._sweep_ledger(now)
        return result

    # ── phase 1: plan ────────────────────────────────────────────────────────
    def _plan(self, sweep: R.Sweep, result: SweepResult) -> list[R.Pending]:
        out: list[R.Pending] = []
        for rule in R.RULES:
            if not R.trigger_enabled(sweep.prefs, rule):
                continue
            try:
                found = rule.evaluate(sweep)
            except Exception as exc:  # noqa: BLE001
                # One rule that throws must not cost the others their sweep —
                # a broken digest should never swallow a meeting alert.
                result.errors.append(f"{rule.id}: {type(exc).__name__}")
                self._log.warning("notify: rule %s failed: %s", rule.id, exc)
                continue
            out.extend(found)
        result.considered = len(out)
        out.sort(key=lambda p: (_URGENCY.get(p.trigger, 9), p.dedupe_key))
        return out

    # ── phases 2 and 3: claim, send, settle ──────────────────────────────────
    def _dispatch(self, pending: list[R.Pending], now: datetime, tz, result: SweepResult) -> None:
        midnight = self._local_midnight(now, tz)

        # Read the day's budget BEFORE claiming anything. A claim writes a row
        # that reads `silent=0` until it settles, so counting afterwards makes
        # every message in this sweep count ITSELF against the ceiling — which
        # silenced the eighth message of the day rather than the ninth, and
        # silenced both of a pair when only the second should have been.
        loud_today = self._svc.notifications(loud_deliveries_since, midnight)

        # Then claim, all of it, under the lock. Anything already said drops out
        # here and never reaches the transport.
        claimed: list[R.Pending] = [
            p for p in pending
            if self._svc.notifications(store.claim_notification, p.trigger, p.dedupe_key)
        ]
        if not claimed:
            return

        for group in self._batches(claimed):
            silent = group[0].silent
            if not silent and loud_today >= MAX_LOUD_PER_DAY:
                silent = True
                result.downgraded += len(group)
            text = self._render(group)
            outcome = self._sender.send(OWNER, text, silent=silent)
            message_id = outcome.message_id
            if outcome.ok and message_id is None:
                # Delivered, but the bot named no message (a 422 after a lost
                # answer). Every row of the group still rode in ONE delivery,
                # so they share one id and the ceiling charges the batch once.
                # Negative, so it never collides with signal-bot's positive ms
                # timestamps; microseconds, so two deliveries never share one.
                message_id = -(time.time_ns() // 1000)
            if outcome.ok:
                result.sent += len(group)
                if not silent:
                    loud_today += 1
            else:
                result.failed += len(group)
                result.errors.append(outcome.error or "send failed")
                self._log.warning("notify: send failed: %s", outcome.error)
            for p in group:
                self._svc.notifications(
                    store.settle_notification, p.trigger, p.dedupe_key,
                    ok=outcome.ok, silent=silent, error=outcome.error,
                    message_id=message_id,
                )

    @staticmethod
    def _batches(claimed: list[R.Pending]) -> list[list[R.Pending]]:
        """Collapse a burst into one send, ACROSS rules and not just within one.

        Partitioned by `silent` first, because that is the one thing a batch
        cannot average: a loud rule and a quiet one sharing a message would
        either wake someone for a booking or swallow a meeting alert.

        Across rules, because that is where the real burst is. Turning on the
        three morning nudges puts four qualifying messages in the 07:30 sweep —
        the digest, what is overdue, that the day is unplanned, that the plan
        runs long — and four interruptions in one minute is precisely how a
        channel gets muted. Within-rule batching alone would have sent all four.

        Each occasion still holds its own ledger row, so the dedupe guarantee is
        untouched; only the delivery is combined.
        """
        out: list[list[R.Pending]] = []
        for silent in (False, True):
            group = [p for p in claimed if p.silent is silent]
            if not group:
                continue
            if len(group) >= BATCH_THRESHOLD:
                out.append(group)
            else:
                out.extend([p] for p in group)
        # The urgency order the caller sorted into, preserved so the ceiling
        # silences the digest before it silences a meeting.
        out.sort(key=lambda g: (_URGENCY.get(g[0].trigger, 9), g[0].dedupe_key))
        return out

    @staticmethod
    def _render(group: list[R.Pending]) -> str:
        if len(group) == 1:
            return clip(group[0].text)
        # Full bodies, not just headlines. A batch is a convenience of DELIVERY
        # and must not cost information — the digest's whole value is its lines,
        # and a morning batch that kept only "Mon 31 Aug: 3 events, 5 due" would
        # have replaced the one message worth sending with a summary of it.
        # `clip` is the backstop; the per-rule shape caps are what keep it from
        # being reached.
        head = (f"{len(group)} things starting soon."
                if all(p.trigger in ("event_starting", "item_reminder", "task_due_soon")
                       for p in group)
                else f"{len(group)} updates.")
        return clip("\n".join([head] + [p.text for p in group]))

    @staticmethod
    def _local_midnight(now: datetime, tz) -> str:
        """Today's local midnight as the '...Z' stamp the ledger stores."""
        local = now.astimezone(tz) if tz else now
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return (start.astimezone(timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"))

    def _sweep_ledger(self, now: datetime) -> None:
        before = ((now - LEDGER_RETENTION)
                  .isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        try:
            self._svc.notifications(store.gc_notifications, before=before)
        except Exception as exc:  # noqa: BLE001 — a failed sweep is not a failed send
            self._log.warning("notify: ledger sweep failed: %s", exc)
