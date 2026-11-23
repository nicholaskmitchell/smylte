"""July: at the seaside.

Day: a beach parasol planted in the sand left of centre, its canopy in panels,
every other one coral. A striped deck chair stands beside it, a bucket and
spade in front, and behind them the sea's line with a small sailboat on it.
Two gulls fly, and the sun is out.

Night: the parasol furled, the deck chair folded flat on the sand, a moon low
over the sea with its glow and its light lying soft on the water, and stars.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import curve, ellipse, line, loop, poly
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

SEA = 66.0                               # the sea's line, behind the beach
# The parasol: its canopy's apex, its lean, its half-width, and how far down
# the rim hangs below the apex.
APEX = (60.0, 30.0)
LEAN = -0.13
HALF, RIM, DOME = 30.0, 13.0, 14.0
RIBS = (-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)  # where the ribs meet the rim, in half-widths
# The deck chair: its rails' x at the seat, the canvas's top and front
# edge, how far back the top leans, and the stripes, in widths of the canvas.
CHAIR = (122.0, 148.0)
CHAIR_TOP, CHAIR_SEAT, CHAIR_LEAN = 52.0, 80.0, 7.0
STRIPES = (0.2, 0.4, 0.6, 0.8)
BUCKET = (82.0, 96.0)                    # the bucket's left and right at the rim
BOAT = (178.0, SEA)
GULLS = ((104.0, 20.0), (122.0, 30.0))
SUN = (176.0, 17.0, 5.0)
MOON = (158.0, 46.0, 6.5)


class July:
    id = 'month-july'
    JOINS = frozenset(frozenset(p) for p in (
        ('parasol', 'ground'), ('chair', 'ground'), ('bucket', 'ground'), ('spade', 'ground'),
        ('boat', 'sea'),
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
    """What both compositions share, so the night is the same beach."""
    return {
        'ground': [r.uniform(-0.5, 0.5) for _ in range(3)],
        'sea': [r.uniform(-0.4, 0.4) for _ in range(8)],
        'shade': k.blob(70.0, GROUND - 1.0, 24.0, 3.6, r.fork('shade'), n=11, wobble=0.06),
    }


def _at(u: float, v: float) -> tuple[float, float]:
    """A point in the parasol's own frame (u across, v down its pole from
    the apex) on the page."""
    c, s = math.cos(LEAN), math.sin(LEAN)
    return (APEX[0] + u * c - v * s, APEX[1] + u * s + v * c)


def _pole_foot() -> tuple[float, float]:
    v = (GROUND - 0.4 - APEX[1]) / math.cos(LEAN)
    return _at(0.0, v)


def _rib(c: float, n: int = 5) -> list[tuple[float, float]]:
    """A rib from the apex to the rim, as a meridian of the dome seen from the side."""
    return [_at(HALF * math.sin(math.pi / 2 * i / n) * c, RIM - DOME * math.cos(math.pi / 2 * i / n))
            for i in range(n + 1)]


def _canopy(b: SketchBuilder) -> None:
    """The coral note: the canopy's panels, every other one filled, each
    closing along a scallop of the rim."""
    for i, (c0, c1) in enumerate(zip(RIBS, RIBS[1:])):
        a, z = _rib(c0), _rib(c1)
        sag = _at(HALF * (c0 + c1) / 2, RIM + 2.6)
        pts = [*a, sag, *reversed(z[1:])]
        shape = loop(*pts, corners=(0, len(a) - 1, len(a) + 1))
        if i % 2 == 0:
            b.filled(shape, part='parasol', paper='glint')
        else:
            b.line(shape, part='parasol')
    b.line(line(_at(0.0, RIM - DOME), _at(0.0, RIM - DOME - 4.0)), part='parasol')


def _pole(b: SketchBuilder, top_v: float) -> None:
    b.line(line(_at(0.0, top_v), _pole_foot()), part='parasol')


def _furled(b: SketchBuilder) -> None:
    """At night the parasol is furled: its cloth a closed coral spindle
    round the top of the pole."""
    pts = [_at(0.0, -4.0), _at(3.2, 6.0), _at(4.2, 16.0), _at(2.6, 28.0), _at(0.0, 31.0),
           _at(-2.6, 28.0), _at(-4.2, 16.0), _at(-3.2, 6.0)]
    b.filled(loop(*pts, corners=(0, 4)), part='parasol', paper='glint')
    b.line(line(_at(-3.6, 21.0), _at(3.6, 21.0)), part='parasol')
    b.line(line(_at(0.0, -4.0), _at(0.0, -8.0)), part='parasol')


def _deck_chair(b: SketchBuilder) -> None:
    """The deck chair, three-quarters on: two rails leaning back, the canvas
    slung between them with its stripes running down it, the front legs
    standing on the sand and the back legs reaching behind."""
    (lx, rx), top, seat = CHAIR, CHAIR_TOP, CHAIR_SEAT
    lean = CHAIR_LEAN
    for x in (lx, rx):
        b.line(line((x + lean - 0.4, top - 3.0), (x, seat), (x - 2.4, GROUND - 0.4)), part='chair')
        b.line(line((x + 1.0, seat + 1.5), (x + 8.0, GROUND - 0.4)), part='chair')
    # The canvas's top and its front edge, sagging a little under nobody.
    b.line(line((lx + lean, top), (rx + lean, top - 0.6)), part='chair')
    b.line(curve((lx, seat), ((lx + rx) / 2, seat + 2.0), (rx, seat)), part='chair')
    for f in STRIPES:
        x0 = lx + (rx - lx) * f
        b.line(line((x0 + lean, top - 0.6 * f + 0.4), (x0, seat + 2.0 * (1 - (2 * f - 1) ** 2) - 0.4)),
               part='chair')


def _folded(b: SketchBuilder) -> None:
    """At night the deck chair is folded flat and laid on the sand: its
    striped canvas resting on the ground, clear of the moon's path."""
    x0, x1 = 114.0, 148.0
    y0, y1 = GROUND - 6.5, GROUND - 0.4
    b.line(poly((x0, y0), (x1, y0 - 0.5), (x1, y1), (x0, y1)), part='chair')
    for f in (0.25, 0.5, 0.75):
        x = x0 + (x1 - x0) * f
        b.line(line((x, y0 - 0.2), (x + 0.2, y1 - 0.2)), part='chair')


