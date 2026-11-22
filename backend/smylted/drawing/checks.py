"""Checks every subject must pass, run by the tests over the roster: marks stay
in the frame, rewards are big enough to see, ink never crosses ink by accident,
and the night is its own picture.

Nothing here runs in production; it reads the paths a sketch already holds.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .pen import PEN, WOBBLE

if TYPE_CHECKING:
    from .scene import Sketch

Point = tuple[float, float]

MIN_REWARD_ACROSS = 10.0
MIN_REWARD_AREA = 60.0
# The smallest light a night may stand on: a glow of this many square units
# (a ring of radius about 14) that shows whatever the state.
MIN_NIGHT_LIGHT = 600.0
# A night is the same place after dark, not the day recoloured: at most this
# share of its marks may sit where a day mark does, and at least this many must
# be its own (the light, the moon, what only comes out at night). A recolour
# scores 1.0 with none of its own. The approved desk, the same room with its
# lamp on, is about 0.85.
MAX_NIGHT_OVERLAP = 0.90
MIN_NIGHT_OWN = 4
# Two marks are in the same place when every side of one's box is within this
# of the other's: both boils' wobble and a unit to spare. A mark the night
# reuses then matches however its hand was jittered and in whatever order it
# was drawn: an exact match on rounded boxes counted a reused mark as new
# whenever its jitter crossed a rounding line, which drawing it later did.
NIGHT_MATCH = 2 * WOBBLE + 1.0

# Ink samples are at most this far apart when crossings are looked for.
_SAMPLE = 0.5


def _tokens(d: str) -> list[tuple[str, list[float]]]:
    """The commands of a path as (letter, numbers)."""
    out: list[tuple[str, list[float]]] = []
    for tok in d.split():
        if tok in ("M", "L", "C", "Z"):
            out.append((tok, []))
        else:
            out[-1][1].append(float(tok))
    return out


def endpoints(d: str) -> list[Point]:
    """The on-curve points of a path: the pair after M, after each L, and the
    last pair of each C (its two control points are skipped)."""
    pts: list[Point] = []
    for cmd, nums in _tokens(d):
        if cmd in ("M", "L", "C") and len(nums) >= 2:
            pts.append((nums[-2], nums[-1]))
    return pts


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    a, b, c, e = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1])


def polyline(d: str, steps: int = 12) -> list[list[Point]]:
    """The path flattened, one list of points per subpath. Each C is sampled at
    `steps` points; Z closes back to the start of its subpath."""
    paths: list[list[Point]] = []
    cur: list[Point] = []
    for cmd, nums in _tokens(d):
        if cmd == "M":
            cur = [(nums[0], nums[1])]
            paths.append(cur)
        elif cmd == "L":
            cur.append((nums[0], nums[1]))
        elif cmd == "C":
            p0 = cur[-1]
            p1, p2, p3 = (nums[0], nums[1]), (nums[2], nums[3]), (nums[4], nums[5])
            cur.extend(_bezier(p0, p1, p2, p3, j / steps) for j in range(1, steps + 1))
        elif cmd == "Z" and cur:
            cur.append(cur[0])
    return paths


def _every_mark(sketch: Sketch):
    yield from sketch.marks
    if sketch.ambient is not None:
        for frame in sketch.ambient.frames:
            yield from frame


def bounds_errors(sketch: Sketch, margin: float | None = None) -> list[str]:
    """One message for each mark with an on-curve point outside the view box by
    more than `margin` (the wobble and a unit, by default)."""
    if margin is None:
        margin = WOBBLE + 1.0
    x0, y0, w, h = sketch.view_box
    errors = []
    for mark in _every_mark(sketch):
        bad = next(
            ((x, y) for d in mark.frames for x, y in endpoints(d)
             if not (x0 - margin <= x <= x0 + w + margin
                     and y0 - margin <= y <= y0 + h + margin)),
            None)
        if bad is not None:
            errors.append(f"{mark.id} ({mark.part}) leaves the frame at "
                          f"({bad[0]:.1f}, {bad[1]:.1f})")
    return errors


# A wash is a plate of colour under the ink. Cut by the frame it shows the
# frame: a straight, jagged edge the picture never drew (a headland running off
# the bottom, a lawn as a band across the width). Every wash closes inside the
# picture, this far from each edge; the subjects that read best keep 6.4 or more.
WASH_MARGIN = 6.0


def wash_edge_errors(sketch: Sketch, margin: float = WASH_MARGIN) -> list[str]:
    """One message for each wash with an on-curve point nearer than `margin`
    to an edge of the view box, on any frame (the focus loop's included)."""
    x0, y0, w, h = sketch.view_box
    errors = []
    for mark in _every_mark(sketch):
        if mark.role != 'wash':
            continue
        bad = next(
            ((x, y) for d in mark.frames for x, y in endpoints(d)
             if not (x0 + margin <= x <= x0 + w - margin
                     and y0 + margin <= y <= y0 + h - margin)),
            None)
        if bad is not None:
            errors.append(f"{mark.id} ({mark.part}) reaches the frame at "
                          f"({bad[0]:.1f}, {bad[1]:.1f})")
    return errors


def _area(pts: list[Point]) -> float:
    total = 0.0
    for i, (x, y) in enumerate(pts):
        nx, ny = pts[(i + 1) % len(pts)]
        total += x * ny - nx * y
    return abs(total) / 2


def reward_sizes(sketch: Sketch) -> dict[int, tuple[float, float]]:
    """For each reward, over its accent marks: the largest side of their
    bounding box, and the area they cover (the shoelace area of each mark's
    first frame, summed)."""
    pts: dict[int, list[Point]] = {}
    area: dict[int, float] = {}
    for mark in sketch.marks:
        if mark.role != 'accent' or mark.reward is None:
            continue
        ends = endpoints(mark.frames[0])
        pts.setdefault(mark.reward, []).extend(ends)
        area[mark.reward] = area.get(mark.reward, 0.0) + (_area(ends) if ends else 0.0)
    out = {}
    for reward, ps in pts.items():
        xs = [p[0] for p in ps]
        ys = [p[1] for p in ps]
        across = max(max(xs) - min(xs), max(ys) - min(ys)) if ps else 0.0
        out[reward] = (across, area[reward])
    return out


def _resample(path: list[Point]) -> list[Point]:
    out: list[Point] = []
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        n = max(1, math.ceil(math.hypot(bx - ax, by - ay) / _SAMPLE))
        out.extend((ax + (bx - ax) * j / n, ay + (by - ay) * j / n) for j in range(n))
    if path:
        out.append(path[-1])
    return out


def _base(part: str) -> str:
    return part.split(':')[0]


def crossings(sketch: Sketch, joins=frozenset(), *, gap: float = PEN
              ) -> list[tuple[str, str, Point]]:
    """Ink that touches by accident: pairs of parts whose ink comes within `gap`
    of each other, centre to centre (by default one pen width, where the edges
    of two lines meet). Two marks may touch when they are the same part, or
    when the pair of their base names (the part before any ':') is in `joins`;
    a join of one name lets two different parts of that name touch. Two
    different REWARDS never may, joined or not: each reward is its own mark.

    Ink is every line that is on, and every coral fill that is on with no line
    of its own part (a bare spark is still a mark). Each boil frame is checked
    with its own frame of every other line (they are shown together), and every
    frame of the focus loop, while it runs, against every boil frame: a
    collision for a sixth of a second is still one someone sees. Each pair of
    parts is reported once, with one example point."""
    lines = [m for m in sketch.marks if m.role == 'line' and m.on]
    inked = {m.part for m in lines}
    bare = [m for m in sketch.marks if m.role == 'accent' and m.on and m.part not in inked]
    still = lines + bare
    loop = []
    if sketch.ambient is not None:
        for frame in sketch.ambient.frames:
            marks = [m for m in frame if m.role in ('line', 'accent') and m.on]
            if marks:
                loop.append(marks)

    def path(mark, k: int) -> str:
        return mark.frames[k] if len(mark.frames) == 3 else mark.frames[0]

    def grid(marks: list, k: int) -> dict[tuple[int, int], list[tuple[int, Point]]]:
        cells: dict[tuple[int, int], list[tuple[int, Point]]] = {}
        for idx, mark in enumerate(marks):
            for sub in polyline(path(mark, k)):
                for p in _resample(sub):
                    cells.setdefault((math.floor(p[0] / gap), math.floor(p[1] / gap)),
                                     []).append((idx, p))
        return cells

    found: dict[tuple[str, str], Point] = {}

    def may_touch(ma, mb) -> bool:
        if ma.reward is not None and mb.reward is not None and ma.reward != mb.reward:
            return False
        a, b = ma.part, mb.part
        return a == b or frozenset((_base(a), _base(b))) in joins

    def compare(cells_a, marks_a, cells_b, marks_b, same: bool) -> None:
        seen: set[tuple[int, int]] = set()
        for (cx, cy), items in cells_a.items():
            for idx, p in items:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for jdx, q in cells_b.get((cx + dx, cy + dy), ()):
                            if same and jdx <= idx:
                                continue
                            key = (idx, jdx)
                            if key in seen:
                                continue
                            if may_touch(marks_a[idx], marks_b[jdx]):
                                seen.add(key)
                                continue
                            if math.dist(p, q) < gap:
                                seen.add(key)
                                found.setdefault(tuple(sorted((marks_a[idx].part, marks_b[jdx].part))), p)

    still_grids = [grid(still, k) for k in range(3)]
    for k in range(3):
        compare(still_grids[k], still, still_grids[k], still, True)
    for frame in loop:
        frame_cells = grid(frame, 0)
        compare(frame_cells, frame, frame_cells, frame, True)
        for k in range(3):
            compare(frame_cells, frame, still_grids[k], still, False)
    return [(a, b, p) for (a, b), p in sorted(found.items())]


def _box(mark) -> tuple[float, float, float, float] | None:
    pts = endpoints(mark.frames[0])
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _night_matches(light: Sketch, dark: Sketch) -> list[bool]:
    """For each dark mark, whether a light mark sits in the same place (every
    side of their first frames' boxes within NIGHT_MATCH). A mark with no
    points matches nothing."""
    cell = NIGHT_MATCH
    grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    for m in light.marks:
        b = _box(m)
        if b is not None:
            grid.setdefault((int(b[0] // cell), int(b[1] // cell)), []).append(b)
    out = []
    for m in dark.marks:
        b = _box(m)
        hit = False
        if b is not None:
            gx, gy = int(b[0] // cell), int(b[1] // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for l in grid.get((gx + dx, gy + dy), ()):
                        if all(abs(u - v) <= NIGHT_MATCH for u, v in zip(b, l)):
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
        out.append(hit)
    return out


def night_overlap(light: Sketch, dark: Sketch) -> float:
    """The share of the dark marks that sit where a light mark does. A night
    that reuses every one of the day's marks scores 1, in any order."""
    hits = _night_matches(light, dark)
    return sum(hits) / len(hits) if hits else 0.0


def night_own(light: Sketch, dark: Sketch) -> int:
    """How many dark marks sit where no light mark does: the night's own."""
    return sum(1 for hit in _night_matches(light, dark) if not hit)


def is_own_night(light: Sketch, dark: Sketch) -> bool:
    """The night rule: at most MAX_NIGHT_OVERLAP of the night reused from the
    day, and at least MIN_NIGHT_OWN marks of its own."""
    hits = _night_matches(light, dark)
    if not hits:
        return False
    return (sum(hits) / len(hits) <= MAX_NIGHT_OVERLAP
            and len(hits) - sum(hits) >= MIN_NIGHT_OWN)


def has_standing_light(dark: Sketch) -> bool:
    """True when the night has a light that shows whatever the state: a glow
    (not a wash, which is paint, not light) of at least MIN_NIGHT_LIGHT square
    units."""
    return any(m.role == 'glow' and not m.when and _area(endpoints(m.frames[0])) >= MIN_NIGHT_LIGHT
               for m in dark.marks)
