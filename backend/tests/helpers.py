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
