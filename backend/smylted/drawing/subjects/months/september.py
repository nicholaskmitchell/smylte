"""September: apple picking.

Day: an apple tree left of centre, its round crown hung with coral apples; a
wooden ladder leaning into the crown from the right; a woven basket on the
ground at the right with three apples showing over its rim; a sun.

Night: the same tree and basket under a harvest moon in the open sky between
them, with its glow, and stars. The ladder has been taken down and lies along
the ground.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import curve, line, loop
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

CROWN = (60.0, 40.0, 42.0, 29.0)         # the crown's centre and radii
# The trunk, and the two limbs it forks into inside the crown.
TRUNK = ((60.0, GROUND), (61.0, 82.0), (60.0, 64.0))
LIMBS = (((60.0, 66.0), (55.0, 58.0), (50.0, 52.0)),
         ((60.0, 66.0), (66.0, 57.0), (71.0, 51.0)))
# The apples on the tree: the coral note.
APPLES = ((34.0, 32.0), (48.0, 23.0), (68.0, 23.0), (86.0, 33.0),
          (36.0, 51.0), (82.0, 53.0), (58.0, 39.0))
APPLE_R = 4.2
# The ladder's rails by day: foot and top of each.
RAILS = (((120.0, GROUND), (91.0, 46.0)), ((130.0, GROUND), (101.0, 46.0)))
RUNGS = (90.0, 81.0, 72.0, 63.0, 54.0)
# By night it lies along the ground: its far rail, and its rungs' feet.
LYING = (90.5, (73.0, 82.0, 91.0, 100.0, 109.0, 118.0, 127.0))
# The basket: its rim's ends, its foot's ends, and the apples over its rim.
RIM = (146.0, 180.0, 80.0)
FOOT = (150.0, 176.0)
CROP = (150.5, 163.0, 175.5)
CROP_R = 5.5
CROP_LIFT = 2.0                          # how far above the rim each apple's centre sits
SUN = (172.0, 22.0)
MOON = (140.0, 30.0, 9.5)                 # its glow clears the basket's handle


class September:
    id = 'month-september'
    JOINS = frozenset(frozenset(p) for p in (
        ('trunk', 'ground'), ('trunk', 'crown'), ('ladder', 'ground'), ('ladder', 'crown'),
        ('basket', 'ground'), ('crop', 'basket'), ('crop', 'crop'),
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
    """What both compositions share, so the night is the same orchard."""
    cx, cy, rx, ry = CROWN
    return {
        'crown': k.blob(cx, cy, rx, ry, r.fork('crown'), n=12, wobble=0.04),
        'apples': [(x + r.uniform(-0.8, 0.8), y + r.uniform(-0.8, 0.8)) for x, y in APPLES],
    }


def _rail_x(rail, y: float) -> float:
    (x0, y0), (x1, y1) = rail
    return x0 + (x1 - x0) * (y - y0) / (y1 - y0)


def _tree(b: SketchBuilder, s: dict) -> None:
    b.line(s['crown'], part='crown')
    b.line(curve(*TRUNK), part='trunk')
    for limb in LIMBS:
        b.line(curve(*limb), part='trunk')
    for i, (x, y) in enumerate(s['apples']):
        k.fruit(b, x, y, APPLE_R, part=f'apple:{i}')


def _basket(b: SketchBuilder) -> None:
    x0, x1, rim = RIM
    f0, f1 = FOOT
    # The apples showing over the rim: more than half of each, cut by the rim.
    cut = math.asin(CROP_LIFT / CROP_R)
    for i, x in enumerate(CROP):
        arc = [(x + CROP_R * math.cos(math.pi - cut + (math.pi + 2 * cut) * j / 6),
                rim - CROP_LIFT + CROP_R * math.sin(math.pi - cut + (math.pi + 2 * cut) * j / 6))
               for j in range(7)]
        b.filled(loop(*arc, corners=(0, 6)), part=f'crop:{i}', paper='glint')
    b.line(line((x0 - 2, rim), (x1 + 2, rim)), part='basket')
    b.line(line((x0, rim), (f0, GROUND)), part='basket')
    b.line(line((x1, rim), (f1, GROUND)), part='basket')
    # The weave: two rows round the sides, MIN_GAP and more apart.
    for y in (86.0, 92.0):
        t = (y - rim) / (GROUND - rim)
        b.line(line((x0 + (f0 - x0) * t, y), (x1 + (f1 - x1) * t, y + 0.3)), part='basket')
    mid = (x0 + x1) / 2
    b.line(curve((x0 + 2, rim), (mid - 9, rim - 13), (mid, rim - 16), (mid + 9, rim - 13), (x1 - 2, rim)),
           part='basket')


def _ladder_up(b: SketchBuilder) -> None:
    for rail in RAILS:
        b.line(line(*rail), part='ladder')
    for y in RUNGS:
        b.line(line((_rail_x(RAILS[0], y), y), (_rail_x(RAILS[1], y), y)), part='ladder')


def _ladder_down(b: SketchBuilder) -> None:
    """The ladder lying on the ground: its near rail on the ground line, its
    far rail a little up the page, the rungs between."""
    y, feet = LYING
    b.line(line((feet[0] - 1.0, y), (feet[-1] + 5.0, y + 0.3)), part='ladder')
    for x in feet:
        b.line(line((x, GROUND), (x + 2.0, y)), part='ladder')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(s['crown']), part='crown')
    k.sun(b, r.fork('sun'), *SUN, 5)
    b.line(curve((6, GROUND + 0.5), (100, GROUND - 0.5), (194, GROUND + 0.5)), part='ground')
    _tree(b, s)
    _ladder_up(b)
    _basket(b)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(s['crown']), part='crown')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    cx, cy, rx, _ = CROWN
    k.stars(b, r.fork('stars'), 4, (108.0, 6.0, 194.0, 36.0), avoid=[(mx, my, mr + 8), (cx, cy, rx + 6.0)],
            gap=16.0)
    b.line(curve((6, GROUND + 0.5), (100, GROUND - 0.5), (194, GROUND + 0.5)), part='ground')
    _tree(b, s)
    _ladder_down(b)
    _basket(b)
