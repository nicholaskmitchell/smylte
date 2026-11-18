"""The drawing as the 1-bit desk unit prints it: ink on paper and nothing else.

Lines are the pen, in ink. The wash and the glow are dropped, because paper has
no tones to give them. A coral fill (an `accent` mark) is not solid ink when it
is large: a fill 8 units or more across becomes a pen hatch at about the
coral's 40% tone, always inside its ink outline, so a big fill (a note, a
garment) never turns into a black block. A smaller fill stays solid ink.

A round reward marked paper='glint' (a fruit) stays solid at any size, with a
spot of paper left in it so it reads as round and shiny: the owner's choice
was "small ones like fruit stay solid with a paper glint", and a disc with a
glint reads as fruit where a hatched disc reads as a button. Only the light
compositions are ever printed, so in practice that is the tree's fruit.

There is no boil here: every mark is drawn from its first frame, and the focus
loop from its first frame while it runs.

The result follows the desk unit's own way of working: everything is drawn
anti-aliased into an 8-bit canvas (255 paper, 0 ink) that the caller can paste
into its own, and the threshold to one bit happens once, at the very end. Ink
and paper are the integers 255 and 0, never colours.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw

from .checks import polyline
from .scene import Mark, Sketch

MIN_WIDTH = 160            # no drawing on a panel narrower than this (px)
HATCH_FROM = 8.0           # accent fills this many units across or more are hatched
SUPERSAMPLE = 4

PAPER = 255
INK = 0

_STEPS = 8
# Hatch pitch, as a multiple of the pen: pen / pitch is the ink share.
_PITCH = 2.5
_SMALL_REWARD = 16.0


def pen_px(px_per_unit: float) -> int:
    """The pen on paper, in device pixels: the phone's 2.25-unit pen, at least 2px."""
    return max(2, round(2.25 * px_per_unit))


def one_bit(img: Image.Image) -> Image.Image:
    """The desk unit's own final step: threshold at 128 with no dither, mode '1'."""
    return img.point(lambda v: 255 if v >= 128 else 0).convert('1', dither=Image.Dither.NONE)


def _marks(sketch: Sketch) -> list[Mark]:
    marks = [m for m in sketch.marks if m.on]
    if sketch.ambient is not None and sketch.ambient.frames:
        marks += [m for m in sketch.ambient.frames[0] if m.on]
    return [m for m in marks if m.role in ('accent', 'line')]


def _hatch(canvas: Image.Image, poly: list[tuple[float, float]], pen: int, *, fine: bool) -> None:
    """Fill the polygon with pen strokes at 45 degrees, lower-left to
    upper-right (direction (1, -1) in image coordinates). The highlighter
    elsewhere uses the opposite diagonal."""
    S = SUPERSAMPLE
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    left, top = max(0, int(min(xs))), max(0, int(min(ys)))
    right = min(canvas.width, int(max(xs)) + 2)
    bottom = min(canvas.height, int(max(ys)) + 2)
    if right <= left or bottom <= top:
        return
    size = (right - left, bottom - top)
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).polygon([(x - left, y - top) for x, y in poly], fill=255)
    layer = Image.new('L', size, PAPER)
    draw = ImageDraw.Draw(layer)
    pitch = round(pen * _PITCH) * S
    # The lines lie along x + y = c; the perpendicular gap between two of them
    # is the step in c over the square root of two. Anchored to the canvas, so
    # neighbouring fills share one hatch.
    step = pitch * 2 ** 0.5
    base = left + top
    n = int((base - pen * S) // step)
    width = round(pen * S * 0.8) if fine else pen * S
    while n * step <= base + size[0] + size[1] + pen * S:
        c = n * step - base
        draw.line([(c - size[1], size[1]), (c, 0)], fill=INK, width=width)
        n += 1
    canvas.paste(layer, (left, top), mask)


def _glint(canvas, poly, gx: float, gy: float, radius: float) -> None:
    """Leave a spot of paper inside the fill after the ink has been drawn."""
    left, top = max(0, int(gx - radius)), max(0, int(gy - radius))
    right = min(canvas.width, int(gx + radius) + 1)
    bottom = min(canvas.height, int(gy + radius) + 1)
    if left >= right or top >= bottom:
        return
    size = (right - left, bottom - top)
    fill = Image.new('L', size)
    ImageDraw.Draw(fill).polygon([(x - left, y - top) for x, y in poly], fill=PAPER)
    spot = Image.new('L', size)
    ImageDraw.Draw(spot).ellipse((gx - radius - left, gy - radius - top,
                                  gx + radius - left, gy + radius - top), fill=PAPER)
    canvas.paste(PAPER, (left, top, right, bottom), ImageChops.darker(fill, spot))


def paper_image(sketch: Sketch, width_px: int) -> Image.Image | None:
    """The drawing as the desk unit prints it: mode 'L', 255 paper and 0 ink,
    width_px wide and round(width_px * h / w) high. None below MIN_WIDTH."""
    if width_px < MIN_WIDTH:
        return None
    x0, y0, w, h = sketch.view_box
    ppu = width_px / w
    height_px = round(width_px * h / w)
    S = SUPERSAMPLE
    pen = pen_px(ppu)
    canvas = Image.new('L', (width_px * S, height_px * S), PAPER)
    draw = ImageDraw.Draw(canvas)
    k = ppu * S

    def to_px(p: tuple[float, float]) -> tuple[float, float]:
        return ((p[0] - x0) * k, (p[1] - y0) * k)

    glints = []

    def paint(marks: list[Mark]) -> None:
        small_rewards = set()
        for mark in marks:
            if mark.role != 'accent':
                continue
            subpaths = polyline(mark.frames[0], steps=_STEPS)
            if not subpaths or len(subpaths[0]) < 3:
                continue
            pts = subpaths[0]
            xs, ys = zip(*pts)
            bw, bh = max(xs) - min(xs), max(ys) - min(ys)
            poly = [to_px(p) for p in pts]
            fine = mark.reward is not None and max(bw, bh) < _SMALL_REWARD
            if fine:
                small_rewards.add((mark.reward, mark.part))
            if mark.paper == 'glint' or max(bw, bh) < HATCH_FROM:
                draw.polygon(poly, fill=INK)
                if mark.paper == 'glint':
                    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                    r = min(bw, bh) / 2
                    gx, gy = to_px((cx - 0.38 * r, cy - 0.38 * r))
                    glints.append((poly, gx, gy, max(1.0, 0.25 * r * k)))
            else:
                _hatch(canvas, poly, pen, fine=fine)

        for mark in marks:
            if mark.role != 'line':
                continue
            d = mark.frames[0]
            for path in polyline(d, steps=_STEPS):
                width = pen * S
                if (mark.reward, mark.part) in small_rewards and not d.endswith(' Z'):
                    xs, ys = zip(*path)
                    if max(max(xs) - min(xs), max(ys) - min(ys)) < HATCH_FROM:
                        # A short detail, such as a pine cone's scales, needs paper around it.
                        width = round(width * 2 / 3)
                pts = [to_px(p) for p in path]
                if len(pts) > 1:
                    draw.line(pts, fill=INK, width=width)
                half = width / 2
                # Pillow has neither round caps nor round joins.
                for x, y in pts:
                    draw.ellipse((x - half, y - half, x + half, y + half), fill=INK)

    marks = _marks(sketch)
    # An earned mark sits over the scene's ink, such as a bow tied to the kite tail.
    paint([m for m in marks if m.reward is None])
    paint([m for m in marks if m.reward is not None])
    for location in glints:
        _glint(canvas, *location)

    return canvas.reduce(S)
