"""A kite.

Day: a kite flies high over a hill, its string sagging down to a fence post on
the crest, its long tail an S across the sky. Each finished task ties a coral
bow on the tail, the first few spread along it from the kite; Start sends wind
streaks past the tail; everything done lifts the kite above two clouds; a day
with nothing planned leaves the kite lying in the grass, its string slack to
the post; overdue work brings a small cloud, and one more at each further
level. The sun crosses the sky with the hour, sets on the hill, and late at
night is an ink moon.

Night: the same kite tethered under the moon, whose glow is the light. Each
finished task hangs a lit lantern on the tail; everything done lights the
whole tail and a lamp on the post; overdue work brings a cloud beside the
moon, a second a step beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

HILL = ((1.0, 150.0), (36.0, 139.0), (70.0, 132.0), (116.0, 136.5), (159.0, 146.0))
# The grass: a soft blob of colour with no outline, under the crest and across
# the hill line, clear of every edge (centre x, centre y, half-width, half-depth).
GRASS = (80.0, 144.0, 62.0, 14.0)
POST_X = 34.0
POST_TOP = 116.0
SAG = 2.0
BOW_R = 6.3               # half a bow's width
LANTERN_R = 6.0
MOON_R = 7.0              # its glow (a ring 2.4 radii round) is the night's light
# The tail's S: the top of its first turn, the radius of both turns (two
# lanterns either side of an apex keep apart), the bows' spacing along it
# (two level bows on one run never touch), and how much the runs ripple.
TURN_TOP = (141.0, 75.5)
TURN_R = 11.5
BOW_STEP = 19.0
RIPPLE = 1.4
FIRST_BOW = 14.0          # the nearest a bow comes to the kite, along the tail
PLANNED = (('planned',),)

# Weather, kept clear of every sun, the kite, its string and its tail:
# (centre x, centre y, width).
OVERDUE_CLOUDS = ((36.0, 46.0, 24.0), (68.0, 41.0, 22.0), (16.0, 68.0, 22.0))
ABOVE_CLOUDS = ((52.0, 76.0, 26.0), (24.0, 98.0, 28.0))


class Kite:
    id = 'kite'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('kite', 'spar'), ('kite', 'string'), ('kite', 'tail'), ('string', 'post'),
        ('post', 'hill'), ('post', 'rail'), ('bow', 'tail'), ('lantern', 'tail'),
        ('postlamp', 'post'),
        # The setting sun rests on the hill, and the slack string lies across
        # the ground line to reach the post.
        ('sun', 'hill'), ('string', 'hill'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _arc(pts: list) -> list[float]:
    out = [0.0]
    for p, q in zip(pts, pts[1:]):
        out.append(out[-1] + math.dist(p, q))
    return out


def _at(pts: list, arc: list[float], s: float):
    """The point at arc length `s` along `pts`, whose running lengths are `arc`."""
    i = max(1, min(len(pts) - 1, next((j for j, a in enumerate(arc) if a >= s), len(arc) - 1)))
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    t = min(1.0, max(0.0, (s - arc[i - 1]) / max(1e-9, arc[i] - arc[i - 1])))
    return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def _hill_y(x: float, hill: list) -> float:
    """The hill line's height at x (the pen's spline, not its vertices)."""
    best = min(hill, key=lambda p: abs(p[0] - x))
    return best[1]


def _tail(bottom) -> tuple[list, list[float]]:
    """The tail: off the tip and out to the right, back left under the kite,
    and right again low over the hill, an S across the sky; and where its
    bows go, evenly spaced along it.

    Each turn's apex falls halfway between two bows: one bow on the apex
    itself would sit too close to its neighbours coming in and going out of
    the turn. Only the first stretch, from the kite to the first turn, changes
    with the kite; the first bow moves along it to keep that rhythm."""
    r_ = TURN_R
    t1 = TURN_TOP
    c1 = (t1[0], t1[1] + r_)
    y2, y3 = t1[1] + 2 * r_, t1[1] + 4 * r_
    left = t1[0] - (5 * BOW_STEP - math.pi * r_)
    c2 = (left, t1[1] + 3 * r_)

    bx, by = bottom
    h0, h1 = (bx + 5, by + 11), (t1[0] - 12, t1[1])
    pts = []
    for i in range(41):
        t = i / 40
        u = 1 - t
        pts.append((u ** 3 * bx + 3 * u * u * t * h0[0] + 3 * u * t * t * h1[0] + t ** 3 * t1[0],
                    u ** 3 * by + 3 * u * u * t * h0[1] + 3 * u * t * t * h1[1] + t ** 3 * t1[1]))
    n = 24
    turn1 = [(c1[0] + r_ * math.cos(-math.pi / 2 + math.pi * i / n),
              c1[1] + r_ * math.sin(-math.pi / 2 + math.pi * i / n)) for i in range(1, n + 1)]
    pts += turn1
    apex1 = _arc(pts)[-1] - _arc(turn1)[-1] / 2
    # The long runs ripple a little in the wind, two whole waves across the
    # middle one, so it still meets both turns level.
    pts += [(t1[0] + (left - t1[0]) * i / 24, y2 + RIPPLE * math.sin(2 * math.pi * 2 * i / 24))
            for i in range(1, 25)]
    turn2 = [(c2[0] + r_ * math.cos(-math.pi / 2 - math.pi * i / n),
              c2[1] + r_ * math.sin(-math.pi / 2 - math.pi * i / n)) for i in range(1, n + 1)]
    pts += turn2
    apex2 = _arc(pts)[-1] - _arc(turn2)[-1] / 2
    # Five bows between the apexes: the ripple lengthens the run a little, so
    # the spacing is measured, not taken as BOW_STEP.
    step = (apex2 - apex1) / 5
    m = int((apex1 - FIRST_BOW) / step - 0.5)
    start = apex1 - step * (m + 0.5)
    after = k.REWARDS - (m + 1) - 5                   # bows past the second apex
    reach = (after - 0.5) * step - math.pi * r_ / 2 + 5.0
    pts += [(left + reach * i / 24, y3 - RIPPLE * math.sin(2 * math.pi * reach / 28 * i / 24))
            for i in range(1, 25)]
    return pts, [start + i * step for i in range(k.REWARDS)]


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same kite after dark."""
    cx, cy = 104 + r.uniform(-6, 2), 46 + r.uniform(-6, 0)
    top, bottom = (cx, cy - 17), (cx, cy + 17)
    left, right = (cx - 13, cy - 5), (cx + 13, cy - 5)
    # The string is tied a little up the kite's lower left edge, so it leaves
    # the kite clear of the tail that hangs from the tip.
    ex, ey = left[0] - bottom[0], left[1] - bottom[1]
    el = math.hypot(ex, ey)
    tie = (bottom[0] + 6 * ex / el, bottom[1] + 6 * ey / el)
    post_top = (POST_X + 0.3, POST_TOP)
    string = []
    for i in range(6):
        t = i / 5
        string.append((tie[0] + (post_top[0] - tie[0]) * t,
                       tie[1] + (post_top[1] - tie[1]) * t + SAG * 4 * t * (1 - t)))

    trace, spots = _tail(bottom)
    arc = _arc(trace)
    # Drawn through points about six units apart along the path.
    keep, last = [trace[0]], 0.0
    for p, a in zip(trace, arc):
        if a - last >= 6.0:
            keep.append(p)
            last = a
    if keep[-1] != trace[-1]:
        keep.append(trace[-1])
    tail = curve(*keep)
    bows = [(_at(trace, arc, a), math.radians(r.uniform(-8, 8))) for a in spots]
    order = k.spread([p for p, _ in bows], bottom)
    by_point = dict(bows)
    slots = [(p, by_point[p]) for p in order]

    hill = k.samples(curve(*HILL), step=1.0)
    return {
        'kite': (cx, cy), 'corners': (top, right, bottom, left), 'string': string,
        'tail': tail, 'trace': trace, 'slots': slots, 'hill': hill,
        'grass': k.blob(*GRASS, r.fork('grass'), n=12, wobble=0.05),
        'moon_spot': (22 + r.uniform(-2, 2), 24 + r.uniform(-2, 2)),
    }


