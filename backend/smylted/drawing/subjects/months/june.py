"""June: the long evening.

Day: a rope hammock slung between two trees standing at the page's left and
right edges, their crowns washed in sage. In the hammock lie a coral cushion
and a closed book; grass grows in tufts along the ground, the hammock's shade
lies under it, and a high sun stands between the crowns.

Night: the same trees and hammock, the book still on it, a moon with its glow
between the crowns, stars, and fireflies under the trees.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import circle, curve, line, loop
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The two trees: crown centre and radii, and the trunk's two sides at the
# ground (each narrows a little toward the crown).
CROWNS = ((27.0, 32.0, 20.0, 23.0), (171.0, 35.0, 18.0, 20.0))
TRUNKS = ((23.0, 30.0), (168.0, 175.0))
TIE = 60.0                               # where the hammock's ropes meet the trunks
# The hammock's bed: its ends, the top edge's height there and its sag.
BED = (52.0, 146.0)
BED_TOP, BED_DEPTH = 61.0, 6.0
SAG_TOP, SAG_BOTTOM = 10.0, 13.0
STRINGS = (64.0, 76.0, 88.0, 99.0, 110.0, 122.0, 134.0)
TUFTS = (44.0, 76.0, 124.0, 152.0, 186.0)
SUN = (99.0, 17.0, 5.0)
MOON = (99.0, 22.0, 6.5)
FIREFLIES = ((44.0, 80.0), (14.0, 70.0), (156.0, 84.0), (186.0, 66.0), (64.0, 88.0))


class June:
    id = 'month-june'
    JOINS = frozenset(frozenset(p) for p in (
        ('tree', 'ground'), ('grass', 'ground'), ('hammock', 'tree'),
        ('cushion', 'hammock'), ('book', 'hammock'),
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
        'crowns': [k.blob(cx, cy, rx, ry, r.fork(f'crown{i}'), n=11, wobble=0.07)
                   for i, (cx, cy, rx, ry) in enumerate(CROWNS)],
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
        'tufts': [(r.uniform(-0.8, 0.8), r.uniform(-0.6, 0.6)) for _ in TUFTS],
        'shade': k.blob(99.0, GROUND - 1.0, 36.0, 4.5, r.fork('shade'), n=12, wobble=0.06),
    }


def _top(x: float) -> float:
    """The bed's top edge at x: it sags most in the middle."""
    x0, x1 = BED
    u = (2 * x - x0 - x1) / (x1 - x0)
    return BED_TOP + SAG_TOP * (1 - u * u)


def _bottom(x: float) -> float:
    x0, x1 = BED
    u = (2 * x - x0 - x1) / (x1 - x0)
    return BED_TOP + BED_DEPTH + SAG_BOTTOM * (1 - u * u)


def _trunk_side(x_ground: float, toward: float, y: float) -> float:
    """A trunk side's x at height y: it leans in by 1.5 from the ground to the crown."""
    return x_ground + toward * 1.5 * (GROUND - y) / (GROUND - 46.0)


def _tree(b: SketchBuilder, s: dict, i: int) -> None:
    part = f'tree:{i}'
    cx, cy, rx, ry = CROWNS[i]
    l, r = TRUNKS[i]
    top = cy + ry * 0.9                 # the trunk ends where the crown begins
    b.line(line((l, GROUND), (_trunk_side(l, 1, top), top)), part=part)
    b.line(line((r, GROUND), (_trunk_side(r, -1, top), top)), part=part)
    b.line(s['crowns'][i], part=part)
    # The trunk goes on up into the crown as one bough, and a branch leaves
    # it to the side, as the potted tree's does.
    mid = (l + r) / 2
    side = 1 if i == 0 else -1
    b.line(curve((mid, top - 0.5), (mid - side * 1.0, cy + 4.0), (mid + side * 1.5, cy - 8.0)), part=part)
    b.line(curve((mid - side * 0.6, cy + 6.0), (mid + side * 5.0, cy + 1.0), (mid + side * 9.0, cy - 1.0)),
           part=part)


