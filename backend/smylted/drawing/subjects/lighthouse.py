"""A lighthouse.

Day: a lighthouse stands on a grassy point that runs down into the sea from
the left, the sea line far behind it, two gulls in the sky beside it. Each
finished task brings a coral-sailed boat onto the sea, the first few spread
from the sea line; Start makes the flag on the lantern flutter; everything
done flies a long pennant from the flag pole; a day with nothing planned
leaves the sea empty and calm; overdue work brings a cloud over the sea, a
second, and a third, smaller, by the tower. The sun crosses the sky with the
hour, sets on the sea line, and late at night is an ink moon.

Night: the lamp is lit, and its beam reaches out over the sea. Each finished
task is a boat's light on the water; everything done sends a second, wider
beam the other way; Start turns the light, three rays round the lantern;
overdue work brings a cloud beside the moon, a second a step beyond it.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

SEA = 96.0                # the sea line, across the frame
# The point: a headland standing in the sea, closed inside the picture. Up a
# low cliff from its foot at the left, over its top under the tower, down to
# its toe in the sea, and back along the waterline at its foot.
POINT = ((9.5, 161.0), (10.0, 149.0), (11.6, 137.0), (20.0, 130.0), (34.0, 123.4), (50.0, 120.0),
         (66.0, 123.4), (78.0, 131.0), (87.0, 141.0), (92.0, 150.0),
         (84.0, 155.2), (74.0, 158.8), (63.0, 159.6), (52.0, 162.4), (40.0, 162.0), (28.0, 164.0),
         (18.0, 162.8))
FOOT_L, BROW, TOE = 0, 2, 9  # the cliff's foot and brow, and the toe in the sea
# The sea lapping at the point's foot: short ripples just below its waterline.
LAP = ((24.0, 171.0, 7.0), (50.0, 169.6, 8.0), (74.0, 165.4, 6.0))
# The tower tapers from its base to the gallery.
BASE_Y, BASE = 122.0, (38.0, 62.0)
GALLERY_Y, TOP = 52.0, (42.0, 58.0)
DECK = (37.0, 63.0)
RAIL_Y = GALLERY_Y - 4.5
LANTERN = (44.0, 36.0, 56.0, 52.0)
DOME_TOP = 32.4
POLE_TOP = 19.0
FLAG_HOIST = (22.0, 27.5)  # where the flag is bent on to the pole
BANDS = (72.0, 108.0)
LAMP = (50.0, 42.0)       # the lamp, and the centre the night's rays turn round

# The boats: a hull HALF wide and a sail beside its mast. Two on the sea line
# left of the tower and four right of it, short of the setting sun's place;
# two rows of three nearer, right of the point.
HALF = 6.3
MAST, CLEW = 5.2, 6.2     # the sail's two lower corners either side of the centre
FOOT = 3.8                # how far above the waterline the sail's foot runs
HORIZON_X = (9.5, 26.85, 71.8, 89.15, 106.5, 123.85)
NEAR = ((103.0, 123.0), (123.0, 123.0), (143.0, 123.0),
        (112.0, 150.0), (132.0, 150.0), (151.5, 150.0))
NEAR_SCALE = 1.1
LIGHT_R = 6.0
DUSK_X = 147.0
PLANNED = (('planned',),)

# Weather by day: two clouds over the sea, a third, smaller, by the tower;
# (centre x, centre y, width), clear of every sun, the gulls and the sails.
CLOUDS = ((92.0, 60.0, 28.0), (132.0, 68.0, 26.0), (24.0, 63.0, 20.0))
GULLS = ((82.0, 40.0), (97.0, 31.0))
# Small waves on the sea, wherever the boats leave room: none on a calm day.
WAVES = ((14.0, 108.0), (80.0, 108.0), (102.0, 168.0), (128.0, 176.0), (150.0, 166.0),
         (112.0, 190.0), (142.0, 192.0))
# The night's turning rays: from RAY_IN to RAY_OUT round the lamp, never
# straight up (the pole) or down (the tower).
RAY_IN, RAY_OUT = 17.0, 23.5
RAY_SWEEP = 70.0          # degrees each side may sweep, up from the level


class Lighthouse:
    id = 'lighthouse'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('tower', 'point'), ('tower', 'gallery'), ('gallery', 'lantern'), ('lantern', 'pole'),
        ('flag', 'pole'), ('pennant', 'pole'), ('flag', 'pennant'), ('sea', 'tower'),
        ('boat', 'sea'), ('sun', 'sea'), ('lamp', 'lantern'),
        # The lantern stands on the deck, two units in from the tower's top.
        ('lantern', 'tower'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _tower_x(y: float) -> tuple[float, float]:
    """The tower's two sides at height y."""
    t = (BASE_Y - y) / (BASE_Y - GALLERY_Y)
    return (BASE[0] + (TOP[0] - BASE[0]) * t, BASE[1] + (TOP[1] - BASE[1]) * t)


