"""December: snow at the door.

Day: a cottage front fills the right of the page, its roof's eave lying under
a scalloped line of snow. A plank door with a small four-pane window, and on
it a wreath of leaves with three coral berries. An unlit lantern hangs on a
bracket beside the door, a small pine stands in a pot at its left, a drift lies
against the wall, and a few snowflakes fall in the sky at the left.

Night: the same cottage with the lantern lit and the door's window glowing,
and stars over the left where the snow fell. The snow has stopped.

A month drawing: still, and the same whatever the day's state (months/_page.py).
"""
from __future__ import annotations

import math

from ...pen import PEN, WOBBLE, curve, line, loop, poly
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

EAVE = 42.0                              # the eave's line, under the snow
APEX = (131.0, 12.0)
ROOF = (68.0, 194.0)                     # the eave's ends
WALLS = (76.0, 186.0)
DOOR = (112.0, 49.0, 150.0)              # x0, top, x1
PANE = (125.0, 54.5, 137.0, 63.5)        # the door's window: x0, y0, x1, y1
WREATH = (131.0, 79.0)                   # the wreath's centre
SEAMS = (119.0, 143.0)
LANTERN = (167.0, 73.0)                  # the lantern's centre
POT = (95.0, 88.0)                       # the pot's top centre
# Ink and wobble on one side of a line: what a flake's or star's reach clears.
INK = PEN / 2 + WOBBLE


