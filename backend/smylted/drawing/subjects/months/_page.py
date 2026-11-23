"""The page a month drawing is drawn on, and the rules it keeps on top of
_kit.py's (tests/test_drawing.py, *the month drawings*).

A month drawing sits before the month's name in the Calendar's header on a
desktop: 210 px wide, or 160 px in a narrow header. So it is LANDSCAPE, 200 x 110
units, about a pixel a unit; the phone never shows it.

* Still: SketchBuilder(self.id, theme, rng, view_box=VIEW_BOX, still=True), so
  every mark is one frame and nothing boils. No ambient, no `when`, no reward,
  no anchor, and the same drawing whatever the DayState. k.moon takes clouds=0,
  because its clouds are conditions.
* Everything in _kit.py's docstring: ground is an ink line; a wash closes inside
  the picture, 6 units clear of every edge (wash_of a closed outline, or a soft
  blob); ink touches ink only where JOINS says; parallel strokes MIN_GAP apart;
  the subject fills the frame and nothing leaves it.
* One coral note, drawn with b.filled (a fill inside its own ink outline).
* A night of its own: at most 90% of the dark marks where a light one is, at
  least four of its own, and a standing light (an unconditional glow of 600
  units^2 or more: a moon of radius 6 or more with its glow, a lit window, a
  lantern, a fire). By day a sun may stand in the sky, placed once: there is
  no hour.
* Small: at most 24,000 bytes of JSON and 200 paths a theme; under 10 ms to draw.
* Readable at 160 px: nothing that matters smaller than 5 units.
"""
from __future__ import annotations

VIEW_BOX = (0, 0, 200, 110)
# Where the ground line runs, as the November mockup has it.
GROUND = 98.0
