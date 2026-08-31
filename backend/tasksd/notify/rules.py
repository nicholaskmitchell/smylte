"""Which notifications exist, when each one fires, and what it says.

Read this file as the answer to "when should the app interrupt me", because
that is what it is. The mechanism (`telegram.py`, the ledger, `scheduler.py`)
is deliberately trigger-agnostic; the policy is all here.

THE BAR. Smylte already has a place to put information the owner will come
looking for — Smylte. So a notification has to earn its send by being something
they cannot recover by opening the app later. That leaves four things: a summary
read once at an hour they chose, which replaces opening the app; a meeting that
starts before they will next look; a stranger who put something on their
calendar while they weren't watching; and the app quietly lying to them because
sync is broken. Everything else people usually build — "task due soon", "you're
overdue", "you haven't planned today" — restates state that is standing or
already on the screen they open anyway. Each of those is a line in the digest,
not a message.

THE SHAPE EVERY RULE HAS. A trigger is a fire INSTANT plus a window that CLOSES,
and the predicate is evaluated backwards over the window (`fire <= now < close`)
rather than forwards from the tick. That one shape discharges most of the hard
cases at once: restart catch-up needs no persisted scheduler state, because the
loop comes up, sweeps, and the ledger decides what has already been said; and a
window that closed while the box was down simply never fires and leaves no row.
DST is correct by construction wherever it matters, because a fire instant is
derived from the event's own instant rather than from a wall clock.

THE ADMISSION TEST FOR A FIFTH RULE. Write its `dedupe_key` first. If you cannot
express it as something that STOPS EXISTING — a day key, a start instant, a
booking id — then the condition is standing, it will re-qualify on every sweep,
and whatever dedupe policy you pick to stop it repeating is arbitrary. Standing
conditions are digest lines. `sync_stalled` below is the one deliberate
exception and it is marked as such.

LOUD AND QUIET ARE FIXED IN CODE, NOT CONFIGURED. `daily_digest` and
`event_starting` buzz; `booking_created` and `sync_stalled` always send with
`disable_notification`. That is why there is no quiet-hours setting: the only
rule that could fire at 3am from outside the owner's control is a booking, and a
booking is silent by construction. A quiet-hours window would be a preference
that exists to compensate for a policy mistake, and not making the mistake is
cheaper — it removes a settings section, the wrap-midnight arithmetic, and the
`release_notification` path that deferral would have needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .. import due as due_rules
from ..scheduling import parse_event_time

# The one source of truth for the ledger's free-text `trigger` column, the
# settings-blob toggle keys and the UI labels. A rule not named here cannot be
# enabled, and a stale key in the settings blob is ignored rather than honoured.
TRIGGERS: tuple[str, ...] = (
    "daily_digest",
    "event_starting",
    "booking_created",
    "sync_stalled",
)

DEFAULT_DIGEST_TIME = "07:30"
DEFAULT_EVENT_LEAD_MINUTES = 10

# A digest more than this late is stale — the day is half over and it would be
# describing a morning that already happened. Skip the day rather than send it.
DIGEST_STALE_AFTER = timedelta(hours=4)
# How far back a booking can be and still be worth announcing. Also the bound on
# what a restore from a backup without the ledger can re-send.
BOOKING_CATCH_UP = timedelta(hours=24)
# An error younger than this is a blip: `set_sync_error` writes `last_error`
# without touching `last_sync_at`, and `set_sync_token` bumps `last_sync_at`
# only on a good pass, so "an error stands AND nothing has succeeded for an
# hour" is precisely "this is not a Radicale restart".
SYNC_STALL_AFTER = timedelta(hours=1)

# Shape guards for the digest. The failure mode of a daily summary is that it
# gets long and stops being read; `notify.clip` is the backstop, not the plan.
MAX_DIGEST_EVENTS = 5
MAX_DIGEST_TASKS = 5


@dataclass(frozen=True)
class Pending:
    """One notification that has qualified but has not been claimed or sent."""
    trigger: str
    dedupe_key: str
    text: str
    silent: bool


@dataclass(frozen=True)
class Sweep:
    """Everything a rule may read, gathered once so rules cannot disagree.

    In particular `now` is passed in rather than read per rule: two rules that
    each called `datetime.now()` could straddle a minute boundary and answer
    different questions about the same sweep. Tests set it directly.
    """
    svc: Any
    now: datetime                    # aware, UTC
    tz: ZoneInfo | None              # the owner's home zone, or None if unset
    day: str                         # local day key, YYYY-MM-DD
    prefs: dict[str, Any]            # the app_settings blob
    interval_s: float                # the sweep cadence, i.e. the window width

    @property
    def local_now(self) -> datetime:
        return self.now.astimezone(self.tz) if self.tz else self.now


@dataclass(frozen=True)
class Rule:
    id: str
    default_on: bool
    silent: bool                     # fixed in code — see the module docstring
    evaluate: Callable[[Sweep], list[Pending]]


# ── preferences ──────────────────────────────────────────────────────────────
#
# A SPARSE override map, not a set of booleans that default true: an absent key
# means "this rule's own default". A rule added in six months is then off or on
# by its own declaration rather than by whatever the account's blob happened to
# be written with before the rule existed.

def trigger_enabled(prefs: dict[str, Any], rule: Rule) -> bool:
    override = (prefs.get("notify_triggers") or {})
    value = override.get(rule.id) if isinstance(override, dict) else None
    return rule.default_on if not isinstance(value, bool) else value


def digest_time(prefs: dict[str, Any]) -> tuple[int, int]:
    """The owner's digest hour as (hour, minute); the default if unreadable.

    Re-validated rather than trusted: the settings blob is one JSON document
    that an older client, a restored backup or a hand edit can put anything in.
    """
    raw = prefs.get("notify_digest_time")
    if not isinstance(raw, str):
        raw = DEFAULT_DIGEST_TIME
    try:
        hh, _, mm = raw.partition(":")
        h, m = int(hh), int(mm)
    except (TypeError, ValueError):
        return _hhmm(DEFAULT_DIGEST_TIME)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return _hhmm(DEFAULT_DIGEST_TIME)
    return h, m


def _hhmm(value: str) -> tuple[int, int]:
    h, _, m = value.partition(":")
    return int(h), int(m)


def event_lead(prefs: dict[str, Any]) -> timedelta:
    """How far ahead of a meeting to say something.

    Floored at three minutes because the pipeline cannot beat it: the CalDAV
    poll is `sync_interval_s` (30s) and the notify tick is another
    `notify_interval_s` (60s), so a two-minute lead would routinely fire after
    the meeting had already started — and the rule refuses to send then.
    """
    raw = prefs.get("notify_event_lead_minutes")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raw = DEFAULT_EVENT_LEAD_MINUTES
    return timedelta(minutes=max(3, min(raw, 120)))


def _clock(prefs: dict[str, Any]) -> str:
    """The owner's clock. A notification is a clock the app draws, so it uses
    the same one as every other surface (`frontend/src/time.ts`)."""
    return "%H:%M" if prefs.get("time_format") == "24h" else "%-I:%M %p"


def _fmt_time(value: datetime, prefs: dict[str, Any]) -> str:
    return value.strftime(_clock(prefs)).strip()


# ── daily_digest ─────────────────────────────────────────────────────────────

def _eval_digest(s: Sweep) -> list[Pending]:
    """One message a day, at an hour the owner set, that answers "what does
    today look like" completely enough that they need not open the app.

    This is the only rule that is genuinely worth the interruption, and it is
    worth it because it REPLACES an action rather than adding one.
    """
    # Refuse rather than guess. With `home_timezone` unset the server clock is
    # UTC in the ordinary deploy, so "07:30" would arrive at 03:30 in California
    # — and a digest that lands in the middle of the night is how the channel
    # gets muted, taking the other three rules with it. The scheduler logs this
    # once; Settings says so too.
    if s.tz is None:
        return []

    hour, minute = digest_time(s.prefs)
    local = s.local_now
    fire = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not (fire <= local < fire + DIGEST_STALE_AFTER):
        return []

    text = _digest_text(s)
    return [Pending("daily_digest", s.day, text, silent=False)] if text else []


def _digest_text(s: Sweep) -> str:
    events = _todays_events(s)
    due_today, overdue = _todays_tasks(s)

    counts = []
    if events:
        counts.append(f"{len(events)} event{'s' if len(events) != 1 else ''}")
    if due_today:
        counts.append(f"{len(due_today)} due")
    if overdue:
        counts.append(f"{overdue} overdue")
    headline = s.local_now.strftime("%a %-d %b")
    # An empty day is a real answer and worth saying — it is the one morning the
    # owner most wants to be told they can stop checking.
    headline += f": {', '.join(counts)}." if counts else ": nothing scheduled."

    lines = [headline]
    for start, summary, all_day in events[:MAX_DIGEST_EVENTS]:
        when = "all day" if all_day else _fmt_time(start, s.prefs)
        lines.append(f"{when}  {summary}")
    if len(events) > MAX_DIGEST_EVENTS:
        lines.append(f"+{len(events) - MAX_DIGEST_EVENTS} more events")
    for summary in due_today[:MAX_DIGEST_TASKS]:
        lines.append(f"· {summary}")
    if len(due_today) > MAX_DIGEST_TASKS:
        lines.append(f"+{len(due_today) - MAX_DIGEST_TASKS} more due")
    return "\n".join(lines)


def _todays_events(s: Sweep) -> list[tuple[datetime, str, bool]]:
    """Today's events across every calendar, sorted, as (start, summary, all_day)."""
    local = s.local_now
    start_of_day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    out: list[tuple[datetime, str, bool]] = []
    for occ in _occurrences(s, start_of_day, end_of_day):
        if occ.get("all_day"):
            out.append((start_of_day, occ.get("summary") or "(untitled)", True))
            continue
        when = _instant(occ, s)
        if when is not None and start_of_day <= when.astimezone(s.tz) < end_of_day:
            out.append((when.astimezone(s.tz), occ.get("summary") or "(untitled)", False))
    # All-day first, then by clock — the order the day is actually lived in.
    out.sort(key=lambda row: (not row[2], row[0]))
    return out


