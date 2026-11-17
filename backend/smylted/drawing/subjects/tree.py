"""A potted tree.

Day: the tree fills the picture, as the mockup's does: a full canopy on a sage
wash, one trunk with a fork or two, a pot on a short sill. Each finished task
hangs a coral fruit in it; Start shakes a few leaves loose from the crown;
everything done brings a bird to its shoulder; a day with nothing planned has
a watering can by the pot; overdue work drops a leaf or two by the pot. The
sun crosses the sky with the hour; late at night it is an ink moon.

Night: the same tree under the moon, its crown still sage, lit from the moon's
side. A lantern hangs under the crown, a pale light. The rewards are fireflies
about the crown, each a coral spark in a soft glow; Start shakes leaves loose
as by day; everything done fills the lantern's glass coral; overdue work brings
a small cloud near the moon.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

SILL = 190.0
MOON_R = 6.0
FRUIT_R = 7.0
FLY_R = 6.0


class PottedTree:
    id = 'tree'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('trunk', 'canopy'), ('trunk', 'branch'), ('branch', 'canopy'), ('trunk', 'soil'),
        ('pot', 'soil'), ('pot', 'rim'), ('pot', 'sill'), ('can', 'sill'), ('fallen', 'sill'),
        ('bird', 'canopy'), ('stir', 'canopy'), ('echo', 'canopy'), ('moon', 'cloud'),
        ('lantern', 'canopy'), ('rim', 'trunk'), ('rim', 'soil'), ('branch',),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same tree after dark."""
    lean = r.uniform(-4, 4)
    pot_w, pot_h = r.uniform(50, 56), r.uniform(32, 36)
    top = SILL - pot_h
    cx, cy = 80 + lean * 0.6, r.uniform(68, 72)
    rx, ry = r.uniform(62, 65), r.uniform(54, 57)
    canopy = k.blob(cx, cy, rx, ry, r.fork('canopy'), n=11, wobble=0.07)

    # One trunk, an S from the soil into the crown, and a fork or two off it.
    crown = (80 + lean * 0.6, cy + ry * 0.5)
    trunk_pts = [(80.0, top + 3), (80 + lean * 0.3 + 1.4, top - (top - crown[1]) * 0.35),
                 (80 + lean * 0.6 - 1.4, top - (top - crown[1]) * 0.7), crown]
    trunk = curve(*trunk_pts)
    forks = []
    sides = [-1, 1] if r.random() < 0.5 else [1, -1]
    for i in range(r.randint(1, 2)):
        side = sides[i]
        t = r.uniform(0.62, 0.8)
        sx = trunk_pts[0][0] + (crown[0] - trunk_pts[0][0]) * t + side * 0.6
        sy = trunk_pts[0][1] + (crown[1] - trunk_pts[0][1]) * t
        ex, ey = sx + side * r.uniform(15, 20), sy - r.uniform(16, 22)
        forks.append(curve((sx, sy), ((sx + ex) / 2 + side * 1.5, (sy + ey) / 2 + 2.5), (ex, ey)))

    # One contour echo inside the crown's lower side, as the mockup draws.
    mirror = -1 if r.random() < 0.5 else 1
    echo = curve(*[(cx + mirror * u * rx, cy + v * ry)
                   for u, v in ((-0.18, 0.16), (-0.5, 0.3), (-0.78, 0.12), (-0.8, -0.2))])

    ink = [*k.samples(trunk), *(p for f in forks for p in k.samples(f)), *k.samples(echo),
           *k.samples(canopy)]
    rim = []                                      # leaves that come loose when Start runs
    # On the crown's sides only, so they fall outside it, clear of the fruit.
    for a in (r.uniform(172, 192), r.uniform(146, 160), r.uniform(-14, 6)):
        rad = math.radians(a)
        rim.append((cx + rx * 0.96 * math.cos(rad), cy + ry * 0.96 * math.sin(rad), rad))

    # Everything keeps clear of the leaves that fall from the crown's sides
    # while Start runs: every place each leaf passes, as far as its tip reaches.
    falls = []
    for rx_, ry_, ra in rim:
        out = 1 if math.cos(ra) >= 0 else -1
        for f in range(6):
            a = ra + 0.5 * f
            falls.append((rx_ + out * 2.6 * f + 5.5 * math.cos(a), ry_ + 3.2 * f - 2 + 5.5 * math.sin(a), 7.0))

    # Clear of every line by two pens and a gap, and of the bird when it comes.
    bird = (cx + rx * 0.5, cy - ry * 0.86 - 8)
    avoid = (*((x, y, FRUIT_R + 4.5) for x, y in ink), (*bird, FRUIT_R + 12),
             *((x, y, r_ + FRUIT_R + 3.0) for x, y, r_ in falls))
    fruit = k.scatter_all(r.fork('fruit'), k.REWARDS, cx, cy - 4, rx * 0.8, ry * 0.74, 19.0, avoid=avoid)
    fruit = k.spread(fruit, (cx, cy - ry))

    # Where the lantern hangs under the crown, away from the trunk; the
    # fireflies keep clear of it.
    lx = cx - rx * 0.52 * (1 if lean >= 0 else -1)
    lantern_y = cy + ry * math.sqrt(max(0.0, 1 - ((lx - cx) / rx) ** 2)) * 0.97
    # ... and of the moon's overdue clouds, below it and beside it.
    moon_spot = r.choice([(16.0, 16.0), (144.0, 16.0)])
    fly_avoid = (*((x, y, FLY_R + 5.0) for x, y in ink),
                 *((x, y, r_ + FLY_R + 3.0) for x, y, r_ in falls),
                 (lx, lantern_y + 12, 19.0), (lx, lantern_y - 2, 13.0),
                 *((x, y, r_ + FLY_R + 3.0) for x, y, r_ in _veil(moon_spot)))
    flies = k.scatter_all(r.fork('flies'), k.REWARDS, cx, cy - 2, rx * 1.16, ry * 1.04, 18.0,
                          avoid=fly_avoid, ok=lambda p: 15 < p[0] < 145 and 15 < p[1] < top - 12)
    flies = k.spread(flies, (cx, cy - ry))

    return {
        'lean': lean, 'pot': r.choice(['belly', 'taper', 'band']), 'pot_w': pot_w, 'top': top,
        'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'canopy': canopy, 'trunk': trunk, 'forks': forks,
        'echo': echo, 'fruit': fruit, 'flies': flies, 'rim': rim, 'lantern': (lx, lantern_y),
        'can_side': r.choice([-1, 1]),
        'moon_spot': moon_spot,
    }


