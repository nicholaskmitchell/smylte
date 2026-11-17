"""A bookshelf.

Day: two shelf boards on the wall under a small framed picture, a few old
books at the left of each, a bookend and a potted plant on the upper board.
Each finished task stands a coral-spined book on a board, the first few
alternating between the two; Start turns a page of the book lying open on the
lower books; everything done brings a cat to sleep on top of the upper books;
a day with nothing planned leaves the slots empty and one book lying flat on
the lower board; overdue work tips a book over against its neighbour, then
drops one on the floor, then a second on top of it. The hour is in the
picture: its sun crosses with the day, sets on a hill, and late at night is a
moon among two stars.

Night: the same shelves under a wall lamp in the corner, whose light falls in a
cone across the upper books and pools on the board. The picture holds the moon
and two stars. Each finished task stands a coral book in a soft glow;
everything done brings the cat to sleep in the lamplight; Start turns the page.
"""
from __future__ import annotations

import math
from datetime import date

from ..pen import HAND_MIN_SEGMENT, curve, ellipse, line, loop, poly
from ..rng import Rng
from ..scene import Sketch, SketchBuilder
from ..state import DayState, Theme
from . import _kit as k

UPPER, LOWER = 92.0, 162.0       # the boards' top lines; each front edge is 5 below
FRONT = 5.0
BOARD = (7.0, 153.0)
FLOOR = 192.0
BRACKETS = (46.0, 114.0)
FRAME = (58.0, 8.0, 104.0, 40.0)
NAIL = (81.0, 3.4)
SHELF_BOOKS = (12.0, 39.5)       # the old books on the upper board
REWARD_W = 10.0
# Reward slots: left edges. Five on the upper board (three by the old books,
# two past the plant), seven on the lower; each 5 clear of the next.
UPPER_SLOTS = (44.5, 59.5, 74.5, 124.5, 139.5)
LOWER_SLOTS = tuple(48.0 + i * (92.0 / 6) for i in range(7))
BOOKEND = 89.5
POT = (103.5, 119.5)
LEAN = math.radians(12.5)
PAGE = 14.0
PLANNED = ('planned',)


def _ruled(*pts, closed: bool = False):
    """Straight segments the hand leaves unbowed: books and the frame stand
    close to their neighbours, and a bow would carry a side into the next.
    Each segment is cut into pieces shorter than the hand's shortest bowed
    one, so it stays a ruled line, and cheap to draw."""
    ring_ = list(pts) + ([pts[0]] if closed else [])
    out = [ring_[0]]
    for (x0, y0), (x1, y1) in zip(ring_, ring_[1:]):
        n = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / (HAND_MIN_SEGMENT - 2)))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return poly(*out[:-1]) if closed else line(*out)


