"""The daily drawing: one engine for every device and the e-paper desk unit.

The server draws; the client only renders the marks as inline SVG and turns
conditional ones on and off against its own copy of the day's state.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
from datetime import date

from . import subjects
from .rng import Rng
from .scene import Sketch, SketchBuilder
from .schedule import subject_for
from .state import DayState, Theme

__all__ = ["DayState", "Rng", "Sketch", "SketchBuilder", "desk_drawing", "desk_seed",
           "drawing_payload", "share_drawing_payload", "share_seed", "subject_for"]

_VIEWS = ('tasks', 'calendar', 'settings')


def _payload(day: date, theme: Theme, salt: str, view: str, state: DayState | None,
             roster, views, months) -> dict | None:
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
    if view == 'month':
        # The Calendar's page top: one drawing per month of the year, the same
        # on every day of it and in every year, seeded per install as a view's
        # is. `day` is any day of the month; the payload names its first.
        subject = months.get(day.month)
        if subject is None:
            return None
        rng = Rng(f"month|{day.month}|{salt}")
        sketch = subject.render(DayState(), theme, rng)
        return {"view": "month", "day": day.replace(day=1).isoformat(), **sketch.to_json()}
    raise ValueError(f"unknown view {view!r}")


@functools.lru_cache(maxsize=64)
def _cached_payload(day: date, theme: Theme, salt: str, view: str,
                    state: DayState | None) -> dict | None:
    return _payload(day, theme, salt, view, state, subjects.ROSTER, subjects.VIEW_DRAWINGS,
                    subjects.MONTH_DRAWINGS)


def drawing_payload(day: date, theme: Theme, salt: str, *, view: str = 'today',
                    state: DayState | None = None, roster=None, views=None,
                    months=None) -> dict | None:
    """The drawing for `day` as the client receives it, or None when there is
    none. The salt seeds it and never appears in it."""
    if roster is None and views is None and months is None:
        return _cached_payload(day, theme, salt, view, state)
    return _payload(
        day, theme, salt, view, state,
        roster if roster is not None else subjects.ROSTER,
        views if views is not None else subjects.VIEW_DRAWINGS,
        months if months is not None else subjects.MONTH_DRAWINGS,
    )


def share_seed(salt: str) -> str:
    """The seed a share's drawing is drawn from: HMAC-SHA256 of the salt, one
    way. cyrb128 and sfc32 are not one-way, so nothing published to a stranger
    is drawn from the salt itself. The salt still picks the subject."""
    return hmac.new(salt.encode("utf-8"), b"share-drawing", hashlib.sha256).hexdigest()[:32]


def _share_payload(day: date, theme: Theme, salt: str, roster) -> dict | None:
    subject = subject_for(day, salt, roster)
    if subject is None:
        return None
    rng = Rng.for_day(day, share_seed(salt), f"subject|{subject.id}")
    sketch = subject.render(DayState(), theme, rng)
    return {"view": "today", "day": day.isoformat(), **sketch.to_json()}


@functools.lru_cache(maxsize=8)
def _cached_share_payload(day: date, theme: Theme, salt: str) -> dict | None:
    return _share_payload(day, theme, salt, subjects.ROSTER)


def share_drawing_payload(day: date, theme: Theme, salt: str, *,
                          roster=None) -> dict | None:
    """The owner's drawing of `day` as a share shows it, or None when the day
    has none. The subject is the one their Today shows (`subject_for` with the
    salt). Its marks are drawn from `share_seed(salt)` in the default state, so
    nothing in it was drawn from the salt and nothing in it is the owner's day:
    the viewer's page turns its marks on from what the share already shows."""
    if roster is None:
        return _cached_share_payload(day, theme, salt)
    return _share_payload(day, theme, salt, roster)


def desk_seed(salt: str) -> str:
    """The seed the desk unit's drawing is drawn from: HMAC-SHA256 of the salt,
    one way, as `share_seed` is. The panel's image is served to whoever holds
    its URL, so nothing in it is drawn from the salt itself; the salt still
    picks the subject."""
    return hmac.new(salt.encode("utf-8"), b"desk-drawing", hashlib.sha256).hexdigest()[:32]


@functools.lru_cache(maxsize=16)
def desk_drawing(day: date, salt: str, state: DayState, *,
                 subject_id: str | None = None) -> Sketch | None:
    """The day's drawing as the desk unit prints it (`paper.paper_image`), or
    None when the day has none. The subject is the one the owner's Today shows
    (`subject_for` with the salt), or the roster's `subject_id` when given
    (ValueError for one it does not hold). Its marks are drawn from
    `desk_seed(salt)`, in its 'paper' composition where it has one
    (`subjects.paper_sketch`)."""
    if subject_id is None:
        subject = subject_for(day, salt, subjects.ROSTER)
        if subject is None:
            return None
    else:
        subject = next((s for s in subjects.ROSTER if s.id == subject_id), None)
        if subject is None:
            raise ValueError(f"unknown subject {subject_id!r}")
    rng = Rng.for_day(day, desk_seed(salt), f"subject|{subject.id}")
    return subjects.paper_sketch(subject, state, rng)
