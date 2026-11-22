"""A tide pool.

Day: a low rocky bank on the shore, the far sea a line under the sky, the
pool on the sand in front of it and a flat stone lying over its near edge; a
starfish on the biggest rock and shells in the sand. Each finished task opens
a coral anemone on the pool's floor, the first few spread across it; Start
drops ripples on the water; everything done brings a crab onto the bank; a
day with nothing planned leaves the pool empty and still, one line of
reflection on it; overdue work hangs seaweed down the bank, then brings a
cloud, and a second. The sun crosses the sky over the sea with the hour, sets
on the sea line, and late at night is an ink moon.

Night: the same bank and pool under the moon, its light lying on the water.
Each finished task lights a glowing speck of plankton in the pool; everything
done brings the crab; Start ripples the moon's reflection; overdue work brings
a cloud beside the moon, a second a step beyond it at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import PEN, WOBBLE, curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

SEA = 36.0                # the far sea line
# The shore: the sand's far edge, an ink line from near the left edge to
# near the right, the ground the bank stands on: (x, y) along it.
SHORE = ((3.0, 111.0), (80.0, 109.2), (157.0, 111.2))
# The bank: a low run of four rocks standing on the shore, left to right a
# middling one, the biggest and a smaller one (both with flat, faceted tops)
# and a low flat one, each joined to the next at a dip (corners 5, 12 and 17).
# Its top from its left foot to its right, both on the shore.
BANK = ((12.0, 110.5), (14.0, 104.0), (19.0, 97.0), (26.0, 92.5), (33.0, 93.0), (37.0, 95.0),
        (40.0, 85.0), (45.0, 76.5), (51.0, 72.5), (65.0, 71.5), (71.0, 75.0), (77.0, 86.0), (80.0, 90.0),
        (83.5, 87.0), (88.0, 85.0), (100.0, 85.5), (104.5, 90.0), (108.0, 95.0),
        (114.0, 93.0), (125.0, 93.0), (134.0, 96.0), (140.0, 102.0), (143.0, 110.5))
# A crack down from each dip, where one rock meets the next: the dip and two
# points on the way down, ending short of the shore.
CLEFTS = ((5, (36.5, 99.0), (35.5, 103.0)), (12, (80.5, 96.0), (79.5, 101.5)),
          (17, (108.5, 99.5), (108.0, 103.0)))
# The pool, on the sand in front of the bank: wide, its far rim near the
# shore at the left and falling away from it toward the right, with no dip in
# it, its near edge swelling in a lobe at the left and drawn in a little bay
# right of the middle. Its corners, clockwise from the far rim's left.
POOL_PTS = ((16.0, 142.0), (22.0, 130.0), (34.0, 123.0), (54.0, 119.0), (76.0, 118.0), (96.0, 119.5),
            (113.0, 122.5), (129.0, 125.5), (142.0, 128.5), (150.0, 136.5), (154.0, 148.0),
            (150.0, 160.0), (141.0, 169.0), (128.0, 175.0), (112.0, 179.0), (94.0, 182.0),
            (74.0, 185.0), (54.0, 186.0), (38.0, 182.0), (26.0, 175.0), (18.0, 164.0), (15.0, 153.0))
# A flat stone in front of the pool, right of the middle, over its near rim,
# which runs behind it.
STONE = ((96.0, 182.0), (102.0, 175.0), (114.0, 171.5), (128.0, 171.0), (138.0, 174.0), (142.0, 181.0),
         (136.0, 186.0), (118.0, 187.5), (102.0, 186.5))
# The anemones' places on the pool's floor (and the plankton's, at night),
# in spread order, the first five away from the ripples so that none lies
# under their arcs: each clear of the rim, the stone and the ripples by CLEAR,
# and of the others by SPACING, however the hand moves the pool, the stone
# and each place by up to SLOT_JITTER.
SLOTS = ((30.7, 158.2), (138.1, 144.4), (88.7, 169.0), (102.1, 153.0), (47.4, 170.7), (115.2, 137.2),
         (68.0, 171.8), (34.3, 137.8), (122.2, 157.5), (57.1, 152.5), (77.7, 151.6), (93.5, 133.5))
SLOT_JITTER = 1.0
ANEMONE_R = 6.25          # 12.5 across
LOBES = 6
# Where two anemones (or two specks of plankton, the same size) would touch.
SPACING = k.apart(ANEMONE_R)
PLANKTON_R = 6.0
# Clear of other ink by the anemone's reach, a pen and both wobbles.
CLEAR = ANEMONE_R + PEN + 2 * WOBBLE
# The ripples: the x they spread from (their height follows the rim, just
# clear of it), the step a ring grows each frame, the angle each arc spans
# (the far side of its ring, one arc per ring round one centre) and how flat
# the rings are, seen across the water: flat enough to lie on it, round
# enough that neighbouring arcs keep MIN_GAP apart at their tops.
RIPPLE_X = 64.0
RIPPLE_STEP = 2.85
RIPPLE_SPAN = math.radians(160)
RIPPLE_FLAT = 0.8
# The moon's light on the water: long, tilted, and toward the moon's side of
# the pool (centre, half length, half width, tilt).
REFLECTION = (74.0, 136.0, 35.0, 9.0, math.radians(-8))
# Nothing planned: the one line of reflection on the still water.
STILL = (84.0, 154.0)
# The rocks' washes: how much smaller than the rock, and how far down and
# right of it (k.wash_of's inset, dx and dy).
WASH_INSET = 0.93
WASH_SHIFT = (1.5, 3.0)
# The starfish on the biggest rock; where the crab stands on the smaller
# one's flat top; and where the seaweed hangs from the low flat one's top,
# well clear of its cleft.
STAR_AT = (57.0, 90.0)
CRAB_X = 94.0
WEED_X = 126.5
# The seaweed: three strands hung side by side from the rock's top, this far
# apart, swaying together down its face toward the water, the middle one to
# the shore, the others shorter (how much shorter than the middle one).
WEED_STEP = 5.5
WEED_SHORT = (2.0, 0.0, 3.0)
# How far the strands sway (together), and how far each leans out at its foot:
# measured over 2,000 days and four salts, every boil frame, the left strand
# keeps 6.8 from the cleft (MIN_GAP + PEN is 6.75) and neighbours stay 2.5
# apart, centre to centre (more than a pen).
WEED_SWAY = 1.6
WEED_LEAN = (-1.4, 0.0, 1.4)
# The shells in the sand, never a pair: one at the left, one in front of the
# pool left of the stone, smaller (x, y, which way they turn, size). The small
# one sits low enough that the near rim, moved by hand and boiling, never comes
# within a pen of it (3.4 centre to centre at worst over 2,000 days and four
# salts), its ink 3 above the picture's foot.
SHELLS = ((12.0, 189.0, 1, 6.0), (92.0, 191.0, -1, 4.4))
MOON_R = 7.0
PLANNED = (('planned',),)

# Weather by day, clear of every sun and the day's late moon: (x, y, width).
CLOUDS = ((52.0, 15.0, 24.0), (110.0, 20.0, 24.0))
LATE_MOON = (80.0, 14.0)
NIGHT_MOON = (70.0, 17.0)
WAVES = ((38.0, 82.0, 48.0), (78.0, 116.0, 56.0))   # from x, to x, y


class TidePool:
    id = 'tidepool'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        # The bank stands on the shore; the rim runs behind the stone, its
        # ends on the stone's outline.
        ('rock', 'rim'), ('shore', 'rock'),
        # The setting sun rests on the sea line; the seaweed hangs from the
        # bank down to the shore, and the crab stands on the bank.
        ('sun', 'sea'), ('seaweed', 'rock'), ('seaweed', 'shore'), ('crab', 'rock'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _interior(points):
    """Prepare a polygon for the many point queries made during placement."""
    edges = []
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[i - 1]
        if y0 != y1:
            edges.append((x0, y0, x1 - x0, y1 - y0, min(y0, y1), max(y0, y1)))

    def inside(point) -> bool:
        x, y = point
        hit = False
        for x0, y0, dx, dy, top, bottom in edges:
            if top <= y < bottom and x < x0 + dx * (y - y0) / dy:
                hit = not hit
        return hit

    return inside


def _pool(r: Rng):
    """The pool's whole outline, its corners moved a little by hand."""
    pts = [(x + r.uniform(-1.0, 1.0), y + r.uniform(-1.0, 1.0)) for x, y in POOL_PTS]
    return loop(*pts)


