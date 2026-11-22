"""A bird feeder.

Day: a branch reaches in from the left, two twigs and three leaves at its tip,
and a little house-shaped feeder hangs from it on a short cord, a perch dowel
across its front under the opening; below, the ground and a few seeds spilled
at the feeder's foot. Each finished task brings a small coral bird: to the
branch, to the dowel's ends, down to the ground either side of the seed, the
first few spread from the branch; Start sends seed falling from the feeder;
everything done fills the feeder, a heap of seed in its opening and husks on
the ground; a day with nothing planned leaves the branch and the feeder empty;
overdue work drifts a leaf down from the tip, then a cloud, then another. The
sun crosses the sky between the birds with the hour, sits low at the right at
dusk, and late at night is an ink moon.

Night: the same branch and feeder by a porch lamp on a bracket at the left,
its light the night's own; an owl sits on the branch near the tip. Each
finished task brings a moth to the lamp's light; everything done turns the
owl's eyes coral; Start turns its head; overdue work brings a cloud beside the
moon, a second at more.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import PEN, WOBBLE, curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

GROUND = 168.0
# The grass: a low bank resting on the ground line, a soft wash with no
# outline, most of it above the line and its lower lip just below, off to the
# left of the feeder and well inside the picture: (centre x, centre y, half
# width, half height).
BANK = (74.0, 161.0, 54.0, 11.0)
FX = 86.0                       # the feeder's middle
APEX = 76.0                     # the roof's peak
EAVE = 90.0                     # the roof's foot and the box's top
BOX = (74.0, 98.0, 117.0)       # the box's sides and its floor
HOLE = (FX, 100.5, 6.0)         # the opening
DOWEL_Y = 111.5
DOWEL = (50.0, 122.0)
TRAY = (71.0, 101.0, 123.0)     # the seed tray under the box: its sides and floor
MOTH_R = 6.0
MOTH_HALO = 11.0
MOON_R = 6.5
PLANNED = (('planned',),)
# Where the birds come, by their feet: on the branch (y from the branch), on
# the dowel's ends, on the ground line, and in front of it, below the ground
# line; each with the way it faces.
BRANCH_BIRDS = ((20.0, 1), (50.0, -1), (97.0, -1), (125.0, 1))
PERCH_BIRDS = ((57.0, 1), (115.0, 1))
GROUND_BIRDS = ((18.0, 1), (50.0, -1), (118.0, 1), (146.0, -1))
FRONT_BIRDS = ((34.0, 187.0, -1), (132.0, 187.0, 1))
# Spilled seed lying on the ground at the feeder's foot, each dot's ink at
# least 2 clear of the ground line's; the husks, under the falling seed, sit
# as low as its last step lets them.
SEEDS = ((70.5, 160.9), (76.0, 159.8), (97.5, 159.9), (101.5, 160.8))
HUSKS = ((83.5, 163.2), (89.5, 163.0))
# Overdue weather by day, clear of every sun and the birds' heads: (x, y, width).
DAY_CLOUDS = ((45.0, 15.0, 24.0), (111.0, 14.0, 24.0))


class BirdFeeder:
    id = 'feeder'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        ('branch', 'twig'), ('twig', 'leaf'), ('branch', 'leaf'), ('cord', 'branch'),
        ('cord', 'feeder'), ('dowel', 'feeder'), ('heap', 'feeder'),
        ('bird', 'branch'), ('bird', 'dowel'), ('bird', 'ground'),
        ('seed', 'ground'), ('husk', 'ground'),
        ('owl', 'branch'), ('owlhead', 'owl'),
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

def _bird(x: float, y: float, facing: int):
    """A small bird standing with its feet at (x, y): its body outline (a
    rounded body, a head bump, a short tail), and its eye, beak and legs."""
    def p(dx: float, dy: float):
        return (x + facing * dx, y + dy)

    body = loop(p(-10.5, -10.0), p(-6.5, -6.4), p(-2.5, -3.4), p(2.5, -3.6), p(6.0, -6.4),
                p(7.2, -9.6), p(7.4, -12.0), p(4.8, -14.4), p(1.8, -12.6), p(-3.0, -11.4),
                p(-7.5, -11.6), corners=(0,))
    marks = [
        line(p(4.4, -11.4), p(4.9, -11.2)),            # eye
        line(p(7.3, -12.2), p(10.0, -11.6)),           # beak
        line(p(-1.5, 0.3), p(-1.2, -3.4), p(1.4, -3.5), p(1.7, 0.3)),   # legs
    ]
    return body, marks


def _owl_head(ox: float, oy: float, turn: float):
    """The owl's head on its shoulders at (ox, oy), turned by `turn` (-1 left,
    0 to the front, 1 right): its outline with two ear tufts, its eyes and its
    beak."""
    s = 1.0 * turn
    f = 1.9 * turn
    head = loop((ox - 7.6 + s, oy), (ox - 8.4 + s, oy - 6.0), (ox - 7.2 + 1.6 * turn, oy - 12.2),
                (ox - 3.4 + s, oy - 9.8), (ox + s, oy - 9.4), (ox + 3.4 + s, oy - 9.8),
                (ox + 7.2 + 1.6 * turn, oy - 12.2), (ox + 8.4 + s, oy - 6.0), (ox + 7.6 + s, oy),
                (ox + s, oy + 0.9), corners=(2, 6))
    # Two round eyes that meet between them, drawn as one figure of eight.
    er, ey = 2.5, oy - 5.2
    m = (ox + f, ey)

    def lobe(cx: float, angles) -> list:
        return [(cx + er * math.cos(math.radians(a)), ey + er * math.sin(math.radians(a))) for a in angles]

    eyes = loop(m, *lobe(ox + f - er, (300, 240, 180, 120, 60)), m,
                *lobe(ox + f + er, (240, 300, 0, 60, 120)), corners=(0, 6))
    beak = line((ox + f - 0.9, oy - 2.6), (ox + f + 0.2 * turn, oy - 0.8), (ox + f + 0.9, oy - 2.6))
    return head, eyes, beak


def _owl_body(ox: float, oy: float, by: float):
    """The owl's body from its shoulders (ox, oy) down to its feet on the
    branch at `by`: an open U, the head closing its top, and two feet."""
    body = curve((ox - 7.6, oy), (ox - 9.0, oy + 5.0), (ox - 7.0, by - 4.0), (ox, by - 1.4),
                 (ox + 7.0, by - 4.0), (ox + 9.0, oy + 5.0), (ox + 7.6, oy))
    wing = curve((ox - 4.6, oy + 3.0), (ox - 4.2, oy + 7.5), (ox - 1.6, by - 4.8))
    feet = [line((ox - 2.6, by - 1.6), (ox - 2.8, by + 0.4)), line((ox + 2.6, by - 1.6), (ox + 2.8, by + 0.4))]
    return body, wing, feet


def _seed(x: float, y: float):
    """A falling seed: a small teardrop, point up."""
    return loop((x, y - 2.2), (x + 1.4, y + 0.4), (x, y + 1.6), (x - 1.4, y + 0.4), corners=(0,))


# ── the shared picture ──────────────────────────────────────────────────────

def _branch_top(samples: list, x: float) -> float:
    """The branch's upper edge at x, as the pen draws it."""
    near = [py for px, py in samples if abs(px - x) <= 0.8]
    return min(near)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same branch and
    feeder after dark."""
    # The branch: one stroke out along its top, round the tip and back along
    # its underside, thick at the left edge and tapering to the tip.
    top = [(0.0, 41.0), (30.0, 40.6 + r.uniform(-0.6, 0.6)), (60.0, 42.4), (86.0, 43.4),
           (112.0, 41.8), (128.0, 40.6), (140.0, 39.6)]
    under = [(128.0, 44.6), (112.0, 46.8), (86.0, 49.0), (60.0, 48.6), (30.0, 48.2), (0.0, 49.8)]
    branch = curve(*top, *under, corners=(len(top) - 1,))
    bs = k.samples(branch, step=1.0)
    # Two twigs off the underside near the tip, a leaf at each end and one
    # more hanging under the branch, all below it, so the low dusk sun at the
    # right and the owl on top have the air above the tip.
    twigs = [curve((117.0, 46.2), (121.0, 51.0), (123.5, 56.5)),
             curve((136.0, 41.9), (142.0, 44.0), (148.0, 45.4))]
    leaves = [((123.5, 56.5), 10.5, math.radians(78 + r.uniform(-6, 6))),
              ((148.0, 45.4), 10.5, math.radians(28 + r.uniform(-6, 6))),
              ((106.0, 47.6), 10.0, math.radians(112 + r.uniform(-6, 6)))]

    ground = curve((0.0, GROUND + 0.6), (80.0, GROUND - 0.6), (160.0, GROUND + 0.4))
    bank = k.blob(*BANK, r.fork('bank'), n=12, wobble=0.12)

    # The birds are placed only by the day, which draws them, from their own
    # fork of this stream.
    def slots() -> list:
        rb = r.fork('birds')
        birds = []
        for x, facing in BRANCH_BIRDS:
            x += rb.uniform(-0.8, 0.8)
            birds.append((x, _branch_top(bs, x) + 0.4, facing))
        for x, facing in PERCH_BIRDS:
            birds.append((x + rb.uniform(-1.0, 1.0), DOWEL_Y - 0.2, facing))
        gs = k.samples(ground, step=1.0)
        for x, facing in GROUND_BIRDS:
            x += rb.uniform(-1.5, 1.5)
            gy = min((abs(px - x), py) for px, py in gs)[1]
            birds.append((x, gy + 0.3, facing))
        for x, y, facing in FRONT_BIRDS:
            birds.append((x + rb.uniform(-1.5, 1.5), y, facing))
        order = k.spread([(x, y) for x, y, _ in birds], (birds[0][0], birds[0][1]))
        by_point = {(x, y): f for x, y, f in birds}
        return [(x, y, by_point[(x, y)]) for x, y in order]

    owl_x = 119.0 + r.uniform(-2.0, 2.0)
    owl_by = _branch_top(bs, owl_x) + 0.3
    return {
        'branch': branch, 'twigs': twigs, 'leaves': leaves,
        'ground': ground, 'bank': bank, 'slots': slots,
        'owl': (owl_x, owl_by - 15.0, owl_by),
        'moon_spot': (20.0 + r.uniform(-2, 2), 17.5 + r.uniform(-0.5, 0.5)),
    }


def _feeder_strokes() -> list:
    """The feeder's own ink: roof, box, opening and tray."""
    x0, x1, floor = BOX
    t0, t1, tray = TRAY
    return [
        poly((FX - 18, EAVE), (FX, APEX), (FX + 18, EAVE)),
        line((x0, EAVE), (x0, floor), (x1, floor), (x1, EAVE)),
        k.ring(*HOLE, 10),
        line((t0, floor), (t0, tray), (t1, tray), (t1, floor)),
    ]


