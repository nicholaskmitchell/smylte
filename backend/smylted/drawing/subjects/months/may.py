"""May: the hive and the meadow.

Day: a straw skep, its coils stacked up a dome, on a small wooden stand at the
left; tall meadow flowers across the rest, daisies, cow parsley and three
coral tulips; bees about the hive; a sun.

Night: the hive quiet, the bees gone in; the tulips closed into narrow buds;
a moon with its glow, stars, and a few fireflies over the meadow.

A month drawing: still, and the same whatever the day's state.
"""
from __future__ import annotations

import math

from ...pen import circle, curve, line, loop
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The stand's board, and the skep sitting on it: its base's ends and its crown.
BOARD = 80.0
SKEP = (14.0, 48.0, 46.0)
COILS = (71.0, 63.5, 56.0)
# The meadow, left to right: (kind, stem x, head height).
MEADOW = (
    ('daisy', 66.0, 64.0), ('tulip', 81.0, 70.0), ('parsley', 95.0, 44.0),
    ('daisy', 109.0, 58.0), ('tulip', 124.0, 64.0), ('daisy', 140.0, 70.0),
    ('parsley', 152.0, 40.0), ('tulip', 167.0, 66.0), ('daisy', 181.0, 56.0),
)
BEES = ((64.0, 40.0, 0.2), (56.0, 25.0, -0.3), (78.0, 30.0, 0.1))
SUN = (180.0, 18.0)
MOON = (116.0, 20.0, 7.0)
FIREFLIES = ((88.0, 66.0), (144.0, 58.0), (102.0, 74.0), (189.0, 76.0), (130.0, 46.0))