def _rim(outline, samples: list, inside_stone) -> object:
    """The rim as drawn: the pool's outline where the stone does not hide
    it, one stroke through the outline's own corners from where it comes out
    from behind the stone round to where it goes back, each end on the
    stone's outline (they are joined)."""
    corners = outline.points
    n = len(corners)
    hid = [inside_stone(p) for p in corners]
    first = next(i for i in range(n) if hid[i - 1] and not hid[i])
    seen = []
    while not hid[(first + len(seen)) % n]:
        seen.append((first + len(seen)) % n)
    # Where the pen crosses the stone's outline: midway between the last
    # point along it that the stone hides and the first it does not, and
    # back.
    pts = samples
    m = len(pts)
    hidden = [inside_stone(p) for p in pts]
    out_at = next(j for j in range(m) if hidden[j - 1] and not hidden[j])
    in_at = next(j for j in range(m) if not hidden[j - 1] and hidden[j])
    mid = lambda p, q: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    start, end = mid(pts[out_at - 1], pts[out_at]), mid(pts[in_at - 1], pts[in_at])
    # Corners right by an end would make a kink in the pen's spline.
    keep = [i for i in seen if math.dist(corners[i], start) >= 3 and math.dist(corners[i], end) >= 3]
    return curve(start, *(corners[i] for i in keep), end)


