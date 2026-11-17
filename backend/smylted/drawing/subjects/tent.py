"""A tent in a clearing.

Day: a small A-frame tent pitched between two pines, its door flap rolled back,
guy lines out to pegs either side, and a camp stove with a pot by the right
pine's trunk. Each finished task drops a coral pine cone on the ground in
front of the tent, the first few spread across the clearing from the door;
Start sets steam rising from the pot; everything done leaves a pair of boots
by the door; a day with nothing planned has the tent packed, a rolled bundle
on the ground; overdue work brings a cloud, and one more at each further
level. The sun crosses the sky between the pines' tops with the hour, sits
low late in the day, and late at night is an ink moon.

Night: the same clearing round a small campfire in front of the tent, whose
glow is the light. Each finished task sends up a coral ember, the first few
fanning out from above the fire; Start makes the flames flicker; everything
done lights the tent's door from inside; overdue work brings a cloud beside
the moon, a second a step beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import PEN, WOBBLE, curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

GROUND = ((0.0, 153.4), (40.0, 151.2), (84.0, 150.4), (124.0, 151.0), (160.0, 154.2))
APEX = (84.0, 90.0)
BASE = (58.0, 110.0)          # the tent's feet on the ground
DOOR_TOP = (84.0, 104.0)
DOOR = (70.0, 98.0)           # the door opening's feet
GUY_AT = 0.4                  # how far down each slope the guy lines are tied
PEGS = (51.5, 116.5)
STOVE = (121.5, 135.5, 143.0)  # its sides and its top
POT = (124.0, 133.0, 135.0)    # its sides and its rim
# Each pine: its middle, its tip, the foot of its branches, its half-width.
PINES = ((20.0, 30.0, 124.0, 19.0), (143.5, 40.0, 109.0, 16.0))
TRUNK = 2.5
CONE_R = 6.5                  # a cone's reach from its middle
EMBER_R = 5.5
MOON_R = 7.0
FIRE_X = 85.0
FIRE_GAP = (74.0, 96.0)       # at night the ground line stops behind the flames
# Clear of a mark's ink by a pen and the wobble of both.
CLEAR = PEN + 2 * WOBBLE
PLANNED = (('planned',),)

# Weather, a cloud a level, kept clear of every sun: (centre x, centre y, width).
CLOUDS = ((28.0, 13.0, 26.0), (134.0, 14.0, 24.0), (82.0, 46.0, 22.0))


class Tent:
    id = 'tent'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('pine', 'trunk'), ('trunk', 'ground'), ('tent', 'ground'), ('tent', 'door'),
        ('door', 'ground'), ('guy', 'tent'), ('guy', 'peg'), ('guy', 'ground'),
        ('peg', 'ground'), ('stove', 'ground'), ('pot', 'stove'), ('steam', 'pot'),
        ('bundle', 'ground'), ('fire', 'ground'), ('boots', 'ground'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _ground_y(x: float, ground: list) -> float:
    """The ground line's height at x (the pen's spline, not its vertices)."""
    return min(ground, key=lambda p: abs(p[0] - x))[1]


def _pine(cx: float, top: float, foot: float, hw: float):
    """A pine: a tall zigzag triangle of four tiers, each wider than the one
    above, its notches stepping back in toward the trunk."""
    tiers = ((0.3, 0.42), (0.56, 0.62), (0.79, 0.8), (1.0, 1.0))
    right = [(cx, top)]
    for i, (f, w) in enumerate(tiers):
        y = top + (foot - top) * f
        right.append((cx + hw * w, y))
        if i < len(tiers) - 1:
            right.append((cx + hw * w * 0.48, y - 3.0))
    left = [(2 * cx - x, y) for x, y in reversed(right[1:])]
    return poly(*right, *left)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same clearing after dark."""
    ground = k.samples(curve(*GROUND), step=1.0)
    g = lambda x: _ground_y(x, ground)
    pines = [_pine(*p) for p in PINES]
    trunks = [[line((cx + side * TRUNK, foot - 0.4), (cx + side * TRUNK * 1.1, g(cx) + 0.6))
               for side in (-1, 1)] for cx, _, foot, _ in PINES]

    ax, ay = APEX
    left_foot, right_foot = (BASE[0], g(BASE[0]) + 0.4), (BASE[1], g(BASE[1]) + 0.4)
    slopes = [line(APEX, left_foot), line(APEX, right_foot)]
    door_l, door_r = (DOOR[0], g(DOOR[0]) + 0.4), (DOOR[1], g(DOOR[1]) + 0.4)
    # The opening: a straight edge on the left, and on the right the flap,
    # rolled back, bowing out toward the slope.
    door = [line(DOOR_TOP, door_l),
            curve(DOOR_TOP, (DOOR_TOP[0] + 7.5, 122.0), (DOOR_TOP[0] + 12.5, 140.0), door_r)]
    guys, pegs = [], []
    for foot, px, side in ((left_foot, PEGS[0], -1), (right_foot, PEGS[1], 1)):
        at = (ax + (foot[0] - ax) * GUY_AT, ay + (foot[1] - ay) * GUY_AT)
        gy = g(px)
        top = (px - side * 0.9, gy - 4.2)
        guys.append(line(at, top))
        pegs.append(line((px + side * 0.2, gy + 2.0), top))
    panels = [poly(APEX, left_foot, door_l, DOOR_TOP), poly(APEX, DOOR_TOP, door_r, right_foot)]
    tent_ink = [*slopes, *door, *guys, *pegs]
    pine_ink = [*pines, *(t for pair in trunks for t in pair)]

    # The ground's ink, the stove and the pegs, for what lies on the ground.
    sx0, sx1, stop = STOVE
    stove = poly((sx0, g(sx0) + 0.4), (sx0, stop), (sx1, stop), (sx1, g(sx1) + 0.4))

    boots = _boots(g)
    flames = [_flames(i) for i in range(3)]
    logs = _logs()

    # Everything else stands on the ground line or above it: the cones keep
    # clear of the line (and the pegs' points just under it), and so of all of it.
    cone_avoid = tuple((x, y, CONE_R + CLEAR + 0.6)
                       for st in (curve(*GROUND), *pegs) for x, y in k.samples(st, 3.0))

    def cones() -> list:
        cr = r.fork('cones')
        # The ellipse holds the whole strip, so its corners hold cones too.
        pts = k.scatter_all(cr, k.REWARDS, 85, 176, 93, 22, k.apart(CONE_R), avoid=cone_avoid,
                            ok=lambda p: 20 <= p[0] <= 150 and p[1] <= 190,
                            floor=k.apart(CONE_R))
        tilt = cr.fork('tilt')
        return [(p, math.radians(tilt.uniform(-80, 80))) for p in k.spread(pts, (84, 160))]

    side = r.choice([-1, 1])
    moon_spot = (80 + side * (40 + r.uniform(-3, 3)), 22 + r.uniform(-2, 2))

    def embers() -> list:
        clouds = _moon_clouds(moon_spot)
        avoid = (*((x, y, EMBER_R + CLEAR + 0.6)
                   for st in (*tent_ink, *pine_ink, *flames) for x, y in k.samples(st, 3.0)
                   if 38 <= x <= 134 and y <= 152),
                 *((x, y, rr + EMBER_R) for x, y, rr in clouds))
        pts = k.scatter_all(r.fork('embers'), k.REWARDS, FIRE_X, 100, 40, 44, k.apart(EMBER_R), avoid=avoid,
                            ok=lambda p: 50 <= p[0] <= 120 and 60 <= p[1] <= 140,
                            floor=k.apart(EMBER_R))
        return k.spread(pts, (FIRE_X, 140))

    return {
        'ground': ground, 'g': g, 'pines': pines, 'trunks': trunks,
        'slopes': slopes, 'door': door, 'guys': guys, 'pegs': pegs,
        'panels': panels, 'stove': stove, 'boots': boots, 'flames': flames, 'logs': logs,
        'cones': cones, 'embers': embers, 'moon_spot': moon_spot,
        'door_glow': poly(DOOR_TOP, door_l, door_r),
    }


