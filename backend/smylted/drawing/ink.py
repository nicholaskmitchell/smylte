"""The shared ink style: how the desk unit's paper prints a drawing.

One style for every subject, so a subject's 'paper' composition says only what
is there (a line, a fine line, a light or mid tone, a solid, a coral fill) and
never how many pixels it is. `paper.py` prints with it.

The pens, in viewBox units, at the desk's 1.4 px per unit (a 160-unit drawing
224 px wide):
  * the main pen, the phone's own 2.25 units: 3 px;
  * the fine pen, 1.5 units: 2 px, for texture inside a shape (a leaf's
    scallop, a fold), never an outline.

The tones are pen hatches at 45 degrees, lower left to upper right: lines along
x + y = c. The renderer's highlighter screen is ink where (x - y) mod 4 == 0,
the other diagonal, so a tone never reads as the highlighter. A hatch is
anchored to the canvas, so neighbouring areas of one tone share their lines.
  * light: the fine pen at 4 fine pens' pitch, 25% ink (2 px every 8 px);
  * mid: the main pen at 2.5 pens' pitch, the coral fills' hatch since 17 Nov
    (3 px every 8 px, 37.5% in theory, about 38% printed).

The coral fills (`accent` marks) keep the owner's 17 Nov rule
(docs/fieldnotes-gaps.md): a fill HATCH_FROM units across or more prints in the
mid tone inside its ink outline; a smaller one prints solid; a round reward
marked paper='glint' (a fruit) prints solid with a spot of paper in it.

In 4-grey (levels 0 paper, 1 light, 2 dark, 3 ink) a tone is flat instead of
hatched: light is level 1, mid and every coral fill level 2 (a fruit keeps its
glint), and lines and solids level 3.
"""
from __future__ import annotations

from dataclasses import dataclass

from .pen import PEN

FINE_PEN = 1.5             # the fine pen, in viewBox units
HATCH_FROM = 8.0           # accent fills this many units across or more are hatched


@dataclass(frozen=True)
class Tone:
    pen: str               # 'main' or 'fine'
    pitch: float           # the hatch's line spacing, in widths of that pen


LIGHT = Tone(pen='fine', pitch=4.0)
MID = Tone(pen='main', pitch=2.5)
TONES = {'light': LIGHT, 'mid': MID}

# The four levels of the 4-grey render, as 8-bit values: what the panel's grey
# planes are made from.
LEVEL_PAPER = 255
LEVEL_LIGHT = 0xC0
LEVEL_DARK = 0x80
LEVEL_INK = 0
TONE_LEVELS = {'light': LEVEL_LIGHT, 'mid': LEVEL_DARK}
ACCENT_LEVEL = LEVEL_DARK


def pen_px(px_per_unit: float) -> int:
    """The pen on paper, in device pixels: the phone's 2.25-unit pen, at least 2px."""
    return max(2, round(PEN * px_per_unit))


def fine_px(px_per_unit: float) -> int:
    """The fine pen on paper, in device pixels, at least 1px."""
    return max(1, round(FINE_PEN * px_per_unit))


def tone_px(tone: Tone, px_per_unit: float) -> tuple[int, int]:
    """A tone's hatch in device pixels: (line width, pitch)."""
    width = pen_px(px_per_unit) if tone.pen == 'main' else fine_px(px_per_unit)
    return width, round(width * tone.pitch)
