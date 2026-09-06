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

TWO TIERS, AND THE DIFFERENCE IS THE DEFAULT. The rules above ship ON: they are
the four that clear the bar for an owner who has said nothing. Everything below
`# ── opt-in ──` ships OFF, and each one was argued against on this page before
it was written — "task due soon" is noise or stress, "you're overdue" is a pager
loop, "you haven't planned today" is the app asking for attention on its own
behalf. Those arguments still stand, and they are what the defaults encode.

What they do not do is decide for someone who disagrees. An owner who wants a
07:30 nudge that today is unplanned knows their own working habits better than
this file does, and a default is a starting position rather than a verdict. So
the cut rules are here, off, each with the case against it written beside it so
the choice is informed rather than blind — which is the honest way to hold both
positions at once: the app does not think you need this, and the app is not the
one living your day.

THE ADMISSION TEST FOR A NEW RULE. Write its `dedupe_key` first. If you cannot
express it as something that STOPS EXISTING — a day key, a start instant, a
booking id — then the condition is standing, it will re-qualify on every sweep,
and whatever dedupe policy you pick to stop it repeating is arbitrary. The
answer for a standing condition is a WALL-CLOCK rule: sample it once a day at an
hour the owner set, keyed on the day. That is what every opt-in rule below does,
and it is why they can be loud without a quiet-hours setting — an hour the owner
chose cannot land at 3am by accident.

LOUD AND QUIET, RESTATED FOR THE OPT-IN TIER. Every rule below is either
wall-clock (fires at an hour the owner set, so it may buzz) or silent. Nothing
event-driven and loud was added except `task_due_soon`, whose timing comes from
the owner's own deadline — the same category as `event_starting`. The property
that keeps quiet hours unnecessary therefore survives the whole tier.

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
    # On by default.
    "daily_digest",
    "event_starting",
    "item_reminder",
    "booking_created",
    "sync_stalled",
    # Off by default — see the docstring's two-tier note.
    "task_due_soon",
    "task_overdue",
    "day_unplanned",
    "capacity_overcommitted",
    "day_not_shut_down",
    "habits_outstanding",
    "booking_link_broken",
    "sync_recovered",
)

DEFAULT_DIGEST_TIME = "07:30"
DEFAULT_EVENT_LEAD_MINUTES = 10
# The evening rules' hour. A second wall clock rather than a third and a fourth:
# every opt-in rule that samples a standing condition fires at either the morning
# hour or this one, so the whole tier costs two settings instead of eight.
DEFAULT_EVENING_TIME = "21:00"
# The blanket task lead. Longer than the meeting default because a deadline is
# not an appointment — you cannot walk into it, you have to have started.
DEFAULT_TASK_LEAD_MINUTES = 30

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

# The longest lead a per-item reminder may carry: a week. Past that the
# reminder is about a different day than the one it names, and the scan
# window it implies stops being cheap.
MAX_REMINDER_MINUTES = 7 * 24 * 60

# How many titles a list-shaped message names before it stops naming them. The
# same reasoning as the digest's caps: past a handful the message is a report,
# and a report is something you open the app for.
MAX_NAMED = 5

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


def evening_time(prefs: dict[str, Any]) -> tuple[int, int]:
    """The hour the evening rules fire at, as (hour, minute)."""
    return _read_time(prefs, "notify_evening_time", DEFAULT_EVENING_TIME)


def _read_time(prefs: dict[str, Any], key: str, fallback: str) -> tuple[int, int]:
    raw = prefs.get(key)
    if not isinstance(raw, str):
        raw = fallback
    try:
        hh, _, mm = raw.partition(":")
        h, m = int(hh), int(mm)
    except (TypeError, ValueError):
        return _hhmm(fallback)
    return (h, m) if (0 <= h <= 23 and 0 <= m <= 59) else _hhmm(fallback)


