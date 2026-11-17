"""A kitchen counter with bread.

Day: a counter under a window of sky (the sage is the daylight in its panes),
a shelf with two jars on the wall at the right, cupboards below. A loaf sits
on a bread board, and beside it stands a cooling rack of three tiers. Each
finished task sets a coral roll on the rack, the first few spread across the
tiers; Start sends steam up from the loaf; everything done hangs a tea towel
over the counter's edge; a day with nothing planned leaves the rack empty and
a bag of flour on the board instead of the loaf; overdue work leaves crumbs on
the board, then a cup on the counter, then a cloud in a top pane. The sun
crosses the panes with the hour, sets on the window's rail, and late at night
is an ink moon among stars.

Night: the same counter with the oven on. The right cupboard is the oven's
door, and its light glows in the oven window and spills onto the floor; the
window is dark, the moon in a top pane and stars beside it. A cat sleeps on
the shelf where the jars stood, and the loaf is put away under a cloth. The
rolls catch the oven's light;
Start sends heat shimmering up the oven door; everything done hangs the tea
towel; overdue work is as by day, the cloud beside the moon.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

WIN = (10.0, 12.0, 74.0, 64.0)
MUNTIN_X, MUNTIN_Y = 42.0, 38.5
SILL = 68.8
SHELF = (92.0, 154.0, 40.0)          # x0, x1, its top; the front edge is 4.6 below
TOP = 128.0                          # the counter's top
EDGE = 134.0                         # its front edge
DOORS = ((8.0, 77.0), (83.0, 152.0))
DOOR_TOP, DOOR_FOOT = 140.0, 192.0
BOARD = (17.5, 74.0, 120.0)          # x0, x1, its top (it rests on the counter)
LOAF_X, LOAF_W, LOAF_H = 40.5, 42.0, 25.5
CRUMBS = ((67.4, 118.9, 0.8), (70.4, 118.7, 0.9), (73.0, 119.3, 0.75))
RACK = (83.0, 155.0)                 # its two end posts
TIERS = (123.3, 108.0, 92.0)         # the wires, the bottom one a pen's room above the counter
ROLL_HW, ROLL_H = 6.1, 9.0           # half a roll's width at its points, its height
TOWEL = (30.0, 46.0)
OVEN_WIN = (94.0, 166.0, 141.0, 186.0)
HANDLE_Y = 145.0
# Each pane's middle: top left, top right, lower left, lower right.
PANES = ((26.0, 25.25), (58.0, 25.25), (26.0, 51.25), (58.0, 51.25))
CLOUD_W = 22.0
CLOTH_GAP = (8.0, 19.6)              # the board's top behind the cloth's corner, from the loaf's middle
CLOUD_DY = 1.3                       # a cloud's ink sits this much above its centre
PLANNED = (('planned',),)


def _rule(*pts):
    """Straight segments that the hand leaves unbowed: a smooth stroke that
    turns at every point. Lines that run close to others stay true."""
    return curve(*pts, corners=tuple(range(len(pts))))


def _box(x0: float, y0: float, x1: float, y1: float):
    return loop((x0, y0), (x1, y0), (x1, y1), (x0, y1), corners=(0, 1, 2, 3))


def _rounded(x0: float, y0: float, x1: float, y1: float, r: float, *, closed: bool = True):
    """A rounded rectangle; open, it has no bottom edge (it rests on a line
    the picture already has) and runs from its lower left to its lower right."""
    c = r * (1 - math.sqrt(0.5))
    bl = [(x0 + r, y1), (x0 + c, y1 - c), (x0, y1 - r)]
    tl = [(x0, y0 + r), (x0 + c, y0 + c), (x0 + r, y0)]
    tr = [(x1 - r, y0), (x1 - c, y0 + c), (x1, y0 + r)]
    br = [(x1, y1 - r), (x1 - c, y1 - c), (x1 - r, y1)]
    pts = bl + tl + tr + br
    corners = tuple(i for i in range(len(pts)) if i % 3 != 1)
    if closed:
        return loop(*pts, corners=corners)
    return curve(*pts, corners=corners)


class KitchenCounter:
    id = 'kitchen'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('sun', 'window'), ('jar', 'shelf'), ('cat', 'shelf'), ('board', 'counter'), ('loaf', 'board'),
        ('cloth', 'board'), ('cloth', 'counter'),
        ('flour', 'board'), ('crumbs', 'board'), ('cup', 'counter'), ('rack', 'counter'),
        ('roll', 'rack'), ('towel', 'counter'), ('towel', 'cupboard'), ('oven', 'cupboard'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


# ── shapes ──────────────────────────────────────────────────────────────────

def _roll(cx: float, wy: float):
    """A roll sitting on the wire at (cx, wy): a dome, a little flat below,
    widest at its points so the pen's spline never runs wider."""
    w, h = ROLL_HW, ROLL_H
    pts = ((-w, -3.4), (-w * 0.86, -6.6), (-w * 0.5, -8.6), (0, -h), (w * 0.5, -8.6), (w * 0.86, -6.6),
           (w, -3.4), (w * 0.84, -0.7), (w * 0.4, 0), (-w * 0.4, 0), (-w * 0.84, -0.7))
    return loop(*[(cx + x, wy + y - 0.1) for x, y in pts])


