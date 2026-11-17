"""A clipboard: the Tasks view's drawing, for a list with nothing left on it.

Day: a clipboard standing a little tilted, a sheet clipped to it with four
rows, every box ticked, and the coral pencil set down across the board's lower
right corner.

Night: the same clipboard and pencil under a desk lamp reaching in from the
left; its light falls from the shade over the top of the sheet, and there are
stars in the corner the lamp does not reach.
"""
from __future__ import annotations

import math
from functools import cache

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

Point = tuple[float, float]

# The clipboard is drawn upright and turned about its centre as one object.
CENTRE = (80.0, 108.0)
TILT = math.radians(-4)
BOARD = (36.0, 32.0, 124.0, 184.0)
BOARD_R = 7.0
INSET = 8.0
CLIP = (65.0, 25.0, 95.0, 45.0)
HOLE = (80.0, 33.0, 2.6)
BOX = 10.0
ROWS = (62.0, 88.0, 114.0, 140.0)
BOX_X = 51.0
WRITE_X = 67.0
WRITING = (40.0, 36.0, 42.0, 38.0)
# The pencil, from the point of its lead: down and to the right, out past the
# board's corner. Lengths along it: the cone, the coral body, the ferrule, the
# eraser; and half its width.
PENCIL_TIP = (86.0, 154.0)
PENCIL_ANGLE = math.radians(33)
CONE, BODY, FERRULE, ERASER = 10.0, 50.0, 6.0, 4.0
HALF = 4.5
# The lamp's shade: the middle of its narrow end, the way it faces, and its depth.
SHADE_TOP = (14.0, 9.0)
SHADE_ANGLE = math.radians(40)
SHADE_DEEP = 16.0