def wall_clock_due(s: "Sweep", hour: int, minute: int) -> bool:
    """Is this the sweep that a rule scheduled for `hour:minute` fires on?

    `fire <= now < fire + DIGEST_STALE_AFTER` — the closing window every rule in
    this file uses, in its wall-clock form. Two consequences worth stating:

      * A restart inside the window still fires (the ledger stops a second
        send), which is why the loop sweeps before its first wait.
      * A window that closed while the box was down never fires and leaves no
        row. A nudge to plan your day, delivered at four in the afternoon, is
        worse than no nudge.

    Returns False with no home timezone, for every wall-clock rule and not just
    the digest: an hour resolved against the server clock — UTC in the ordinary
    deploy — is not the hour anyone chose.
    """
    if s.tz is None:
        return False
    local = s.local_now
    fire = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return fire <= local < fire + DIGEST_STALE_AFTER


def task_lead(prefs: dict[str, Any]) -> timedelta:
    """The blanket lead for a task deadline, for owners who opt into one."""
    raw = prefs.get("notify_task_lead_minutes")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raw = DEFAULT_TASK_LEAD_MINUTES
    return timedelta(minutes=max(3, min(raw, 1440)))


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
    # `wall_clock_due` refuses outright with no home timezone — see its note.
    if not wall_clock_due(s, *digest_time(s.prefs)):
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
        counts.append(f"{len(overdue)} overdue")
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
            # Filtered like the timed branch below, which this one was not:
            # `_occurrences` widens the SQL window by a day each side and
            # leaves the precise cut to the caller, and an all-day row was
            # appended unconditionally — so yesterday's (with the DTEND every
            # client writes), tomorrow's and the day after's all landed under
            # today's headline and in its count. A DATE start parses to local
            # midnight; DTEND is exclusive and absent means one day. The
            # overlap test rather than "starts today" keeps a three-day trip
            # in the digest on its middle day, which is when the owner most
            # wants reminding of it.
            first = _instant(occ, s)
            if first is None:
                continue
            first = first.astimezone(s.tz) if s.tz else first
            last = _instant({"start": occ.get("end")}, s) if occ.get("end") else None
            last = (last.astimezone(s.tz) if s.tz else last) if last else first + timedelta(days=1)
            if first < end_of_day and last > start_of_day:
                out.append((start_of_day, occ.get("summary") or "(untitled)", True))
            continue
        when = _instant(occ, s)
        if when is not None and start_of_day <= when.astimezone(s.tz) < end_of_day:
            out.append((when.astimezone(s.tz), occ.get("summary") or "(untitled)", False))
    # All-day first, then by clock — the order the day is actually lived in.
    out.sort(key=lambda row: (not row[2], row[0]))
    return out


def _todays_tasks(s: Sweep) -> tuple[list[str], list[str]]:
    """(titles due today, titles already overdue).

    "Overdue" is `due.due_parts`, the app's own rule, imported rather than
    re-derived — the connector and `frontend/src/util.ts` answer with the same
    two numbers and a third answer here would be a third number on screen.
    """
    from ..service import _due_day

    now_epoch = s.now.timestamp()
    due_today: list[str] = []
    overdue: list[str] = []
    # `include_parked=False`: a digest counting work the owner deliberately set
    # aside would report a backlog they have already dealt with, every morning,
    # which is the number the parking file exists to move.
    for lst in s.svc.list_lists():
        for task in s.svc.list_tasks(lst["href"], include_done=False, include_parked=False):
            parts = due_rules.due_parts(task.get("due"), s.tz)
            if parts is None:
                continue
            if parts[1] < now_epoch:
                overdue.append(task.get("summary") or "(untitled)")
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
        # An event the owner set their own lead on belongs to `item_reminder`.
        # Without this both rules qualify and the same meeting is announced
        # twice, at two different times — the blanket rule at the global lead
        # and the explicit one at theirs.
        if occ.get("notify_minutes_before") is not None:
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


# ── item_reminder ────────────────────────────────────────────────────────────