def _roll_reach() -> float:
    """Half a roll's ink across, as the pen draws its spline."""
    xs = [x for x, _ in k.samples(_roll(0.0, 0.0), step=0.5)]
    return max(-min(xs), max(xs))


def _loaf_pts(s: dict) -> list:
    cx, w, h = s['loaf_x'], LOAF_W, LOAF_H
    base = BOARD[2] + 0.2
    left, right = cx - w / 2, cx + w / 2
    return [(left, base), (left + 0.9, base - 6.5), (left + 4.2, base - 15.0), (left + 11.0, base - 22.2),
            (cx, base - h), (right - 11.0, base - 22.2), (right - 4.2, base - 15.0),
            (right - 0.9, base - 6.5), (right, base)]


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same kitchen after dark."""
    reach = _roll_reach()
    x0, x1 = RACK
    # Neighbours a pen and both wobbles apart; the end rolls may come closer
    # to the posts (they stand on the rack), but never within a pen of them.
    pitch = 2 * reach + k.MIN_GAP + 0.3
    room = (x1 - x0) - 2 * (k.MIN_GAP - 0.5) - 2 * reach
    if 3 * pitch > room + 1e-9:
        raise ValueError(f"four rolls {pitch:.2f} apart do not fit a tier {x1 - x0:.1f} wide")
    mid = (x0 + x1) / 2
    spots = [(mid + (i - 1.5) * pitch, y) for y in TIERS for i in range(4)]
    order = k.spread(spots, spots[0])
    return {
        'rolls': [(p, math.radians(r.uniform(-12, 12))) for p in order],
        'loaf_x': LOAF_X + r.uniform(-0.5, 0.5),
        'slashes': [math.radians(r.uniform(-6, 6)) for _ in range(3)],
        'jars': (r.uniform(15.0, 17.0), r.uniform(11.0, 13.0)),
        'moon_pane': r.choice([0, 1]),
    }


# ── the kitchen ─────────────────────────────────────────────────────────────

def _window(b: SketchBuilder) -> None:
    x0, y0, x1, y1 = WIN
    b.line(_box(x0, y0, x1, y1), part='window')
    b.line(curve((MUNTIN_X, y0), (MUNTIN_X + 0.3, y1)), part='window')
    b.line(curve((x0, MUNTIN_Y), (x1, MUNTIN_Y + 0.3)), part='window')
    b.line(curve((x0 - 5, SILL), ((x0 + x1) / 2, SILL + 0.2), (x1 + 5, SILL)), part='sill')


def _shelf(b: SketchBuilder, s: dict, *, night: bool) -> None:
    x0, x1, y = SHELF
    f = y + 4.6
    b.line(_box(x0, y, x1, f), part='shelf')
    for bx in (x0 + 9, x1 - 9):
        b.line(_rule((bx - 3.2, f), (bx, f + 7.0), (bx + 3.2, f)), part='shelf')
    if night:
        _cat(b)
        return
    # Two jars, a tall one with a band and a short wide one, open at the foot:
    # they stand on the shelf's line.
    for cx, w, h, band in ((106.0, 15.0, s['jars'][0], True), (134.0, 13.0, s['jars'][1], False)):
        top = y - h
        hw = w / 2
        b.line(curve((cx - hw, y + 0.1), (cx - hw - 0.5, y - h * 0.55), (cx - hw + 1.6, top),
                     (cx + hw - 1.6, top), (cx + hw + 0.5, y - h * 0.55), (cx + hw, y + 0.1),
                     corners=(2, 3)), part='jar')
        b.line(_rule((cx - hw + 2.4, top), (cx - hw + 2.4, top - 4.6), (cx + hw - 2.4, top - 4.6),
                     (cx + hw - 2.4, top)), part='jar')
        if band:
            b.line(curve((cx - hw - 0.4, y - h * 0.45), (cx + hw + 0.4, y - h * 0.45 + 0.3)), part='jar')


def _cat(b: SketchBuilder) -> None:
    """At night a cat sleeps on the shelf where the jars stood, curled, its
    head at the left with its ears up, its tail wrapped along its front."""
    x, y = 136.0, SHELF[2] + 0.1

    def p(u: float, v: float):
        return (x - u * 1.08, y - v * 1.08)

    b.line(loop(p(0, 0), p(0.8, 5.6), p(6.5, 10.2), p(14, 11), p(18.6, 9.6), p(19.8, 13), p(22.2, 10.6),
                p(24.6, 13), p(26.2, 9.4), p(27.8, 4.6), p(27, 0), corners=(0, 5, 7, 10)), part='cat')
    b.line(curve(p(1.4, 4.8), p(7, 5.2), p(13.5, 4.8), p(17, 6.4), p(16.2, 8.2)), part='cat')
    b.line(curve(p(21.6, 6.4), p(23, 5.4), p(24.6, 6.2)), part='cat')


def _counter(b: SketchBuilder) -> None:
    """The top and its front edge; the edge behind the towel is drawn only
    while the towel is not there."""
    l, r = 1.5, 158.5
    t0, t1 = TOWEL
    b.line(curve((l, TOP), (40, TOP + 0.3), (80, TOP + 0.4), (120, TOP + 0.3), (r, TOP)), part='counter')
    b.line(_rule((l, TOP), (l, EDGE), (t0, EDGE + 0.1)), part='counter')
    b.line(_rule((t0, EDGE + 0.1), (t1, EDGE + 0.1)), when=(('notAllDone',),), part='counter')
    b.line(_rule((t1, EDGE + 0.1), (r, EDGE), (r, TOP)), part='counter')


def _cupboards(b: SketchBuilder, *, night: bool) -> None:
    (a0, a1), (c0, c1) = DOORS
    t0, t1 = TOWEL
    # The left door: its top behind the towel is drawn only while the towel
    # is not there.
    b.line(_rule((t0, DOOR_TOP), (a0, DOOR_TOP), (a0, DOOR_FOOT), (a1, DOOR_FOOT), (a1, DOOR_TOP),
                 (t1, DOOR_TOP)), part='cupboard')
    b.line(_rule((t0, DOOR_TOP), (t1, DOOR_TOP)), when=(('notAllDone',),), part='cupboard')
    b.line(k.ring(a1 - 6.5, DOOR_TOP + 8.0, 1.6, 7), part='cupboard')
    b.line(_box(c0, DOOR_TOP, c1, DOOR_FOOT), part='cupboard')
    if not night:
        b.line(k.ring(c0 + 6.5, DOOR_TOP + 8.0, 1.6, 7), part='cupboard')
        return
    # At night the right cupboard is the oven: a handle across its top and a
    # window in its door.
    hx0, hx1 = c0 + 17, c1 - 17
    b.line(_rule((hx0, DOOR_TOP), (hx0, HANDLE_Y), (hx1, HANDLE_Y), (hx1, DOOR_TOP)), part='oven')
    b.line(_rounded(*OVEN_WIN, 3.0), part='oven')


def _board(b: SketchBuilder, s: dict, *, night: bool) -> None:
    x0, x1, y = BOARD
    if not night:
        b.line(_rounded(x0, y, x1, TOP + 0.2, 3.0, closed=False), part='board')
        return
    # At night the cloth's corner hangs over the board's front, so its top
    # edge stops either side of the corner (and runs on under the flour bag).
    g0, g1 = s['loaf_x'] + CLOTH_GAP[0], s['loaf_x'] + CLOTH_GAP[1]
    r, c = 3.0, 3.0 * (1 - math.sqrt(0.5))
    b.line(curve((x0 + r, TOP + 0.2), (x0 + c, TOP + 0.2 - c), (x0, TOP + 0.2 - r), (x0, y + r), (x0 + c, y + c),
                 (x0 + r, y), (g0, y), corners=(0, 2, 3, 5, 6)), part='board')
    b.line(curve((g1, y), (x1 - r, y), (x1 - c, y + c), (x1, y + r), (x1, TOP + 0.2 - r), (x1 - c, TOP + 0.2 - c),
                 (x1 - r, TOP + 0.2), corners=(0, 1, 3, 4, 6)), part='board')
    b.line(_rule((g0, y), (g1, y)), when=(('nothingPlanned',),), part='board')


def _loaf(b: SketchBuilder, s: dict) -> None:
    pts = _loaf_pts(s)
    b.line(curve(*pts), when=PLANNED, part='loaf')
    cx = s['loaf_x']
    base = BOARD[2]
    for (dx, depth), a in zip(((-11.0, 18.0), (0.0, 20.0), (11.0, 18.0)), s['slashes']):
        x, y = cx + dx, base - depth
        ends = k.rotate(((x - 3.4, y + 1.7), (x + 3.4, y - 1.7)), (x, y), a)
        b.line(line(*ends), when=PLANNED, part='loaf')


def _cloth(b: SketchBuilder, s: dict) -> None:
    """At night the loaf is put away: a cloth draped over it, a low dome
    whose hem spreads on the board, one corner falling over the board's
    front, and one fold from the top down toward that corner."""
    cx, base = s['loaf_x'], BOARD[2] + 0.2
    pts = ((-21.5, 0), (-19.2, -3.6), (-17.0, -9.0), (-11.5, -15.2), (-3.5, -18.6), (5.0, -18.4),
           (12.5, -15.0), (16.8, -9.4), (18.9, -3.4), (20.6, 1.8), (21.4, 5.8), (14.5, 3.2),
           (CLOTH_GAP[0], 0.1))
    b.line(curve(*[(cx + u, base + v) for u, v in pts], corners=(0, 10, len(pts) - 1)), when=PLANNED, part='cloth')
    b.line(curve((cx - 1.0, base - 15.6), (cx + 3.6, base - 9.2), (cx + 11.8, base - 4.0)),
           when=PLANNED, part='cloth')


def _flour(b: SketchBuilder, s: dict) -> None:
    """Nothing planned: a bag of flour stands on the board, its top folded
    over."""
    when = (('nothingPlanned',),)
    cx, base = s['loaf_x'] - 1.0, BOARD[2] + 0.2
    hw, h = 12.0, 28.0
    top = base - h
    b.line(curve((cx - hw, base), (cx - hw - 1.4, base - h * 0.45), (cx - hw + 0.6, top + 5.0),
                 (cx - hw + 1.2, top), (cx + hw - 1.6, top - 0.8), (cx + hw - 0.4, top + 5.2),
                 (cx + hw + 1.4, base - h * 0.45), (cx + hw, base), corners=(3, 4)),
           when=when, part='flour')
    b.line(curve((cx - hw + 0.6, top + 5.0), (cx, top + 6.4), (cx + hw - 0.4, top + 5.2)), when=when, part='flour')
    b.line(curve((cx - 4.5, top + 12.5), (cx + 0.2, top + 11.6), (cx + 4.5, top + 12.6)), when=when, part='flour')


def _crumbs(b: SketchBuilder) -> None:
    """Overdue work: crumbs left on the board."""
    for x, y, r in CRUMBS:
        b.line(k.ring(x, y, r, 5), when=(('overdue', 1),), part='crumbs')


def _cup(b: SketchBuilder) -> None:
    """Overdue work, at two: a cup left on the counter at its left end."""
    when = (('overdue', 2),)
    l, r, top = 5.0, 12.6, TOP - 10.5
    b.line(_rule((l, top), (l + 0.6, TOP + 0.2), (r - 0.6, TOP + 0.2), (r, top)), when=when, part='cup')
    b.line(curve((l, top), ((l + r) / 2, top + 1.0), (r, top)), when=when, part='cup')
    b.line(curve((l + 0.2, top + 2.4), (1.9, top + 3.6), (2.2, top + 6.6), (l + 0.5, top + 7.6)), when=when, part='cup')


def _rack(b: SketchBuilder) -> None:
    x0, x1 = RACK
    hi = TIERS[-1] - 3.5
    for x in (x0, x1):
        b.line(_rule((x, hi), (x, TIERS[0] + 1.0)), part='rack')
        # A little foot either side of the post.
        b.line(_rule((x - 1.8, TOP + 0.2), (x, TIERS[0] + 1.0), (x + 1.8, TOP + 0.2)), part='rack')
    for y in TIERS:
        b.line(curve((x0, y), ((x0 + x1) / 2, y + 0.1), (x1, y)), part='rack')


def _towel(b: SketchBuilder) -> None:
    """Everything done: a tea towel hangs over the counter's front edge, its
    front fold ending above the back's hem, two stripes across it."""
    when = (('allDone',),)
    t0, t1 = TOWEL
    foot = 161.5
    b.line(_rule((t0, TOP + 0.2), (t0 + 0.4, foot), (t1 + 0.4, foot + 0.3), (t1, TOP + 0.3)), when=when, part='towel')
    for y in (foot - 6.0, foot - 11.5):
        b.line(_rule((t0 + 0.3, y), (t1 + 0.3, y + 0.2)), when=when, part='towel')


