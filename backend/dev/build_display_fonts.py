"""Rebuild the TTFs the display renderer draws with, from the app's own woff2.

    python -m dev.build_display_fonts

The display is one design with two rasterizers — a browser and Pillow — and this
is what keeps the second one in the first one's typefaces. It takes the THREE
SHIPPED FAMILIES from `frontend/public/fonts/` and pins each to the weight (and,
for Fraunces, the optical size) the design actually uses, writing static TTFs
into `tasksd/display/fonts/`.

Nothing imports this at runtime. It is here rather than in a README snippet
because the choices below are empirical — they were measured against a
thresholded 1-bit render — and a build step whose reasoning lives in prose gets
re-run with different numbers the first time someone tries.

**Why TTF at all.** No Python rasterizer reads woff2; FreeType, which is what
Pillow is, takes SFNT. The conversion is mechanical: decompress, pin the
variable axes, merge the two unicode subsets.

**Why the subsets are MERGED rather than one being picked.** They carve up the
alphabet between them — `inter-latin` holds ASCII and Latin-1 (so `ü`, `é`,
`ç`), `inter-latin-ext` holds the rest of extended Latin (so `ż`, `ł`). What a
display draws is the owner's own text, and a list called *Ćwiczenia* should not
render as a row of boxes.

**Why these weights.**

  * Fraunces at **wght 500** is the weight `.cal-title`, `.content-title` and
    `.day-col-head .dnum` use in app.css. The display is not inventing a
    headline weight, it is borrowing the one the product already has.
  * Fraunces at **opsz 9** — the font's own default, and the sturdy end of its
    optical-size axis. This is the empirical one. Fraunces' high optical sizes
    are a display cut with fine hairlines, which is exactly what a one-bit
    panel destroys: measured at opsz 144, "August 2026" loses its stems and a
    15px day number is mush, while opsz 9 stays solid from 15px to 44px and
    still reads unmistakably as Fraunces. It is also the value the browser
    resolves to under `font-optical-sizing: none`, which display.css sets for
    the eink palette — so both rasterizers draw the same letterforms rather
    than merely the same family.
  * JetBrains Mono at **wght 500**, one step above the 400 app.css leaves its
    micro-labels at. A label in the app is read at arm's length and one on a
    wall at three metres, and one weight step is what keeps it present at that
    distance without promoting it into a heading. Measured: 400 thresholds
    cleanly too, so this is legibility at distance rather than a fix.
  * Inter at **wght 400** only. Nothing in the renderer sets Inter bold any
    more — every emphatic role went to Fraunces or to tracked mono when the
    display picked up the editorial system — so a bold static would be 150KB of
    dead weight in the repo.

All three are SIL Open Font License 1.1; `fonts/OFL.txt` travels with them, as
the licence requires.
"""
from __future__ import annotations

import os
import tempfile

from fontTools.merge import Merger
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "frontend", "public", "fonts"))
DEST = os.path.normpath(os.path.join(HERE, "..", "tasksd", "display", "fonts"))

# (output name, subset prefix, axis pins). See the module docstring for why each
# number is what it is.
FACES = (
    ("Inter-Regular.ttf", "inter", {"wght": 400}),
    ("Fraunces-Medium.ttf", "fraunces", {"wght": 500, "opsz": 9}),
    ("JetBrainsMono-Medium.ttf", "jetbrains-mono", {"wght": 500}),
)


def build(name: str, prefix: str, axes: dict[str, float], *, out_dir: str = DEST) -> str:
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for subset in ("latin", "latin-ext"):
            font = TTFont(os.path.join(SRC, f"{prefix}-{subset}.woff2"))
            # `updateFontNames=False`: the name table keeps saying "Fraunces"
            # rather than "Fraunces Medium 9pt", which is what the renderer's
            # own filenames are for. A renamed family buys nothing here and
            # makes the file harder to recognise.
            instancer.instantiateVariableFont(font, axes, inplace=True, updateFontNames=False)
            path = os.path.join(tmp, f"{prefix}-{subset}.ttf")
            font.save(path)
            parts.append(path)
        out = os.path.join(out_dir, name)
        Merger().merge(parts).save(out)
    return out


def main() -> None:
    for name, prefix, axes in FACES:
        path = build(name, prefix, axes)
        pinned = ", ".join(f"{k}={v:g}" for k, v in axes.items())
        print(f"{name:<26} {pinned:<20} {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main()