def _scene(b: SketchBuilder, s: dict) -> None:
    """The branch, the feeder on its cord, the ground and the spilled seed."""
    b.line(s['branch'], part='branch')
    for i, t in enumerate(s['twigs']):
        b.line(t, part=f'twig:{i}')
    for i, ((x, y), length, a) in enumerate(s['leaves']):
        k.draw_leaf(b, x, y, length, a, part=f'leaf:{i}')
    b.line(line((FX, 47.6), (FX, APEX + 0.6)), part='cord')
    for st in _feeder_strokes():
        b.line(st, part='feeder')
    b.line(line((DOWEL[0], DOWEL_Y), (DOWEL[1], DOWEL_Y + 0.3)), part='dowel')
    b.line(s['ground'], part='ground')
    for x, y in SEEDS:
        b.line(line((x - 0.5, y), (x + 0.5, y + 0.2)), when=PLANNED, part='seed')


def _ground_wash(b: SketchBuilder, s: dict) -> None:
    b.wash(s['bank'], part='ground')


# ── day ─────────────────────────────────────────────────────────────────────

def _sky_day(b: SketchBuilder, s: dict, r: Rng) -> None:
    """The hour, between the birds' heads on the branch, and 6 units clear of
    the branch itself."""
    k.sun(b, r.fork('sun-m'), 16, 12, 4.8, when=(k.MORNING,), rays=5, ray_len=3.2)
    k.sun(b, r.fork('sun-n'), 74, 12, 5.0, when=(k.MIDDAY,), rays=5, ray_len=3.2)
    k.sun(b, r.fork('sun-a'), 146, 13, 5.0, when=(k.AFTERNOON,), rays=5, ray_len=3.2)
    # Dusk: ground birds stand on the ground line at the right, so the sun
    # sets low in the sky there instead, small, with no horizon.
    k.sun(b, r.fork('sun-d'), 150, 25, 3.6, when=(k.DUSK,), rays=5, ray_gap=2.4, ray_len=2.8)
    mx, my = 16.0, 13.0
    k.moon(b, mx, my, 6.0, glow=False, clouds=0, when=(k.LATE,))
    k.stars(b, r.fork('late-stars'), 3, (8, 7, 152, 22),
            avoid=((mx, my, 13), *((x, y, w * 0.6 + 4) for x, y, w in DAY_CLOUDS)),
            when=(k.LATE,), part='star')
    for level, (x, y, w) in enumerate(DAY_CLOUDS, start=2):
        k.cloud(b, x, y, w, when=(('overdue', level),), part=f'cloud:{level - 1}')


