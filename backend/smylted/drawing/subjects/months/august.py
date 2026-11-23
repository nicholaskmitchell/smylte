"""August: sunflowers.

Day: three tall sunflowers of different heights in front of a picket fence,
each head a ring of ink petals round a coral disc, with big leaves on their
stems. A small bird sits on the fence's end post, and the sun is out.

Night: the heads bowed, turned down on their stems; a moon with its glow,
stars, and the end post empty.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import line, curve, loop
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The fence: its pickets' tops (the point above), their width and pitch, the
# rails, and the end post the bird sits on.
PICKET_TOP, POINT = 80.0, 76.0
PICKET, PITCH = 7.0, 13.0
PICKETS = (8.0, 172.0)                   # the first picket's left side, and where they stop
RAILS = (84.0, 93.0)
# How much further on the pickets right of the last stem stand (the end post
# with them), so that stem's gap is wider than the others: its low right leaf
# reaches out over the next picket's point.
WIDEN = 3.0
POST = (177.0 + WIDEN, 185.0 + WIDEN, 70.0)    # x0, x1, top
# The sunflowers: stem x (where a picket would stand, so it leaves just that
# one out), the head's centre height, and its leaves' heights and sides.
FLOWERS = (
    (50.5, 33.0, ((58.0, -1), (64.0, 1))),
    (102.5, 21.0, ((46.0, 1), (57.0, -1))),
    (141.5, 38.0, ((62.0, -1), (65.0, 1))),
)
PETALS, OUTER, INNER, DISC = 12, 15.0, 10.0, 7.5
LEAF = 17.0
SUN = (172.0, 18.0, 5.0)
MOON = (170.0, 24.0, 7.0)


class August:
    id = 'month-august'
    JOINS = frozenset(frozenset(p) for p in (
        ('fence', 'ground'), ('flower', 'ground'), ('bird', 'fence'),
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
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
        'rails': [r.uniform(-0.4, 0.4) for _ in range(40)],
        'turn': [r.uniform(0, 2 * math.pi / PETALS) for _ in FLOWERS],
    }


def _pickets() -> list[float]:
    """Each picket's left side, leaving out the ones a stem stands in front of."""
    out = []
    x = PICKETS[0]
    while x + PICKET <= PICKETS[1]:
        if all(abs(x + PICKET / 2 - fx) > PICKET for fx, _, _ in FLOWERS):
            out.append(x + (WIDEN if x > FLOWERS[-1][0] else 0.0))
        x += PITCH
    return out


def _fence(b: SketchBuilder, s: dict) -> None:
    g = GROUND - 0.4
    xs = _pickets()
    for x in xs:
        b.line(line((x, g), (x, PICKET_TOP), (x + PICKET / 2, POINT), (x + PICKET, PICKET_TOP), (x + PICKET, g)),
               part='fence')
    x0, x1, top = POST
    b.line(line((x0, g), (x0, top), (x1, top), (x1, g)), part='fence')
    b.line(line((x0 - 1.8, top - 0.2), (x0 + 1.0, top - 3.6), (x1 - 1.0, top - 3.6), (x1 + 1.8, top - 0.2)),
           part='fence')
    # The rails run behind the pickets: only the spans between them show.
    j = iter(s['rails'])
    edges = sorted(x for p in xs for x in (p, p + PICKET)) + [x0]
    for y in RAILS:
        for a, z in zip(edges[1::2], edges[2::2]):
            if z - a > PITCH:                 # a stem stands in this gap
                continue
            d = next(j) if a < 100 else -next(j)
            b.line(line((a, y + d), (z, y - d)), part='fence')


def _leaves(i: int) -> list:
    x, hy, leaves = FLOWERS[i]
    out = []
    for y, side in leaves:
        ang = math.pi / 2 - side * (math.pi / 2 - 0.3)       # out and a little down
        out.append(((x + side * 0.6, y), k.leaf(x + side * 0.6, y, LEAF, ang), ang))
    return out


