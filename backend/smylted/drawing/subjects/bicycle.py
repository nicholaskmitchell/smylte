"""A bicycle by a garden wall.

Day: a bicycle leans against a brick garden wall, a basket on its front rack,
ivy over the wall's left end. Each finished task opens a coral flower, in the
basket and in the ivy by turns; Start sets a ribbon streamer fluttering from
the handlebar; everything done ties a ribbon on the handlebar's end, hanging
in a loop; a day with nothing planned leaves the basket empty and the ivy
bare; overdue work lets the back tyre down, then brings a cloud, and at more
a second. The sun crosses the sky above the wall with the hour, sets on the
wall's coping, and late at night is an ink moon.

Night: the same wall and bicycle under a street lamp at the right, its light
falling in a cone onto the bicycle. Each finished task opens a flower lit by
the lamp; everything done ties the ribbon; Start sends moths round the lamp;
overdue work brings a cloud beside the moon, a second a step beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

COPING = 60.0              # the wall's top
FOOT = 150.0               # where the wall meets the pavement
GROUND = 172.0
REAR, FRONT = (44.0, 148.0), (118.0, 148.0)
TYRE, RIM = 22.0, 17.0
BRACKET = (79.0, 151.0)    # the bottom bracket
SEAT = (68.0, 106.0)       # the top of the seat tube
HEAD_TOP, HEAD_LOW = (106.0, 108.0), (110.0, 121.0)
BAR_END = (89.0, 93.0)     # the grip's end, where the ribbon is tied
BASKET = (114.0, 93.0, 146.0, 113.0)
POST_X = 156.5             # the street lamp, at night
LAMP = (141.0, 28.0)       # the middle of its head
FLOWER_R = 6.0
# The basket's bouquet: a front row on the rim, stems into the basket, and a
# back row nested above and between them (each back head over two front ones,
# so it never shows without them: the front row comes first).
BASKET_FRONT = ((110.0, 87.0), (127.0, 87.0), (144.0, 87.0))
BASKET_BACK = ((101.5, 72.0), (118.5, 72.0), (135.5, 72.0))
# The ivy's flowers, in three staggered rows on its wash.
IVY = ((14.0, 74.0), (32.0, 74.0), (23.0, 91.0), (41.0, 91.0), (14.0, 108.0), (32.0, 108.0))
PLANNED = ('planned',)

# Overdue weather by day, clear of every sun and the moon: (x, y, width).
CLOUDS = ((60.0, 34.0, 26.0), (108.0, 38.0, 26.0))


class Bicycle:
    id = 'bicycle'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('frame', 'wheel'), ('frame', 'saddle'), ('frame', 'bar'), ('rack', 'basket'),
        ('rack', 'frame'), ('rack', 'wheel'), ('wheel', 'ground'), ('flower', 'basket'),
        ('ribbon', 'bar'), ('ivy', 'wall'), ('sun', 'wall'), ('lamp', 'ground'),
        ('lamp', 'wall'),
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
    """What both compositions share, so the night is the same bicycle after dark."""
    # Each group moves as one, so its flowers keep their spacing.
    bx, by = r.uniform(-0.8, 0.8), r.uniform(-0.8, 0.8)
    ix, iy = r.uniform(-0.8, 0.8), r.uniform(-0.8, 0.8)
    front = [(x + bx, y + by) for x, y in BASKET_FRONT]
    back = [(x + bx, y + by) for x, y in BASKET_BACK]
    ivy = [(x + ix, y + iy) for x, y in IVY]
    turns = [r.uniform(0, 2 * math.pi / 5) for _ in range(k.REWARDS)]
    # Basket and ivy by turns, each farthest-first, the basket's front row
    # before its back row.
    basket = k.spread(front, front[1]) + k.spread(back, back[1])
    wall = k.spread(ivy, ivy[0])
    flowers = []
    for a, c in zip(basket, wall):
        flowers += [('basket', a), ('ivy', c)]
    return {
        'flowers': [(kind, p, t) for (kind, p), t in zip(flowers, turns)],
        'moon_spot': (22 + r.uniform(-2, 2), 20 + r.uniform(-2, 2)),
    }


# ── shapes ──────────────────────────────────────────────────────────────────

def _flower(x: float, y: float, turn: float):
    """Five round petals, notched between, about 12 across."""
    pts, corners = [], []
    for i in range(5):
        a = turn + 2 * math.pi * i / 5
        for da, rr in ((-0.36, FLOWER_R), (0.36, FLOWER_R)):
            pts.append((x + rr * math.cos(a + da), y + rr * math.sin(a + da)))
        corners.append(len(pts))
        pts.append((x + 3.5 * math.cos(a + math.pi / 5), y + 3.5 * math.sin(a + math.pi / 5)))
    return loop(*pts, corners=corners)


def _flat_tyre():
    """The back tyre let down: its bottom pressed flat on the ground and
    bulging a little either side."""
    cx, cy = REAR
    pts = []
    for i in range(14):
        a = 2 * math.pi * i / 14
        x, y = cx + TYRE * math.cos(a), cy + TYRE * math.sin(a)
        if y > cy + 12:
            x += (2.4 if x > cx else -2.4) * (y - cy - 12) / 10
            y = min(y, GROUND - 2.4)
        pts.append((x, y))
    return loop(*pts)


# ── the wall ────────────────────────────────────────────────────────────────

def _wall(b: SketchBuilder, *, night: bool) -> None:
    right = POST_X if night else 160.0
    b.line(curve((0, COPING), (60, COPING + 0.3), (120, COPING), (right, COPING + 0.2)), part='wall')
    # Its foot, where the wheels leave room.
    b.line(line((0.5, FOOT), (16.5, FOOT + 0.2)), part='wall')
    b.line(line((146.0, FOOT), (152.0 if night else 159.5, FOOT + 0.2)), part='wall')
    # A few bricks: above the saddle and bar, and through the frame. None
    # behind the basket or in the ivy.
    for stroke in (
        line((58, 72), (89, 72.3)), line((68, COPING), (68, 72)), line((82, COPING), (82, 72.2)),
        line((61, 72), (61, 82)),
        line((81, 126), (97, 126.3)), line((86, 126.2), (86, 133)),
    ):
        b.line(stroke, part='wall')


def _ivy(b: SketchBuilder) -> None:
    """A vine hanging from the coping beside the ivy's flowers and trailing
    back along under them; its leaves only on a day with something planned
    (the ivy is bare otherwise)."""
    b.line(curve((50, COPING), (53, 72), (53.2, 88), (53.6, 100), (51, 112), (40, 120), (26, 121.5),
                 (12, 121), (3, 115)), part='ivy')
    when = (PLANNED,)
    for x, y, length, angle in ((52.6, 76.0, 8.0, 0), (53.0, 105.0, 8.0, 125),
                                (9.0, 121.0, 8.0, 100), (21.0, 121.4, 8.5, 80),
                                (51.2, 64.0, 7.5, 160)):
        k.draw_leaf(b, x, y, length, math.radians(angle), when=when, part='ivy')


# ── the bicycle ─────────────────────────────────────────────────────────────

def _wheels(b: SketchBuilder) -> None:
    for i, (cx, cy) in enumerate((REAR, FRONT)):
        if i == 0:
            b.line(k.ring(cx, cy, TYRE, 12), when=(('calm',),), part='wheel')
            b.line(_flat_tyre(), when=(('overdue', 1),), part='wheel')
        else:
            b.line(k.ring(cx, cy, TYRE, 12), part='wheel')
        b.line(k.ring(cx, cy, RIM, 10), part='wheel')
        b.line(line((cx - 0.8, cy), (cx + 0.8, cy + 0.2)), part='wheel')


def _bike(b: SketchBuilder) -> None:
    _wheels(b)
    bx, by = BRACKET
    # The frame: seat stays and chain stays to the back axle, the seat tube,
    # top tube, head tube and down tube, and the fork to the front axle.
    b.line(line(REAR, SEAT, HEAD_TOP, HEAD_LOW, BRACKET, REAR), part='frame')
    b.line(line(BRACKET, (SEAT[0] - 1.5, SEAT[1] - 6)), part='frame')
    b.line(curve(HEAD_LOW, (113.5, 133), (116.5, 143), FRONT), part='frame')
    b.line(k.ring(bx, by, 6.0, 8), part='frame')
    b.line(line(BRACKET, (84.5, 161.0)), part='frame')
    b.line(line((81.0, 162.0), (88.5, 161.2)), part='frame')
    # The saddle on its post.
    b.line(loop((59.5, 96.0), (65, 93.6), (73, 94.6), (79.5, 97.2), (73, 99.2), (62, 99.4),
                corners=(3,)), part='saddle')
    # The handlebar: the stem up from the head tube, the bar swept back.
    b.line(line(HEAD_TOP, (104.0, 97.0)), part='bar')
    b.line(curve((104.0, 97.0), (100.0, 93.8), (94.0, 92.6), BAR_END), part='bar')
    # The basket on its rack: a rim band and three uprights of wicker.
    x0, y0, x1, y1 = BASKET
    b.line(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)), part='basket')
    b.line(line((x0, y0 + 5.2), (x1, y0 + 5.4)), part='basket')
    for x in (122.0, 130.0, 138.0):
        b.line(line((x, y0 + 5.3), (x + 0.2, y1)), part='basket')
    b.line(line(FRONT, (x1 - 3.0, y1)), part='rack')
    b.line(line((x0, y1), (108.0, 114.5)), part='rack')


def _ground(b: SketchBuilder) -> None:
    b.line(curve((0, GROUND), (80, GROUND + 0.3), (160, GROUND)), part='ground')


def _ribbon(b: SketchBuilder) -> None:
    """Everything done: a ribbon tied to the handlebar's end, hanging in a loop."""
    x, y = BAR_END
    when = (('allDone',),)
    b.line(loop((x, y), (x - 3.6, y + 3.8), (x - 2.6, y + 7.6), (x + 0.2, y + 4.2), corners=(0,)),
           when=when, part='ribbon')
    b.line(curve((x, y), (x + 1.4, y + 4.2), (x + 2.6, y + 8.4)), when=when, part='ribbon')