class May:
    id = 'month-may'
    JOINS = frozenset(frozenset(p) for p in (
        ('stand', 'ground'), ('skep', 'stand'), ('flower', 'ground'),
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
    """What both compositions share, so the night is the same meadow."""
    return {
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
        'lean': [r.uniform(-0.9, 0.9) for _ in MEADOW],
    }


def _skep_outline():
    x0, x1, top = SKEP
    mx = (x0 + x1) / 2
    return loop((x0, BOARD - 0.5), (x0 - 1.0, 68.0), (x0 + 4.0, 55.0), (mx, top),
                (x1 - 4.0, 55.0), (x1 + 1.0, 68.0), (x1, BOARD - 0.5), corners=(0, 6))


def _coil_span(y: float) -> tuple[float, float]:
    """Where a coil at height y meets the dome's sides, a little inside them."""
    x0, x1, top = SKEP
    mx, half = (x0 + x1) / 2, (x1 - x0) / 2 + 1.0
    # The dome is near enough a half-ellipse over its lower straight part.
    t = max(0.0, min(1.0, (68.0 - y) / (68.0 - top)))
    w = half * math.sqrt(max(0.0, 1 - t * t)) if y < 68.0 else half
    return mx - w + 0.6, mx + w - 0.6


def _hive(b: SketchBuilder) -> None:
    """The stand, and the skep on it: its coils bowing round the dome, and
    the entrance arched at its foot."""
    b.line(line((8.0, BOARD), (54.0, BOARD + 0.4)), part='stand')
    b.line(line((12.0, BOARD + 5.0), (52.0, BOARD + 5.4)), part='stand')
    for x in (14.0, 46.0):
        b.line(line((x, BOARD + 5.4), (x + (-1.5 if x < 30 else 1.5), GROUND)), part='stand')
    b.line(_skep_outline(), part='skep')
    for y in COILS:
        a, c = _coil_span(y)
        b.line(curve((a, y), ((a + c) / 2, y + 2.4), (c, y)), part='skep')
    mx = (SKEP[0] + SKEP[1]) / 2
    b.line(curve((mx - 4.5, BOARD - 0.5), (mx - 3.6, 76.0), (mx, 75.0), (mx + 3.6, 76.0),
                 (mx + 4.5, BOARD - 0.5)), part='skep')


def _daisy(b: SketchBuilder, x: float, top: float, lean: float, part: str) -> None:
    hx = x + lean
    b.line(curve((x, GROUND), (x + lean * 0.3, (GROUND + top) / 2), (hx, top + 5.0)), part=part)
    pts = []
    for j in range(16):
        a = 2 * math.pi * j / 16
        rr = 5.6 if j % 2 == 0 else 3.6
        pts.append((hx + rr * math.cos(a), top + rr * math.sin(a)))
    b.line(loop(*pts), part=part)
    b.line(circle(hx, top, 1.2, n=6), part=part)
    b.line(curve((x + 0.6, GROUND - 8.0), (x + 4.0, GROUND - 13.0), (x + 6.0, GROUND - 12.0)),
           part=part)


def _parsley(b: SketchBuilder, x: float, top: float, lean: float, part: str) -> None:
    """Cow parsley: a tall stem, rays fanning out from its head, and the flat
    lace of florets across their tips."""
    hx, hy = x + lean, top + 9.0
    b.line(curve((x, GROUND), (x + lean * 0.4, (GROUND + hy) / 2), (hx, hy)), part=part)
    tips = [(hx + dx, top + 0.12 * dx * dx / 3.0) for dx in (-9.0, -4.5, 0.0, 4.5, 9.0)]
    for tx, ty in tips:
        b.line(line((hx, hy), (tx, ty)), part=part)
    lace = []
    for i, (tx, ty) in enumerate(tips):
        lace.append((tx - 2.25, ty - 0.6))
        lace.append((tx, ty - 3.0))
    lace.append((tips[-1][0] + 2.25, tips[-1][1] - 0.6))
    b.line(curve(*lace, corners=tuple(range(0, len(lace), 2))), part=part)
    b.line(curve((x + 0.6, GROUND - 10.0), (x + 4.4, GROUND - 16.0), (x + 7.0, GROUND - 15.0)),
           part=part)


def _tulip(b: SketchBuilder, x: float, top: float, lean: float, part: str, *, open_: bool) -> None:
    hx = x + lean * 0.5
    b.line(curve((x, GROUND), (x + lean * 0.2, (GROUND + top) / 2), (hx, top + 8.0)), part=part)
    b.line(loop((x + 0.8, GROUND), (x + 4.0, GROUND - 14.0), (x + 5.4, GROUND - 24.0),
                (x + 2.2, GROUND - 14.0), corners=(0, 2)), part=part)
    if open_:
        head = loop((hx - 4.4, top - 1.0), (hx - 4.8, top + 4.0), (hx, top + 8.0), (hx + 4.8, top + 4.0),
                    (hx + 4.4, top - 1.0), (hx + 2.0, top + 1.6), (hx, top - 2.4), (hx - 2.0, top + 1.6),
                    corners=(0, 4, 5, 6, 7))
    else:
        head = loop((hx - 3.0, top + 4.0), (hx - 2.4, top + 0.6), (hx, top - 3.0), (hx + 2.4, top + 0.6),
                    (hx + 3.0, top + 4.0), (hx, top + 8.0), corners=(2,))
    b.filled(head, part=part)


def _meadow(b: SketchBuilder, s: dict, *, open_: bool) -> None:
    for i, ((kind, x, top), lean) in enumerate(zip(MEADOW, s['lean'])):
        part = f'flower:{i}'
        if kind == 'daisy':
            _daisy(b, x, top, lean, part)
        elif kind == 'parsley':
            _parsley(b, x, top, lean, part)
        else:
            _tulip(b, x, top, lean, part, open_=open_)


def _bee(b: SketchBuilder, x: float, y: float, tilt: float, part: str) -> None:
    """A bee in flight, heading right: a body pointed at its sting, a stripe
    across it, and two wings swept back over it."""
    c, sn = math.cos(tilt), math.sin(tilt)

    def at(u: float, v: float) -> tuple[float, float]:
        return (x + u * c - v * sn, y + u * sn + v * c)

    b.line(loop(at(4.4, 0.0), at(2.4, -2.9), at(-2.0, -2.8), at(-5.4, 0.0), at(-2.0, 2.8), at(2.4, 2.9),
                corners=(3,)), part=part)
    b.line(line(at(0.0, -2.8), at(0.0, 2.8)), part=part)
    for u, v in ((-1.2, -5.4), (-4.0, -4.8)):
        b.line(loop(at(0.6 + (u + 1.2) * 0.3, -2.9), at(u + 1.2, v), at(u - 1.4, v - 0.4), at(u - 1.0, -3.0)),
               part=part)


def _ground(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6.0, GROUND + g[0]), (100.0, GROUND + g[1]), (194.0, GROUND + g[2])),
           part='ground')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(_skep_outline(), dx=3.0, dy=2.5), part='skep')
    k.sun(b, r.fork('sun'), *SUN, 5)
    _ground(b, s)
    _hive(b)
    _meadow(b, s, open_=True)
    for i, (x, y, tilt) in enumerate(BEES):
        _bee(b, x, y, tilt, f'bee:{i}')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(_skep_outline(), dx=3.0, dy=2.5), part='skep')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    for x, y in FIREFLIES:
        b.glow(circle(x, y, 4.6, n=8), part='firefly')
    avoid = [(mx, my, mr + 4.0), (95.0, 44.0, 12.0), (152.0, 40.0, 12.0)]
    k.stars(b, r.fork('stars'), 3, (10.0, 8.0, 96.0, 40.0), avoid=avoid)
    k.stars(b, r.fork('stars-right'), 3, (128.0, 8.0, 192.0, 32.0), avoid=avoid, part='spark')
    _ground(b, s)
    _hive(b)
    _meadow(b, s, open_=False)
    # Each firefly's own spark of ink at the heart of its glow.
    for x, y in FIREFLIES:
        b.line(circle(x, y, 0.8, n=6), part='firefly')