def _stem_and_leaves(b: SketchBuilder, i: int, top: float) -> None:
    x, hy, _ = FLOWERS[i]
    part = f'flower:{i}'
    b.line(curve((x, GROUND - 0.4), (x, PICKET_TOP), (x + 0.8, (PICKET_TOP + top) / 2), (x + 0.4, top)),
           part=part)
    for (sx, sy), outline, ang in _leaves(i):
        b.line(outline, part=part)
        tip = (sx + 0.14 * LEAF * math.cos(ang), sy + 0.14 * LEAF * math.sin(ang))
        b.line(line((sx, sy), tip), part=part)
        # The midrib.
        b.line(line(tip, (sx + 0.8 * LEAF * math.cos(ang), sy + 0.8 * LEAF * math.sin(ang))), part=part)


def _head(b: SketchBuilder, cx: float, cy: float, turn: float, part: str, *,
          rx: float = 1.0, ry: float = 1.0, tilt: float = 0.0) -> None:
    """A sunflower's head: a ring of pointed petals round a coral disc.
    Squashed by (rx, ry) and turned by `tilt`, it is a head seen edge on."""
    c, sn = math.cos(tilt), math.sin(tilt)

    def at(u: float, v: float) -> tuple[float, float]:
        u, v = u * rx, v * ry
        return (cx + u * c - v * sn, cy + u * sn + v * c)

    pts = []
    for j in range(PETALS * 2):
        a = turn + math.pi * j / PETALS
        rr = OUTER if j % 2 == 0 else INNER
        pts.append(at(rr * math.cos(a), rr * math.sin(a)))
    b.line(loop(*pts, corners=tuple(range(0, PETALS * 2, 2))), part=part)
    b.filled(loop(*[at(DISC * math.cos(2 * math.pi * j / 10), DISC * math.sin(2 * math.pi * j / 10))
                    for j in range(10)]), part=part, paper='glint')


def _ground(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6.0, GROUND + g[0]), (100.0, GROUND + g[1]), (194.0, GROUND + g[2])), part='ground')


def _scene(b: SketchBuilder, s: dict) -> None:
    for i in range(len(FLOWERS)):
        for _, outline, _ in _leaves(i):
            b.wash(k.wash_of(outline, inset=0.9, dx=1.6, dy=1.6), part=f'flower:{i}')
    _ground(b, s)
    _fence(b, s)


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _scene(b, s)
    for i, (x, hy, _) in enumerate(FLOWERS):
        _stem_and_leaves(b, i, hy + INNER)
        _head(b, x + 0.4, hy, s['turn'][i], f'flower:{i}')
    x0, x1, top = POST
    k.bird(b, (x0 + x1) / 2, top - 4.0, k_=1.1, facing=-1)
    k.sun(b, r.fork('sun'), *SUN)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    _scene(b, s)
    heads = []
    for i, (x, hy, leaves) in enumerate(FLOWERS):
        part = f'flower:{i}'
        # The stem rises a little less and bows over at the top; the head
        # hangs from it, turned down and away.
        crook = hy + 4.0
        _stem_and_leaves(b, i, crook)
        b.line(curve((x + 0.4, crook), (x + 1.6, crook - 6.0), (x + 6.0, crook - 7.5), (x + 10.0, crook - 4.0)),
               part=part)
        hx, hy2 = x + 15.0, crook + 9.0
        _head(b, hx, hy2, s['turn'][i], part, rx=1.0, ry=0.35, tilt=1.2)
        heads += [(hx, hy2, OUTER + 4.0), (x + 5.0, crook - 4.0, 10.0)]   # the head, and the crook above it
    avoid = [(mx, my, mr * 2.4)] + heads
    k.stars(b, r.fork('stars'), 5, (10.0, 8.0, 190.0, 40.0), avoid=avoid, gap=20.0)
