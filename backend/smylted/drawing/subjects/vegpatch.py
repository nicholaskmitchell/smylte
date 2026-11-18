"""A vegetable patch.

Day: a raised bed of soil in front of a fence of posts and a rail, three cane
wigwams standing in it, a vine winding up each with its two leaves, and a
trowel stuck in the soil at the right end. Each finished task ripens a coral
tomato on a vine, hanging under one of its swings out to an outer cane, the
first few spread across the three; Start sends a bee looping through the sky;
everything done sets a basket of tomatoes on the ground in front of the bed; a
day with nothing planned leaves the soil turned in three ridges with a seed
marker in each, no canes; overdue work sprouts a weed at the bed's left end,
then a second, then brings a cloud. The sun crosses the sky with the hour,
sits low and small at the right at dusk, and late at night is an ink moon.

Night: the same bed under the moon, whose glow is the light, and a hedgehog
on the ground in front of it. Each finished task lights a firefly above the
canes; everything done hangs a lantern from the middle wigwam's tie; Start
sets the hedgehog sniffing; overdue work brings a cloud beside the moon, a
second beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date
from functools import cache

from ..pen import PEN, WOBBLE, Stroke, curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

# The fence across the back: its posts (middles), their tops and feet, and
# the rail, high on the posts so the tomatoes hang below it. The posts stand
# at the ends and in the air between the wigwams, never behind one.
POSTS = (4.0, 59.5, 101.0, 156.0)
POST_W = 2.2                   # half a post's width
POST_TOP, POST_FOOT = 69.5, 100.0
RAIL_Y = 76.0
# The raised bed: its sides, the top edge, the board seam and the bottom; the
# soil heaps a little above the top edge.
BED = (10.0, 150.0)
BED_TOP, SEAM, BED_FOOT = 150.0, 161.0, 172.0
HEAP = 5.2
# The wigwams: where they stand, the tie, and their canes' feet from the
# middle (measured where the canes would meet y 150): two splayed legs and a
# third between them, set a little to one side.
WIGWAMS = (40.0, 80.0, 120.0)
TIE_Y = 58.0
TIP = 7.0                       # how far the canes run on above the tie
SPLAY = 0.2                     # and how far apart, of their feet's: a tied bundle
FEET = (-11.5, 4.0, 11.5)
# The vine: planted at the foot of one outer cane, it winds up the wigwam in
# two turns, swinging out a little past the outer canes, and ends at its last
# swing, below the rail.
VINE_FOOT = BED_TOP - HEAP - 1.0
VINE_TOP = 76.5
VINE_TURN = (VINE_FOOT - VINE_TOP) / 2
VINE_OUT = 2.5
# The side (-1 left, 1 right) of each wigwam's first swing above its foot,
# where its lowest tomato hangs: away from the weeds by the soil.
FIRST = (-1, 1, 1)
# A tomato under each of the vine's four swings, from the bottom: how far
# below the swing its top hangs and how far out past it. The lowest keeps
# clear of the soil; the top one hangs on a short stalk, clear of the rail.
HANG = ((0.0, 0.5), (1.0, 1.0), (1.0, 0.5), (3.9, 0.5))
# Each wigwam's two leaves, on the vine between its tomatoes: (height, side
# against FIRST, angle in degrees pointing right, length).
LEAVES = ((104.0, -1, -20.0, 10.0), (120.0, 1, -20.0, 10.0))
TOMATO_R = 6.5
FIREFLY_R = 6.0
FIREFLY_HALO = 11.0
MOON_R = 6.5
# The clouds beside the night's moon, in its radii: both keep to the top of
# the sky, leaving the air over the canes to the fireflies.
CLOUD_1 = (-3.6, -0.2)
CLOUD_2 = (-7.6, -0.4)
PLANNED = (('planned',),)
# Paper between two marks' ink: a pen and the wobble of both.
CLEAR = PEN + 2 * WOBBLE

# Overdue weather by day: (x, y, width), clear of every sun and the bee.
DAY_CLOUD = (46.0, 22.0, 24.0)
BEE_BOX = (60.0, 10.0, 110.0, 36.0)
WEEDS = (15.5, 59.0)
LANTERN = (91.5, 65.0, 4.4)
HOG = (131.0, 192.0)            # the hedgehog's middle, on the ground


class VegetablePatch:
    id = 'vegpatch'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('cane', 'tie'), ('cane', 'soil'), ('cane', 'rail'), ('cane', 'post'),
        ('vine', 'cane'), ('vine', 'tie'), ('vine', 'soil'), ('vine', 'rail'), ('vine', 'post'),
        ('tomato', 'vine'), ('leaf', 'vine'), ('leaf', 'cane'), ('leaf', 'post'),
        ('rail', 'post'), ('soil', 'bed'), ('trowel', 'soil'), ('trowel', 'bed'),
        ('weed', 'soil'), ('weed', 'bed'), ('marker', 'soil'), ('crop', 'basket'),
        ('lantern', 'tie'), ('lantern', 'cane'), ('nose', 'hedgehog'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


# ── geometry ────────────────────────────────────────────────────────────────

def _soil_y(x: float) -> float:
    """The soil's surface at x: heaped HEAP above the bed's top edge, down to
    it at the bed's ends."""
    x0, x1 = BED
    u = min(1.0, max(0.0, (x - x0 - 1) / 11), max(0.0, (x1 - 1 - x) / 11))
    u = u * u * (3 - 2 * u)
    return BED_TOP - HEAP * u