def _eval_item_reminder(s: Sweep) -> list[Pending]:
    """"Notify me N minutes before this one", set on a single task or event.

    This is the rule that lets task deadlines earn a notification at all. A
    blanket "task due soon" was rejected outright and the reasoning stands — a
    task due at 17:00 is either something you already knew about, in which case
    the ping is noise, or something you cannot do in thirty minutes, in which
    case it is stress. What changes here is who is asking. A lead the owner set
    on ONE task is not the app guessing that a deadline is worth an
    interruption; it is the owner saying this one is, and an explicit request
    outranks the interruption bar every time.

    That is also why the field is per item and has no global default for tasks:
    a default would quietly recreate the blanket rule, and the whole reason this
    is acceptable is that nothing fires unless someone asked for it.
    """
    out: list[Pending] = []
    horizon = timedelta(minutes=MAX_REMINDER_MINUTES)

    for occ in _occurrences(s, s.now - timedelta(days=1), s.now + horizon + timedelta(days=1)):
        lead = _reminder_lead(occ.get("notify_minutes_before"))
        if lead is None or occ.get("status") == "CANCELLED":
            continue
        start = _instant(occ, s)
        if start is None:
            continue
        pending = _reminder_pending(
            s, start, lead,
            summary=occ.get("summary") or "(untitled)",
            key=f"{occ.get('calendar')}|{occ.get('master_uid') or occ.get('uid')}",
            all_day=bool(occ.get("all_day")),
        )
        if pending:
            out.append(pending)

    # PARKED WORK IS STILL REMINDED ABOUT, and that is the one place in this
    # module where it is. The README's rule for `item_reminder` is that a lead
    # the owner set on one item "is you asking rather than the app guessing, and
    # an explicit request outranks any bar the app would otherwise apply" —
    # parking is a bar the app applies to its own views, not a withdrawal of a
    # request. Setting something aside and having asked to be told about it are
    # compatible ("not now, but tell me on the 3rd"), and the way to stop the
    # reminder is to clear the reminder.
    for lst in s.svc.list_lists():
        for task in s.svc.list_tasks(lst["href"], include_done=False):
            lead = _reminder_lead(task.get("notify_minutes_before"))
            if lead is None:
                continue
            # A recurring VTODO's `items.due` is the MASTER's deadline and
            # nothing in this codebase expands a VTODO recurrence set
            # (`recur.expand_occurrences` is VEVENT-only, one caller). Reminding
            # off it would fire once on a date that stopped being true months
            # ago, and never again.
            if task.get("has_rrule"):
                continue
            parts = due_rules.due_parts(task.get("due"), s.tz)
            if parts is None:
                continue
            due_at = datetime.fromtimestamp(parts[0], tz=timezone.utc)
            pending = _reminder_pending(
                s, due_at, lead,
                summary=task.get("summary") or "(untitled)",
                key=f"{lst['href']}|{task.get('uid')}",
                all_day=bool(task.get("due_is_date")),
                due=True,
            )
            if pending:
                out.append(pending)
    return out


def _reminder_lead(raw) -> timedelta | None:
    """The stored lead, or None when this item carries no reminder."""
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    if raw < 0 or raw > MAX_REMINDER_MINUTES:
        return None
    return timedelta(minutes=raw)