def _land_y(x: float, land: list) -> float:
    """The point's outline at x (the pen's spline, not its vertices)."""
    return min(land, key=lambda p: abs(p[0] - x))[1]


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same sea after dark."""
    boats = [(x, SEA, 1.0) for x in HORIZON_X] + [(x, y, NEAR_SCALE) for x, y in NEAR]
    facing = {(x, y): r.choice([-1, 1]) for x, y, _ in boats}
    tall = {(x, y): r.uniform(15.0, 16.0) for x, y, _ in boats}
    order = k.spread([(x, y) for x, y, _ in boats], (100.0, SEA))
    scale = {(x, y): sc for x, y, sc in boats}
    land = k.samples(loop(*POINT, corners=(FOOT_L, BROW, TOE)), step=1.0)
    return {
        'boats': [(x, y, scale[(x, y)], facing[(x, y)], tall[(x, y)]) for x, y in order],
        'land': [p for p in land if p[1] <= 150.5],
        'moon_spot': (134 + r.uniform(-2, 2), 18 + r.uniform(-1.5, 1.5)),
    }


# ── the headland and the lighthouse ─────────────────────────────────────────

def _point(b: SketchBuilder, s: dict) -> None:
    outline = loop(*POINT, corners=(FOOT_L, BROW, TOE))
    b.wash(k.wash_of(outline, inset=0.95, dx=3.0, dy=3.0), part='point')
    b.line(outline, part='point')
    for x, y, h in LAP:
        b.line(curve((x - h, y + 0.4), (x - h / 3, y - 0.5), (x + h / 3, y + 0.5), (x + h, y - 0.3)),
               part='point')


def _tower(b: SketchBuilder, s: dict) -> None:
    land = s['land']
    for side in (0, 1):
        x0 = BASE[side]
        b.line(line((TOP[side], GALLERY_Y), (x0, _land_y(x0, land) + 0.6)), part='tower')
    for y in BANDS:
        x0, x1 = _tower_x(y)
        b.line(line((x0, y), (x1, y + 0.3)), part='tower')
    # A small arched door at its foot.
    foot = _land_y(50.0, land) + 0.5
    b.line(curve((47.3, foot), (47.3, 115.6), (50.0, 113.0), (52.7, 115.6), (52.7, foot), corners=(0, 4)),
           part='tower')
    # The gallery: its deck over the tower's top, a short rail each side of
    # the lantern.
    b.line(line((DECK[0], GALLERY_Y), (DECK[1], GALLERY_Y + 0.2)), part='gallery')
    x0, y0, x1, y1 = LANTERN
    b.line(line((DECK[0] + 1.2, GALLERY_Y), (DECK[0] + 1.2, RAIL_Y), (x0, RAIL_Y)), part='gallery')
    b.line(line((x1, RAIL_Y), (DECK[1] - 1.2, RAIL_Y), (DECK[1] - 1.2, GALLERY_Y)), part='gallery')
    b.line(poly((x0, y1), (x0, y0), (x1, y0), (x1, y1)), part='lantern')
    b.line(curve((x0 - 0.6, y0), (46.2, 33.4), (50.0, DOME_TOP), (53.8, 33.4), (x1 + 0.6, y0)),
           part='lantern')
    b.line(line((50.0, DOME_TOP + 0.4), (50.2, POLE_TOP)), part='pole')


def _sea_line(b: SketchBuilder) -> None:
    """The sea line, broken by the tower: a little chop on it on a day with
    work planned, flat calm on a day with none."""
    left, right = _tower_x(SEA)
    for x0, x1 in ((0.5, left), (right, 159.5)):
        n = max(2, round((x1 - x0) / 8))
        chop = [(x0 + (x1 - x0) * i / n, SEA + (0.7 if i % 2 else -0.2) * (0 < i < n)) for i in range(n + 1)]
        b.line(curve(*chop), when=PLANNED, part='sea')
        b.line(line((x0, SEA), (x1, SEA + 0.2)), when=(('nothingPlanned',),), part='sea')


def _waves(b: SketchBuilder) -> None:
    for x, y in WAVES:
        b.line(curve((x - 4.5, y), (x - 2.2, y - 1.3), (x, y), (x + 2.2, y + 1.1), (x + 4.5, y)),
               when=PLANNED, part='wave')


def _flag(child: SketchBuilder, shape: int, *, when: tuple = ()) -> None:
    """The flag on its pole, one of three shapes as it flutters."""
    top, foot = FLAG_HOIST
    fly, dip, lift, low = ((61.5, -0.9, 0.5, 0.3), (60.6, 0.8, -0.7, -0.4), (61.0, 0.0, 1.0, 0.9))[shape]
    hx = 50.7
    child.line(loop((hx, top), (55.6, top + dip), (fly, top + 0.8 + lift), (fly - 0.6, foot + 0.2 + low),
                    (55.6, foot + dip), (hx, foot), corners=(0, 2, 3, 5)), when=when, part='flag')


def _pennant(b: SketchBuilder) -> None:
    """Everything done: a long pennant streams from the pole's top."""
    hx = 50.7
    b.line(loop((hx, POLE_TOP), (62.0, 16.4), (74.0, 13.2), (87.0, 9.4), (74.0, 15.0), (62.0, 18.6),
                (hx, POLE_TOP + 2.0), corners=(0, 3, 6)), when=(('allDone',),), part='pennant')


