"""The desk unit's drawing: each subject's 'paper' composition, drawn for ink,
the shared ink style that prints it, and the seed it is drawn from."""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from datetime import date, timedelta

import pytest

from smylted import drawing
from smylted.drawing import DayState, Rng, SketchBuilder, desk_drawing, desk_seed, pen, subjects
from smylted.drawing.checks import polyline
from smylted.drawing.ink import HATCH_FROM, LEVEL_DARK, LEVEL_INK, LEVEL_LIGHT, LEVEL_PAPER
from smylted.drawing.paper import MIN_WIDTH, one_bit, paper_image
from smylted.drawing.schedule import ANCHOR
from smylted.drawing.subjects import assert_declarative, has_paper, paper_sketch

DAY = date(2026, 11, 25)
DESK_PX = 224              # the drawing's width on the desk face, 1.4 px per unit
FOUR = {LEVEL_PAPER, LEVEL_LIGHT, LEVEL_DARK, LEVEL_INK}

# The states a panel shows, the hour pinned to noon: nothing planned, none
# done, half done, all done (a short day and a full one), every reward.
NOTHING = DayState(nothing_planned=True)
NONE_DONE = DayState()
HALF = DayState(progress=0.5, rewards=3)
ALL_DONE = DayState(progress=1.0, rewards=6, all_done=True)
FULL = DayState(progress=1.0, rewards=12, all_done=True)
PANEL_STATES = (NOTHING, NONE_DONE, HALF, ALL_DONE, FULL)
SAMPLES = [(DAY + timedelta(days=d), salt) for d in range(5) for salt in ('desk-salt', 'second-salt')]

# The roster subjects still printed from their light composition. Written out
# so that drawing one changes this test.
NOT_YET_ON_PAPER = ['seedlings', 'bookshelf', 'kite', 'feeder', 'tidepool', 'lighthouse',
                    'vegpatch', 'tent', 'pond', 'bicycle', 'kitchen']


def _paper_params():
    return [pytest.param(s, id=s.id) for s in subjects.ROSTER if has_paper(s)]


def _renders(subject, state):
    for day, salt in SAMPLES:
        yield f"{day} {salt}", desk_drawing(day, salt, state, subject_id=subject.id)


def _ink(img) -> float:
    return img.histogram()[0] / (img.width * img.height)


def _ink_in(img, box) -> float:
    x0, y0, x1, y1 = box
    px = img.load()
    n = sum(1 for y in range(y0, y1) for x in range(x0, x1) if px[x, y] == 0)
    return n / ((x1 - x0) * (y1 - y0))


# -- which subjects draw for paper --------------------------------------------

def test_the_subjects_not_yet_drawn_for_paper():
    """The lead makes this list empty before the desk work leaves draft."""
    assert [s.id for s in subjects.ROSTER if not has_paper(s)] == NOT_YET_ON_PAPER


def test_a_subject_without_paper_prints_its_light_composition():
    """Never 'paper' to a subject that does not draw it: its render would
    take it for the night."""
    subject = next(s for s in subjects.ROSTER if not has_paper(s))
    sketch = paper_sketch(subject, NONE_DONE, Rng('fallback'))
    assert sketch.theme == 'light'
    assert sketch.to_json() == subject.render(NONE_DONE, 'light', Rng('fallback')).to_json()


@pytest.mark.parametrize('subject', _paper_params())
def test_a_paper_subject_prints_its_paper_composition(subject):
    sketch = paper_sketch(subject, NONE_DONE, Rng('paper'))
    assert sketch.theme == 'paper'


# -- the paper composition keeps the contract ---------------------------------

@pytest.mark.parametrize('subject', _paper_params())
def test_paper_is_declarative(subject):
    assert_declarative(subject)
    for day, salt in SAMPLES:
        assert_declarative(subject, f'{day}|{salt}')


@dataclasses.dataclass
class _Leaf:
    """A subject with a paper composition that depends on the state."""
    id: str = "test-leaf"
    since: date = ANCHOR
    until: date | None = None
    PAPER = True

    def render(self, state, theme, rng):
        b = SketchBuilder(self.id, theme, rng)
        b.line(pen.line((20, 100), (140, 100)))
        if theme == 'paper' and state.rewards:
            b.shade(pen.circle(80, 60, 20))
        return b.build(state)


def test_declarative_checks_the_paper_composition_too():
    with pytest.raises(AssertionError, match="paper"):
        assert_declarative(_Leaf())