def _reminder_pending(
    s: Sweep, moment: datetime, lead: timedelta, *,
    summary: str, key: str, all_day: bool, due: bool = False,
    trigger: str = "item_reminder",
) -> Pending | None:
    """The shared window and wording for both halves of the rule.

    `fire <= now < moment` — the same closing window every other rule uses. The
    upper bound is the moment itself: once it has passed, saying "in -3 minutes"
    is noise, and nothing is claimed, so a later restart cannot resurrect it.
    """
    delta = moment - s.now
    if not (timedelta(0) <= delta <= lead):
        return None
    minutes = max(0, int(delta.total_seconds() // 60))
    local = moment.astimezone(s.tz) if s.tz else moment
    # An all-day deadline has no clock to name, and "due at 12:00 AM" is a time
    # nobody set — it is midnight because a date has to resolve to something.
    when = local.strftime("%a %-d %b") if all_day else _fmt_time(local, s.prefs)
    verb = "due" if due else "at"
    return Pending(
        trigger,
        # The moment, not the lead: moving the item is a new occasion and
        # re-arms, and changing the lead on an item whose reminder already went
        # out does not send a second one.
        f"{key}|{moment.astimezone(timezone.utc).isoformat()}",
        f"{summary} {verb} {when} — in {minutes} min.",
        silent=False,
    )


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


# ── opt-in ───────────────────────────────────────────────────────────────────
#
# Everything below ships OFF. Each was argued against before it was written, and
# the argument is kept beside it rather than deleted — a rule you switch on
# should come with the reason the app did not switch it on for you.


def _eval_task_due_soon(s: Sweep) -> list[Pending]:
    """A blanket lead on every timed task deadline.

    THE CASE AGAINST, which is why it is off: a task due at 17:00 is either
    something you already knew about, in which case the ping is noise, or
    something you cannot do in thirty minutes, in which case it is stress. The
    per-item `item_reminder` exists precisely so a deadline can be made to notify
    without every deadline doing so.

    THE CASE FOR: some people work from a deadline list and want the whole list
    to speak. That is a working style, not an error, and this file is not
    entitled to an opinion about it.

    Two exclusions are not preferences and cannot be turned off:

      * a recurring VTODO — `items.due` is the MASTER's deadline and nothing in
        this codebase expands a VTODO recurrence set, so this would fire once on
        a date that stopped being true months ago and never again;
      * an all-day deadline — it names a day, not a clock, so "in 30 minutes"
        would be measured against a midnight nobody chose. Those are what the
        digest's "due today" line is for.
    """
    lead = task_lead(s.prefs)
    out: list[Pending] = []
    # `include_parked=False`, unlike `_eval_item_reminder` above: this rule is
    # the app guessing that a deadline is worth interrupting for, and a deadline
    # on work the owner has set aside is the weakest guess it could make.
    for lst in s.svc.list_lists():
        for task in s.svc.list_tasks(lst["href"], include_done=False, include_parked=False):
            if task.get("has_rrule") or task.get("due_is_date"):
                continue
            # An item carrying its own lead belongs to `item_reminder`; without
            # this the same task is announced twice, at two different times.
            if task.get("notify_minutes_before") is not None:
                continue
            parts = due_rules.due_parts(task.get("due"), s.tz)
            if parts is None:
                continue
            due_at = datetime.fromtimestamp(parts[0], tz=timezone.utc)
            pending = _reminder_pending(
                s, due_at, lead,
                summary=task.get("summary") or "(untitled)",
                key=f"{lst['href']}|{task.get('uid')}",
                all_day=False, due=True, trigger="task_due_soon",
            )
            if pending:
                out.append(pending)
    return out


def _eval_task_overdue(s: Sweep) -> list[Pending]:
    """How much is past its deadline, once a day at the morning hour.

    THE CASE AGAINST: "this task is overdue" is true on every sweep from now
    until the heat death of the task list, so any implementation is really a
    dedupe policy wearing a trigger's clothes. This one picks the least
    arbitrary policy available — sample it once a day, at an hour the owner set,
    keyed on the day — and reports a COUNT rather than pretending each task is
    news. The digest already carries the same number as one line, which is why
    this is off: turning it on means wanting the number badly enough to be
    interrupted by it on a day you did not open the app.
    """
    if not wall_clock_due(s, *digest_time(s.prefs)):
        return []
    _, overdue = _todays_tasks(s)
    if not overdue:
        return []
    lines = [f"{len(overdue)} task{'s' if len(overdue) != 1 else ''} overdue."]
    lines += [f"· {t}" for t in overdue[:MAX_NAMED]]
    if len(overdue) > MAX_NAMED:
        lines.append(f"+{len(overdue) - MAX_NAMED} more")
    return [Pending("task_overdue", s.day, "\n".join(lines), silent=False)]


def _eval_day_unplanned(s: Sweep) -> list[Pending]:
    """Today has no committed plan, at the morning hour.

    THE CASE AGAINST: the owner knows they have not planned today. Sending a
    message about it is the app asking for attention on its own behalf rather
    than giving them something, and it is the single most likely message to be
    muted — which then takes the digest down with it.

    THE CASE FOR: a ritual that only works when you remember to perform it is a
    ritual with a reliability problem, and an alarm clock is not an insult.
    """
    if not wall_clock_due(s, *digest_time(s.prefs)):
        return []
    plan = s.svc.open_day(s.day, create=False)
    # `create=False` is mandatory and not a default worth trusting to a caller:
    # create=True would BUILD the snapshot, so the rule that reports the day is
    # unplanned would be the thing that planned it.
    if plan.get("committed_at"):
        return []
    return [Pending("day_unplanned", s.day, "Today isn't planned yet.", silent=False)]


def _eval_capacity_overcommitted(s: Sweep) -> list[Pending]:
    """Today's plan runs past the length the owner said they would work.

    THE CASE AGAINST: the number is already on the screen where the planning
    happens, in words, before the day starts. A message about a number you are
    looking at while you create the condition is not information.

    The one guard that is NOT optional: an account that has never stated a
    capacity is told nothing at all. `plan["capacity"]` is None for those, and
    inventing an eight-hour day for someone is the thing this app must not do —
    see `service._effective_capacity`. Zero is a real capacity ("not working
    today") and is honoured as one.
    """
    if not wall_clock_due(s, *digest_time(s.prefs)):
        return []
    plan = s.svc.open_day(s.day, create=False)
    capacity = plan.get("capacity")
    if not isinstance(capacity, int):
        return []
    planned = sum(
        e.get("estimate_minutes") or 0
        for e in plan.get("entries") or []
        # Dropped and MOVED rows are out, exactly as the app's own strip has
        # them: declining something, or doing it on Thursday, is how a day gets
        # back under its capacity.
        if not e.get("dropped_at") and not e.get("rolled_to") and not e.get("done_at")
    )
    if planned <= capacity:
        return []
    over = planned - capacity
    return [Pending(
        "capacity_overcommitted", s.day,
        f"Today's plan runs {_minutes(over)} past the {_minutes(capacity)} "
        f"you said you'd work.",
        silent=False,
    )]


def _eval_day_not_shut_down(s: Sweep) -> list[Pending]:
    """The day was planned and never closed, at the evening hour.

    THE CASE AGAINST: habit-formation, not information — it tells the owner
    nothing they do not know.

    Only for a day that was actually PLANNED. Nagging someone to shut down a day
    they never opened is asking them to perform a ritual for its own sake, which
    is the exact failure the case against names.
    """
    if not wall_clock_due(s, *evening_time(s.prefs)):
        return []
    plan = s.svc.open_day(s.day, create=False)
    if not plan.get("planned") or plan.get("shutdown_at"):
        return []
    return [Pending("day_not_shut_down", s.day,
                    "Today hasn't been shut down.", silent=False)]


def _eval_habits_outstanding(s: Sweep) -> list[Pending]:
    """Habits still open on today's plan, at the evening hour.

    THE CASE AGAINST, and it is the strongest one on this page: the app's own
    position is that a habit is "never coloured as a failure", that nothing here
    scores the day, and that a weekly count is over the occurrences that EXIST so
    days you never opened are not counted against you. A message that lists what
    you have not done is in tension with all three, and it is the rule most
    likely to make someone feel worse for having a habit than for not having one.

    So the wording carries no verdict — it names what is left, in the same voice
    the day itself uses, and never a streak, a percentage or a count of misses.
    And it fires only on a day whose plan EXISTS: a habit occurrence lives
    nowhere but in a `day_plan` row, so on a day nobody opened there is nothing
    to be outstanding and nothing the owner could tick if there were.
    """
    if not wall_clock_due(s, *evening_time(s.prefs)):
        return []
    plan = s.svc.open_day(s.day, create=False)
    if not plan.get("planned"):
        return []
    left = [
        e.get("title") or "(untitled)"
        for e in plan.get("entries") or []
        if e.get("kind") == "habit"
        and not e.get("done_at") and not e.get("dropped_at") and not e.get("rolled_to")
    ]
    if not left:
        return []
    head = f"{len(left)} habit{'s' if len(left) != 1 else ''} left today."
    return [Pending("habits_outstanding", s.day,
                    "\n".join([head] + [f"· {t}" for t in left[:MAX_NAMED]]),
                    silent=False)]


def _eval_booking_link_broken(s: Sweep) -> list[Pending]:
    """An enabled booking link pointing at a calendar that is gone.

    Deleting a calendar IN THE APP auto-disables its links, so this can only
    happen the other way round: the collection left the wire from another client,
    and a public URL the owner has already shared now answers with nothing behind
    it. Silent — it is a thing to fix at a keyboard.

    Sampled daily rather than on the change, because there is no change to hang
    it on: the link did not move, the calendar did.
    """
    broken = [link for link in s.svc.list_booking_links()
              if link.get("enabled") and link.get("calendar_missing")]
    if not broken:
        return []
    names = ", ".join(sorted({(link.get("title") or "?") for link in broken}))
    return [Pending("booking_link_broken", s.day,
                    f"Booking link{'s' if len(broken) != 1 else ''} pointing at a "
                    f"calendar that no longer exists — {names}. Anyone with the "
                    f"link sees an error.", silent=True)]


def _eval_sync_recovered(s: Sweep) -> list[Pending]:
    """Sync is working again, after a `sync_stalled` message went out.

    THE CASE AGAINST: a second message to retract the first is exactly the
    pattern that trains people to stop reading — every alert now costs two
    interruptions and the second one carries no action.

    THE CASE FOR: an owner who acted on the first one wants to know their fix
    took, without opening the app to check.

    Keyed on the outage it closes, not on the day: the `claimed_at` of the
    `sync_stalled` row that is being answered. A flapping server therefore
    produces one down and one up per outage rather than a pair every day, and a
    recovery can never be announced for an outage that was never announced.
    """
    if s.svc.sync_health():
        return []
    last = s.svc.notifications(_last_stall)
    if last is None:
        return []
    return [Pending("sync_recovered", last,
                    "Smylte sync is working again.", silent=True)]


def _last_stall(conn):
    """The `claimed_at` of the most recent sync_stalled delivery, or None."""
    row = conn.execute(
        "SELECT claimed_at FROM notification_deliveries "
        "WHERE trigger='sync_stalled' ORDER BY claimed_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _minutes(total: int) -> str:
    """A duration as the app writes one: "45 min", "2h", "1h 30m"."""
    hours, mins = divmod(max(0, total), 60)
    if not hours:
        return f"{mins} min"
    return f"{hours}h" if not mins else f"{hours}h {mins}m"


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
    Rule("item_reminder", default_on=True, silent=False, evaluate=_eval_item_reminder),
    Rule("booking_created", default_on=True, silent=True, evaluate=_eval_booking_created),
    Rule("sync_stalled", default_on=True, silent=True, evaluate=_eval_sync_stalled),
    # ── off by default ───────────────────────────────────────────────────────
    Rule("task_due_soon", default_on=False, silent=False, evaluate=_eval_task_due_soon),
    Rule("task_overdue", default_on=False, silent=False, evaluate=_eval_task_overdue),
    Rule("day_unplanned", default_on=False, silent=False, evaluate=_eval_day_unplanned),
    Rule("capacity_overcommitted", default_on=False, silent=False,
         evaluate=_eval_capacity_overcommitted),
    Rule("day_not_shut_down", default_on=False, silent=False,
         evaluate=_eval_day_not_shut_down),
    Rule("habits_outstanding", default_on=False, silent=False,
         evaluate=_eval_habits_outstanding),
    Rule("booking_link_broken", default_on=False, silent=True,
         evaluate=_eval_booking_link_broken),
    Rule("sync_recovered", default_on=False, silent=True, evaluate=_eval_sync_recovered),
)

assert tuple(r.id for r in RULES) == TRIGGERS, "RULES and TRIGGERS must stay in step"
