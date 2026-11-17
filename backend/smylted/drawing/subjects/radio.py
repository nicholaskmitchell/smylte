"""Settings: an old table radio on a shelf.

Day: a table radio standing on a shelf, its speaker grille on the left, a
tuning window on the right with the coral needle across it, two knobs below
the window and a telescopic antenna up from its top right corner.

Night: the same radio and shelf with the tuning window lit, its light the
night's; music comes off the speaker in three sound arcs, two notes float
above the handle, and a crescent moon hangs at the top left.

A view drawing: still, one picture per theme, the same whatever the day.
"""
from __future__ import annotations

import math

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

# The body: its base sits flat on the shelf. Narrower than the frame so the
# night's sound arcs have room off its left side.
LEFT, RIGHT, TOP, BASE = 28.0, 148.0, 82.0, 160.0
SHELF, SHELF_EDGE = BASE, BASE + 6.0
SPEAKER = (59.0, 121.0, 23.0)
GRILLE = (-14.0, -7.0, 0.0, 7.0, 14.0)      # each line's offset from the speaker's centre
GRILLE_INSET = 7.0                          # a pen and 4.75 of paper short of the ring
WIN = (94.0, 96.0, 140.0, 116.0)
# Tick marks along the window's bottom edge, closing up toward the right as an
# AM dial's do: the widest gap holds the needle.
TICKS = (98.5, 120.0, 126.0, 131.5, 136.0)
TICK = 4.0
NEEDLE_X = 109.25
NEEDLE_BASE, NEEDLE_TIP = 6.5, 2.5      # wide enough that the coral shows inside its ink
KNOBS = ((107.0, 137.0, -2.1), (129.0, 137.0, -1.0))   # (x, y, pointer angle)
KNOB_R = 7.0
ANTENNA_ROOT = (140.0, 81.0)
ANTENNA_TILT = math.radians(30)             # from vertical, leaning left


class Radio:
    id = 'radio'
    JOINS = frozenset(frozenset(p) for p in (
        ('radio', 'shelf'), ('bracket', 'shelf'), ('handle', 'radio'), ('antenna', 'radio'),
        ('tick', 'window'), ('needle', 'window'), ('pointer', 'knob'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, still=True)
        if theme == 'light':
            _day(b)
        else:
            _night(b)
        return b.build(state)


def _body():
    """Rounded at the top, sharp at the base so it sits flat."""
    return loop((LEFT, BASE), (LEFT, TOP + 11), (LEFT + 3, TOP + 3), (LEFT + 11, TOP),
                (RIGHT - 11, TOP), (RIGHT - 3, TOP + 3), (RIGHT, TOP + 11), (RIGHT, BASE),
                corners=(0, 7))


def _shelf(b: SketchBuilder) -> None:
    # Level, never bowed up into the radio standing on it.
    b.line(curve((6, SHELF), (80, SHELF + 0.3), (154, SHELF)), part='shelf')
    b.line(curve((8, SHELF_EDGE), (80, SHELF_EDGE + 0.3), (152, SHELF_EDGE)), part='shelf')
    for wall, inward in ((36.0, 1), (124.0, -1)):
        b.line(line((wall, SHELF_EDGE), (wall, SHELF_EDGE + 13), (wall + inward * 11, SHELF_EDGE)),
               part='bracket')


def _antenna(b: SketchBuilder) -> None:
    """Three segments, each thinner than the last, and a ball at the tip."""
    rx, ry = ANTENNA_ROOT
    dx, dy = -math.sin(ANTENNA_TILT), -math.cos(ANTENNA_TILT)
    nx, ny = -dy, dx

    def at(u: float, v: float):
        return (rx + dx * u + nx * v, ry + dy * u + ny * v)

    b.line(poly(at(0, -3), at(0, 3), at(26, 3), at(26, -3)), part='antenna')
    b.line(line(at(26, -2.3), at(50, -2.3), at(50, 2.3), at(26, 2.3)), part='antenna')
    b.line(line(at(50, 0), at(71, 0)), part='antenna')
    tx, ty = at(73.6, 0)
    b.line(k.ring(tx, ty, 2.6, 7), part='antenna')


def _radio(b: SketchBuilder) -> None:
    _shelf(b)
    b.line(_body(), part='radio')
    mid = (LEFT + RIGHT) / 2
    b.line(curve((mid - 21, TOP), (mid - 19, TOP - 12), (mid, TOP - 18), (mid + 19, TOP - 12),
                 (mid + 21, TOP)), part='handle')
    sx, sy, sr = SPEAKER
    b.line(k.ring(sx, sy, sr, 12), part='speaker')
    for off in GRILLE:
        h = math.sqrt(sr * sr - off * off) - GRILLE_INSET
        b.line(line((sx - h, sy + off), (sx + h, sy + off + 0.3)), part='grille')
    x0, y0, x1, y1 = WIN
    b.line(loop((x0, y0), (x1, y0), (x1, y1), (x0, y1), corners=(0, 1, 2, 3)), part='window')
    for x in TICKS:
        b.line(line((x, y1), (x + 0.2, y1 - TICK)), part='tick')
    # The one coral accent: the tuning needle, a thin upright wedge across the window.
    nb, nt = NEEDLE_BASE / 2, NEEDLE_TIP / 2
    b.filled(poly((NEEDLE_X - nb, y1 + 3.5), (NEEDLE_X + nb, y1 + 3.5),
                  (NEEDLE_X + nt, y0 - 3.5), (NEEDLE_X - nt, y0 - 3.5)), part='needle')
    for i, (kx, ky, a) in enumerate(KNOBS):
        b.line(k.ring(kx, ky, KNOB_R, 9), part=f'knob:{i}')
        b.line(line((kx + 1.5 * math.cos(a), ky + 1.5 * math.sin(a)),
                    (kx + KNOB_R * math.cos(a), ky + KNOB_R * math.sin(a))), part=f'pointer:{i}')
    _antenna(b)


def _day(b: SketchBuilder) -> None:
    b.wash(k.wash_of(_body()), part='radio')
    _radio(b)


def _note(b: SketchBuilder, x: float, y: float, part: str) -> None:
    """A quaver: an oval head at (x, y), a stem up from its right and a flag."""
    b.line(ellipse(x, y, 3.8, 2.8, n=8, rot=-0.35), part=part)
    sx = x + 3.4
    b.line(curve((sx, y - 1.2), (sx, y - 17), (sx + 4.2, y - 13), (sx + 5, y - 8), corners=(1,)),
           part=part)


def _night(b: SketchBuilder) -> None:
    # The tuning window is lit: its light is the night's.
    x0, y0, x1, y1 = WIN
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    b.glow(ellipse(cx, cy, 36, 27, n=14), part='window')
    b.glow(ellipse(cx, cy, 24, 14, n=12), part='window')
    k.moon(b, 22, 26, 8.0, glow=False, clouds=0)
    _note(b, 48, 62, 'note:0')
    _note(b, 67, 50, 'note:1')
    # Music off the speaker's left side, outside the body.
    for i, (end, middle, half) in enumerate(((21.0, 17.5, 8.0), (15.5, 11.0, 12.0), (10.0, 5.5, 16.0))):
        sy = SPEAKER[1]
        b.line(curve((end, sy - half), (middle, sy), (end, sy + half)), part=f'sound:{i}')
    _radio(b)
