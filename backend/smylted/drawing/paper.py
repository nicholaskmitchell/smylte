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

from PIL import Image, ImageDraw

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


def _hatch(canvas: Image.Image, poly: list[tuple[float, float]], pen: int) -> None:
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
    while n * step <= base + size[0] + size[1] + pen * S:
        c = n * step - base
        draw.line([(c - size[1], size[1]), (c, 0)], fill=INK, width=pen * S)
        n += 1
    canvas.paste(layer, (left, top), mask)


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

    marks = _marks(sketch)

    for mark in marks:
        if mark.role != 'accent':
            continue
        subpaths = polyline(mark.frames[0], steps=_STEPS)
        if not subpaths or len(subpaths[0]) < 3:
            continue
        pts = subpaths[0]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        poly = [to_px(p) for p in pts]
        if mark.paper == 'glint' or max(bw, bh) < HATCH_FROM:
            draw.polygon(poly, fill=INK)
            if mark.paper == 'glint':
                cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                r = min(bw, bh) / 2
                gx, gy = to_px((cx - 0.38 * r, cy - 0.38 * r))
                gr = max(1.0, 0.25 * r * k)
                draw.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=PAPER)
        else:
            _hatch(canvas, poly, pen)

    half = pen * S / 2
    for mark in marks:
        if mark.role != 'line':
            continue
        for path in polyline(mark.frames[0], steps=_STEPS):
            pts = [to_px(p) for p in path]
            if len(pts) > 1:
                draw.line(pts, fill=INK, width=pen * S)
            # Pillow has neither round caps nor round joins: a disc at every vertex.
            for x, y in pts:
                draw.ellipse((x - half, y - half, x + half, y + half), fill=INK)

    return canvas.reduce(S)
