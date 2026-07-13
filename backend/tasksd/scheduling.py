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
from datetime import date, datetime, time, timedelta
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


def merge(intervals: list[Interval]) -> list[Interval]:
    """Sorted, coalesced (overlapping/adjacent become one)."""
    out: list[Interval] = []
    for iv in sorted(intervals):
        if out and iv.start <= out[-1].end:
            if iv.end > out[-1].end:
                out[-1] = Interval(out[-1].start, iv.end)
        else:
            out.append(iv)
    return out


def pad(intervals: list[Interval], buffer_minutes: int) -> list[Interval]:
    """Each interval widened by the buffer on both sides, re-coalesced."""
    if not buffer_minutes:
        return merge(intervals)
    b = timedelta(minutes=buffer_minutes)
    return merge([Interval(iv.start - b, iv.end + b) for iv in intervals])


def clip(intervals: list[Interval], window: Interval) -> list[Interval]:
    """Merged intervals cut down to the visible window."""
    out = []
    for iv in merge(intervals):
        s, e = max(iv.start, window.start), min(iv.end, window.end)
        if s < e:
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
    local_now = now.astimezone(tz)
    open_from = local_now + timedelta(hours=min_notice_hours)
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
            s = win.start
            while s + duration <= win.end:
                slot = Interval(s, s + duration)
                if slot.start >= open_from and not _overlaps_any(slot, blocked):
                    slots.append(slot)
                    if len(slots) >= max_slots:
                        return slots
                s += duration
        day += timedelta(days=1)
    return slots


def _overlaps_any(slot: Interval, blocked: list[Interval]) -> bool:
    # `blocked` is merged/sorted; a linear scan with early exit is plenty for
    # the bounded horizon this runs over.
    for b in blocked:
        if b.start >= slot.end:
            return False
        if slot.start < b.end and slot.end > b.start:
            return True
    return False
