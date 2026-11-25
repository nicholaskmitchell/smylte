"""A desk with a kettle.

Day: a desk under a window full of sky (the sage is the daylight in its
panes): a mug, an open notebook, a kettle. Each finished task pins a coral note
to the wall beside the window, in rows of three; Start sends steam up from the
mug; everything done closes the notebook with the pencil on it, and the kettle
has boiled; a day with nothing planned leaves the book tented on the desk;
overdue work is a sheet or two still pinned up by the window, ink only. The sun
crosses the panes with the hour.

Night: the same desk with the lamp on. The lamp is the light: it glows out of
its shade onto the notebook and pools on the desk; the window is dark, with the
moon in a pane. The notes catch the light; Start steams the kettle; everything
done closes the notebook and brings the stars out in the panes.

Paper (the desk unit, drawn for ink): the same desk at midday. The window's
glass is a light tone, all but the pane the sun is in; the kettle and the mug
take a light tone on their side away from the window; the desk's front edge is
a solid band over a drawer in a light tone, with its shadow on the floor. The notes are
hatched, each with its pin; everything done closes the notebook with a solid
pencil on it, and the kettle has boiled.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import Composition, DayState
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
    PAPER = True
    JOINS = frozenset(frozenset(p) for p in (
        ('kettle', 'desk'), ('mug', 'desk'), ('notebook', 'desk'), ('pencil', 'notebook'),
        ('desk', 'leg'), ('leg', 'floor'), ('window', 'ledge'),
        ('sun', 'window'), ('lamp', 'desk'), ('steam', 'kettle'),
        ('drawer', 'desk'), ('notebook', 'writing'),
    ))

    def render(self, state: DayState, theme: Composition, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        _common(b, s)
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        elif theme == 'paper':
            _paper(b, s, rng.fork('paper'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    # Pinned in rows of three, a little off the grid, each clear of the next:
    # a full row reads as done.
    notes = []
    for i in range(k.REWARDS):
        row, col = i // 3, i % 3
        x = 100 + col * 21 + (5 if row % 2 else 0) + r.uniform(-1.0, 1.0)
        y = 19 + row * 20 + r.uniform(-1.0, 1.0)
        notes.append((x, y, math.radians(r.uniform(-5, 5))))
    return {
        'kettle_x': r.uniform(125, 128),
        'notes': notes,
        'lines': [r.uniform(0.55, 0.95) for _ in range(4)],
        'papers': [math.radians(d + r.uniform(-2, 2)) for d in (-6, 5, -3)],
        'moon_pane': r.choice([(28.0, 24.0), (60.0, 24.0)]),
    }


def _common(b: SketchBuilder, s: dict) -> None:
    # The top sags a little and never rises, so nothing standing on it touches
    # a line that bows up into it.
    b.line(curve((4, TOP), (42, TOP + 0.6), (80, TOP + 0.9), (118, TOP + 0.8), (156, TOP + 0.5)), part='desk')
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
    open_ = (('notAllDone',), ('planned',))
    b.line(curve((x0 + 2, TOP - 13), (x0 + 9, TOP - 16), (mid, TOP - 13)), when=open_, part='notebook')
    b.line(curve((mid, TOP - 13), (x1 - 9, TOP - 16), (x1 - 2, TOP - 13)), when=open_, part='notebook')
    b.line(line((x0 + 2, TOP - 13), (x0, TOP)), when=open_, part='notebook')
    b.line(line((x1 - 2, TOP - 13), (x1, TOP)), when=open_, part='notebook')
    b.line(line((mid, TOP - 13), (mid, TOP)), when=open_, part='notebook')
    # The writing is its own part: the pages may hold it, but it must keep clear
    # of the desk top, or the two print as one bar.
    ln = s['lines']
    k.hatch(b, x0 + 5.2, TOP - 9.4, (6.4 * ln[0], 6 * ln[1]), 4.6, when=open_, part='writing')
    k.hatch(b, mid + 4.2, TOP - 9.4, (6 * ln[2], 5.6 * ln[3]), 4.6, when=open_, part='writing')
    # Nothing planned: the book left tented on the desk, spine up.
    idle = (('nothingPlanned',),)
    b.line(line((x0 + 1, TOP), (mid, TOP - 15), (x1 - 1, TOP)), when=idle, part='notebook')
    b.line(line((mid - 2.2, TOP - 15.6), (mid + 2.2, TOP - 15.6)), when=idle, part='notebook')
    # Everything done: the book closed, its band round it, the pencil on top.
    done = (('allDone',),)
    b.line(line((x0, TOP), (x0 + 2, TOP - 6), (x1 - 2, TOP - 6), (x1, TOP)), when=done, part='notebook')
    b.line(line((x1 - 7, TOP - 6), (x1 - 7.3, TOP)), when=done, part='notebook')
    b.line(poly((x0 + 4, TOP - 6.4), (x0 + 4, TOP - 9.0), (x1 - 9, TOP - 9.0), (x1 - 4, TOP - 7.4),
                (x1 - 9, TOP - 6.0)), when=done, part='pencil')


def _papers(b: SketchBuilder, s: dict) -> None:
    """Overdue work: a sheet per level still pinned to the wall beside the
    window, ink only (the coral notes are what is done), each with a turned
    corner and a line of writing so it reads as paper."""
    x = 8.5
    for level, (y, a) in enumerate(zip((92.0, 109.0, 126.0), s['papers']), start=1):
        when = (('overdue', level),)
        sheet = ((x - 4.5, y - 6), (x + 2.1, y - 6), (x + 4.5, y - 3.6), (x + 4.5, y + 6), (x - 4.5, y + 6))
        pts = k.rotate(sheet, (x, y), a)
        b.line(poly(*pts), when=when, part=f'papers:{level}')
        fold = k.rotate(((x + 2.1, y - 6), (x + 2.1, y - 3.6), (x + 4.5, y - 3.6)), (x, y), a)
        b.line(line(*fold), when=when, part=f'papers:{level}')
        w0, w1 = k.rotate(((x - 2.6, y + 1.6), (x + 2.6, y + 1.8)), (x, y), a)
        b.line(line(w0, w1), when=when, part=f'papers:{level}')


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
    sun = dict(ray_gap=3.4, ray_len=2.6, rays=5)
    k.sun(b, r.fork('sun-m'), 28, 28, 3.8, when=(k.MORNING,), **sun)
    k.sun(b, r.fork('sun-n'), 60, 27, 3.8, when=(k.MIDDAY,), **sun)
    k.sun(b, r.fork('sun-a'), 60, 59, 3.8, when=(k.AFTERNOON,), **sun)
    k.low_sun(b, r.fork('sun-d'), 28, y1 - 1.4, 5.4, when=(k.DUSK,))
    mx, my = s['moon_pane']
    k.moon(b, mx, my, 5.0, glow=False, clouds=0, when=(k.LATE,))
    _notes(b, s)
    tx, ty = spout_tip(s)
    k.steam(b, tx, ty, 0, 6, height=16, when=(('allDone',),))                  # the kettle has boiled
    b.ambient(1.0, (('focus',),), lambda f, child: k.steam(child, MUG_X, TOP - 30, f, 6, height=20))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    mx, my = s['moon_pane']
    # The moon in its pane, with no clouds: a pane has no room for a cloud
    # that reads, and the sheets pinned by the window already show overdue work.
    k.moon(b, mx, my, 5.0, glow=False, clouds=0)
    # Everything done: stars come out in the panes.
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    k.stars(b, r.fork('pane-stars'), 3, (x0 + 10, y0 + 10, x1 - 10, y1 - 10),
            ok=lambda p: abs(p[0] - xm) > 10 and abs(p[1] - ym) > 10,
            avoid=((mx, my, 12),),
            gap=14, when=(('allDone',),), part='star')
    # The lamp: base behind the mug, its shade aimed down at the notebook, its
    # light falling there in a cone and pooling on the desk.
    ax, ay = 0.5, 0.866
    px, py = ay, -ax
    tip = (38.0, TOP - 58)
    n = (tip[0] + 2 * ax, tip[1] + 2 * ay)
    m = (n[0] + 13 * ax, n[1] + 13 * ay)
    b.glow(ellipse(m[0] + 16 * ax, m[1] + 16 * ay, 20, 11, n=12, rot=math.atan2(ay, ax)), part='lamp')
    b.glow(ellipse(78, TOP - 5, 26, 8, n=12), part='lamp')
    b.line(curve((14, TOP), (20, TOP - 4.2), (26, TOP), corners=(0, 2)), part='lamp')
    b.line(line((20, TOP - 4), (18, TOP - 38)), part='lamp')
    b.line(line((18, TOP - 38), tip), part='lamp')
    b.line(poly((n[0] + 3 * px, n[1] + 3 * py), (m[0] + 9 * px, m[1] + 9 * py),
                (m[0] - 9 * px, m[1] - 9 * py), (n[0] - 3 * px, n[1] - 3 * py)), part='lamp')
    for t in (-3.5, 1.5, 6.5):                     # it is on (rays toward the notebook, off the mug)
        cx, cy = m[0] + t * px, m[1] + t * py
        b.line(line((cx + 5.4 * ax, cy + 5.4 * ay), (cx + 8.2 * ax, cy + 8.2 * ay)), part='lamp-ray')
    _notes(b, s)
    tx, ty = spout_tip(s)
    b.ambient(1.0, (('focus',),), lambda f, child: k.steam(child, tx, ty, f, 6, height=18))


# ── paper: the desk unit's composition, drawn for ink ───────────────────────

SHADE_INSET = 3.6         # a tone keeps this far inside the lines round it
SUN_PANE = 1              # the pane the midday sun is in, left to right, top to bottom


def _panes() -> list:
    x0, y0, x1, y1 = WIN
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    i = SHADE_INSET
    return [(x0 + i, y0 + i, xm - i, ym - i), (xm + i, y0 + i, x1 - i, ym - i),
            (x0 + i, ym + i, xm - i, y1 - i), (xm + i, ym + i, x1 - i, y1 - i)]


def _paper(b: SketchBuilder, s: dict, r: Rng) -> None:
    """The day at midday, drawn for ink: tone where the room has mass, no
    wash, no boil, no ambient (the desk unit pins the hour to noon)."""
    # The glass, but for the pane the sun is in: that one is all glare, paper.
    for i, (px0, py0, px1, py1) in enumerate(_panes()):
        if i != SUN_PANE:
            b.shade(poly((px0, py0), (px1, py0), (px1, py1), (px0, py1)), 'light', part='window')
    sun = dict(ray_gap=3.4, ray_len=2.6, rays=5)
    k.sun(b, r.fork('sun-n'), 60, 27, 3.8, when=(k.MIDDAY,), **sun)
    # The kettle and the mug, lit from the window on the left.
    x = s['kettle_x']
    i = SHADE_INSET
    b.shade(loop((x - 2, TOP - 32 + i), (x + 12 - i, TOP - 32 + i), (x + 21.5 - i, TOP - 17),
                 (x + 20 - i, TOP - i), (x - 2, TOP - i), corners=(0, 3, 4)), 'light', part='kettle')
    b.shade(poly((MUG_X + 1, TOP - 25.2 + i), (MUG_X + 10 - i, TOP - 26 + i),
                 (MUG_X + 9 - i, TOP - i), (MUG_X + 1, TOP - i)), 'light', part='mug')
    # The drawer's front, a light tone.
    b.shade(poly((40.4 + i, TOP + 7.6 + i), (120 - i, TOP + 7.9 + i), (120.4 - i, TOP + 21.4 - i),
                 (40.4 + i, TOP + 21 - i)), 'light', part='drawer')
    # The desk's front edge, solid, and its shadow on the floor between the legs.
    b.solid(poly((6, TOP + 2.2), (154, TOP + 2.8), (153, TOP + 6.0), (7, TOP + 5.4)), part='desk')
    b.shade(poly((15.6 + i, FLOOR - 7.5), (144.4 - i, FLOOR - 7.0), (144.4 - i, FLOOR - 2.6),
                 (15.6 + i, FLOOR - 3.0)), 'light', part='floor')
    _notes(b, s)
    # Everything done: the book closed, a solid pencil on it, and the kettle
    # has boiled.
    x0, x1 = BOOK
    b.solid(poly((x0 + 4, TOP - 6.4), (x0 + 4, TOP - 9.0), (x1 - 9, TOP - 9.0), (x1 - 4, TOP - 7.4),
                 (x1 - 9, TOP - 6.0)), when=(('allDone',),), part='pencil')
    tx, ty = spout_tip(s)
    k.steam(b, tx, ty, 0, 6, height=16, when=(('allDone',),))
