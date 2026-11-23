"""October: pumpkins.

Day: three ribbed coral pumpkins, one sitting on a straw bale and two on the
ground beside it; a wheelbarrow at the right; three leaves falling; a sun.

Night: the same pumpkins, bale and barrow by a lantern hung on a post, its
warm glow the light; a thin moon and stars. The leaves have come down and lie
on the ground.

A month drawing: still, and the same whatever the day's state (months/_page.py).
No faces: they are pumpkins, not lanterns.
"""
from __future__ import annotations

import math

from ...pen import curve, line, loop, poly
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

BALE = (40.0, 64.0, 102.0)               # x0, top, x1; it stands on the ground
# The straw: short strokes across the bale, rows MIN_GAP and more apart, each
# stroke its own length and a slant of its own: (x0, x1, how far its end drops).
STRAW = ((72.0, ((47.0, 59.0, 0.7), (79.0, 97.0, -0.5))),
         (78.5, ((52.0, 73.0, -0.6), (85.0, 96.0, 0.8))),
         (85.0, ((46.0, 56.0, 0.5), (69.0, 93.0, -0.8))),
         (91.5, ((50.0, 67.0, -0.4), (77.0, 95.0, 0.6))))
# The pumpkins: centre and radii. The first sits on the bale, the others stand
# on the ground in front of its ends.
PUMPKINS = ((70.0, 53.5, 14.5, 10.5), (26.0, 86.5, 15.0, 11.5), (112.0, 89.5, 12.0, 8.5))
# The wheelbarrow: its tray, its wheel, and the handle and leg behind.
TRAY = ((140.0, 62.0), (192.0, 62.0), (184.0, 80.0), (156.0, 80.0))
WHEEL = (150.0, 89.0, 9.0)
FALLING = ((88.0, 24.0, 12.0, 0.6), (120.0, 44.0, 12.0, 2.3), (140.0, 30.0, 12.0, -0.9))
# By night the leaves have come down, on the ground, under the barrow and on
# the bale: (x, what it lies on, length, angle).
FALLEN = ((128.0, GROUND, 9.0, -0.12), (45.0, BALE[1], 8.0, -0.12), (166.0, GROUND, 10.0, -0.12))
POST = (96.0, 26.0)                      # the lantern's post, behind the bale: its x and its top
LANTERN = (116.0, 48.0)                  # the lantern's centre
SUN = (176.0, 22.0)
MOON = (178.0, 20.0, 6.0)


class October:
    id = 'month-october'
    JOINS = frozenset(frozenset(p) for p in (
        ('bale', 'ground'), ('pumpkin', 'bale'), ('pumpkin', 'ground'),
        ('barrow', 'ground'), ('post', 'bale'), ('post', 'lantern'),
        ('fallen', 'ground'), ('fallen', 'bale'),
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
    """What both compositions share, so the night is the same yard."""
    return {
        'lean': [r.uniform(-0.12, 0.12) for _ in PUMPKINS],
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
    }


def _bale_outline():
    x0, top, x1 = BALE
    return poly((x0, GROUND), (x0, top), (x1, top), (x1, GROUND))


def _pumpkin(b: SketchBuilder, i: int, cx: float, cy: float, rx: float, ry: float, lean: float) -> None:
    """A coral pumpkin: a round body dipped at its stem, ink ribs down it, and a
    stem. Ribs MIN_GAP and more apart, meeting near the stem and the foot."""
    part = f'pumpkin:{i}'
    pts = []
    for j in range(12):
        a = -math.pi / 2 + 2 * math.pi * j / 12
        dip = 1.6 if j == 0 else 0.0
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a) + dip))
    b.filled(loop(*pts), part=part, paper='glint')
    top, foot = cy - ry + 1.6, cy + ry
    ribs = (-0.5, 0.5) if rx < 11 else (-0.55, 0.0, 0.55)
    for u in ribs:
        b.line(curve((cx + u * rx * 0.25, top + 1.2), (cx + u * rx * 0.7, cy), (cx + u * rx * 0.3, foot - 1.4)),
               part=part)
    b.line(curve((cx, top + 0.4), (cx + 0.6 + lean * 6, top - 3.2), (cx + 2.4 + lean * 8, top - 5.6)), part=part)


def _yard(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6, GROUND + g[0]), (100, GROUND + g[1] * 0.6), (194, GROUND + g[2])), part='ground')
    b.line(_bale_outline(), part='bale')
    for y, runs in STRAW:
        for x0, x1, drop in runs:
            b.line(line((x0, y), (x1, y + drop)), part='bale')
    for i, (p, lean) in enumerate(zip(PUMPKINS, s['lean'])):
        _pumpkin(b, i, *p, lean)
    # The wheelbarrow: tray, wheel and strut, handle and leg.
    b.line(loop(*TRAY, corners=(0, 1, 2, 3)), part='barrow')
    wx, wy, wr = WHEEL
    b.line(k.ring(wx, wy, wr, 10), part='barrow')
    b.line(line((wx, wy), (160.0, 80.0)), part='barrow')
    b.line(line((184.0, 80.0), (196.0, 72.5)), part='barrow')
    b.line(line((190.0, 76.3), (191.0, GROUND)), part='barrow')


def _washes(b: SketchBuilder) -> None:
    b.wash(k.wash_of(_bale_outline(), inset=0.9, dx=3.0, dy=2.0), part='bale')
    b.wash(k.wash_of(loop(*TRAY, corners=(0, 1, 2, 3)), inset=0.86, dx=2.5, dy=1.5), part='barrow')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _washes(b)
    k.sun(b, r.fork('sun'), *SUN, 5)
    _yard(b, s)
    for i, (x, y, ln, a) in enumerate(FALLING):
        k.draw_leaf(b, x, y, ln, a, part=f'leaf:{i}')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _washes(b)
    lx, ly = LANTERN
    # The lantern lit: the standing light.
    b.glow(k.ring(lx, ly, 17.0, 12), part='glow')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, glow=False, clouds=0)
    k.stars(b, r.fork('stars'), 4, (80.0, 6.0, 194.0, 34.0), avoid=[(mx, my, mr + 6)],
            ok=lambda p: not (86.0 <= p[0] <= 128.0 and p[1] >= 18.0), gap=16.0)
    _yard(b, s)
    # The post standing behind the bale, its arm and hook, and the lantern hung from it.
    px, top = POST
    b.line(line((px, BALE[1]), (px, top)), part='post')
    b.line(line((px, top + 4.0), (lx, top + 4.0), (lx, ly - 11.0)), part='post')
    b.line(poly((lx - 8, ly - 7.0), (lx, ly - 11.0), (lx + 8, ly - 7.0)), part='lantern')
    b.line(poly((lx - 6.5, ly - 7.0), (lx + 6.5, ly - 7.0), (lx + 6.5, ly + 8.0), (lx - 6.5, ly + 8.0)),
           part='lantern')
    b.line(line((lx - 8, ly + 8.0), (lx + 8, ly + 8.0)), part='lantern')
    b.line(loop((lx, ly - 2.2), (lx + 1.7, ly + 1.6), (lx, ly + 3.0), (lx - 1.7, ly + 1.6), corners=(0,)),
           part='flame')
    # The leaves, come down: each resting on what it lies on.
    for i, (x, under, ln, a) in enumerate(FALLEN):
        k.draw_leaf(b, x, under - 1.0 - k.leaf_low(ln, a), ln, a, part=f'fallen:{i}')
