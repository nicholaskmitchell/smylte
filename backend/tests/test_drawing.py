"""The daily drawing engine: the seeded stream, the conditions, the pen, the
sketch builder, the schedule, the subject contract and the route.

Nothing here touches Radicale. The subject is a test-only one defined below;
real subjects are separate modules that plug into this engine.
"""
from __future__ import annotations

import dataclasses
import json
import math
import pathlib
import re
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import smylted.drawing
from smylted.drawing.pen import PEN
from smylted import drawing
from smylted.app import create_app
from smylted.drawing import (
    DayState,
    Rng,
    SketchBuilder,
    conditions,
    drawing_payload,
    pen,
    schedule,
    subjects,
    subject_for,
)
from smylted.drawing import checks
from smylted.drawing.checks import (
    MIN_REWARD_ACROSS,
    MIN_REWARD_AREA,
    bounds_errors,
    crossings,
    has_standing_light,
    night_overlap,
    reward_sizes,
)
from smylted.drawing.pen import WOBBLE, Pen, hand
from smylted.drawing.scene import Mark, Sketch
from smylted.drawing.rng import cyrb128
from smylted.drawing.schedule import ANCHOR
from smylted.drawing.subjects import assert_declarative, joins_of
from tests.conftest import api_settings

DAY = date(2026, 11, 16)


# -- rng ----------------------------------------------------------------------

def test_same_path_gives_the_same_stream():
    a, b = Rng("2026-11-16|salt|x"), Rng("2026-11-16|salt|x")
    assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]


def test_different_paths_differ():
    a, b = Rng("one"), Rng("two")
    assert [a.random() for _ in range(20)] != [b.random() for _ in range(20)]


def test_a_fork_does_not_depend_on_how_much_of_the_parent_was_read():
    fresh = Rng("parent")
    read = Rng("parent")
    for _ in range(50):
        read.random()
    x, y = fresh.fork("x"), read.fork("x")
    assert x.path == y.path == "parent|x"
    assert [x.random() for _ in range(20)] == [y.random() for _ in range(20)]


def test_random_is_in_the_unit_interval():
    for path in ("a", "b", "", "2026-01-01|s|schedule"):
        r = Rng(path)
        for _ in range(5000):
            v = r.random()
            assert 0 <= v < 1


def test_shuffled_is_a_permutation_and_leaves_the_input_alone():
    items = list(range(30))
    out = Rng("shuffle").shuffled(items)
    assert sorted(out) == items
    assert items == list(range(30))
    assert out != items


def test_randint_is_inclusive_and_jitter_bounded():
    r = Rng("ints")
    seen = {r.randint(2, 5) for _ in range(500)}
    assert seen == {2, 3, 4, 5}
    assert all(-1.5 <= r.jitter(1.5) <= 1.5 for _ in range(500))


def test_for_day_names_the_stream_by_day_salt_and_purpose():
    assert Rng.for_day(DAY, "salt", "schedule").path == "2026-11-16|salt|schedule"


def test_cyrb128_regression_pin():
    # These pin the hash: a change to cyrb128 reshuffles every drawing ever
    # scheduled, so it must be deliberate.
    assert cyrb128("") == (41608494, 3485963809, 1435736333, 1262568316)
    assert cyrb128("2026-11-16|salt|schedule") == (
        3992580582, 676454449, 1205717031, 2274435719)


# -- conditions ---------------------------------------------------------------

@pytest.mark.parametrize("when, state, on", [
    ((), DayState(), True),
    ((("reward", 0),), DayState(rewards=0), False),
    ((("reward", 0),), DayState(rewards=1), True),
    ((("reward", 11),), DayState(rewards=11), False),
    ((("reward", 11),), DayState(rewards=12), True),
    ((("focus",),), DayState(), False),
    ((("focus",),), DayState(focus_active=True), True),
    ((("allDone",),), DayState(all_done=True), True),
    ((("allDone",),), DayState(), False),
    ((("notAllDone",),), DayState(), True),
    ((("notAllDone",),), DayState(all_done=True), False),
    ((("nothingPlanned",),), DayState(nothing_planned=True), True),
    ((("nothingPlanned",),), DayState(), False),
    ((("planned",),), DayState(), True),
    ((("planned",),), DayState(nothing_planned=True), False),
    ((("overdue", 1),), DayState(overdue=0), False),
    ((("overdue", 1),), DayState(overdue=1), True),
    ((("overdue", 3),), DayState(overdue=2), False),
    ((("overdue", 3),), DayState(overdue=3), True),
    ((("overdue", 3),), DayState(overdue=40), True),     # capped at OVERDUE_LEVELS
    ((("calm",),), DayState(overdue=0), True),
    ((("calm",),), DayState(overdue=1), False),
    ((("progress", 0.5),), DayState(progress=0.49), False),
    ((("progress", 0.5),), DayState(progress=0.5), True),
    ((("progress", 1),), DayState(progress=1.0), True),
    ((("hour", 9, 17),), DayState(hour=9), True),
    ((("hour", 9, 17),), DayState(hour=16), True),
    ((("hour", 9, 17),), DayState(hour=17), False),
    ((("hour", 9, 17),), DayState(hour=3), False),
    ((("hour", 20, 6),), DayState(hour=22), True),        # wraps midnight
    ((("hour", 20, 6),), DayState(hour=3), True),
    ((("hour", 20, 6),), DayState(hour=12), False),
    ((("hour", 20, 6),), DayState(hour=6), False),
    ((("hour", 20, 6),), DayState(hour=20), True),
    ((("unlit", 0),), DayState(rewards=0), True),
    ((("unlit", 0),), DayState(rewards=1), False),
    ((("unlit", 5),), DayState(rewards=3), True),
    ((("unlit", 5),), DayState(rewards=6), False),
    ((("idle",),), DayState(), True),
    ((("idle",),), DayState(focus_active=True), False),
    ((("focus",), ("reward", 2)), DayState(focus_active=True, rewards=3), True),
    ((("focus",), ("reward", 2)), DayState(focus_active=True, rewards=2), False),
    ((("focus",), ("reward", 2)), DayState(rewards=3), False),
])
def test_condition_truth_table(when, state, on):
    assert conditions.evaluate(when, state) is on
    # The wire form evaluates the same.
    assert conditions.evaluate(conditions.to_json(when), state) is on


