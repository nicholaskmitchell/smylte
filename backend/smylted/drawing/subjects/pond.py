"""A lily pond.

Day: a wide pond below a far bank, reeds with bulrush heads at either side,
six round lily pads afloat on it and a frog on the bank at the right. Each
finished task opens a coral lily beside a pad, two to a pad, the first few
spread across the pond; Start sends a dragonfly darting over the water;
everything done brings the frog onto the largest pad; a day with nothing
planned leaves the pads bare; overdue work floats a fallen leaf on the water,
then brings a cloud, and a second. The sun crosses the sky with the hour, sets
on the far bank between the reeds, and late at night is an ink moon.

Night: the same pond under the moon, its reflection a soft light on the
water. Each finished task lights a lily; everything done brings the frog onto
the largest pad; Start sends ripples across the moon's reflection; overdue
work brings a cloud beside the moon, a second a step beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import PEN, WOBBLE, curve, ellipse, line, loop
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

# The pond's rim, all the way round from the inlet's upper lip: the far edge
# flatter, a bulge at the near left, and on the right a stream's mouth, a
# short rounded notch that ends inside the picture. Each day moves the points
# by up to RIM_JITTER.
RIM = ((147.0, 115.5), (150.0, 100.0), (147.0, 82.0), (134.0, 71.5),
       (112.0, 67.5), (84.0, 66.5), (56.0, 67.5), (30.0, 71.0), (22.0, 86.0),
       (19.0, 102.0), (16.0, 120.0), (10.5, 138.0), (8.2, 158.0), (11.5, 176.0),
       (28.0, 185.5), (56.0, 186.5), (86.0, 183.0), (114.0, 175.0), (135.0, 160.0),
       (146.0, 142.0), (146.5, 128.0), (149.5, 125.6), (150.8, 121.8), (149.8, 118.0))
MOUTH = (0, 20)  # the inlet's two lips, where the rim turns into the notch
RIM_JITTER = 0.8
# The far bank, behind the reeds, across the whole picture.
BANK = ((0.0, 58.0), (42.0, 55.5), (90.0, 53.0), (128.0, 52.5), (160.0, 54.0))
DUSK_X = 104.0                             # where the sun sets on it
# The pads: (x, y, radius), the largest first, at the centre-left; the frog
# sits on it when everything is done.
PADS = ((43.5, 150.5, 16.0), (118.0, 88.5, 14.0), (99.1, 155.0, 13.0),
        (36.8, 108.7, 12.0), (73.2, 118.9, 12.0), (128.0, 130.5, 12.0))
NOTCH = math.radians(16)                   # half the notch's opening
NOTCH_CLEAR = math.radians(26)             # no lily nearer the notch than this
LILY_R = 7.0               # a lily's reach from its middle
LILY_CLEFT = 3.9           # how far from its middle its petals part
LILY_PETAL = 6.8          # how far its petals reach at their widest
LILY_LOBE = math.radians(22)               # half the turn between a petal's two widest points
GLOW_R = 6.0
# Paper between two marks' ink: a pen and the wobble of both.
CLEAR = PEN + 2 * WOBBLE
SPACING = 2 * LILY_R + CLEAR              # two lilies never touch
# The ripples on the moon's reflection, the night's focus loop: arcs round
# one centre, the near side of each ring, growing a step a frame. Their
# smallest and the step between rings, the arcs' half angle and how flat the
# rings are, seen across the water. By day the fallen leaf floats there.
RIPPLE = (72.0, 86.0)
RIPPLE_R0 = 3.0
RIPPLE_STEP = 3.0
RIPPLE_SPAN = math.radians(85)
RIPPLE_FLAT = 0.75
# The water no pad or lily may enter: the ripples' ink and the leaf's.
CALM = (54.0, 90.0, 84.0, 99.5)           # x0, x1, y0, y1
REFLECTION = (72.0, 86.0, 27.0, 10.0)     # the moon on the water: x, y, half axes
MOON_R = 7.0
PLANNED = (('planned',),)

# The reeds: a tall clump of four at the left, a short clump of three at the
# right. Each is (where its foot meets the rim, head x, head y); a head is a
# bulrush 4.4 wide and 11 tall, a short spike above it.
REEDS = (((17.0, 115.0), 8.0, 74.0), ((19.0, 99.0), 13.0, 46.5),
         ((22.0, 86.0), 22.0, 49.0), ((29.0, 71.5), 31.0, 45.0),
         ((147.0, 82.0), 143.0, 66.0), ((150.0, 92.0), 149.5, 70.0),
         ((150.0, 106.0), 155.5, 79.5))
HEAD = (2.2, 5.5)
SPIKE = 3.0

FROG_BANK = (143.0, 185.0)                 # the frog's middle on the bank
# Weather by day, clear of every sun and the dragonfly: (x, y, width).
CLOUDS = ((52.0, 11.0, 22.0), (127.0, 8.0, 22.0))
LATE_MOON = (22.0, 19.0)
NIGHT_MOON = (70.0, 17.0)
# The dragonfly darts and hovers: where it is in each frame of the loop, and
# the sky it keeps to.
DARTS = ((50.0, 33.0), (51.5, 32.0), (69.0, 28.5), (70.5, 29.5), (79.0, 35.0), (63.0, 36.0))
DRAGONFLY_BOX = (36.0, 16.0, 92.0, 48.0)


class LilyPond:
    id = 'pond'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        # The reeds grow at the water's edge; a lily sits against its pad (or
        # between two); the setting sun rests on the far bank, and the bank
        # runs behind the reeds.
        ('reed', 'rim'), ('reed', 'bank'), ('lily', 'pad'), ('sun', 'bank'),
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

def _rim(pts):
    """The rim as the pen draws it, closed all round: the water's edge."""
    return loop(*pts, corners=MOUTH)