def _kitchen(b: SketchBuilder, s: dict, *, night: bool) -> None:
    _window(b)
    _shelf(b, s, night=night)
    _counter(b)
    _cupboards(b, night=night)
    _board(b, s, night=night)
    if night:
        _cloth(b, s)
    else:
        _loaf(b, s)
    _flour(b, s)
    _crumbs(b)
    _cup(b)
    _rack(b)
    _towel(b)


def _rolls(b: SketchBuilder, s: dict, *, night: bool) -> None:
    for i, ((x, y), a) in enumerate(s['rolls']):
        when = (('reward', i), *PLANNED)
        if night:
            b.glow(ellipse(x, y - 4.5, 10.5, 8.5, n=10), when=when, part=f'roll:{i}')
        b.filled(_roll(x, y), when=when, part=f'roll:{i}')
        ends = k.rotate(((x - 2.3, y - 4.6), (x + 2.1, y - 6.6)), (x, y - 5.6), a)
        b.line(line(*ends), when=when, part=f'roll:{i}')
        b.anchor(i, x, y)


# ── the window's sky ────────────────────────────────────────────────────────

def _pane_ok(margin: float):
    x0, y0, x1, y1 = WIN

    def ok(p) -> bool:
        x, y = p
        inside_x = x0 + margin <= x <= MUNTIN_X - margin or MUNTIN_X + margin <= x <= x1 - margin
        inside_y = y0 + margin <= y <= MUNTIN_Y - margin or MUNTIN_Y + margin <= y <= y1 - margin
        return inside_x and inside_y
    return ok


