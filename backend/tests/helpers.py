"""Shared test helpers."""
from __future__ import annotations


def foreign_raw(uid: str, summary: str, *, extra: tuple[str, ...] = ()) -> bytes:
    """A raw VTODO as a *foreign* client would PUT it, always carrying an
    X-property we assert is never lost by our read/write path."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//foreign-client//EN",
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        "STATUS:NEEDS-ACTION",
        "X-FOREIGN-KEEP:do-not-drop",
        *extra,
        "END:VTODO",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()


def foreign_event_raw(
    uid: str,
    summary: str = "Event",
    *,
    dtstart: str = "20260106T090000Z",
    dtend: str | None = "20260106T093000Z",
    rrule: str | None = None,
    exdate: str | None = None,
    rdate: str | None = None,
    all_day: bool = False,
    vtimezone: tuple[str, ...] = (),
    extra: tuple[str, ...] = (),
    overrides: tuple[tuple[str, ...], ...] = (),
) -> bytes:
    """A raw VEVENT (optionally recurring, with EXDATE/RDATE and RECURRENCE-ID
    overrides) as a foreign client would PUT it. Carries an X-property we assert
    survives read/write. ``overrides`` is a tuple of line-tuples, each becoming an
    extra VEVENT sharing this UID (supply its own RECURRENCE-ID/DTSTART/…)."""
    def _dt(prop: str, value: str) -> str:
        # A "TZID=Area/City:..." value carries its own parameter; render with ';'.
        return f"{prop};{value}" if value.startswith("TZID=") else f"{prop}:{value}"

    if all_day:
        ds = [f"DTSTART;VALUE=DATE:{dtstart}"] + ([f"DTEND;VALUE=DATE:{dtend}"] if dtend else [])
    else:
        ds = [_dt("DTSTART", dtstart)] + ([_dt("DTEND", dtend)] if dtend else [])
    master = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        *ds,
        *([f"RRULE:{rrule}"] if rrule else []),
        *([f"EXDATE:{exdate}"] if exdate else []),
        *([f"RDATE:{rdate}"] if rdate else []),
        "X-FOREIGN-KEEP:do-not-drop",
        *extra,
        "END:VEVENT",
    ]
    override_blocks: list[str] = []
    for ov in overrides:
        override_blocks += ["BEGIN:VEVENT", f"UID:{uid}", *ov, "END:VEVENT"]
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//foreign-client//EN",
        *vtimezone,
        *master,
        *override_blocks,
        "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode()
