"""A sketch: the marks of one drawing, each with the conditions it shows under.

Roles name paint, never a colour; the client applies them:
  * `line`   stroke in --fg at --stroke-pen (1.8px), round caps and joins, no fill
  * `wash`   fill in --wash, no stroke
  * `accent` fill in --accent-fill, no stroke

A `line` mark carries three frames, the boil; `wash` and `accent` carry one. An
ambient is a loop at 6fps whose marks carry one frame each.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from . import conditions
from .pen import Pen, Stroke
from .rng import Rng
from .state import DayState, Theme

Role = Literal['line', 'wash', 'accent']

FPS = 6
LINE_FRAMES = 3
MAX_MARKS = 400
MAX_POINTS = 6000


@dataclass
class Mark:
    id: str
    role: Role
    frames: tuple[str, ...]
    when: tuple
    reward: int | None
    on: bool

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "frames": list(self.frames),
            "when": conditions.to_json(self.when),
            "reward": self.reward,
            "on": self.on,
        }


@dataclass
class Ambient:
    seconds: float
    when: tuple
    frames: tuple[tuple[Mark, ...], ...]

    def to_json(self) -> dict:
        return {
            "seconds": float(self.seconds),
            "when": conditions.to_json(self.when),
            "frames": [[m.to_json() for m in frame] for frame in self.frames],
        }


@dataclass
class Sketch:
    subject: str
    theme: Theme
    view_box: tuple[int, int, int, int]
    marks: tuple[Mark, ...]
    ambient: Ambient | None

    def to_json(self) -> dict:
        return {
            "subject": self.subject,
            "theme": self.theme,
            "viewBox": list(self.view_box),
            "marks": [m.to_json() for m in self.marks],
            "ambient": None if self.ambient is None else self.ambient.to_json(),
        }


def _reward_of(when: tuple) -> int | None:
    rewards = [atom[1] for atom in when if atom[0] == 'reward']
    if len(rewards) > 1:
        raise ValueError("a mark may carry at most one reward condition")
    return rewards[0] if rewards else None


class SketchBuilder:
    def __init__(self, subject: str, theme: Theme, rng: Rng,
                 view_box=(0, 0, 160, 200)):
        self.subject = subject
        self.theme = theme
        self.rng = rng
        self.view_box = tuple(view_box)
        self._pen = Pen(rng.fork('pen'))
        self._marks: list[Mark] = []
        self._points = 0
        self._ambient: Ambient | None = None
        # Set on the child builders `ambient` hands out: their marks are one
        # still frame each, named a{f}m{n}.
        self._prefix = ""
        self._still = False

    def _add(self, role: Role, stroke: Stroke, when, key: str | None) -> None:
        when = conditions.validate(when)
        reward = _reward_of(when)
        mark_id = f"{self._prefix}m{len(self._marks)}"
        key = mark_id if key is None else key
        if role == 'line' and not self._still:
            frames = self._pen.frames(stroke, key, LINE_FRAMES)
        else:
            frames = (self._pen.still(stroke, key),)
        self._points += len(stroke.points) * len(frames)
        self._marks.append(Mark(mark_id, role, frames, when, reward, False))

    def line(self, stroke: Stroke, *, when=(), key: str | None = None) -> None:
        self._add('line', stroke, when, key)

    def wash(self, stroke: Stroke, *, when=(), key: str | None = None) -> None:
        self._add('wash', stroke, when, key)

    def accent(self, stroke: Stroke, *, when=(), key: str | None = None) -> None:
        self._add('accent', stroke, when, key)

    def ambient(self, seconds: float, when,
                draw: Callable[[int, SketchBuilder], None]) -> None:
        if self._still:
            raise ValueError("an ambient frame cannot hold an ambient")
        if self._ambient is not None:
            raise ValueError("a sketch has at most one ambient")
        when = conditions.validate(when)
        frames = []
        for f in range(round(seconds * FPS)):
            child = SketchBuilder(self.subject, self.theme, self.rng, self.view_box)
            child._pen = self._pen
            child._prefix = f"a{f}"
            child._still = True
            draw(f, child)
            self._points += child._points
            frames.append(tuple(child._marks))
        self._ambient = Ambient(seconds, when, tuple(frames))

    def build(self, state: DayState) -> Sketch:
        def settle(m: Mark) -> Mark:
            when = conditions.validate(m.when)
            return dataclasses.replace(m, when=when, on=conditions.evaluate(when, state))

        # Paint order is by role, whatever order the subject drew in: washes
        # under everything, coral fills over them, ink on top. A fill never
        # covers a line, which is what keeps ink on paper reading as ink.
        order = {'wash': 0, 'accent': 1, 'line': 2}
        marks = tuple(settle(m) for m in sorted(self._marks, key=lambda m: order[m.role]))
        ambient = None
        total = len(marks)
        if self._ambient is not None:
            a = self._ambient
            frames = tuple(tuple(settle(m) for m in frame) for frame in a.frames)
            total += sum(len(frame) for frame in frames)
            ambient = Ambient(a.seconds, conditions.validate(a.when), frames)
        if total > MAX_MARKS:
            raise ValueError(f"a sketch may hold at most {MAX_MARKS} marks, not {total}")
        if self._points > MAX_POINTS:
            raise ValueError(
                f"a sketch may hold at most {MAX_POINTS} path points, not {self._points}")
        return Sketch(self.subject, self.theme, self.view_box, marks, ambient)
