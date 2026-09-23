"""Rebuild the TTFs the display renderer draws with, from the app's own woff2.

    python -m dev.build_display_fonts

The display is one design with two rasterizers — a browser and Pillow — and this
is what keeps the second one in the first one's typefaces. It takes the THREE
SHIPPED FAMILIES from `frontend/public/fonts/` and pins each to the weight (and,
for Newsreader, the optical size) the design actually uses, writing static TTFs
into `smylted/display/fonts/`.

Nothing imports this at runtime. It is here rather than in a README snippet
because the choices below are empirical — they were measured against a
thresholded 1-bit render — and a build step whose reasoning lives in prose gets
re-run with different numbers the first time someone tries.

**Why TTF at all.** No Python rasterizer reads woff2; FreeType, which is what
Pillow is, takes SFNT. The conversion is mechanical: decompress, pin the
variable axes, merge the two unicode subsets.

**Why the subsets are MERGED rather than one being picked.** They carve up the
alphabet between them — `newsreader-latin` holds ASCII and Latin-1 (so `ü`,
`é`, `ç`), `newsreader-latin-ext` holds the rest of extended Latin (so `ż`,
`ł`). What a display draws is the owner's own text, and a list called
*Ćwiczenia* should not render as a row of boxes.

**Why these weights.**

  * Newsreader at **wght 500** is the weight `.cal-title`, `.content-title` and
    `.day-col-head .dnum` use in app.css. The display is not inventing a
    headline weight, it is borrowing the one the product already has.
  * Newsreader at **opsz 12** — NOT the font's default, and this is the
    empirical one. Newsreader's fvar default is opsz 18, its text cut, and that
    is what `font-optical-sizing: none` alone would pin. It is too fine for one
    bit: at wght 500 its thinnest stroke is 42/1000 em and its stems 94, where
    the Fraunces opsz 9 it replaces had 49 and 124, and that difference is
    exactly what the threshold eats. On rendered frames, "August 2026" at 30px
    loses the hairlines of its 2s and the top of its 6, and a small day
    number's 1 loses its flag and its foot — on a 4.2" panel "10" read "I0".
    Counted over 63 glyphs at four pen phases, against each glyph's own shape
    at 200px, opsz 18 comes apart more often than Fraunces did at 18, 22, 26
    and 30px (21% of glyphs against 10% at 18px): the band every headline on
    the panel lives in.
    Down the axis the hairlines thicken — 57/1000 em at opsz 14, 65 at 12, 76
    at 9 — and 12 is where to stop. There, no size from 9px to 30px comes apart
    more often than Fraunces did and most far less (9.5% at the 15px day
    number, against 33%), the only fault above that is a 36px g closing off a
    pinhole, and it still sets at the width the layout was tuned against:
    "August 2026" at 30px is 184px, where Fraunces was 183. Below 12 the
    caption cut widens and flattens (204px at opsz 6) and stops reading as
    Newsreader. display.css pins the browser to the same instance with
    `font-variation-settings`, so both rasterizers draw the same letterforms
    rather than merely the same family — see `OPSZ` for how that is held.
  * JetBrains Mono at **wght 500**, one step above the 400 app.css leaves its
    micro-labels at. A label in the app is read at arm's length and one on a
    wall at three metres, and one weight step is what keeps it present at that
    distance without promoting it into a heading. Measured: 400 thresholds
    cleanly too, so this is legibility at distance rather than a fix.
  * Hanken Grotesk at **wght 400** only. Nothing in the renderer sets the sans
    bold — every emphatic role went to the serif or to tracked mono when the
    display picked up the editorial system — so a bold static would be dead
    weight in the repo. Measured the same way as the serif, 400 thresholds at
    parity with the Inter 400 it replaces — at the 9–11px chip sizes the two
    lose the same glyphs to within one — and it sets about 5% narrower, which a
    month cell spends on letters.

All three are SIL Open Font License 1.1; `fonts/OFL.txt` travels with them, as
the licence requires.
"""
from __future__ import annotations

import os
import re
import tempfile

# fontTools is imported where it is used, not here. The app does not install it
# (requirements.txt has no reason to), and tests/test_displays.py imports this
# module to hold `OPSZ` against the stylesheet — which it must be able to do on
# a machine with only the app's dependencies.

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "frontend", "public", "fonts"))
DEST = os.path.normpath(os.path.join(HERE, "..", "smylted", "display", "fonts"))
DISPLAY_CSS = os.path.normpath(
    os.path.join(HERE, "..", "..", "frontend", "src", "styles", "display.css"))