def _pane_cloud(b: SketchBuilder, pane: int, when: tuple) -> tuple:
    x, y = PANES[pane]
    k.cloud(b, x, y + CLOUD_DY, CLOUD_W, when=when, part='cloud')
    return (x, y, 13.0)


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = WIN
    b.wash(k.wash_of(poly((x0, y0), (x1, y0), (x1, y1), (x0, y1)), inset=0.95, dx=3, dy=3), part='window')
    b.wash(k.wash_of(loop(*_loaf_pts(s)), inset=0.9, dx=3, dy=2), when=PLANNED, part='loaf')
    _kitchen(b, s, night=False)
    # The hour, in the panes.
    sun = dict(ray_gap=2.4, ray_len=2.2, rays=5)
    k.sun(b, r.fork('sun-m'), *PANES[0], 3.2, when=(k.MORNING,), **sun)
    k.sun(b, r.fork('sun-n'), *PANES[1], 3.2, when=(k.MIDDAY,), **sun)
    k.sun(b, r.fork('sun-a'), *PANES[3], 3.2, when=(k.AFTERNOON,), **sun)
    k.low_sun(b, r.fork('sun-d'), PANES[2][0], y1 - 1.4, 5.0, when=(k.DUSK,))
    moon = s['moon_pane']
    mx, my = PANES[moon]
    k.moon(b, mx, my, 5.0, glow=False, clouds=0, when=(k.LATE,))
    # Overdue work, at three: a cloud in a top pane, the one the sun or the
    # moon is not in at that hour.
    _pane_cloud(b, 1, (('overdue', 3), k.MORNING))
    _pane_cloud(b, 0, (('overdue', 3), ('hour', 11, 22)))
    late_cloud = _pane_cloud(b, 1 - moon, (('overdue', 3), k.LATE))
    k.stars(b, r.fork('late-stars'), 3, (x0 + 2, y0 + 2, x1 - 2, y1 - 2), ok=_pane_ok(2.5),
            avoid=((mx, my, 8.5), late_cloud), gap=14, when=(k.LATE,), part='star')
    _rolls(b, s, night=False)
    x, top = s['loaf_x'], BOARD[2] - LOAF_H
    b.ambient(1.0, (('focus',),),
              lambda f, child: k.steam(child, x, top - 5.0, f, 6, height=14, when=PLANNED))