def _cane_x(cx: float, foot: float, y: float) -> float:
    """A cane's x at height y: through the tie, toward its foot at y 150."""
    return cx + foot * (y - TIE_Y) / (BED_TOP - TIE_Y)


def _cane_foot(cx: float, foot: float) -> tuple[float, float]:
    """Where a cane meets the soil."""
    y = BED_TOP
    for _ in range(4):
        y = _soil_y(_cane_x(cx, foot, y)) + 0.6
    return (_cane_x(cx, foot, y), y)


def _ridge_y(x: float) -> float:
    """Nothing planned: the turned soil, three ridges along the bed."""
    x0, x1 = BED
    u = (x - x0) / (x1 - x0) * 3
    return BED_TOP - 6.5 * math.sin(math.pi * (u % 1.0)) ** 0.8


@cache
def _vine_samples(vine: Stroke) -> tuple:
    # Each wigwam's vine has fixed geometry. The leaf angles still vary by seed.
    return tuple(k.samples(vine, step=1.0))


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same patch after dark."""
    wigwams = []
    for i, cx in enumerate(WIGWAMS):
        feet = (FEET[0], FEET[1] * r.choice([-1, 1]) + r.uniform(-1.0, 1.0), FEET[2])
        canes = []
        for f in feet:
            # Above the tie the canes cross and run on a little, a bundle
            # tied at the top.
            tip = (cx - SPLAY * f, TIE_Y - TIP)
            canes.append(curve(tip, (cx, TIE_Y), _cane_foot(cx, f), corners=(1,)))
        # The vine: from the foot of the outer cane opposite its first swing,
        # out to each outer cane and back, two turns up the wigwam.
        first = FIRST[i]

        def vine_at(y: float) -> float:
            reach = _cane_x(0.0, FEET[2], y) + VINE_OUT * min(1.0, (VINE_FOOT - y) / 12.0)
            return cx - first * reach * math.cos(2 * math.pi * (VINE_FOOT - y) / VINE_TURN)

        n = 16
        ys = [VINE_FOOT + (VINE_TOP - VINE_FOOT) * j / n for j in range(n + 1)]
        vine = curve(*[(vine_at(y), y) for y in ys])
        # A tomato under each swing, on alternate sides going up.
        stalks = []
        for j, (below, past) in enumerate(HANG, start=1):
            sy = VINE_FOOT - j * VINE_TURN / 2
            sx = vine_at(sy)
            side = 1 if sx > cx else -1
            tx, ty = sx + side * past, sy + below + TOMATO_R
            stalk = line((sx, sy), (tx, ty - TOMATO_R)) if below > 2.0 else None
            stalks.append(((tx, ty), stalk, (sx, sy)))
        # Two leaves, their bases on the vine itself.
        on_vine = _vine_samples(vine)
        leaves = []
        for y, side, deg, length in LEAVES:
            x, y = min(on_vine, key=lambda p: abs(p[1] - y))
            if side * first < 0:
                deg = 180.0 - deg
            leaves.append((x, y, length, math.radians(deg + r.uniform(-5, 5))))
        wigwams.append({'cx': cx, 'feet': feet, 'canes': canes, 'vine': vine, 'stalks': stalks,
                        'leaves': leaves})
    slots = [st for w in wigwams for st in w['stalks']]
    centres = [c for c, _, _ in slots]
    order = k.spread(centres, min(centres, key=lambda p: (p[1], p[0])))
    by_centre = {c: (stalk, a) for c, stalk, a in slots}
    return {
        'wigwams': wigwams,
        'slots': [(c, *by_centre[c]) for c in order],
        'moon_spot': (138.0 + r.uniform(-1.5, 1.5), 18.0 + r.uniform(-0.5, 0.5)),
    }


# ── the shared picture ──────────────────────────────────────────────────────

def _bed_outline():
    # Ruled, not bowed: the soil and the canes' feet sit just above its top.
    x0, x1 = BED
    return loop((x0, BED_TOP), (x1, BED_TOP), (x1, BED_FOOT), (x0, BED_FOOT), corners=(0, 1, 2, 3))


def _rail_y(x: float) -> float:
    """The rail's gentle sag between the end posts."""
    return RAIL_Y + 0.4 * math.sin(math.pi * (x - POSTS[0]) / 76.0) ** 2


