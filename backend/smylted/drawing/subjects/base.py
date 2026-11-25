"""What a subject is, and the contract every subject keeps."""
from __future__ import annotations

from datetime import date
from typing import Protocol

from ..rng import Rng
from ..scene import Sketch
from ..state import Composition, DayState


class DayDrawing(Protocol):
    id: str
    since: date
    until: date | None
    # The base part names that are meant to touch, e.g.
    # frozenset({frozenset({'trunk', 'canopy'})}); the geometry checks leave
    # those alone. A subject without any need not define it.
    JOINS: frozenset[frozenset[str]]
    # True when the subject draws its own 'paper' composition, for the desk
    # unit's ink (`paper_sketch`). A subject without it need not define it:
    # it is False, and the desk unit prints its light composition converted.
    PAPER: bool

    def render(self, state: DayState, theme: Composition, rng: Rng) -> Sketch: ...


def joins_of(subject) -> frozenset:
    """The base part names the subject says may touch; none if it says nothing."""
    return getattr(subject, 'JOINS', frozenset())


def has_paper(subject) -> bool:
    """Whether the subject draws its own 'paper' composition."""
    return getattr(subject, 'PAPER', False)


def paper_sketch(subject, state: DayState, rng: Rng) -> Sketch:
    """The subject as the desk unit prints it: its own 'paper' composition,
    drawn for ink, when it has one. Until it does, its light composition, which
    `paper.py` converts (the wash and glow dropped). Never 'paper' to a subject
    without one: its `render` would take any theme but 'light' for the night."""
    if has_paper(subject):
        return subject.render(state, 'paper', rng)
    return subject.render(state, 'light', rng)


_FULL = DayState(progress=1, rewards=12, focus_active=True, all_done=True,
                 nothing_planned=False, overdue=3, hour=21)


def _shape(sketch: Sketch):
    """The sketch as JSON with every `on` taken out: what must not depend on
    the day's state."""
    def strip(mark: dict) -> dict:
        return {k: v for k, v in mark.items() if k != 'on'}

    data = sketch.to_json()
    data["marks"] = [strip(m) for m in data["marks"]]
    if data["ambient"] is not None:
        data["ambient"]["frames"] = [
            [strip(m) for m in frame] for frame in data["ambient"]["frames"]]
    return data


def assert_declarative(subject, rng_path: str = 'contract') -> None:
    """AssertionError unless the subject draws the same marks whatever the
    state, so only `on` differs. That is what lets the client react to the
    state without a round trip."""
    themes = ('light', 'dark', 'paper') if has_paper(subject) else ('light', 'dark')
    for theme in themes:
        empty = _shape(subject.render(DayState(), theme, Rng(rng_path)))
        full = _shape(subject.render(_FULL, theme, Rng(rng_path)))
        if empty != full:
            raise AssertionError(
                f"subject {subject.id!r} draws different marks for different states "
                f"({theme} theme); only `on` may depend on the state")
