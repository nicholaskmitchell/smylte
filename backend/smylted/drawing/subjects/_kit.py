"""Shared pieces for the subjects: the shapes and the rules more than one picture uses.

Everything here is geometry. Paint is a role chosen at the call site (line,
wash, glow, accent); motion is the client's. The canvas is the builder's
viewBox, 160 x 200, portrait, y growing downward.

Rules for a subject. The tests hold every subject to four of them, over a week
of days under two salts, both themes and every hour (tests/test_drawing.py): it
stays in its frame; every reward is at least 10 units across and 60 units^2 of
coral; ink touches ink only where JOINS says, measured at the pen's own width
(PEN) on every boil frame and every frame of the focus loop, and two rewards
never touch at all; and the night is its own picture: at most 90% of its marks
where a day mark is, at least four of its own (checks.is_own_night), and a glow
of at least 600 units^2 that is always on. The rest are this kit's conventions, which the
tests cannot see:

* Fill the frame, as the mockup's tree does: the subject is the picture, not a
  vignette in a corner of sky. Nothing leaves the frame.
* The wash is the subject's own outline, shifted down and right like a print
  plate a little off register: `wash_of`. At night the wash stays under the
  subject, and light is a `glow`.
* A reward is a coral fill inside its own ink outline, drawn by `b.filled` (the
  two register, and the outline holds still while the picture boils), at least
  10 units across. Fill the slots in `spread` order, so three or four rewards
  already cover the picture (or in reading order, where a full row reads as
  done, like the desk's notes), and `b.anchor` each reward where it grows from.
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
  sheets. Never red, never heavy. A cloud by a night moon comes from `moon`,
  beside it and never under it; keep other things clear of the circles it
  returns. Where there is no room for a cloud that reads, pass `clouds=0`.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from ..checks import polyline
from ..pen import PEN, WOBBLE, Stroke, curve, line, loop, to_d
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
    """A leaf's outline, from its stalk end (cx, cy) along `angle` (radians):
    fuller on one side than the other, as a leaf is, with a point at the tip.
    `draw_leaf` adds the stalk."""
    ca, sa = math.cos(angle), math.sin(angle)

    def at(u: float, v: float) -> Point:
        return (cx + u * ca - v * sa, cy + u * sa + v * ca)

    L = length
    return loop(at(0.14 * L, 0), at(0.42 * L, 0.30 * L), at(L, 0), at(0.55 * L, -0.20 * L), corners=(0, 2))


def draw_leaf(b: SketchBuilder, cx: float, cy: float, length: float, angle: float, *,
              when: Iterable = (), part: str = 'leaf') -> None:
    """A leaf and its stalk, one part."""
    when = tuple(when)
    b.line(leaf(cx, cy, length, angle), when=when, part=part)
    tip = (cx + 0.14 * length * math.cos(angle), cy + 0.14 * length * math.sin(angle))
    b.line(line((cx, cy), tip), when=when, part=part)


def leaf_low(length: float, angle: float) -> float:
    """How far below its stalk end a leaf at `angle` reaches: set a leaf on a
    line by raising it this much, so it rests on the line instead of crossing it."""
    pts = leaf(0, 0, length, angle).points
    return max(0.0, *(y for _, y in pts))


def wash_of(stroke: Stroke, *, inset: float = 0.93, dx: float = 4.0, dy: float = 4.0) -> Stroke:
    """The wash under an outline: the same shape, a little smaller, shifted down
    and right like a print plate off register. The mockup shifts its wash 3
    units in a 96-unit drawing, about 5 in ours; 4 keeps it a touch tighter."""
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


# Candidate points drawn per point `scatter_all` places, and the attempts it
# makes at one gap before easing it.
CANDIDATES = 120
ATTEMPTS = 24


class _Clearance:
    """`avoid` circles bucketed on a grid, each in every cell it overlaps, so
    a placement asks only its own cell: the ink of a whole tree is hundreds
    of circles. The cell is about one avoid circle across: smaller cells make
    each circle land in many more of them, larger ones make each query test
    more circles. The test itself is exact either way."""

    CELL = 12.0

    def __init__(self, avoid: Sequence[Circle]):
        self.grid: dict[tuple[int, int], list[tuple[Point, float]]] = {}
        c = self.CELL
        for x, y, r in avoid:
            circle = ((x, y), r)
            for gx in range(math.floor((x - r) / c), math.floor((x + r) / c) + 1):
                for gy in range(math.floor((y - r) / c), math.floor((y + r) / c) + 1):
                    self.grid.setdefault((gx, gy), []).append(circle)

    def clear(self, p: Point) -> bool:
        px, py = p
        c = self.CELL
        for center, radius in self.grid.get((math.floor(px / c), math.floor(py / c)), ()):
            if math.dist(p, center) < radius:
                return False
        return True


def apart(r: float) -> float:
    """How far apart the centres of two round rewards of radius `r` must be so
    their ink never touches: both radii, a pen between them, and the wobble of
    each."""
    return 2 * r + PEN + 2 * WOBBLE


def scatter_all(rng: Rng, count: int, cx: float, cy: float, rx: float, ry: float,
                gap: float, *, avoid: Sequence[Circle] = (),
                ok: Callable[[Point], bool] | None = None,
                floor: float | None = None) -> list[Point]:
    """Exactly `count` points inside an ellipse, at least `gap` apart, clear of
    `avoid` and passing `ok`.

    Candidates are drawn once, CANDIDATES per point wanted, and each is tested
    against `avoid` and `ok` once. An attempt then picks a candidate at random,
    drops every candidate within `gap` of it, and repeats (random sequential
    addition), so it costs a few list passes however crowded the subject is:
    the tree's fruit used to take a dozen attempts of 600 dart throws each, and
    the render ran past its time budget. After ATTEMPTS failures the gap eases a
    step at a time, down to `floor` (by default half the gap) and never below. For rewards
    the floor is where two of them would touch: twice their radius, a pen and
    the wobble of both. Deterministic for a given rng. ValueError when even
    that cannot place them all: the subject's constraints leave no room, and
    that is a subject to fix, not a day to hang."""
    floor = gap * 0.5 if floor is None else floor
    room = _Clearance(avoid)
    draw = rng.fork('candidates')
    candidates: list[Point] = []
    for _ in range(count * CANDIDATES):
        a = draw.uniform(0, 2 * math.pi)
        r = math.sqrt(draw.random())
        p = (cx + rx * r * math.cos(a), cy + ry * r * math.sin(a))
        if room.clear(p) and (ok is None or ok(p)):
            candidates.append(p)
    g = gap
    while True:
        for attempt in range(ATTEMPTS):
            pick = rng.fork(f'order{attempt}|{g:.2f}')
            left = candidates
            out: list[Point] = []
            while left and len(out) < count:
                point = left[int(pick.random() * len(left))]
                out.append(point)
                left = [q for q in left if math.dist(q, point) >= g]
            if len(out) == count:
                return out
        if g <= floor:
            break
        # The floor itself is the last gap tried: easing straight past it
        # (19 to 17.9 against a floor of 18.75) left a crowded tree no second
        # level at all, and that day's drawing failed.
        g = max(g * 0.94, floor)
    raise ValueError(f"cannot place {count} points {floor:.1f} or more apart under these constraints")


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
        ln = ray_len * (1.0 if i % 2 == 0 else 0.75)
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


def _crescent(cx: float, cy: float, r: float) -> Stroke:
    """A crescent opening to the right, its two horns sharp."""
    ox, rr = cx + 0.45 * r, 0.946 * r
    outer = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
             for a in range(70, 291, 20)]
    inner = [(ox + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
             for a in (263.4, 225, 180, 135, 96.6)]
    return loop(*outer, *inner[1:-1], corners=(0, len(outer) - 1))


# A cloud's bumps by how wide it is, so no bump is narrower than the pen:
# (centre u, radius u, height), in widths of the cloud.
# The smallest cloud by a night moon: three bumps.
MOON_CLOUD = 22.0

_CLOUD_BUMPS = {
    4: ((-0.33, 0.13, 0.55), (-0.1, 0.17, 1.0), (0.14, 0.15, 0.8), (0.34, 0.11, 0.45)),
    3: ((-0.27, 0.18, 0.8), (0.0, 0.22, 1.0), (0.27, 0.16, 0.6)),
    2: ((-0.2, 0.26, 1.0), (0.2, 0.22, 0.8)),
}


def _upper_meet(c1, c2):
    """Where two circles cross, the upper of the two points (or None)."""
    (x1, y1, r1), (x2, y2, r2) = c1, c2
    d = math.dist((x1, y1), (x2, y2))
    if d == 0 or d > r1 + r2 or d < abs(r1 - r2):
        return None
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    mx, my = x1 + a * (x2 - x1) / d, y1 + a * (y2 - y1) / d
    p = (mx + h * (y2 - y1) / d, my - h * (x2 - x1) / d)
    q = (mx - h * (y2 - y1) / d, my + h * (x2 - x1) / d)
    return p if p[1] < q[1] else q


def cloud(b: SketchBuilder, cx: float, cy: float, w: float, *, when: Iterable = (),
          part: str = 'cloud') -> None:
    """A cumulus in one pen stroke: up from the lower left, over its bumps
    (meeting at sharp cusps, never doubling back), down the right, and back
    along a flat base that stops short of where it began. Two bumps under 22
    units wide, three under 34, four above, so no bump is narrower than the
    pen. Weather, never a warning."""
    when = tuple(when)
    h = w * 0.36
    base = cy + h * 0.45
    table = _CLOUD_BUMPS[4 if w >= 34 else 3 if w >= 22 else 2]
    circles = [(cx + u * w, base - h * 0.62 * hk, ru * w) for u, ru, hk in table]
    if min(r for _, _, r in circles) < PEN:
        raise ValueError(f"a cloud {w:.1f} wide has bumps narrower than the pen")
    meets = [_upper_meet(circles[i], circles[i + 1]) for i in range(len(circles) - 1)]
    x0, y0, r0 = circles[0]
    pts: list[Point] = [(x0 - r0 * 0.9, base)]
    corners = [0]
    for i, (bx, by, r) in enumerate(circles):
        lo = math.pi + 0.35 if i == 0 else math.atan2(meets[i - 1][1] - by, meets[i - 1][0] - bx)
        hi = 2 * math.pi - 0.35 if i == len(circles) - 1 else math.atan2(meets[i][1] - by, meets[i][0] - bx)
        if lo < 0:
            lo += 2 * math.pi
        if hi < 0:
            hi += 2 * math.pi
        for k_ in (1, 2):
            a = lo + (hi - lo) * k_ / 3
            pts.append((bx + r * math.cos(a), by + r * math.sin(a)))
        if i < len(circles) - 1:
            corners.append(len(pts))
            pts.append(meets[i])
    xn, yn, rn = circles[-1]
    corners.append(len(pts))
    pts.append((xn + rn * 0.9, base))
    pts.append((cx - w * 0.28, base + 0.4))
    b.line(curve(*pts, corners=tuple(corners)), when=when, part=part)


def moon(b: SketchBuilder, cx: float, cy: float, r: float, *, when: Iterable = (),
         glow: bool = True, clouds: int = 2, part: str = 'moon',
         first: tuple[float, float] | None = None,
         second: tuple[float, float] | None = None) -> list[Circle]:
    """A crescent opening to the right, always whole. With `glow`, a soft
    light round it. With `clouds` 1 or 2, overdue work draws a cloud beside it,
    toward the picture, and with 2, at two or more a second a step below and
    beyond the first. Weather near the moon, never ink across it, and never
    straight under it, where a small cloud and the crescent read as a little
    figure. Each cloud is at least MOON_CLOUD units wide, three bumps: a
    smaller one reads as a speck at phone size. Where there is no room for that
    (a window pane, a crown that fills the sky), pass `clouds=0` and show
    overdue work some other way.

    `first` and `second` place the clouds in moon radii from its centre. By
    default they are measured from the clouds' own size instead: a cloud is
    never narrower than MOON_CLOUD, so offsets in a small moon's radius would
    run its clouds into it and into each other.

    Returns a circle round each cloud it may draw (none with `clouds=0`), so
    the subject's stars and other scattered things can keep clear of them. The
    two clouds are parts `cloud:1` and `cloud:2`, so the crossing check sees
    them if they ever touch."""
    when = tuple(when)
    if glow:
        b.glow(ring(cx - r * 0.2, cy, r * 2.4, 12), when=when, part=part)
    b.line(_crescent(cx, cy, r), when=when, part=part)
    if clouds not in (0, 1, 2):
        raise ValueError(f"a moon has 0, 1 or 2 clouds, not {clouds!r}")
    if not clouds:
        return []
    toward = 1 if cx < 80 else -1
    size = max(r, MOON_CLOUD / 3.4)            # the radius the clouds are sized for
    w = 3.4 * size
    fx, fy = (toward * 3.3 * size, 0.5 * size) if first is None else (first[0] * r, first[1] * r)
    sx, sy = (toward * 5.2 * size, 2.7 * size) if second is None else (second[0] * r, second[1] * r)
    reach = 0.5 * w + 4.0                      # half the cloud and a margin
    out: list[Circle] = [(cx + fx, cy + fy, reach)]
    cloud(b, cx + fx, cy + fy, w, when=(*when, ('overdue', 1)), part='cloud:1')
    if clouds == 2:
        cloud(b, cx + sx, cy + sy, w, when=(*when, ('overdue', 2)), part='cloud:2')
        out.append((cx + sx, cy + sy, reach))
    return out


def stars(b: SketchBuilder, rng: Rng, count: int, box: tuple[float, float, float, float], *,
          avoid: Sequence[Circle] = (), ok: Callable[[Point], bool] | None = None, gap: float = 14.0,
          when: Iterable = (), part: str = 'star') -> list[Point]:
    """Small four-stroke stars in `box` (x0, y0, x1, y1), apart from each other
    and clear of `avoid` and `ok` by their whole reach (arms, ink and wobble),
    not just their centres. Returns where they went."""
    when = tuple(when)
    reach = 3.0 + PEN / 2 + WOBBLE
    ring8 = [(reach * math.cos(math.pi * i / 4), reach * math.sin(math.pi * i / 4)) for i in range(8)]
    out: list[Point] = []
    for _ in range(400):
        if len(out) == count:
            break
        p = (rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3]))
        if any(math.dist(p, q) < gap for q in out):
            continue
        around = [p] + [(p[0] + dx, p[1] + dy) for dx, dy in ring8]
        if not all(clear_of(q, avoid) and (ok is None or ok(q)) for q in around):
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


def bird_strokes(x: float, y: float, *, k_: float = 1.4, facing: int = 1) -> list[Stroke]:
    """The strokes of a small bird perched with its feet at (x, y): what `bird`
    draws, so a subject can keep other things clear of the bird's own ink."""
    def p(dx: float, dy: float) -> Point:
        return (x + facing * dx * k_, y + (dy - 6) * k_)

    return [
        loop(p(-6, 0), p(0, -3.4), p(5, -1), p(2, 2.6), p(-4, 2.4)),
        loop(p(4, -3.6), p(7.2, -5.4), p(8.6, -2.6), p(6, -1.4)),
        line(p(8.6, -4), p(11, -3.4)),                 # beak
        line(p(-6, 0), p(-10.4, -2.6)),                # tail
        line(p(-1, 2.6), p(-1.4, 6)),
        line(p(1.6, 2.4), p(1.8, 6)),
    ]


def bird(b: SketchBuilder, x: float, y: float, *, when: Iterable = (), k_: float = 1.4,
         facing: int = 1, part: str = 'bird') -> None:
    """A small bird perched with its feet at (x, y)."""
    when = tuple(when)
    for stroke in bird_strokes(x, y, k_=k_, facing=facing):
        b.line(stroke, when=when, part=part)


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