class Clipboard:
    id = 'clipboard'
    JOINS = frozenset(frozenset(p) for p in (
        ('clip', 'board'), ('clip', 'paper'), ('tick', 'box'),
        ('pencil', 'board'), ('pencil', 'paper'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, still=True)
        if theme == 'dark':
            _lamp(b)
        _clipboard(b)
        if theme == 'dark':
            _stars(b, rng.fork('stars'))
        return b.build(state)


def _turn(pts) -> list[Point]:
    return k.rotate(pts, CENTRE, TILT)


def _rounded(x0: float, y0: float, x1: float, y1: float, r0: float, r1: float | None = None
             ) -> tuple[list[Point], list[int]]:
    """A rounded rectangle's points, clockwise from the right end of its top, and the
    indices where its straight sides meet its corners (r0 the top corners, r1
    the bottom ones)."""
    r1 = r0 if r1 is None else r1
    pts: list[Point] = []
    tangents: list[int] = []
    for (cx, cy, r, a0) in ((x1 - r0, y0 + r0, r0, -90), (x1 - r1, y1 - r1, r1, 0),
                            (x0 + r1, y1 - r1, r1, 90), (x0 + r0, y0 + r0, r0, 180)):
        for i, da in enumerate((0, 45, 90)):
            a = math.radians(a0 + da)
            if i != 1:
                tangents.append(len(pts))
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts, tangents


def _inside(p: Point, poly: list[Point]) -> bool:
    x, y = p
    hit = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def _uncovered(pts: list[Point], keep: list[int], covers: list[list[Point]]
               ) -> list[tuple[list[Point], list[int]]]:
    """The runs of a closed outline that no cover lies over, each with the
    indices (in the run) of the outline's points in `keep`. A cut ends where
    the outline meets the cover's edge: the line goes under the thing on top."""
    def bare(p: Point) -> bool:
        return not any(_inside(p, c) for c in covers)

    n = len(pts)
    start = next(i for i in range(n) if bare(pts[i]))
    order = [(start + i) % n for i in range(n + 1)]
    runs: list[tuple[list[Point], list[int]]] = []
    cur: list[Point] | None = [pts[start]]
    marks: list[int] = [0] if start in keep else []
    for ia, ib in zip(order, order[1:]):
        a, b_ = pts[ia], pts[ib]
        steps = max(1, math.ceil(math.dist(a, b_) / 0.4))
        last = a
        for j in range(1, steps + 1):
            q = (a[0] + (b_[0] - a[0]) * j / steps, a[1] + (b_[1] - a[1]) * j / steps)
            if cur is not None and not bare(q):
                if last != cur[-1]:
                    cur.append(last)
                runs.append((cur, marks))
                cur, marks = None, []
            elif cur is None and bare(q):
                cur, marks = [q], []
            last = q
        if cur is not None:
            if ib in keep and ib != start:
                marks.append(len(cur))
            if cur[-1] != b_:
                cur.append(b_)
    if cur is not None:
        if runs and runs[0][0][0] == pts[start]:
            first, fmarks = runs.pop(0)
            off = len(cur) - 1
            cur = cur + first[1:]
            marks = marks + ([off] if start in keep else []) + [m + off for m in fmarks if m > 0]
        runs.append((cur, marks))
    return runs


def _pencil_frame():
    ca, sa = math.cos(PENCIL_ANGLE), math.sin(PENCIL_ANGLE)
    tx, ty = PENCIL_TIP

    def at(u: float, v: float) -> Point:
        return (tx + u * ca - v * sa, ty + u * sa + v * ca)
    return at


def _pencil_cover() -> list[Point]:
    at = _pencil_frame()
    end = CONE + BODY + FERRULE
    return [at(0, 0), at(CONE, -HALF), at(end, -HALF), at(end + ERASER * 0.8, -HALF * 0.8),
            at(end + ERASER, 0), at(end + ERASER * 0.8, HALF * 0.8), at(end, HALF), at(CONE, HALF)]


def _clip_outline() -> tuple[list[Point], list[int]]:
    return _rounded(*CLIP, 5.5, 3.0)


def _board_outline() -> tuple[list[Point], list[int]]:
    return _rounded(*BOARD, BOARD_R)


def _paper_outline() -> list[Point]:
    x0, y0, x1, y1 = BOARD
    return [(x0 + INSET, y0 + INSET), (x1 - INSET, y0 + INSET), (x1 - INSET, y1 - INSET),
            (x0 + INSET, y1 - INSET)]


@cache
def _surfaces():
    """Clip the fixed outlines once. The pen still draws them for each seed."""
    board, tangents = _board_outline()
    clip, clip_corners = _clip_outline()
    pencil = _pencil_cover()
    paper = _paper_outline()
    return (
        k.wash_of(loop(*_turn(board), corners=tangents)),
        tuple(curve(*_turn(run), corners=corners)
              for run, corners in _uncovered(board, tangents, [clip, pencil])),
        tuple(curve(*_turn(run), corners=range(len(run)))
              for run, _ in _uncovered(paper, [0, 1, 2, 3], [clip, pencil])),
        loop(*_turn(clip), corners=clip_corners),
    )


def _clipboard(b: SketchBuilder) -> None:
    wash, board, paper, clip = _surfaces()
    b.wash(wash, part='board')
    for stroke in board:
        b.line(stroke, part='board')
    for stroke in paper:
        b.line(stroke, part='paper')
    b.line(clip, part='clip')
    hx, hy, hr = HOLE
    b.line(loop(*_turn(k.ring(hx, hy, hr, 8).points)), part='clip')
    for cy, length in zip(ROWS, WRITING):
        h = BOX / 2
        box = [(BOX_X, cy - h), (BOX_X + BOX, cy - h), (BOX_X + BOX, cy + h), (BOX_X, cy + h)]
        b.line(curve(*_turn(box + box[:1]), corners=range(5)), part='box')
        b.line(line(*_turn(((BOX_X + 1.6, cy - 0.4), (BOX_X + 4.6, cy + 3.2),
                            (BOX_X + BOX + 3.2, cy - h - 3.6)))), part='tick')
        wave = [(WRITE_X + length * i / 4, cy + 0.9 * math.sin(i * 1.7 + cy)) for i in range(5)]
        b.line(curve(*_turn(wave)), part='writing')
    _pencil(b)


def _pencil(b: SketchBuilder) -> None:
    at = _pencil_frame()
    a, z = CONE, CONE + BODY
    # The coral body: its sharpened end a shallow point, the paint ending
    # where the wood begins.
    body = [at(a, -HALF), at(z, -HALF), at(z, HALF), at(a, HALF), at(a - 2.4, 1.6),
            at(a - 2.4, -1.6)]
    b.filled(loop(*_turn(body), corners=range(len(body))), part='pencil')
    b.line(line(*_turn((at(a - 2.4, 0), at(z, 0)))), part='pencil')
    b.line(line(*_turn((at(a, -HALF), at(0, 0), at(a, HALF)))), part='pencil')
    b.line(line(*_turn((at(3.4, -1.3), at(3.4, 1.3)))), part='pencil')
    f = z + FERRULE
    b.line(line(*_turn((at(z, -HALF), at(f, -HALF), at(f, HALF), at(z, HALF)))), part='pencil')
    b.line(curve(*_turn((at(f, -HALF * 0.85), at(f + ERASER * 0.8, -HALF * 0.75),
                         at(f + ERASER, 0), at(f + ERASER * 0.8, HALF * 0.75),
                         at(f, HALF * 0.85)))), part='pencil')


def _lamp(b: SketchBuilder) -> None:
    """A desk lamp reaching in from the left, its shade aimed at the sheet."""
    ax, ay = math.cos(SHADE_ANGLE), math.sin(SHADE_ANGLE)
    px, py = -ay, ax
    tx, ty = SHADE_TOP
    m = (tx + SHADE_DEEP * ax, ty + SHADE_DEEP * ay)     # the middle of its mouth

    def at(u: float, v: float) -> Point:
        return (m[0] + u * ax + v * px, m[1] + u * ay + v * py)

    # The standing light: from the mouth over the top half of the sheet.
    b.glow(ellipse(*at(50, 0), 56, 34, n=14, rot=SHADE_ANGLE), part='lamp')
    b.line(poly(at(-SHADE_DEEP, -4.5), at(0, -13), at(0, 13), at(-SHADE_DEEP, 4.5)), part='lamp')
    # The arm: from the back of the shade to an elbow, and out of the frame.
    b.line(line(at(-SHADE_DEEP, 0), at(-SHADE_DEEP - 3, 0), (7.0, 34.0), (0.0, 50.0)), part='lamp')
    # The bulb, just showing under the shade.
    b.line(curve(at(0, -6.5), at(4.2, 0), at(0, 6.5)), part='lamp')
    for deg in (-38, 0, 38):
        a = math.radians(deg)
        u, v = math.cos(a), math.sin(a)
        b.line(line(at(8.5 * u, 8.5 * v), at(13 * u, 13 * v)), part='ray')


def _stars(b: SketchBuilder, r: Rng) -> None:
    """Two or three stars in the top right corner, clear of the board and clip."""
    near = []
    for pts, corners in (_board_outline(), _clip_outline()):
        near += [(x, y, 6.0) for x, y in k.samples(loop(*_turn(pts), corners=corners), 3.0)]
    k.stars(b, r, 3, (102, 6, 152, 22), avoid=near, gap=14, part='star')