def _veil(spot) -> tuple:
    """Where the night moon's overdue clouds go (see _night): circles round
    each, the size of the cloud."""
    x, y = spot
    toward = 1 if x < 80 else -1
    return ((x + toward * 2.6 * MOON_R, y - 0.5 * MOON_R, 9.0), (x - toward * 0.5 * MOON_R, y + 2.0 * MOON_R, 7.0))


def _pot(b: SketchBuilder, s: dict) -> None:
    w, top = s['pot_w'], s['top']
    x0, x1 = 80 - w / 2, 80 + w / 2
    # The rim runs a little past the pot each side, as the mockup's does.
    b.line(line((x0 - 3, top), (x1 + 3, top + 0.4)), part='rim')
    if s['pot'] == 'belly':
        b.line(curve((x0, top), (x0 - 3, top + (SILL - top) * 0.45), (x0 + 7, SILL), (x1 - 7, SILL),
                     (x1 + 3, top + (SILL - top) * 0.45), (x1, top), corners=(2, 3)), part='pot')
    elif s['pot'] == 'taper':
        b.line(line((x0, top), (x0 + 6, SILL), (x1 - 6, SILL), (x1, top)), part='pot')
    else:
        b.line(line((x0 + 1, top), (x0 + 3, SILL), (x1 - 3, SILL), (x1 - 1, top)), part='pot')
        band = top + (SILL - top) * 0.3
        b.line(line((x0 + 1.6, band), (x1 - 1.6, band)), part='pot')
    b.line(curve((x0 + 6, top + 2.2), (80, top + 4.4), (x1 - 6, top + 2.2)), part='soil')


def _tree(b: SketchBuilder, s: dict) -> None:
    b.line(s['trunk'], part='trunk')
    for i, f in enumerate(s['forks']):
        b.line(f, part=f'branch:{i}')
    b.line(s['canopy'], part='canopy')
    b.line(s['echo'], part='echo')


def _sill(b: SketchBuilder, s: dict) -> None:
    half = s['pot_w'] / 2 + 46
    b.line(line((80 - half, SILL), (80 + half, SILL + 0.5)), part='sill')


def _can(b: SketchBuilder, s: dict, *, when: tuple) -> None:
    """A watering can by the pot, resting: nothing to do yet, and that is fine."""
    side = s['can_side']
    x = 80 + side * (s['pot_w'] / 2 + 22)
    b.line(poly((x - 9, SILL), (x + 9, SILL), (x + 8, SILL - 16), (x - 8, SILL - 16)), when=when, part='can')
    b.line(line((x + side * 8, SILL - 10), (x + side * 18, SILL - 21)), when=when, part='can')
    b.line(curve((x - side * 7, SILL - 16), (x - side * 3, SILL - 25), (x + side * 4, SILL - 16)),
           when=when, part='can')


def _fallen(b: SketchBuilder, s: dict) -> None:
    """Overdue work, gently: a leaf down by the pot per level, resting on the
    sill (never cut by it), strewn rather than in a row."""
    side = -s['can_side']
    base = 80 + side * (s['pot_w'] / 2 + 9)
    for level, (dx, deg) in enumerate(((0, -8), (side * 15, 172), (side * 30, -3)), start=1):
        a = math.radians(deg)
        length = 10.5
        cx = base + dx - 0.5 * length * math.cos(a)          # placed by its middle
        k.draw_leaf(b, cx, SILL - 1.4 - k.leaf_low(length, a), length, a,
                    when=(('overdue', level),), part=f'fallen:{level}')