class December:
    id = 'month-december'
    JOINS = frozenset(frozenset(p) for p in (
        ('roof', 'snow'), ('wall', 'snow'), ('wall', 'roof'), ('wall', 'ground'),
        ('door', 'ground'), ('pot', 'ground'), ('pine', 'pot'),
        ('berry', 'wreath'), ('bracket', 'lantern'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, view_box=VIEW_BOX, still=True)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s, rng.fork('day'))
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same cottage."""
    return {
        'snow': [r.uniform(-0.6, 0.6) for _ in range(9)],
        'leaves': r.uniform(-0.12, 0.12),
        'drift': r.fork('drift'),
    }


def _pine_outline():
    """Two tiers and a tip, closed: the pine in its pot."""
    x, top = POT[0], POT[1] - 6.0
    return poly((x - 11, top), (x - 4, top - 12), (x - 8.5, top - 12), (x, top - 30),
                (x + 8.5, top - 12), (x + 4, top - 12), (x + 11, top))


def _door_outline():
    x0, y0, x1 = DOOR
    return poly((x0, GROUND), (x0, y0), (x1, y0), (x1, GROUND))


def _cottage(b: SketchBuilder, s: dict) -> None:
    b.line(curve((6, GROUND + 0.6), (100, GROUND - 0.5), (194, GROUND + 0.6)), part='ground')
    x0, x1 = ROOF
    b.line(line((x0, EAVE), APEX, (x1, EAVE)), part='roof')
    b.line(line((x0, EAVE), (x1, EAVE)), part='roof')
    # The snow lying along the eave: round lumps resting on it, the troughs on the line.
    n = 9
    w = (x1 - x0 - 4) / n
    pts, corners = [], []
    for i in range(n + 1):
        x = x0 + 2 + w * i
        corners.append(len(pts))
        pts.append((x, EAVE - 0.4))
        if i < n:
            h = 5.0 + s['snow'][i]
            pts.extend(((x + w * 0.2, EAVE - h * 0.85), (x + w * 0.5, EAVE - h),
                        (x + w * 0.8, EAVE - h * 0.85)))
    b.line(curve(*pts, corners=corners), part='snow')
    for x in WALLS:
        b.line(line((x, GROUND), (x, EAVE)), part='wall')
    # The door, its seams hidden behind the wreath, and its window.
    b.line(line((DOOR[0], GROUND), (DOOR[0], DOOR[1]), (DOOR[2], DOOR[1]), (DOOR[2], GROUND)),
           part='door')
    cx, cy = WREATH
    for x in SEAMS:
        hide = math.sqrt(max(0.0, 15.0 ** 2 - (x - cx) ** 2))
        b.line(line((x, DOOR[1] + 5.5), (x, cy - hide)), part='seam')
        b.line(line((x, cy + hide), (x, GROUND - 5.0)), part='seam')
    px0, py0, px1, py1 = PANE
    b.line(poly((px0, py0), (px1, py0), (px1, py1), (px0, py1)), part='pane')
    b.line(line(((px0 + px1) / 2, py0), ((px0 + px1) / 2, py1)), part='pane')
    b.line(line((px0, (py0 + py1) / 2), (px1, (py0 + py1) / 2)), part='pane')
    # The wreath: leaves round a ring, open at its foot, where three coral berries sit.
    for i in range(6):
        a = math.radians(128 + 47 * i) + s['leaves']
        b.line(k.leaf(cx + 6.5 * math.cos(a), cy + 6.5 * math.sin(a), 7.5, a + math.pi / 2), part='wreath')
    for bx, by in ((cx - 3.9, cy + 6.6), (cx + 3.9, cy + 6.6), (cx, cy + 10.4)):
        b.filled(k.ring(bx, by, 3.7, 9), part='berry', paper='glint')
    # The pine in its pot.
    x, top = POT
    b.line(poly((x - 7, top), (x + 7, top), (x + 5, GROUND), (x - 5, GROUND)), part='pot')
    b.line(_pine_outline(), part='pine')
    b.line(line((x, top - 6.0), (x, top)), part='pine')
    # The lantern on its bracket.
    lx = LANTERN[0]
    b.line(line((157.0, 53.0), (157.0, 62.0)), part='bracket')
    b.line(line((157.0, 58.0), (lx, 58.0), (lx, 62.0)), part='bracket')
    b.line(poly((lx - 8, 66.0), (lx, 62.0), (lx + 8, 66.0)), part='lantern')
    b.line(poly((lx - 6.5, 66.0), (lx + 6.5, 66.0), (lx + 6.5, 81.0), (lx - 6.5, 81.0)), part='lantern')
    b.line(line((lx - 8, 81.0), (lx + 8, 81.0)), part='lantern')


def _sky_left(p) -> bool:
    """The open sky left of the cottage's eave, above the drift."""
    x, y = p
    return y <= 84 and x <= ROOF[0] - 6


def _flakes(b: SketchBuilder, r: Rng, count: int) -> None:
    """Snowflakes: small six-armed stars, apart and clear of the cottage."""
    reach = 3.4 + INK
    around = [(reach * math.cos(math.pi * i / 4), reach * math.sin(math.pi * i / 4)) for i in range(8)]
    out: list[tuple[float, float]] = []
    for _ in range(400):
        if len(out) == count:
            break
        p = (r.uniform(10.0, 60.0), r.uniform(10.0, 80.0))
        if any(math.dist(p, q) < 15.0 for q in out):
            continue
        if not all(_sky_left((p[0] + dx, p[1] + dy)) for dx, dy in [(0, 0), *around]):
            continue
        out.append(p)
    for i, (x, y) in enumerate(out):
        turn = r.uniform(0, math.pi / 3)
        arm = r.uniform(3.0, 3.4)
        for j in range(3):
            a = turn + math.pi * j / 3
            b.line(line((x - arm * math.cos(a), y - arm * math.sin(a)),
                        (x + arm * math.cos(a), y + arm * math.sin(a))), part=f'flake:{i}')


def _washes(b: SketchBuilder, s: dict) -> None:
    b.wash(k.wash_of(_pine_outline(), inset=0.9, dx=2.5, dy=2.5), part='pine')
    b.wash(k.wash_of(_door_outline(), inset=0.86, dx=2.5, dy=1.5), part='door')
    b.wash(k.blob(70.0, 96.0, 17.0, 5.0, s['drift'], n=11, wobble=0.08), part='drift')


def _day(b: SketchBuilder, s: dict, r: Rng) -> None:
    _washes(b, s)
    _cottage(b, s)
    _flakes(b, r.fork('flakes'), 6)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    _washes(b, s)
    lx, ly = LANTERN
    # The lantern lit: the standing light. The door's window glows too.
    b.glow(k.ring(lx, ly, 17.0, 12), part='lamp')
    px0, py0, px1, py1 = PANE
    b.glow(k.ring((px0 + px1) / 2, (py0 + py1) / 2, 10.0, 11), part='window')
    _cottage(b, s)
    b.line(loop((lx, 70.8), (lx + 1.7, 74.6), (lx, 76.0), (lx - 1.7, 74.6), corners=(0,)), part='flame')
    k.stars(b, r.fork('stars'), 4, (10.0, 8.0, 60.0, 70.0), ok=_sky_left, gap=16.0, part='star')
