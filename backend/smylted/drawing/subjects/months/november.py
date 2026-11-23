"""November: the last leaves.

Day: a bare tree at the left with its last coral leaves hanging from the twig
tips, three more falling; a rake leaning on a three-post fence at the right, a
bird on the middle post; a leaf pile at the foot of it all as a soft wash, two
leaves lying on it; a sun.

Night: the same tree, fence and pile under a moon with its glow, and three
stars.

A month drawing: still, and the same whatever the day's state (months/_page.py).
The owner saw it first in the Calendar's mockup.
"""
from __future__ import annotations

from ...pen import curve, line
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The tree: its trunk, its three limbs and the twigs off them.
TREE = (
    ((44, GROUND), (45, 82), (43, 66), (46, 52)),
    ((45, 68), (35, 58), (25, 48), (18, 38)),
    ((45, 61), (56, 52), (66, 45), (75, 36)),
    ((46, 52), (47, 40), (44, 28), (46, 17)),
)
TWIGS = (((25, 48), (17, 50)), ((35, 58), (28, 53)), ((56, 52), (61, 42)),
         ((45, 29), (37, 22)), ((47, 40), (55, 33)), ((66, 45), (76, 48)))
# The last leaves, hanging from twig tips: (x, y, length, angle).
HANGING = ((18, 38, 12, 2.3), (55, 33, 12, -0.6), (76, 48, 11, 0.9))
# And three falling, clear of the tree and of each other.
FALLING = ((92, 40, 12, 0.5), (108, 62, 12, -1.0), (84, 76, 11, 2.4))
# Two leaves lying on the pile, ink only: (x, length, angle).
PILE = ((84.0, 10.0, -0.15), (103.0, 8.0, 0.55))
POSTS = ((146, 66), (168, 63), (190, 66))
SUN = (122, 20)
MOON = (120, 22, 7)


class November:
    id = 'month-november'
    JOINS = frozenset(frozenset(p) for p in (
        ('tree', 'ground'), ('fence', 'ground'), ('rake', 'fence'), ('rake', 'ground'),
        ('bird', 'fence'), ('leaf', 'tree'),
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
    """What both compositions share, so the night is the same corner of garden."""
    return {'pile': r.fork('pile')}


def _scene(b: SketchBuilder, s: dict) -> None:
    # Colour first: the leaf pile, a soft wash with no outline across the line.
    b.wash(k.blob(98, 95, 18, 7, s['pile']), part='pile')


def _garden(b: SketchBuilder) -> None:
    b.line(line((8, GROUND), (192, GROUND)), part='ground')
    for limb in TREE:
        b.line(curve(*limb), part='tree')
    for twig in TWIGS:
        b.line(curve(*twig), part='tree')
    # The last leaves: the coral note.
    for i, (x, y, ln, a) in enumerate(HANGING):
        b.filled(k.leaf(x, y, ln, a), part=f'leaf:{i}')
    for i, (x, y, ln, a) in enumerate(FALLING):
        b.filled(k.leaf(x, y, ln, a), part=f'fall:{i}')
    # Leaves lying on the pile, raised so they rest on it, not on the line,
    # and clear of it however the hand bows the line.
    for i, (x, ln, a) in enumerate(PILE):
        k.draw_leaf(b, x, GROUND - 8.0 - k.leaf_low(ln, a), ln, a, part=f'pile:{i}')
    # A rake leaning on the fence.
    b.line(line((127, 92), (155, 65)), part='rake')
    b.line(line((117, 92), (137, 92)), part='rake')
    for x in (117.5, 122, 126.5, 131, 135.5):
        b.line(line((x, 92), (x, 97)), part='rake')
    # The fence.
    for x, top in POSTS:
        b.line(line((x, GROUND), (x, top)), part='fence')
    for y in (73, 86):
        b.line(line((140, y), (194, y + 0.5)), part='fence')
    k.bird(b, POSTS[1][0], POSTS[1][1], k_=1.15, facing=-1, part='bird')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _scene(b, s)
    k.sun(b, r.fork('sun'), *SUN, 5)
    _garden(b)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _scene(b, s)
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    k.stars(b, r.fork('stars'), 3, (84, 6, 150, 40), avoid=[(mx, my, mr + 9), (98, 43, 11)])
    _garden(b)