def _streamer(frame: int, child: SketchBuilder) -> None:
    """Start: a ribbon streams back from the handlebar and flutters, three
    shapes in turn."""
    x, y = BAR_END
    wave = (0.0, 1.0, -1.0)[frame % 3]
    pts = [(x, y)]
    for i in range(1, 5):
        t = i / 4
        pts.append((x - 15 * t, y - 7 * t + wave * 2.2 * math.sin(math.pi * 1.5 * t)))
    child.line(curve(*pts), part='ribbon')


def _flowers(b: SketchBuilder, s: dict, *, night: bool) -> None:
    for i, (kind, (x, y), turn) in enumerate(s['flowers']):
        when = (('reward', i), PLANNED)
        part = f'flower:{i}'
        if night:
            b.glow(k.ring(x, y, 11.0, 10), when=when, part=part)
        b.filled(_flower(x, y, turn), when=when, part=part, paper='glint')
        b.line(line((x - 0.5, y - 0.3), (x + 0.5, y + 0.3)), when=when, part=part)
        if kind == 'basket' and y > 80:
            b.line(line((x, y + FLOWER_R - 0.6), (x + 0.6, BASKET[1] + 8)), when=when, part=part)
            b.anchor(i, x, BASKET[1])
        else:
            b.anchor(i, x, y)


