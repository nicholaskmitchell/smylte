"""The daily drawing: one engine for every device and the e-paper desk unit.

The server draws; the client only renders the marks as inline SVG and turns
conditional ones on and off against its own copy of the day's state.
"""
from __future__ import annotations

import functools
from datetime import date

from . import subjects
from .rng import Rng
from .scene import Sketch, SketchBuilder
from .schedule import subject_for
from .state import DayState, Theme

__all__ = ["DayState", "Rng", "Sketch", "SketchBuilder", "drawing_payload", "subject_for"]

_VIEWS = ('tasks', 'calendar', 'settings')


def _payload(day: date, theme: Theme, salt: str, view: str, state: DayState | None,
             roster, views) -> dict | None:
    if view == 'today':
        subject = subject_for(day, salt, roster)
        if subject is None:
            return None
        rng = Rng.for_day(day, salt, f"subject|{subject.id}")
        sketch = subject.render(state or DayState(), theme, rng)
        return {"view": "today", "day": day.isoformat(), **sketch.to_json()}
    if view in _VIEWS:
        subject = views.get(view)
        if subject is None:
            return None
        # The same every day: a view's drawing is static.
        rng = Rng(f"view|{view}|{salt}")
        sketch = subject.render(DayState(), theme, rng)
        return {"view": view, "day": None, **sketch.to_json()}
    raise ValueError(f"unknown view {view!r}")


@functools.lru_cache(maxsize=64)
def _cached_payload(day: date, theme: Theme, salt: str, view: str,
                    state: DayState | None) -> dict | None:
    return _payload(day, theme, salt, view, state, subjects.ROSTER, subjects.VIEW_DRAWINGS)


def drawing_payload(day: date, theme: Theme, salt: str, *, view: str = 'today',
                    state: DayState | None = None, roster=None, views=None) -> dict | None:
    """The drawing for `day` as the client receives it, or None when there is
    none. The salt seeds it and never appears in it."""
    if roster is None and views is None:
        return _cached_payload(day, theme, salt, view, state)
    return _payload(
        day, theme, salt, view, state,
        roster if roster is not None else subjects.ROSTER,
        views if views is not None else subjects.VIEW_DRAWINGS,
    )