def test_validate_normalises_lists_to_tuples():
    assert conditions.validate([["reward", 3], ["hour", 20, 6]]) == (
        ("reward", 3), ("hour", 20, 6))
    assert conditions.to_json((("focus",), ("progress", 0.5))) == [
        ["focus"], ["progress", 0.5]]


@pytest.mark.parametrize("when", [
    [("sunny",)],                          # unknown atom
    [()],                                  # empty atom
    [(3,)],                                # not a name
    [("focus", 1)],                        # wrong arity
    [("reward",)],
    [("hour", 1)],
    [("reward", 1, 2)],
    [("reward", 12)],                      # out of range
    [("unlit", 12)],
    [("unlit", -1)],
    [("unlit", 1.0)],
    [("unlit",)],
    [("idle", 1)],
    [("reward", -1)],
    [("reward", 1.0)],
    [("reward", True)],
    [("overdue", 0)],
    [("overdue", 4)],
    [("progress", 1.5)],
    [("progress", -0.1)],
    [("progress", "half")],
    [("hour", -1, 6)],
    [("hour", 20, 25)],
    [("hour", 20.5, 6)],
])
def test_validate_rejects(when):
    with pytest.raises(ValueError):
        conditions.validate(when)


# -- pen ----------------------------------------------------------------------

_D = re.compile(r"^[MLCZ0-9 .\-]+$")


def _numbers(d: str) -> list[str]:
    return [tok for tok in d.split(" ") if tok not in ("M", "L", "C", "Z")]


def test_every_jittered_point_stays_within_the_wobble():
    stroke = pen.curve(*[(i * 3.0, 50 + math.sin(i) * 20) for i in range(60)])
    p = Pen(Rng("wobble"))
    for k in range(20):
        for (x, y), (jx, jy) in zip(stroke.points, p.jittered(stroke, f"k{k}")):
            assert math.hypot(jx - x, jy - y) <= WOBBLE + 1e-9


def test_three_boil_frames_differ():
    frames = Pen(Rng("boil")).frames(pen.curve((10, 10), (40, 30), (80, 20)), "m0")
    assert len(frames) == 3
    assert len(set(frames)) == 3


@pytest.mark.parametrize("stroke", [
    pen.line((0, 0), (10.04, -0.04), (-20.55, 3)),
    pen.curve((10, 10), (40, 30), (80, 20), (120, 90)),
    pen.loop((10, 10), (40, 30), (80, 20)),
    pen.poly((0, 0), (5, 0), (5, 5)),
    pen.ellipse(80, 100, 40, 20, rot=0.4),
    pen.circle(-10, -10, 3),
])
def test_path_data_is_plain_and_one_decimal(stroke):
    p = Pen(Rng("d"))
    for d in p.frames(stroke, "k") + (p.still(stroke, "k"),):
        assert _D.match(d), d
        for tok in _numbers(d):
            assert re.fullmatch(r"-?\d+(\.\d)?", tok), tok
            assert not tok.endswith(".0") and tok != "-0", tok
        assert d.endswith("Z") is stroke.closed


def test_to_d_formats_and_splines():
    assert pen.to_d([(0, 0), (10.04, -0.04)], False, False) == "M 0 0 L 10 0"
    assert pen.to_d([(0, 0), (5, 0), (5, 5)], True, False) == "M 0 0 L 5 0 L 5 5 Z"
    # Open ends are duplicated, so a two-point spline is a straight Bezier.
    assert pen.to_d([(0, 0), (6, 0)], False, True) == "M 0 0 C 1 0 5 0 6 0"
    closed = pen.to_d([(0, 0), (6, 0), (6, 6)], True, True)
    assert closed.startswith("M 0 0 C ") and closed.endswith(" 0 0 Z")
    assert closed.count("C") == 3


def test_same_path_gives_identical_frames():
    stroke = pen.ellipse(50, 50, 20, 10)
    assert Pen(Rng("same")).frames(stroke, "m3") == Pen(Rng("same")).frames(stroke, "m3")
    assert Pen(Rng("same")).still(stroke, "m3") == Pen(Rng("same")).still(stroke, "m3")


def test_constructors_are_pure_geometry():
    e = pen.ellipse(10, 20, 4, 2, n=8)
    assert len(e.points) == 8 and e.closed and e.smooth
    assert e.points[0] == pytest.approx((14, 20))
    assert pen.circle(0, 0, 1).points == pen.circle(0, 0, 1).points
    assert not pen.line((0, 0), (1, 1)).smooth
    assert not pen.curve((0, 0), (1, 1)).closed


def _cubics(d: str) -> list[list[float]]:
    """The numbers of each C segment of a path: x1 y1 x2 y2 x y."""
    return [[float(t) for t in seg.split()] for seg in d.replace(" Z", "").split(" C ")[1:]]


def test_to_d_corners_turn_instead_of_passing_through():
    pts = [(0, 0), (10, -10), (20, 0), (20, 10), (0, 10)]
    cornered = _cubics(pen.to_d(pts, True, True, corners=(3, 4)))
    # The segment from (20, 10) to (0, 10) leaves and arrives along the edge.
    assert cornered[3][1] == 10 and cornered[3][3] == 10
    plain = _cubics(pen.to_d(pts, True, True))
    assert max(plain[3][1], plain[3][3]) > 10
    # No corners given is the same as before.
    assert pen.to_d(pts, True, True, corners=()) == pen.to_d(pts, True, True)


def test_curve_and_loop_carry_corners():
    assert pen.curve((0, 0), (1, 1), (2, 0), corners=[1]).corners == (1,)
    assert pen.loop((0, 0), (1, 1), (2, 0), corners=(0, 2)).corners == (0, 2)
    assert pen.line((0, 0), (1, 1)).corners == ()
    assert pen.circle(0, 0, 1).corners == ()