def _fall(frame: int, child: SketchBuilder) -> None:
    """Start: seed falls from the feeder's tray, three seeds stepping down
    the column under it from the tray's floor to just above the husks on the
    ground."""
    for j, x in enumerate((85.0, 88.6, 86.6)):
        y = TRAY[2] + 7.0 + 5.2 * ((frame + 2 * j) % 6)
        child.line(_seed(x, y), part='fall')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground_wash(b, s)
    _sky_day(b, s, r)
    _scene(b, s)
    # Everything done: the feeder is full, a heap of seed in its opening, and
    # husks on the ground at its foot.
    done = (('allDone',),)
    hx, hy, hr = HOLE
    mound = [(hx - 5.8, hy + 1.4), (hx - 3.0, hy - 1.4), (hx, hy - 2.2), (hx + 3.0, hy - 1.4),
             (hx + 5.8, hy + 1.4)]
    under = [(hx + hr * math.cos(math.radians(a)), hy + hr * math.sin(math.radians(a)))
             for a in (30, 60, 90, 120, 150)]
    b.wash(loop(*mound, *under), when=done, part='heap')
    b.line(curve(*mound), when=done, part='heap')
    for dx, dy in ((-2.8, 1.2), (1.4, 0.6), (-0.4, 3.6)):
        b.line(line((hx + dx - 0.5, hy + dy), (hx + dx + 0.5, hy + dy + 0.2)), when=done, part='heap')
    # Husks: the split halves of eaten seed, small cups lying on the ground.
    for x, y in HUSKS:
        b.line(curve((x - 1.7, y - 0.6), (x, y + 0.7), (x + 1.7, y - 0.6)), when=done, part='husk')
    # Overdue: a leaf drifts down below the tip.
    k.draw_leaf(b, 140.0, 122.0, 12.0, math.radians(150), when=(('overdue', 1),), part='drift')
    for i, (x, y, facing) in enumerate(s['slots']()):
        when = (('reward', i), *PLANNED)
        body, marks = _bird(x, y, facing)
        b.filled(body, when=when, part=f'bird:{i}')
        for m in marks:
            b.line(m, when=when, part=f'bird:{i}')
        b.anchor(i, x, y)
    b.ambient(1.0, (('focus',),), _fall)