def _moon_clouds(spot) -> list:
    """Where `k.moon` puts its clouds for a moon of MOON_R at `spot`, with the
    reach it returns: so the embers can keep clear before the moon is drawn."""
    cx, cy = spot
    toward = 1 if cx < 80 else -1
    size = max(MOON_R, k.MOON_CLOUD / 3.4)
    reach = 0.5 * 3.4 * size + 4.0
    return [(cx + toward * 3.3 * size, cy + 0.5 * size, reach),
            (cx + toward * 5.2 * size, cy + 2.7 * size, reach)]


def _boots(g) -> list:
    """Everything done: a pair of boots standing in the doorway, heels
    together and toes out. Each is open at the sole, which is the ground."""
    out = []
    for facing in (-1, 1):
        hx = DOOR_TOP[0] + facing * 0.6
        foot = g(hx) + 0.4
        top = foot - 7.0

        def p(dx: float, y: float, hx=hx, facing=facing):
            return (hx + facing * dx, y)

        out.append(line(p(0.0, foot), p(0.0, top), p(3.6, top), p(3.6, foot - 3.2), p(6.0, foot - 2.2),
                        p(6.0, foot)))
    return out


def _logs() -> list:
    """Three logs crossed under the fire."""
    x = FIRE_X
    return [line((x - 10.5, 165.0), (x + 8.0, 158.2)), line((x + 10.5, 165.0), (x - 8.0, 158.2)),
            line((x - 9.0, 162.0), (x + 9.0, 162.4))]


