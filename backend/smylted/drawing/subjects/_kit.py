"""Shared pieces for the subjects: the shapes and the rules more than one picture uses.

Everything here is geometry. Paint is a role chosen at the call site (line,
wash, glow, accent); motion is the client's. The canvas is the builder's
viewBox, 160 x 200, portrait, y growing downward.

Rules for a subject, which the tests hold every subject to (tests/test_drawing.py):

* Fill the frame, as the mockup's tree does: the subject is the picture, not a
  vignette in a corner of sky. Nothing leaves the frame.
* The wash is the subject's own outline, shifted down and right like a print
  plate a little off register: `wash_of`. At night the wash stays under the
  subject, and light is a `glow`.
* A reward is a coral fill inside its own ink outline, drawn by `b.filled` (the
  two register, and the outline holds still while the picture boils), at least
  10 units across. Fill the slots in `spread` order, so three or four rewards
  already cover the picture, and `b.anchor` each reward where it grows from.
* Ink never crosses ink by accident. Name every mark's `part`; declare the
  parts that are meant to touch in the subject's JOINS; place scattered things
  with `avoid`.
* Parallel strokes in one object are at least MIN_GAP apart (`hatch`), or they
  fuse into a bar on the phone and on paper.
* The light composition shows the hour with the sun, and late at night with an
  ink moon, line only, so it also works on the 1-bit desk unit. The dark
  composition is its own picture with light as its subject: one moon a day
  (its place chosen once, not by the hour), stars clear of it, and glows.
* Overdue work is weather, never a warning: clouds, fallen leaves, a few
  sheets. Never red, never heavy.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from ..checks import polyline
from ..pen import Stroke, curve, line, loop, to_d
from ..rng import Rng
from ..scene import SketchBuilder

Point = tuple[float, float]
Circle = tuple[float, float, float]

# The light shifts through the day. (from, to) hours, the last wrapping midnight.
MORNING = ('hour', 5, 11)
MIDDAY = ('hour', 11, 15)
AFTERNOON = ('hour', 15, 19)
DUSK = ('hour', 19, 22)
LATE = ('hour', 22, 5)
DAY_HOURS = (MORNING, MIDDAY, AFTERNOON, DUSK, LATE)

REWARDS = 12
MIN_GAP = 4.5          # two phone pen widths: parallel strokes closer than this fuse


# ── shapes ──────────────────────────────────────────────────────────────────

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


def ring(cx: float, cy: float, r: float, n: int = 9) -> Stroke:
    """A closed, smooth circle through `n` points."""
    return loop(*[(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                  for i in range(n)])


def leaf(cx: float, cy: float, length: float, angle: float) -> Stroke:
    """An almond leaf from (cx, cy) pointing along `angle` (radians)."""
    ca, sa = math.cos(angle), math.sin(angle)
    w = length * 0.32

    def at(u: float, v: float) -> Point:
        return (cx + u * ca - v * sa, cy + u * sa + v * ca)

    return loop(at(0, 0), at(length * 0.5, w), at(length, 0), at(length * 0.5, -w), corners=(0, 2))


def wash_of(stroke: Stroke, *, inset: float = 0.93, dx: float = 4.0, dy: float = 4.0) -> Stroke:
    """The wash under an outline: the same shape, a little smaller, shifted down
    and right like a print plate off register (the mockup's translate(3 3))."""
    pts = stroke.points
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    moved = tuple((mx + (x - mx) * inset + dx, my + (y - my) * inset + dy) for x, y in pts)
    return Stroke(moved, closed=True, smooth=stroke.smooth, corners=stroke.corners)


def centroid(stroke: Stroke) -> Point:
    pts = stroke.points
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def samples(stroke: Stroke, step: float = 2.0) -> list[Point]:
    """Points along the stroke as the pen draws it (the spline, not just its
    vertices), about `step` apart: what to keep clear of, for `avoid`."""
    out: list[Point] = []
    d = to_d(stroke.points, stroke.closed, stroke.smooth, stroke.corners)
    for sub in polyline(d, steps=12):
        for (x0, y0), (x1, y1) in zip(sub, sub[1:]):
            n = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / step))
            out.extend((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n))
        out.append(sub[-1])
    return out


def rotate(pts: Iterable[Point], about: Point, angle: float) -> list[Point]:
    c, s = math.cos(angle), math.sin(angle)
    ax, ay = about
    return [(ax + (x - ax) * c - (y - ay) * s, ay + (x - ax) * s + (y - ay) * c) for x, y in pts]