# ── night ───────────────────────────────────────────────────────────────────

LAMP = (26.5, 68.0)             # the bracket arm's end, where the lamp hangs
# The highest a moth flies: clear of the branch's underside (49.8 at its
# lowest, at the left edge) by a moth, a pen and the wobble of both.
TOP_MOTH = 61.0
LOW_MOTH = 150.0                # and the lowest, well above the ground
MOTH_REACH = 58.0               # how far from the lamp's light a moth strays
# Twelve places for the moths, packed by hand inside MOTH_REACH of the lamp's
# light (the closest pair is 19.8 apart; see the note in _night).
MOTH_SLOTS = ((11.5, 120.3), (11.9, 83.1), (18.6, 101.8), (21.9, 138.5), (31.9, 119.0),
              (35.5, 61.5), (38.5, 100.1), (41.7, 80.4), (42.1, 136.7), (56.0, 63.6),
              (56.9, 123.4), (57.1, 93.1))


def _lamp_strokes() -> list:
    lx, ly = LAMP
    return [
        line((0.0, ly), (lx, ly), (lx, ly + 3.4)),                         # the arm and its hook
        line((0.0, ly + 10.0), (lx - 12.0, ly)),                           # the brace
        poly((lx - 5.4, ly + 6.8), (lx, ly + 3.4), (lx + 5.4, ly + 6.8)),  # the cap
        line((lx - 4.2, ly + 6.8), (lx - 3.2, ly + 18.6), (lx + 3.2, ly + 18.6), (lx + 4.2, ly + 6.8)),
        loop((lx, ly + 10.0), (lx + 1.4, ly + 13.4), (lx, ly + 15.2), (lx - 1.4, ly + 13.4),
             corners=(0,)),                                                # the flame
    ]