def _fence(b: SketchBuilder, s: dict) -> None:
    for x in POSTS:
        b.line(line((x - POST_W, POST_FOOT), (x - POST_W, POST_TOP + 1.6), (x, POST_TOP),
                    (x + POST_W, POST_TOP + 1.6), (x + POST_W, POST_FOOT)), part='post')
    x0, x1 = POSTS[0], POSTS[-1]
    b.line(curve(*[(x, _rail_y(x)) for x in (x0, 42.0, 80.0, 118.0, x1)]),
           when=(('nothingPlanned',),), part='rail')
    # The wigwams stand in front of the rail: it stops short of their canes,
    # and of the top tomato hanging just below it.
    ends = [x0]
    for w in s['wigwams']:
        xs = [_cane_x(w['cx'], f, RAIL_Y) + d for f in w['feet'] for d in (-CLEAR, CLEAR)]
        (tx, ty), _, _ = w['stalks'][-1]
        reach = (TOMATO_R + CLEAR) ** 2 - (ty - RAIL_Y - 0.4) ** 2
        if reach > 0:
            xs += [tx - math.sqrt(reach), tx + math.sqrt(reach)]
        ends += [min(xs), max(xs)]
    ends.append(x1)
    for a, c in zip(ends[::2], ends[1::2]):
        n = max(2, round((c - a) / 12.0))
        b.line(curve(*[(a + (c - a) * j / n, _rail_y(a + (c - a) * j / n)) for j in range(n + 1)]),
               when=PLANNED, part='rail')


def _bed(b: SketchBuilder) -> None:
    x0, x1 = BED
    b.line(_bed_outline(), part='bed')
    b.line(curve((x0, SEAM), (80.0, SEAM + 0.4), (x1, SEAM)), part='bed')
    # The soil: heaped when planned, turned in three ridges when not.
    xs = [x0 + 0.5, *range(16, 146, 10), x1 - 0.5]
    b.line(curve(*[(x, _soil_y(x)) for x in xs]), when=PLANNED, part='soil')
    xs = [x0 + (x1 - x0) * j / 12 for j in range(13)]
    b.line(curve(*[(x, _ridge_y(x)) for x in xs], corners=(4, 8)), when=(('nothingPlanned',),),
           part='soil')
    # Nothing planned: a seed marker in each ridge, a stick and its flag.
    for cx in WIGWAMS:
        base = _ridge_y(cx)
        b.line(line((cx, base + 0.4), (cx + 0.4, 128.0)), when=(('nothingPlanned',),), part='marker')
        b.line(poly((cx + 0.4, 128.0), (cx + 9.0, 128.4), (cx + 8.8, 134.4), (cx + 0.4, 134.2)),
               when=(('nothingPlanned',),), part='marker')