@pytest.mark.parametrize('subject', _paper_params())
def test_paper_has_no_wash_glow_boil_or_ambient(subject):
    for where, sketch in _renders(subject, FULL):
        roles = {m.role for m in sketch.marks}
        assert not roles & {'wash', 'glow'}, f"{subject.id} {where}: {roles}"
        assert sketch.ambient is None, f"{subject.id} {where}"
        assert all(len(m.frames) == 1 for m in sketch.marks), f"{subject.id} {where}: a line boils"


@pytest.mark.parametrize('subject', _paper_params())
def test_paper_holds_every_reward(subject):
    for where, sketch in _renders(subject, FULL):
        rewards = {m.reward for m in sketch.marks if m.reward is not None and m.on}
        assert rewards == set(range(12)), f"{subject.id} {where}: {sorted(rewards)}"


# -- on the panel -------------------------------------------------------------

@pytest.mark.parametrize('subject', _paper_params())
def test_paper_stays_airy_at_desk_size(subject):
    for state in PANEL_STATES:
        for where, sketch in _renders(subject, state):
            img = one_bit(paper_image(sketch, DESK_PX))
            assert img.size == (224, 280)
            assert _ink(img) < 0.30, f"{subject.id} {where} {state}: {_ink(img):.1%} ink"


@pytest.mark.parametrize('subject', _paper_params())
def test_every_paper_reward_is_hatched_or_glinted(subject):
    """The owner's 17 Nov rule on paper: a coral fill 8 units across or more
    is a hatch, never a solid block; a fruit is solid with its glint. Every
    one of the twelve is one or the other."""
    for where, s in _renders(subject, FULL):
        img = one_bit(paper_image(s, DESK_PX))
        ppu = DESK_PX / s.view_box[2]
        seen = set()
        for m in s.marks:
            if m.role != 'accent' or m.reward is None:
                continue
            pts = polyline(m.frames[0], steps=8)[0]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            bw, bh = max(xs) - min(xs), max(ys) - min(ys)
            if m.paper == 'glint':
                r = min(bw, bh) / 2
                gx = (min(xs) + max(xs)) / 2 - 0.38 * r
                gy = (min(ys) + max(ys)) / 2 - 0.38 * r
                assert img.getpixel((int(gx * ppu), int(gy * ppu))) != 0, (where, m.part, 'no glint')
            else:
                assert max(bw, bh) >= HATCH_FROM, (where, m.part, 'too small to hatch')
                box = (round((min(xs) + 2) * ppu), round((min(ys) + 2) * ppu),
                       round((max(xs) - 2) * ppu), round((max(ys) - 2) * ppu))
                assert _ink_in(img, box) < 0.75, (where, m.part, 'a solid block')
            seen.add(m.reward)
        assert seen == set(range(12)), f"{subject.id} {where}: {sorted(seen)}"


@pytest.mark.parametrize('subject', _paper_params())
def test_four_grey_holds_exactly_the_four_levels(subject):
    sketch = desk_drawing(DAY, 'desk-salt', FULL, subject_id=subject.id)
    img = paper_image(sketch, DESK_PX, levels=4)
    assert img.mode == 'L' and img.size == (224, 280)
    hist = img.histogram()
    # Every tone this subject uses is there, and nothing between them.
    assert {v for v in range(256) if hist[v]} == FOUR


def test_four_grey_maps_each_role_to_its_level():
    def draw(b):
        b.shade(pen.poly((10, 10), (70, 10), (70, 70), (10, 70)), 'light')
        b.shade(pen.poly((90, 10), (150, 10), (150, 70), (90, 70)), 'mid')
        b.accent(pen.poly((10, 110), (70, 110), (70, 170), (10, 170)))
        b.solid(pen.poly((90, 110), (150, 110), (150, 170), (90, 170)))
    b = SketchBuilder("t", 'paper', Rng("levels"))
    draw(b)
    img = paper_image(b.build(DayState()), 240, levels=4)
    ppu = 1.5
    at = lambda x, y: img.getpixel((round(x * ppu), round(y * ppu)))
    assert at(40, 40) == LEVEL_LIGHT
    assert at(120, 40) == LEVEL_DARK
    assert at(40, 140) == LEVEL_DARK
    assert at(120, 140) == LEVEL_INK
    assert at(80, 90) == LEVEL_PAPER
    hist = img.histogram()
    assert {v for v in range(256) if hist[v]} == FOUR


def test_two_levels_hatch_the_tones():
    """On the 1-bit panel a light tone is the fine pen at a quarter, a mid
    tone the coral fills' hatch, and neither is solid."""
    def draw(b):
        b.shade(pen.poly((10, 10), (70, 10), (70, 70), (10, 70)), 'light')
        b.shade(pen.poly((90, 10), (150, 10), (150, 70), (90, 70)), 'mid')
    b = SketchBuilder("t", 'paper', Rng("tones"))
    draw(b)
    img = one_bit(paper_image(b.build(DayState()), DESK_PX))
    ppu = DESK_PX / 160
    light = _ink_in(img, tuple(round(v * ppu) for v in (16, 16, 64, 64)))
    mid = _ink_in(img, tuple(round(v * ppu) for v in (96, 16, 144, 64)))
    assert 0.18 <= light <= 0.32, light
    assert 0.30 <= mid <= 0.45, mid
    assert light < mid