def _flames(shape: int):
    """The fire's flames: one tongue of fire with two tips, leaning a little
    differently in each of three shapes."""
    x = FIRE_X
    (l1, h1), (l2, h2) = (((0.0, 0.0), (0.0, 0.0)), ((-1.2, -1.0), (0.8, 1.2)),
                          ((0.9, 1.0), (-0.6, -1.4)))[shape]
    return loop((x, 160.4), (x - 5.4, 158.0), (x - 6.4, 154.2), (x - 3.6 + l1, 148.6 + h1),
                (x + 0.6, 153.2), (x + 3.8 + l2, 149.8 + h2), (x + 6.4, 154.6), (x + 5.4, 158.2),
                corners=(3, 4, 5))


# ── the shared picture ──────────────────────────────────────────────────────

def _ground(b: SketchBuilder, s: dict, *, gap: tuple[float, float] | None = None) -> None:
    ground = s['ground']
    region = poly(*[(x, y) for x, y in ground[::8]], (159.0, 155.0), (157.0, 194.0), (3.0, 194.0))
    b.wash(k.wash_of(region, dx=1.5, dy=3.0), part='ground')
    if gap is None:
        b.line(curve(*GROUND), part='ground')
        return
    x0, x1 = gap
    for lo, hi in ((0.0, x0), (x1, 160.0)):
        pts = [p for p in ground if lo <= p[0] <= hi]
        b.line(curve(*pts[::18], pts[-1]), part='ground')


def _pines(b: SketchBuilder, s: dict) -> None:
    for i, (pine, trunk) in enumerate(zip(s['pines'], s['trunks'])):
        b.wash(k.wash_of(pine, inset=0.92, dx=2.0, dy=3.0), part='pine')
        b.line(pine, part=f'pine:{i}')
        for t in trunk:
            b.line(t, part=f'trunk:{i}')


def _tent(b: SketchBuilder, s: dict) -> None:
    for panel in s['panels']:
        b.wash(k.wash_of(panel, inset=0.86, dx=2.0, dy=2.0), when=PLANNED, part='tent')
    for st in s['slopes']:
        b.line(st, when=PLANNED, part='tent')
    for st in s['door']:
        b.line(st, when=PLANNED, part='door')
    for guy, peg in zip(s['guys'], s['pegs']):
        b.line(guy, when=PLANNED, part='guy')
        b.line(peg, when=PLANNED, part='peg')


def _bundle(b: SketchBuilder, s: dict) -> None:
    """Nothing planned: the tent is packed, a rolled bundle lying on the ground
    at the left of its pitch, two straps round it."""
    when = (('nothingPlanned',),)
    g = s['g']
    x0, x1 = 42.0, 72.0
    foot = g((x0 + x1) / 2) + 0.4
    top = foot - 11.0
    b.line(loop((x0 + 3, foot), (x0, foot - 5.5), (x0 + 3, top), (x1 - 3, top), (x1, foot - 5.5),
                (x1 - 3, foot), corners=(0, 2, 3, 5)), when=when, part='bundle')
    for x in (x0 + 9.0, x1 - 9.5):
        b.line(line((x, top + 0.2), (x + 0.4, foot - 0.2)), when=when, part='bundle')


def _stove(b: SketchBuilder, s: dict) -> None:
    b.line(s['stove'], part='stove')
    sx0, sx1, stop = STOVE
    b.line(k.ring((sx0 + sx1) / 2, stop + 3.6, 1.1, 6), part='stove')
    px0, px1, rim = POT
    b.line(line((px0, rim), (px0 + 0.4, stop), (px1 - 0.4, stop), (px1, rim)), part='pot')
    b.line(line((px0 - 1.2, rim), (px1 + 1.2, rim)), part='pot')
    b.line(line((px0, rim + 1.6), (px0 - 4.0, rim + 0.8)), part='pot')


def _steam(frame: int, child: SketchBuilder) -> None:
    """Start: steam rises from the pot, drifting a little left, away from the pine."""
    px0, px1, rim = POT
    x, y = (px0 + px1) / 2, rim - 2.0
    phase = 2 * math.pi * frame / 6
    for j, dx in enumerate((-2.6, 2.6)):
        pts = []
        for i in range(6):
            t = i / 5
            sway = math.sin(phase + t * 4 + j * 0.2) * (1.2 + t * 1.8)
            pts.append((x + dx + sway - 6.0 * t * t, y - t * 15.0))
        child.line(curve(*pts), part='steam')