def _trowel(b: SketchBuilder) -> None:
    """A trowel stuck in the soil at the bed's right end, leaning out."""
    a = math.radians(32)
    ca, sa = math.cos(a), math.sin(a)
    base = (141.0, _soil_y(141.0) + 1.0)

    def at(u: float, v: float):
        # u up the trowel's axis, v across it.
        return (base[0] + u * sa + v * ca, base[1] - u * ca + v * sa)

    b.line(curve(at(0, -3.4), at(4.0, -3.6), at(8.0, -2.4), at(10.0, 0.0), at(8.0, 2.4),
                 at(4.0, 3.6), at(0, 3.4), corners=(3,)), part='trowel')
    b.line(line(at(10.0, 0.0), at(12.6, 0.0)), part='trowel')
    b.line(loop(at(12.6, -1.5), at(19.4, -1.6), at(19.4, 1.6), at(12.6, 1.5), corners=(0, 1, 2, 3)),
           part='trowel')


def _leaf(x: float, y: float, length: float, a: float):
    """A leaf whose base is at (x, y) (`k.leaf` starts its outline a little
    out along its stalk)."""
    back = 0.14 * length
    return k.leaf(x - back * math.cos(a), y - back * math.sin(a), length, a)


def _tie(cx: float):
    """The twine round the canes where they cross."""
    return curve((cx - 2.6, TIE_Y - 1.0), (cx, TIE_Y + 1.4), (cx + 2.6, TIE_Y - 1.0))


def _day_cane(b: SketchBuilder, cane, tomatoes: list) -> None:
    """Hide the cane directly behind each tomato when its reward is lit."""
    tip, tie, foot = cane.points
    length = math.dist(tie, foot)
    vx, vy = (foot[0] - tie[0]) / length, (foot[1] - tie[1]) / length
    # A small overlap at the joins keeps an unlit cane continuous as it boils.
    overlap = 0.7
    radius = TOMATO_R + CLEAR + overlap
    cuts = []
    for (x, y), reward in tomatoes:
        dx, dy = x - tie[0], y - tie[1]
        d_sq = radius**2 - (dx * vy - dy * vx)**2
        if d_sq <= 0:
            continue
        along, reach = dx * vx + dy * vy, math.sqrt(d_sq)
        start, end = max(0.0, along - reach), min(length, along + reach)
        if start < end:
            cuts.append((start, end, reward))
    if not cuts:
        b.line(cane, when=PLANNED, part='cane')
        return

    def at(distance: float):
        return (tie[0] + vx * distance, tie[1] + vy * distance)

    edges = sorted({0.0, length, *(edge for start, end, _ in cuts for edge in (start, end))})
    segments = []
    for start, end in zip(edges, edges[1:]):
        middle = (start + end) / 2
        # The first earned tomato covering this piece hides it for good.
        reward = min((reward for lo, hi, reward in cuts if lo < middle < hi), default=None)
        if segments and segments[-1][2] == reward:
            start = segments.pop()[0]
        segments.append((start, end, reward))
    for start, end, reward in segments:
        first = at(max(0.0, start - overlap))
        last = at(min(length, end + overlap))
        points = (tip, first, last) if start == 0.0 else (first, last)
        when = PLANNED if reward is None else (*PLANNED, ('unlit', reward))
        b.line(line(*points), when=when, part='cane')


def _wigwams(b: SketchBuilder, s: dict, *, night: bool) -> None:
    rewards = {centre: i for i, (centre, _, _) in enumerate(s['slots'])}
    for w in s['wigwams']:
        tomatoes = [(centre, rewards[centre]) for centre, _, _ in w['stalks']]
        for cane in w['canes']:
            if night:
                b.line(cane, when=PLANNED, part='cane')
            else:
                _day_cane(b, cane, tomatoes)
        b.line(_tie(w['cx']), when=PLANNED, part='tie')
        b.line(w['vine'], when=PLANNED, part='vine')
        for x, y, length, a in w['leaves']:
            # No stalk of its own: the leaf's base sits on the vine.
            b.line(_leaf(x, y, length, a), when=PLANNED, part='leaf')