def _ground(b: SketchBuilder, s: dict) -> None:
    hill = s['hill']
    b.wash(s['grass'], part='hill')
    b.line(curve(*HILL), part='hill')
    foot = _hill_y(POST_X, hill)
    b.line(line((POST_X - 2.4, foot + 1.2), (POST_X - 2.3, POST_TOP), (POST_X + 2.7, POST_TOP + 0.2),
                (POST_X + 2.6, foot + 1.0)), part='post')
    b.line(line((POST_X - 13, 125.4), (POST_X - 2.4, 125)), part='rail')


def _flying(b: SketchBuilder, s: dict) -> None:
    top, right, bottom, left = s['corners']
    b.line(poly(top, right, bottom, left), when=PLANNED, part='kite')
    # The upright spar stops short of the tip, clear of the string and the tail.
    b.line(line(top, (bottom[0], bottom[1] - 9.5)), when=PLANNED, part='spar')
    b.line(line(left, right), when=PLANNED, part='spar')
    b.line(curve(*s['string']), when=PLANNED, part='string')
    b.line(s['tail'], when=PLANNED, part='tail')


def _grounded(b: SketchBuilder, s: dict) -> None:
    """Nothing planned: the kite lies in the grass on the hill, its string
    slack along the ground to the post."""
    when = (('nothingPlanned',),)
    hill = s['hill']
    cx = 112.0
    cy = _hill_y(cx, hill) + 12.5
    a = math.atan2(_hill_y(cx + 10, hill) - _hill_y(cx - 10, hill), 20)
    # Lying along the slope, a little foreshortened, its nose to the post.
    tip, up, head, down = k.rotate(((cx - 16, cy), (cx + 4, cy - 6.5), (cx + 16, cy), (cx + 4, cy + 6.5)),
                                   (cx, cy), a)
    b.line(poly(tip, up, head, down), when=when, part='kite')
    b.line(line(k.rotate([(cx - 10, cy)], (cx, cy), a)[0], head), when=when, part='spar')
    b.line(line(up, down), when=when, part='spar')
    foot = _hill_y(POST_X, hill)
    pts = [tip]
    for x, dy in ((84, 10.0), (66, 13.5), (50, 9.0)):
        pts.append((x, _hill_y(x, hill) + dy))
    pts.append((POST_X + 2.6, foot - 3.0))
    b.line(curve(*pts), when=when, part='string')


