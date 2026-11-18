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

# In viewBox units. The phone draws the 160-unit drawing at 128px (0.8px per
# unit), so a point strays at most 1px there, the design system's --wobble. The
# desktop draws it at 1.2px per unit: the same proportion of a larger drawing.
WOBBLE = 1.25

# The ink's width in viewBox units: the client draws --stroke-pen (1.8px) at
# 1.25 units to the pixel. Two lines closer than this, centre to centre, touch.
PEN = 2.25

# The hand: segments shorter than this stay ruled; longer ones get a point
# about every HAND_STEP units, bowed by at most HAND_BOW.
HAND_MIN_SEGMENT = 28.0
HAND_STEP = 22.0
HAND_BOW = 2.0


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    closed: bool = False
    smooth: bool = True
    # Indices of points a smooth stroke turns sharply at, not through.
    corners: tuple[int, ...] = ()


def _pts(pts) -> tuple[Point, ...]:
    return tuple((float(x), float(y)) for x, y in pts)


def line(*pts: Point) -> Stroke:
    return Stroke(_pts(pts), closed=False, smooth=False)


def curve(*pts: Point, corners: Sequence[int] = ()) -> Stroke:
    return Stroke(_pts(pts), closed=False, smooth=True, corners=tuple(corners))


def loop(*pts: Point, corners: Sequence[int] = ()) -> Stroke:
    return Stroke(_pts(pts), closed=True, smooth=True, corners=tuple(corners))


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
    # One correctly rounded conversion, as `round(v, 1)` is: "-0.0" and "0.0"
    # are both "0", and a whole number drops its ".0".
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
        return "0" if s == "-0" else s
    return s


def _pair(p: Point) -> str:
    return f"{_num(p[0])} {_num(p[1])}"


def to_d(points: Sequence[Point], closed: bool, smooth: bool,
         corners: Sequence[int] = ()) -> str:
    """SVG path data: straight segments, or a uniform Catmull-Rom spline
    through the points as cubic Beziers. At a corner the spline turns instead
    of passing through: its handles point straight at the neighbouring point."""
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
            i1 = i % n if closed else i
            i2 = (i + 1) % n if closed else min(i + 1, n - 1)
            if i1 in corners:
                c1 = (p1[0] + (p2[0] - p1[0]) / 3, p1[1] + (p2[1] - p1[1]) / 3)
            else:
                c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            if i2 in corners:
                c2 = (p2[0] - (p2[0] - p1[0]) / 3, p2[1] - (p2[1] - p1[1]) / 3)
            else:
                c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            parts.append(f"C {_pair(c1)} {_pair(c2)} {_pair(p2)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def hand(stroke: Stroke, rng: Rng) -> Stroke:
    """A ruled line drawn by hand: each long straight segment gains a gentle bow
    (one side for the whole stroke) and a little tremor, and the stroke becomes
    a smooth one that still turns sharply at its original vertices. Short
    segments stay ruled, and a stroke with none long enough comes back as it
    was. A stroke that is already smooth is left alone."""
    if stroke.smooth:
        return stroke
    pts = stroke.points
    n = len(pts)
    s = -1.0 if rng.random() < 0.5 else 1.0
    segments = n if stroke.closed else n - 1
    out: list[Point] = []
    corners: list[int] = []
    bowed = False
    for i in range(segments):
        p, q = pts[i], pts[(i + 1) % n]
        corners.append(len(out))
        out.append(p)
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length < HAND_MIN_SEGMENT:
            continue
        bowed = True
        k = math.ceil(length / HAND_STEP) - 1
        nx, ny = -dy / length, dx / length
        for j in range(1, k + 1):
            t = j / (k + 1)
            off = (s * min(HAND_BOW, 0.012 * length) * math.sin(math.pi * t)
                   + rng.uniform(-0.3, 0.3))
            out.append((p[0] + dx * t + nx * off, p[1] + dy * t + ny * off))
    if not stroke.closed and n:
        corners.append(len(out))
        out.append(pts[-1])
    if not bowed:
        return stroke
    return Stroke(tuple(out), closed=stroke.closed, smooth=True, corners=tuple(corners))


class Pen:
    def __init__(self, rng: Rng, wobble: float = WOBBLE):
        self.rng = rng
        self.wobble = wobble

    def jittered(self, stroke: Stroke, key: str) -> list[Point]:
        """Every point moved at most `wobble`: a polar jitter, so the bound is
        a distance and not a box whose corners stray further. The jitter scales
        with the size of the stroke and the rest of the allowance is one offset
        shared by every point: small shapes move as one and keep their shape;
        long strokes get the full hand."""
        pts = stroke.points
        if not pts:
            return []
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        size = max(max(xs) - min(xs), max(ys) - min(ys))
        local = self.wobble * min(1.0, max(0.2, size / 30.0))
        rng = self.rng.fork(key)
        r = (self.wobble - local) * math.sqrt(rng.random())
        a = rng.uniform(0.0, 2 * math.pi)
        gx, gy = r * math.cos(a), r * math.sin(a)
        out = []
        for x, y in pts:
            r = local * math.sqrt(rng.random())
            a = rng.uniform(0.0, 2 * math.pi)
            out.append((x + gx + r * math.cos(a), y + gy + r * math.sin(a)))
        return out

    def frames(self, stroke: Stroke, key: str, count: int = 3) -> tuple[str, ...]:
        return tuple(
            to_d(self.jittered(stroke, f"{key}|f{k}"), stroke.closed, stroke.smooth,
                 stroke.corners)
            for k in range(count)
        )

    def still(self, stroke: Stroke, key: str) -> str:
        return to_d(self.jittered(stroke, f"{key}|still"), stroke.closed, stroke.smooth,
                    stroke.corners)