def _scene(b: SketchBuilder, s: dict, *, night: bool) -> None:
    b.wash(k.wash_of(_bed_outline(), inset=0.96, dx=3.0, dy=2.5), part='bed')
    _fence(b, s)
    _bed(b)
    _trowel(b)
    _wigwams(b, s, night=night)


# ── day ─────────────────────────────────────────────────────────────────────

def _in_box(p, box, margin: float) -> bool:
    x0, y0, x1, y1 = box
    return x0 - margin <= p[0] <= x1 + margin and y0 - margin <= p[1] <= y1 + margin


def _sky_day(b: SketchBuilder, s: dict, r: Rng) -> None:
    """The hour, left and right of the bee's patch of sky."""
    k.sun(b, r.fork('sun-m'), 16, 18, 5.2, when=(k.MORNING,), rays=5)
    k.sun(b, r.fork('sun-n'), 126, 14, 5.6, when=(k.MIDDAY,), rays=5)
    k.sun(b, r.fork('sun-a'), 143, 24, 5.4, when=(k.AFTERNOON,), rays=5)
    # Dusk: the fence rail has canes on it, so the sun sits low and small in
    # the sky's bottom right corner, with no horizon.
    k.sun(b, r.fork('sun-d'), 146, 33, 3.8, when=(k.DUSK,), rays=5, ray_gap=2.4, ray_len=2.8)
    mx, my = s['moon_spot']
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    cx, cy, cw = DAY_CLOUD
    k.stars(b, r.fork('late-stars'), 3, (6, 5, 154, 38),
            avoid=((mx, my, 13), (cx, cy, cw * 0.5 + 3)),
            ok=lambda p: not _in_box(p, BEE_BOX, 1.0), when=(k.LATE,), part='star')
    k.cloud(b, cx, cy, cw, when=(('overdue', 3),), part='cloud:1')


def _weeds(b: SketchBuilder) -> None:
    """Overdue work: a weed at the bed's left end, then a second."""
    for level, x in enumerate(WEEDS, start=1):
        y = _soil_y(x) + 0.6
        when = (('overdue', level),)
        b.line(curve((x, y), (x + 0.6, y - 5.0), (x - 0.4, y - 10.0)), when=when, part='weed')
        for dx, top in ((-1, 6.5), (1, 4.0)):
            b.line(line((x + 0.3, y - top + 1.0), (x + dx * 3.4, y - top - 2.2),
                        (x + dx * 2.0, y - top + 0.6)), when=when, part='weed')


def _basket(b: SketchBuilder) -> None:
    """Everything done: a basket of tomatoes on the ground in front of the
    bed's left end."""
    when = (('allDone',),)
    x0, x1, rim, foot = 13.0, 49.0, 183.0, 196.5
    b.line(poly((x0, rim), (x1, rim), (x1 - 3.0, foot), (x0 + 3.0, foot)), when=when, part='basket')
    b.line(curve((x0 + 1.6, 189.6), (31.0, 189.9), (x1 - 1.6, 189.6)), when=when, part='basket')
    for cx, rr in ((21.5, 5.0), (31.0, 5.6), (40.5, 5.0)):
        # Each a dome above the rim: the rest is in the basket.
        cy = rim + 1.0
        half = math.sqrt(rr * rr - 1.0)
        a0 = math.atan2(-1.0, -half)
        a1 = math.atan2(-1.0, half)
        if a1 < a0:
            a1 += 2 * math.pi
        arc = [(cx + rr * math.cos(a0 + (a1 - a0) * j / 6), cy + rr * math.sin(a0 + (a1 - a0) * j / 6))
               for j in range(7)]
        b.filled(loop(*arc, corners=(0, 6)), when=when, part='crop', paper='glint')


