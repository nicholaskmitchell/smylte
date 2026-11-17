"""Seedlings on a windowsill.

Day: three pots on a sill under a window of sky (the sage is the daylight in
its panes), a seedling in each. Each finished task opens a coral bud on a
seedling, the first few spread across the three; Start brings a butterfly to
the right-hand pane; everything done sets a watering can down on the sill; a
day with nothing planned leaves the pots empty, a seed packet leaning on the
last; overdue work droops a leaf, then drops one on the sill, then another.
The sun crosses the panes with the hour, sets on the window's rail, and late
at night is an ink moon.

Night: the same sill with a tealight between the first two pots. Its flame is
the light, and the buds are lit by it; the window is dark, the moon in a pane
and stars beside it. Start makes the flame flicker; everything done brings the
can and a soft light along the sill; nothing planned and overdue work are as
by day.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

WIN = (12.0, 8.0, 148.0, 68.0)
MUNTINS = (57.0, 103.0)
SILL = 176.0
EDGE = 183.0
RIM, BAND = 146.0, 152.0
SOIL = 148.0               # the height the seedlings' tips are measured from
TOP_W, BASE_W = 28.0, 21.0
BUD_R = 6.5
GLOW_R = 6.0
LEAF = 9.5
# Each bud from its seedling's tip: (dx, dy), the tip's own bud first.
BUDS = ((0.0, -9.5), (-12.0, 14.0), (11.0, 26.0), (-12.0, 38.0))
PLANNED = (('planned',),)
# Paper between a mark's ink and the next: a pen and the wobble of both.
CLEAR = k.MIN_GAP + 0.25


class WindowsillSeedlings:
    id = 'seedlings'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('pot', 'sill'), ('pot', 'soil'), ('stem', 'soil'), ('stem', 'leaf'), ('stem', 'bud'),
        ('window', 'muntin'), ('sun', 'window'), ('packet', 'sill'), ('packet', 'pot'),
        ('can', 'sill'), ('cup', 'sill'), ('flame', 'cup'), ('fallen', 'sill'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _half(y: float) -> float:
    """A pot's half-width at height y: it tapers from the rim to the base."""
    return TOP_W / 2 - (TOP_W - BASE_W) / 2 * (y - RIM) / (SILL - RIM)


