"""Shared pieces for the subjects: the shapes more than one picture uses.

Everything here is geometry. Colour is a role (line, wash, accent) chosen at
the call site; motion is the client's. The canvas is the builder's viewBox,
160 x 200, portrait, with y growing downward; the ground of most pictures sits
near y = 186.

Each helper takes the builder and a `when` so a subject can say under which
state a piece shows; the subject decides, the kit only draws.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from ..pen import Stroke, curve, line, loop
from ..rng import Rng
from ..scene import SketchBuilder

Point = tuple[float, float]

# The light shifts through the day in four steps, within either theme.
# (from, to) hours, the last wrapping midnight.
MORNING = ('hour', 5, 11)
MIDDAY = ('hour', 11, 15)
AFTERNOON = ('hour', 15, 19)
EVENING = ('hour', 19, 5)
HOURS = (MORNING, MIDDAY, AFTERNOON, EVENING)

REWARDS = 12


def blob(cx: float, cy: float, rx: float, ry: float, rng: Rng, n: int = 11,
         wobble: float = 0.12) -> Stroke:
    """An organic closed shape: an ellipse whose radius wanders by `wobble`."""
    pts = []
    turn = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        a = turn + 2 * math.pi * i / n
        k = 1 + rng.uniform(-wobble, wobble)
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    return loop(*pts)


def inside(points: Sequence[Point], cx: float, cy: float, rx: float, ry: float) -> bool:
    return all(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1 for x, y in points)


def scatter(rng: Rng, count: int, cx: float, cy: float, rx: float, ry: float,
            gap: float, tries: int = 400) -> list[Point]:
    """`count` points inside an ellipse, at least `gap` apart (best effort)."""
    out: list[Point] = []
    for _ in range(tries):
        if len(out) == count:
            break
        a = rng.uniform(0, 2 * math.pi)
        r = math.sqrt(rng.random())
        p = (cx + rx * r * math.cos(a), cy + ry * r * math.sin(a))
        if all(math.dist(p, q) >= gap for q in out):
            out.append(p)
    while len(out) < count:        # never fewer slots than rewards
        a = rng.uniform(0, 2 * math.pi)
        out.append((cx + rx * 0.6 * math.cos(a), cy + ry * 0.6 * math.sin(a)))
    return out


def sun(b: SketchBuilder, cx: float, cy: float, r: float, *, when: Iterable = ()) -> None:
    """A small sun: a disc and eight short rays."""
    when = tuple(when)
    b.line(ring(cx, cy, r, 9), when=when)
    for i in range(8):
        a = math.pi * i / 4 + 0.2
        b.line(line((cx + (r + 3) * math.cos(a), cy + (r + 3) * math.sin(a)),
                    (cx + (r + 7) * math.cos(a), cy + (r + 7) * math.sin(a))), when=when)


def low_sun(b: SketchBuilder, cx: float, cy: float, r: float, *, when: Iterable = ()) -> None:
    """A setting sun: half a disc over a short horizon stroke."""
    when = tuple(when)
    arc = [(cx + r * math.cos(math.pi + math.pi * i / 6), cy + r * math.sin(math.pi + math.pi * i / 6))
           for i in range(7)]
    b.line(curve(*arc), when=when)
    b.line(line((cx - r - 6, cy), (cx + r + 6, cy)), when=when)
    for i in range(3):
        a = math.pi + math.pi * (i + 1) / 4
        b.line(line((cx + (r + 3) * math.cos(a), cy + (r + 3) * math.sin(a)),
                    (cx + (r + 6) * math.cos(a), cy + (r + 6) * math.sin(a))), when=when)


def moon(b: SketchBuilder, cx: float, cy: float, r: float, *, glow: bool = True,
         when: Iterable = ()) -> None:
    """A crescent opening to the right, with a soft glow round it (at night the
    wash is light, never a fill under the picture)."""
    when = tuple(when)
    if glow:
        b.wash(ring(cx - r * 0.2, cy, r * 1.7, 11), when=when)
    outer = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
             for a in range(70, 291, 20)]
    ox, rr = cx + 0.45 * r, 0.946 * r
    inner = [(ox + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
             for a in (263.4, 225, 180, 135, 96.6)]
    b.line(loop(*outer, *inner[1:-1]), when=when)


def stars(b: SketchBuilder, rng: Rng, count: int, box: tuple[float, float, float, float],
          *, when: Iterable = ()) -> None:
    """Small four-stroke stars scattered in `box` (x0, y0, x1, y1)."""
    when = tuple(when)
    for _ in range(count):
        x, y = rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3])
        s = rng.uniform(1.6, 2.6)
        b.line(line((x - s, y), (x + s, y)), when=when)
        b.line(line((x, y - s), (x, y + s)), when=when)


def cloud(b: SketchBuilder, cx: float, cy: float, w: float, *, when: Iterable = ()) -> None:
    """A soft cumulus outline, ink only: weather, never a warning."""
    when = tuple(when)
    h = w * 0.36
    pts = [
        (cx - w / 2, cy + h / 2), (cx - w * 0.46, cy), (cx - w * 0.3, cy - h * 0.45),
        (cx - w * 0.08, cy - h * 0.6), (cx + w * 0.14, cy - h * 0.75), (cx + w * 0.34, cy - h * 0.4),
        (cx + w * 0.5, cy + h * 0.05), (cx + w * 0.44, cy + h / 2),
    ]
    b.line(curve(*pts), when=when)
    b.line(line((cx - w / 2, cy + h / 2), (cx + w * 0.44, cy + h / 2)), when=when)


def glow_dot(b: SketchBuilder, x: float, y: float, r: float, *, halo: float, when: Iterable = ()) -> None:
    """Something lit: a coral dot with a wash halo (a firefly, a bulb)."""
    when = tuple(when)
    b.wash(ring(x, y, halo, 9), when=when)
    b.accent(ring(x, y, r, 7), when=when)


def fruit(b: SketchBuilder, x: float, y: float, r: float, *, when: Iterable = ()) -> None:
    """A coral fruit, outlined in ink so its shape holds on light paper."""
    when = tuple(when)
    b.accent(ring(x, y, r, 8), when=when)
    b.line(ring(x, y, r, 8), when=when)
    b.line(line((x + 0.4, y - r), (x + 1.6, y - r - 2.6)), when=when)


def steam(b: SketchBuilder, x: float, y: float, frame: int, frames: int, height: float = 22) -> None:
    """Two wisps rising from (x, y), one still frame of a loop of `frames`."""
    phase = 2 * math.pi * frame / frames
    for k, dx in enumerate((-3.5, 3.5)):
        pts = []
        for i in range(6):
            t = i / 5
            sway = math.sin(phase + t * 4 + k * 1.7) * (1.6 + t * 2.2)
            pts.append((x + dx + sway, y - t * height))
        b.line(curve(*pts))


def leaf(cx: float, cy: float, length: float, angle: float) -> Stroke:
    """An almond leaf pointing along `angle` (radians)."""
    ca, sa = math.cos(angle), math.sin(angle)
    w = length * 0.32

    def at(u: float, v: float) -> Point:
        return (cx + u * ca - v * sa, cy + u * sa + v * ca)

    return loop(at(0, 0), at(length * 0.5, w), at(length, 0), at(length * 0.5, -w))


def ring(cx: float, cy: float, r: float, n: int = 9) -> Stroke:
    """A closed, smooth circle through `n` points."""
    return loop(*[(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                  for i in range(n)])