def test_hand_bows_a_long_line_to_one_side():
    stroke = pen.line((0, 100), (160, 100))
    out = hand(stroke, Rng("hand"))
    assert out.smooth and not out.closed
    assert out.corners == (0, len(out.points) - 1)
    assert out.points[0] == (0, 100) and out.points[-1] == (160, 100)
    offsets = [y - 100 for _, y in out.points[1:-1]]
    assert offsets
    assert all(o > 0 for o in offsets) or all(o < 0 for o in offsets)
    assert all(0 < abs(o) <= 2.3 for o in offsets)
    assert hand(stroke, Rng("hand")) == out


def test_hand_leaves_short_and_smooth_strokes_alone():
    short = pen.line((0, 0), (20, 0))
    assert hand(short, Rng("hand")) is short
    curved = pen.curve((0, 0), (80, 20), (160, 0))
    assert hand(curved, Rng("hand")) is curved


def test_hand_keeps_the_corners_of_a_polygon():
    square = pen.poly((0, 0), (40, 0), (40, 40), (0, 40))
    out = hand(square, Rng("hand"))
    assert out.closed and out.smooth
    assert len(out.points) == 8
    assert out.corners == (0, 2, 4, 6)
    assert [out.points[i] for i in out.corners] == list(square.points)


def test_small_shapes_move_as_one_and_keep_their_shape():
    stroke = pen.circle(0, 0, 2.2, n=7)
    p = Pen(Rng("small"))
    for k in range(20):
        moved = p.jittered(stroke, f"k{k}")
        for i in range(7):
            for j in range(i + 1, 7):
                was = (stroke.points[j][0] - stroke.points[i][0],
                       stroke.points[j][1] - stroke.points[i][1])
                now = (moved[j][0] - moved[i][0], moved[j][1] - moved[i][1])
                assert math.hypot(now[0] - was[0], now[1] - was[1]) <= 2 * 0.2 * WOBBLE + 1e-9


def test_a_stroke_with_no_points_jitters_to_nothing():
    assert Pen(Rng("none")).jittered(pen.Stroke(()), "k") == []


# -- scene --------------------------------------------------------------------

def _builder(path: str = "scene") -> SketchBuilder:
    return SketchBuilder("test", "light", Rng(path))


def test_build_sets_on_per_state():
    b = _builder()
    b.line(pen.line((0, 0), (10, 10)), when=(("focus",),))
    b.wash(pen.circle(5, 5, 3))
    off, on = b.build(DayState()), b.build(DayState(focus_active=True))
    # Marks come back in paint order (wash, glow, accent, line), ids as drawn.
    assert [m.id for m in on.marks] == ["m1", "m0"]
    assert {m.id: m.on for m in off.marks} == {"m0": False, "m1": True}
    assert {m.id: m.on for m in on.marks} == {"m0": True, "m1": True}
    by_id = {m.id: m for m in on.marks}
    assert len(by_id["m0"].frames) == 3 and len(by_id["m1"].frames) == 1


def test_unlit_is_not_a_reward_atom():
    b = _builder()
    b.accent(pen.circle(5, 5, 3), when=[["unlit", 4]])
    assert b.build(DayState()).marks[0].reward is None


def test_a_reward_atom_sets_reward():
    b = _builder()
    b.accent(pen.circle(5, 5, 3), when=[["reward", 4], ["planned"]])
    b.accent(pen.circle(5, 5, 3))
    sk = b.build(DayState(rewards=5))
    assert sk.marks[0].reward == 4 and sk.marks[0].on
    assert sk.marks[1].reward is None


def test_two_reward_atoms_raise():
    with pytest.raises(ValueError):
        _builder().accent(pen.circle(5, 5, 3), when=(("reward", 1), ("reward", 2)))


def test_a_second_ambient_raises():
    b = _builder()
    b.ambient(1, (), lambda f, fb: fb.line(pen.line((0, f), (5, f))))
    with pytest.raises(ValueError):
        b.ambient(1, (), lambda f, fb: None)


def test_ambient_frames():
    b = _builder()
    b.ambient(1.5, (("focus",),), lambda f, fb: (
        fb.line(pen.line((0, f), (5, f))), fb.wash(pen.circle(5, f, 2))))
    sk = b.build(DayState(focus_active=True))
    assert len(sk.ambient.frames) == round(1.5 * 6) == 9
    assert [m.id for m in sk.ambient.frames[2]] == ["a2m0", "a2m1"]
    assert all(len(m.frames) == 1 for frame in sk.ambient.frames for m in frame)
    assert sk.ambient.when == (("focus",),)


def test_the_mark_budget():
    b = _builder()
    for _ in range(400):
        b.accent(pen.poly((0, 0), (1, 0), (1, 1)))
    b.build(DayState())
    b.accent(pen.poly((0, 0), (1, 0), (1, 1)))
    with pytest.raises(ValueError):
        b.build(DayState())


def test_the_point_budget():
    b = _builder()
    for _ in range(100):      # 21 points x 3 frames x 100 = 6300
        b.line(pen.curve(*[(i, i) for i in range(21)]))
    with pytest.raises(ValueError):
        b.build(DayState())


def test_to_json_round_trips():
    b = _builder()
    b.line(pen.curve((0, 0), (5, 5), (10, 0)), when=(("hour", 20, 6),))
    b.accent(pen.circle(5, 5, 3), when=(("reward", 0),))
    b.ambient(0.5, (("focus",),), lambda f, fb: fb.line(pen.line((0, f), (5, f))))
    data = b.build(DayState()).to_json()
    assert json.loads(json.dumps(data)) == data
    assert set(data) == {"subject", "theme", "viewBox", "marks", "ambient"}
    assert data["viewBox"] == [0, 0, 160, 200]
    assert next(m for m in data["marks"] if m["id"] == "m0")["when"] == [["hour", 20, 6]]
    assert set(data["ambient"]) == {"seconds", "when", "frames"}


