"""Slot math for client booking links — pure functions, no I/O.

Everything here works on tz-aware datetimes in the link's IANA timezone. The
cache stores event times as ISO strings that are naive-local when this app
wrote them (floating time) and offset-aware when another CalDAV client did;
``parse_event_time`` normalizes both into the link zone.

All-day events deliberately do NOT count as busy: in practice they are
annotations (birthdays, holidays, trip banners), and treating them as 24h busy
would silently zero out whole days of availability. An owner who wants to block
a day can add a timed event spanning it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from icalendar.prop import vDuration

_RANGE_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


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
            m = _RANGE_RE.match(r) if isinstance(r, str) else None
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


def parse_event_time(iso: str, tz: ZoneInfo) -> datetime:
    """An event ISO string as an aware datetime in the link zone: naive strings
    (floating local, this app's own writes) are stamped with the link zone;
    aware ones (foreign CalDAV clients) are converted into it."""
    dt = datetime.fromisoformat(iso)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def busy_intervals(events: Iterable[dict], tz: ZoneInfo) -> list[Interval]:
    """Blocking intervals from event DTOs (``TaskService.events_in_range`` shape,
    recurrences already expanded). Cancelled and all-day events don't block (see
    module docstring); a malformed event is skipped rather than failing the page."""
    out: list[Interval] = []
    for ev in events:
        try:
            if not ev.get("start") or ev.get("start_is_date") or ev.get("all_day"):
                continue
            if str(ev.get("status") or "").upper() == "CANCELLED":
                continue
            start = parse_event_time(ev["start"], tz)
            if ev.get("end"):
                end = parse_event_time(ev["end"], tz)
            elif ev.get("duration"):
                end = start + vDuration.from_ical(ev["duration"])
            else:
                continue                       # zero-length: blocks nothing
            if end > start:
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


def pad(intervals: list[Interval], buffer_minutes: int) -> list[Interval]:
    """Each interval widened by the buffer on both sides, re-coalesced."""
    if not buffer_minutes:
        return merge(intervals)
    b = timedelta(minutes=buffer_minutes)
    # Widen the INSTANT, then derive the local value back. Subtracting from an
    # aware datetime adds to its naive fields and re-derives the offset, so a
    # buffer straddling a transition would otherwise be an hour out.
    return merge([
        Interval((_u(iv.start) - b).astimezone(iv.start.tzinfo),
                 (_u(iv.end) + b).astimezone(iv.end.tzinfo))
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
    max_slots: int = 1000,
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
            win = Interval(
                datetime.combine(day, w_start, tzinfo=tz),
                datetime.combine(day, w_end, tzinfo=tz),
            )
            # Step in UTC, not wall clock. `aware_dt + timedelta` adds to the
            # naive fields and re-derives the offset, so across a transition a
            # "30-minute" slot is not 30 minutes: spring-forward produced one
            # whose end instant PRECEDED its start (and two slots naming the
            # same instant), and fall-back produced a 90-minute slot — on the
            # only unauthenticated write path into the owner's calendar. UTC has
            # no such discontinuity; the local values are derived back from it
            # for display and for matching a booking request.
            s_utc = win.start.astimezone(timezone.utc)
            end_utc = win.end.astimezone(timezone.utc)
            while s_utc + duration <= end_utc:
                slot = Interval(s_utc.astimezone(tz), (s_utc + duration).astimezone(tz))
                # Filter on the INSTANT (`s_utc`), never on `slot.start`. Both
                # passes of a repeated fall-back hour carry the same wall clock,
                # so comparing local values admitted slots already in the past
                # and hid genuinely free ones.
                if s_utc >= open_from_utc and not _overlaps_any(slot, blocked):
                    slots.append(slot)
                    if len(slots) >= max_slots:
                        return slots
                s_utc += duration
        day += timedelta(days=1)
    return slots


def _overlaps_any(slot: Interval, blocked: list[Interval]) -> bool:
    # `blocked` is merged/sorted; a linear scan with early exit is plenty for
    # the bounded horizon this runs over. Compared as instants: on a fall-back
    # day a busy block in the first pass of the repeated hour shares its wall
    # clock with the second, so local comparison blocked both.
    s_start, s_end = _u(slot.start), _u(slot.end)
    for b in blocked:
        b_start, b_end = _u(b.start), _u(b.end)
        if b_start >= s_end:
            return False
        if s_start < b_end and s_end > b_start:
            return True
    return False
