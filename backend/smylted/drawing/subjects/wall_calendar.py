"""A wall calendar, today marked: the Calendar view's drawing.

Day: a calendar page hanging from a nail on a string, spiral rings across its
top, the month in a sage header band, and below it a grid of days. The first
week is crossed off; today, the next day, is filled coral and ringed by hand.
The page's bottom right corner curls up.

Night: the same calendar under a crescent moon in the top right corner, with
stars in the top corners. The moonlight falls across the page's upper right,
and today keeps its coral with a soft light of its own.

A view drawing: still, and the same whatever the day's state.
"""
from __future__ import annotations

import math

from ..pen import PEN, WOBBLE, curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

NAIL = (80.0, 14.0)
PAGE = (27.0, 44.0, 133.0, 184.0)     # x0, y0, x1, y1
HEADER = 66.0                         # the header band's lower edge
RINGS = (48.0, 64.0, 80.0, 96.0, 112.0)
# The curl: where the cut leaves the right edge and the bottom, and the
# folded corner's tip.
CUT = ((133.0, 168.0), (117.0, 184.0))
TIP = (120.5, 171.0)
DAY = 12.5                            # a day square's side
COLS = tuple(32.75 + 20.5 * i for i in range(5))
ROWS = tuple(74.0 + 25.0 * j for j in range(4))
CROSSED = 7                           # days crossed off; today is the next
MOON = (140.0, 24.0, 9.0)
# Ink and wobble on one side of a line: what a star's reach must clear.
INK = PEN / 2 + WOBBLE


class WallCalendar:
    id = 'wall-calendar'
    JOINS = frozenset(frozenset(p) for p in (
        ('string', 'nail'), ('string', 'page'), ('curl', 'page'), ('ring', 'page'),
        ('cross', 'day'), ('today', 'day'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, still=True)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s)
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same calendar."""
    crosses = []
    for _ in range(CROSSED):
        crosses.append(tuple(r.uniform(1.2, 2.2) for _ in range(8)))
    return {
        'month': [r.uniform(-0.8, 0.8) for _ in range(7)],
        'crosses': crosses,
        'ring_start': r.uniform(-1.2, -0.6),
    }


def _days() -> list[tuple[float, float]]:
    """The top left corner of each day square, in reading order."""
    return [(x, y) for y in ROWS for x in COLS]


def _square(x: float, y: float):
    return poly((x, y), (x + DAY, y), (x + DAY, y + DAY), (x, y + DAY))


def _header_outline():
    x0, y0, x1, _ = PAGE
    return poly((x0, y0), (x1, y0), (x1, HEADER), (x0, HEADER))


def _calendar(b: SketchBuilder, s: dict) -> None:
    x0, y0, x1, y1 = PAGE
    b.line(k.ring(*NAIL, 1.4, 6), part='nail')
    b.line(line((x0 + 0.5, y0), (NAIL[0], NAIL[1] + 1.6), (x1 - 0.5, y0)), part='string')
    # Ruled straight, not bowed: the days sit close inside its edges.
    b.line(loop((x0, y0), (x1, y0), CUT[0], CUT[1], (x0, y1), corners=(0, 1, 2, 3, 4)),
           part='page')
    b.line(line((x0, HEADER), (x1, HEADER)), part='page')
    # The corner curling up off the cut, a little proud of where it would lie.
    b.line(curve(CUT[0], (126.0, 168.6), TIP, (118.6, 177.0), CUT[1], corners=(2,)), part='curl')
    for i, x in enumerate(RINGS):
        b.line(ellipse(x, y0, 2.4, 4.5, n=8), part=f'ring:{i}')
    # The month's name: a short wavy line in the band.
    my = (y0 + HEADER) / 2 + 1.5
    b.line(curve(*[(60.0 + 40.0 * i / 6, my + w) for i, w in enumerate(s['month'])]), part='month')
    days = _days()
    for i, (x, y) in enumerate(days):
        if i == CROSSED:
            continue
        b.line(_square(x, y), part=f'day:{i}')
    for i, (a, bb, c, d, e, f, g, h) in enumerate(s['crosses']):
        x, y = days[i]
        b.line(line((x + a, y + bb), (x + DAY - c, y + DAY - d)), part=f'cross:{i}')
        b.line(line((x + DAY - e, y + f), (x + g, y + DAY - h)), part=f'cross:{i}')


def _today(b: SketchBuilder, s: dict) -> None:
    """Today: the coral square, and a ring drawn round it by hand, its ends
    overlapping a little."""
    x, y = _days()[CROSSED]
    b.filled(_square(x, y), part=f'day:{CROSSED}')
    cx, cy = x + DAY / 2, y + DAY / 2
    start = s['ring_start']
    sweep = 2 * math.pi + 0.5
    pts = []
    for i in range(13):
        a = start + sweep * i / 12
        grow = 0.9 * i / 12
        pts.append((cx + (9.8 + grow) * math.cos(a), cy + (11.2 + grow) * math.sin(a)))
    b.line(curve(*pts), part='today')


def _day(b: SketchBuilder, s: dict) -> None:
    b.wash(k.wash_of(_header_outline(), inset=0.9, dx=3, dy=2), part='page')
    _calendar(b, s)
    _today(b, s)


def _segment_distance(p, a, c) -> float:
    ax, ay = a
    dx, dy = c[0] - ax, c[1] - ay
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _sky(p) -> bool:
    """Above the string and the page, clear of the string's ink."""
    x0, y0, x1, _ = PAGE
    left, apex, right = (x0, y0), (NAIL[0], NAIL[1] + 1.6), (x1, y0)
    if x0 <= p[0] <= x1:
        side = (left, apex) if p[0] <= apex[0] else (apex, right)
        (ax, ay), (cx, cy) = side
        if p[1] >= ay + (cy - ay) * (p[0] - ax) / (cx - ax):
            return False
    elif p[1] >= y0:
        return False
    # The string may bow by a unit or so as the hand draws it.
    return min(_segment_distance(p, left, apex), _segment_distance(p, apex, right)) >= INK + 1.0


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(_header_outline(), inset=0.9, dx=3, dy=2), part='page')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    # The moonlight falling across the page's upper right: the standing light.
    b.glow(ellipse(110.0, 66.0, 32.0, 21.0, n=12, rot=-0.45), part='moonlight')
    avoid = [(mx, my, mr + INK + 1.0), (*NAIL, 1.4 + INK + 1.0)]
    k.stars(b, r.fork('stars-left'), 2, (9.0, 7.0, 62.0, 38.0), avoid=avoid, ok=_sky,
            part='star')
    k.stars(b, r.fork('stars-right'), 2, (92.0, 7.0, 128.0, 32.0), avoid=avoid, ok=_sky,
            part='spark')
    x, y = _days()[CROSSED]
    b.glow(k.ring(x + DAY / 2, y + DAY / 2, 15.0, 11), part='today')
    _calendar(b, s)
    _today(b, s)
