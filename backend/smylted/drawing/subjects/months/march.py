"""March: wind and showers.

Day: an open umbrella planted in the ground, leaning a little with the wind;
a pair of coral wellington boots beside it; a small cloud at the left with
slanted rain falling into a puddle on the path, splashing in it; three
daffodils at the right, their heads nodding.

Night: the rain has stopped. The umbrella is furled and leans on the boots,
a moon with its glow stands beside a cloud, and stars come out. The puddle
keeps its wash.

A month drawing: still, and the same whatever the day's state.
"""
from __future__ import annotations

import math

from ...pen import curve, line, loop
from ...rng import Rng
from ...scene import Sketch, SketchBuilder
from ...state import DayState, Theme
from .. import _kit as k
from ._page import GROUND, VIEW_BOX

# The puddle on the path: centre, half-width, half-height.
PUDDLE = (40.0, 98.5, 17.0, 3.2)
# Where the open umbrella's shaft meets the ground, and its lean.
FOOT = (86.0, GROUND)
LEAN = 0.1
# The boots: each one's heel x (the shaft's back edge).
BOOTS = (109.0, 133.0)
BOOT_TOP = 70.0
# The daffodils: stem x, the height its neck turns, the way its head faces,
# and its leaf's side and length.
DAFFODILS = ((158.0, 56.0, -1, -1, 25.0), (167.0, 44.0, 1, 1, 15.0),
             (190.0, 66.0, -1, 1, 22.0))
# The heads' size: large enough to read as daffodils in a narrow header.
HEAD = 1.3
MOON = (68.0, 26.0, 7.0)
# The night's cloud, beside the moon and never under it.
NIGHT_CLOUD = (32.0, 28.0, 30.0)


class March:
    id = 'month-march'
    JOINS = frozenset(frozenset(p) for p in (
        ('umbrella', 'ground'), ('boot', 'ground'), ('puddle', 'ground'),
        ('daffodil', 'ground'), ('umbrella', 'boot'),
    ))

    def render(self, state: DayState, theme: Theme, rng: Rng) -> Sketch:
        b = SketchBuilder(self.id, theme, rng, view_box=VIEW_BOX, still=True)
        s = _structure(rng.fork('scene'))
        if theme == 'light':
            _day(b, s)
        else:
            _night(b, s, rng.fork('night'))
        return b.build(state)


def _structure(r: Rng) -> dict:
    """What both compositions share, so the night is the same place."""
    return {
        'ground': [r.uniform(-0.5, 0.5) for _ in range(4)],
        'nod': [r.uniform(-0.15, 0.15) for _ in DAFFODILS],
    }


def _puddle():
    cx, cy, rx, ry = PUDDLE
    return k.blob(cx, cy, rx, ry, Rng('puddle'), n=10, wobble=0.04)


def _ground(b: SketchBuilder, s: dict) -> None:
    """The ground line, broken where the puddle lies on the path."""
    cx, cy, rx, _ = PUDDLE
    g = s['ground']
    b.line(line((6.0, GROUND + g[0]), (cx - rx + 0.6, cy)), part='ground')
    b.line(curve((cx + rx - 0.6, cy), (110.0, GROUND + g[1]), (152.0, GROUND + g[2]),
                 (194.0, GROUND + g[3])), part='ground')


def _boots(b: SketchBuilder) -> None:
    """A pair of wellingtons standing side by side, toes to the right: the
    coral note, each boot filled inside its outline, with a turned-down cuff."""
    for i, x in enumerate(BOOTS):
        top = BOOT_TOP + (1.5 if i else 0.0)
        boot = loop((x, top), (x + 10.0, top), (x + 10.4, 87.0), (x + 14.6, 89.4),
                    (x + 17.0, 93.0), (x + 17.0, GROUND - 0.4), (x + 0.4, GROUND - 0.4),
                    corners=(0, 1, 5, 6))
        b.filled(boot, part=f'boot:{i}')
        b.line(line((x + 0.4, top + 5.0), (x + 9.8, top + 5.0)), part=f'boot:{i}')


