"""Slot math for client booking links — pure functions, no I/O.

Everything here works on tz-aware datetimes in the link's IANA timezone. The
cache stores event times as ISO strings that are naive-local when this app
wrote them (floating time) and offset-aware when another CalDAV client did;
``parse_event_time`` normalizes both into the link zone.

All-day events deliberately do NOT count as busy: in practice they are
annotations (birthdays, holidays, trip banners), and treating them as 24h busy
would silently zero out whole days of availability. An owner who wants to block
a day can add a timed event spanning it.

Neither do events the owner has marked FREE — iCalendar's
``TRANSP:TRANSPARENT``, which Apple Calendar spells "Busy/Free" and Thunderbird
"Show Time As". That is the property's entire purpose: RFC 5545 §3.8.2.7 defines
OPAQUE as "consumes time on a calendar" and TRANSPARENT as does not, and the
example the RFC itself gives for the latter is an event that "does not block
searches for busy time". A held slot, a tentative pencilling-in, a colleague's
FYI invite — the owner has already said these do not block, in the field their
other calendar clients put in front of them, and a booking page that ignored it
would be the one reader on the account overruling them.

The DEFAULT is OPAQUE and the decision lives in ``read.blocks_time``, not here:
absent is busy, an unrecognised value is busy, and a cache row written before
the column existed is busy. Every way of not knowing lands on "this might be a
real commitment", which is the only direction a page that hands availability to
anonymous visitors may be wrong in.
"""
from __future__ import annotations

import json
import logging
import re
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from icalendar.prop import vDuration

from .ical.read import advance

# `fullmatch` below, not `match`: Python's `$` also matches before a trailing
# newline, so "09:00-17:00\n" satisfied a pattern written to be exact.
_RANGE_RE = re.compile(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})")

log = logging.getLogger("tasksd.scheduling")

# A runaway backstop, not a page size. It exists because the candidate cursor
# advances by `duration`, so a non-positive one never terminates (see
# generate_slots); it was never meant to shape what a visitor sees.
#
# At 1000 it did exactly that: a 15-minute link with a wide weekly window ran out
# roughly a month into a 60-day horizon, and every day past that rendered as
# fully booked — indistinguishable, to someone looking at the page, from the
# owner genuinely having no time left.
#
# The bound is now set from what the schema actually permits: horizon_days caps
# at 180 and duration_minutes at 5, so 24h of availability every day is
# 288 * 180 = 51 840 slots. Rounding up leaves headroom no real link approaches,
# while still refusing to loop forever. If it ever engages, that is a truncation
# worth seeing in the log rather than inferring from a suspiciously empty page.
MAX_SLOTS = 60_000


class SlotTaken(Exception):
    """The requested slot is not (or no longer) available."""


@dataclass(frozen=True, order=True)
class Interval:
    start: datetime          # tz-aware, link timezone
    end: datetime


def parse_availability(raw: str | dict | None) -> dict[int, list[tuple[time, time]]]:
    """Validate and normalize the weekly availability JSON.

    Shape: ``{"0": ["09:00-12:00", "13:00-17:00"], ...}`` with keys "0" (Monday)
    through "6" (Sunday). Raises ValueError with a human-readable message on any
    malformed input (routes turn that into a 422).
    """
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("availability is not valid JSON") from None
    if not isinstance(raw, dict):
        raise ValueError("availability must be an object keyed by weekday")
    out: dict[int, list[tuple[time, time]]] = {}
    for key, ranges in raw.items():
        if str(key) not in ("0", "1", "2", "3", "4", "5", "6"):
            raise ValueError(f"availability key {key!r} is not a weekday 0-6 (0=Monday)")
        day = int(key)
        if not isinstance(ranges, list):
            raise ValueError(f"availability[{key}] must be a list of 'HH:MM-HH:MM' ranges")
        parsed: list[tuple[time, time]] = []
        for r in ranges:
            m = _RANGE_RE.fullmatch(r) if isinstance(r, str) else None
            if not m:
                raise ValueError(f"bad availability range {r!r} (expected 'HH:MM-HH:MM')")
            h1, m1, h2, m2 = (int(g) for g in m.groups())
            try:
                s, e = time(h1, m1), time(h2, m2)
            except ValueError:
                raise ValueError(f"bad availability range {r!r} (invalid time)") from None
            if s >= e:
                raise ValueError(f"availability range {r!r} must start before it ends")
            parsed.append((s, e))
        parsed.sort()
        for (_, prev_end), (nxt_start, _) in zip(parsed, parsed[1:]):
            if nxt_start < prev_end:
                raise ValueError(f"availability ranges overlap on weekday {day}")
        if parsed:
            out[day] = parsed
    return out


