"""A washing line.

Day: two posts and two lines across the middle of the picture, against a sage
hedge, a basket at the foot. Each finished task pegs out a coral garment, the
first few spread along both lines; Start sends a gust over the lines; with
everything done the basket stands empty and a bird sits on a post; a day with
nothing planned shows the bare lines over an empty basket; overdue work brings a
cloud, and one more at each further level. The sun crosses the sky with the hour, sets on a
far hill, and late at night is an ink moon.

Night: the same posts and lines, beside a house on the far hill with a lit
window, the laundry back in its basket. Each finished task strings a lit bulb
on the line; everything done empties the basket and lights the house's second
window, coral; Start sends a moth fluttering by the house; overdue work brings
a cloud beside the moon, a second a step beyond it at more.

Paper (the desk unit, drawn for ink): the same posts and lines at midday. The
hedge is a light tone under a leafy top edge in the fine pen; the basket in
front of it is a mid tone, wicker; the posts are solid. The garments are
hatched inside their outlines, each with its pegs; with everything done the
basket is empty and the bird on the post is a solid silhouette.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import curve, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import Composition, DayState
from . import _kit as k

GROUND = 176.0
LEFT, RIGHT = 18.0, 142.0
TOPS = (60.0, 100.0)      # where each line meets the posts
CAP = 52.0                # the posts' cross-pieces
SAG = 9.0
BULB_R = 6.0


def _sag(x: float, y0: float) -> float:
    t = (x - LEFT) / (RIGHT - LEFT)
    return y0 + SAG * 4 * t * (1 - t)


def _slope(x: float) -> float:
    t = (x - LEFT) / (RIGHT - LEFT)
    return math.atan(SAG * 4 * (1 - 2 * t) / (RIGHT - LEFT))


class WashingLine:
    id = 'washing-line'
    since = date(2026, 1, 1)
    until = None
    PAPER = True
    JOINS = frozenset(frozenset(p) for p in (
        ('post', 'line'), ('post', 'cap'), ('post', 'ground'), ('basket', 'ground'),
        ('tuft', 'ground'), ('garment', 'line'), ('bird', 'cap'), ('heap', 'basket'),
        ('bulb', 'line'), ('house', 'hill'), ('sun', 'hill'),
        ('bird', 'post'), ('hedge', 'ground'),
    ))

    def render(self, state: DayState, theme: Composition, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        elif theme == 'paper':
            _paper(b, s, rng.fork('paper'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    slots = []
    for row in (0, 1):
        for col in range(6):
            x = LEFT + 17.5 + col * 17.8 + r.uniform(-0.8, 0.8)
            slots.append((x, _sag(x, TOPS[row])))
    slots = k.spread(slots, (LEFT + 15, TOPS[0]))
    basket = (24.0, 52.0)
    tufts = k.place_along(r.fork('tufts'), 4, 60, 128, avoid=((100, 132),), gap=12)
    return {
        'slots': slots,
        'kinds': [r.choice(['shirt', 'socks', 'towel', 'dress']) for _ in range(k.REWARDS)],
        'basket': basket,
        'tufts': tufts,
        'moon_spot': r.choice([(30.0, 24.0), (80.0, 20.0), (128.0, 24.0)]),
    }


def _frame(b: SketchBuilder, s: dict) -> None:
    for x in (LEFT, RIGHT):
        b.line(line((x, GROUND + 0.5), (x + 0.6, CAP + 0.4)), part='post')
        b.line(line((x - 7, CAP), (x + 7, CAP - 0.5)), part='cap')
    for y0 in TOPS:
        pts = [(x, _sag(x, y0)) for x in (LEFT, 49, 80, 111, RIGHT)]
        b.line(curve(*pts), part='line')
    b.line(curve((4, GROUND + 1.2), (80, GROUND - 0.8), (156, GROUND + 1.4)), part='ground')
    for i, x in enumerate(s['tufts']):
        b.line(curve((x - 3, GROUND), (x - 1, GROUND - 4.6), (x, GROUND - 6.4)), part=f'tuft:{i}')
        b.line(curve((x + 1.4, GROUND), (x + 3, GROUND - 4), (x + 4.6, GROUND - 5.4)), part=f'tuft:{i}')


def _basket(b: SketchBuilder, s: dict) -> None:
    x0, x1 = s['basket']
    g = GROUND - 0.4
    b.line(loop((x0, g - 15), (x1, g - 15), (x1 - 3, g), (x0 + 3, g), corners=(0, 1, 2, 3)), part='basket')
    b.line(curve((x0 + 1.6, g - 10), ((x0 + x1) / 2, g - 8.4), (x1 - 1.6, g - 10)), part='basket')
    b.line(curve((x0 + 2.6, g - 5), ((x0 + x1) / 2, g - 3.6), (x1 - 2.6, g - 5)), part='basket')


def _garment(kind: str, x: float, y: float):
    """One garment hanging from (x, y): its top follows the line's slope, its
    sides hang straight down."""
    # At most 12 wide, so neighbours on a line keep paper between them.
    if kind == 'shirt':
        pts = ((x - 4.2, y), (x - 1.6, y), (x, y + 2), (x + 1.6, y), (x + 4.2, y), (x + 6, y + 5),
               (x + 4.2, y + 7), (x + 4, y + 18), (x - 4, y + 18), (x - 4.2, y + 7), (x - 6, y + 5))
    elif kind == 'socks':
        pts = ((x - 5.4, y), (x - 0.6, y), (x - 0.6, y + 10), (x + 4.4, y + 13), (x + 3, y + 17.5),
               (x - 5.4, y + 12.5))
    elif kind == 'towel':
        pts = ((x - 5.5, y), (x + 5.5, y), (x + 5.8, y + 19), (x - 5.2, y + 19))
    else:
        pts = ((x - 3, y), (x + 3, y), (x + 3.6, y + 6), (x + 6, y + 20), (x - 6, y + 20), (x - 3.6, y + 6))
    t = math.tan(_slope(x))
    return poly(*[(px, py + t * (px - x)) for px, py in pts])


def _pegs(b: SketchBuilder, x: float, y: float, *, when: tuple, part: str) -> None:
    t = math.tan(_slope(x))
    for dx in (-3.8, 3.8):
        px, py = x + dx, y + t * dx
        b.line(line((px, py - 2.6), (px + 0.2, py + 3.2)), when=when, part=part)


def _gusts(frame: int, child: SketchBuilder) -> None:
    """Start: a gust passes over the lines, curling down, clear of the weather."""
    for j, (y, x0, span, up) in enumerate(((44.0, 28.0, 30.0, 1),)):
        x = x0 + (frame * 5 + j * 15) % span
        child.line(curve((x, y), (x + 14, y + up * 1.2), (x + 26, y - up * 0.4), (x + 34, y + up * 1.6),
                         (x + 37.4, y + up * 5.0), (x + 34, y + up * 7.4), (x + 31, y + up * 5.2)),
                   part='gust')
        child.line(curve((x + 6, y + 4.8), (x + 16, y + 5.8), (x + 25, y + 5.0)), part='gust')


def _sky_day(b: SketchBuilder, s: dict, r: Rng) -> None:
    k.sun(b, r.fork('sun-m'), 20, 22, 5.6, when=(k.MORNING,))
    k.sun(b, r.fork('sun-n'), 84, 16, 6.0, when=(k.MIDDAY,))
    k.sun(b, r.fork('sun-a'), 138, 18, 5.6, when=(k.AFTERNOON,))
    # Dusk: the sun sets on a far hill between the posts.
    b.line(curve((92, 150), (112, 144.5), (134, 147.5)), when=(k.DUSK,), part='hill')
    k.low_sun(b, r.fork('sun-d'), 113, 145.4, 6.0, when=(k.DUSK,))
    x, y = s['moon_spot']
    k.moon(b, x, y, 6.0, glow=False, clouds=0, when=(k.LATE,))
    clouds = ((50, 34, 28), (110, 40, 24), (60, 14, 18))
    k.stars(b, r.fork('late-stars'), 3, (8, 8, 152, 36),
            avoid=((x, y, 18), (RIGHT - 8, CAP - 12, 16), *((cx, cy, w * 0.75 + 4) for cx, cy, w in clouds)),
            when=(k.LATE,), part='star')
    # Overdue work: weather, kept clear of every sun.
    for level, (cx, cy, w) in enumerate(clouds, start=1):
        k.cloud(b, cx, cy, w, when=(('overdue', level),), part=f'cloud:{level}')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    hedge = k.blob(80, 142, 66, 30, r.fork('hedge'), n=12, wobble=0.06)
    b.wash(hedge, part="hedge")
    _sky_day(b, s, r)
    _frame(b, s)
    _basket(b, s)
    x0, x1 = s['basket']
    g = GROUND - 0.4
    b.line(curve((x0 + 4, g - 15), (x0 + 9, g - 21), (x0 + 15, g - 18), (x1 - 8, g - 22), (x1 - 4, g - 15)),
           when=(('planned',), ('notAllDone',)), part='heap')
    for i, ((x, y), kind) in enumerate(zip(s['slots'], s['kinds'])):
        when = (('reward', i),)
        b.filled(_garment(kind, x, y + 0.8), when=when, part=f'garment:{i}')
        _pegs(b, x, y, when=when, part=f'garment:{i}')
        b.anchor(i, x, y)
    k.bird(b, RIGHT, CAP - 0.6, when=(('allDone',),), facing=-1)
    b.ambient(1.0, (('focus',),), _gusts)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    # The far hill and the house on it: its lit window is the light the line hangs by.
    b.wash(k.blob(93, 168, 54, 13, r.fork('ground'), n=12, wobble=0.05), part='ground')
    b.line(curve((70, 154), (98, 148.4), (122, 149), (134, 151)), part='hill')
    hx, hy = 120.0, 149.0
    b.line(line((hx - 11, hy), (hx - 11, hy - 13), (hx, hy - 21), (hx + 11, hy - 13), (hx + 11, hy)), part='house')
    win1 = poly((hx - 8.6, hy - 11), (hx - 2.4, hy - 11), (hx - 2.4, hy - 4.8), (hx - 8.6, hy - 4.8))
    win2 = poly((hx + 2.4, hy - 11), (hx + 8.6, hy - 11), (hx + 8.6, hy - 4.8), (hx + 2.4, hy - 4.8))
    b.glow(k.ring(hx - 5.5, hy - 7.9, 11, 10), part='house')
    b.line(win1, part='house')
    b.glow(k.ring(hx + 5.5, hy - 7.9, 11, 10), when=(('allDone',),), part='house')
    b.accent(win2, when=(('allDone',),), part='house', paper='glint')
    b.line(win2, part='house')
    x, y = s['moon_spot']
    clouds = k.moon(b, x, y, 6.5)
    k.stars(b, r.fork('stars'), 4, (8, 6, 152, 40), avoid=((x, y + 6, 24), *clouds), part='star')
    _frame(b, s)
    _basket(b, s)
    # The day's laundry is in the basket until it is all done.
    x0, x1 = s['basket']
    g = GROUND - 0.4
    b.line(curve((x0 + 4, g - 15), (x0 + 9, g - 21), (x0 + 15, g - 18), (x1 - 8, g - 22), (x1 - 4, g - 15)),
           when=(('planned',), ('notAllDone',)), part='heap')
    # A bulb is strung only when it is lit: the line shows what is done, not
    # what is missing.
    for i, (bx, by) in enumerate(s['slots']):
        cy = by + 3 + BULB_R
        lit = (('reward', i),)
        b.line(line((bx, by), (bx, by + 3)), when=lit, part=f'bulb:{i}')
        k.glow_dot(b, bx, cy, BULB_R, halo=11, when=lit, part=f'bulb:{i}')
        b.anchor(i, bx, by + 3)

    def moth(frame: int, child: SketchBuilder) -> None:
        # A small loop in the clear air left of the house: under the bulbs,
        # over the hill, clear of the walls. Two wings, so it is a moth.
        a = 2 * math.pi * frame / 6
        mx, my = 78 + 9 * math.cos(a), 136 + 4 * math.sin(a)
        child.line(loop((mx, my), (mx - 5.5, my - 4), (mx - 6, my + 1.5), corners=(0,)), part='moth')
        child.line(loop((mx, my), (mx + 5.5, my - 4), (mx + 6, my + 1.5), corners=(0,)), part='moth')
    b.ambient(1.0, (('focus',),), moth)


# ── paper: the desk unit's composition, drawn for ink ───────────────────────

SHADE_INSET = 3.6         # a tone keeps this far inside the lines round it
HEDGE = (LEFT + 7, RIGHT - 7)   # the hedge between the posts
# Its top at the middle, under the longest garment on the lower line, and how
# much lower it is at the posts.
HEDGE_TOP = TOPS[1] + SAG + 34.0
HEDGE_FALL = 10.0
HEDGE_BUMPS = 7
POST_W = 2.2              # a solid post's half-width at the foot
HEDGE_SLIVER = 40.0       # a piece of the hedge's tone smaller than this (square units) is left out


def _hedge_height(t: float) -> float:
    """The hedge's top across its width (t 0 to 1): highest in the middle,
    lower toward the posts, and down to the ground at either end."""
    g = GROUND - 1.0
    top = HEDGE_TOP + HEDGE_FALL * (2 * t - 1) ** 2
    return g - (g - top) * min(1.0, 5 * t, 5 * (1 - t)) ** 0.5


def _hedge_top(r: Rng) -> tuple[list, list]:
    """The hedge's leafy top: a row of bumps from the ground and back down to
    it. Its points and the cusps between the bumps."""
    x0, x1 = HEDGE
    pts, corners = [], []
    n = HEDGE_BUMPS
    for i in range(n + 1):
        t = i / n
        corners.append(len(pts))
        jog = 0.0 if i in (0, n) else r.uniform(-1, 1)
        pts.append((x0 + (x1 - x0) * t, _hedge_height(t) + jog))
        if i < n:
            tm = (i + 0.5) / n
            pts.append((x0 + (x1 - x0) * tm, _hedge_height(tm) - r.uniform(3.5, 5)))
    return pts, corners


def _clip(pts: list, keep) -> list:
    """The polygon cut to one side of a line (Sutherland-Hodgman): `keep(p)`
    is how far p is inside, negative outside, and linear in p."""
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        da, db = keep(a), keep(b)
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _post(x: float):
    """A post as a solid, a little narrower at the cap."""
    w0, w1 = POST_W, POST_W * 0.8
    mid = (GROUND + CAP) / 2
    return loop((x - w0, GROUND + 0.5), (x + w0, GROUND + 0.5), (x + 0.3 + (w0 + w1) / 2, mid),
                (x + 0.6 + w1, CAP + 0.4), (x + 0.6 - w1, CAP + 0.4), (x + 0.3 - (w0 + w1) / 2, mid),
                corners=(0, 1, 3, 4))


def _paper(b: SketchBuilder, s: dict, r: Rng) -> None:
    """The day at midday, drawn for ink: tone where the hedge and the basket
    have mass, no wash, no boil, no ambient (the desk unit pins the hour to
    noon)."""
    k.sun(b, r.fork('sun-n'), 84, 16, 6.0, when=(k.MIDDAY,))
    top, corners = _hedge_top(r.fork('hedge'))
    x0, x1 = HEDGE
    g = GROUND - SHADE_INSET
    bx0, bx1 = s['basket']
    bg = GROUND - 0.4
    i = SHADE_INSET
    # The tone comes to the cusps of the leafy top, so its bumps stay paper,
    # and the hedge stands behind the basket: its tone goes round it, clear of
    # the laundry heaped in it.
    hedge = [(x, min(y + i * 0.6, g)) for x, y in top[::2]] + [(x1, g), (x0, g)]
    over = bg - 22 - i
    for piece in (_clip(hedge, lambda p: p[0] - (bx1 + i)),
                  _clip(_clip(hedge, lambda p: (bx1 + i) - p[0]), lambda p: over - p[1])):
        area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(piece, piece[1:] + piece[:1]))) / 2
        if area >= HEDGE_SLIVER:
            b.shade(poly(*piece), 'light', part='hedge')
    b.shade(poly((bx0 + i, bg - 15 + i), (bx1 - i, bg - 15 + i), (bx1 - 3 - i * 0.8, bg - i * 0.6),
                 (bx0 + 3 + i * 0.8, bg - i * 0.6)), 'mid', part='basket')
    # Its leafy top goes behind the basket: the line starts at the first cusp clear of it.
    j = next(c for c in corners if top[c][0] >= bx1 + k.MIN_GAP)
    b.line(curve(*top[j:], corners=[c - j for c in corners if c >= j]), part='hedge', weight='fine')
    for x in (LEFT, RIGHT):
        b.solid(_post(x), part='post')
    _frame(b, s)
    _basket(b, s)
    b.line(curve((bx0 + 4, bg - 15), (bx0 + 9, bg - 21), (bx0 + 15, bg - 18), (bx1 - 8, bg - 22), (bx1 - 4, bg - 15)),
           when=(('planned',), ('notAllDone',)), part='heap')
    for n, ((x, y), kind) in enumerate(zip(s['slots'], s['kinds'])):
        when = (('reward', n),)
        b.filled(_garment(kind, x, y + 0.8), when=when, part=f'garment:{n}')
        _pegs(b, x, y, when=when, part=f'garment:{n}')
        b.anchor(n, x, y)
    # Everything done: the bird on the post, a solid silhouette.
    strokes = k.bird_strokes(RIGHT, CAP - 0.6, facing=-1)
    done = (('allDone',),)
    for st in strokes[:2]:
        b.solid(st, when=done, part='bird')
    for st in strokes[2:]:
        b.line(st, when=done, part='bird')
