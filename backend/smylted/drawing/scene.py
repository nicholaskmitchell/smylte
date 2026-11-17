"""A sketch: the marks of one drawing, each with the conditions it shows under.

Roles name paint, never a colour; the client applies them:
  * `line`   stroke in --fg at --stroke-pen (1.8px), round caps and joins, no fill
  * `wash`   fill in --wash, no stroke
  * `glow`   fill in --wash with a soft radial falloff: light at night (the
             client draws the gradient)
  * `accent` fill in --accent-fill, no stroke

A `line` mark carries three frames, the boil; `wash`, `glow` and `accent` carry
one. An ambient is a loop at 6fps whose marks carry one frame each.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from . import conditions
from .checks import endpoints
from .pen import Pen, Stroke, hand, to_d
from .rng import Rng
from .state import MAX_REWARDS, DayState, Theme

Role = Literal['line', 'wash', 'glow', 'accent']
PAPERS = ('auto', 'glint')

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
    # Where the client grows a reward's marks from; set by `build` for marks
    # that carry a reward.
    origin: tuple[float, float] | None = None
    # How the client treats the mark against the paper, and which piece of the
    # subject it belongs to. Both are for the server's own checks and never
    # travel.
    paper: str = 'auto'
    part: str = ''

    def to_json(self) -> dict:
        out = {
            "id": self.id,
            "role": self.role,
            "frames": list(self.frames),
            "when": conditions.to_json(self.when),
            "reward": self.reward,
            "on": self.on,
        }
        if self.origin is not None:
            out["origin"] = [round(self.origin[0], 1), round(self.origin[1], 1)]
        return out


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


def _is_index(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _inset(points: list, amount: float) -> list:
    """Every point moved `amount` toward the centroid, or onto it if nearer."""
    if not points:
        return []
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    out = []
    for x, y in points:
        d = math.hypot(cx - x, cy - y)
        if d <= amount:
            out.append((cx, cy))
        else:
            out.append((x + (cx - x) * amount / d, y + (cy - y) * amount / d))
    return out


def _reward_of(when: tuple) -> int | None:
    rewards = [atom[1] for atom in when if atom[0] == 'reward']
    if len(rewards) > 1:
        raise ValueError("a mark may carry at most one reward condition")
    return rewards[0] if rewards else None


class SketchBuilder:
    def __init__(self, subject: str, theme: Theme, rng: Rng,
                 view_box=(0, 0, 160, 200), *, still: bool = False):
        self.subject = subject
        self.theme = theme
        self.rng = rng
        self.view_box = tuple(view_box)
        self._pen = Pen(rng.fork('pen'))
        self._marks: list[Mark] = []
        self._points = 0
        self._ambient: Ambient | None = None
        self._anchors: dict[int, tuple[float, float]] = {}
        # Set on the child builders `ambient` hands out: their marks are one
        # still frame each, named a{f}m{n}.
        self._prefix = ""
        # `still=True` is a drawing that never boils (a view's): every mark
        # is one frame, and it has no ambient.
        self._still = still

    def _append(self, mark_id: str, role: Role, frames: tuple[str, ...], points: int,
                when: tuple, reward: int | None, paper: str, part: str | None) -> None:
        if paper not in PAPERS:
            raise ValueError(f"paper must be one of {PAPERS}, not {paper!r}")
        self._points += points * len(frames)
        self._marks.append(
            Mark(mark_id, role, frames, when, reward, False, None, paper, part or mark_id))

    def _add(self, role: Role, stroke: Stroke, when, key: str | None, *,
             part: str | None = None, paper: str = 'auto', still: bool = False) -> None:
        when = conditions.validate(when)
        reward = _reward_of(when)
        mark_id = f"{self._prefix}m{len(self._marks)}"
        key = mark_id if key is None else key
        if role == 'line':
            # One bow for every boil frame: the hand is chosen before the frames.
            stroke = hand(stroke, self._pen.rng.fork(f"{key}|hand"))
        if role == 'line' and not self._still and not still:
            frames = self._pen.frames(stroke, key, LINE_FRAMES)
        else:
            frames = (self._pen.still(stroke, key),)
        self._append(mark_id, role, frames, len(stroke.points), when, reward, paper, part)

    def line(self, stroke: Stroke, *, when=(), key: str | None = None,
             part: str | None = None) -> None:
        self._add('line', stroke, when, key, part=part)

    def wash(self, stroke: Stroke, *, when=(), key: str | None = None,
             part: str | None = None) -> None:
        self._add('wash', stroke, when, key, part=part)

    def glow(self, stroke: Stroke, *, when=(), key: str | None = None,
             part: str | None = None) -> None:
        self._add('glow', stroke, when, key, part=part)

    def accent(self, stroke: Stroke, *, when=(), key: str | None = None,
               part: str | None = None, paper: str = 'auto') -> None:
        self._add('accent', stroke, when, key, part=part, paper=paper)

    def filled(self, stroke: Stroke, *, when=(), key: str | None = None,
               part: str | None = None, paper: str = 'auto') -> None:
        """A coral fill and its ink outline, drawn from the same jittered
        points so the ink sits on the edge of the fill. The fill is drawn in
        by half a unit so it never shows outside the line. The outline holds
        still, one frame, while the picture boils: a reward stays put."""
        when = conditions.validate(when)
        reward = _reward_of(when)
        accent_id = f"{self._prefix}m{len(self._marks)}"
        line_id = f"{self._prefix}m{len(self._marks) + 1}"
        k = key if key is not None else accent_id
        stroke = hand(stroke, self._pen.rng.fork(f"{k}|hand"))
        pts = self._pen.jittered(stroke, f"{k}|f0")
        closed, smooth, corners = stroke.closed, stroke.smooth, stroke.corners
        fill = to_d(_inset(pts, 0.5), closed, smooth, corners)
        outline = (to_d(pts, closed, smooth, corners),)
        part = part or accent_id
        self._append(accent_id, 'accent', (fill,), len(stroke.points), when, reward,
                     paper, part)
        self._append(line_id, 'line', outline, len(stroke.points), when, reward,
                     'auto', part)

    def anchor(self, reward: int, x: float, y: float) -> None:
        """Where reward `reward`'s marks grow from, instead of their centroid."""
        if not _is_index(reward) or not 0 <= reward < MAX_REWARDS:
            raise ValueError(f"reward index must be an int in 0..{MAX_REWARDS - 1}")
        x0, y0, w, h = self.view_box
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
            # The client refuses a drawing with an origin off the picture, so
            # one bad anchor would blank the whole day.
            raise ValueError(f"reward {reward} anchored at ({x}, {y}), outside the picture")
        self._anchors[reward] = (float(x), float(y))

    def ambient(self, seconds: float, when,
                draw: Callable[[int, SketchBuilder], None]) -> None:
        if self._still:
            raise ValueError("a still drawing (or an ambient frame) cannot hold an ambient")
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

    def _origins(self) -> dict[int, tuple[float, float]]:
        """Where each reward grows from: its anchor if the subject set one,
        else the centroid of the on-curve points of its marks."""
        pooled: dict[int, list[tuple[float, float]]] = {}
        for m in self._marks:
            if m.reward is not None and m.reward not in self._anchors:
                pooled.setdefault(m.reward, []).extend(endpoints(m.frames[0]))
        out = {r: (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
               for r, pts in pooled.items() if pts}
        out.update(self._anchors)
        return out

    def build(self, state: DayState) -> Sketch:
        def settle(m: Mark) -> Mark:
            when = conditions.validate(m.when)
            return dataclasses.replace(m, when=when, on=conditions.evaluate(when, state))

        # Paint order is by role, whatever order the subject drew in: washes
        # under everything, glows over them, coral fills over those, ink on
        # top. A fill never covers a line, which is what keeps ink on paper
        # reading as ink.
        order = {'wash': 0, 'glow': 1, 'accent': 2, 'line': 3}
        origins = self._origins()
        marks = tuple(
            settle(dataclasses.replace(m, origin=origins.get(m.reward)))
            if m.reward is not None else settle(m)
            for m in sorted(self._marks, key=lambda m: order[m.role]))
        ambient = None
        total = len(marks)
        if self._ambient is not None:
            a = self._ambient
            # A loop's marks are on only while the loop is: its own condition
            # and theirs.
            looping = conditions.evaluate(a.when, state)
            frames = tuple(tuple(dataclasses.replace(settle(m), on=looping and settle(m).on)
                                 for m in frame) for frame in a.frames)
            total += sum(len(frame) for frame in frames)
            ambient = Ambient(a.seconds, conditions.validate(a.when), frames)
        if total > MAX_MARKS:
            raise ValueError(f"a sketch may hold at most {MAX_MARKS} marks, not {total}")
        if self._points > MAX_POINTS:
            raise ValueError(
                f"a sketch may hold at most {MAX_POINTS} path points, not {self._points}")
        return Sketch(self.subject, self.theme, self.view_box, marks, ambient)