def parse_event_time(iso: str, tz: ZoneInfo, naive_tz: ZoneInfo | None = None) -> datetime:
    """An event ISO string as an aware datetime in the link zone.

    Aware strings (foreign CalDAV clients) name an instant and are converted
    into ``tz``. Naive ones are floating local wall time — and they are this
    app's OWN writes: `build_new_event` emits `DTSTART:20260810T090000` with no
    zone, and the cache stores it naive.

    Which zone that wall clock belongs to is the whole question. It used to be
    read as the *link's* zone, which is a free-text field the owner sets per
    link and may be anywhere. When the two differed, every floating event landed
    at the wrong absolute instant in the busy set — off by exactly the offset
    difference — so the owner's real appointment was advertised as free and an
    unauthenticated visitor could book straight over it, while the genuinely
    free hour was blocked. ``naive_tz`` is the zone the owner authors in (their
    home timezone setting); the link zone is left doing what it is for, the
    availability-window math and display.
    """
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is not None:
        return dt.astimezone(tz)
    return dt.replace(tzinfo=naive_tz or tz).astimezone(tz)


def busy_intervals(
    events: Iterable[dict], tz: ZoneInfo, *, naive_tz: ZoneInfo | None = None
) -> list[Interval]:
    """Blocking intervals from event DTOs (``TaskService.events_in_range`` shape,
    recurrences already expanded). Cancelled, all-day and FREE events don't block
    (see module docstring); a malformed event is skipped rather than failing the
    page.

    ``naive_tz``: the zone floating times are authored in — see
    ``parse_event_time``. Defaults to ``tz``, the historical behaviour."""
    out: list[Interval] = []
    for ev in events:
        try:
            if not ev.get("start") or ev.get("start_is_date") or ev.get("all_day"):
                continue
            if str(ev.get("status") or "").upper() == "CANCELLED":
                continue
            # `is False`, not falsy, and not `.get("busy", True)` either. The
            # DTO always carries this key — `_event_dto` and `_occurrence_dto`
            # both set it from `blocks_time`, which has already applied the
            # spec's default — so the only way to arrive here without one is a
            # dict some other caller built. Reading a MISSING key as free would
            # make every such caller's events silently bookable over; reading
            # only an explicit `False` as free keeps the fail-safe direction the
            # module docstring commits to.
            if ev.get("busy") is False:
                continue
            start = parse_event_time(ev["start"], tz, naive_tz)
            if ev.get("end"):
                end = parse_event_time(ev["end"], tz, naive_tz)
            elif ev.get("duration"):
                # `start + timedelta` adds to the NAIVE fields and re-derives the
                # offset, which is wall-clock arithmetic — the exact thing `pad`
                # and `generate_slots` both carry comments explaining they avoid.
                # Across spring-forward a two-hour commitment blocked one hour and
                # the tail was offered to an anonymous visitor; across fall-back a
                # thirty-minute one blocked ninety, withholding real availability.
                #
                # `advance` applies the two halves of the DURATION the way RFC 5545
                # §3.3.6 defines them rather than picking one: the weeks/days part
                # is nominal (P1D is "same time tomorrow", 23 real hours across the
                # spring-forward) and the time part is exact. Adding everything to
                # the instant would have fixed PT2H and broken P1D, which is the
                # same class of trade as the bug.
                end = advance(
                    start, ev["duration"], vDuration.from_ical(ev["duration"]))
            else:
                continue                       # zero-length: blocks nothing
            # Through `_u`, like every other comparison in this module — see its
            # docstring. Both operands share one ZoneInfo object, so CPython
            # compares their NAIVE fields: an event starting in the first pass of
            # the repeated hour and ending in the second has end-wall-clock <=
            # start-wall-clock, and this guard silently dropped it. It never
            # reached `merge`, so the busy set had no trace of it and the slot
            # sitting on top of it was offered — and `book_slot` re-validates
            # against the same busy set, so an anonymous POST wrote a second
            # event at the identical instant. This app's own bookings are in
            # scope: 30 minutes from 01:30 CDT is 06:30Z->07:00Z = 01:30 -> 01:00
            # local.
            if _u(end) > _u(start):
                out.append(Interval(start, end))
        except Exception:  # noqa: BLE001 — one bad event must not sink the page
            continue
    return merge(out)