def _middle_y(d: str) -> float:
    pts = checks.endpoints(d)
    return pts[len(pts) // 2][1]


def test_a_ruled_line_is_bowed_the_same_way_in_every_frame():
    b = _builder()
    b.line(pen.line((0, 50), (160, 50)))
    mark = b.build(DayState()).marks[0]
    assert len(mark.frames) == 3
    offsets = [_middle_y(d) - 50 for d in mark.frames]
    assert all(o > 0 for o in offsets) or all(o < 0 for o in offsets)


def test_glow_is_one_frame_between_wash_and_accent():
    b = _builder()
    b.line(pen.line((0, 0), (10, 10)))
    b.accent(pen.circle(5, 5, 3))
    b.glow(pen.circle(5, 5, 9), when=(("hour", 20, 6),))
    b.wash(pen.circle(5, 5, 12))
    sk = b.build(DayState())
    assert [m.role for m in sk.marks] == ['wash', 'glow', 'accent', 'line']
    glow = sk.marks[1]
    assert len(glow.frames) == 1 and glow.when == (("hour", 20, 6),)


@pytest.mark.parametrize("stroke", [
    pen.circle(40, 40, 12, n=12),
    pen.poly((10, 10), (60, 12), (58, 70), (12, 66)),
])
def test_filled_is_an_accent_then_its_outline(stroke):
    b = _builder()
    b.filled(stroke, when=(("reward", 2),), part="fruit")
    b.filled(stroke, when=(("reward", 3),))
    sk = b.build(DayState(rewards=4))
    by_id = {m.id: m for m in sk.marks}
    accent, outline = by_id["m0"], by_id["m1"]
    assert (accent.role, outline.role) == ("accent", "line")
    assert accent.when == outline.when == (("reward", 2),)
    assert accent.reward == outline.reward == 2
    assert accent.part == outline.part == "fruit"
    assert len(accent.frames) == 1 and len(outline.frames) == 1
    # Unnamed, a fill and its outline are one part, named for the fill.
    assert by_id["m3"].part == by_id["m2"].part == "m2"
    assert len(by_id["m3"].frames) == 1
    near = list(zip(checks.endpoints(accent.frames[0]), checks.endpoints(outline.frames[0])))
    assert len(near) > 3
    for (ax, ay), (ox, oy) in near:
        # The inset is 0.5; each coordinate is then rounded to a tenth.
        assert math.hypot(ax - ox, ay - oy) <= 0.65


def test_filled_inside_an_ambient_child_is_one_frame_each():
    b = _builder()
    b.ambient(1, (), lambda f, fb: fb.filled(pen.circle(40, 40, 12)))
    frame = b.build(DayState()).ambient.frames[0]
    assert [m.role for m in frame] == ["accent", "line"]
    assert [len(m.frames) for m in frame] == [1, 1]


def test_paper_must_be_a_known_one():
    with pytest.raises(ValueError):
        _builder().accent(pen.circle(5, 5, 3), paper="shiny")
    with pytest.raises(ValueError):
        _builder().filled(pen.circle(5, 5, 3), paper="shiny")
    _builder().accent(pen.circle(5, 5, 3), paper="glint")


def test_an_anchor_must_be_inside_the_picture():
    # The client refuses a whole drawing for one origin off the picture.
    b = _builder()
    b.anchor(0, 0, 0)
    b.anchor(1, 160, 200)
    for x, y in ((-0.1, 50), (80, 200.1), (161, 10)):
        with pytest.raises(ValueError):
            b.anchor(2, x, y)


def test_rewards_carry_an_origin_and_nothing_else_does():
    b = _builder()
    b.line(pen.line((0, 0), (10, 10)))
    b.accent(pen.circle(30, 40, 5), when=(("reward", 0),), paper="glint", part="bud")
    b.accent(pen.circle(80, 90, 5), when=(("reward", 1),))
    b.anchor(0, 12.5, 40.0)
    sk = b.build(DayState(rewards=2))
    by_reward = {m.reward: m for m in sk.marks}
    data = sk.to_json()["marks"]
    anchored = next(m for m in data if m["reward"] == 0)
    assert anchored["origin"] == [12.5, 40.0]
    centred = by_reward[1]
    ends = checks.endpoints(centred.frames[0])
    cx = sum(x for x, _ in ends) / len(ends)
    cy = sum(y for _, y in ends) / len(ends)
    assert centred.origin == pytest.approx((cx, cy))
    assert next(m for m in data if m["reward"] == 1)["origin"] == [round(cx, 1), round(cy, 1)]
    plain = next(m for m in data if m["reward"] is None)
    assert "origin" not in plain
    assert by_reward[0].paper == "glint" and by_reward[0].part == "bud"
    for m in data:
        assert not {"paper", "part"} & set(m)


def test_an_ambient_mark_gets_no_origin():
    b = _builder()
    b.ambient(1, (), lambda f, fb: fb.accent(pen.circle(5, 5, 3), when=(("reward", 0),)))
    sk = b.build(DayState())
    assert all(m.origin is None for frame in sk.ambient.frames for m in frame)


@pytest.mark.parametrize("reward", [12, -1, True, 1.5])
def test_anchor_rejects_a_bad_reward(reward):
    with pytest.raises(ValueError):
        _builder().anchor(reward, 1, 2)


# -- the geometry checks ------------------------------------------------------

_BOX = "M 10 10 L 30 10 L 30 30 L 10 30 Z"


def _mark(mid, d, *, role="line", part="", on=True, reward=None, when=(), frames=None):
    return Mark(mid, role, frames or (d,), when, reward, on, None, "auto", part or mid)


def _sketch(*marks, ambient=None):
    return Sketch("t", "light", (0, 0, 160, 200), tuple(marks), ambient)


def test_endpoints_skip_control_points():
    d = "M 0 0 L 10 0 C 10 5 15 10 20 10 Z"
    assert checks.endpoints(d) == [(0, 0), (10, 0), (20, 10)]
    assert checks.endpoints("") == []


def test_polyline_flattens_curves_and_closes():
    d = "M 0 0 L 10 0 C 10 5 15 10 20 10 Z"
    (path,) = checks.polyline(d, steps=2)
    assert path == [(0, 0), (10, 0), pytest.approx((13.125, 6.875)), (20, 10), (0, 0)]
    assert len(checks.polyline(d)[0]) == 1 + 1 + 12 + 1
    assert len(checks.polyline("M 0 0 L 1 1 M 5 5 L 6 6")) == 2


def test_bounds_errors_allow_a_margin_and_name_the_mark():
    inside = _mark("m0", "M -1 50 L 20 50", part="trunk")
    outside = _mark("m1", "M -3 50 L 20 50", part="roots")
    assert bounds_errors(_sketch(inside)) == []
    assert bounds_errors(_sketch(inside, outside)) == [
        "m1 (roots) leaves the frame at (-3.0, 50.0)"]
    assert bounds_errors(_sketch(outside), margin=4) == []


def test_bounds_errors_look_at_the_ambient_too():
    frame = (_mark("a0m0", "M 0 0 L 170 0"),)
    from smylted.drawing.scene import Ambient
    sk = _sketch(ambient=Ambient(1.0, (), (frame,)))
    assert len(bounds_errors(sk)) == 1


def test_reward_sizes_of_a_square():
    one = _mark("m0", _BOX, role="accent", reward=3)
    assert reward_sizes(_sketch(one)) == {3: (20.0, 400.0)}
    two = _mark("m1", "M 50 50 L 55 50 L 55 55 L 50 55 Z", role="accent", reward=3)
    other = _mark("m2", _BOX, role="line", reward=4)
    sizes = reward_sizes(_sketch(one, two, other))
    assert sizes == {3: (45.0, 425.0)}
    assert MIN_REWARD_ACROSS == 10.0 and MIN_REWARD_AREA == 60.0


def _cross_marks(a_part="a", b_part="b", on=True):
    return _sketch(_mark("m0", "M 0 50 L 100 50", part=a_part),
                   _mark("m1", "M 50 0 L 50 100", part=b_part, on=on))


def test_crossings_report_parts_that_cross():
    found = crossings(_cross_marks())
    assert len(found) == 1
    a, b, (x, y) = found[0]
    assert (a, b) == ("a", "b") and (x, y) == pytest.approx((50, 50), abs=PEN + 0.5)


def test_crossings_measure_against_the_pen():
    # Two parallel lines: touching when their centres are closer than the
    # pen is wide, clear when they are farther.
    def pair(gap):
        return _sketch(_mark("m0", "M 0 50 L 100 50", part="a"), _mark("m1", f"M 0 {50 + gap} L 100 {50 + gap}", part="b"))
    assert len(crossings(pair(PEN - 0.2))) == 1
    assert crossings(pair(PEN + 0.2)) == []


def test_crossings_check_each_boil_frame_with_its_own():
    # They touch only in the second boil frame, the one shown with the other's second.
    still = "M 0 50 L 100 50"
    a = _mark("m0", still, part="a", frames=(still, still, still))
    b = _mark("m1", "", part="b", frames=("M 0 60 L 100 60", "M 0 51 L 100 51", "M 0 60 L 100 60"))
    assert [p[:2] for p in crossings(_sketch(a, b))] == [("a", "b")]


def test_two_rewards_never_touch_even_when_joined():
    a = _mark("m0", "M 0 50 L 100 50", part="note:1", reward=1)
    b = _mark("m1", "M 50 0 L 50 100", part="note:2", reward=2)
    assert len(crossings(_sketch(a, b), frozenset({frozenset({"note"})}))) == 1
    # The same reward's own marks may.
    c = _mark("m1", "M 50 0 L 50 100", part="note:1", reward=1)
    assert crossings(_sketch(a, c)) == []


def test_a_bare_spark_is_ink():
    # A coral fill with no line of its own (a firefly) still counts; one with
    # its own outline is counted by the outline.
    spark = _mark("m0", "M 40 40 L 60 40 L 60 60 L 40 60 Z", role="accent", part="fly")
    line_ = _mark("m1", "M 0 50 L 100 50", part="branch")
    assert len(crossings(_sketch(spark, line_))) == 1
    ringed = _mark("m2", "M 40 40 L 60 40 L 60 60 L 40 60 Z", part="fly")
    assert len(crossings(_sketch(spark, ringed, _mark("m3", "M 0 90 L 100 90", part="far")))) == 0


def test_crossings_ignore_joined_parts_and_marks_that_are_off():
    assert crossings(_cross_marks(), frozenset({frozenset({"a", "b"})})) == []
    assert crossings(_cross_marks(on=False)) == []
    assert crossings(_cross_marks("a", "a")) == []
    # The same base with different parts needs a join of one name.
    sk = _cross_marks("fruit:1", "fruit:2")
    assert len(crossings(sk)) == 1
    assert crossings(sk, frozenset({frozenset({"fruit"})})) == []
    # Only line marks count.
    assert crossings(_sketch(_mark("m0", "M 0 50 L 100 50", role="wash"),
                             _mark("m1", "M 50 0 L 50 100", role="wash"))) == []


def test_crossings_see_the_ambient():
    from smylted.drawing.scene import Ambient
    frame = (_mark("a0m0", "M 50 0 L 50 100"),)
    sk = _sketch(_mark("m0", "M 0 50 L 100 50"), ambient=Ambient(1.0, (), (frame,)))
    assert len(crossings(sk)) == 1


def test_crossings_check_every_frame_of_the_loop_against_every_boil_frame():
    # The loop runs over the boiling picture, so a loop frame meets each of the
    # three boil frames in turn: touching only the third is still touching.
    from smylted.drawing.scene import Ambient
    still = _mark("m0", "", part="a",
                  frames=("M 0 20 L 100 20", "M 0 20 L 100 20", "M 0 49.5 L 100 49.5"))
    loop = (_mark("a0m0", "M 0 50 L 100 50", part="b"),)
    sk = _sketch(still, ambient=Ambient(1.0, (), (loop,)))
    assert [p[:2] for p in crossings(sk)] == [("a", "b")]


def test_a_bare_spark_in_the_loop_is_ink():
    from smylted.drawing.scene import Ambient
    spark = (_mark("a0m0", "M 40 40 L 60 40 L 60 60 L 40 60 Z", role="accent", part="fly"),)
    sk = _sketch(_mark("m0", "M 0 50 L 100 50", part="branch"), ambient=Ambient(1.0, (), (spark,)))
    assert len(crossings(sk)) == 1


@pytest.mark.parametrize("r", [4.0, 5.0, 6.0, 7.0, 8.0])
@pytest.mark.parametrize("cx", [30.0, 130.0])
def test_a_moons_clouds_keep_off_it_and_each_other(r, cx):
    # The clouds are never narrower than MOON_CLOUD, so a small moon's default
    # offsets must come from the clouds' size: measured in its own radius they
    # ran into the crescent and into each other. No joins: nothing here may
    # touch, and the two clouds are separate parts so the check can see them.
    from smylted.drawing.rng import Rng
    from smylted.drawing.scene import SketchBuilder
    from smylted.drawing.subjects import _kit as k
    for salt in ("a", "b", "c", "d", "e", "f"):
        b = SketchBuilder("probe", "dark", Rng.for_day(date(2026, 11, 17), salt, "moon"))
        k.moon(b, cx, 40.0, r)
        sk = b.build(_DayState(overdue=2))
        assert crossings(sk) == [], f"r={r} cx={cx} salt={salt}"


def test_a_moon_says_where_its_clouds_go():
    # The circles it returns hold every point of the clouds' ink, so a subject
    # that keeps its stars out of them keeps them off the clouds.
    from smylted.drawing.rng import Rng
    from smylted.drawing.scene import SketchBuilder
    from smylted.drawing.subjects import _kit as k
    b = SketchBuilder("probe", "dark", Rng.for_day(date(2026, 11, 17), "salt", "moon"))
    circles = k.moon(b, 30.0, 40.0, 6.5)
    assert len(circles) == 2
    sk = b.build(_DayState(overdue=2))
    for n, (x, y, reach) in enumerate(circles, start=1):
        ink = [p for m in sk.marks if m.part == f"cloud:{n}" for f in m.frames
               for sub in checks.polyline(f) for p in sub]
        assert ink and all(math.dist(p, (x, y)) <= reach for p in ink)
    assert k.moon(SketchBuilder("probe", "dark", Rng.for_day(date(2026, 11, 17), "salt", "moon")),
                  30.0, 40.0, 6.5, clouds=0) == []


def test_crossings_are_fast_over_thousands_of_samples():
    marks = [_mark(f"m{i}", f"M 0 {i * 5} L 100 {i * 5}", part=f"row{i}") for i in range(20)]
    sk = _sketch(*marks)             # 20 lines x 200 samples
    t = time.perf_counter()
    assert crossings(sk) == []
    assert time.perf_counter() - t < 1.0


def test_night_overlap_counts_marks_in_the_same_place():
    light = _sketch(_mark("m0", "M 10 10 L 30 30"), _mark("m1", "M 50 50 L 70 90"))
    dark = _sketch(_mark("m0", "M 10.4 10.4 L 29.6 30.4"),
                   _mark("m1", "M 0 0 L 5 5"),
                   _mark("m2", "M 100 100 L 120 120"),
                   _mark("m3", "M 50 50 L 70 90"))
    assert night_overlap(light, dark) == 0.5
    assert night_overlap(light, _sketch()) == 0.0
    assert night_overlap(light, light) == 1.0


def test_a_standing_light_is_a_glow_big_enough_to_see_that_is_always_on():
    big = "M 10 10 L 40 10 L 40 40 L 10 40 Z"            # 900 square units
    assert has_standing_light(_sketch(_mark("m0", big, role="glow")))
    # A wash is paint, not light; a small glow is a speck; a glow that comes
    # and goes is not standing.
    assert not has_standing_light(_sketch(_mark("m0", big, role="wash")))
    assert not has_standing_light(_sketch(_mark("m0", _BOX, role="glow")))
    assert not has_standing_light(_sketch(_mark("m0", big, role="glow", when=(("hour", 20, 6),))))
    assert not has_standing_light(_sketch(_mark("m0", big, role="line")))


# -- schedule -----------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class _Fake:
    id: str
    since: date = ANCHOR
    until: date | None = None


def _roster(n: int) -> list[_Fake]:
    return [_Fake(f"s{i:02d}") for i in range(n)]


def _ids(start: date, days: int, salt: str, roster) -> list[str | None]:
    out = []
    for i in range(days):
        s = subject_for(start + timedelta(days=i), salt, roster)
        out.append(None if s is None else s.id)
    return out


def _no_repeat_within(ids: list, span: int) -> bool:
    return all(len(set(ids[i:i + span])) == len(ids[i:i + span])
               for i in range(len(ids)))


@pytest.fixture
def fresh_memo():
    schedule._MEMO.clear()
    yield
    schedule._MEMO.clear()


def test_no_repeat_within_a_week_for_many_salts(fresh_memo):
    roster = _roster(14)
    for k in range(300):
        assert _no_repeat_within(_ids(ANCHOR, 3 * 365 + 1, f"salt-{k}", roster), 7), k


def test_no_repeat_within_a_week_over_twenty_years(fresh_memo):
    assert _no_repeat_within(_ids(ANCHOR, 20 * 365 + 5, "long", _roster(14)), 7)


def test_three_subjects_do_not_repeat_within_three_days(fresh_memo):
    for k in range(20):
        assert _no_repeat_within(_ids(ANCHOR, 400, f"three-{k}", _roster(3)), 3)


def test_picks_are_stable_across_calls_and_a_cleared_memo(fresh_memo):
    roster = _roster(14)
    first = _ids(ANCHOR, 200, "stable", roster)
    assert _ids(ANCHOR, 200, "stable", roster) == first
    schedule._MEMO.clear()
    # Asked for late days first, so the memo is built in a different order.
    assert subject_for(ANCHOR + timedelta(days=150), "stable", roster).id == first[150]
    assert _ids(ANCHOR, 200, "stable", roster) == first


def test_a_future_subject_changes_no_earlier_pick(fresh_memo):
    roster = _roster(14)
    joins = ANCHOR + timedelta(days=400)
    before = _ids(ANCHOR, 400, "join", roster)
    after = _ids(ANCHOR, 400, "join", roster + [_Fake("s99", since=joins)])
    assert after == before
    later = _ids(joins, 300, "join", roster + [_Fake("s99", since=joins)])
    assert "s99" in later


def test_a_retired_subject_is_never_picked_on_or_after_until(fresh_memo):
    until = ANCHOR + timedelta(days=100)
    roster = _roster(7) + [_Fake("gone", until=until)]
    ids = _ids(ANCHOR, 300, "retire", roster)
    assert "gone" in ids[:100]
    assert "gone" not in ids[100:]


def test_a_day_before_the_anchor(fresh_memo):
    early = [_Fake("early-a", since=date(2025, 1, 1)), _Fake("early-b", since=date(2025, 1, 1))]
    roster = early + _roster(5)
    s = subject_for(date(2025, 6, 1), "past", roster)
    assert s is not None and s.id in {"early-a", "early-b"}
    assert subject_for(date(2025, 6, 1), "past", roster) is s
    assert subject_for(date(2024, 6, 1), "past", roster) is None


def test_an_empty_roster(fresh_memo):
    assert subject_for(DAY, "salt", []) is None
    assert subject_for(date(2025, 6, 1), "salt", []) is None


# -- a test-only subject ------------------------------------------------------

@dataclasses.dataclass
class _Sprig:
    id: str = "test-sprig"
    since: date = ANCHOR
    until: date | None = None
    declarative: bool = True

    def render(self, state, theme, rng):
        b = SketchBuilder(self.id, theme, rng)
        for i in range(30):
            x = 12 + i * 4.5
            b.line(pen.curve((x, 185), (x + rng.jitter(3), 130), (x + rng.jitter(6), 70)))
        b.wash(pen.ellipse(80, 175, 60, 18))
        b.wash(pen.circle(80, 80, 45, n=14))
        for i in range(12):
            if self.declarative or state.rewards > 0:
                b.accent(pen.circle(35 + (i % 4) * 30, 45 + (i // 4) * 30, 5),
                         when=(("reward", i),))
        b.ambient(1, (("focus",),),
                  lambda f, fb: fb.line(pen.line((70, 20 + f), (90, 20 + f))))
        return b.build(state)


def test_the_test_subject_is_declarative():
    assert_declarative(_Sprig())


def test_a_state_dependent_subject_is_not():
    with pytest.raises(AssertionError):
        assert_declarative(_Sprig(declarative=False))


def test_one_render_is_fast():
    best = math.inf
    for _ in range(5):
        t = time.perf_counter()
        _Sprig().render(DayState(rewards=3), "light", Rng("speed"))
        best = min(best, time.perf_counter() - t)
    assert best < 0.020, best


def test_drawing_payload_shape_and_no_salt():
    salt = "f00dfeedcafe1234beadfacedeed5678"
    payload = drawing_payload(DAY, "dark", salt, roster=[_Sprig()],
                              state=DayState(rewards=2, focus_active=True))
    assert set(payload) == {"view", "day", "subject", "theme", "viewBox", "marks", "ambient"}
    assert payload["view"] == "today" and payload["day"] == "2026-11-16"
    assert payload["subject"] == "test-sprig" and payload["theme"] == "dark"
    assert len(payload["marks"]) == 30 + 2 + 12
    for m in payload["marks"]:
        keys = {"id", "role", "frames", "when", "reward", "on"}
        assert set(m) == keys | ({"origin"} if m["reward"] is not None else set())
        assert len(m["frames"]) == (3 if m["role"] == "line" else 1)
    rewards = [m for m in payload["marks"] if m["reward"] is not None]
    assert [m["reward"] for m in rewards] == list(range(12))
    assert [m["on"] for m in rewards] == [True, True] + [False] * 10
    assert len(payload["ambient"]["frames"]) == 6
    assert salt not in json.dumps(payload)
    # The same inputs draw the same drawing.
    assert drawing_payload(DAY, "dark", salt, roster=[_Sprig()],
                           state=DayState(rewards=2, focus_active=True)) == payload
    assert drawing_payload(DAY, "dark", salt, roster=[]) is None


def test_view_drawings_are_the_same_every_day():
    views = {"tasks": _Sprig(id="tasks-view")}
    a = drawing_payload(DAY, "light", "salt", view="tasks", views=views)
    b = drawing_payload(DAY + timedelta(days=9), "light", "salt", view="tasks", views=views)
    assert a == b and a["day"] is None and a["view"] == "tasks"
    assert drawing_payload(DAY, "light", "salt", view="calendar", views=views) is None


# -- the route ----------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subjects, "ROSTER", [_Sprig(id=f"test-sprig-{i}") for i in range(5)])
    monkeypatch.setattr(subjects, "VIEW_DRAWINGS", {})
    drawing._cached_payload.cache_clear()
    # The DAV URL points at a closed port: the drawing never reaches the wire.
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "drawing.db")),
        radicale_url="http://127.0.0.1:1", request_timeout_s=1)
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/login",
                      json={"username": "admin", "password": "testpass123"}
                      ).status_code == 200
        yield c
    drawing._cached_payload.cache_clear()