def _hammock(b: SketchBuilder) -> None:
    """The bed, its spreader ends, the cross strings of its net, and the
    ropes fanning to each trunk."""
    x0, x1 = BED
    n = 8
    tops = [(x0 + (x1 - x0) * i / n, _top(x0 + (x1 - x0) * i / n)) for i in range(n + 1)]
    bottoms = [(x1 - (x1 - x0) * i / n, _bottom(x1 - (x1 - x0) * i / n)) for i in range(n + 1)]
    b.line(loop(*tops, *bottoms, corners=(0, n, n + 1, 2 * n + 1)), part='hammock')
    for x in STRINGS:
        b.line(line((x, _top(x) + 0.3), (x + 1.0, _bottom(x + 1.0) - 0.3)), part='hammock')
    for (l, r), end, toward in ((TRUNKS[0], x0, 1), (TRUNKS[1], x1, -1)):
        side = r if toward == 1 else l
        knot = (_trunk_side(side, -toward, TIE), TIE)
        for y in (_top(end), _top(end) + BED_DEPTH / 2, _bottom(end)):
            b.line(line(knot, (end, y)), part='hammock')


def _cushion(b: SketchBuilder) -> None:
    """The coral note: a plump cushion propped at the hammock's head end,
    lying along the bed's slope."""
    xa, xb = 57.0, 75.0
    a, c = (xa, _top(xa) - 0.4), (xb, _top(xb) - 0.4)
    ang = math.atan2(c[1] - a[1], c[0] - a[0])
    nx, ny = math.sin(ang), -math.cos(ang)            # up off the bed
    h = 9.0

    def up(p, d):
        return (p[0] + nx * d, p[1] + ny * d)

    mid = ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2)
    b.filled(loop(a, up(mid, -0.4), c, up(c, h * 0.5), up(c, h), up(mid, h + 1.2), up(a, h),
                  up(a, h * 0.5), corners=(0, 2, 4, 6)), part='cushion', paper='glint')


def _book(b: SketchBuilder) -> None:
    """The book left on the bed, shut: a flat slab with its pages' edge."""
    l, r = 104.0, 122.0
    bl, br = _top(l) - 0.4, _top(r) - 0.4
    b.line(loop((l, bl), (l - 0.4, bl - 5.0), (r - 0.4, br - 5.0), (r, br),
                corners=(0, 1, 2, 3)), part='book')
    b.line(line((l + 2.0, bl - 2.5), (r - 2.0, br - 2.5)), part='book')


def _ground(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6.0, GROUND + g[0]), (100.0, GROUND + g[1]), (194.0, GROUND + g[2])), part='ground')
    for i, (x, (dx, dh)) in enumerate(zip(TUFTS, s['tufts'])):
        x += dx
        # Two blades leaning together, as the washing line's grass does.
        b.line(curve((x - 3.0, GROUND), (x - 1.0, GROUND - 4.6 - dh), (x, GROUND - 6.4 - dh)),
               part=f'grass:{i}')
        b.line(curve((x + 1.4, GROUND), (x + 3.0, GROUND - 4.0), (x + 4.6, GROUND - 5.4)),
               part=f'grass:{i}')


def _scene(b: SketchBuilder, s: dict) -> None:
    for i, crown in enumerate(s['crowns']):
        b.wash(k.wash_of(crown, dx=3.5, dy=3.5), part=f'tree:{i}')
    b.wash(s['shade'], part='shade')
    _ground(b, s)
    _tree(b, s, 0)
    _tree(b, s, 1)
    _hammock(b)
    _cushion(b)
    _book(b)


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _scene(b, s)
    k.sun(b, r.fork('sun'), *SUN)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    for x, y in FIREFLIES:
        b.glow(circle(x, y, 4.2, n=8), part='firefly')
    _scene(b, s)
    # Each firefly's own spark of ink at the heart of its glow.
    for x, y in FIREFLIES:
        b.line(circle(x, y, 0.8, n=6), part='firefly')
    k.stars(b, r.fork('stars'), 4, (52.0, 8.0, 146.0, 44.0), avoid=[(mx, my, mr + 6.0)],
            ok=_sky, gap=16.0)


def _sky(p) -> bool:
    """Between the crowns, and above the hammock's ropes."""
    for cx, cy, rx, ry in CROWNS:
        if ((p[0] - cx) / (rx * 1.12 + 4.0)) ** 2 + ((p[1] - cy) / (ry * 1.12 + 4.0)) ** 2 < 1:
            return False
    return p[1] < TIE - 8.0