# ── compositions ────────────────────────────────────────────────────────────

def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    b.wash(k.wash_of(loop((1, 61), (30, 61), (54, 62), (59, 75), (54, 87), (60, 99), (55, 112),
                          (46, 124), (32, 129), (19, 125), (6, 130), (1, 120), (3, 90)), dx=2.0, dy=1.5),
           part='ivy')
    _wall(b, night=False)
    _ivy(b)
    _ground(b)
    _bike(b)
    # The hour.
    k.sun(b, r.fork('sun-m'), 22.0, 24.0, 5.6, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 82.0, 16.0, 5.8, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 138.0, 22.0, 5.6, when=(k.AFTERNOON,))
    k.low_sun(b, r.fork('sun-d'), 20.0, COPING - 0.2, 6.5, when=(k.DUSK,))
    mx, my = s['moon_spot']
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    k.stars(b, r.fork('late-stars'), 3, (40, 6, 152, 50),
            avoid=((mx, my, 14), *((x, y, w * 0.6 + 4) for x, y, w in CLOUDS)),
            when=(k.LATE,), part='star')
    for level, (x, y, w) in enumerate(CLOUDS, start=2):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level - 1}')
    _ribbon(b)
    _flowers(b, s, night=False)
    b.ambient(1.0, (('focus',),), _streamer)


def _lamp(b: SketchBuilder) -> None:
    """The street lamp: a post up the right edge, its neck curving over the
    wall to a hooded head."""
    lx, ly = LAMP
    b.glow(poly((lx - 6, ly + 6), (lx + 6, ly + 6), (158, GROUND), (82, GROUND)), part='lamp')
    b.glow(k.ring(lx, ly + 5, 14.0, 10), part='lamp')
    b.line(line((POST_X, GROUND + 0.4), (POST_X + 0.2, 26.0)), part='lamp')
    b.line(curve((POST_X + 0.2, 26.0), (155.0, 17.5), (148.0, 15.0), (lx, ly - 7.5)), part='lamp')
    b.line(loop((lx - 2.6, ly - 7.5), (lx + 2.6, ly - 7.5), (lx + 7.0, ly + 1.5), (lx - 7.0, ly + 1.5),
                corners=(0, 1, 2, 3)), part='lamp')
    b.line(curve((lx - 3.2, ly + 1.8), (lx, ly + 5.0), (lx + 3.2, ly + 1.8)), part='lamp')


# Where the moths flutter round the lamp, clockwise: three at a time, a step
# round each frame.
MOTH_STATIONS = tuple((LAMP[0] + 17 * math.cos(math.radians(a)), LAMP[1] + 17 * math.sin(math.radians(a)))
                      for a in (75, 110, 145, 180, 215, 250))


def _moths(frame: int, child: SketchBuilder) -> None:
    for j in range(3):
        x, y = MOTH_STATIONS[(frame + 2 * j) % 6]
        flap = 1.0 if (frame + j) % 2 else 0.6
        child.line(loop((x, y), (x - 3.2, y - 2.6 * flap), (x - 3.4, y + 1.0), (x, y),
                        (x + 3.4, y + 1.0), (x + 3.2, y - 2.6 * flap), corners=(0, 3)), part='moth')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _lamp(b)
    mx, my = s['moon_spot']
    clouds = k.moon(b, mx, my, 7.0, clouds=2)
    k.stars(b, r.fork('stars'), 3, (40, 6, 118, 50),
            avoid=((mx, my, 20), *clouds, (LAMP[0], LAMP[1], 30)), part='star')
    _wall(b, night=True)
    _ivy(b)
    _ground(b)
    _bike(b)
    _ribbon(b)
    _flowers(b, s, night=True)
    b.ambient(1.0, (('focus',),), _moths)
