"""A desk with a kettle.

Day: a desk under a window in daylight: a mug, an open notebook, a kettle on a
sage wash. Each finished task pins a coral note to the wall; Start sends steam
up from the mug; everything done closes the notebook with a pencil on it; a
day with nothing planned leaves the notebook's pages blank; overdue work is a
small stack of papers at the desk's end, a sheet per level.

Night: the same desk with the lamp on. The lamp is the light: its glow pools
on the desk (the only wash), the window is dark with the moon in a pane, and
the notes on the wall catch the light. Start curls steam through it.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

TOP = 150.0          # the desk's surface
WIN = (14.0, 16.0, 70.0, 80.0)


class DeskWithKettle:
    id = 'desk'
    since = date(2026, 1, 1)
    until = None

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        _common(b, s)
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    notes = []
    cols, rows = 4, 3
    for i in range(k.REWARDS):
        col, row = i % cols, i // cols
        x = 86 + col * 16 + r.uniform(-1.5, 1.5)
        y = 22 + row * 18 + r.uniform(-1.5, 1.5)
        notes.append((x, y, math.radians(r.uniform(-9, 9))))
    return {
        'kettle_x': r.uniform(126, 132),
        'mug_x': r.uniform(48, 52),
        'notes': notes,
        'lines': [r.uniform(0.55, 0.95) for _ in range(6)],
        'papers': [math.radians(r.uniform(-10, 10)) for _ in range(3)],
    }


def _common(b: SketchBuilder, s: dict) -> None:
    b.line(line((4, TOP), (156, TOP + 0.5)))
    b.line(line((4, TOP + 7), (156, TOP + 7.4)))
    b.line(line((14, TOP + 7), (14, 198)))
    b.line(line((146, TOP + 7.4), (146, 198)))
    x0, y0, x1, y1 = WIN
    b.line(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    b.line(line(((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)))
    b.line(line((x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)))
    b.line(line((x0 - 4, y1 + 3), (x1 + 4, y1 + 3)))
    _kettle(b, s['kettle_x'])
    _mug(b, s['mug_x'])
    _notebook(b, s)
    _papers(b, s)


def _kettle(b: SketchBuilder, x: float) -> None:
    b.line(loop((x - 16, TOP), (x - 17, TOP - 16), (x - 9, TOP - 27), (x + 9, TOP - 27),
                (x + 17, TOP - 16), (x + 16, TOP)))
    b.line(curve((x - 16, TOP - 12), (x - 24, TOP - 18), (x - 28, TOP - 26)))     # spout
    b.line(curve((x - 10, TOP - 27), (x - 6, TOP - 40), (x + 6, TOP - 40), (x + 10, TOP - 27)))
    b.line(loop((x - 3, TOP - 27), (x, TOP - 31), (x + 3, TOP - 27)))               # the lid's knob


def _mug(b: SketchBuilder, x: float) -> None:
    b.line(poly((x - 8, TOP - 20), (x + 8, TOP - 20), (x + 7, TOP), (x - 7, TOP)))
    b.line(curve((x + 8, TOP - 16), (x + 14, TOP - 14), (x + 13, TOP - 6), (x + 7.4, TOP - 5)))


def _notebook(b: SketchBuilder, s: dict) -> None:
    open_ = (('notAllDone',),)
    b.line(curve((66, TOP - 7), (76, TOP - 10), (85, TOP - 7)), when=open_)
    b.line(curve((85, TOP - 7), (94, TOP - 10), (104, TOP - 7)), when=open_)
    b.line(line((64, TOP), (106, TOP)), when=open_)
    b.line(line((66, TOP - 7), (64, TOP)), when=open_)
    b.line(line((104, TOP - 7), (106, TOP)), when=open_)
    b.line(line((85, TOP - 7), (85, TOP)), when=open_)
    for i, frac in enumerate(s['lines']):                     # writing, if the day has any
        x0 = 69 if i < 3 else 88
        y = TOP - 5.6 + (i % 3) * 1.8
        b.line(line((x0, y), (x0 + 13 * frac, y)), when=(('notAllDone',), ('planned',)))
    done = (('allDone',),)
    b.line(poly((66, TOP - 6), (104, TOP - 6), (106, TOP), (64, TOP)), when=done)
    b.line(line((70, TOP - 9), (100, TOP - 12)), when=done)                         # the pencil
    b.line(line((100, TOP - 12), (103, TOP - 12.6)), when=done)


def _papers(b: SketchBuilder, s: dict) -> None:
    for level, a in enumerate(s['papers'], start=1):
        cx, cy, w, h = 22, TOP - 2 - level * 2.2, 22, 3
        c, sn = math.cos(a), math.sin(a)
        pts = [(cx + dx * c - dy * sn, cy + dx * sn + dy * c)
               for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
        b.line(poly(*pts), when=(('overdue', level),))


def _notes(b: SketchBuilder, s: dict) -> None:
    for i, (x, y, a) in enumerate(s['notes']):
        c, sn = math.cos(a), math.sin(a)
        pts = [(x + dx * c - dy * sn, y + dx * sn + dy * c)
               for dx, dy in ((-6, -6), (6, -6), (6, 6), (-6, 6))]
        when = (('reward', i),)
        b.accent(poly(*pts), when=when)
        b.line(poly(*pts), when=when)


def _steam(s: dict):
    def draw(frame: int, child: SketchBuilder) -> None:
        k.steam(child, s['mug_x'], TOP - 24, frame, 6, height=20)
    return draw


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    k.sun(b, x0 + 13, y0 + 13, 5, when=(k.MORNING,))
    k.sun(b, x1 - 13, y0 + 12, 5.5, when=(k.MIDDAY,))
    k.sun(b, x1 - 12, y1 - 14, 5, when=(k.AFTERNOON,))
    k.low_sun(b, (x0 + x1) / 2, y1 - 2, 6, when=(k.EVENING,))
    b.wash(k.blob(s['kettle_x'] + 2, TOP - 13, 22, 17, r.fork('wash'), n=9, wobble=0.08))
    _notes(b, s)
    b.ambient(1.0, (('focus',),), _steam(s))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    k.moon(b, x0 + 13, y0 + 13, 5, glow=False, when=(k.MORNING,))
    k.moon(b, x1 - 13, y0 + 13, 5.5, glow=False, when=(k.MIDDAY,))
    k.moon(b, x1 - 13, y1 - 15, 5, glow=False, when=(k.AFTERNOON,))
    k.moon(b, x0 + 14, y1 - 15, 5.5, glow=False, when=(k.EVENING,))
    # The lamp: its pool of light on the desk is the night's one wash.
    b.wash(k.blob(66, TOP - 1, 36, 7, r.fork('pool'), n=9, wobble=0.05))
    b.wash(k.ring(62, TOP - 33, 8, 9))
    b.line(curve((26, TOP), (34, TOP - 4.5), (42, TOP)))                          # the base
    b.line(line((34, TOP - 4), (30, TOP - 30)))                                    # lower arm
    b.line(line((30, TOP - 30), (48, TOP - 48)))                                   # upper arm
    ax, ay = 10 / 17.2, 14 / 17.2                                                  # the shade's axis
    px, py = ay, -ax
    n, w = (50.0, TOP - 50), (60.0, TOP - 36)
    b.line(poly((n[0] + 3 * px, n[1] + 3 * py), (w[0] + 10 * px, w[1] + 10 * py),
                (w[0] - 10 * px, w[1] - 10 * py), (n[0] - 3 * px, n[1] - 3 * py)))
    _notes(b, s)
    b.ambient(1.0, (('focus',),), _steam(s))