def _shimmer(frame: int, child: SketchBuilder) -> None:
    """Start: heat rises up the oven door above its window, one wavy line a
    frame, stepping up."""
    y = (160.2, 155.4, 150.7)[frame % 3]
    phase = math.pi * (frame // 3) + frame
    x0, x1 = 104.0, 131.0
    pts = [(x0 + (x1 - x0) * i / 8, y + 0.9 * math.sin(phase + i * 1.5)) for i in range(9)]
    child.line(curve(*pts), part='heat')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    wx0, wy0, wx1, wy1 = OVEN_WIN
    # The oven's light: in its window and spilling down onto the floor.
    b.glow(poly((wx0 - 1, wy0 - 1), (wx1 + 1, wy0 - 1), (wx1 + 1, wy1), (157, 199), (78, 199),
                (wx0 - 1, wy1)), part='oven')
    _kitchen(b, s, night=True)
    moon = s['moon_pane']
    mx, my = PANES[moon]
    k.moon(b, mx, my, 5.0, clouds=0)
    # Overdue work, at three: a cloud beside the moon, in the next pane.
    cloud = _pane_cloud(b, 1 - moon, (('overdue', 3),))
    # Stars beside the moon, in the panes it and the cloud leave.
    wx0, wy0, wx1, wy1 = WIN
    k.stars(b, r.fork('stars'), 3, (wx0 + 2, wy0 + 2, wx1 - 2, wy1 - 2), ok=_pane_ok(2.5),
            avoid=((mx, my, 8.5), cloud), gap=14, part='star')
    _rolls(b, s, night=True)
    b.ambient(1.0, (('focus',),), _shimmer)
