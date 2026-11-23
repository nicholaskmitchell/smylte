"""February: the robin and the snowdrops.

Day: a robin perched on a snowy wall post at the left, its breast the coral
note. A low garden wall runs right from the post with snow lying along its top
and a bare shrub behind it, clumps of snowdrops hang their bells along the
ground at the right, and snow lies about in patches under a small sun.

Night: the robin tucked into itself on the same post, rounder, its head down;
the snowdrops closed; a moon with its glow, and stars clear of the shrub.

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

POST = (18.0, 42.0, 68.0)                # x0, x1, top
WALL = (42.0, 128.0, 76.0)               # x0, x1, top
PERCH = (30.0, 63.2)                     # the robin's feet, on the post's snow
SCALE = 1.5                              # the robin's size: about 25 units long
SHRUB = 91.2
CLUMPS = (142.0, 164.0, 186.0)           # each clump's foot
SUN = (158.0, 20.0, 4.5)
MOON = (160.0, 22.0, 6.5)
# Ink and wobble on one side of a line: what a star's reach clears.
INK = PEN / 2 + WOBBLE


class February:
    id = 'month-february'
    JOINS = frozenset(frozenset(p) for p in (
        ('post', 'ground'), ('post', 'snow'), ('wall', 'ground'), ('wall', 'post'), ('wall', 'snow'),
        ('robin', 'snow'), ('shrub', 'snow'), ('shrub', 'wall'), ('clump', 'ground'),
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
    """What both compositions share, so the night is the same garden."""
    return {
        'snow': [r.uniform(-0.6, 0.6) for _ in range(8)],
        'drops': [[(r.uniform(-1.0, 1.0), r.uniform(-1.0, 1.0)) for _ in range(2)] for _ in CLUMPS],
        'patches': r.fork('patches'),
    }


def _at(x: float, y: float):
    """A point on the robin, in its own units (feet at 0, 0, facing right)."""
    px, py = PERCH
    return (px + x * SCALE, py + y * SCALE)


def _lumps(b: SketchBuilder, x0: float, x1: float, y: float, n: int, height: float, jitter, part: str) -> None:
    """Snow lying on a ledge: round lumps resting on the line at y."""
    w = (x1 - x0) / n
    pts, corners = [], []
    for i in range(n + 1):
        x = x0 + w * i
        corners.append(len(pts))
        pts.append((x, y - 0.4))
        if i < n:
            h = height + jitter[i % len(jitter)]
            pts.extend(((x + w * 0.2, y - h * 0.85), (x + w * 0.5, y - h), (x + w * 0.8, y - h * 0.85)))
    b.line(curve(*pts, corners=corners), part=part)


def _garden(b: SketchBuilder, s: dict) -> None:
    b.line(curve((6, GROUND + 0.6), (100, GROUND - 0.5), (194, GROUND + 0.6)), part='ground')
    # The wall post, its cap of snow heaped up where the robin sits.
    x0, x1, top = POST
    b.line(line((x0, GROUND), (x0, top), (x1, top), (x1, GROUND)), part='post')
    b.line(line((x0 + 3.0, top + 5.0), (x1 - 3.0, top + 5.0)), part='post')
    b.line(curve((x0 - 1.6, top - 0.3), (x0 + 3.0, top - 3.4), (PERCH[0] - 2.0, PERCH[1] - 0.2),
                 (PERCH[0] + 4.0, PERCH[1] - 0.1), (x1 - 3.0, top - 3.0), (x1 + 1.6, top - 0.3)), part='snow')
    # The low wall, a few stones in its face, and the snow along its top.
    wx0, wx1, wtop = WALL
    b.line(line((wx0, wtop), (wx1, wtop), (wx1, GROUND)), part='wall')
    b.line(line((wx0, 86.0), (wx1, 86.5)), part='wall')
    for x, y0, y1 in ((70.0, wtop, 86.0), (104.0, wtop, 86.0),
                      (55.0, 86.0, GROUND), (87.0, 86.0, GROUND), (117.0, 86.0, GROUND)):
        b.line(line((x, y0), (x, y1)), part='wall')
    _lumps(b, wx0 + 0.6, wx1 + 1.0, wtop, 8, 4.4, s['snow'], 'snow')
    # A bare shrub behind the wall, rising out of the snow along it: its
    # stems go down behind the wall's top.
    sx = SHRUB
    for dx, tx, ty in ((-3.0, -16.0, 44.0), (0.0, 2.0, 36.0), (3.0, 17.0, 44.0)):
        mid = (sx + dx + (tx - dx) * 0.45, wtop - 4.0 - (wtop - 4.0 - ty) * 0.5)
        b.line(curve((sx + dx, wtop - 4.4), mid, (sx + tx, ty)), part='shrub')
    for (ax, ay), (cx, cy) in (((sx - 9.0, 57.0), (sx - 17.0, 54.0)), ((sx + 1.2, 52.0), (sx + 8.0, 45.0)),
                               ((sx + 10.0, 56.0), (sx + 19.0, 55.0)), ((sx - 1.0, 46.0), (sx - 7.0, 40.0))):
        b.line(line((ax, ay), (cx, cy)), part='shrub')


def _clumps(b: SketchBuilder, s: dict, open_: bool) -> None:
    """Snowdrops: two stems a clump, each arching over to hang one bell, and
    two strap leaves. The tall one nods right and the short one left, so the
    bells of two clumps side by side hang at different heights."""
    for i, (x, drops) in enumerate(zip(CLUMPS, s['drops'])):
        part = f'clump:{i}'
        b.line(curve((x - 1.0, GROUND), (x - 2.6, GROUND - 6.0), (x - 4.6, GROUND - 10.0)), part=part)
        b.line(curve((x + 1.0, GROUND), (x + 2.8, GROUND - 6.0), (x + 4.8, GROUND - 9.0)), part=part)
        for side, h0, (dx, dh) in ((1, 24.0, drops[0]), (-1, 14.0, drops[1])):
            h = h0 + dh
            foot = x + 0.4 * side
            top = (foot + side * (1.4 + dx * 0.3), GROUND - h)
            tip = (top[0] + side * 3.6, top[1] + 1.6)
            b.line(curve((foot, GROUND), (foot + side * 0.6, GROUND - h * 0.6), top, tip), part=part)
            bx, by = tip[0] + side * 0.4, tip[1] + 0.6
            if open_:
                # An open bell: three petals spread round a point at the top.
                b.line(loop((bx, by), (bx + 3.0, by + 2.6), (bx + 3.4, by + 7.4), (bx + 1.1, by + 5.8),
                            (bx, by + 7.8), (bx - 1.1, by + 5.8), (bx - 3.4, by + 7.4), (bx - 3.0, by + 2.6),
                            corners=(0, 2, 3, 4, 5, 6)), part=part)
            else:
                # Closed for the night: a slim bud.
                b.line(loop((bx, by), (bx + 1.9, by + 3.4), (bx + 1.3, by + 7.4), (bx, by + 8.4),
                            (bx - 1.3, by + 7.4), (bx - 1.9, by + 3.4), corners=(0, 3)), part=part)


def _robin(b: SketchBuilder) -> None:
    """Perched and alert: a plump body, the head up, the tail cocked, the
    breast the coral note."""
    # The body from the throat, over the head and back, to the belly; the
    # breast's own outline closes the front.
    b.line(curve(_at(7.6, -11.6), _at(8.2, -13.6), _at(6.6, -16.2), _at(3.0, -17.2), _at(-0.6, -15.4),
                 _at(-4.4, -11.2), _at(-8.0, -7.2), _at(-5.6, -4.0), _at(-1.0, -2.8), _at(3.4, -3.6)),
           part='robin')
    b.filled(loop(_at(7.6, -11.6), _at(7.8, -7.6), _at(3.4, -3.6), _at(2.2, -7.4), _at(4.0, -11.0),
                  corners=(0, 2)), part='robin', paper='glint')
    b.line(poly(_at(8.0, -14.6), _at(11.6, -13.4), _at(8.0, -12.4)), part='robin')
    b.line(loop(_at(-7.4, -8.0), _at(-14.0, -11.6), _at(-13.4, -7.6), _at(-7.6, -5.2), corners=(1, 2)), part='robin')
    b.line(line(_at(-1.6, -2.9), _at(-2.0, 0.0)), part='robin')
    b.line(line(_at(1.8, -3.0), _at(2.2, 0.0)), part='robin')


def _robin_tucked(b: SketchBuilder) -> None:
    """Asleep: puffed round, the head sunk into the shoulders and the beak
    tipped down, the tail low; the breast still coral."""
    b.line(curve(_at(7.6, -11.0), _at(7.9, -14.0), _at(5.6, -16.4), _at(2.8, -16.6), _at(0.6, -15.8),
                 _at(-4.6, -15.0), _at(-8.4, -10.4), _at(-8.0, -4.6), _at(-3.4, -0.9), _at(2.6, -0.8)),
           part='robin')
    b.filled(loop(_at(7.6, -11.0), _at(8.4, -6.0), _at(2.6, -0.8), _at(2.0, -5.4), _at(4.4, -10.0),
                  corners=(0, 2)), part='robin', paper='glint')
    b.line(poly(_at(7.8, -13.2), _at(10.4, -11.8), _at(7.8, -11.6)), part='robin')
    b.line(loop(_at(-7.8, -5.0), _at(-12.6, -3.4), _at(-12.0, -1.6), _at(-6.6, -2.4), corners=(1, 2)), part='robin')


def _patches(b: SketchBuilder, s: dict) -> None:
    r = s['patches']
    b.wash(k.blob(78.0, GROUND - 1.0, 26.0, 4.6, r.fork('wall'), n=12, wobble=0.07), part='patch')
    b.wash(k.blob(163.0, GROUND - 1.0, 22.0, 4.6, r.fork('drops'), n=12, wobble=0.07), part='patch')


def _sky(p) -> bool:
    """Open sky: clear of the robin, the shrub and the wall's snow."""
    x, y = p
    if x < 52 and y > 28:                                    # the robin and its post
        return False
    if SHRUB - 26 <= x <= SHRUB + 26 and y > 30:            # the shrub
        return False
    return y < WALL[2] - 12


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _patches(b, s)
    _garden(b, s)
    _clumps(b, s, True)
    _robin(b)
    sx, sy, sr = SUN
    k.sun(b, r.fork('sun'), sx, sy, sr, rays=6, ray_gap=2.4, ray_len=3.4)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    _patches(b, s)
    _garden(b, s)
    _clumps(b, s, False)
    _robin_tucked(b)
    k.stars(b, r.fork('stars'), 5, (10.0, 8.0, 190.0, 50.0), avoid=[(mx, my, mr * 2.4)],
            ok=_sky, gap=18.0, part='star')