def _bank(r: Rng) -> tuple[object, list]:
    """The bank's top, its corners moved a little by hand (its feet only
    along the shore), and its corners."""
    pts = [(x + r.uniform(-1.5, 1.5), y + (0.0 if i in (0, len(BANK) - 1) else r.uniform(-1.5, 1.5)))
           for i, (x, y) in enumerate(BANK)]
    return line(*pts), pts


def _ripple_angles(n: int) -> list[float]:
    """The angles along a ripple arc: its far side, centred straight up."""
    return [-math.pi / 2 + RIPPLE_SPAN * (i / (n - 1) - 0.5) for i in range(n)]


def _ripple_arc(rx: float, centre):
    """One ring of the ripples: a single arc, the far side of the ring."""
    x, y = centre
    return curve(*((x + rx * math.cos(a), y + rx * RIPPLE_FLAT * math.sin(a)) for a in _ripple_angles(7)))


def _ring_sizes(frame: int) -> list[float]:
    return [3.0 + RIPPLE_STEP * ((frame + 2 * j) % 6) for j in range(3)]


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same pool after dark."""
    outline = _pool(r.fork('pool'))
    rim_pts = k.samples(outline, step=2.0)
    stone = [(x + r.uniform(-1.0, 1.0), y + r.uniform(-1.0, 1.0)) for x, y in STONE]
    rim = _rim(outline, rim_pts, _interior(stone))
    ridge, bank = _bank(r.fork('bank'))
    shore = curve(*SHORE)
    strokes = [ridge]
    # A crack down from each dip, where one rock meets the next.
    for dip, p, q in CLEFTS:
        strokes.append(curve(bank[dip], p, (q[0] + r.uniform(-0.5, 0.5), q[1] + r.uniform(-0.5, 0.5))))
    # The wash fills the bank down to the shore it stands on.
    region = poly(*bank, *reversed([p for p in k.samples(shore, step=6.0) if bank[0][0] < p[0] < bank[-1][0]]))
    star_at = (STAR_AT[0] + r.uniform(-1.0, 1.0), STAR_AT[1] + r.uniform(-0.5, 0.5))
    star_turn = r.uniform(0, 2 * math.pi / 5)

    # The bank's top above x: the crab stands on it, its inner feet just
    # over it, and the seaweed hangs from it, starting just inside it (both
    # are joined).
    def top_y(x: float) -> float:
        return min(y0 + (y1 - y0) * (x - x0) / (x1 - x0)
                   for (x0, y0), (x1, y1) in zip(bank, bank[1:])
                   if min(x0, x1) <= x <= max(x0, x1) and x0 != x1)

    shore_pts = k.samples(shore, step=1.0)
    weed = []
    for i, short in enumerate(WEED_SHORT):
        x = WEED_X + WEED_STEP * (i - 1) + r.uniform(-0.3, 0.3)
        foot = min(shore_pts, key=lambda p: abs(p[0] - x))[1]
        weed.append((x, top_y(x) + 0.6, foot - 0.4 - short))
    crab_x, crab_dy = CRAB_X + r.uniform(-0.3, 0.3), r.uniform(-0.5, 0.5)
    crab_at = (crab_x, (top_y(crab_x - 4.4) + top_y(crab_x + 4.4)) / 2 - 8.1 + crab_dy)

    # The ripples sit as high on the water as the far rim lets them.
    sizes = [3.0 + RIPPLE_STEP * i for i in range(6)]
    top = sizes[-1] * RIPPLE_FLAT                                # how high the widest arc rises
    back = max(y for x, y in rim_pts if abs(x - RIPPLE_X) <= sizes[-1] + 2 and y < 130)
    ripple = (RIPPLE_X, back + PEN + 2 * WOBBLE + top + 1.0)

    # Anemones and plankton take the fixed places on the pool's floor, each
    # moved a little by hand: only the composition that draws them asks, each
    # from its own fork.
    def floor_points(label: str) -> list:
        h = r.fork(label)
        return [(x + h.uniform(-SLOT_JITTER, SLOT_JITTER), y + h.uniform(-SLOT_JITTER, SLOT_JITTER))
                for x, y in SLOTS]

    return {
        'rim': rim, 'stone': poly(*stone), 'shore': shore, 'bank': (strokes, region),
        'star': (star_at, star_turn), 'crab': crab_at, 'weed': weed, 'ripple': ripple,
        'anemones': lambda: floor_points('anemones'),
        'plankton': lambda: floor_points('plankton'),
        'turns': [r.uniform(0, math.pi) for _ in range(k.REWARDS)],
    }


def _starfish(at, turn: float):
    x, y = at
    pts = []
    for i in range(10):
        a = turn - math.pi / 2 + math.pi * i / 5
        rr = 9.0 if i % 2 == 0 else 3.8
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    return loop(*pts, corners=(0, 2, 4, 6, 8))


def _anemone(x: float, y: float, turn: float):
    """A round head of short tentacle lobes, scalloped rather than pointed so
    it reads as a soft thing and not a star."""
    pts = []
    for i in range(2 * LOBES):
        a = turn + math.pi * i / LOBES
        rr = ANEMONE_R if i % 2 == 0 else 5.0
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    return loop(*pts)


def _shell(cx: float, cy: float, facing: int, size: float = 6.0):
    """A small spiral shell, its turns MIN_GAP apart."""
    pts = []
    for i in range(9):
        t = i / 8
        a = facing * (1.9 * math.pi * t) + math.pi / 2
        rr = size - 0.8 * size * t
        pts.append((cx + rr * math.cos(a), cy + rr * 0.85 * math.sin(a)))
    return curve(*pts)


def _setting(b: SketchBuilder, s: dict) -> None:
    """The shore both compositions stand on."""
    b.line(line((1.0, SEA), (159.0, SEA + 0.3)), part='sea')
    # The sea beyond the bank: two long, low swells.
    for x0, x1, y in WAVES:
        b.line(curve(*((x0 + (x1 - x0) * i / 6, y + 0.9 * math.sin(i * 1.9)) for i in range(7))),
               part='wave')
    strokes, region = s['bank']
    b.wash(k.wash_of(region, inset=WASH_INSET, dx=WASH_SHIFT[0], dy=WASH_SHIFT[1]), part='rock')
    b.wash(k.wash_of(s['stone'], inset=WASH_INSET, dx=WASH_SHIFT[0], dy=WASH_SHIFT[1]), part='rock')
    for st in strokes:
        b.line(st, part='rock')
    b.line(s['stone'], part='rock')
    b.line(s['rim'], part='rim')
    b.line(s['shore'], part='shore')
    b.line(_starfish(*s['star']), part='starfish')
    for n, (x, y, facing, size) in enumerate(SHELLS, start=1):
        b.line(_shell(x, y, facing, size), part=f'shell:{n}')
    # Nothing planned: the pool lies still, one line of reflection on it.
    cx, cy = STILL
    b.line(curve((cx - 22, cy + 1), (cx, cy + 0.2), (cx + 22, cy + 1)), when=(('nothingPlanned',), ('idle',)),
           part='still')
    _crab(b, s['crab'])


def _crab(b: SketchBuilder, at) -> None:
    """Everything done: a crab on the bank, its claws up."""
    x, y = at
    when = (('allDone',),)
    b.line(ellipse(x, y, 7.0, 4.2, n=10), when=when, part='crab')
    for side in (-1, 1):
        # An arm up and out to a pincer, in one stroke: out along the outer
        # prong, back to the joint and out along the inner one.
        b.line(curve((x + side * 5.6, y - 2.4), (x + side * 8.6, y - 5.4), (x + side * 9.4, y - 8.4),
                     (x + side * 11.8, y - 11.4), (x + side * 9.4, y - 8.4), (x + side * 7.4, y - 12.0),
                     corners=(2, 3, 4)), when=when, part='crab')
        # Two legs each side, splayed down: one stroke, out, along the shell
        # and out again.
        b.line(line((x + side * 10.4, y + 5.4), (x + side * 6.2, y + 1.8), (x + side * 2.0, y + 4.0),
                    (x + side * 4.4, y + 8.6)), when=when, part='crab')


def _seaweed(b: SketchBuilder, s: dict, when: tuple) -> None:
    """Three strands of seaweed draped over the bank's top, down its face
    toward the water, the middle one to the shore (they are joined): each one
    long, gentle S, the outer two fanning out toward their feet, each tip
    curled outward in a small hook. They sway together, in step with the
    middle strand at each height, so neighbours keep their spacing (only the
    boil can bring two together, and a tuft of weed may touch)."""
    _, mid_top, mid_bottom = s['weed'][1]
    span = mid_bottom - mid_top
    for j, (x, top, bottom) in enumerate(s['weed']):
        n = 5
        lean = WEED_LEAN[j]
        pts = []
        for i in range(n + 1):
            y = top + (bottom - top) * i / n
            sway = WEED_SWAY * math.sin(2 * math.pi * (y - mid_top) / span) * min(1.0, 2 * i / n)
            pts.append((x + sway + lean * i / n, y))
        tx, ty = pts[-1]
        pts[-1] = (tx + (-1.5 if j == 0 else 1.5), ty - 1.5)
        b.line(curve(*pts), when=when, part='seaweed')


def _ripples(centre):
    def draw(frame: int, child: SketchBuilder) -> None:
        """Start: three rings spread across the water, growing outward (the
        newest still a drop, too small to draw)."""
        for rx in _ring_sizes(frame):
            if rx < 4:
                continue
            child.line(_ripple_arc(rx, centre), part='ripple')
    return draw


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _setting(b, s)
    # The hour, over the sea.
    k.sun(b, r.fork('sun-m'), 22, 18, 5.5, when=(k.MORNING,), rays=5)
    k.sun(b, r.fork('sun-n'), 80, 14, 5.8, when=(k.MIDDAY,), rays=5)
    k.sun(b, r.fork('sun-a'), 138, 18, 5.5, when=(k.AFTERNOON,), rays=5)
    k.low_sun(b, r.fork('sun-d'), 134, SEA + 0.2, 6.0, when=(k.DUSK,))
    mx, my = LATE_MOON
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    k.stars(b, r.fork('late-stars'), 3, (8, 5, 152, 26),
            avoid=((mx, my, 14), *((x, y, w * 0.6 + 4) for x, y, w in CLOUDS)),
            when=(k.LATE,), part='star')
    # Overdue work: seaweed on the bank, then a cloud, and a second.
    _seaweed(b, s, (('overdue', 1),))
    for level, (x, y, w) in enumerate(CLOUDS, start=2):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level - 1}')
    for i, (x, y) in enumerate(s['anemones']()):
        b.filled(_anemone(x, y, s['turns'][i]), when=(('reward', i), *PLANNED), part=f'anemone:{i}')
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), _ripples(s['ripple']))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _setting(b, s)
    mx, my = NIGHT_MOON
    # The clouds go right of the moon, both above the sea line.
    clouds = k.moon(b, mx, my, MOON_R, clouds=2, second=(7.4, -0.5))
    k.stars(b, r.fork('stars'), 3, (6, 4, 154, 26), avoid=((mx, my, 20), *clouds), part='star')
    # The moon's light on the water, under the ripples: a long glow, tilted,
    # on the moon's side of the pool.
    gx, gy, ga, gb, tilt = REFLECTION
    b.glow(ellipse(gx, gy, ga, gb, n=12, rot=tilt), part='reflection')
    for i, (x, y) in enumerate(s['plankton']()):
        k.glow_dot(b, x, y, PLANKTON_R, halo=11, when=(('reward', i), *PLANNED), part=f'plankton:{i}')
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), _ripples(s['ripple']))