def _head(s: dict, turn: float, child: SketchBuilder, when: tuple, part: str, *,
          coral: bool = True) -> None:
    ox, oy, _ = s['owl']
    head, eyes, beak = _owl_head(ox, oy, turn)
    child.line(head, when=when, part=part)
    child.line(beak, when=when, part=part)
    if not coral:
        child.line(eyes, when=when, part=part)
        return
    child.line(eyes, when=(*when, ('notAllDone',)), part=part)
    # Everything done: the owl's eyes are coral.
    child.filled(eyes, when=(*when, ('allDone',)), part=part, paper='glint')


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _ground_wash(b, s)
    mx, my = s['moon_spot']
    # The clouds beside the moon: the first beside it, the second a step
    # further on and lower, still above the branch.
    clouds = k.moon(b, mx, my, MOON_R, clouds=2, second=(6.6, 2.3))
    # The porch lamp and its light, whatever the state.
    lx, ly = LAMP
    b.glow(k.ring(lx, ly + 13.0, 27.0, 12), part='lamp')
    b.glow(k.ring(lx, ly + 13.0, 9.0, 9), part='lamp')
    for st in _lamp_strokes():
        b.line(st, part='lamp')
    _scene(b, s)
    # The owl, near the tip.
    ox, oy, by = s['owl']
    body, wing, feet = _owl_body(ox, oy, by)
    for st in (body, wing, *feet):
        b.line(st, part='owl')
    _head(s, 0, b, (('idle',),), 'owl')

    # Moths crowd round the lamp: twelve fixed places within MOTH_REACH of its
    # light, under the branch and clear of the feeder and the owl. Random
    # scatter cannot place twelve this far apart inside the reach (it failed on
    # most days), so the places are packed by hand (closest pair 19.8 apart,
    # the floor is 16.75) and each one moves by at most a unit a day.
    light = (LAMP[0], LAMP[1] + 13.0)
    rm = r.fork('moths')
    pts = [(x + rm.jitter(1.0), y + rm.jitter(1.0)) for x, y in MOTH_SLOTS]
    moths = k.spread(pts, light)
    k.stars(b, r.fork('stars'), 3, (44, 8, 156, 30),
            avoid=((mx, my, 20), *clouds, (ox, oy - 6, 18)), part='star')
    for i, (x, y) in enumerate(moths):
        k.glow_dot(b, x, y, MOTH_R, halo=MOTH_HALO, when=(('reward', i), *PLANNED), part=f'moth:{i}', glass=False)
        b.anchor(i, x, y)

    def turn(frame: int, child: SketchBuilder) -> None:
        # Start: the owl looks left, to the front, right and back again. Its
        # eyes are ink while it turns, whatever the state: the loop's marks
        # carry no condition of their own.
        _head(s, (-1, 0, 1, 1, 0, -1)[frame], child, (), 'owlhead', coral=False)
    b.ambient(1.0, (('focus',),), turn)