def _todays_tasks(s: Sweep) -> tuple[list[str], int]:
    """(titles due today, count already overdue).

    "Overdue" is `due.due_parts`, the app's own rule, imported rather than
    re-derived — the connector and `frontend/src/util.ts` answer with the same
    two numbers and a third answer here would be a third number on screen.
    """
    from ..service import _due_day

    now_epoch = s.now.timestamp()
    due_today: list[str] = []
    overdue = 0
    for lst in s.svc.list_lists():
        for task in s.svc.list_tasks(lst["href"], include_done=False):
            parts = due_rules.due_parts(task.get("due"), s.tz)
            if parts is None:
                continue
            if parts[1] < now_epoch:
                overdue += 1
                continue
            if _due_day(task.get("due"), is_date=task.get("due_is_date", False),
                        zone=s.tz) == s.day:
                due_today.append(task.get("summary") or "(untitled)")
    return due_today, overdue


# ── event_starting ───────────────────────────────────────────────────────────

def _eval_event_starting(s: Sweep) -> list[Pending]:
    """The one case the digest structurally cannot cover: the owner read it at
    07:30 and is heads-down at 14:50 when a 15:00 call exists.

    The lower bound is deliberately zero rather than negative. If the box was
    down and the meeting has already started, saying so is noise — nothing is
    sent and nothing is claimed, so a later restart cannot resurrect it either.
    """
    lead = event_lead(s.prefs)
    out: list[Pending] = []
    for occ in _occurrences(s, s.now - timedelta(days=1), s.now + lead + timedelta(days=1)):
        if occ.get("all_day") or occ.get("status") == "CANCELLED" or not occ.get("busy"):
            continue
        start = _instant(occ, s)
        if start is None:
            continue
        delta = start - s.now
        if not (timedelta(0) <= delta <= lead):
            continue
        summary = occ.get("summary") or "(untitled)"
        minutes = max(0, int(delta.total_seconds() // 60))
        local = start.astimezone(s.tz) if s.tz else start
        when = _fmt_time(local, s.prefs)
        text = f"{summary} at {when} — in {minutes} min."
        if occ.get("location"):
            text += f"\n{occ['location']}"
        out.append(Pending(
            "event_starting",
            # The collection href, not the slug: a UID is unique per collection
            # and not globally (invariant #4). The start INSTANT, not
            # `recurrence_id`, because that falls back to the instance's own
            # start on malformed resources — and keying on the instant gives the
            # right behaviour when a meeting is moved, since the new time is a
            # new occasion and re-arms.
            f"{occ.get('calendar')}|{occ.get('master_uid') or occ.get('uid')}"
            f"|{start.astimezone(timezone.utc).isoformat()}",
            text,
            silent=False,
        ))
    return out


# ── booking_created ──────────────────────────────────────────────────────────

def _eval_booking_created(s: Sweep) -> list[Pending]:
    """The only information in the app that originates outside the owner and
    arrives while they are not looking.

    Polled from the `bookings` ledger rather than taken off the SSE bus:
    `book_slot` publishes an event, but `_recover_orphaned_booking` inserts a
    real row and publishes nothing, so an event-driven hook would silently
    under-report exactly the bookings that went wrong.
    """
    floor = (s.now - BOOKING_CATCH_UP).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    out: list[Pending] = []
    for row in s.svc.bookings_created_since(floor):
        start = _parse_iso(row.get("start_at"))
        local = start.astimezone(s.tz) if (start and s.tz) else start
        when = _fmt_time(local, s.prefs) if local else "an unknown time"
        day = local.strftime("%a %-d %b") if local else ""
        name = (row.get("client_name") or "Someone").strip() or "Someone"
        title = (row.get("link_title") or "time").strip() or "time"
        out.append(Pending(
            "booking_created",
            # `bookings.id` — a natural key that is already unique, and one that
            # cannot recur. No FK from the ledger to `bookings` exists and none
            # should be added: the schema's own note says a cascade would re-arm
            # a notification that has already been delivered.
            str(row.get("id")),
            f"{name} booked {title}{(' ' + day) if day else ''} at {when}.",
            silent=True,
        ))
    return out


# ── sync_stalled ─────────────────────────────────────────────────────────────

def _eval_sync_stalled(s: Sweep) -> list[Pending]:
    """The only condition where the app is actively lying: everything on screen
    looks normal and the data is simply frozen. `sync_state.last_error` is
    surfaced to the owner nowhere else — not in the SPA, not in the API — so
    without this they find out days later when a task added on their phone
    never appeared.

    THE DELIBERATE EXCEPTION to the admission test at the top of this file. "Sync
    has been broken for an hour" is a standing condition, so the day key does
    NOT name an occasion that stops existing: while it stays broken this sends
    one message per day, forever. That is the honest cost and it is bounded — one
    silent line a day — where the alternatives are worse: a shorter bucket is
    more noise about one fact, and a once-ever key means a second outage next
    month says nothing at all.

    There is deliberately no "sync recovered" message. A second message to
    retract the first is exactly the pattern that trains people to stop reading.
    """
    stalled = s.svc.sync_health()
    if not stalled:
        return []
    cutoff = (s.now - SYNC_STALL_AFTER).isoformat().replace("+00:00", "Z")
    broken = [r for r in stalled
              if not r.get("last_sync_at") or (r.get("last_sync_at") or "") < cutoff]
    if not broken:
        return []
    names = ", ".join(sorted({(r.get("name") or "?") for r in broken}))
    # The error text itself is deliberately NOT sent. It comes from the DAV
    # layer, it is unbounded, and the transport is a postcard through two
    # systems: a connection string or a URL with a credential in it must not
    # ride along. Point at where it lives instead of moving it.
    return [Pending(
        "sync_stalled",
        s.day,
        f"Smylte sync is failing — {names}. Nothing new has synced for over an "
        f"hour; check the tasksd log.",
        silent=True,
    )]


# ── shared plumbing ──────────────────────────────────────────────────────────

def _occurrences(s: Sweep, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Every event occurrence across every calendar in the window.

    The SQL range scan compares ISO strings against mostly-naive `dtstart`
    values, so the bounds are naive-widened by a day and the precise filter
    happens in Python — the same shape `service._link_busy` uses.

    `blocking=False` on purpose, unlike the booking path: `blocking=True`
    reports an unexpandable series as covering the whole window, which for this
    caller would be a false alarm every single minute. The grid's degradation to
    the master row at least names a real time.
    """
    start_iso = (start - timedelta(days=1)).replace(tzinfo=None).isoformat()
    end_iso = (end + timedelta(days=1)).replace(tzinfo=None).isoformat()
    out: list[dict[str, Any]] = []
    for cal in s.svc.list_calendars():
        out.extend(s.svc.events_in_range(cal["href"], start_iso, end_iso))
    return out


def _instant(occ: dict[str, Any], s: Sweep) -> datetime | None:
    """An occurrence's start as an absolute instant.

    Never a string comparison against `now`: the column holds offset-aware,
    floating and date-only values in the same place, and only
    `scheduling.parse_event_time` knows which is which.
    """
    raw = occ.get("start")
    if not raw:
        return None
    zone = s.tz or timezone.utc
    try:
        return parse_event_time(raw, zone, naive_tz=s.tz)
    except (ValueError, TypeError):
        return None


def _parse_iso(raw) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


RULES: tuple[Rule, ...] = (
    Rule("daily_digest", default_on=True, silent=False, evaluate=_eval_digest),
    Rule("event_starting", default_on=True, silent=False, evaluate=_eval_event_starting),
    Rule("booking_created", default_on=True, silent=True, evaluate=_eval_booking_created),
    Rule("sync_stalled", default_on=True, silent=True, evaluate=_eval_sync_stalled),
)

assert tuple(r.id for r in RULES) == TRIGGERS, "RULES and TRIGGERS must stay in step"
