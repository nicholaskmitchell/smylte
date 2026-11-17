"""A tide pool.

Day: two rocks frame a pool on the shore, the far sea a line under the sky, a
starfish on the left rock and shells in the sand. Each finished task opens a
coral anemone on the pool's floor, the first few spread across it; Start drops
ripples on the water; everything done brings a crab onto the right rock; a day
with nothing planned leaves the pool empty and still, one line of reflection
on it; overdue work hangs seaweed on the right rock, then brings a cloud, and a
second. The sun crosses the sky over the sea with the hour, sets on the sea
line, and late at night is an ink moon.

Night: the same rocks and pool under the moon, its light lying on the water.
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
# The pool: no oval but a rock pool's shape, its far edge flat and running in
# behind the boulder's foot, a small notch in it, narrow under the ledge and
# out in a lobe at the lower right. Its corners, and the notch's (drawn sharp).
POOL_PTS = ((36.0, 111.0), (52.0, 110.5), (70.0, 111.0), (86.0, 110.5), (95.0, 111.0), (100.0, 116.0),
            (105.0, 111.0), (113.0, 111.5), (118.0, 116.0), (120.0, 127.0), (120.0, 137.0),
            (129.0, 146.0), (143.0, 152.0), (151.0, 162.0), (148.0, 173.0), (135.0, 180.0),
            (112.0, 185.0), (82.0, 186.0), (55.0, 184.0), (34.0, 179.0), (20.0, 169.0),
            (15.0, 155.0), (17.0, 140.0), (25.0, 124.0))
POOL_NOTCH = 5
# The ellipse anemones are scattered in: round the floor they may use.
FLOOR = (88.0, 150.0, 62.0, 30.0)          # centre x, centre y, half width, half height
# The rocks, each running off its side of the frame: at the left a big low
# boulder, its top flattish and notched, standing in front of the pool's far
# corner; at the right a low flat ledge behind the pool. A facet line from one
# corner (index, end point): the boulder's crack from its notch. The ledge has
# none: its face holds the crab and the seaweed.
LEFT_ROCK = ((-4.0, 128.0), (-4.0, 87.0), (7.0, 84.0), (17.0, 82.0), (26.0, 83.0), (30.0, 89.0),
             (34.0, 83.5), (45.0, 84.0), (53.0, 91.0), (55.0, 101.0), (52.0, 111.0), (45.0, 119.0),
             (30.0, 124.0), (12.0, 127.0))
LEFT_FACET = (5, (35.0, 99.0))
RIGHT_ROCK = ((164.0, 143.0), (164.0, 106.0), (151.0, 106.5), (139.0, 105.5), (127.0, 107.0),
              (117.0, 108.5), (109.0, 118.0), (110.0, 130.0), (116.0, 143.0), (128.0, 150.0),
              (146.0, 144.5))
RIGHT_FACET = None
ANEMONE_R = 6.25          # 12.5 across: 13 leaves too little floor for twelve
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
REFLECTION = (74.0, 134.0, 35.0, 9.0, math.radians(-8))
# Nothing planned: the one line of reflection on the still water.
STILL = (84.0, 152.0)
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
        # The rocks stand behind the pool: their outlines end on its rim.
        ('rock', 'rim'),
        # The setting sun rests on the sea line; the seaweed hangs from the rock.
        ('sun', 'sea'), ('seaweed', 'rock'),
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


def _sparse(pts: list, step: float = 3.5) -> list:
    """Every point of `pts` at least `step` from the last one kept (and the
    last point), for avoid circles: `k.samples` keeps a point per spline
    piece however short."""
    out = pts[:1]
    for p in pts[1:]:
        if math.dist(p, out[-1]) >= step:
            out.append(p)
    if pts and out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _pool(r: Rng):
    """The pool's whole outline, its corners moved a little by hand (the
    notch's sharp)."""
    pts = [(x + r.uniform(-1.0, 1.0), y + r.uniform(-1.0, 1.0)) for x, y in POOL_PTS]
    return loop(*pts, corners=(POOL_NOTCH,))


def _rim(outline, samples: list, inside_boulder) -> tuple:
    """The rim as drawn: the pool's outline where the boulder does not hide
    it, one stroke through the outline's own corners from where it comes out
    from behind the boulder round to where it goes back, each end on the
    boulder's outline (they are joined), the notch kept sharp. And the points
    along it, to keep clear of."""
    corners = outline.points
    n = len(corners)
    hid = [inside_boulder(p) for p in corners]
    first = next(i for i in range(n) if hid[i - 1] and not hid[i])
    seen = []
    while not hid[(first + len(seen)) % n]:
        seen.append((first + len(seen)) % n)
    # Where the pen crosses the boulder's outline: midway between the last
    # point along it that the boulder hides and the first it does not, and
    # back.
    pts = samples
    m = len(pts)
    hidden = [inside_boulder(p) for p in pts]
    out_at = next(j for j in range(m) if hidden[j - 1] and not hidden[j])
    in_at = next(j for j in range(m) if not hidden[j - 1] and hidden[j])
    mid = lambda p, q: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    start, end = mid(pts[out_at - 1], pts[out_at]), mid(pts[in_at - 1], pts[in_at])
    # Corners right by an end would make a kink in the pen's spline.
    keep = [i for i in seen if math.dist(corners[i], start) >= 3 and math.dist(corners[i], end) >= 3]
    rim = curve(start, *(corners[i] for i in keep), end, corners=(keep.index(POOL_NOTCH) + 1,))
    along = [p for p, h in zip(pts, hidden) if not h]
    return rim, along


