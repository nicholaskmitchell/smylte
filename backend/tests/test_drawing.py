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
from smylted.drawing.pen import WOBBLE, Pen
from smylted.drawing.rng import cyrb128
from smylted.drawing.schedule import ANCHOR
from smylted.drawing.subjects import assert_declarative
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


# -- scene --------------------------------------------------------------------

def _builder(path: str = "scene") -> SketchBuilder:
    return SketchBuilder("test", "light", Rng(path))


def test_build_sets_on_per_state():
    b = _builder()
    b.line(pen.line((0, 0), (10, 10)), when=(("focus",),))
    b.wash(pen.circle(5, 5, 3))
    off, on = b.build(DayState()), b.build(DayState(focus_active=True))
    # Marks come back in paint order (wash, accent, line), ids as drawn.
    assert [m.id for m in on.marks] == ["m1", "m0"]
    assert {m.id: m.on for m in off.marks} == {"m0": False, "m1": True}
    assert {m.id: m.on for m in on.marks} == {"m0": True, "m1": True}
    by_id = {m.id: m for m in on.marks}
    assert len(by_id["m0"].frames) == 3 and len(by_id["m1"].frames) == 1


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
        assert set(m) == {"id", "role", "frames", "when", "reward", "on"}
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
    light = [m.frames for m in renders['light'].marks]
    dark = [m.frames for m in renders['dark'].marks]
    assert light != dark, f"{subject.id}: dark is the light drawing"


def test_paint_order_is_wash_then_accent_then_line():
    for subject in _subjects.ROSTER:
        for theme in ('light', 'dark'):
            sketch = subject.render(_DayState(), theme, _Rng('order'))
            order = [{'wash': 0, 'accent': 1, 'line': 2}[m.role] for m in sketch.marks]
            assert order == sorted(order), f"{subject.id} {theme}"