class Bookshelf:
    id = 'bookshelf'
    since = date(2026, 1, 1)
    until = None
    JOINS = frozenset(frozenset(p) for p in (
        # The brackets are drawn in the board's own stroke, so they need no join.
        ('book', 'board'), ('book',), ('rbook', 'board'), ('bookend', 'board'),
        ('plant', 'board'), ('cat', 'book'), ('frame', 'nail'),
        ('frame', 'hill'), ('sun', 'hill'), ('flat', 'board'), ('pile', 'floor'), ('pile',),
        ('page', 'book'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _order(upper: list, lower: list) -> list:
    """The slots farthest-first, alternating boards while both have some left,
    from the upper board's first slot."""
    pools = [list(upper), list(lower)]
    order = [pools[0].pop(0)]
    turn = 1
    while pools[0] or pools[1]:
        pool = pools[turn] if pools[turn] else pools[1 - turn]
        nxt = max(pool, key=lambda p: min(math.dist(p, q) for q in order))
        pool.remove(nxt)
        order.append(nxt)
        turn = 1 - turn
    return order


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same shelf after dark."""
    # The upper old books: three, their tops close enough that a cat lies
    # along them.
    x0, x1 = SHELF_BOOKS
    w1, w2 = r.uniform(8.5, 10.0), r.uniform(8.0, 9.5)
    tall = r.uniform(40.0, 44.0)
    heights = [tall - r.uniform(0.0, 3.5) for _ in range(3)]
    heights[r.randint(0, 2)] = tall
    edges = [x0, x0 + w1, x0 + w1 + w2, x1]
    # A run of neighbours (maybe none) carries a second band.
    first, run = r.randint(0, 2), r.randint(0, 2)
    upper = [(edges[i], edges[i + 1], heights[i], r.uniform(6.0, 10.0), first <= i < first + run)
             for i in range(3)]
    # The lower old books: two side by side and a third a step apart, the one
    # that tips over.
    wa = r.uniform(8.5, 9.0)
    first, run = r.randint(0, 1), r.randint(0, 2)
    lower = [(12.0, 12.0 + wa, r.uniform(34.0, 36.0), r.uniform(6.0, 9.0), first <= 0 < first + run),
             (12.0 + wa, 28.0, r.uniform(34.0, 36.0), r.uniform(6.0, 9.0), first <= 1 < first + run),
             (32.75, 39.75, r.uniform(34.0, 36.0), r.uniform(6.0, 9.0), False)]
    slots = ([(x, UPPER, r.uniform(36.0, 44.0)) for x in UPPER_SLOTS]
             + [(x, LOWER, r.uniform(36.0, 44.0)) for x in LOWER_SLOTS])
    by_anchor = {(x + REWARD_W / 2, y): (x, y, h) for x, y, h in slots}
    anchors = _order([(x + REWARD_W / 2, UPPER) for x in UPPER_SLOTS],
                     [(x + REWARD_W / 2, LOWER) for x in LOWER_SLOTS])
    return {
        'upper': upper, 'lower': lower,
        'slots': [by_anchor[a] for a in anchors],
        'leaves': [r.uniform(-4, 4) for _ in range(3)],
        'moon': (69.5 + r.uniform(-1, 1), 22.0 + r.uniform(-1, 1)),
    }


# ── the shelf ───────────────────────────────────────────────────────────────

def _boards(b: SketchBuilder) -> None:
    left, right = BOARD
    for y in (UPPER, LOWER):
        # One stroke round the board and down round its two brackets, its
        # two long sides kept apart by the front's depth, not bowed toward
        # each other by the hand. The top sags a little and never rises, so
        # nothing standing on it is cut by a line bowing up into it.
        f = y + FRONT
        (b0, b1) = BRACKETS
        b.line(loop((left, y), (43, y + 0.4), (80, y + 0.6), (117, y + 0.5), (right, y + 0.2),
                    (right, f + 0.2), (b1 + 4.5, f + 0.4), (b1, f + 8.5), (b1 - 4.5, f + 0.5),
                    (80, f + 0.6), (b0 + 4.5, f + 0.4), (b0, f + 8.5), (b0 - 4.5, f + 0.2), (left, f),
                    corners=(0, 4, 5, 6, 7, 8, 10, 11, 12, 13)), part='board')
    b.line(curve((2, FLOOR + 0.3), (80, FLOOR - 0.5), (158, FLOOR + 0.4)), part='floor')


def _frame(b: SketchBuilder) -> None:
    x0, y0, x1, y1 = FRAME
    b.line(_ruled((x0, y0), (x1, y0), (x1, y1), (x0, y1), closed=True), part='frame')
    nx, ny = NAIL
    b.line(line((x0 + 7, y0), (nx, ny + 0.6), (x1 - 7, y0)), part='frame')
    b.line(k.ring(nx, ny, 1.2, 6), part='nail')


def _book(b: SketchBuilder, x0: float, x1: float, base: float, h: float, band: float | None, *,
          when: tuple = (), part: str, turn: float = 0.0) -> None:
    """An old book standing on a board, its spine toward us with a title band
    (none when its row draws the bands); turned by `turn` about its foot on
    the side it tips to."""
    top = base - h
    pivot = (x0, base)

    def at(*pts):
        return k.rotate(pts, pivot, turn) if turn else list(pts)

    b.line(_ruled(*at((x0, base), (x0, top), (x1, top), (x1, base))), when=when, part=part)
    if band is not None:
        b.line(line(*at((x0, top + band), (x1, top + band + 0.3))), when=when, part=part)


def _row(b: SketchBuilder, books: list, base: float, first: int) -> None:
    """Old books standing side by side, sharing their sides. Their title
    bands run as one stroke across the row, a step at each shared side, the
    way a set's bands line up; a run of them has a second band below."""
    pts, second = [], []
    # Measured from the lowest top, so the band clears every book's top.
    y0 = base - min(bh for _, _, bh, _, _ in books) + books[0][3]
    for i, (x0, x1, h, _, two) in enumerate(books):
        _book(b, x0, x1, base, h, None, part=f'book:{first + i}')
        y = y0 + 0.8 * i
        pts += [(x0, y), (x1, y + 0.3)]
        if two:
            second += [(x0, y + 5.0), (x1, y + 5.3)]
    b.line(line(*pts), part=f'book:{first}')
    if second:
        b.line(line(*second), part=f'book:{first}')


def _old_books(b: SketchBuilder, s: dict) -> None:
    _row(b, s['upper'], UPPER, 0)
    _row(b, s['lower'][:2], LOWER, 3)
    # Overdue work tips the third over against its neighbour: it rests on its
    # foot's left corner, its left face on the neighbour's top corner.
    x0, x1, h, band, _ = s['lower'][2]
    _book(b, x0, x1, LOWER, h, band, when=(('calm',),), part='book:5')
    nx, nh = s['lower'][1][1], s['lower'][1][2]
    foot = nx + nh * math.tan(LEAN)
    _book(b, foot, foot + (x1 - x0), LOWER, h, band, when=(('overdue', 1),), part='book:5',
          turn=-LEAN)


def _open_top(s: dict) -> float:
    return LOWER - max(h for _, _, h, _, _ in s['lower'])


def _open_book(b: SketchBuilder, s: dict) -> None:
    """A book lying open on the three short lower books, its pages two
    shallow humps meeting at the spine."""
    y = _open_top(s)
    b.line(curve((12.6, y - 0.3), (12.2, y - 5.4), (17.5, y - 7.8), (23, y - 7.2), (27, y - 1.6),
                 (31, y - 7.2), (36.5, y - 7.8), (41.8, y - 5.4), (41.4, y - 0.3),
                 corners=(0, 1, 4, 7, 8)), part='book:open')


def _page(s: dict):
    """Start: a page lifts off the right of the open book and sweeps over to
    the left, curling as it goes."""
    y = _open_top(s) - 1.6

    def draw(frame: int, child: SketchBuilder) -> None:
        a = math.radians(32 + 23 * frame)
        bend = math.radians(16)
        mid = (27 + PAGE * 0.55 * math.cos(a + bend), y - PAGE * 0.55 * math.sin(a + bend))
        tip = (27 + PAGE * math.cos(a), y - PAGE * math.sin(a))
        child.line(curve((27, y), mid, tip), part='page')
    return draw


def _bookend(b: SketchBuilder) -> None:
    x = BOOKEND
    b.line(_ruled((x, UPPER + 0.4), (x, UPPER - 22), (x + 4.6, UPPER - 22), (x + 4.6, UPPER - 4.6),
                  (x + 9.2, UPPER - 4.6), (x + 9.2, UPPER + 0.5)), part='bookend')


def _plant(b: SketchBuilder, s: dict) -> None:
    x0, x1 = POT
    top = UPPER - 13
    b.line(_ruled((x0, top), (x0 + 2.4, UPPER + 0.5), (x1 - 2.4, UPPER + 0.5), (x1, top), closed=True),
           part='plant')
    b.line(line((x0 + 0.5, top + 3.4), (x1 - 0.5, top + 3.4)), part='plant')
    cx = (x0 + x1) / 2
    da, db, dc = (math.radians(v) for v in s['leaves'])
    k.draw_leaf(b, cx - 1.6, top - 0.2, 12.5, math.radians(-122) + da, part='plant')
    k.draw_leaf(b, cx + 0.2, top - 0.4, 14.0, math.radians(-88) + db, part='plant')
    k.draw_leaf(b, cx + 1.8, top - 0.2, 11.0, math.radians(-62) + dc, part='plant')


def _cat(b: SketchBuilder, s: dict) -> None:
    """Everything done: a cat curled asleep along the tops of the upper books,
    its head at the right, ears up, its tail wrapped along its front."""
    y = UPPER - max(h for _, _, h, _, _ in s['upper'])
    x = 11.0

    def p(u: float, v: float):
        return (x + u, y - v)

    when = (('allDone',),)
    b.line(loop(p(0, 0), p(0.8, 5.6), p(6.5, 10.2), p(14, 11), p(18.6, 9.6), p(19.8, 13), p(22.2, 10.6),
                p(24.6, 13), p(26.2, 9.4), p(27.8, 4.6), p(27, 0), corners=(0, 5, 7, 10)),
           when=when, part='cat')
    b.line(curve(p(1.4, 4.8), p(7, 5.2), p(13.5, 4.8), p(17, 6.4), p(16.2, 8.2)), when=when, part='cat')
    b.line(curve(p(21.6, 6.4), p(23, 5.4), p(24.6, 6.2)), when=when, part='cat')


def _flat(b: SketchBuilder) -> None:
    """Nothing planned: one book lies flat on the lower board."""
    x0, x1, t = 66.0, 102.0, 7.0
    when = (('nothingPlanned',),)
    b.line(_ruled((x0, LOWER + 0.4), (x0, LOWER - t), (x1, LOWER - t), (x1, LOWER + 0.4)), when=when,
           part='flat')
    b.line(line((x0 + 5, LOWER - t), (x0 + 5, LOWER + 0.3)), when=when, part='flat')


def _pile(b: SketchBuilder) -> None:
    """Overdue work: a book down on the floor, and at three a second on it."""
    for level, (x0, x1, base, t) in ((2, (10.0, 44.0, FLOOR, 7.0)), (3, (13.0, 39.0, FLOOR - 7.0, 6.0))):
        when = (('overdue', level),)
        b.line(_ruled((x0, base), (x0, base - t), (x1, base - t), (x1, base)), when=when,
               part=f'pile:{level}')
        b.line(line((x1 - 5, base - t), (x1 - 5, base)), when=when, part=f'pile:{level}')


def _rewards(b: SketchBuilder, s: dict, *, night: bool) -> None:
    for i, (x0, base, h) in enumerate(s['slots']):
        when = (('reward', i), PLANNED)
        x1, top = x0 + REWARD_W, base - h
        if night:
            b.glow(ellipse((x0 + x1) / 2, base - h / 2, 9.0, h / 2 + 5, n=10), when=when, part=f'rbook:{i}')
        b.filled(_ruled((x0, base), (x0, top), (x1, top), (x1, base), closed=True), when=when,
                 part=f'rbook:{i}')
        band = top + 0.24 * h
        b.line(line((x0, band), (x1, band + 0.3)), when=when, part=f'rbook:{i}')
        b.anchor(i, (x0 + x1) / 2, base)


def _shelf(b: SketchBuilder, s: dict) -> None:
    _boards(b)
    _frame(b)
    _old_books(b, s)
    _open_book(b, s)
    _bookend(b)
    _plant(b, s)
    _cat(b, s)
    _flat(b)
    _pile(b)


# ── the picture on the wall ─────────────────────────────────────────────────

def _picture_stars(b: SketchBuilder, r: Rng, s: dict, *, when: tuple = ()) -> None:
    """Two stars right of the moon, one high and one low: the picture has room
    for two only there, so each is placed in its own corner of that room."""
    x0, y0, x1, y1 = FRAME
    inset = 3.0
    for i, box in enumerate(((83.0, 16.4, 87.5, 19.5), (91.5, 26.0, 95.6, 31.6))):
        k.stars(b, r.fork(f'star{i}'), 1, box, avoid=((*s['moon'], 9.5),),
                ok=lambda p: x0 + inset <= p[0] <= x1 - inset and y0 + inset <= p[1] <= y1 - inset,
                when=when, part=f'star{i}')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    x0, y0, x1, y1 = FRAME
    b.wash(k.wash_of(_ruled((x0, y0), (x1, y0), (x1, y1), (x0, y1), closed=True), inset=0.95, dx=3, dy=3),
           part='frame')
    for books, base in ((s['upper'], UPPER), (s['lower'][:2], LOWER)):
        outline = [(books[0][0], base)]
        for bx0, bx1, h, _, _ in books:
            outline += [(bx0, base - h), (bx1, base - h)]
        outline.append((books[-1][1], base))
        b.wash(k.wash_of(_ruled(*outline, closed=True), inset=0.9, dx=3, dy=3), part='book')
    _shelf(b, s)
    # The hour, in the picture.
    sun = dict(ray_gap=2.6, ray_len=2.2, rays=5)
    k.sun(b, r.fork('sun-m'), 72.0, 27.0, 3.2, when=(k.MORNING,), **sun)
    k.sun(b, r.fork('sun-n'), 81.0, 21.6, 3.2, when=(k.MIDDAY,), **sun)
    k.sun(b, r.fork('sun-a'), 90.0, 27.0, 3.2, when=(k.AFTERNOON,), **sun)
    b.line(curve((x0, 33.6), (70, 30.6), (84, 31.0), (96, 29.6), (x1, 31.2)), when=(k.DUSK,), part='hill')
    k.low_sun(b, r.fork('sun-d'), 84.0, 31.2, 5.0, when=(k.DUSK,))
    k.moon(b, *s['moon'], 5.0, glow=False, clouds=0, when=(k.LATE,))
    _picture_stars(b, r.fork('late-stars'), s, when=(k.LATE,))
    _rewards(b, s, night=False)
    b.ambient(1.0, (('focus',),), _page(s))


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    # The wall lamp in the corner: its light falls in a cone across the upper
    # books and pools on the board.
    b.glow(loop((17.5, 26.5), (30.5, 26.5), (47, 62), (46, 88), (8, 88), (6, 62)), part='lamp')
    b.glow(ellipse(27.0, UPPER + 0.5, 25.0, 5.5, n=12), part='lamp')
    b.line(line((1.6, 9.5), (1.8, 18.5)), part='lamp')
    b.line(curve((1.8, 14.0), (10, 13.0), (18.5, 13.4), (24.0, 16.0)), part='lamp')
    b.line(_ruled((21.0, 16.0), (27.0, 16.0), (31.0, 25.8), (17.0, 25.8), closed=True), part='lamp')
    k.moon(b, *s['moon'], 5.0, glow=True, clouds=0)
    _picture_stars(b, r.fork('stars'), s)
    _shelf(b, s)
    _rewards(b, s, night=True)
    b.ambient(1.0, (('focus',),), _page(s))