# ── the boats ───────────────────────────────────────────────────────────────

def _hull(x: float, y: float, sc: float):
    h = HALF * sc
    return curve((x - h, y - FOOT * sc + 0.2), (x - 0.55 * h, y - 0.6), (x, y), (x + 0.55 * h, y - 0.6),
                 (x + h, y - FOOT * sc + 0.2))


def _sail(x: float, y: float, sc: float, facing: int, tall: float):
    foot = y - FOOT * sc
    mast = x - facing * MAST * sc
    return poly((mast, foot), (mast, foot - tall * sc), (x + facing * CLEW * sc, foot))


def _boats(b: SketchBuilder, s: dict, *, night: bool) -> None:
    for i, (x, y, sc, facing, tall) in enumerate(s['boats']):
        when = (('reward', i), *PLANNED)
        part = f'boat:{i}'
        if night:
            k.glow_dot(b, x, y - FOOT * sc - LIGHT_R * 1.05, LIGHT_R, halo=min(11.0, 159.5 - x),
                       when=when, part=part)
        else:
            b.filled(_sail(x, y, sc, facing, tall), when=when, part=part)
        b.line(_hull(x, y, sc), when=when, part=part)
        b.anchor(i, x, y)


# ── the light ───────────────────────────────────────────────────────────────

def _gull(b: SketchBuilder, x: float, y: float, i: int) -> None:
    """A gull in flight: two wings bowed up from a dip, their tips down."""
    b.line(curve((x - 7.0, y + 0.4), (x - 3.6, y - 3.4), (x, y), (x + 3.6, y - 3.4), (x + 7.0, y + 0.2),
                 corners=(2,)), part=f'gull:{i}')


def _sky_ok(p) -> bool:
    """Room for a star: off the lighthouse, its pennant and the sails."""
    x, y = p
    if 30 <= x <= 70:
        return False
    if 44 <= x <= 94 and y <= 30:
        return False
    return y <= 70


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _point(b, s)
    _sea_line(b)
    _waves(b)
    _tower(b, s)
    b.line(line((50.0, LANTERN[1]), (50.0, LANTERN[3])), part='lantern')
    _flag(b, 0, when=(('idle',),))
    _pennant(b)
    for i, (x, y) in enumerate(GULLS):
        _gull(b, x, y, i)
    # The hour.
    k.sun(b, r.fork('sun-m'), 18, 32, 6.0, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 124, 18, 6.2, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 144, 44, 6.0, when=(k.AFTERNOON,))
    k.low_sun(b, r.fork('sun-d'), DUSK_X, SEA + 0.3, 6.5, when=(k.DUSK,))
    mx, my = 128.0, 22.0
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    weather = [(x, y, w * 0.55 + 4) for x, y, w in CLOUDS]
    k.stars(b, r.fork('late-stars'), 3, (6, 6, 154, 70),
            avoid=((mx, my, 14), *weather, *((x, y, 11) for x, y in GULLS)), ok=_sky_ok,
            when=(k.LATE,), part='star')
    # Overdue work: a cloud over the sea, a second, a third by the tower.
    for level, (x, y, w) in enumerate(CLOUDS, start=1):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level}')
    _boats(b, s, night=False)
    b.ambient(1.0, (('focus',),), lambda f, child: _flag(child, (1, 2, 0, 1, 2, 0)[f]))


def _rays(frame: int, child: SketchBuilder) -> None:
    """Start: the light turns, three short rays round the lantern."""
    cx, cy = LAMP
    span = 2 * RAY_SWEEP
    for j in range(3):
        t = (frame * span / 18 + j * span / 3) % span
        deg = -t if t < RAY_SWEEP else -(180 - RAY_SWEEP) - (t - RAY_SWEEP)
        a = math.radians(deg)
        child.line(line((cx + RAY_IN * math.cos(a), cy + RAY_IN * math.sin(a)),
                        (cx + RAY_OUT * math.cos(a), cy + RAY_OUT * math.sin(a))), part='ray')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _point(b, s)
    cx, cy = LAMP
    # The lamp is lit: its beam out over the sea, always; everything done, a
    # second, wider one the other way.
    b.glow(poly((cx, cy - 2.5), (160.0, 28.0), (160.0, 78.0), (cx, cy + 2.5)), part='beam')
    b.glow(poly((cx, cy - 2.5), (0.0, 6.0), (0.0, 86.0), (cx, cy + 2.5)), when=(('allDone',),), part='beam')
    b.glow(k.ring(cx, cy, 12.0, 11), part='lamp')
    mx, my = s['moon_spot']
    clouds = k.moon(b, mx, my, 7.0, clouds=2)
    k.stars(b, r.fork('stars'), 3, (6, 6, 154, 70),
            avoid=((mx, my, 20), *clouds, (cx, cy, RAY_OUT + 6)), ok=_sky_ok, part='star')
    _sea_line(b)
    _waves(b)
    _tower(b, s)
    b.filled(k.ring(cx, cy, 3.0, 8), part='lamp')
    _boats(b, s, night=True)
    b.ambient(1.0, (('focus',),), _rays)
