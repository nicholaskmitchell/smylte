"""January: a snow day.

Day: a snowman left of centre, three stacked balls with stick arms, two coal
buttons and a carrot nose seen from the side, and a coral knitted scarf round
his neck, its two tails hanging. A split-rail fence runs behind him at the
right, a bare birch stands at the far right, a drift lies round his foot, a
small pale sun is out and snow is falling.

Night: the same snowman and fence under a moon and stars, the snow stopped,
and far off on the left a small house with a lit window.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import PEN, WOBBLE, curve, line, loop, poly
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

SX = 66.0                                # the snowman's middle
BALLS = ((SX, 85.5, 12.5), (SX, 64.5, 10.0), (SX, 45.5, 8.0))   # bottom, middle, head
SCARF_TOP, SCARF_BOTTOM = 52.4, 57.6
POSTS = (112.0, 140.0, 168.0)
POST_TOP = 70.0
RAILS = (77.0, 87.0)
BIRCH = (179.5, 186.5)                   # the trunk's two sides at its foot
LEAN = 1.2                               # how far each side leans in by the top
SUN = (128.0, 20.0, 4.0)
MOON = (146.0, 22.0, 6.5)
HOUSE = (12.0, 34.0, 84.0)               # the far house: x0, x1, eave
# Ink and wobble on one side of a line: what a flake's reach clears.
INK = PEN / 2 + WOBBLE


class January:
    id = 'month-january'
    JOINS = frozenset(frozenset(p) for p in (
        ('snowman', 'ground'), ('snowman', 'scarf'), ('arm', 'snowman'),
        ('fence', 'ground'), ('birch', 'ground'), ('house', 'ground'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, view_box=VIEW_BOX, still=True)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same snow day."""
    return {
        'rails': [r.uniform(-0.6, 0.6) for _ in range(len(RAILS) * 2)],
        'drift': r.fork('drift'),
    }