def _bow(p, a):
    """A bow tied on the tail at p: two small triangles meeting at the knot,
    about 13 wide and 10 tall, hanging level, turned a little by a."""
    ca, sa = math.cos(a), math.sin(a)

    def at(u: float, v: float):
        return (p[0] + u * ca - v * sa, p[1] + u * sa + v * ca)

    w = BOW_R
    return poly(at(-w, -5.2), at(-1.6, -2.4), at(1.6, -2.4), at(w, -5.2),
                at(w, 5.2), at(1.6, 2.4), at(-1.6, 2.4), at(-w, 5.2))


def _streaks(frame: int, child: SketchBuilder) -> None:
    """Start: three short streaks of wind blow past the tail, clear of it."""
    for j, (x0, y) in enumerate(((126.0, 44.0), (130.0, 53.0), (124.0, 61.0))):
        x = x0 + ((frame + 2 * j) % 6) * 3.2
        child.line(curve((x, y), (x + 5, y - 1.2), (x + 10, y - 0.4), (x + 14, y + 1.0)), part='wind')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground(b, s)
    # The hour.
    k.sun(b, r.fork('sun-m'), 18, 20, 5.6, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 62, 14, 5.8, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 144, 17, 5.6, when=(k.AFTERNOON,))
    sx = 142.0
    k.low_sun(b, r.fork('sun-d'), sx, _hill_y(sx, s['hill']) + 0.4, 6.0, when=(k.DUSK,))
    mx, my = s['moon_spot']
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    cx, cy = s['kite']
    k.stars(b, r.fork('late-stars'), 3, (8, 6, 152, 26),
            avoid=((mx, my, 14), *((x, y, w * 0.6 + 4) for x, y, w in OVERDUE_CLOUDS)),
            ok=lambda p: math.dist(p, (cx, cy - 17)) > 12 and math.dist(p, (cx, cy - 6)) > 18,
            when=(k.LATE,), part='star')
    # Overdue work: a small cloud a level (parts 3 to 5: the clouds the kite
    # flies above are 1 and 2, and both sets can show at once).
    for level, (x, y, w) in enumerate(OVERDUE_CLOUDS, start=1):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level + 2}')
    # Everything done: the kite flies above the clouds.
    for i, (x, y, w) in enumerate(ABOVE_CLOUDS, start=1):
        k.cloud(b, x, y, w, when=(('allDone',),), part=f'cloud:{i}')
    _flying(b, s)
    _grounded(b, s)
    for i, (p, a) in enumerate(s['slots']):
        b.filled(_bow(p, a), when=(('reward', i), *PLANNED), part=f'bow:{i}')
        b.anchor(i, *p)
    b.ambient(1.0, (('focus',),), _streaks)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground(b, s)
    mx, my = s['moon_spot']
    clouds = k.moon(b, mx, my, MOON_R, clouds=2)
    cx, cy = s['kite']
    k.stars(b, r.fork('stars'), 3, (8, 6, 152, 30), avoid=((mx, my, 20), *clouds),
            ok=lambda p: math.dist(p, (cx, cy - 17)) > 12 and math.dist(p, (cx, cy - 6)) > 18,
            part='star')
    _flying(b, s)
    _grounded(b, s)
    done = (('allDone',), *PLANNED)
    # Everything done: the whole tail lit, and the lamp on the post.
    trace = s['trace']
    side_a, side_b = [], []
    for (x0, y0), (x1, y1) in zip(trace[::6], trace[6::6]):
        d = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / d, (x1 - x0) / d
        side_a.append((x0 + 5 * nx, y0 + 5 * ny))
        side_b.append((x0 - 5 * nx, y0 - 5 * ny))
    b.glow(loop(*side_a, *reversed(side_b)), when=done, part='tail')
    k.glow_dot(b, POST_X + 6.2, 127.0, 3.6, halo=10, when=(('allDone',),), part='postlamp')
    b.line(line((POST_X + 2.6, 122.4), (POST_X + 6.2, 122.4), (POST_X + 6.2, 123.6)),
           when=(('allDone',),), part='postlamp')
    for i, (p, _) in enumerate(s['slots']):
        k.glow_dot(b, *p, LANTERN_R, halo=11, when=(('reward', i), *PLANNED), part=f'lantern:{i}')
        b.anchor(i, *p)
    b.ambient(1.0, (('focus',),), _streaks)
