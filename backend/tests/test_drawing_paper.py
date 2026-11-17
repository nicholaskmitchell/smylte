"""The drawing on paper: the 1-bit desk unit prints ink on paper and nothing else."""
from __future__ import annotations

import time
from datetime import date

import pytest

from smylted.drawing import subjects
from smylted.drawing.checks import endpoints, polyline
from smylted.drawing.paper import HATCH_FROM, MIN_WIDTH, one_bit, paper_image, pen_px
from smylted.drawing.pen import circle, line, poly
from smylted.drawing.rng import Rng
from smylted.drawing.scene import SketchBuilder
from smylted.drawing.state import DayState

DAY = date(2026, 11, 16)
FOCUS = (("focus",),)


def sketch_of(draw, state=DayState()):
    b = SketchBuilder("t", "light", Rng("p"))
    draw(b)
    return b.build(state)


def ink(img) -> int:
    """Ink pixels in a 1-bit image."""
    return img.histogram()[0]


def is_ink(img, x: int, y: int) -> bool:
    return img.getpixel((x, y)) == 0


def ink_in(img, box) -> float:
    """The share of ink in a box given in device pixels (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    px = img.load()
    n = sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[x, y] == 0)
    return n / ((x1 - x0) * (y1 - y0))


def unit_box(bounds, inset, ppu):
    x0, y0, x1, y1 = bounds
    return (round((x0 + inset) * ppu), round((y0 + inset) * ppu),
            round((x1 - inset) * ppu), round((y1 - inset) * ppu))


def test_size_and_mode():
    s = sketch_of(lambda b: b.line(line((20, 100), (140, 100))))
    for w, size in ((160, (160, 200)), (240, (240, 300))):
        img = paper_image(s, w)
        assert img.mode == 'L'
        assert img.size == size
    assert paper_image(s, MIN_WIDTH - 1) is None


def test_pen_is_at_least_two_pixels():
    assert pen_px(0.5) == 2
    assert pen_px(1.0) == 2
    assert pen_px(2.0) == 4


def test_a_wash_and_a_glow_print_nothing():
    def draw(b):
        b.wash(poly((10, 10), (150, 10), (150, 190), (10, 190)))
        b.glow(circle(80, 100, 40))
    s = sketch_of(draw)
    assert all(m.on for m in s.marks)
    img = one_bit(paper_image(s, 240))
    assert ink(img) == 0


def test_a_line_is_the_pen_with_round_ends():
    s = sketch_of(lambda b: b.line(line((20, 100), (140, 100))))
    img = paper_image(s, 240)
    ppu = 1.5
    pen = pen_px(ppu)
    bits = one_bit(img)
    # The hand wobbles the stroke, so the end is read from the path itself.
    ex, ey = endpoints(s.marks[0].frames[0])[-1]
    x = round(80 * ppu)
    thickness = sum(1 for yy in range(img.height) if is_ink(bits, x, yy))
    assert pen - 1 <= thickness <= pen + 1
    # Ink on the axis just past the end (a round cap) and paper diagonally past
    # the corner, where a square cap would still be ink.
    px, py = int(ex * ppu) + 1, int(ey * ppu)
    assert is_ink(bits, px, py)
    assert not is_ink(bits, px, py - 2)
    assert not is_ink(bits, px, py + 1)
    assert not is_ink(bits, px + 2, py)


def test_off_marks_are_not_printed():
    s = sketch_of(lambda b: b.line(line((20, 100), (140, 100)), when=FOCUS),
                  DayState(focus_active=False))
    assert not s.marks[0].on
    assert ink(one_bit(paper_image(s, 240))) == 0
    on = sketch_of(lambda b: b.line(line((20, 100), (140, 100)), when=FOCUS),
                   DayState(focus_active=True))
    assert ink(one_bit(paper_image(on, 240))) > 0


def test_a_small_accent_is_solid_ink():
    s = sketch_of(lambda b: b.accent(circle(80, 100, 3)))
    for w, ppu in ((160, 1.0), (240, 1.5)):
        img = one_bit(paper_image(s, w))
        assert is_ink(img, round(80 * ppu), round(100 * ppu))


def test_a_glint_leaves_a_spot_of_paper_in_a_solid_fruit():
    s = sketch_of(lambda b: b.accent(circle(80, 100, 6), paper='glint'))
    for w, ppu in ((160, 1.0), (240, 1.5)):
        img = one_bit(paper_image(s, w))
        assert is_ink(img, round(80 * ppu), round(100 * ppu))
        # The pixel that holds the point.
        assert not is_ink(img, int((80 - 0.38 * 6) * ppu), int((100 - 0.38 * 6) * ppu))


def test_a_big_accent_is_hatched_not_solid():
    s = sketch_of(lambda b: b.accent(poly((50, 80), (90, 80), (90, 120), (50, 120))))
    for w, ppu in ((160, 1.0), (240, 1.5)):
        img = one_bit(paper_image(s, w))
        box = unit_box((50, 80, 90, 120), 3, ppu)
        frac = ink_in(img, box)
        assert 0.28 <= frac <= 0.52, frac
        assert frac < 1


def test_a_hatch_stays_inside_its_outline():
    s = sketch_of(lambda b: b.accent(poly((50, 80), (90, 80), (90, 120), (50, 120))))
    img = one_bit(paper_image(s, 240))
    assert ink_in(img, (0, 0, 240, round(78 * 1.5))) == 0
    assert ink_in(img, (round(92 * 1.5), 0, 240, 300)) == 0


def test_the_ambient_prints_its_first_frame_only_while_it_runs():
    def draw(b):
        b.ambient(1.0, FOCUS, lambda f, c: c.line(line((20, 50), (60, 50))))
    on = sketch_of(draw, DayState(focus_active=True))
    off = sketch_of(draw, DayState(focus_active=False))
    ppu = 1.5
    y = round(50 * ppu)
    row = lambda img: sum(1 for x in range(img.width) if is_ink(img, x, y))
    assert row(one_bit(paper_image(on, 240))) > 0
    assert ink(one_bit(paper_image(off, 240))) == 0


def test_the_same_sketch_gives_the_same_bytes():
    s = sketch_of(lambda b: (b.accent(poly((50, 80), (90, 80), (90, 120), (50, 120))),
                             b.line(circle(80, 100, 30))))
    assert paper_image(s, 240).tobytes() == paper_image(s, 240).tobytes()


# -- the roster ---------------------------------------------------------------

EMPTY = DayState(rewards=0, hour=9)
FULL = DayState(progress=1, rewards=12, all_done=True, focus_active=True, overdue=3, hour=13)


def roster_sketch(subject, state):
    rng = Rng.for_day(DAY, 'paper-salt', f'subject|{subject.id}')
    return subject.render(state, 'light', rng)


@pytest.mark.parametrize('subject', subjects.ROSTER, ids=lambda s: s.id)
@pytest.mark.parametrize('state', (EMPTY, FULL), ids=('empty', 'full'))
@pytest.mark.parametrize('width', (160, 240))
def test_the_roster_on_paper_stays_airy(subject, state, width):
    img = one_bit(paper_image(roster_sketch(subject, state), width))
    assert ink(img) < 0.30 * img.width * img.height


@pytest.mark.parametrize('subject', subjects.ROSTER, ids=lambda s: s.id)
@pytest.mark.parametrize('width', (160, 240))
def test_no_reward_is_a_solid_block(subject, width):
    s = roster_sketch(subject, FULL)
    img = one_bit(paper_image(s, width))
    ppu = width / s.view_box[2]
    for m in s.marks:
        if m.role != 'accent' or m.reward is None or m.paper != 'auto' or not m.on:
            continue
        pts = polyline(m.frames[0], steps=8)[0]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(max(xs) - min(xs), max(ys) - min(ys)) < HATCH_FROM:
            continue
        box = unit_box((min(xs), min(ys), max(xs), max(ys)), 2, ppu)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        assert ink_in(img, box) < 0.75, (m.id, m.part)


def test_a_full_drawing_rasterises_quickly():
    subject = next(s for s in subjects.ROSTER if s.id == 'washing-line')
    s = roster_sketch(subject, FULL)
    best = min(_timed(s) for _ in range(3))
    assert best < 0.5


def _timed(s) -> float:
    start = time.perf_counter()
    paper_image(s, 240)
    return time.perf_counter() - start