def _stir(s: dict):
    """Start: three leaves come loose from the crown and drift down and out."""
    def draw(frame: int, child: SketchBuilder) -> None:
        for i, (x, y, a) in enumerate(s['rim']):
            out = 1 if math.cos(a) >= 0 else -1
            f = (frame + i * 2) % 6
            k.draw_leaf(child, x + out * 2.6 * f, y + 3.2 * f - 2, 11, a + 0.5 * f, part='stir')
    return draw


def _sky(b: SketchBuilder, s: dict, r: Rng) -> None:
    """The hour, day composition: the sun crosses, and late on an ink moon."""
    k.sun(b, r.fork('sun-m'), 17, 18, 5.0, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 143, 17, 5.4, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 145, 132, 5.0, when=(k.AFTERNOON,))
    k.sun(b, r.fork('sun-d'), 18, 140, 4.6, when=(k.DUSK,), rays=5)
    x, y = s['moon_spot']
    k.moon(b, x, y, 6.0, glow=False, veiled=False, when=(k.LATE,))
    bird = (s['cx'] + s['rx'] * 0.5, s['cy'] - s['ry'] * 0.86 - 6)
    k.stars(b, r.fork('late-stars'), 3, (6, 6, 154, 40), avoid=((x, y, 18), (*bird, 18)),
            ok=lambda p: not _in_crown(s, p, 1.12), when=(k.LATE,), part='late-star')


def _in_crown(s: dict, p, grow: float) -> bool:
    return ((p[0] - s['cx']) / (s['rx'] * grow)) ** 2 + ((p[1] - s['cy']) / (s['ry'] * grow)) ** 2 <= 1


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(s['canopy']), part='canopy')
    _sky(b, s, r)
    _sill(b, s)
    _pot(b, s)
    _tree(b, s)
    _fallen(b, s)
    _can(b, s, when=(('nothingPlanned',),))
    k.bird(b, s['cx'] + s['rx'] * 0.5, s['cy'] - s['ry'] * 0.86 + 0.5, when=(('allDone',),),
           facing=-1 if s['lean'] > 0 else 1)
    for i, (x, y) in enumerate(s['fruit']):
        k.fruit(b, x, y, FRUIT_R, when=(('reward', i),), part=f'fruit:{i}')
        b.anchor(i, x, y - FRUIT_R)
    b.ambient(1.0, (('focus',),), _stir(s))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    x, y = s['moon_spot']
    side = -1 if x < 80 else 1
    # The crown in moonlight: its sage falls toward the moon, not away from it
    # as the day's does.
    b.wash(k.wash_of(s['canopy'], dx=4.0 * side, dy=-4.0), part='canopy')
    # The overdue clouds keep to the corner and the top edge, clear of the crown.
    toward = 1 if x < 80 else -1
    k.moon(b, x, y, MOON_R, first=(toward * 2.6, -0.5), second=(-toward * 0.5, 2.0))
    flies = tuple((fx, fy, FLY_R + 6) for fx, fy in s['flies'])
    k.stars(b, r.fork('stars'), 4, (6, 4, 154, 34),
            avoid=((x, y + 7, 26), *((vx, vy, vr + 4) for vx, vy, vr in _veil(s['moon_spot'])), *flies),
            ok=lambda p: not _in_crown(s, p, 1.14), part='star')
    _sill(b, s)
    _pot(b, s)
    _tree(b, s)
    _fallen(b, s)
    _can(b, s, when=(('nothingPlanned',),))
    # A lantern hangs under the crown every night, a pale light; everything
    # done fills its glass coral.
    lx, rim = s['lantern']
    done = (('allDone',),)
    b.glow(k.ring(lx, rim + 13, 15, 12), part='lantern')
    b.glow(k.ring(lx, rim + 13, 5, 9), part='lantern')
    b.line(line((lx, rim - 4), (lx, rim + 5)), part='lantern')
    b.line(line((lx - 4.6, rim + 6), (lx + 4.6, rim + 6.2)), part='lantern')
    body = loop((lx - 3.6, rim + 7), (lx + 3.6, rim + 7), (lx + 4.6, rim + 13), (lx + 3.4, rim + 19),
                (lx - 3.4, rim + 19), (lx - 4.6, rim + 13), corners=(0, 1, 3, 4))
    b.line(body, when=(('notAllDone',),), part='lantern')
    b.filled(body, when=done, part='lantern', paper='glint')
    b.line(line((lx - 3.6, rim + 20.4), (lx + 3.6, rim + 20.4)), part='lantern')
    for i, (fx, fy) in enumerate(s['flies']):
        k.glow_dot(b, fx, fy, FLY_R, halo=14, when=(('reward', i),), part=f'fly:{i}', glass=False)
        b.anchor(i, fx, fy)
    b.ambient(1.0, (('focus',),), _stir(s))