def test_the_route_draws_today(api):
    r = api.get("/api/drawing?day=2026-11-16&theme=dark")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, max-age=3600"
    body = r.json()
    assert body["subject"].startswith("test-sprig-")
    assert body["theme"] == "dark" and body["day"] == "2026-11-16"
    assert body["marks"]


def test_the_route_refuses_bad_input(api):
    assert api.get("/api/drawing?day=2026-13-01").status_code == 422
    assert api.get("/api/drawing?day=2026-11-16&theme=blue").status_code == 422
    assert api.get("/api/drawing").status_code == 422
    r = api.get("/api/drawing?day=2026-11-16&view=tasks")
    assert r.status_code == 404
    assert r.json() == {"detail": "no drawing"}


def test_the_route_needs_a_session(api):
    api.cookies.clear()
    assert api.get("/api/drawing?day=2026-11-16").status_code == 401


def test_the_salt_persists_and_never_leaves(api):
    first = api.get("/api/drawing?day=2026-11-16").json()
    drawing._cached_payload.cache_clear()
    second = api.get("/api/drawing?day=2026-11-16").json()
    assert first["subject"] == second["subject"]
    assert first == second
    salt = api.app.state.service.drawing_salt()
    assert re.fullmatch(r"[0-9a-f]{32}", salt)
    assert salt not in json.dumps(first)


