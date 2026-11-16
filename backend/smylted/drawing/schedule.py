"""Which subject a day draws.

From ANCHOR on, the pick is greedy and walks forward a day at a time: each day
shuffles the subjects eligible on it and takes the first one not picked on the
days just before, so no subject comes back within a week while there are seven
to choose from. Every pick depends on the ones before it, so the picks are
memoised per salt and roster and only ever extended. A day before ANCHOR has no
history to avoid, and is a plain shuffle.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import date, timedelta

from .rng import Rng
from .subjects.base import DayDrawing

ANCHOR = date(2026, 1, 1)
WINDOW = 6

# (salt, roster signature) -> the id picked on each day from ANCHOR, in order;
# None for a day nothing was eligible on.
_MEMO: dict[tuple, list[str | None]] = {}
_LOCK = threading.Lock()


def _eligible(day: date, roster: Sequence[DayDrawing]) -> list[DayDrawing]:
    return sorted(
        (s for s in roster if s.since <= day and (s.until is None or day < s.until)),
        key=lambda s: s.id,
    )


def _extend(picks: list[str | None], through: date, salt: str,
            roster: Sequence[DayDrawing]) -> None:
    d = ANCHOR + timedelta(days=len(picks))
    while d <= through:
        eligible = _eligible(d, roster)
        if not eligible:
            picks.append(None)
        else:
            order = Rng.for_day(d, salt, 'schedule').shuffled(eligible)
            window = min(WINDOW, len(eligible) - 1)
            recent = set(picks[-window:]) if window > 0 else set()
            pick = next((s for s in order if s.id not in recent), order[0])
            picks.append(pick.id)
        d += timedelta(days=1)


def subject_for(day: date, salt: str,
                roster: Sequence[DayDrawing]) -> DayDrawing | None:
    if day < ANCHOR:
        eligible = _eligible(day, roster)
        if not eligible:
            return None
        return Rng.for_day(day, salt, 'schedule').shuffled(eligible)[0]
    key = (salt, tuple((s.id, s.since, s.until) for s in roster))
    index = (day - ANCHOR).days
    with _LOCK:
        picks = _MEMO.setdefault(key, [])
        if len(picks) <= index:
            _extend(picks, day, salt, roster)
        picked = picks[index]
    if picked is None:
        return None
    return next(s for s in roster if s.id == picked)