def _arc(cx: float, cy: float, rad: float, a0: float, a1: float, n: int = 10):
    return [(cx + rad * math.cos(a0 + (a1 - a0) * i / n), cy + rad * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def _snowman(b: SketchBuilder) -> None:
    (bx, by, br), (mx, my, mr), (hx, hy, hr) = BALLS
    b.line(k.ring(bx, by, br, 12), part='snowman')
    # The middle ball and the head open where the scarf wraps the neck.
    m0 = math.asin((SCARF_BOTTOM - 0.2 - my) / mr)              # the right end's angle
    b.line(curve(*_arc(mx, my, mr, m0, math.pi - m0, 14)), part='snowman')
    h0 = math.asin((SCARF_TOP + 0.2 - hy) / hr)
    b.line(curve(*_arc(hx, hy, hr, math.pi - h0, 2 * math.pi + h0, 10)), part='snowman')
    # The carrot nose, from the side.
    b.line(poly((hx + hr - 0.5, hy - 1.2), (hx + hr + 8.5, hy + 0.9), (hx + hr - 0.5, hy + 1.3)),
           part='snowman')
    # Two coal buttons.
    for y in (81.0, 89.0):
        b.line(k.ring(bx, y, 0.9, 6), part=f'coal:{y:.0f}')
    # Stick arms, each with a twig.
    for side in (-1, 1):
        x0, y0 = mx + side * mr * math.cos(math.radians(15)), my + mr * math.sin(math.radians(15))
        x1, y1 = x0 + side * 15.0, y0 - 10.0
        b.line(line((x0, y0), (x1, y1)), part='arm')
        fx, fy = x0 + side * 10.0, y0 - 6.7
        b.line(line((fx, fy), (fx + side * 1.5, fy - 5.5)), part='arm')


def _scarf(b: SketchBuilder) -> None:
    """The coral note: a knitted band round the neck and two tails."""
    x0, x1 = SX - 10.5, SX + 10.5
    b.filled(loop((x0, SCARF_TOP + 1.6), (SX, SCARF_TOP), (x1, SCARF_TOP + 1.6),
                  (x1 - 0.4, SCARF_BOTTOM - 0.2), (SX, SCARF_BOTTOM + 0.6), (x0 + 0.4, SCARF_BOTTOM - 0.4),
                  corners=(0, 2, 3, 5)), part='scarf', paper='glint')
    b.filled(poly((SX - 1.0, SCARF_BOTTOM), (SX + 3.4, SCARF_BOTTOM), (SX + 3.0, 69.0), (SX - 0.8, 68.4)),
             part='scarf', paper='glint')
    b.filled(poly((SX + 3.8, SCARF_BOTTOM), (SX + 6.9, SCARF_BOTTOM - 0.3), (SX + 6.5, 64.0), (SX + 3.9, 64.6)),
             part='scarf', paper='glint')


def _fence(b: SketchBuilder, s: dict) -> None:
    for x in POSTS:
        b.line(line((x, GROUND), (x, POST_TOP)), part='fence')
    j = iter(s['rails'])
    for y in RAILS:
        b.line(line((POSTS[0] - 6.0, y + next(j)), (POSTS[-1] + 6.0, y + next(j))), part='fence')


def _birch(b: SketchBuilder) -> None:
    l, r = BIRCH
    b.line(line((l, GROUND), (l + LEAN, 16.0)), part='birch')
    b.line(line((r, GROUND), (r - LEAN, 16.0)), part='birch')
    b.line(line((l + LEAN, 16.0), ((l + r) / 2, 11.0), (r - LEAN, 16.0)), part='birch')
    # The bark's dark marks, on alternate sides.
    for y, side in ((28.0, 0), (42.0, 1), (56.0, 0), (70.0, 1), (84.0, 0)):
        lean = LEAN * (1 - (y - 16.0) / (GROUND - 16.0))
        x = (l + lean if side == 0 else r - lean)
        b.line(line((x, y), (x + (3.2 if side == 0 else -3.2), y + 0.8)), part='birch')
    # Bare branches, up and away from the trunk.
    b.line(curve((l + 1.2, 40.0), (170.0, 32.0), (160.0, 22.0)), part='birch')
    b.line(curve((170.0, 32.0), (164.0, 33.0), (157.0, 30.0)), part='birch')
    b.line(curve((l + 1.4, 26.0), (174.0, 18.0), (170.0, 10.0)), part='birch')
    b.line(curve((r - 1.0, 34.0), (191.0, 26.0), (192.0, 18.0)), part='birch')


def _clear(p) -> bool:
    """Open sky and snow: clear of the snowman, his arms, the fence and the birch."""
    x, y = p
    if y > GROUND - 8 or y < 6:
        return False
    for cx, cy, r in BALLS:
        if math.dist(p, (cx, cy)) < r + 4:
            return False
    if SX - 34 <= x <= SX + 34 and 36 <= y <= 70:          # the arms and the nose
        return False
    if POSTS[0] - 12 <= x <= POSTS[-1] + 12 and y >= POST_TOP - 6:
        return False
    if x >= 150:                                            # the birch and its branches
        return False
    return True


def _flakes(b: SketchBuilder, r: Rng, count: int, avoid) -> None:
    """Falling snow: small six-armed flakes, apart and clear of everything."""
    reach = 3.0 + INK
    around = [(reach * math.cos(math.pi * i / 4), reach * math.sin(math.pi * i / 4)) for i in range(8)]
    out: list[tuple[float, float]] = []
    for _ in range(600):
        if len(out) == count:
            break
        p = (r.uniform(10.0, 148.0), r.uniform(8.0, 88.0))
        if any(math.dist(p, q) < 17.0 for q in out):
            continue
        if not all(_clear(q) and k.clear_of(q, avoid) for q in [p, *((p[0] + dx, p[1] + dy) for dx, dy in around)]):
            continue
        out.append(p)
    for i, (x, y) in enumerate(out):
        turn = r.uniform(0, math.pi / 3)
        arm = r.uniform(2.6, 3.0)
        for j in range(3):
            a = turn + math.pi * j / 3
            b.line(line((x - arm * math.cos(a), y - arm * math.sin(a)),
                        (x + arm * math.cos(a), y + arm * math.sin(a))), part=f'flake:{i}')


def _scene(b: SketchBuilder, s: dict) -> None:
    b.wash(k.blob(SX + 2, GROUND - 1.5, 30.0, 5.5, s['drift'], n=12, wobble=0.07), part='drift')
    b.line(curve((6, GROUND + 0.6), (100, GROUND - 0.5), (194, GROUND + 0.6)), part='ground')
    _fence(b, s)
    _birch(b)
    _snowman(b)
    _scarf(b)


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _scene(b, s)
    sx, sy, sr = SUN
    k.sun(b, r.fork('sun'), sx, sy, sr, rays=6, ray_gap=2.4, ray_len=3.2)
    _flakes(b, r.fork('flakes'), 9, avoid=[(sx, sy, sr + 2.4 + 3.2 + 4)])


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    # Far off on the left, a small house with its window lit.
    x0, x1, eave = HOUSE
    cx = (x0 + x1) / 2
    b.glow(k.ring(cx, 90.5, 8.0, 11), part='window')
    _scene(b, s)
    b.line(line((x0 + 2, GROUND), (x0 + 2, eave), (x0, eave), (cx, eave - 9.0), (x1, eave),
                (x1 - 2, eave), (x1 - 2, GROUND)), part='house')
    b.line(poly((cx - 3.2, 87.5), (cx + 3.2, 87.5), (cx + 3.2, 93.0), (cx - 3.2, 93.0)), part='pane')
    k.stars(b, r.fork('stars'), 5, (10.0, 8.0, 150.0, 40.0), avoid=[(mx, my, mr * 2.4)],
            ok=_clear, gap=18.0, part='star')