# -- no colour in the engine ----------------------------------------------------

def test_the_engine_names_no_colour():
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(|hsla?\(")
    root = pathlib.Path(smylted.drawing.__file__).parent
    files = [p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert files
    for p in files:
        assert not colour.search(p.read_text(encoding="utf-8")), p


def test_route_takes_only_the_one_day_spelling(api):
    """`date.fromisoformat` takes `20261116` and `2026-W47-1` too; the route
    takes the spelling the client sends and nothing else."""
    for bad in ("20261116", "2026-W47-1", "2026-11-16T00:00"):
        assert api.get(f"/api/drawing?day={bad}").status_code == 422, bad


# ── every registered subject keeps the contract ─────────────────────────────

import time as _time


from smylted.drawing import subjects as _subjects
from smylted.drawing.rng import Rng as _Rng
from smylted.drawing.state import DayState as _DayState


@pytest.mark.parametrize("subject", _subjects.ROSTER, ids=lambda s: s.id)
def test_registered_subject_keeps_the_contract(subject):
    """Declarative (only `on` depends on the state), a reward slot for every one
    of the twelve in both themes, a light and a dark composition that are not
    the same picture, and fast enough to draw on every request."""
    _subjects.assert_declarative(subject)
    renders = {}
    for theme in ('light', 'dark'):
        rng = _Rng.for_day(date(2026, 11, 16), 'contract-salt', f'subject|{subject.id}')
        best = min(
            (lambda: (_t := _time.perf_counter(),
                      subject.render(_DayState(), theme, _Rng(rng.path)),
                      _time.perf_counter() - _t))()[::2]
            for _ in range(3))
        sketch = subject.render(_DayState(rewards=12), theme, _Rng(rng.path))
        renders[theme] = sketch
        rewards = {m.reward for m in sketch.marks if m.reward is not None}
        assert rewards == set(range(12)), f"{subject.id} {theme}: reward slots {sorted(rewards)}"
        assert sketch.ambient is not None, f"{subject.id} {theme}: no focus loop"
        # The client's loop keyframes are written for one second at 6fps.
        assert len(sketch.ambient.frames) == 6, f"{subject.id} {theme}: the focus loop is not 6 frames"
        assert best[1] < 0.05, f"{subject.id} {theme}: {best[1] * 1000:.1f}ms to draw"
        roles = {m.role for m in sketch.marks}
        assert 'line' in roles and 'accent' in roles, roles
    light, dark = renders['light'], renders['dark']
    assert night_overlap(light, dark) <= 0.75, f"{subject.id}: dark is the light drawing"
    assert has_standing_light(dark), f"{subject.id}: the night has no standing light"


def test_paint_order_is_wash_glow_accent_line():
    for subject in _subjects.ROSTER:
        for theme in ('light', 'dark'):
            sketch = subject.render(_DayState(), theme, _Rng('order'))
            order = [{'wash': 0, 'glow': 1, 'accent': 2, 'line': 3}[m.role]
                     for m in sketch.marks]
            assert order == sorted(order), f"{subject.id} {theme}"


# ── the geometry rules, over the roster ─────────────────────────────────────

# Every day draws a different picture of a subject, so the rules are checked on
# a week of days under two salts, not one: a placement that collides one day in
# twenty is still a collision someone sees.
_SAMPLES = [(date(2026, 11, 16) + timedelta(days=d), salt)
            for d in range(7) for salt in ('contract-salt', 'second-salt')]


def _roster_params():
    return [pytest.param(s, id=s.id) for s in _subjects.ROSTER]


def _renders(subject, state, theme):
    for day, salt in _SAMPLES:
        rng = _Rng.for_day(day, salt, f'subject|{subject.id}')
        yield f"{day} {salt}", subject.render(state, theme, rng)


_FULL_STATES = [
    _DayState(progress=1, rewards=12, focus_active=True, all_done=True, overdue=3, hour=h)
    for h in (9, 13, 16, 20, 23)
]
_PLANNED_NOTHING = _DayState(nothing_planned=True, hour=10)
# The everyday states the full grid above never reaches: half the day done,
# Start running and overdue work showing, with everything that is on only while
# the day is not finished (an open notebook, an unlit lantern's glass, the
# laundry still in the basket); and a day with nothing planned that still has
# overdue work and a running clock.
_BUSY_STATES = [
    _DayState(progress=0.5, rewards=6, focus_active=True, overdue=3, hour=h)
    for h in (9, 13, 16, 20, 23)
] + [_DayState(nothing_planned=True, focus_active=True, overdue=3, hour=20)]


@pytest.mark.parametrize("subject", _roster_params())
def test_subject_stays_in_its_frame(subject):
    for theme in ('light', 'dark'):
        for state in _FULL_STATES + [_PLANNED_NOTHING] + _BUSY_STATES:
            for where, sketch in _renders(subject, state, theme):
                errors = bounds_errors(sketch)
                assert not errors, f"{subject.id} {theme} {where} hour {state.hour}: {errors[:5]}"


@pytest.mark.parametrize("subject", _roster_params())
def test_every_reward_can_be_seen(subject):
    for theme in ('light', 'dark'):
        for where, sketch in _renders(subject, _DayState(rewards=12), theme):
            sizes = reward_sizes(sketch)
            for i in range(12):
                across, area = sizes.get(i, (0.0, 0.0))
                assert across >= MIN_REWARD_ACROSS and area >= MIN_REWARD_AREA, (
                    f"{subject.id} {theme} {where}: reward {i} is {across:.1f} across, "
                    f"{area:.1f} square units")


@pytest.mark.parametrize("subject", _roster_params())
def test_no_ink_crosses_by_accident(subject):
    states = _FULL_STATES + [
        _DayState(rewards=0, hour=9),
        _DayState(rewards=4, all_done=True, progress=1, hour=16),
        _PLANNED_NOTHING,
    ] + _BUSY_STATES
    for theme in ('light', 'dark'):
        for state in states:
            for where, sketch in _renders(subject, state, theme):
                found = crossings(sketch, joins_of(subject))
                assert not found, (
                    f"{subject.id} {theme} {where} {state}: ink crosses at "
                    + ", ".join(f"{a} x {b}" for a, b, _ in found[:10]))


@pytest.mark.parametrize("subject", _roster_params())
def test_the_night_is_its_own_picture(subject):
    for (where, light), (_, dark) in zip(_renders(subject, _DayState(rewards=12), 'light'),
                                         _renders(subject, _DayState(rewards=12), 'dark')):
        assert night_overlap(light, dark) <= 0.75, f"{subject.id} {where}"
        assert has_standing_light(dark), f"{subject.id} {where}"