def _bee(frame: int, child: SketchBuilder) -> None:
    """Start: a bee loops through its patch of sky, a figure of eight."""
    t = 2 * math.pi * frame / 6
    x, y = 85.0 + 15.0 * math.sin(t), 23.0 + 5.0 * math.sin(2 * t)
    heading = math.atan2(10.0 * math.cos(2 * t), 15.0 * math.cos(t))
    face = 1 if math.cos(t) >= 0 else -1
    tilt = 0.25 * math.sin(heading) * face
    child.line(ellipse(x, y, 5.2, 3.4, n=8, rot=tilt), part='bee')
    for dx in (-1.3, 1.4):
        child.line(line((x + dx - 0.3, y - 2.9), (x + dx + 0.3, y + 2.9)), part='bee')
    # Two wings, a loop each, rising from its back.
    child.line(loop((x - 0.6, y - 3.0), (x - 6.0, y - 7.4), (x - 2.0, y - 9.2), corners=(0,)), part='bee')
    child.line(loop((x + 0.6, y - 3.0), (x + 2.4, y - 9.2), (x + 6.2, y - 7.0), corners=(0,)), part='bee')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _sky_day(b, s, r)
    _scene(b, s, night=False)
    _weeds(b)
    _basket(b)
    for i, ((x, y), stalk, (ax, ay)) in enumerate(s['slots']):
        when = (('reward', i), *PLANNED)
        if stalk is not None:
            b.line(stalk, when=when, part='vine')
        k.fruit(b, x, y, TOMATO_R, when=when, part=f'tomato:{i}')
        b.anchor(i, ax, ay)
    b.ambient(1.0, (('focus',),), _bee)


# ── night ───────────────────────────────────────────────────────────────────

def _cloud_keepout(cx: float, cy: float, w: float, margin: float) -> list:
    """Circles round a three-bump cloud's ink (`k.cloud`'s geometry), each
    widened by `margin`: the cloud itself, not the whole box round it."""
    h = w * 0.36
    base = cy + h * 0.45
    bumps = ((-0.27, 0.18, 0.8), (0.0, 0.22, 1.0), (0.27, 0.16, 0.6))
    out = [(cx + u * w, base - h * 0.62 * hk, ru * w + margin) for u, ru, hk in bumps]
    out += [(cx + w * (-0.43 + 0.86 * j / 6), base, margin) for j in range(7)]
    return out


def _sparse(pts: list, step: float) -> list:
    """`pts` thinned to about `step` apart: `samples` keeps a point on every
    piece of a spline, so a small closed shape gives dozens."""
    out = [pts[0]]
    for p in pts[1:]:
        if math.dist(p, out[-1]) >= step:
            out.append(p)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _hedgehog(b: SketchBuilder) -> None:
    """A hedgehog on the ground in front of the bed's right end, facing left:
    a dome of spines from its rump over to its brow, its belly and feet, and
    an eye. The snout is the nose's."""
    hx, hy = HOG
    spines = []
    for j in range(11):
        a = math.radians(-4 - 148 * j / 10)
        rx, ry = (12.0, 10.5) if j % 2 else (9.0, 7.2)
        spines.append((hx + 2.0 + rx * math.cos(a), hy + 1.0 + ry * math.sin(a)))
    b.line(curve(*spines, corners=tuple(range(1, 10))), part='hedgehog')
    brow = spines[-1]
    b.line(curve((hx - 8.2, hy + 2.6), (hx + 2.0, hy + 3.2), (spines[0][0] + 0.4, spines[0][1] + 0.6)),
           part='hedgehog')
    for dx in (-4.0, 6.0):
        b.line(line((hx + dx, hy + 3.0), (hx + dx - 0.8, hy + 5.4)), part='hedgehog')
    b.line(k.ring(brow[0] - 2.4, brow[1] + 1.6, 0.7, 5), part='hedgehog')