def _rock(corners, facet, r: Rng, pool_pts: list) -> tuple[list, object, list]:
    """A rock behind the pool: its outline's visible runs (in the frame and
    outside the pool, each ending on the rim or at the frame's edge, its
    corners kept), a facet line, the region its wash fills, which follows
    the rim where the pool hides the rock, and its corners as drawn."""
    pts = [(x, y) if x < 0 or x > 160 else (x + r.uniform(-1.5, 1.5), y + r.uniform(-1.5, 1.5))
           for x, y in corners]
    walk = []                                    # (point, is a corner)
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n = max(1, math.ceil(math.dist(p, q)))
        walk.extend(((p[0] + (q[0] - p[0]) * j / n, p[1] + (q[1] - p[1]) * j / n), j == 0)
                    for j in range(n))
    # (The pool lies below y 96: nothing above it needs the polygon test.)
    inside_pool = _interior(pool_pts)
    seen = [1.5 <= x <= 158.5 and (y <= 96 or not inside_pool((x, y))) for (x, y), _ in walk]
    # Start the walk at a hidden point, so no run wraps past the list's end.
    start = seen.index(False)
    order = walk[start:] + walk[:start]
    flags = seen[start:] + seen[:start]
    runs, cur = [], []
    for item, ok in zip(order, flags):
        if ok:
            cur.append(item)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    strokes = []
    for run in runs:
        if len(run) < 6:
            continue
        keep = [run[0][0], *(p for p, corner in run[1:-1] if corner), run[-1][0]]
        strokes.append(line(*keep))
    if facet is not None:
        i, end = facet
        strokes.append(line(pts[i], end))
    region = []
    for (x, y), _ in walk[::8]:
        if y > 96 and inside_pool((x, y)):
            x, y = min(pool_pts, key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
        region.append((min(158.5, max(1.5, x)), y))
    return strokes, poly(*region), pts


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
    samples = k.samples(outline, step=2.0)
    coarse = _sparse(samples)   # enough to tell inside from out
    # The boulder stands in front of the pool, the ledge behind it.
    rocks = [_rock(LEFT_ROCK, LEFT_FACET, r.fork('left'), []),
             _rock(RIGHT_ROCK, RIGHT_FACET, r.fork('right'), coarse)]
    boulder = rocks[0][2]
    inside_boulder = _interior(boulder)
    rim, rim_pts = _rim(outline, samples, inside_boulder)
    star_at = (15 + r.uniform(-1.5, 1.5), 107 + r.uniform(-2, 2))
    star_turn = r.uniform(0, 2 * math.pi / 5)
    crab_at = (139 + r.uniform(-0.3, 0.3), 127 + r.uniform(-0.5, 0.5))
    weed_x = 156.6 + r.uniform(-0.25, 0.25)
    # Where the seaweed hangs from: the right rock's top edge above weed_x
    # (a short edge, which the hand leaves straight).
    corners = rocks[1][2]
    weed_top = min(y0 + (y1 - y0) * (weed_x - x0) / (x1 - x0)
                   for (x0, y0), (x1, y1) in zip(corners, corners[1:])
                   if min(x0, x1) <= weed_x <= max(x0, x1) and x0 != x1) + 0.6

    # Anemones and plankton keep clear of the rim, the boulder and the
    # starfish by their own reach, out of the ripples' ground (and its ink),
    # on the pool's floor.
    sizes = [3.0 + RIPPLE_STEP * i for i in range(6)]
    top = sizes[-1] * RIPPLE_FLAT                                # how high the widest arc rises
    drop = sizes[-1] * RIPPLE_FLAT * -math.cos(RIPPLE_SPAN / 2)  # how far its ends fall below the centre
    # The ripples sit as high on the water as the far rim lets them.
    back = max(y for x, y in rim_pts if abs(x - RIPPLE_X) <= sizes[-1] + 2 and y < 130)
    ripple = (RIPPLE_X, back + PEN + 2 * WOBBLE + top + 1.0)
    # Both are cheap to trace from their own geometry: the arcs from the
    # ellipses they lie on, the starfish from its points and the midpoints
    # between them.
    ripple_ink = [(ripple[0] + rx * math.cos(a), ripple[1] + rx * RIPPLE_FLAT * math.sin(a))
                  for rx in sizes for a in _ripple_angles(9)]
    star = _starfish(star_at, star_turn).points
    star_ink = [*star, *((((x0 + x1) / 2, (y0 + y1) / 2)) for (x0, y0), (x1, y1) in zip(star, star[1:] + star[:1]))]
    # The boulder's outline where it stands in the pool.
    foot = [p for st in rocks[0][0] for p in _sparse(k.samples(st, step=2.0)) if p[1] > 100]
    # Circles a few units apart, each a little wider to cover the scallops
    # between them: fewer circles, and the placement is that much quicker.
    wide = CLEAR + 0.3
    avoid = (*((x, y, wide) for x, y in _sparse(rim_pts)),
             *((x, y, wide) for x, y in ripple_ink),
             *((x, y, wide) for x, y in star_ink),
             *((x, y, wide) for x, y in foot),
             *((x, y, wide) for x, y in rim.points))    # the notch's tip and all
    bx0, bx1 = ripple[0] - sizes[-1] - 1.0, ripple[0] + sizes[-1] + 1.0
    by0, by1 = ripple[1] - top - 1.0, ripple[1] + drop + 1.0
    reach = ANEMONE_R + WOBBLE
    # Clear of the rim by CLEAR, a point is in the pool when it is inside its
    # outline's corners (the spline strays from them by far less), and out
    # of the boulder's when it is right of its foot or outside its corners.
    inside_pool = _interior(outline.points)
    foot_x = max(x for x, _ in boulder)

    def ok(p) -> bool:
        dx = max(bx0 - p[0], 0.0, p[0] - bx1)
        dy = max(by0 - p[1], 0.0, p[1] - by1)
        return (math.hypot(dx, dy) >= reach and inside_pool(p)
                and (p[0] > foot_x or not inside_boulder(p)))

    # Placed only by the composition that draws them, each from its own fork.
    # Candidates come from an ellipse just round the floor they may use (the
    # pool drawn in by CLEAR), a little looser to reach the lobe: a looser
    # one wastes them on the rim and leaves too few to pack twelve.
    cx, cy, fa, fb = FLOOR

    # The floor is tight: on the rare day one pass cannot place all twelve, a
    # second stream tries again.
    def floor_points(label: str) -> list:
        for n in range(3):
            try:
                pts = k.scatter_all(r.fork(f'{label}|{n}'), k.REWARDS, cx, cy, fa, fb, SPACING,
                                    avoid=avoid, ok=ok, floor=SPACING)
            except ValueError:
                if n == 2:
                    raise
                continue
            return k.spread(pts, (cx, cy))

    return {
        'rim': rim, 'rocks': rocks, 'star': (star_at, star_turn), 'crab': crab_at,
        'weed': (weed_x, weed_top), 'ripple': ripple,
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


def _shell(cx: float, cy: float, facing: int):
    """A small spiral shell, its turns MIN_GAP apart."""
    pts = []
    for i in range(9):
        t = i / 8
        a = facing * (1.9 * math.pi * t) + math.pi / 2
        rr = 6.0 - 4.8 * t
        pts.append((cx + rr * math.cos(a), cy + rr * 0.85 * math.sin(a)))
    return curve(*pts)


def _setting(b: SketchBuilder, s: dict) -> None:
    """The shore both compositions stand on."""
    b.line(line((1.0, SEA), (159.0, SEA + 0.3)), part='sea')
    # The sea between the rocks: two long, low swells.
    for x0, x1, y in WAVES:
        b.line(curve(*((x0 + (x1 - x0) * i / 6, y + 0.9 * math.sin(i * 1.9)) for i in range(7))),
               part='wave')
    for strokes, region, _ in s['rocks']:
        b.wash(k.wash_of(region, dx=1.5, dy=3.0), part='rock')
    for strokes, _, _ in s['rocks']:
        for st in strokes:
            b.line(st, part='rock')
    b.line(s['rim'], part='rim')
    b.line(_starfish(*s['star']), part='starfish')
    b.line(_shell(15.0, 189.0, 1), part='shell:1')
    b.line(_shell(145.0, 189.0, -1), part='shell:2')
    # Nothing planned: the pool lies still, one line of reflection on it.
    cx, cy = STILL
    b.line(curve((cx - 22, cy + 1), (cx, cy + 0.2), (cx + 22, cy + 1)), when=(('nothingPlanned',),),
           part='still')
    _crab(b, s['crab'])


def _crab(b: SketchBuilder, at) -> None:
    """Everything done: a crab on the right rock, its claws up."""
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
    """A strand of seaweed hung over the right rock's top edge."""
    x, top = s['weed']
    pts = [(x + 1.6 * math.sin(i * 1.3) * min(1.0, i / 2), top + i * 5.4) for i in range(6)]
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
    # Overdue work: seaweed on the rock, then a cloud, and a second.
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
