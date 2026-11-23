"""April: blossom.

Day: a young cherry tree left of centre, its branches spreading over the left
two thirds of the sky, clusters of five-petal blossoms on their tips, a few of
them coral; a small lantern hung unlit on a cord from the right-hand limb;
petals falling between the tree and a slatted bench at the right; a sun over
the bench.

Night: the same tree and bench, the lantern lit in the tree with its glow, a
moon high in the right with its glow, and stars clear of the branches. No
petals fall.

A month drawing: still, and the same whatever the day's state.
"""
from __future__ import annotations

import math

from ...pen import curve, line, loop, poly
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The tree: the trunk's foot, and its limbs as hand-placed curves.
TRUNK = ((60.0, GROUND), (61.5, 84.0), (60.5, 72.0), (62.0, 62.0))
LIMBS = (
    ((62.0, 62.0), (50.0, 53.0), (36.0, 46.0), (22.0, 42.0)),
    ((50.0, 53.0), (45.0, 41.0), (40.0, 28.0)),
    ((62.0, 62.0), (64.0, 48.0), (66.0, 34.0), (69.0, 20.0)),
    ((62.0, 64.0), (78.0, 55.0), (96.0, 47.0), (114.0, 42.0)),
    ((80.0, 54.0), (88.0, 40.0), (95.0, 26.0)),
    ((36.0, 46.0), (28.0, 52.0), (20.0, 58.0)),
    ((96.0, 47.0), (108.0, 54.0), (122.0, 56.0)),
)
# The blossoms: a cluster round each branch tip, as (x, y) centres.
BLOSSOMS = (
    (17.0, 38.0), (28.0, 33.0), (13.0, 49.0), (19.0, 61.0), (30.0, 67.0),
    (39.0, 24.0), (50.0, 19.0), (32.0, 14.0),
    (69.0, 15.0), (81.0, 12.0), (59.0, 10.0),
    (96.0, 21.0), (107.0, 16.0),
    (116.0, 38.0), (125.0, 30.0), (113.0, 27.0),
    (123.0, 58.0), (132.0, 50.0),
    (55.0, 37.0), (82.0, 36.0),
)
# Which blossoms are coral: one in each part of the crown.
CORAL = (1, 3, 6, 9, 12, 14)
# A blossom's radius: the coral ones are the larger, so the eye finds them.
PETAL_R = 5.0
CORAL_R = 6.2
# The petals in the air, between the tree and the bench.
PETALS = ((142.0, 40.0, 0.5), (136.0, 70.0, -0.6), (146.0, 24.0, 1.1), (120.0, 80.0, 0.2))
BENCH = (146.0, 192.0)
# The lantern hung from the right-hand limb: its body's centre, and where its
# cord meets the limb.
LANTERN = (104.0, 68.0)
CORD_TOP = 52.0
# The lit lantern's light: centred a little under it, so it clears the
# blossom at the limb's end.
LIGHT = (104.0, 70.0, 15.0)
SUN = (170.0, 22.0)
MOON = (170.0, 22.0, 7.0)