# ── placement ───────────────────────────────────────────────────────────────

def clear_of(p: Point, avoid: Sequence[Circle]) -> bool:
    return all(math.dist(p, (x, y)) >= r for x, y, r in avoid)


class _Clearance:
    """`avoid` circles bucketed on a grid, so a placement asks only its
    neighbourhood: the ink of a whole tree is hundreds of circles."""

    def __init__(self, avoid: Sequence[Circle]):
        self.cell = max((r for _, _, r in avoid), default=1.0)
        self.grid: dict[tuple[int, int], list[Circle]] = {}
        for c in avoid:
            self.grid.setdefault((int(c[0] // self.cell), int(c[1] // self.cell)), []).append(c)

    def clear(self, p: Point) -> bool:
        gx, gy = int(p[0] // self.cell), int(p[1] // self.cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for x, y, r in self.grid.get((gx + dx, gy + dy), ()):
                    if (p[0] - x) ** 2 + (p[1] - y) ** 2 < r * r:
                        return False
        return True


def scatter(rng: Rng, count: int, cx: float, cy: float, rx: float, ry: float,
            gap: float, *, avoid: Sequence[Circle] = (), ok: Callable[[Point], bool] | None = None,
            tries: int = 600) -> list[Point]:
    """Up to `count` points inside an ellipse, at least `gap` apart, clear of
    `avoid` and passing `ok`. May return fewer: see `scatter_all`."""
    out: list[Point] = []
    room = _Clearance(avoid)
    for _ in range(tries):
        if len(out) == count:
            break
        a = rng.uniform(0, 2 * math.pi)
        r = math.sqrt(rng.random())
        p = (cx + rx * r * math.cos(a), cy + ry * r * math.sin(a))
        if all(math.dist(p, q) >= gap for q in out) and room.clear(p) and (ok is None or ok(p)):
            out.append(p)
    return out


def scatter_all(rng: Rng, count: int, cx: float, cy: float, rx: float, ry: float,
                gap: float, **kw) -> list[Point]:
    """Exactly `count` points: `scatter`, retried on fresh forks, then with the
    gap eased a step at a time. Deterministic for a given rng."""
    g = gap
    while True:
        for attempt in range(24):
            pts = scatter(rng.fork(f'try{attempt}|{g:.2f}'), count, cx, cy, rx, ry, g, **kw)
            if len(pts) == count:
                return pts
        g *= 0.94


def spread(points: Sequence[Point], start: Point) -> list[Point]:
    """The points in farthest-first order from `start`: each next one the
    farthest from those already taken, so the first few cover the picture."""
    left = list(points)
    first = min(left, key=lambda p: math.dist(p, start))
    order = [first]
    left.remove(first)
    while left:
        nxt = max(left, key=lambda p: min(math.dist(p, q) for q in order))
        order.append(nxt)
        left.remove(nxt)
    return order


def place_along(rng: Rng, count: int, x0: float, x1: float, *,
                avoid: Sequence[tuple[float, float]] = (), gap: float = 8.0, tries: int = 300) -> list[float]:
    """Up to `count` positions on [x0, x1], at least `gap` apart, outside every
    (from, to) span in `avoid`. Sorted."""
    out: list[float] = []
    for _ in range(tries):
        if len(out) == count:
            break
        x = rng.uniform(x0, x1)
        if any(a <= x <= b for a, b in avoid) or any(abs(x - q) < gap for q in out):
            continue
        out.append(x)
    return sorted(out)


# ── things ──────────────────────────────────────────────────────────────────

def sun(b: SketchBuilder, rng: Rng, cx: float, cy: float, r: float, *, when: Iterable = (),
        part: str = 'sun', rays: int = 6, ray_gap: float = 2.6, ray_len: float = 3.8) -> None:
    """A sun drawn by hand: a pen circle whose ends overlap, and a few uneven
    rays. Its reach is r + ray_gap + ray_len."""
    when = tuple(when)
    start = rng.uniform(0, 2 * math.pi)
    sweep = 2 * math.pi + 0.45
    disc = [(cx + r * math.cos(start + sweep * i / 11), cy + r * math.sin(start + sweep * i / 11))
            for i in range(12)]
    b.line(curve(*disc), when=when, part=part)
    base = rng.uniform(0, 2 * math.pi)
    for i in range(rays):
        a = base + 2 * math.pi * i / rays + rng.uniform(-0.14, 0.14)
        ln = ray_len * (1.0 if i % 2 == 0 else 0.62)
        r0 = r + ray_gap
        b.line(line((cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                    (cx + (r0 + ln) * math.cos(a), cy + (r0 + ln) * math.sin(a))), when=when, part=part)


def low_sun(b: SketchBuilder, rng: Rng, cx: float, cy: float, r: float, *, when: Iterable = (),
            part: str = 'sun') -> None:
    """A setting sun: the upper half of a disc resting on (cx, cy), three rays
    up. It draws no horizon of its own: set it on one the picture already has
    (a far hill, a window's rail), never on a ground with other things on it."""
    when = tuple(when)
    arc = [(cx + r * math.cos(math.pi + math.pi * i / 6), cy + r * math.sin(math.pi + math.pi * i / 6))
           for i in range(7)]
    b.line(curve(*arc), when=when, part=part)
    for i in range(3):
        a = math.pi + math.pi * (i + 1) / 4 + rng.uniform(-0.1, 0.1)
        b.line(line((cx + (r + 2.6) * math.cos(a), cy + (r + 2.6) * math.sin(a)),
                    (cx + (r + 5.6) * math.cos(a), cy + (r + 5.6) * math.sin(a))), when=when, part=part)


def _crescent(cx: float, cy: float, r: float, *, trimmed: bool = False) -> Stroke:
    """A crescent opening to the right. Trimmed, its lower horn is left out
    (a cloud passes in front of it there): an open stroke instead of a loop."""
    ox, rr = cx + 0.45 * r, 0.946 * r
    if not trimmed:
        outer = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                 for a in range(70, 291, 20)]
        inner = [(ox + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
                 for a in (263.4, 225, 180, 135, 96.6)]
        return loop(*outer, *inner[1:-1], corners=(0, len(outer) - 1))
    outer = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
             for a in (165, 190, 215, 240, 265, 290)]
    inner = [(ox + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
             for a in (250, 222, 196)]
    return curve(*outer, *inner, corners=(len(outer) - 1,))


def cloud(b: SketchBuilder, cx: float, cy: float, w: float, *, when: Iterable = (),
          part: str = 'cloud') -> None:
    """A cumulus in one pen stroke: up from the lower left, over four low
    bumps (the second the tallest), down the right, and back along a flat
    base that stops short of where it began. Weather, never a warning."""
    when = tuple(when)
    h = w * 0.36
    base = cy + h * 0.45
    bumps = ((-0.33, 0.13, 0.55), (-0.1, 0.17, 1.0), (0.14, 0.15, 0.8), (0.34, 0.11, 0.45))
    pts: list[Point] = [(cx - w * 0.47, base)]
    corners = []
    for i, (u, ru, hk) in enumerate(bumps):
        bx, by = cx + u * w, base - h * 0.62 * hk
        if i:
            corners.append(len(pts))
        for a in (195, 240, 290, 335):
            ang = math.radians(a)
            pts.append((bx + ru * w * math.cos(ang), by + ru * w * 0.95 * math.sin(ang)))
    corners.append(len(pts))
    pts.append((cx + w * 0.47, base))
    pts.append((cx - w * 0.3, base + 0.4))
    b.line(curve(*pts, corners=tuple(corners)), when=when, part=part)


def moon(b: SketchBuilder, cx: float, cy: float, r: float, *, when: Iterable = (),
         glow: bool = True, veiled: bool = True, part: str = 'moon', drift: int | None = None) -> None:
    """A crescent opening to the right. With `glow`, a soft light round it.
    With `veiled`, overdue work draws a cloud across its lower horn (the
    crescent is trimmed where the cloud passes, so ink never tangles), and a
    second, smaller cloud below it at two or more, drifting toward the nearer
    edge of the picture (`drift` -1 left, 1 right), away from the subject."""
    when = tuple(when)
    if drift is None:
        drift = -1 if cx < 80 else 1
    if glow:
        b.glow(ring(cx - r * 0.2, cy, r * 2.4, 12), when=when, part=part)
    if not veiled:
        b.line(_crescent(cx, cy, r), when=when, part=part)
        return
    b.line(_crescent(cx, cy, r), when=(*when, ('calm',)), part=part)
    b.line(_crescent(cx, cy, r, trimmed=True), when=(*when, ('overdue', 1)), part=part)
    cloud(b, cx + 0.15 * r, cy + 0.62 * r, 2.7 * r, when=(*when, ('overdue', 1)), part='cloud')
    cloud(b, cx + drift * 1.15 * r, cy + 2.3 * r, 2.0 * r, when=(*when, ('overdue', 2)), part='cloud')


def stars(b: SketchBuilder, rng: Rng, count: int, box: tuple[float, float, float, float], *,
          avoid: Sequence[Circle] = (), ok: Callable[[Point], bool] | None = None, gap: float = 14.0,
          when: Iterable = (), part: str = 'star') -> list[Point]:
    """Small four-stroke stars in `box` (x0, y0, x1, y1), apart from each other
    and clear of `avoid`. Returns where they went."""
    when = tuple(when)
    out: list[Point] = []
    for _ in range(400):
        if len(out) == count:
            break
        p = (rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3]))
        if any(math.dist(p, q) < gap for q in out) or not clear_of(p, avoid) or (ok and not ok(p)):
            continue
        out.append(p)
    for i, (x, y) in enumerate(out):
        s = rng.uniform(2.2, 3.0)
        b.line(line((x - s, y), (x + s, y)), when=when, part=f'{part}:{i}')
        b.line(line((x, y - s), (x, y + s)), when=when, part=f'{part}:{i}')
    return out


def glow_dot(b: SketchBuilder, x: float, y: float, r: float, *, halo: float, when: Iterable = (),
             part: str = 'light', glass: bool = True) -> None:
    """Something lit, with a soft glow round it: a coral core in its own ink
    ring (`glass`: a bulb, a lantern's flame), or a bare coral spark (a
    firefly: nothing but light)."""
    when = tuple(when)
    b.glow(ring(x, y, halo, 11), when=when, part=part)
    if glass:
        b.filled(ring(x, y, r, 9), when=when, part=part, paper='glint')
    else:
        b.accent(ring(x, y, r, 9), when=when, part=part, paper='glint')


def fruit(b: SketchBuilder, x: float, y: float, r: float, *, when: Iterable = (),
          part: str = 'fruit', stem: bool = False) -> None:
    """A coral fruit in its own ink ring, which holds its shape on light paper."""
    when = tuple(when)
    b.filled(ring(x, y, r, 9), when=when, part=part, paper='glint')
    if stem:
        b.line(line((x + 0.4, y - r), (x + 1.6, y - r - 2.6)), when=when, part=part)


def bird(b: SketchBuilder, x: float, y: float, *, when: Iterable = (), k_: float = 1.4,
         facing: int = 1, part: str = 'bird') -> None:
    """A small bird perched with its feet at (x, y)."""
    when = tuple(when)

    def p(dx: float, dy: float) -> Point:
        return (x + facing * dx * k_, y + (dy - 6) * k_)

    b.line(loop(p(-6, 0), p(0, -3.4), p(5, -1), p(2, 2.6), p(-4, 2.4)), when=when, part=part)
    b.line(loop(p(4, -3.6), p(7.2, -5.4), p(8.6, -2.6), p(6, -1.4)), when=when, part=part)
    b.line(line(p(8.6, -4), p(11, -3.4)), when=when, part=part)                 # beak
    b.line(line(p(-6, 0), p(-10.4, -2.6)), when=when, part=part)                # tail
    b.line(line(p(-1, 2.6), p(-1.4, 6)), when=when, part=part)
    b.line(line(p(1.6, 2.4), p(1.8, 6)), when=when, part=part)


def hatch(b: SketchBuilder, x0: float, y0: float, lengths: Sequence[float], gap: float, *,
          when: Iterable = (), part: str) -> None:
    """Parallel strokes from x0, the first at y0 and each next `gap` lower,
    with their own lengths (writing on a page, slats). ValueError when the
    strokes would fuse."""
    if gap < MIN_GAP:
        raise ValueError(f"parallel strokes {gap} apart fuse at phone size; keep them {MIN_GAP} apart")
    for i, ln in enumerate(lengths):
        y = y0 + i * gap
        b.line(line((x0, y), (x0 + ln, y + 0.3)), when=tuple(when), part=part)


def steam(b: SketchBuilder, x: float, y: float, frame: int, frames: int, height: float = 22,
          *, part: str = 'steam', when: Iterable = ()) -> None:
    """Two wisps rising from (x, y), one still frame of a loop of `frames`
    (frame 0 when drawn once, still)."""
    phase = 2 * math.pi * frame / frames
    for k, dx in enumerate((-3.2, 3.2)):
        pts = []
        for i in range(6):
            t = i / 5
            sway = math.sin(phase + t * 4 + k * 0.2) * (1.4 + t * 2.0)
            pts.append((x + dx + sway, y - t * height))
        b.line(curve(*pts), part=part, when=tuple(when))