def _bucket_and_spade(b: SketchBuilder) -> None:
    l, r = BUCKET
    h = 12.0
    g = GROUND - 0.4
    b.line(poly((l, g - h), (r, g - h), (r - 2.0, g), (l + 2.0, g)), part='bucket')
    hr = (r - l) / 2 - 1.2
    hc = ((l + r) / 2, g - h + 0.6)
    b.line(curve(*[(hc[0] - hr * math.cos(math.pi * i / 6), hc[1] - hr * 0.8 * math.sin(math.pi * i / 6))
                   for i in range(7)]), part='bucket')
    # The spade stuck in the sand beside it, leaning away.
    blade = ((r + 6.0, g), (r + 11.5, g - 0.4), (r + 11.0, g - 7.0), (r + 6.4, g - 7.0))
    b.line(loop(*blade, corners=(0, 1, 2, 3)), part='spade')
    b.line(line((r + 8.8, g - 7.0), (r + 11.0, g - 20.0)), part='spade')
    b.line(line((r + 9.0, g - 20.6), (r + 13.0, g - 19.8)), part='spade')


def _sea(b: SketchBuilder, s: dict, gaps: list[tuple[float, float]]) -> None:
    """The sea's line, broken where something on the beach stands in front of it."""
    j = s['sea']
    edges = [6.0]
    for a, z in sorted(gaps):
        edges += [a, z]
    edges.append(194.0)
    for i in range(0, len(edges), 2):
        x0, x1 = edges[i], edges[i + 1]
        if x1 - x0 < 4.0:
            continue
        b.line(line((x0, SEA + j[i % 8]), (x1, SEA + j[(i + 1) % 8])), part='sea')


def _ground(b: SketchBuilder, s: dict) -> None:
    g = s['ground']
    b.line(curve((6.0, GROUND + g[0]), (100.0, GROUND + g[1]), (194.0, GROUND + g[2])), part='ground')


def _boat(b: SketchBuilder) -> None:
    """A small sailboat on the sea's line: a hull, a mast, a mainsail aft
    and a jib before it."""
    x, y = BOAT
    b.line(loop((x - 10.0, y - 5.0), (x + 11.0, y - 5.0), (x + 7.0, y - 0.8), (x - 7.0, y - 0.8),
                corners=(0, 1, 2, 3)), part='boat')
    b.line(line((x, y - 5.0), (x, y - 26.0)), part='boat')
    b.line(line((x, y - 25.0), (x - 9.0, y - 7.5), (x, y - 7.5)), part='boat')
    b.line(line((x, y - 22.0), (x + 8.5, y - 7.5), (x, y - 7.5)), part='boat')


def _gull(b: SketchBuilder, x: float, y: float, i: int) -> None:
    b.line(curve((x - 6.5, y + 1.4), (x - 3.4, y - 1.4), (x, y + 0.2), (x + 3.4, y - 1.4), (x + 6.5, y + 1.4),
                 corners=(2,)), part=f'gull:{i}')


def _pole_x(y: float) -> float:
    fx, fy = _pole_foot()
    return fx + (APEX[0] - fx) * (fy - y) / (fy - APEX[1])


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(s['shade'], part='shade')
    k.sun(b, r.fork('sun'), *SUN)
    _ground(b, s)
    px = _pole_x(SEA)
    _sea(b, s, [(px - 7.0, px + 7.0), (CHAIR[0] - 4.0, CHAIR[1] + CHAIR_LEAN + 4.0)])
    _canopy(b)
    _pole(b, RIM + 2.6)
    _deck_chair(b)
    _bucket_and_spade(b)
    _boat(b)
    for i, (x, y) in enumerate(GULLS):
        _gull(b, x, y, i)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(s['shade'], part='shade')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    _ground(b, s)
    px = _pole_x(SEA)
    _sea(b, s, [(px - 7.0, px + 7.0)])
    # The moon's light on the water: a long, flat glow under it, just below
    # the sea's line, as the tide pool's reflection is drawn. Light, not ink.
    b.glow(ellipse(mx, SEA + 4.0, 17.0, 3.5, n=12), part='moonlight')
    _furled(b)
    _pole(b, 31.0)
    _folded(b)
    _bucket_and_spade(b)
    k.stars(b, r.fork('stars'), 5, (10.0, 8.0, 190.0, 34.0),
            avoid=[(mx, my, mr * 2.4), (APEX[0], APEX[1], 12.0)], gap=22.0)