class April:
    id = 'month-april'
    JOINS = frozenset(frozenset(p) for p in (
        ('tree', 'ground'), ('bench', 'ground'), ('blossom', 'tree'), ('blossom',),
        ('lantern', 'tree'),
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
    """What both compositions share, so the night is the same tree."""
    return {
        'turn': [r.uniform(0, 2 * math.pi / 5) for _ in BLOSSOMS],
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
    }


def _blossom(x: float, y: float, turn: float, r: float, notch: float, sharp: bool = True):
    """Five round petals, each with a notch between it and the next: sharp
    for the coral ones, soft for the small ink ones, which a sharp notch
    would crowd with ink."""
    pts, notches = [], []
    for i in range(5):
        a = turn + 2 * math.pi * i / 5
        for da, rr in ((-0.34, 0.97), (0.34, 0.97)):
            pts.append((x + r * rr * math.cos(a + da), y + r * rr * math.sin(a + da)))
        notches.append(len(pts))
        pts.append((x + r * notch * math.cos(a + math.pi / 5),
                    y + r * notch * math.sin(a + math.pi / 5)))
    return loop(*pts, corners=tuple(notches) if sharp else ())


def _petal(x: float, y: float, a: float):
    """One petal adrift: rounded, notched at its outer end."""
    c, sn = math.cos(a), math.sin(a)
    pts = [(0.0, 0.0), (1.6, -1.8), (4.6, -2.2), (6.2, -1.0), (5.4, 0.2), (6.2, 1.2), (4.6, 2.2),
           (1.6, 1.8)]
    return loop(*[(x + u * c - v * sn, y + u * sn + v * c) for u, v in pts], corners=(0, 4))


def _crown():
    """The soft green haze behind the blossom: a blob with no outline."""
    return k.blob(68.0, 36.0, 54.0, 21.0, Rng('crown'), n=12, wobble=0.06)


def _scene(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6.0, GROUND + g[0]), (100.0, GROUND + g[1]), (194.0, GROUND + g[2])),
           part='ground')
    b.line(curve(*TRUNK), part='tree')
    for limb in LIMBS:
        b.line(curve(*limb), part='tree')
    for i, ((x, y), turn) in enumerate(zip(BLOSSOMS, s['turn'])):
        if i in CORAL:
            shape = _blossom(x, y, turn, CORAL_R, 0.58)
            b.filled(shape, part=f'blossom:{i}')
        else:
            b.line(_blossom(x, y, turn, PETAL_R, 0.6, sharp=False), part=f'blossom:{i}')
    _lantern(b)
    _bench(b)


def _lantern(b: SketchBuilder) -> None:
    """A small lantern hung on a short cord from the right-hand limb: its
    peaked cap, its glass body and its base."""
    lx, ly = LANTERN
    b.line(line((lx, CORD_TOP), (lx, ly - 10.0)), part='lantern')
    b.line(poly((lx - 7.0, ly - 6.5), (lx, ly - 10.0), (lx + 7.0, ly - 6.5)), part='lantern')
    b.line(poly((lx - 5.8, ly - 6.5), (lx + 5.8, ly - 6.5), (lx + 5.8, ly + 7.0), (lx - 5.8, ly + 7.0)),
           part='lantern')
    b.line(line((lx - 7.0, ly + 7.0), (lx + 7.0, ly + 7.0)), part='lantern')


def _bench(b: SketchBuilder) -> None:
    """A slatted wooden bench seen a little from the side: its seat a slab
    with depth, two back slats on posts, and the front legs."""
    x0, x1 = BENCH
    seat = ((x0, 83.0), (x1 - 5.0, 83.0), (x1, 77.0), (x0 + 5.0, 77.0))
    b.wash(k.wash_of(loop(*seat, corners=(0, 1, 2, 3)), dx=2.0, dy=2.0), part='bench')
    b.line(loop(*seat, corners=(0, 1, 2, 3)), part='bench')
    for x in (x0 + 9.0, x1 - 4.0):
        b.line(line((x, 59.0), (x, 77.0)), part='bench')
    k.hatch(b, x0 + 6.0, 63.0, (x1 - x0 - 6.0, x1 - x0 - 6.0), 6.0, part='bench')
    for x in (x0 + 3.0, x1 - 9.0):
        b.line(line((x, 83.0), (x, GROUND)), part='bench')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(_crown(), part='crown')
    k.sun(b, r.fork('sun'), *SUN, 5)
    _scene(b, s)
    for i, (x, y, a) in enumerate(PETALS):
        b.line(_petal(x - 3.0, y, a), part=f'petal:{i}')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(_crown(), part='crown')
    # The lantern lit in the tree: its light, under the ink.
    gx, gy, gr = LIGHT
    b.glow(k.ring(gx, gy, gr, 12), part='lamp')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    avoid = [(mx, my, mr + 4.0)] + [(x, y, CORAL_R + 4.0) for x, y in BLOSSOMS]
    k.stars(b, r.fork('stars'), 4, (128.0, 8.0, 194.0, 52.0), avoid=avoid)
    _scene(b, s)
    lx, ly = LANTERN
    b.line(loop((lx, ly - 1.8), (lx + 1.2, ly + 1.2), (lx, ly + 2.4), (lx - 1.2, ly + 1.2), corners=(0,)),
           part='flame')