def _soil_y(dx: float) -> float:
    """The soil's height at dx from the pot's centre: a low mound in the rim."""
    return RIM + 0.6 + 0.9 * (dx / 13.8) ** 2


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same sill after dark."""
    pots = [x + r.uniform(-1, 1) for x in (30.0, 72.0, 114.0)]
    tips = [SOIL - r.uniform(52, 56) for _ in pots]
    # All three lean the same way, toward the light, each by its own amount:
    # neighbours' buds then keep their distance.
    lean = r.choice([-1, 1])
    bends = [lean * r.uniform(0.8, 1.6) for _ in pots]

    seedlings = []
    buds = []
    for cx, tip, bend in zip(pots, tips, bends):
        base = _soil_y(0)

        def sx(y: float, cx=cx, tip=tip, bend=bend, base=base) -> float:
            u = (base - y) / (base - tip)
            return cx + bend * math.sin(math.pi * u)

        # The stem runs on past its tip as the tip bud's 3-unit stalk.
        stem = curve(*[(sx(base + (tip - base) * i / 5), base + (tip - base) * i / 5) for i in range(6)],
                     (cx, tip - 3.0))
        stalks = []
        heads = [((cx, tip - 9.5), (cx, tip - 3.0))]
        for dx, dy in BUDS[1:]:
            c = (sx(tip + dy) + dx, tip + dy)
            jy = c[1] + 4.0
            j = (sx(jy), jy)
            d = math.dist(j, c)
            e = (c[0] + BUD_R * (j[0] - c[0]) / d, c[1] + BUD_R * (j[1] - c[1]) / d)
            mid = ((j[0] + e[0]) / 2, (j[1] + e[1]) / 2 + 0.9)
            stalks.append(curve(j, mid, e))
            heads.append((c, e))
        seedlings.append({
            'cx': cx, 'tip': tip, 'stem': stem, 'stalks': stalks,
            # Two leaves low on the stem: one left between the left buds, one
            # right below the right bud (the lower, which droops when overdue).
            'left': (sx(tip + 26), tip + 26),
            'right': (sx(tip + 40), tip + 40),
        })
        buds.extend(heads)
    order = k.spread([c for c, _ in buds], buds[0][0])
    by_centre = dict(buds)
    return {
        'pots': pots, 'seedlings': seedlings,
        'buds': [(c, by_centre[c]) for c in order],
        'moon_spot': (31 + r.uniform(-2, 2), 30 + r.uniform(-2, 2)),
        'leaf_tilt': [math.radians(r.uniform(-4, 4)) for _ in pots],
    }


def _pot_outline(cx: float):
    return poly((cx - TOP_W / 2, RIM), (cx + TOP_W / 2, RIM), (cx + BASE_W / 2, SILL), (cx - BASE_W / 2, SILL))


def _window(b: SketchBuilder) -> None:
    x0, y0, x1, y1 = WIN
    # Ruled straight, not bowed: the seedlings' tip buds sit close under it.
    b.line(loop((x0, y0), (x1, y0), (x1, y1), (x0, y1), corners=(0, 1, 2, 3)), part='window')
    for x in MUNTINS:
        b.line(line((x, y0), (x + 0.3, y1)), part='muntin')


def _sill(b: SketchBuilder) -> None:
    # Level, never bowed up into what stands on it.
    b.line(curve((4, SILL), (80, SILL + 0.3), (156, SILL)), part='sill')
    b.line(curve((6, EDGE), (80, EDGE + 0.3), (154, EDGE + 0.2)), part='sill')


def _pots(b: SketchBuilder, s: dict) -> None:
    for cx in s['pots']:
        # Open at the top: the soil is its top, the band its rim.
        b.line(line((cx - TOP_W / 2, RIM), (cx - BASE_W / 2, SILL)), part='pot')
        b.line(line((cx + TOP_W / 2, RIM), (cx + BASE_W / 2, SILL)), part='pot')
        hb = _half(BAND)
        b.line(line((cx - hb, BAND), (cx + hb, BAND)), part='pot')
        hs = 13.8
        b.line(curve(*[(cx + dx, _soil_y(dx)) for dx in (-hs, -7, 0, 7, hs)]), part='soil')


def _seedlings(b: SketchBuilder, s: dict) -> None:
    for i, p in enumerate(s['seedlings']):
        b.line(p['stem'], when=PLANNED, part='stem')
        for st in p['stalks']:
            b.line(st, when=PLANNED, part='stem')
        tilt = s['leaf_tilt'][i]
        k.draw_leaf(b, *p['left'], LEAF, math.pi - 0.08 + tilt, when=PLANNED)
        if i == 0:
            # Overdue work: pot 1's lower leaf droops.
            k.draw_leaf(b, *p['right'], LEAF, math.radians(-8) + tilt, when=(*PLANNED, ('calm',)))
            k.draw_leaf(b, *p['right'], LEAF, math.radians(42), when=(*PLANNED, ('overdue', 1)))
        else:
            k.draw_leaf(b, *p['right'], LEAF, math.radians(-8) + tilt, when=PLANNED)


def _fallen(b: SketchBuilder, s: dict, *, night: bool) -> None:
    """Overdue work, gently: at two a leaf down on the sill between the first
    two pots (by night, where the tealight stands there, on pot 1's left), at
    three a second between the last two."""
    p1, p2, p3 = s['pots']
    spots = [((p1 + p2) / 2, 9.0, -6.0), ((p2 + p3) / 2, 9.0, 174.0)]
    if night:
        spots[0] = ((4.6 + p1 - _half(SILL - 3.5) - CLEAR) / 2, 8.0, -6.0)
    for level, (mid, length, deg) in enumerate(spots, start=2):
        a = math.radians(deg)
        x = mid - 0.5 * length * math.cos(a)
        k.draw_leaf(b, x, SILL - 1.4 - k.leaf_low(length, a), length, a,
                    when=(('overdue', level),), part=f'fallen:{level}')


def _can(b: SketchBuilder) -> None:
    """Everything done: a small watering can set down at the sill's right end."""
    when = (('allDone',),)
    top = SILL - 13
    b.line(line((139.6, SILL), (140.4, top), (150.4, top), (151.2, SILL)), when=when, part='can')
    b.line(curve((143, top), (146.5, top - 5), (151.5, top - 3.6), (151, top + 3)), when=when, part='can')
    b.line(curve((140.2, top + 8.5), (136.4, top + 3.5), (133.4, top - 2.4)), when=when, part='can')


def _packet(b: SketchBuilder, s: dict) -> None:
    """Nothing planned: a seed packet leaning on pot 3's right side."""
    when = (('nothingPlanned',),)
    cx = s['pots'][2]
    w, h, a = 14.0, 20.0, math.radians(12)
    ca, sa = math.cos(a), math.sin(a)
    # Its foot on the sill, its top left corner against the pot's wall.
    top_y = SILL - h * ca
    bx = cx + _half(top_y) + h * sa
    foot = (bx, SILL)
    up, along = (-sa, -ca), (ca, -sa)

    def at(u: float, v: float):
        return (foot[0] + along[0] * u + up[0] * v, foot[1] + along[1] * u + up[1] * v)

    b.line(poly(at(0, 0), at(w, 0), at(w, h), at(0, h)), when=when, part='packet')
    b.line(line(at(0.4, h - 5), at(w - 0.4, h - 5)), when=when, part='packet')


def _bud(cx: float, cy: float):
    """A round flower head opening: five rounded petals."""
    # A sharp notch between petals and a smooth round tip on each: the spline
    # turns at the notches and runs through the tips.
    pts = []
    for i in range(5):
        c = -math.pi / 2 + 2 * math.pi * i / 5
        for da, rr in ((-math.pi / 5, 0.72), (0.0, 1.0)):
            pts.append((cx + BUD_R * rr * math.cos(c + da), cy + BUD_R * rr * math.sin(c + da)))
    return loop(*pts, corners=(0, 2, 4, 6, 8))


def _butterfly(frame: int, child: SketchBuilder) -> None:
    """Start: a small butterfly flutters round the right-hand pane."""
    t = 2 * math.pi * frame / 6
    x, y = 125.5 + 4.0 * math.cos(t), 36.0 + 3.0 * math.sin(t)
    w = 4.4 * (1.0, 0.7, 0.4, 0.7, 1.0, 0.85)[frame]
    child.line(line((x, y - 2.8), (x + 0.2, y + 2.8)), part='butterfly')
    # Both wings in one stroke, a figure of eight through the body.
    wings = []
    for side in (-1, 1):
        wings += [(x, y + 0.4), (x + side * w, y - 3.6), (x + side * w * 1.05, y + 0.4),
                  (x + side * w * 0.6, y + 2.9)]
    child.line(loop(*wings, corners=(0, 4)), part='butterfly')


def _pane_ok(margin: float, panes: tuple):
    x0, y0, x1, y1 = WIN
    edges = (x0, *MUNTINS, x1)

    def ok(p) -> bool:
        if not y0 + margin <= p[1] <= y1 - margin:
            return False
        return any(edges[i] + margin <= p[0] <= edges[i + 1] - margin for i in panes)
    return ok


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    b.wash(k.wash_of(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)), inset=0.95, dx=3, dy=3), part='window')
    for cx in s['pots']:
        b.wash(k.wash_of(_pot_outline(cx), inset=0.9, dx=3, dy=2), part='pot')
    _window(b)
    # The hour, in the left and middle panes (the right is the butterfly's).
    sun = dict(ray_gap=3.4, ray_len=2.6, rays=5)
    k.sun(b, r.fork('sun-m'), 32, 40, 3.8, when=(k.MORNING,), **sun)
    k.sun(b, r.fork('sun-n'), 78, 26, 3.8, when=(k.MIDDAY,), **sun)
    k.sun(b, r.fork('sun-a'), 88, 38, 3.8, when=(k.AFTERNOON,), **sun)
    k.low_sun(b, r.fork('sun-d'), 34, y1 - 1.4, 5.4, when=(k.DUSK,))
    mx, my = s['moon_spot']
    k.moon(b, mx, my, 5.0, glow=False, clouds=0, when=(k.LATE,))
    k.stars(b, r.fork('late-stars'), 2, (60, 10, 100, WIN[3] - 2), ok=_pane_ok(2.5, (1,)),
            when=(k.LATE,), part='star')
    _sill(b)
    _pots(b, s)
    _seedlings(b, s)
    _fallen(b, s, night=False)
    _can(b)
    _packet(b, s)
    for i, ((x, y), (ax, ay)) in enumerate(s['buds']):
        b.filled(_bud(x, y), when=(('reward', i), *PLANNED), part=f'bud:{i}')
        # Its eye: held still with the head, as a dot of ink.
        b.filled(k.ring(x, y, 0.9, 5), when=(('reward', i), *PLANNED), part=f'bud:{i}')
        b.anchor(i, ax, ay)
    b.ambient(1.0, (('focus',),), _butterfly)