def test_levels_must_be_two_or_four():
    b = SketchBuilder("t", 'paper', Rng("x"))
    b.line(pen.line((20, 100), (140, 100)))
    with pytest.raises(ValueError):
        paper_image(b.build(DayState()), 240, levels=3)
    assert paper_image(b.build(DayState()), MIN_WIDTH - 1, levels=4) is None


@pytest.mark.parametrize('subject', _paper_params())
def test_paper_bytes_are_deterministic(subject):
    first = desk_drawing(DAY, 'desk-salt', HALF, subject_id=subject.id)
    desk_drawing.cache_clear()
    again = desk_drawing(DAY, 'desk-salt', HALF, subject_id=subject.id)
    assert first is not again
    assert first.to_json() == again.to_json()
    for levels in (2, 4):
        assert (paper_image(first, DESK_PX, levels=levels).tobytes()
                == paper_image(again, DESK_PX, levels=levels).tobytes())


# -- the builder keeps paper and the themes apart ------------------------------

@pytest.mark.parametrize('call', [
    lambda b: b.wash(pen.circle(80, 100, 20)),
    lambda b: b.glow(pen.circle(80, 100, 20)),
    lambda b: b.ambient(1.0, (('focus',),), lambda f, c: c.line(pen.line((10, 10), (20, 10)))),
], ids=['wash', 'glow', 'ambient'])
def test_paper_refuses_the_themes_washes_glows_and_loops(call):
    with pytest.raises(ValueError, match="paper"):
        call(SketchBuilder("t", 'paper', Rng("x")))


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('call', [
    lambda b: b.shade(pen.circle(80, 100, 20)),
    lambda b: b.shade(pen.circle(80, 100, 20), 'mid'),
    lambda b: b.solid(pen.circle(80, 100, 20)),
    lambda b: b.line(pen.line((10, 10), (90, 10)), weight='fine'),
], ids=['light-shade', 'mid-shade', 'solid', 'fine-line'])
def test_the_themes_refuse_papers_own_marks(theme, call):
    """So a client's JSON never carries them."""
    with pytest.raises(ValueError, match="paper"):
        call(SketchBuilder("t", theme, Rng("x")))


def test_paper_marks_say_their_tone_and_pen():
    b = SketchBuilder("t", 'paper', Rng("x"))
    b.shade(pen.circle(80, 100, 20), 'mid')
    b.line(pen.line((10, 10), (90, 10)), weight='fine')
    b.line(pen.line((10, 30), (90, 30)))
    out = b.build(DayState()).to_json()
    shade, fine, main = out["marks"]
    assert shade["role"] == "shade" and shade["tone"] == "mid"
    assert fine["weight"] == "fine"
    assert "weight" not in main and "tone" not in main


def test_paper_rejects_an_unknown_tone_or_pen():
    b = SketchBuilder("t", 'paper', Rng("x"))
    with pytest.raises(ValueError):
        b.shade(pen.circle(80, 100, 20), 'dark')
    with pytest.raises(ValueError):
        b.line(pen.line((10, 10), (90, 10)), weight='bold')


# -- the seed -------------------------------------------------------------------

def test_the_desk_seed_is_one_way_and_its_own():
    salt = "f00dfeedcafe1234beadfacedeed5678"
    seed = desk_seed(salt)
    assert seed == hmac.new(salt.encode(), b"desk-drawing", hashlib.sha256).hexdigest()[:32]
    assert seed != salt and seed != drawing.share_seed(salt)


def test_the_desk_draws_the_days_subject_from_the_desk_seed():
    for day, salt in SAMPLES:
        subject = drawing.subject_for(day, salt, subjects.ROSTER)
        sketch = desk_drawing(day, salt, HALF)
        assert sketch.subject == subject.id
        rng = Rng.for_day(day, desk_seed(salt), f"subject|{subject.id}")
        assert sketch.to_json() == paper_sketch(subject, HALF, rng).to_json()


def test_a_named_subject_overrides_the_days():
    sketch = desk_drawing(DAY, 'desk-salt', HALF, subject_id='washing-line')
    assert sketch.subject == 'washing-line' and sketch.theme == 'paper'
    with pytest.raises(ValueError):
        desk_drawing(DAY, 'desk-salt', HALF, subject_id='no-such-subject')
