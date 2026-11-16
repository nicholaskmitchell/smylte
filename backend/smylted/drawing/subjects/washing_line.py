"""A washing line.

Day: two posts and two lines across the grass, a basket at the foot. Each
finished task pegs out a coral garment; Start puts wind in the line; with
everything done the basket stands empty; a day with nothing planned shows the
bare lines with their pegs; overdue work brings a cloud, a bigger one at more.

Night: the same posts and lines strung with small bulbs beside a house with a
lit window. Each finished task lights a bulb; Start sways the line; with
everything done a second window lights; overdue work edges a cloud onto the
moon. The garments are in for the night.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

GROUND = 186.0
LEFT, RIGHT = 16.0, 144.0
TOPS = (54.0, 94.0)       # where each line meets the posts
SAG = 10.0


def _sag(x: float, y0: float) -> float:
    t = (x - LEFT) / (RIGHT - LEFT)
    return y0 + SAG * 4 * t * (1 - t)


class WashingLine:
    id = 'washing-line'
    since = date(2026, 1, 1)
    until = None

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    slots = []
    for i in range(k.REWARDS):
        row, col = i % 2, i // 2                      # alternate lines, so both fill
        x = LEFT + 14 + col * 20 + r.uniform(-1.5, 1.5)
        slots.append((x, _sag(x, TOPS[row]), row))
    return {
        'slots': slots,
        'kinds': [r.choice(['shirt', 'socks', 'towel', 'dress']) for _ in range(k.REWARDS)],
        'tufts': [r.uniform(24, 136) for _ in range(5)],
    }


def _frame(b: SketchBuilder, s: dict) -> None:
    for x in (LEFT, RIGHT):
        b.line(line((x, GROUND + 1), (x + 0.6, TOPS[0] - 6)))
        b.line(line((x - 7, TOPS[0] - 4), (x + 7, TOPS[0] - 4.5)))
    for y0 in TOPS:
        pts = [(x, _sag(x, y0)) for x in (LEFT, 48, 80, 112, RIGHT)]
        b.line(curve(*pts))
    b.line(line((4, GROUND), (156, GROUND + 0.6)))
    for x in s['tufts']:
        b.line(curve((x - 3, GROUND), (x - 1, GROUND - 4.6), (x, GROUND - 6)))
        b.line(curve((x + 1, GROUND), (x + 2.4, GROUND - 4), (x + 4, GROUND - 5)))


def _basket(b: SketchBuilder) -> None:
    b.line(loop((26, GROUND - 14), (54, GROUND - 14), (51, GROUND), (29, GROUND)))
    b.line(line((27, GROUND - 7), (52.5, GROUND - 7)))
    for x in (34, 40, 46):
        b.line(line((x, GROUND - 13), (x - 0.5, GROUND - 1)))


def _garment(kind: str, x: float, y: float):
    """The outline of one garment hanging from (x, y) on the line."""
    if kind == 'shirt':
        return poly((x - 7, y), (x - 2, y), (x, y + 2), (x + 2, y), (x + 7, y), (x + 10, y + 5),
                    (x + 6, y + 7), (x + 5.5, y + 17), (x - 5.5, y + 17), (x - 6, y + 7), (x - 10, y + 5))
    if kind == 'socks':
        return poly((x - 6, y), (x - 2, y), (x - 2, y + 10), (x + 3, y + 13), (x + 2, y + 16),
                    (x - 6, y + 12))
    if kind == 'towel':
        return poly((x - 7, y), (x + 7, y), (x + 7.4, y + 18), (x - 6.6, y + 18))
    return poly((x - 4, y), (x + 4, y), (x + 5, y + 6), (x + 9, y + 19), (x - 9, y + 19), (x - 5, y + 6))


def _pegs(b: SketchBuilder, x: float, y: float, *, when: tuple) -> None:
    for dx in (-4, 4):
        b.line(line((x + dx, y - 2.4), (x + dx, y + 3)), when=when)


def _wind(frame: int, child: SketchBuilder) -> None:
    """Start: three gusts cross the line, a loop at 6fps."""
    for j in range(3):
        x = 20 + ((frame * 22 + j * 46) % 120)
        y = 30 + j * 30
        child.line(curve((x, y), (x + 8, y - 2.4), (x + 15, y + 0.6), (x + 18, y - 2)))


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.blob(80, GROUND + 4, 86, 14, r.fork('hill'), n=12, wobble=0.04))
    k.sun(b, 28, 22, 7, when=(k.MORNING,))
    k.sun(b, 80, 16, 7.5, when=(k.MIDDAY,))
    k.sun(b, 132, 22, 7, when=(k.AFTERNOON,))
    k.low_sun(b, 120, GROUND - 0.5, 8, when=(k.EVENING,))
    k.cloud(b, 100, 26, 30, when=(('overdue', 1),))
    k.cloud(b, 60, 34, 22, when=(('overdue', 2),))
    k.cloud(b, 128, 40, 18, when=(('overdue', 3),))
    _frame(b, s)
    _basket(b)
    b.line(curve((31, GROUND - 14), (36, GROUND - 20), (42, GROUND - 17), (49, GROUND - 21), (52, GROUND - 14)),
           when=(('planned',), ('notAllDone',)))
    for x, y, _row in s['slots'][:6]:
        _pegs(b, x, y, when=(('nothingPlanned',),))
    for i, ((x, y, _row), kind) in enumerate(zip(s['slots'], s['kinds'])):
        shape = _garment(kind, x, y + 1)
        when = (('reward', i),)
        b.accent(shape, when=when)
        b.line(shape, when=when)
        _pegs(b, x, y, when=when)
    b.ambient(1.0, (('focus',),), _wind)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    moons = ((30, 22, k.MORNING), (80, 16, k.MIDDAY), (130, 22, k.AFTERNOON), (128, 20, k.EVENING))
    for x, y, hour in moons:
        k.moon(b, x, y, 6.5, when=(hour,))
        k.cloud(b, x + 6, y + 5, 22, when=(hour, ('overdue', 1)))
        k.cloud(b, x - 12, y + 12, 16, when=(hour, ('overdue', 2)))
    k.stars(b, r.fork('stars'), 4, (40, 8, 116, 30))
    # The house: its lit window is the light the line hangs by.
    hx, hy = 112, GROUND
    b.line(poly((hx - 18, hy), (hx - 18, hy - 26), (hx, hy - 40), (hx + 18, hy - 26), (hx + 18, hy)))
    b.wash(k.ring(hx - 6, hy - 16, 9, 9))
    b.line(poly((hx - 11, hy - 21), (hx - 1, hy - 21), (hx - 1, hy - 11), (hx - 11, hy - 11)))
    b.wash(k.ring(hx + 8, hy - 16, 8, 9), when=(('allDone',),))
    b.line(poly((hx + 3, hy - 21), (hx + 13, hy - 21), (hx + 13, hy - 11), (hx + 3, hy - 11)))
    _frame(b, s)
    _basket(b)
    for i, (x, y, _row) in enumerate(s['slots']):
        b.line(line((x, y), (x, y + 3)))
        b.line(k.ring(x, y + 5.6, 2.4, 7))
        k.glow_dot(b, x, y + 5.6, 2.2, halo=6, when=(('reward', i),))
    b.ambient(1.0, (('focus',),), _wind)
