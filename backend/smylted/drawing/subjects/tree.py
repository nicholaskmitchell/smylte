"""A potted tree on a sill.

Day: the tree in sun, its canopy on a sage wash. Each finished task hangs a
coral fruit in it; Start stirs two leaves; everything done brings a bird to the
crown; a day with nothing planned has a watering can beside the pot; overdue
work curls a leaf or two and, at most, drops one on the sill.

Night: the same tree, pot and branches, under a crescent moon. Light is the
subject: the moon's glow is the only wash, the rewards are fireflies in the
branches, Start sets one drifting, everything done lights a lantern on a
branch, and overdue work edges a cloud onto the moon. More paper, fewer fills.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

SILL = 186.0


class PottedTree:
    id = 'tree'
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
    """What both compositions share, so dark reads as the same tree after dark."""
    lean = r.uniform(-6, 6)
    pot_w, pot_h = r.uniform(46, 56), r.uniform(34, 41)
    cx, cy = 80 + lean, r.uniform(74, 80)
    rx, ry = r.uniform(45, 51), r.uniform(38, 44)
    top = SILL - pot_h
    branches = []
    for i in range(r.randint(2, 3)):
        side = -1 if i % 2 == 0 else 1
        t = r.uniform(0.35, 0.7)
        sx = 80 + lean * t * 0.8
        sy = top - (top - (cy + ry * 0.4)) * t
        ex = sx + side * r.uniform(14, 24)
        ey = sy - r.uniform(14, 24)
        branches.append(((sx, sy), ((sx + ex) / 2 + side * 2, (sy + ey) / 2 + 3), (ex, ey)))
    edge = []
    for _ in range(r.randint(2, 4)):
        a = r.uniform(-0.2, math.pi + 0.2) + math.pi       # the upper rim
        edge.append((cx + rx * 0.98 * math.cos(a), cy + ry * 0.98 * math.sin(a), a))
    return {
        'lean': lean, 'pot': r.choice(['taper', 'belly', 'band']),
        'pot_w': pot_w, 'top': top, 'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry,
        'canopy': k.blob(cx, cy, rx, ry, r.fork('canopy'), n=11, wobble=0.09),
        'branches': branches,
        'inner': [_inner(r.fork(f'inner{i}'), cx, cy, rx, ry) for i in range(3)],
        'spots': k.scatter(r.fork('fruit'), k.REWARDS, cx, cy - 2, rx * 0.72, ry * 0.64, gap=10.5),
        'edge_leaves': edge,
        'can_side': r.choice([-1, 1]),
        'droops': [(cx - rx * 0.45, cy + ry * 0.86), (cx + rx * 0.4, cy + ry * 0.9),
                   (cx + rx * 0.05, cy + ry * 0.98)],
    }


def _inner(r: Rng, cx: float, cy: float, rx: float, ry: float):
    """A short hatch inside the canopy: the shadow side of the leaves."""
    x0 = cx + r.uniform(-0.55, 0.1) * rx
    y0 = cy + r.uniform(-0.1, 0.45) * ry
    return curve((x0, y0), (x0 + rx * 0.22, y0 + r.uniform(1, 4)),
                 (x0 + rx * 0.4, y0 - r.uniform(2, 6)))


def _pot(b: SketchBuilder, s: dict) -> None:
    w, top = s['pot_w'], s['top']
    x0, x1 = 80 - w / 2, 80 + w / 2
    if s['pot'] == 'taper':
        b.line(poly((x0 - 3, top - 6), (x1 + 3, top - 6), (x1 + 3, top), (x0 - 3, top)))
        b.line(poly((x0, top), (x1, top), (x1 - 6, SILL), (x0 + 6, SILL)))
    elif s['pot'] == 'belly':
        b.line(line((x0 - 1, top), (x1 + 1, top)))
        b.line(curve((x0, top), (x0 - 4, top + (SILL - top) * 0.5), (x0 + 7, SILL),
                     (x1 - 7, SILL), (x1 + 4, top + (SILL - top) * 0.5), (x1, top)))
    else:
        b.line(poly((x0, top), (x1, top), (x1, SILL), (x0, SILL)))
        band = top + (SILL - top) * 0.32
        b.line(line((x0, band), (x1, band)))
    b.line(curve((x0 + 5, top + 2), (80, top + 4), (x1 - 5, top + 2)))         # the soil


def _trunk(b: SketchBuilder, s: dict) -> None:
    top, lean = s['top'], s['lean']
    crown = (80 + lean * 0.8, s['cy'] + s['ry'] * 0.42)
    mid = (80 + lean * 0.35, (top + crown[1]) / 2)
    for dx, tip in ((-2.4, -1.2), (2.4, 1.2)):
        b.line(curve((80 + dx, top + 1), (mid[0] + dx * 0.8, mid[1]), (crown[0] + tip, crown[1])))
    for p0, p1, p2 in s['branches']:
        b.line(curve(p0, p1, p2))


def _sill(b: SketchBuilder) -> None:
    b.line(line((6, SILL), (154, SILL + 0.6)))
    b.line(line((10, SILL + 7), (150, SILL + 7.4)))


def _can(b: SketchBuilder, s: dict, *, when: tuple) -> None:
    """A watering can beside the pot, resting: nothing to do yet, and that is fine."""
    side = s['can_side']
    x = 80 + side * (s['pot_w'] / 2 + 26)
    b.line(poly((x - 11, SILL), (x + 11, SILL), (x + 9, SILL - 18), (x - 9, SILL - 18)), when=when)
    b.line(line((x + side * 9, SILL - 12), (x + side * 22, SILL - 24)), when=when)
    b.line(curve((x - side * 8, SILL - 18), (x - side * 4, SILL - 28), (x + side * 4, SILL - 18)), when=when)


def _bird(b: SketchBuilder, x: float, y: float, *, when: tuple, k_: float = 1.5) -> None:
    def p(dx: float, dy: float):
        return (x + dx * k_, y + dy * k_)
    b.line(loop(p(-6, 0), p(0, -3.4), p(5, -1), p(2, 2.6), p(-4, 2.4)), when=when)
    b.line(loop(p(4, -3.6), p(7.2, -5.4), p(8.6, -2.6), p(6, -1.4)), when=when)
    b.line(line(p(8.6, -4), p(11, -3.4)), when=when)                 # beak
    b.line(line(p(-6, 0), p(-10.4, -2.6)), when=when)                # tail
    b.line(line(p(-1, 2.6), p(-1.6, 6)), when=when)
    b.line(line(p(1.6, 2.4), p(1.8, 6)), when=when)


def _droops(b: SketchBuilder, s: dict) -> None:
    """Overdue work, gently: a curled leaf per level, and at most one on the sill."""
    for level, (x, y) in enumerate(s['droops'][:2], start=1):
        b.line(k.leaf(x, y, 9, math.radians(100 + level * 14)), when=(('overdue', level),))
    x = 80 + s['can_side'] * -(s['pot_w'] / 2 + 14)
    b.line(k.leaf(x, SILL - 2.4, 9, math.radians(-8)), when=(('overdue', 3),))


def _stir(s: dict):
    """Start: two edge leaves sway, a small loop at 6fps."""
    leaves = s['edge_leaves'][:2]

    def draw(frame: int, child: SketchBuilder) -> None:
        swing = math.sin(2 * math.pi * frame / 6) * 0.28
        for x, y, a in leaves:
            child.line(k.leaf(x, y, 8, a + swing))
    return draw


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    cx, cy, rx, ry = s['cx'], s['cy'], s['rx'], s['ry']
    b.wash(k.blob(cx + 3, cy + 3, rx, ry, r.fork('wash'), n=11, wobble=0.06))
    k.sun(b, 20, 30, 7, when=(k.MORNING,))
    k.sun(b, 140, 20, 8, when=(k.MIDDAY,))
    k.sun(b, 144, 40, 7, when=(k.AFTERNOON,))
    k.low_sun(b, 146, SILL - 0.5, 9, when=(k.EVENING,))
    _sill(b)
    _pot(b, s)
    _trunk(b, s)
    b.line(s['canopy'])
    for stroke in s['inner']:
        b.line(stroke)
    for x, y, a in s['edge_leaves'][2:]:
        b.line(k.leaf(x, y, 8, a))
    _droops(b, s)
    _can(b, s, when=(('nothingPlanned',),))
    _bird(b, cx + rx * 0.12, cy - ry * 0.98 - 8, when=(('allDone',),))
    for i, (x, y) in enumerate(s['spots']):
        k.fruit(b, x, y, 4.6, when=(('reward', i),))
    b.ambient(1.0, (('focus',),), _stir(s))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    cx, cy, rx, ry = s['cx'], s['cy'], s['rx'], s['ry']
    moons = ((22, 24, k.MORNING), (138, 18, k.MIDDAY), (142, 30, k.AFTERNOON), (24, 22, k.EVENING))
    for x, y, hour in moons:
        k.moon(b, x, y, 7.5, when=(hour,))
    k.stars(b, r.fork('stars'), 5, (6, 6, 154, 26))
    for i, (x, y, hour) in enumerate(moons):
        k.cloud(b, x + 6, y + 5, 24, when=(hour, ('overdue', 1)))
        k.cloud(b, x - 10, y + 12, 18, when=(hour, ('overdue', 2)))
    _sill(b)
    _pot(b, s)
    _trunk(b, s)
    b.line(s['canopy'])
    b.line(s['inner'][0])
    _can(b, s, when=(('nothingPlanned',),))
    x, y = s['branches'][0][2]
    b.line(line((x, y), (x, y + 6)), when=(('allDone',),))                       # the lantern's cord
    k.glow_dot(b, x, y + 10, 3.4, halo=11, when=(('allDone',),))
    b.line(poly((x - 3.6, y + 6), (x + 3.6, y + 6), (x + 3.6, y + 14), (x - 3.6, y + 14)), when=(('allDone',),))
    x = 80 + s['can_side'] * -(s['pot_w'] / 2 + 14)
    b.line(k.leaf(x, SILL - 2.4, 9, math.radians(-8)), when=(('overdue', 3),))
    for i, (x, y) in enumerate(s['spots']):
        k.glow_dot(b, x, y, 2.2, halo=5.6, when=(('reward', i),))

    path = [(cx + rx * 0.55 * math.cos(t), cy - ry * 0.2 + ry * 0.3 * math.sin(2 * t))
            for t in (2 * math.pi * f / 6 for f in range(6))]

    def drift(frame: int, child: SketchBuilder) -> None:
        x, y = path[frame]
        child.accent(k.ring(x, y, 2.0, 7))
    b.ambient(1.0, (('focus',),), drift)