def _head(x: float, neck: float, face: int) -> tuple[float, float]:
    """Where a daffodil's head sits: the ruff's centre, just past its neck."""
    return x + face * 4.0 * HEAD, neck + 2.0


def _daffodils(b: SketchBuilder, s: dict) -> None:
    """Three daffodils in a clump, ink only: a stem that bends at its neck, a
    long blade of a leaf, and a nodding head seen from the side, its trumpet
    flaring out of a ruff of petals."""
    for i, ((x, neck, face, side, blade), nod) in enumerate(zip(DAFFODILS, s['nod'])):
        part = f'daffodil:{i}'
        hx, hy = _head(x, neck, face)
        b.line(curve((x, GROUND), (x - face * 0.6, (GROUND + neck) / 2), (x - face * 0.2, neck + 5.0),
                     (hx - face * 2.6 * HEAD, hy)), part=part)
        b.line(curve((x + side * 0.8, GROUND), (x + side * 3.0, GROUND - blade * 0.55),
                     (x + side * 5.6, GROUND - blade)), part=part)
        c, sn = math.cos(nod), math.sin(nod)

        def at(u: float, v: float) -> tuple[float, float]:
            u, v = u * HEAD, v * HEAD
            return (hx + face * (u * c - v * sn), hy + u * sn + v * c)

        # The ruff of petals: a pointed lens across the neck.
        b.line(loop(at(0.0, -7.0), at(-2.6, 0.0), at(0.0, 7.0), at(2.0, 0.0), corners=(0, 2)),
               part=part)
        # The trumpet, flaring out of the ruff to a frilled mouth.
        b.line(curve(at(1.6, -2.4), at(8.6, -4.6), at(9.6, -2.2), at(8.8, 0.0), at(9.6, 2.2),
                     at(8.6, 4.6), at(1.6, 2.4), corners=(1, 5)), part=part)


def _umbrella_open(b: SketchBuilder) -> None:
    """The open umbrella, planted by its handle and leaning with the wind, in
    ink: a canopy with a scalloped hem, its ribs, a ferrule and the shaft."""
    fx, fy = FOOT

    def turn(*pts):
        return k.rotate(pts, FOOT, LEAN)

    rim = 56.0
    hem = [fx - 24.0, fx - 12.0, fx, fx + 12.0, fx + 24.0]
    canopy = turn((hem[0], rim), (fx - 22.0, 45.0), (fx - 14.0, 37.5), (fx, 34.0),
                  (fx + 14.0, 37.5), (fx + 22.0, 45.0), (hem[4], rim),
                  (fx + 18.0, rim - 3.2), (hem[3], rim + 0.8), (fx + 6.0, rim - 2.6),
                  (hem[2], rim + 1.2), (fx - 6.0, rim - 2.6), (hem[1], rim + 0.8),
                  (fx - 18.0, rim - 3.2))
    b.line(loop(*canopy, corners=(0, 6, 8, 10, 12)), part='umbrella')
    apex, = turn((fx, 34.0))
    for u in (-12.0, 12.0):
        mid, end = turn((fx + u * 0.55, 44.0), (fx + u, rim + 0.8))
        b.line(curve(apex, mid, end), part='umbrella')
    b.line(line(*turn((fx, 34.0), (fx, 27.5))), part='umbrella')
    b.line(line(*turn((fx, rim + 1.2), (fx, fy))), part='umbrella')