def _u(dt: datetime) -> datetime:
    """The instant, as UTC.

    Every comparison in this module must go through here. Two datetimes that
    share one ZoneInfo object are compared by CPython on their NAIVE fields
    (`datetime_richcompare` short-circuits when `self.tzinfo is other.tzinfo`),
    so on a fall-back day the two passes of the repeated hour — different
    instants, identical wall clock — compare EQUAL. Since `tz` is built once per
    link and threaded through slot generation, busy parsing and booking, that is
    exactly the situation here.
    """
    return dt.astimezone(timezone.utc)


def merge(intervals: list[Interval]) -> list[Interval]:
    """Sorted, coalesced (overlapping/adjacent become one)."""
    out: list[Interval] = []
    for iv in sorted(intervals, key=lambda x: (_u(x.start), _u(x.end))):
        if out and _u(iv.start) <= _u(out[-1].end):
            if _u(iv.end) > _u(out[-1].end):
                out[-1] = Interval(out[-1].start, iv.end)
        else:
            out.append(iv)
    return out


def _widen(value: datetime, by: timedelta, tz) -> datetime:
    """`value` moved by `by` as an instant, back in `tz` — clamped, not raising.

    An interval near `datetime.min` or `datetime.max` runs out of representable
    range here, and OverflowError is caught by nothing on this path:
    `busy_intervals`' per-event guard has already returned, `generate_slots` does
    not guard, and app.py's handler taxonomy has no entry for it. One VEVENT with
    `DTSTART:00010101T000000` and a DURATION — which any client sharing the
    collection can PUT, and which `store.get_events_in_range` admits for EVERY
    window because its DURATION branch has no lower date bound — therefore 500'd
    `GET /api/public/booking/{token}` permanently, for everyone, until someone
    found and deleted the resource.

    Clamping is the right answer rather than dropping the interval: a busy block
    at the edge of representable time still blocks, and the buffer around it
    cannot extend past the edge anyway. The safe direction on a booking path is
    to keep blocking.
    """
    try:
        return (_u(value) + by).astimezone(tz)
    except (OverflowError, ValueError):
        edge = datetime.max if by > timedelta(0) else datetime.min
        try:
            return edge.replace(tzinfo=timezone.utc).astimezone(tz)
        except (OverflowError, ValueError):
            return value            # cannot even be re-expressed; leave it as it was


def pad(intervals: list[Interval], buffer_minutes: int) -> list[Interval]:
    """Each interval widened by the buffer on both sides, re-coalesced."""
    if not buffer_minutes:
        return merge(intervals)
    b = timedelta(minutes=buffer_minutes)
    # Widen the INSTANT, then derive the local value back. Subtracting from an
    # aware datetime adds to its naive fields and re-derives the offset, so a
    # buffer straddling a transition would otherwise be an hour out.
    return merge([
        Interval(_widen(iv.start, -b, iv.start.tzinfo),
                 _widen(iv.end, b, iv.end.tzinfo))
        for iv in intervals
    ])


def clip(intervals: list[Interval], window: Interval) -> list[Interval]:
    """Merged intervals cut down to the visible window."""
    out = []
    for iv in merge(intervals):
        s = iv.start if _u(iv.start) > _u(window.start) else window.start
        e = iv.end if _u(iv.end) < _u(window.end) else window.end
        if _u(s) < _u(e):
            out.append(Interval(s, e))
    return out