def _nose(child: SketchBuilder, shape: int, *, when: tuple = ()) -> None:
    """The hedgehog's snout from its brow to the dot of its nose and back
    under to its chin: down, level, up."""
    hx, hy = HOG
    lift, reach = ((1.6, 0.0), (0.0, 1.0), (-1.8, 0.4))[shape]
    a = math.radians(-152)
    brow = (hx + 2.0 + 9.0 * math.cos(a), hy + 1.0 + 7.2 * math.sin(a))
    tip = (hx - 15.0 - reach, hy + 0.4 + lift)
    chin = (hx - 8.2, hy + 2.6)
    child.line(curve(brow, (brow[0] - 4.0, brow[1] + 1.2 + lift * 0.3), tip, chin, corners=(2,)),
               when=when, part='nose')
    child.line(k.ring(tip[0] - 0.2, tip[1], 0.8, 5), when=when, part='nose')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    mx, my = s['moon_spot']
    k.moon(b, mx, my, MOON_R, clouds=2, first=CLOUD_1, second=CLOUD_2)
    _scene(b, s, night=True)
    _hedgehog(b)
    _nose(b, 1, when=(('idle',),))
    # Everything done: a lantern hangs from the middle wigwam's tie.
    lx, ly, lr = LANTERN
    done = (('allDone',), *PLANNED)
    top = ly - lr - 1.6
    b.line(curve((WIGWAMS[1] + 1.2, TIE_Y + 0.4), (lx - 5.0, TIE_Y + 0.6), (lx, top)), when=done,
           part='lantern')
    # Its cap, so it reads as a lantern, not one more firefly.
    cap = line((lx - 3.0, ly - lr + 0.6), (lx - 1.4, top), (lx + 1.4, top), (lx + 3.0, ly - lr + 0.6))
    b.line(cap, when=done, part='lantern')
    k.glow_dot(b, lx, ly, lr, halo=9.0, when=done, part='lantern')

    # Fireflies above and between the wigwams, clear of every line up there.
    w = 3.4 * max(MOON_R, k.MOON_CLOUD / 3.4)
    ink = [st for wg in s['wigwams'] for st in wg['canes']]
    ink += [_leaf(x, y, length, a) for wg in s['wigwams'] for x, y, length, a in wg['leaves'] if y < 75]
    ink += [_tie(cx) for cx in WIGWAMS]
    ink += [line((lx - 5.0, TIE_Y), (lx, top)), cap, k.ring(lx, ly, lr)]
    ink += [line((x, POST_TOP), (x, POST_TOP + 4)) for x in POSTS]
    clear = FIREFLY_R + CLEAR + 0.4
    avoid = [(x, y, clear + 0.3) for st in ink for x, y in _sparse(k.samples(st, step=4.5), 4.5) if y < 75]
    clouds = [(mx + u * MOON_R, my + v * MOON_R) for u, v in (CLOUD_1, CLOUD_2)]
    for cx_, cy_ in clouds:
        avoid += _cloud_keepout(cx_, cy_, w, clear)
    avoid.append((mx, my, MOON_R + clear + 1.0))

    def ok(p) -> bool:
        # Each halo in the frame, as far as the pen's wobble, and every
        # firefly a pen and both wobbles above the rail.
        return (FIREFLY_HALO - 1.0 <= p[0] <= 161.0 - FIREFLY_HALO
                and 14.0 <= p[1] <= RAIL_Y - FIREFLY_R - CLEAR - 0.4)

    pts = k.scatter_all(r.fork('fireflies'), k.REWARDS, 80.0, 41.0, 100.0, 34.0, 18.5,
                        avoid=avoid, ok=ok, floor=k.apart(FIREFLY_R))
    flies = k.spread(pts, (WIGWAMS[1], 30.0))
    k.stars(b, r.fork('stars'), 3, (6, 4, 154, 40),
            avoid=((mx, my, 16), *((cx_, cy_, 0.5 * w + 4.0) for cx_, cy_ in clouds),
                   *((x, y, FIREFLY_R + 4.0) for x, y in flies)),
            part='star')
    for i, (x, y) in enumerate(flies):
        k.glow_dot(b, x, y, FIREFLY_R, halo=FIREFLY_HALO, when=(('reward', i), *PLANNED),
                   part=f'firefly:{i}', glass=False)
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), lambda f, child: _nose(child, (0, 1, 2, 1, 0, 2)[f]))
