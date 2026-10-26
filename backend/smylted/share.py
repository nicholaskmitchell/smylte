"""What a share says, as data. Pure: no DB, no clock, no I/O.

A share is read by somebody else, so every decision about what may leave the
server is made here, in functions that take plain values and return plain values:
a title bounded and stripped of control characters, a colour that is a hex
literal or nothing, a time that is a UTC instant or a date, a row key that says
nothing about the row it names. Keeping them apart from the service means the
rules a stranger's page depends on can be tested without a Radicale or a clock,
and cannot quietly pick up a second source of truth by reaching for one.

The only import from the rest of the app is `plain`, the display path's text
guard: one definition of "safe to draw" for every surface that shows an owner's
words to someone who is not the owner.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .display.frame import plain

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")      # token_urlsafe(32), always 43 chars

# The horizons an owner may pick for a share, in days from the owner's today.
# Written out rather than bounded, so a PATCH cannot ask a public route to
# expand a year of recurrences on every poll.
HORIZONS = (1, 7, 14, 28)
DEFAULT_HORIZON = 7

MAX_TASKS_PER_LIST = 200
MAX_EVENTS = 500
MAX_DEPTH = 3
TITLE_CHARS = 200

POLL_LIVE_S = 15                                  # focus state not idle
POLL_IDLE_S = 30
PAUSED_IDLE_S = 30 * 60                           # paused longer than this reads as idle
BETWEEN_IDLE_S = 15 * 60                          # over longer than this reads as idle

FOCUS_PHASES = ("focus", "break", "long_break")

# It lands in a style attribute on the viewer's page, so anything that is not a
# plain hex colour is dropped rather than escaped.
_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")

# A CLASS property at the start of a content line, after unfolding. There is no
# end anchor: the value group runs to the end of the line, and `$` in multiline
# mode does not match before the `\r` of a CRLF line ending, which is what a
# CalDAV server stores.
_CLASS_RE = re.compile(r"(?im)^CLASS(?:;[^:\r\n]*)?:([^\r\n]*)")
_UNFOLD_RE = re.compile(r"\r?\n[ \t]")

IDLE = {"state": "idle", "phase": None, "phase_length_s": None,
        "ends_at": None, "remaining_s": None}


def stamp(moment: datetime) -> str:
    """A UTC millisecond 'Z' stamp. The same shape as `service._stamp_at`,
    written out here because the service imports this module."""
    return moment.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def title(value: str | None) -> str:
    return plain(value, limit=TITLE_CHARS)


def color(value: str | None) -> str | None:
    return value if value and _COLOR_RE.fullmatch(value) else None


def is_private(raw: bytes | str | None) -> bool:
    """Whether a resource carries a CLASS other than PUBLIC anywhere in it.

    Coarse on purpose. One non-PUBLIC CLASS on the master or on any override
    marks the whole resource, so every occurrence of an event and the task itself
    are sent without a title. The alternative, resolving which component a given
    occurrence came from, is a second reading of the recurrence rules in the one
    place a mistake shows somebody else's private appointment. An empty value,
    an x-name and a vendor value all count as private: only an explicit PUBLIC
    is shown.
    """
    if not raw:
        return False
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = _UNFOLD_RE.sub("", text)
    return any(m.group(1).strip().upper() != "PUBLIC" for m in _CLASS_RE.finditer(text))


def instant(value: str | None, *, is_date: bool, zone: ZoneInfo | None) -> str | None:
    """A stored time as a UTC instant ('Z') or a bare date, or None.

    A floating time has no zone of its own, so it is read in the owner's home
    zone here on the server, where that zone is known; the viewer only ever sees
    the resulting instant and never learns the zone. With no home zone it falls
    back to the server's, the rule `_today` and `_event_day` already follow.
    """
    if not value:
        return None
    if is_date or "T" not in value:
        return value[:10]
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=zone) if zone else moment.astimezone()
        return stamp(moment)
    except (ValueError, OverflowError, OSError):
        return None


def row_key(share_id: str, entry_id: str) -> str:
    """An opaque, stable name for a plan row. The entry id is a plan-internal
    handle, so the viewer gets a hash of it salted with the share's own id: the
    same row reads the same across polls, and nothing can be recovered from it."""
    return hashlib.sha256(f"{share_id}:{entry_id}".encode()).hexdigest()[:16]


def tree(tasks: Sequence[Mapping]) -> list[tuple[Mapping, int]]:
    """Open tasks in list order, each with its nesting depth.

    A parent is looked up ONLY among the rows handed in. A subtask whose parent
    is closed, parked, in another collection or itself is a root: it is open, so
    it stays visible, and a parent outside the share is never read, so its title
    cannot surface as an indent. Rows no root reaches are pure RELATED-TO cycles;
    they are appended flat rather than dropped, since each of them is open.
    """
    uids = {t["uid"] for t in tasks}
    children: dict[str, list[int]] = {}
    roots: list[int] = []
    for i, t in enumerate(tasks):
        parent = t["related_parent"]
        if not parent or parent == t["uid"] or parent not in uids:
            roots.append(i)
        else:
            children.setdefault(parent, []).append(i)
    out: list[tuple[Mapping, int]] = []
    seen: set[int] = set()
    # Reversed on the way in, so the stack pops in input order.
    stack = [(i, 0) for i in reversed(roots)]
    while stack:
        i, level = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        out.append((tasks[i], min(level, MAX_DEPTH)))
        stack.extend((c, level + 1) for c in reversed(children.get(tasks[i]["uid"], ())))
    out.extend((t, 0) for i, t in enumerate(tasks) if i not in seen)
    return out


def _parse(value: str | None) -> datetime | None:
    """A stored stamp as an aware UTC datetime, or None if absent or unreadable."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def focus_block(s: Mapping | None, now: datetime) -> dict:
    """The focus state a viewer sees, from a live session row or None.

    Returns a NEW dict with exactly the five clock keys. Only `ends_at` (fixed
    while running) or `remaining_s` (frozen while paused) ever carries the clock,
    so two polls of an unchanged session are equal and the ETag holds; the
    viewer counts down on its own device.

    A session nobody ended is not necessarily live: a timer left paused all
    afternoon, or one that ran out and was never continued, would otherwise say
    "focusing" to a stranger for hours. Past the idle thresholds they read as
    idle, which is also the honest answer.
    """
    if s is None:
        return dict(IDLE)
    phase = s["phase"] if s["phase"] in FOCUS_PHASES else "focus"
    length = max(0, int(s["phase_length_s"] or 0))
    elapsed = min(max(0, int(s["phase_elapsed_s"] or 0)), length)
    room = length - elapsed
    since = _parse(s["running_since"])
    updated = _parse(s["updated_at"])
    if since is not None:
        ends = since + timedelta(seconds=room)
        if now < ends:
            return {"state": "focusing" if phase == "focus" else "break",
                    "phase": phase, "phase_length_s": length,
                    "ends_at": stamp(ends), "remaining_s": None}
        over_since = ends
    elif room > 0:
        if updated is not None and (now - updated).total_seconds() > PAUSED_IDLE_S:
            return dict(IDLE)
        return {"state": "paused", "phase": phase, "phase_length_s": length,
                "ends_at": None, "remaining_s": room}
    else:
        over_since = updated or now
    if (now - over_since).total_seconds() > BETWEEN_IDLE_S:
        return dict(IDLE)
    return {"state": "between", "phase": phase, "phase_length_s": length,
            "ends_at": None, "remaining_s": None}