def _window_end_utc(day: date, w_end: time, tz: ZoneInfo) -> datetime:
    """The instant an availability window ends, never LATER than the owner said.

    `datetime.combine(day, w_end, tzinfo=tz)` resolves a wall-clock time that does
    not exist — the spring-forward gap — with PEP 495 fold=0, i.e. the
    PRE-transition offset. For an end time that is the instant of `w_end + gap`
    in post-transition local time, so the window GREW by the gap instead of
    shrinking, and slots were emitted after the owner's stated hours. The comment
    that used to sit here asserted the opposite; that is true only when the
    START falls in the gap.

    Where the gap sits in the last hour of the local day — America/Nuuk,
    America/Godthab and America/Scoresbysund move -02 to -01 at 01:00 UTC, so
    local 23:00:00-23:59:59 never happens — the over-run slot's local date is the
    NEXT day, and `book_slot` re-validates with `only_day=req.date()`, a
    different weekday whose availability does not contain it. So the public page
    advertised a slot and the booking was then refused with "that time is not
    available". Deterministic, not a race: an owner offering Saturday evenings
    ending 23:30 had 00:00 Sunday offered on their behalf.

    For a nonexistent wall time, fold=1 resolves with the POST-transition offset,
    which lands strictly BEFORE the transition — inside the real window. Taking
    it shrinks the window, which is the documented intent and the safe direction
    on the one unauthenticated path into the owner's calendar. An ordinary time
    is unaffected, and an ambiguous one (fall-back) keeps fold=0, the earlier
    pass, exactly as before.
    """
    local = datetime.combine(day, w_end, tzinfo=tz)
    as_instant = local.astimezone(timezone.utc)
    # A wall time exists iff it survives a round trip through UTC.
    if as_instant.astimezone(tz).replace(tzinfo=None) == local.replace(tzinfo=None):
        return as_instant

    # It does not, so the window really ends where the clock jumps: the
    # transition instant. The two folds bracket it exactly — fold=0 resolves with
    # the pre-transition offset and lands AT or AFTER the transition, fold=1 with
    # the post-transition offset and lands BEFORE it — so bisect between them for
    # the first instant carrying the new offset. Clamping to fold=1 alone would
    # be a whole gap too conservative and would throw away real availability the
    # owner offered (Nuuk 18:00-23:30 would stop at 22:00 instead of 23:00).
    lo = local.replace(fold=1).astimezone(timezone.utc)
    hi = as_instant
    after = hi.astimezone(tz).utcoffset()
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(tz).utcoffset() == after:
            hi = mid
        else:
            lo = mid
    return hi