RIM_LINE = k.samples(_rim(RIM), 1.0)


def _in_pond(p, margin: float) -> bool:
    """Whether p is inside the pond's rim, at least `margin` from it (and
    from the most a day moves it)."""
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in zip(RIM_LINE, RIM_LINE[1:] + RIM_LINE[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    m = margin + 1.0 + RIM_JITTER
    return inside and all((x - qx) ** 2 + (y - qy) ** 2 >= m * m for qx, qy in RIM_LINE)


def _bank_y(x: float) -> float:
    """The far bank's height at x."""
    return min(BANK_LINE, key=lambda q: abs(q[0] - x))[1]


BANK_LINE = k.samples(curve(*BANK), 1.0)


def _from_calm(p) -> float:
    x0, x1, y0, y1 = CALM
    return math.hypot(max(x0 - p[0], 0.0, p[0] - x1), max(y0 - p[1], 0.0, p[1] - y1))


def _turn_gap(a: float, b: float) -> float:
    d = (a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def _lily_spots(i: int) -> list:
    """Where a lily may sit against pad i: (angle, middle), every 6 degrees
    round it, inside the pond, clear of the calm water and of every other
    pad (touching one is fine: it sits between the two)."""
    x, y, rr = PADS[i]
    out = []
    for deg in range(0, 360, 6):
        t = math.radians(deg)
        d = rr + LILY_R + 0.6
        p = (x + d * math.cos(t), y + d * math.sin(t))
        if not _in_pond(p, LILY_R + CLEAR):
            continue
        if _from_calm(p) < LILY_R + CLEAR + 0.5:
            continue
        if any(math.dist(p, (x2, y2)) < r2 + LILY_R - 0.5 for j, (x2, y2, r2) in enumerate(PADS) if j != i):
            continue
        out.append((t, p))
    return out


SPOTS = [_lily_spots(i) for i in range(len(PADS))]
# Where each pad's notch may open: away from where its lilies can sit (toward
# the rim, the calm water or a neighbour), so it never takes their room.
NOTCHES = [[math.radians(deg) for deg in range(0, 360, 6)
            if all(_turn_gap(math.radians(deg), t) >= NOTCH_CLEAR for t, _ in spots)]
           or [0.0] for spots in SPOTS]


def _place_lilies(r: Rng, notches: list) -> list | None:
    """Two lilies to each pad, none at its notch, every two SPACING apart:
    a search in the stream's own order, so each day sets them differently.
    None if it gives up."""
    cand = []
    for i, spots in enumerate(SPOTS):
        c = [(t, p) for t, p in spots if _turn_gap(t, notches[i]) >= NOTCH_CLEAR]
        c.sort(key=lambda _: r.random())
        cand.append(c)
    order = sorted(range(len(PADS)), key=lambda i: len(cand[i]))
    chosen: list = []
    budget = [4000]

    def fits(p) -> bool:
        return all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= SPACING ** 2 for q in chosen)

    def fill(n: int) -> bool:
        if n == len(order):
            return True
        c = cand[order[n]]
        for ia in range(len(c)):
            pa = c[ia][1]
            if not fits(pa):
                continue
            for ib in range(ia + 1, len(c)):
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                pb = c[ib][1]
                if math.dist(pa, pb) < SPACING or not fits(pb):
                    continue
                chosen.extend((pa, pb))
                if fill(n + 1):
                    return True
                del chosen[-2:]
        return False

    return list(chosen) if fill(0) else None


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same pond after dark."""
    pts = [(x + r.uniform(-RIM_JITTER, RIM_JITTER), y + r.uniform(-RIM_JITTER, RIM_JITTER)) for x, y in RIM]
    rim = _rim(pts)
    edge = k.samples(rim, 1.0)
    # Each pad's notch, and its lilies round the rest of it. The largest
    # pad's notch opens downward, under the frog's chin and clear of it.
    for attempt in range(8):
        rn = r.fork(f'notches{attempt}')
        notches = [math.radians(108 + rn.uniform(-8, 8))] + [rn.choice(NOTCHES[i]) for i in range(1, len(PADS))]
        lilies = _place_lilies(r.fork(f'lilies{attempt}'), notches)
        if lilies is not None:
            break
    else:
        raise ValueError("no room for the lilies round the pads")
    order = k.spread(lilies, (12.0, 128.0))

    reeds = []
    for foot, hx, hy in REEDS:
        bx, by = min(edge, key=lambda q: math.dist(q, foot))
        hx += r.uniform(-0.8, 0.8)
        hy += r.uniform(-1.0, 1.0)
        reeds.append(((bx, by - 0.6), (hx, hy)))
    return {
        'rim': rim, 'notches': notches, 'lilies': order, 'reeds': reeds,
        'tilt': [r.uniform(0, 2 * math.pi / 5) for _ in range(k.REWARDS)],
        'leaf': math.radians(r.uniform(-28, -12)),
    }


# ── shapes ──────────────────────────────────────────────────────────────────

def _pad(i: int, notch: float):
    """A round pad with its notch, a narrow wedge cut in toward its middle
    (the largest pad's shallower, under the frog)."""
    x, y, rr = PADS[i]
    depth = rr * (0.72 if i == 0 else 0.42)
    tip = (x + depth * math.cos(notch), y + depth * math.sin(notch))
    n = 9
    arc = [(x + rr * math.cos(notch + NOTCH + (2 * math.pi - 2 * NOTCH) * j / n),
            y + rr * math.sin(notch + NOTCH + (2 * math.pi - 2 * NOTCH) * j / n)) for j in range(n + 1)]
    return loop(tip, *arc, corners=(0, 1, n + 1))


def _lily(x: float, y: float, tilt: float):
    """A water lily open on the water, seen from above: five rounded petals
    round its middle, each a curve between the clefts."""
    pts = []
    for j in range(5):
        a = tilt + 2 * math.pi * j / 5
        pts.append((x + LILY_CLEFT * math.cos(a), y + LILY_CLEFT * math.sin(a)))
        for side in (-1, 1):
            t = a + math.pi / 5 + side * LILY_LOBE
            pts.append((x + LILY_PETAL * math.cos(t), y + LILY_PETAL * math.sin(t)))
    return loop(*pts, corners=(0, 3, 6, 9, 12))


def _frog(b: SketchBuilder, x: float, y: float, when: tuple) -> None:
    """A frog sitting, seen from the front, its middle at (x, y): a wide body,
    two round eyes on top and a smile."""
    b.line(loop((x - 10, y + 3.4), (x - 8.2, y - 2.6), (x - 3.5, y - 5.2), (x + 3.5, y - 5.2),
                (x + 8.2, y - 2.6), (x + 10, y + 3.4), (x + 5, y + 6.2), (x - 5, y + 6.2),
                corners=(0, 5)), when=when, part='frog')
    for side in (-1, 1):
        b.line(k.ring(x + side * 5.0, y - 6.2, 2.5, 7), when=when, part='frog')
    b.line(curve((x - 4.2, y - 0.2), (x, y + 1.6), (x + 4.2, y - 0.2)), when=when, part='frog')


def _reed(base, head):
    """A reed: its stem from the water's edge up to the bulrush, the head,
    and the spike above it."""
    (bx, by), (hx, hy) = base, head
    hw, hh = HEAD
    foot = (hx, hy + hh)
    mid = ((bx + hx) / 2 + 0.8 * (1 if hx < 80 else -1), (by + foot[1]) / 2)
    return [curve((bx, by), mid, foot), ellipse(hx, hy, hw, hh, n=6),
            line((hx, hy - hh), (hx + 0.3, hy - hh - SPIKE))]


def _reed_tops(s: dict) -> list:
    """Circles round the reeds' heads and spikes, for the stars to keep out of."""
    return [(hx, hy, HEAD[1] + SPIKE + CLEAR / 2) for _, (hx, hy) in s['reeds']]


def _dragonfly(frame: int, child: SketchBuilder) -> None:
    """Start: a dragonfly darts over the pond and hovers, its wings beating."""
    x, y = DARTS[frame]
    beat = math.radians(14) * (1 if frame % 2 else -1)
    child.line(line((x - 11.5, y + 0.8), (x + 5.0, y)), part='dragonfly')
    child.line(k.ring(x + 6.8, y - 0.1, 1.6, 6), part='dragonfly')
    for root, lean in ((2.2, -0.25), (-1.8, 0.25)):
        for side in (-1, 1):
            a = side * (math.pi / 2 + lean + beat)
            ca, sa = math.cos(a), math.sin(a)

            def at(u: float, v: float, root=root, ca=ca, sa=sa):
                return (x + root + u * ca - v * sa, y + u * sa + v * ca)

            child.line(loop(at(0, 0), at(4.8, 2.0), at(10.0, 0), at(4.8, -2.0), corners=(0,)),
                       part='dragonfly')


def _ripples(frame: int, child: SketchBuilder) -> None:
    """Start, at night: rings spread across the moon's reflection from one
    drop, three arcs one inside another, the newest still too small to draw."""
    x, y = RIPPLE
    for j in range(3):
        rx = RIPPLE_R0 + RIPPLE_STEP * ((frame + 2 * j) % 6)
        if rx < 4:
            continue
        pts = [(x + rx * math.cos(a), y + rx * RIPPLE_FLAT * math.sin(a))
               for a in (math.pi / 2 + RIPPLE_SPAN * (i / 3 - 1) for i in range(7))]
        child.line(curve(*pts), part='ripple')


# ── the pond ────────────────────────────────────────────────────────────────

def _setting(b: SketchBuilder, s: dict) -> None:
    """The pond both compositions share: the far bank, the water, the reeds,
    the pads and the frog."""
    b.wash(k.wash_of(s['rim'], dx=2.0, dy=3.0), part='rim')
    b.line(curve(*BANK), part='bank')
    b.line(s['rim'], part='rim')
    for base, head in s['reeds']:
        for st in _reed(base, head):
            b.line(st, part='reed')
    for i, notch in enumerate(s['notches']):
        b.line(_pad(i, notch), part=f'pad:{i}')
    # The frog: on the bank, or on the largest pad when everything is done.
    _frog(b, *FROG_BANK, (('notAllDone',),))
    px, py, _ = PADS[0]
    _frog(b, px, py - 0.5, (('allDone',),))


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _setting(b, s)
    # The hour.
    k.sun(b, r.fork('sun-m'), 19, 22, 5.5, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 98, 15, 5.8, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 142, 30, 5.5, when=(k.AFTERNOON,))
    k.low_sun(b, r.fork('sun-d'), DUSK_X, _bank_y(DUSK_X) - 0.2, 6.0, when=(k.DUSK,))
    mx, my = LATE_MOON
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    dx0, dy0, dx1, dy1 = DRAGONFLY_BOX
    k.stars(b, r.fork('late-stars'), 3, (34, 4, 156, 38),
            avoid=((mx, my, 14), *((x, y, w * 0.6 + 4) for x, y, w in CLOUDS), *_reed_tops(s)),
            ok=lambda p: not (dx0 <= p[0] <= dx1 and dy0 <= p[1] <= dy1),
            when=(k.LATE,), part='star')
    # Overdue work: a fallen leaf on the water, then a cloud, and a second.
    k.draw_leaf(b, 63.0, 93.0, 14.0, s['leaf'], when=(('overdue', 1),), part='leaf')
    for level, (x, y, w) in enumerate(CLOUDS, start=2):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level - 1}')
    for i, (x, y) in enumerate(s['lilies']):
        b.filled(_lily(x, y, s['tilt'][i]), when=(('reward', i), *PLANNED), part=f'lily:{i}')
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), _dragonfly)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _setting(b, s)
    mx, my = NIGHT_MOON
    clouds = k.moon(b, mx, my, MOON_R, clouds=2)
    k.stars(b, r.fork('stars'), 3, (6, 4, 154, 38), avoid=((mx, my, 20), *clouds, *_reed_tops(s)),
            part='star')
    # The moon's light on the water, under the ripples.
    x, y, rx, ry = REFLECTION
    b.glow(ellipse(x, y, rx, ry, n=12), part='reflection')
    for i, (x, y) in enumerate(s['lilies']):
        k.glow_dot(b, x, y, GLOW_R, halo=11, when=(('reward', i), *PLANNED), part=f'lily:{i}')
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), _ripples)