# The optical size the serif is pinned at, for the eink panel. See the module
# docstring for why it is 12 and not the font's own default.
#
# The browser half of the pin lives in display.css, as
# `.display--eink { font-variation-settings: "opsz" 12 }`, and the two MUST name
# the same number or the bitmap and the page quietly draw different letterforms
# — nothing would error, the panel would just stop matching the app. So `main`
# reads the stylesheet's number and refuses to build if it differs, and
# tests/test_displays.py asserts the same thing on every CI run. What neither
# can see is a TTF that was never rebuilt after this number moved — that takes
# fontTools, which CI does not install — so change it here, in display.css and
# in the committed fonts together.
OPSZ = 12

# (output name, subset prefix, axis pins). See the module docstring for why each
# number is what it is.
FACES = (
    ("HankenGrotesk-Regular.ttf", "hanken-grotesk", {"wght": 400}),
    ("Newsreader-Medium.ttf", "newsreader", {"wght": 500, "opsz": OPSZ}),
    ("JetBrainsMono-Medium.ttf", "jetbrains-mono", {"wght": 500}),
)


def opsz_axis(prefix: str = "newsreader") -> tuple[float, float, float]:
    """The source font's optical-size axis, as (min, default, max), from fvar.

    Read from the woff2 rather than written down, because the default is what a
    browser draws under `font-optical-sizing: none` — the instance the pin above
    departs from — and a re-downloaded Newsreader is free to move it.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(os.path.join(SRC, f"{prefix}-latin.woff2"))
    for axis in font["fvar"].axes:
        if axis.axisTag == "opsz":
            return axis.minValue, axis.defaultValue, axis.maxValue
    raise ValueError(f"{prefix} has no optical-size axis")


def css_opsz(path: str = DISPLAY_CSS) -> float | None:
    """The optical size display.css pins the eink page's serif to, or None.

    The bare `.display--eink` rule's `font-variation-settings: "opsz" N`, and
    only that: the colour palette deliberately leaves optical sizing to the
    browser, so an `opsz` in any other rule — or in a comment — is not this pin.
    If more than one such rule sets it, the last wins, as it does in the cascade.
    """
    with open(path, encoding="utf-8") as fh:
        css = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)
    found = None
    for rule in re.finditer(r"(?<![\w-])\.display--eink\s*\{([^}]*)\}", css):
        pin = re.search(r"font-variation-settings\s*:\s*[\"']opsz[\"']\s+([\d.]+)",
                        rule.group(1))
        if pin:
            found = float(pin.group(1))
    return found


def build(name: str, prefix: str, axes: dict[str, float], *, out_dir: str = DEST) -> str:
    from fontTools.merge import Merger
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for subset in ("latin", "latin-ext"):
            font = TTFont(os.path.join(SRC, f"{prefix}-{subset}.woff2"))
            # `updateFontNames=False`: the name table keeps the source's own
            # records rather than being rewritten from STAT. For Newsreader
            # those say "Newsreader 16pt Regular", which is Google's name for
            # the variable font's default and not this instance — but STAT
            # would call opsz 12 "6pt", which is no truer, and nothing reads
            # the names anyway. The filename is what says what the file is.
            instancer.instantiateVariableFont(font, axes, inplace=True, updateFontNames=False)
            path = os.path.join(tmp, f"{prefix}-{subset}.ttf")
            font.save(path)
            parts.append(path)
        out = os.path.join(out_dir, name)
        Merger().merge(parts).save(out)
    return out


def main() -> None:
    lo, default, hi = opsz_axis()
    # Checked, not trusted: an out-of-range pin is clamped by the instancer
    # without a word, and a stylesheet naming a different number is the drift
    # this whole script exists to prevent.
    assert lo <= OPSZ <= hi, f"opsz {OPSZ} is outside Newsreader's axis ({lo:g}–{hi:g})"
    pinned = css_opsz()
    css_says = "no optical size" if pinned is None else f"opsz {pinned:g}"
    assert pinned == OPSZ, (
        f"display.css pins the eink serif to {css_says}, this builds opsz {OPSZ:g}: "
        "the page and the bitmap would draw different letterforms")
    print(f"Newsreader opsz axis {lo:g}–{hi:g}, default {default:g}; "
          f"pinned at {OPSZ:g} (display.css agrees)")
    for name, prefix, axes in FACES:
        path = build(name, prefix, axes)
        pins = ", ".join(f"{k}={v:g}" for k, v in axes.items())
        print(f"{name:<26} {pins:<20} {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main()