def generate_slots(
    *,
    availability: dict[int, list[tuple[time, time]]],
    duration_minutes: int,
    busy: list[Interval],
    buffer_minutes: int,
    tz: ZoneInfo,
    now: datetime,
    min_notice_hours: int,
    horizon_days: int,
    only_day: date | None = None,
    max_slots: int = MAX_SLOTS,
) -> list[Interval]:
    """Bookable slots between ``now + min_notice`` and ``now + horizon_days``.

    Candidate starts step through each availability window in duration-sized
    increments anchored at the WINDOW start (a mid-window busy block must not
    shift later slots off the grid). A slot survives if it fits the window and
    misses every (buffer-padded) busy interval. ``only_day`` restricts output to
    one link-tz date (booking re-validation) while keeping the notice/horizon
    rules in force.
    """
    # The candidate cursor advances by `duration`, so a non-positive one never
    # advances and the loop below cannot terminate: the only early exit is the
    # max_slots cap, and that is unreachable whenever the window sits before
    # `open_from` — which it does for any default min_notice_hours. The caller
    # runs this inside the service lock, so the hang would take the whole app
    # with it and survive a restart, since the bad value is persisted. Every
    # HTTP path bounds this field already; this refuses to be the loop that
    # trusts them to have.
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")

    local_now = now.astimezone(tz)
    # Apply the notice as absolute time. `aware + timedelta` adds to the naive
    # fields AND resets fold to 0, so deriving this from the local value threw
    # away which pass of a repeated fall-back hour `now` was in — re-opening the
    # window an hour early no matter how the later comparison was written.
    open_from_utc = _u(now) + timedelta(hours=min_notice_hours)
    open_from = open_from_utc.astimezone(tz)
    last_day = local_now.date() + timedelta(days=horizon_days)
    blocked = pad(busy, buffer_minutes)
    # Converted ONCE, here, rather than per slot inside the overlap test — see
    # `_overlaps_any`. `pad` returns a merged list, so these are ascending and
    # searchable.
    blocked_starts = [_u(b.start) for b in blocked]
    blocked_ends = [_u(b.end) for b in blocked]
    duration = timedelta(minutes=duration_minutes)

    slots: list[Interval] = []
    day = max(open_from.date(), local_now.date())
    while day <= last_day and len(slots) < max_slots:
        if only_day is not None and day != only_day:
            day += timedelta(days=1)
            continue
        for w_start, w_end in availability.get(day.weekday(), []):
            # Constructing with tzinfo= resolves DST gaps forward (PEP 495) —
            # a spring-forward window shrinks rather than crashing.
            # Only the START is taken from here now; the end goes through
            # `_window_end_utc`, which does its own `datetime.combine`. Keeping
            # an `Interval` whose `.end` no longer described what the loop used
            # was the exact trap the comment it replaced warned about — and it
            # cost a second tz-aware construction per window per day on the
            # unauthenticated path.
            win_start = datetime.combine(day, w_start, tzinfo=tz)
            # Step in UTC, not wall clock. `aware_dt + timedelta` adds to the
            # naive fields and re-derives the offset, so across a transition a
            # "30-minute" slot is not 30 minutes: spring-forward produced one
            # whose end instant PRECEDED its start (and two slots naming the
            # same instant), and fall-back produced a 90-minute slot — on the
            # only unauthenticated write path into the owner's calendar. UTC has
            # no such discontinuity; the local values are derived back from it
            # for display and for matching a booking request.
            s_utc = win_start.astimezone(timezone.utc)
            # Not `win.end.astimezone(...)` — see `_window_end_utc` for the
            # spring-forward gap that made this window grow instead of shrink.
            end_utc = _window_end_utc(day, w_end, tz)
            while s_utc + duration <= end_utc:
                e_utc = s_utc + duration
                # Filter on the INSTANTS, never on local values. Both passes of a
                # repeated fall-back hour carry the same wall clock, so comparing
                # local values admitted slots already in the past and hid
                # genuinely free ones. The local Interval is derived only for a
                # slot that survives, so a rejected candidate costs no
                # conversions at all.
                if s_utc >= open_from_utc and not _overlaps_any(
                    s_utc, e_utc, blocked_starts, blocked_ends
                ):
                    slots.append(Interval(s_utc.astimezone(tz), e_utc.astimezone(tz)))
                    if len(slots) >= max_slots:
                        # Reaching the backstop means the answer is INCOMPLETE:
                        # every day after this one will read as fully booked. Say
                        # so, rather than leaving it to be inferred from a page
                        # that looks like a busy owner.
                        log.warning(
                            "slot generation hit the %d cap on %s — availability "
                            "past this point is truncated, not booked",
                            max_slots, day,
                        )
                        return slots
                s_utc += duration
        day += timedelta(days=1)
    return slots


def _overlaps_any(
    s_start: datetime, s_end: datetime,
    blocked_starts: list[datetime], blocked_ends: list[datetime],
) -> bool:
    """Does the slot [s_start, s_end) hit any blocked interval?

    Every argument is already a UTC INSTANT, and that is deliberate rather than
    incidental: on a fall-back day a busy block in the first pass of the repeated
    hour shares its wall clock with the second, so comparing local values blocked
    both. Taking instants in the signature is what stops a caller reintroducing
    that by passing `slot.start`.

    `blocked` comes from `merge`, so it is disjoint and sorted by start — which
    makes it sorted by end too — and the answer is a binary search rather than a
    scan. This used to take an `Interval` list and call `_u()` on both ends of
    every interval it walked, on every slot, with nothing hoisted: O(slots x
    intervals) `astimezone` calls on the ONE unauthenticated path into the
    owner's calendar, run inside the global service lock. A 15-minute link over a
    90-day horizon with an ordinary calendar measured 2.9 s of pure CPU per
    anonymous GET; the public limiter's 120 requests / 300 s is far more than
    enough to keep the lock permanently occupied.
    """
    # First index whose interval starts at or after the slot ends; everything
    # before it starts early enough to matter, and of those only the last can
    # still be running when the slot opens.
    i = bisect_left(blocked_starts, s_end)
    return i > 0 and blocked_ends[i - 1] > s_start