def _flame(child: SketchBuilder, x: float, shape: int, *, when: tuple = ()) -> None:
    lean, tall = ((0.0, 0.0), (-1.1, -0.8), (0.9, 0.6))[shape]
    y = SILL - 16.4
    child.line(loop((x + lean, y + tall), (x + 2.3, y + 5), (x, y + 8), (x - 2.3, y + 5),
                    corners=(0,)), when=when, part='flame')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    for cx in s['pots']:
        b.wash(k.wash_of(_pot_outline(cx), inset=0.9, dx=3, dy=2), part='pot')
    _window(b)
    mx, my = s['moon_spot']
    # No clouds: a pane has no room for one that reads, and overdue work
    # shows on the sill.
    k.moon(b, mx, my, 5.0, clouds=0)
    k.stars(b, r.fork('stars'), 3, (60, 10, 146, WIN[3] - 2), ok=_pane_ok(2.5, (1, 2)), part='star')
    # The tealight between the first two pots: its light is the night's.
    p1, p2, _ = s['pots']
    tx = (p1 + p2) / 2
    b.glow(k.ring(tx, SILL - 12, 26.0, 12), part='candle')
    b.glow(ellipse(80, SILL - 2, 72, 7, n=12), when=(('allDone',),), part='candle')
    b.line(line((tx - 4.0, SILL), (tx - 4.3, SILL - 6), (tx + 4.3, SILL - 6), (tx + 4.0, SILL)), part='cup')
    b.line(line((tx, SILL - 6), (tx + 0.2, SILL - 8.6)), part='flame')
    _flame(b, tx, 0, when=(('idle',),))
    _sill(b)
    _pots(b, s)
    _seedlings(b, s)
    _fallen(b, s, night=True)
    _can(b)
    _packet(b, s)
    for i, ((x, y), (ax, ay)) in enumerate(s['buds']):
        k.glow_dot(b, x, y, GLOW_R, halo=11, when=(('reward', i), *PLANNED), part=f'bud:{i}')
        b.anchor(i, ax, ay)
    b.ambient(1.0, (('focus',),), lambda f, child: _flame(child, tx, (1, 2, 0, 2, 1, 0)[f]))
