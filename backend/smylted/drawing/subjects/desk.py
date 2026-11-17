"""A desk with a kettle.

Day: a desk under a window full of sky (the sage is the daylight in its
panes): a mug, an open notebook, a kettle. Each finished task pins a coral note
to the wall beside the window; Start sends steam up from the mug; everything
done closes the notebook with the pencil on it, and the kettle has boiled; a
day with nothing planned leaves the pages blank; overdue work is a few sheets at
the desk's end, one per level. The sun crosses the panes with the hour.

Night: the same desk with the lamp on. The lamp is the light: it glows out of
its shade onto the notebook and pools on the desk; the window is dark, with the
moon in a pane. The notes catch the light; Start steams the kettle; everything
done closes the notebook and lets the moonlight into the panes.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

TOP = 146.0          # the desk's surface
FLOOR = 192.0
WIN = (12.0, 12.0, 76.0, 76.0)
MUG_X = 44.0
BOOK = (65.0, 96.0)  # the open notebook's two outer edges


class DeskWithKettle:
    id = 'desk'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('kettle', 'desk'), ('mug', 'desk'), ('notebook', 'desk'), ('pencil', 'notebook'),
        ('papers', 'desk'), ('desk', 'leg'), ('leg', 'floor'), ('window', 'ledge'),
        ('sun', 'window'), ('lamp', 'desk'), ('note',), ('steam', 'kettle'), ('moon', 'cloud'),
        ('drawer', 'desk'),
    ))

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
    for i in range(k.REWARDS):
        row, col = i // 4, i % 4
        x = 96 + col * 16 + (6 if row % 2 else 0) + r.uniform(-1.6, 1.6)
        y = 24 + row * 21 + r.uniform(-2.4, 2.4)
        notes.append((x, y, math.radians(r.uniform(-11, 11))))
    return {
        'kettle_x': r.uniform(125, 128),
        'notes': notes,
        'lines': [r.uniform(0.55, 0.95) for _ in range(4)],
        'papers': [math.radians(r.uniform(-5, 5)) for _ in range(3)],
        'moon_pane': r.choice([(28.0, 24.0), (60.0, 24.0)]),
    }


def _common(b: SketchBuilder, s: dict) -> None:
    b.line(line((4, TOP), (156, TOP + 0.5)), part='desk')
    b.line(line((7, TOP + 7), (153, TOP + 7.8)), part='desk')
    b.line(line((15, TOP + 7.2), (15.6, FLOOR)), part='leg')
    b.line(line((145, TOP + 7.7), (144.4, FLOOR)), part='leg')
    b.line(line((2, FLOOR + 0.4), (158, FLOOR + 1.2)), part='floor')
    x0, y0, x1, y1 = WIN
    b.line(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)), part='window')
    b.line(line(((x0 + x1) / 2, y0), ((x0 + x1) / 2 + 0.4, y1)), part='window')
    b.line(line((x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2 + 0.4)), part='window')
    b.line(line((x0 - 5, y1 + 3.4), (x1 + 5, y1 + 3.8)), part='ledge')
    # A drawer under the top, so the desk has a body, not a frame.
    b.line(line((40, TOP + 7.6), (40.4, TOP + 21), (120.4, TOP + 21.4), (120, TOP + 7.9)), part='drawer')
    b.line(k.ring(80.2, TOP + 14.6, 1.8, 7), part='drawer')
    _kettle(b, s['kettle_x'])
    _mug(b)
    _notebook(b, s)
    _papers(b, s)


def kettle_body(x: float):
    return loop((x - 20, TOP), (x - 21.5, TOP - 17), (x - 12, TOP - 32), (x + 12, TOP - 32),
                (x + 21.5, TOP - 17), (x + 20, TOP), corners=(0, 5))


def _kettle(b: SketchBuilder, x: float) -> None:
    b.line(kettle_body(x), part='kettle')
    b.line(curve((x - 12, TOP - 32), (x - 7, TOP - 48), (x + 7, TOP - 48), (x + 12, TOP - 32)), part='kettle')
    b.line(loop((x - 3.4, TOP - 32), (x, TOP - 36.8), (x + 3.4, TOP - 32), corners=(0, 2)), part='kettle')
    # The spout: a tube that leaves the body and tapers to its lip.
    b.line(curve((x - 20.6, TOP - 11), (x - 27.5, TOP - 17), (x - 34.5, TOP - 29)), part='kettle')
    b.line(curve((x - 21.3, TOP - 20), (x - 26.5, TOP - 24), (x - 31.4, TOP - 31.4)), part='kettle')
    b.line(line((x - 31.4, TOP - 31.4), (x - 34.5, TOP - 29)), part='kettle')


def spout_tip(s: dict):
    return (s['kettle_x'] - 33, TOP - 33)


def _mug(b: SketchBuilder) -> None:
    x = MUG_X
    b.line(line((x - 10, TOP - 26), (x - 9, TOP), (x + 9, TOP), (x + 10, TOP - 26)), part='mug')
    b.line(curve((x - 10, TOP - 26), (x, TOP - 25.2), (x + 10, TOP - 26)), part='mug')
    b.line(curve((x + 10, TOP - 21), (x + 17.4, TOP - 18), (x + 16.4, TOP - 8), (x + 9.4, TOP - 6)), part='mug')


def _notebook(b: SketchBuilder, s: dict) -> None:
    x0, x1 = BOOK
    mid = (x0 + x1) / 2
    open_ = (('notAllDone',),)
    b.line(curve((x0 + 2, TOP - 11), (x0 + 9, TOP - 14), (mid, TOP - 11)), when=open_, part='notebook')
    b.line(curve((mid, TOP - 11), (x1 - 9, TOP - 14), (x1 - 2, TOP - 11)), when=open_, part='notebook')
    b.line(line((x0 + 2, TOP - 11), (x0, TOP)), when=open_, part='notebook')
    b.line(line((x1 - 2, TOP - 11), (x1, TOP)), when=open_, part='notebook')
    b.line(line((mid, TOP - 11), (mid, TOP)), when=open_, part='notebook')
    writing = (('notAllDone',), ('planned',))       # a day with nothing planned: blank pages
    ln = s['lines']
    k.hatch(b, x0 + 4, TOP - 7.4, (11 * ln[0], 10 * ln[1]), 4.6, when=writing, part='notebook')
    k.hatch(b, mid + 3, TOP - 7.4, (11 * ln[2], 9 * ln[3]), 4.6, when=writing, part='notebook')
    done = (('allDone',),)
    b.line(line((x0, TOP), (x0 + 2, TOP - 6), (x1 - 2, TOP - 6), (x1, TOP)), when=done, part='notebook')
    b.line(line((x0 + 5, TOP - 6.6), (x1 - 9, TOP - 10.8)), when=done, part='pencil')
    b.line(line((x1 - 9, TOP - 10.8), (x1 - 6.2, TOP - 11.6)), when=done, part='pencil')


def _papers(b: SketchBuilder, s: dict) -> None:
    """Overdue work: a sheet per level at the desk's end, each a single stroke
    so the stack stays light on paper."""
    for level, a in enumerate(s['papers'], start=1):
        cx, cy, w = 11.0, TOP - 1.4 - (level - 1) * 4.6, 12.0
        c, sn = math.cos(a), math.sin(a)
        b.line(line((cx - w / 2 * c, cy - w / 2 * sn), (cx + w / 2 * c, cy + w / 2 * sn)),
               when=(('overdue', level),), part='papers')


def _notes(b: SketchBuilder, s: dict) -> None:
    for i, (x, y, a) in enumerate(s['notes']):
        when = (('reward', i),)
        pts = k.rotate(((x - 6.5, y - 6.5), (x + 6.5, y - 6.5), (x + 6.5, y + 6.5), (x - 6.5, y + 6.5)), (x, y), a)
        b.filled(poly(*pts), when=when, part=f'note:{i}')
        px, py = k.rotate([(x, y - 3.6)], (x, y), a)[0]
        b.line(k.ring(px, py, 1.3, 6), when=when, part=f'note:{i}')       # the pin
        b.anchor(i, px, py)


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    b.wash(k.wash_of(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)), inset=0.95, dx=3, dy=3), part='window')
    b.wash(k.wash_of(kettle_body(s['kettle_x']), inset=0.9), part='kettle')
    sun = dict(ray_gap=1.8, ray_len=2.8)
    k.sun(b, r.fork('sun-m'), 28, 28, 3.8, when=(k.MORNING,), **sun)
    k.sun(b, r.fork('sun-n'), 60, 27, 3.8, when=(k.MIDDAY,), **sun)
    k.sun(b, r.fork('sun-a'), 60, 59, 3.8, when=(k.AFTERNOON,), **sun)
    k.low_sun(b, r.fork('sun-d'), 28, y1 - 1.4, 5.4, when=(k.DUSK,))
    mx, my = s['moon_pane']
    k.moon(b, mx, my, 5.0, glow=False, veiled=False, when=(k.LATE,))
    _notes(b, s)
    tx, ty = spout_tip(s)
    k.steam(b, tx, ty, 0, 6, height=16, when=(('allDone',),))                  # the kettle has boiled
    b.ambient(1.0, (('focus',),), lambda f, child: k.steam(child, MUG_X, TOP - 30, f, 6, height=20))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    mx, my = s['moon_pane']
    k.moon(b, mx, my, 5.0, glow=False)
    # Everything done: the moonlight comes into the panes.
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    for px0, py0, px1, py1 in ((x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)):
        b.glow(ellipse((px0 + px1) / 2, (py0 + py1) / 2, (px1 - px0) * 0.42, (py1 - py0) * 0.42, n=10),
               when=(('allDone',),), part='window')
    # The lamp: base behind the mug, its shade aimed down at the notebook.
    ax, ay = 0.45, 0.89
    px, py = ay, -ax
    tip = (44.0, TOP - 58)
    n = (tip[0] + 2 * ax, tip[1] + 2 * ay)
    m = (n[0] + 13 * ax, n[1] + 13 * ay)
    b.glow(ellipse(m[0] + 9 * ax, m[1] + 9 * ay, 15, 10, n=12, rot=math.atan2(ay, ax)), part='lamp')
    b.glow(ellipse(80, TOP - 2.5, 32, 3.6, n=12), part='lamp')
    b.line(curve((20, TOP), (26, TOP - 4.2), (32, TOP), corners=(0, 2)), part='lamp')
    b.line(line((26, TOP - 4), (20, TOP - 38)), part='lamp')
    b.line(line((20, TOP - 38), tip), part='lamp')
    b.line(poly((n[0] + 3 * px, n[1] + 3 * py), (m[0] + 9 * px, m[1] + 9 * py),
                (m[0] - 9 * px, m[1] - 9 * py), (n[0] - 3 * px, n[1] - 3 * py)), part='lamp')
    for t in (-3.5, 1.5, 6.5):                     # it is on (rays toward the notebook, off the mug)
        cx, cy = m[0] + t * px, m[1] + t * py
        b.line(line((cx + 3.8 * ax, cy + 3.8 * ay), (cx + 6.4 * ax, cy + 6.4 * ay)), part='lamp-ray')
    _notes(b, s)
    tx, ty = spout_tip(s)
    b.ambient(1.0, (('focus',),), lambda f, child: k.steam(child, tx, ty, f, 6, height=18))