def _umbrella_furled(b: SketchBuilder) -> None:
    """The umbrella furled and leaning on the first boot: its ferrule on the
    ground, the cloth rolled tight, the shaft and the crook above."""
    x0 = BOOTS[0]
    tip = (x0 - 20.5, GROUND)
    rest = (x0 - 0.6, BOOT_TOP + 1.0)        # where the cloth lies on the boot
    dx, dy = rest[0] - tip[0], rest[1] - tip[1]
    ln = math.hypot(dx, dy)
    ux, uy = dx / ln, dy / ln
    nx, ny = -uy, ux                        # across the umbrella, toward the boot

    def at(s_: float, w: float) -> tuple[float, float]:
        return (tip[0] + ux * s_ + nx * w, tip[1] + uy * s_ + ny * w)

    # The rest point is on the cloth's edge, so the axis runs half a cloth
    # away from the boot.
    off = -4.6
    # The ferrule runs on down its own axis until its tip meets the ground.
    p0 = at(0.0, off)
    s0 = (GROUND + 0.2 - p0[1]) / uy
    b.line(line(at(s0, off), at(9.0, off)), part='umbrella')
    b.line(loop(at(9.0, off), at(20.0, off - 3.2), at(31.0, off - 4.8), at(40.0, off - 3.8),
                  at(44.0, off), at(40.0, off + 3.8), at(31.0, off + 4.8), at(20.0, off + 3.2),
                  corners=(0, 4)), part='umbrella')
    b.line(line(at(44.0, off), at(54.0, off)), part='umbrella')
    hook = [at(54.0, off), at(57.5, off + 0.6), at(59.0, off + 3.4), at(57.4, off + 6.2),
            at(54.6, off + 6.6)]
    b.line(curve(*hook), part='umbrella')


def _rain(b: SketchBuilder) -> None:
    """Short slanted strokes under the cloud, in staggered rows."""
    n = 0
    for row, y in enumerate((32.0, 44.0, 56.0)):
        x0 = 20.0 if row % 2 == 0 else 25.0
        for j in range(5 if row % 2 == 0 else 4):
            x = x0 + 9.0 * j
            b.line(line((x, y), (x + 2.2, y + 6.0)), part=f'rain:{n}')
            n += 1


def _splash(b: SketchBuilder) -> None:
    """Where the rain lands in the puddle: one splash, off centre, rising out
    of the puddle's surface: three arcs of different lengths fanning out of one
    point and curling outward, a short one to the left, a tall one in the
    middle and a longer one to the right."""
    x, y = PUDDLE[0] + 5.0, 95.9             # just inside the puddle's top edge
    b.line(curve((x, y), (x - 1.2, y - 3.2), (x - 3.8, y - 4.8)), part='puddle')
    b.line(curve((x, y), (x - 0.6, y - 4.6), (x + 0.4, y - 8.4)), part='puddle')
    b.line(curve((x, y), (x + 1.6, y - 3.8), (x + 4.8, y - 5.8)), part='puddle')


def _day(b: SketchBuilder, s: dict) -> None:
    puddle = _puddle()
    b.wash(k.wash_of(puddle, dx=2.0, dy=1.0), part='puddle')
    k.cloud(b, 40.0, 15.0, 44.0, part='cloud')
    _rain(b)
    _ground(b, s)
    b.line(puddle, part='puddle')
    _splash(b)
    _umbrella_open(b)
    _boots(b)
    _daffodils(b, s)


def _night(b: SketchBuilder, s: dict, r: Rng) -> None:
    puddle = _puddle()
    b.wash(k.wash_of(puddle, dx=2.0, dy=1.0), part='puddle')
    mx, my, mr = MOON
    k.moon(b, mx, my, mr, clouds=0)
    cx, cy, cw = NIGHT_CLOUD
    k.cloud(b, cx, cy, cw, part='cloud')
    avoid = [(mx, my, mr + 4.0), (cx, cy, cw / 2 + 4.0)]
    heads = [(*_head(x, neck, face), 12.5 * HEAD) for x, neck, face, _, _ in DAFFODILS]
    k.stars(b, r.fork('stars'), 4, (92.0, 8.0, 192.0, 40.0), avoid=avoid + heads)
    k.stars(b, r.fork('low'), 2, (10.0, 36.0, 50.0, 50.0), avoid=avoid, gap=24.0, part='spark')
    _ground(b, s)
    b.line(puddle, part='puddle')
    _umbrella_furled(b)
    _boots(b)
    _daffodils(b, s)
