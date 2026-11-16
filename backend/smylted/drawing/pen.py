"""Strokes, and the pen that draws them by hand.

A stroke is pure geometry. The pen gives it a wobble: a few frames of it for a
line, which the client cycles to make the line boil, and one still frame for a
fill or an ambient frame.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .rng import Rng

Point = tuple[float, float]

# In viewBox units. The client never draws the Today drawing larger than 1.25px
# per unit, so a point strays at most 1px on screen.
WOBBLE = 0.8


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    closed: bool = False
    smooth: bool = True


def _pts(pts) -> tuple[Point, ...]:
    return tuple((float(x), float(y)) for x, y in pts)


def line(*pts: Point) -> Stroke:
    return Stroke(_pts(pts), closed=False, smooth=False)


def curve(*pts: Point) -> Stroke:
    return Stroke(_pts(pts), closed=False, smooth=True)


def loop(*pts: Point) -> Stroke:
    return Stroke(_pts(pts), closed=True, smooth=True)


def poly(*pts: Point) -> Stroke:
    return Stroke(_pts(pts), closed=True, smooth=False)


def ellipse(cx: float, cy: float, rx: float, ry: float, n: int = 12,
            rot: float = 0.0) -> Stroke:
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = rx * math.cos(a), ry * math.sin(a)
        pts.append((cx + x * cos_r - y * sin_r, cy + x * sin_r + y * cos_r))
    return Stroke(tuple(pts), closed=True, smooth=True)


def circle(cx: float, cy: float, r: float, n: int = 10) -> Stroke:
    return ellipse(cx, cy, r, r, n=n)


def _num(v: float) -> str:
    v = round(v, 1)
    if v == 0:
        return "0"
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _pair(p: Point) -> str:
    return f"{_num(p[0])} {_num(p[1])}"


def to_d(points: Sequence[Point], closed: bool, smooth: bool) -> str:
    """SVG path data: straight segments, or a uniform Catmull-Rom spline
    through the points as cubic Beziers."""
    n = len(points)
    if n == 0:
        return ""
    parts = [f"M {_pair(points[0])}"]
    if not smooth or n < 2:
        parts.extend(f"L {_pair(p)}" for p in points[1:])
    else:
        if closed:
            def at(i: int) -> Point:
                return points[i % n]
            segments = n
        else:
            def at(i: int) -> Point:
                return points[min(max(i, 0), n - 1)]
            segments = n - 1
        for i in range(segments):
            p0, p1, p2, p3 = at(i - 1), at(i), at(i + 1), at(i + 2)
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            parts.append(f"C {_pair(c1)} {_pair(c2)} {_pair(p2)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


class Pen:
    def __init__(self, rng: Rng, wobble: float = WOBBLE):
        self.rng = rng
        self.wobble = wobble

    def jittered(self, stroke: Stroke, key: str) -> list[Point]:
        """Every point moved at most `wobble`: a polar jitter, so the bound is
        a distance and not a box whose corners stray further."""
        rng = self.rng.fork(key)
        out = []
        for x, y in stroke.points:
            r = self.wobble * math.sqrt(rng.random())
            a = rng.uniform(0.0, 2 * math.pi)
            out.append((x + r * math.cos(a), y + r * math.sin(a)))
        return out

    def frames(self, stroke: Stroke, key: str, count: int = 3) -> tuple[str, ...]:
        return tuple(
            to_d(self.jittered(stroke, f"{key}|f{k}"), stroke.closed, stroke.smooth)
            for k in range(count)
        )

    def still(self, stroke: Stroke, key: str) -> str:
        return to_d(self.jittered(stroke, f"{key}|still"), stroke.closed, stroke.smooth)