def _cone(x: float, y: float, a: float):
    """A pine cone lying at (x, y), turned by a: an egg about 10 by 13, its
    tip a little pointed, and two rows of scales across it."""
    body = []
    for i in range(12):
        t = 2 * math.pi * i / 12
        ry = 6.5 if i == 0 else 6.2
        body.append((5.6 * math.sin(t), -ry * math.cos(t)))
    scales = [[(-2.4, yy + 1.7), (0.0, yy), (2.4, yy + 1.7)] for yy in (-2.8, 1.8)]
    turn = lambda pts: k.rotate([(x + u, y + v) for u, v in pts], (x, y), a)
    return loop(*turn(body), corners=(0,)), [line(*turn(sc)) for sc in scales]


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground(b, s)
    _pines(b, s)
    # The hour, between the pines' tops.
    k.sun(b, r.fork('sun-m'), 52, 34, 5.2, when=(k.MORNING,), ray_len=3.4)
    k.sun(b, r.fork('sun-n'), 82, 20, 5.4, when=(k.MIDDAY,), ray_len=3.4)
    k.sun(b, r.fork('sun-a'), 112, 32, 5.2, when=(k.AFTERNOON,), ray_len=3.4)
    # Dusk: the gap left of the tent holds a guy line and its peg, so the sun
    # sits low in the sky instead of on the ground.
    k.sun(b, r.fork('sun-d'), 116, 45, 4.0, when=(k.DUSK,), rays=5, ray_gap=2.2, ray_len=2.6)
    mx, my = 58.0, 27.0
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    k.stars(b, r.fork('late-stars'), 3, (8, 5, 152, 48),
            avoid=((mx, my, 14), *((x, y, w * 0.55 + 5) for x, y, w in CLOUDS)),
            ok=lambda p: _clear_of_pines(p, 6.0), when=(k.LATE,), part='star')
    for level, (x, y, w) in enumerate(CLOUDS, start=1):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level}')
    _tent(b, s)
    _bundle(b, s)
    _stove(b, s)
    for boot in s['boots']:
        b.line(boot, when=(('allDone',),), part='boots')
    for i, ((x, y), a) in enumerate(s['cones']()):
        body, scales = _cone(x, y, a)
        when = (('reward', i), *PLANNED)
        b.filled(body, when=when, part=f'cone:{i}')
        # Its scales held still with it, as the seedlings' bud eyes are.
        for sc in scales:
            b.filled(sc, when=when, part=f'cone:{i}')
        b.anchor(i, x, max(p[1] for p in body.points))
    b.ambient(1.0, (('focus',),), _steam)


def _clear_of_pines(p, margin: float) -> bool:
    """True when p is outside both pines' triangles by `margin` or more."""
    for cx, top, foot, hw in PINES:
        if p[1] < top - margin:
            continue
        half = hw * max(0.0, (p[1] - top) / (foot - top))
        if abs(p[0] - cx) < half + margin:
            return False
    return True


def _fire(child: SketchBuilder, shape: int, *, when: tuple = ()) -> None:
    child.line(_flames(shape), when=when, part='fire')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground(b, s, gap=FIRE_GAP)
    _pines(b, s)
    mx, my = s['moon_spot']
    clouds = k.moon(b, mx, my, MOON_R, clouds=2)
    k.stars(b, r.fork('stars'), 3, (8, 5, 152, 50), avoid=((mx, my, 20), *clouds),
            ok=lambda p: _clear_of_pines(p, 6.0), part='star')
    _tent(b, s)
    _bundle(b, s)
    _stove(b, s)
    # The campfire in front of the tent: its light is the night's.
    b.glow(k.ring(FIRE_X, 154.0, 32.0, 12), part='fire')
    b.glow(k.wash_of(s['door_glow'], inset=0.84, dx=0.0, dy=1.0), when=(('allDone',), *PLANNED),
           part='door')
    for log in s['logs']:
        b.line(log, part='fire')
    _fire(b, 0, when=(('idle',),))
    for i, (x, y) in enumerate(s['embers']()):
        k.glow_dot(b, x, y, EMBER_R, halo=10, when=(('reward', i), *PLANNED), part=f'ember:{i}',
                   glass=False)
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), lambda f, child: _fire(child, (1, 2, 0, 2, 1, 0)[f]))
