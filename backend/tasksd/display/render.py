"""A frame, rasterized. For a panel that has no browser.

The device this exists for is not a computer with a small screen — it is an
ESP32 with a Waveshare panel soldered to it, a few hundred kilobytes of RAM, and
no ability to run a browser, lay out CSS or decompress much of anything. It can
fetch bytes over HTTP and push them at a display controller. So the layout
happens here and it is handed pixels.

Two rules run through all of it, and they are both about the panel rather than
about taste:

  * **On eink there is no grey.** Every pixel is ink or paper, and an
    intermediate value becomes a dither pattern — which on a panel that
    part-refreshes shimmers between updates and, at the type sizes a wall
    display uses, turns secondary text into grey mush. So nothing in the eink
    palette is a tint. Hierarchy is carried by SIZE, WEIGHT and RULES, which
    survive being thresholded, and never by opacity, which does not.
  * **A repaint is expensive.** A full eink refresh flashes the panel black for
    the better part of a second. That is why the routes hash the image and
    answer 304 — and why the layout is stable rather than fitted: a grid that
    changed height when a month needed five weeks instead of six would repaint
    everything on the 1st for no new information.

Text is anti-aliased into an 8-bit buffer and thresholded once at the end rather
than being drawn without anti-aliasing. Measured on the type sizes here, that is
what keeps a 14px label legible: FreeType's monochrome rendering drops the stems
of `i` and `l` at small sizes, and thresholding a smoothed glyph keeps them.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont


# What the raw format IS, stated on the wire so a firmware can assert its
# panel's convention rather than assume it. `mono-hlsb` is MicroPython's own
# name for this packing, which is the vocabulary the client already speaks.
RAW_FORMAT = "mono-hlsb"
RAW_FORMAT_INVERTED = "mono-hlsb-inverted"
_RAW_MEDIA = "application/octet-stream"

# A 256-byte lookup that complements a byte. Every idiomatic Pillow way to
# invert a mode-"1" image is SILENTLY WRONG — measured on an 8×2 image with two
# black pixels (`3fff`): `ImageChops.invert`, `Image.eval(v: 255-v)` and
# `img.point(lambda v: 255-v)` all return `ffff`, an entirely white image, and
# `ImageOps.invert` refuses mode "1" outright. Mode "1" is stored one byte per
# pixel as 0/255, and after those calls the formerly-white pixels read back as
# 254 — nonzero, so they repack as 1. Inverting the PACKED BYTES is the only
# thing that inverts the picture, and it is also 22× faster over a 48KB
# framebuffer (0.06ms against 1.3ms for a generator expression).
_INVERT = bytes(255 - i for i in range(256))

# The most pixels one render may cover, and the only bound on the AREA of an
# image the public routes will draw.
#
# Each dimension was already capped at 4096, which sounds bounded and is not:
# 4096×4096 is 16.7 million pixels, and on a colour display `.bmp` is three
# bytes each. Measured before this bound existed — one unauthenticated GET,
# roughly 200 bytes of request:
#
#     GET /api/public/display/<token>.bmp?w=4096&h=4096  ->  50,331,702 bytes
#
# ~100 MB of transient RSS per request with it, on a route that by design has
# no session. 4 million covers every browserless panel that exists with room to
# spare — the largest e-ink Waveshare sell is 13.3" at 1600×1200 (1.9M), and a
# 2560×1440 colour panel is 3.7M — while cutting the worst case to a quarter.
# Anything larger than this is a screen with a browser, which fetches the page
# rather than the image.
MAX_PIXELS = 4_000_000

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

# The app's three type slots, by the names tokens.css gives them. A display is
# drawn in the product's own typefaces at the product's own weights, so a panel
# on a wall reads as Smylte rather than as a generic dashboard that happens to
# hold the same data — see `dev/build_display_fonts.py` for how each file is
# pinned and why.
#
# The ROLE is what is named at every call site below, never the file. "This is a
# micro-label" survives a change of typeface; "this is JetBrainsMono-Medium"
# does not.
_FACES = {
    "serif": os.path.join(_FONT_DIR, "Fraunces-Medium.ttf"),
    "sans": os.path.join(_FONT_DIR, "Inter-Regular.ttf"),
    "mono": os.path.join(_FONT_DIR, "JetBrainsMono-Medium.ttf"),
}

# How far a micro-label is tracked, as a fraction of its size. app.css spends
# 0.06em–0.12em on these depending on how small the label is; the two values
# here are the ends of that range, and the uppercase mono they go with is the
# loudest editorial marker the product has.
_TRACK_TIGHT = 0.06
_TRACK_WIDE = 0.12

# The light theme's tokens, mirrored from frontend/src/styles/tokens.css (the
# OKLCH accents converted once to sRGB). A display is always "light": it is
# paper on a wall, and an eink panel is physically white. There is no dark
# variant here for the same reason there is no dark variant of a poster.
_INK = (20, 19, 26)             # --fg
_PAPER = (251, 250, 247)        # --bg
_MUTED = (110, 108, 120)        # --fg-muted, flattened onto --bg
_RULE = (206, 204, 200)         # --rule, flattened onto --bg
_ACCENT = (216, 75, 0)          # --accent: oklch(0.60 0.19 42)

# Eink is the same two values everywhere. Written out rather than derived by
# thresholding the palette above, because "muted" and "rule" must be BLACK here,
# not a grey that thresholds to whichever side it happens to land on.
_EINK = {"ink": (0, 0, 0), "paper": (255, 255, 255),
         "muted": (0, 0, 0), "rule": (0, 0, 0), "accent": (0, 0, 0)}
_COLOR = {"ink": _INK, "paper": _PAPER, "muted": _MUTED,
          "rule": _RULE, "accent": _ACCENT}


@lru_cache(maxsize=64)
def _font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """One FreeType face per (role, size). Cached: a month grid asks for the
    same handful of sizes a few hundred times, and each `truetype()` call
    re-reads and re-parses the whole file from disk."""
    return ImageFont.truetype(_FACES[role], size)


def _oneline(s: str) -> str:
    """The first line of `s`. A guard, not a feature.

    Pillow REFUSES to measure a string containing a newline — "can't measure
    length of multiline text" — and `_label` measures ONE CHARACTER AT A TIME,
    so there the string that blows up is the newline by itself. A newline in an
    event title is ordinary: RFC 5545 escapes it and every parser unescapes it
    back. Unguarded, one such title raised ValueError out of `render_frame`, and
    every `.png`, `.bmp` and `.bin` fetch for that display answered 500 — for as
    long as the event existed, while the JSON frame went on working.

    `frame.plain` is the real fix and normalises this at the one edge all three
    surfaces are built from. This is the half that does not depend on every
    future caller of the renderer having gone through it: a panel drawing the
    first line of a two-line title shows slightly less than it might; a 500
    shows nothing at all.
    """
    return s.splitlines()[0] if ("\n" in s or "\r" in s) else s


def _text_width(draw: ImageDraw.ImageDraw, s: str, font) -> int:
    """How wide `s` is in `font`. Newline-guarded — see `_oneline`."""
    return int(draw.textlength(_oneline(s), font=font))


def _label_width(
    draw: ImageDraw.ImageDraw, text: str, size: int, *, track: float = _TRACK_WIDE,
) -> float:
    """What `_label` would occupy. Layout has to be decided before anything is
    drawn — see the cell loop, which must know whether a title will fit before
    it commits to a marker."""
    text = _oneline(text).upper()
    if not text:
        return 0.0
    font = _font("mono", size)
    return (sum(draw.textlength(c, font=font) for c in text)
            + size * track * (len(text) - 1))


def _label(
    draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int,
    fill, *, track: float = _TRACK_WIDE, right: float | None = None,
) -> float:
    """A micro-label: uppercase mono, tracked. Returns the width it drew.

    Tracked BY HAND, one glyph at a time, because Pillow has no letter-spacing
    and the tracking is not decoration here — uppercase mono set solid is a
    different thing from the app's label, which is airy on purpose. This is the
    one piece of typography the browser gets for free (`letter-spacing`) and the
    rasterizer has to build.

    `right` right-aligns to that x instead of drawing from `xy[0]`, which needs
    the width up front — hence measuring and drawing in the same function rather
    than a caller doing both.

    The trailing gap is dropped from the measurement. CSS puts letter-spacing
    AFTER every character including the last, so a right-aligned tracked label
    measured naively sits one gap short of its edge; browsers have the same
    quirk and it is visible at 0.12em on a wall.
    """
    width = _label_width(draw, text, size, track=track)
    text = _oneline(text).upper()
    if not text:
        return 0.0
    font = _font("mono", size)
    gap = size * track
    x = (right - width) if right is not None else xy[0]
    for char in text:
        draw.text((x, xy[1]), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + gap
    return width


def _fit(draw: ImageDraw.ImageDraw, s: str, font, width: int) -> str:
    """`s`, shortened with an ellipsis until it fits `width`.

    Binary search rather than dropping one character at a time, and this is not
    a micro-optimisation. The obvious loop re-measures the WHOLE string on every
    step, so it is quadratic in the title's length, and the title comes from
    whatever CalDAV client wrote the event. Measured: 1,000 characters took
    0.23s, 2,000 took 0.80s, 4,000 took 2.99s — and `_display_events` copies a
    grid-spanning event's summary into all 42 cells, on a route with no session.
    `frame.plain` now caps titles at `MAX_TEXT_CHARS`, which is the real fix;
    this is the half that does not depend on every caller remembering.

    The search is over prefix length: `lo` always fits, `hi` never does, so it
    settles on the longest prefix that does — the same answer the character-wise
    loop gave, in a handful of measurements rather than thousands. What still
    matters most is that it returns "" rather than a lone ellipsis when there is
    no room at all — a column of "…" tells the reader nothing except that the
    layout is wrong.
    """
    if not s:
        return ""
    if _text_width(draw, s, font) <= width:
        return s
    ellipsis = "…"
    if _text_width(draw, ellipsis, font) > width:
        return ""
    # `s` itself does not fit (checked above), so neither does `s + ellipsis`:
    # `hi` starts on a known-bad length and `lo` on a known-good one.
    lo, hi = 0, len(s)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _text_width(draw, s[:mid] + ellipsis, font) <= width:
            lo = mid
        else:
            hi = mid
    cut = s[:lo]
    return (cut.rstrip() + ellipsis) if cut.strip() else ""


def _marker(
    draw: ImageDraw.ImageDraw, x: int, y: int, size: int, *,
    treatment: str, color, eink: bool, colors,
) -> None:
    """The mark that says which calendar an item belongs to.

    On a colour panel this is a filled square in the calendar's own colour, and
    the treatment is ignored — colour is the better signal and it is available.
    On eink the treatments are the signal, and there are four because four are
    what stay apart across a room: filled, hollow, a bar, and a dotted outline.
    A fifth calendar does not get a fifth pattern; it gets a letter beside its
    mark (see `frame.assign_sources`), which is unambiguous at any count.
    """
    if not eink:
        draw.rectangle([x, y, x + size, y + size], fill=color)
        return
    # `colors` is already flattened to the 8-bit buffer's scalars by
    # `render_frame`; the tuples in `_EINK` would be rejected by mode "L".
    ink = colors["ink"]
    if treatment == "solid":
        draw.rectangle([x, y, x + size, y + size], fill=ink)
    elif treatment == "outline":
        draw.rectangle([x, y, x + size, y + size], outline=ink, width=max(1, size // 6))
    elif treatment == "bar":
        draw.rectangle([x, y, x + max(1, size // 3), y + size], fill=ink)
    else:  # dotted — the outline, drawn every other pixel
        step = 2
        for px in range(x, x + size + 1, step):
            draw.point((px, y), fill=ink)
            draw.point((px, y + size), fill=ink)
        for py in range(y, y + size + 1, step):
            draw.point((x, py), fill=ink)
            draw.point((x + size, py), fill=ink)


def _check(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, colors) -> None:
    """A tick, drawn as two strokes rather than set as the character ✓.

    Inter has no ✓ — it is not in the Latin subsets this app ships — so setting
    it would render a box. Drawing it also puts its weight under our control:
    a hairline tick disappears on a panel read from three metres away.
    """
    weight = max(2, size // 5)
    draw.line([(x + size * 0.10, y + size * 0.55),
               (x + size * 0.40, y + size * 0.85),
               (x + size * 0.92, y + size * 0.15)],
              fill=colors["ink"], width=weight, joint="curve")


def _habit_glyph(
    draw: ImageDraw.ImageDraw, x: int, y: int, size: int, colors, *, done: bool
) -> None:
    """The habit mark: a ring, filled once it has been done.

    A ring rather than the app's `↻` because that glyph is not in the Latin
    subsets this app ships, and an arrow at 10px on a thresholded panel is a
    smudge where a ring stays a ring.

    Filled rather than ticked, and that is not a stylistic choice. A tick drawn
    INSIDE a circle is a diagonal through a ring, which is the international
    sign for *not allowed* — the first render of this read "Stretch: forbidden".
    A filled disc has no such second meaning, and it keeps the two marks on this
    screen distinct at a glance: a solid dot is a habit kept, a ticked box is a
    row finished.
    """
    weight = max(2, size // 6)
    if done:
        draw.ellipse([x, y, x + size, y + size], fill=colors["ink"])
    else:
        draw.ellipse([x, y, x + size, y + size], outline=colors["ink"], width=weight)


def _scale(height: int) -> float:
    """Type scale from panel height. 480px — the common 7.5" panel — is 1.0.

    Clamped at both ends. Below 0.75 the type stops being legible before the
    layout stops fitting, and past 2.6 a large panel would be drawn in
    headlines; a bigger screen should show MORE, not the same thing louder.
    """
    return max(0.75, min(2.6, height / 480))


def _item_scale(scale: float) -> float:
    """The scale for the SMALL tier — a month cell's events and their clocks.

    Deliberately gentler than `_scale`, and it is the same sentence that
    function's own docstring ends on: a bigger screen should show MORE, not the
    same thing louder. A headline that grows with the panel is right, because
    there is one of it; a cell's event text that grows with the panel is not,
    because the column it sits in grows at exactly the same rate and so the
    number of characters that fit never improves. Measured on a 1200×825 panel
    with linear scaling: "1:1 with Sam" still truncated to "1:1 wit…" on a cell
    with half its height empty.

    Growing the small tier at a bit over half the rate spends the extra pixels
    on more words and more rows instead. It is a no-op at 480px, where the
    common 7.5" panel sits and where nothing was wrong.
    """
    return 1.0 + (scale - 1.0) * 0.55


def _grid_scale(width: int, height: int) -> float:
    """The scale a MONTH GRID's small tier is drawn at.

    `_scale` reads the panel's height, which is right for a headline and wrong
    for a seven-column grid: what bounds a cell's text is the COLUMN, and a
    column is a seventh of the width. A portrait panel has a large height and a
    narrow column, so height alone inflated the type past what the column could
    hold — measured on a 600×800 Kindle, every cell rendered its clock and then
    had no room left for the event, so the month came out as a grid of bare
    times with nothing to say what any of them were.

    Taking the smaller of the two ratios makes the binding dimension the one
    that decides. 800×480 — the common 7.5" panel, and the reference both
    numbers are taken from — is 1.0 either way, so nothing there moves.
    """
    return max(0.75, min(2.6, min(height / 480, width / 800)))


# A month grid stops being a month grid somewhere, and it is worth saying so
# rather than drawing seven columns of overlapping ink. These are the smallest
# cell a day can be drawn in and still be read: measured against the panels
# people actually mount, a 4.2" (400×300) clears both and reads fine, while a
# 2.9" (296×128) gives a 39px column — four characters — and is hopeless.
_MIN_COL_W = 46
_MIN_ROW_H = 26


def month_grid_fits(width: int, height: int) -> bool:
    """Is a month grid worth drawing on a panel this size?

    THE predicate, exported so there is one of it. `_render_calendar` asks it
    before drawing and answers a panel that fails with a sentence instead; the
    service asks it so Settings can say so at the moment the owner types the
    size in, which is the useful moment — finding out on the wall means walking
    to the other room. A copy of this arithmetic in TypeScript would be a
    second opinion about the same question, and the two would drift.

    The geometry is `_render_calendar`'s, kept deliberately in step with it: the
    same padding, the same header, the same six rows.
    """
    scale = _scale(height)
    pad = int(16 * scale)
    grid_top = pad + int(38 * scale) + int(18 * scale)
    col_w = (width - 2 * pad) / 7
    row_h = (height - grid_top - pad) / 6
    return col_w >= _MIN_COL_W and row_h >= _MIN_ROW_H


def _plan_cell(
    draw: ImageDraw.ImageDraw, items: list[dict], treatments: dict, *,
    room: int, avail: float, item_font, time_font, initial_size: int, gap: int,
) -> tuple[list[tuple[dict, str, str]], int]:
    """What one day's cell can actually show. Returns the rows and how many were
    dropped.

    Every decision about a row is made HERE, before a single pixel of it is
    drawn, and that ordering is the whole point. Drawing the marker and the
    clock first and then discovering the title had no room left an ORPHAN: a
    bullet and a bare "10:00" with nothing saying what it was. On a narrow
    column that was every row on the panel.

    A clock also has to earn its place. It is fixed-width mono and it goes
    first, so on a narrow column it eats the title whole; when what would be
    left cannot hold a readable title, the time is dropped and the row spends
    its width on words instead. "Dentist" with no time beats "14:30 …" with no
    event.

    Split out of the drawing loop so both of those rules can be tested on their
    own. Through a rendered panel they cannot be: `month_grid_fits` refuses the
    sizes narrow enough to make the orphan case reachable, which is the belt to
    this brace and makes the brace invisible from outside.
    """
    # Six characters of title, which is about where a truncated event stops
    # being worth the row it costs.
    min_title = draw.textlength("nnnnnn", font=item_font)
    planned: list[tuple[dict, str, str]] = []
    for item in items[:room]:
        src = treatments.get(item["source"], {})
        room_w = avail
        if src.get("initial"):
            room_w -= _label_width(draw, src["initial"], initial_size, track=0) + gap
        stamp = item["time"]
        stamp_w = (_text_width(draw, stamp, time_font) + gap) if stamp else 0
        if stamp and room_w - stamp_w < min_title:
            stamp, stamp_w = "", 0
        text = _fit(draw, item["text"], item_font, int(room_w - stamp_w))
        if not text:
            # Not even an ellipsis fits. A marker on its own says nothing; the
            # row is worth more inside the "+N".
            continue
        planned.append((src, stamp, text))
    return planned, len(items) - len(planned)


def _render_calendar(
    img: Image.Image, frame: dict[str, Any], *, eink: bool, colors,
) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    scale = _scale(height)
    pad = int(16 * scale)
    cal = frame["calendar"]
    treatments = {s["id"]: s for s in frame["sources"]}

    # The app's own type slots, by role. A serif headline, a tracked uppercase
    # mono micro-label, sans for the things that are read rather than scanned —
    # the same three the product uses everywhere else.
    title_font = _font("serif", int(30 * scale))
    day_font = _font("serif", int(15 * scale))
    # A day outside this month, one size step down. It is NOT merely a quieter
    # colour: `--fg-muted` on a one-bit panel IS black, so a colour step alone
    # made July's last week indistinguishable from August's first — the whole
    # point of drawing those days at all. Size is one of the three things that
    # survive thresholding (the others being weight and rule), and it keeps the
    # distinction inside one type system rather than reaching for a second face
    # to say "not this month".
    outside_font = _font("serif", int(12 * scale))
    # The small tier is bound by the column, not by the panel's height.
    small = _item_scale(_grid_scale(width, height))
    item_font = _font("sans", int(12 * small))
    time_font = _font("mono", int(10 * small))
    label_size = int(11 * scale)

    # Header: the month, and the display's own name at the right. The name is
    # there because a household with two panels needs to know which one it is
    # looking at when one of them is showing last week. It is a micro-label
    # rather than a second headline, exactly as `.topbar-meta` is in the app.
    draw.text((pad, pad - int(4 * scale)), cal["title"], font=title_font, fill=colors["ink"])
    _label(draw, (0, pad + int(12 * scale)),
           _fit(draw, frame["display"]["name"], _font("mono", label_size), width // 3),
           label_size, colors["muted"], right=width - pad)
    top = pad + int(38 * scale)
    draw.line([(pad, top), (width - pad, top)], fill=colors["rule"], width=1)

    # Weekday row, then a fixed six-row grid. Fixed, so the layout does not move
    # between a five-week month and a six-week one — see the module docstring.
    head_h = int(18 * scale)
    grid_top = top + head_h
    grid_w = width - 2 * pad
    col_w = grid_w / 7
    grid_h = height - grid_top - pad
    row_h = grid_h / 6

    if not month_grid_fits(width, height):
        # A 2.9" panel is 296×128: a 39px column, four characters wide. Seven of
        # those is not a small month grid, it is a smear — and a screen that
        # renders a smear looks broken rather than misconfigured, so the owner
        # has no way to know what to do about it. This says it instead, in the
        # one place they will see it, and names the mode that DOES fit a panel
        # this size.
        message = cal["too_small_text"]
        hint = cal["too_small_hint"]
        note = _font("sans", max(10, int(13 * scale)))
        hint_font = _font("sans", max(9, int(11 * scale)))
        draw.text((pad, grid_top + int(6 * scale)),
                  _fit(draw, message, note, width - 2 * pad),
                  font=note, fill=colors["ink"])
        draw.text((pad, grid_top + int(6 * scale) + int(16 * scale)),
                  _fit(draw, hint, hint_font, width - 2 * pad),
                  font=hint_font, fill=colors["muted"])
        return

    for i, label in enumerate(cal["weekday_names"]):
        _label(draw, (pad + col_w * i + int(4 * scale), top + int(3 * scale)),
               label, label_size, colors["muted"])

    # Column separators. A month grid without them lets one day's text run into
    # the next day's cell, and on a wall the reader has no cursor to disambiguate
    # with. On eink they are DOTTED rather than solid: `rule` is black there like
    # everything else, and six full-height black lines would out-weigh the
    # content they are separating.
    for c in range(1, 7):
        x = pad + col_w * c
        if eink:
            for py in range(int(grid_top), int(height - pad), 3):
                draw.point((int(x), py), fill=colors["rule"])
        else:
            draw.line([(x, grid_top), (x, height - pad)], fill=colors["rule"], width=1)

    item_h = int(15 * small)
    marker_size = int(7 * small)
    # The space between the clock and the title, and between a calendar's
    # initial and what follows it. Proportional to the type rather than a flat
    # 4px, which at the small end came out as ONE SPACE WIDTH — measured on a
    # 648×480 panel, "10:00" and "1:1 with Sam" rendered as "10:001:1 with…"
    # and read as a single word. A mono field abutting a sans one needs more
    # air than two words of the same face do, and a title that starts with a
    # digit needs it badly. app.css spends ~0.7em on the same seam
    # (`.task-meta`'s flex gap at its font size).
    field_gap = max(4, int(item_font.size * 0.6))
    for r, week in enumerate(cal["weeks"]):
        y = grid_top + row_h * r
        draw.line([(pad, y), (width - pad, y)], fill=colors["rule"], width=1)
        for c, cell in enumerate(week):
            x = pad + col_w * c
            cx, cy = int(x + 4 * scale), int(y + 3 * scale)
            number = day_font
            if cell["today"]:
                # Today is a filled block with the number knocked out of it.
                # It reads at a glance and, crucially, survives thresholding —
                # a tint behind the number would not.
                box = int(19 * scale)
                draw.rectangle([cx - int(2 * scale), cy - int(2 * scale),
                                cx + box, cy + box], fill=colors["ink"])
                draw.text((cx + int(3 * scale), cy), cell["label"],
                          font=number, fill=colors["paper"])
            else:
                # A day outside this month is quieter but never grey on eink —
                # it is the regular weight where an in-month day is bold, which
                # is a difference that survives being one bit deep.
                # A day outside the month is the SAME serif at the same
                # weight, only quieter — there is one type system on this
                # screen, and dropping to another face to say "not this month"
                # would be saying it with the wrong instrument.
                inside = cell["in_month"]
                draw.text((cx + int(3 * scale), cy + (0 if inside else int(2 * scale))),
                          cell["label"],
                          font=day_font if inside else outside_font,
                          fill=colors["ink"] if inside else colors["muted"])

            # However many item lines are left under the number. The frame
            # carries up to twenty; this is what fits, and anything past it is
            # counted rather than dropped silently.
            item_top = cy + int(21 * scale)
            room = max(0, int((row_h - (item_top - y) - 2 * scale) // item_h))
            items = cell["items"]

            planned, dropped = _plan_cell(
                draw, items, treatments, room=room,
                avail=col_w - (cx - x) - marker_size - int(4 * small) - 4 * small,
                item_font=item_font, time_font=time_font,
                initial_size=int(11 * small), gap=field_gap)
            spare = dropped + cell["hidden"]
            if spare > 0:
                # The counter goes on the DAY NUMBER's line, at the right of the
                # cell, rather than taking an item line of its own. A month grid
                # on an 800×480 panel has room for about two events a day, and
                # spending one of them to say "+4" costs the reader more than
                # the count is worth. It cannot push the grid taller either,
                # which the fixed six-row layout depends on.
                # Mono, like every other count in the app (`.day-col-head
                # .count`, `.side-item .count`), and untracked: this is a
                # number to be read, not a label to be scanned.
                _label(draw, (0, cy + int(4 * scale)), f"+{spare}",
                       int(10 * scale), colors["muted"], track=0,
                       right=x + col_w - 4 * scale)
            for i, (src, stamp, text) in enumerate(planned):
                iy = item_top + i * item_h
                _marker(draw, cx, iy + int(3 * small), marker_size,
                        treatment=src.get("treatment", "solid"),
                        color=src.get("color") or _ACCENT, eink=eink, colors=colors)
                tx = cx + marker_size + int(4 * small)
                if src.get("initial"):
                    tx += _label(draw, (tx, iy + int(1 * small)), src["initial"],
                                 int(11 * small), colors["ink"], track=0) + field_gap
                # The clock leads the title, in mono — the app sets every time
                # it draws in mono (`.task-meta .due`), and here it also buys
                # tabular figures, so the times line up down the column instead
                # of ragging. A wall calendar is read for WHEN before WHAT, and
                # a fixed left edge is what makes the column scannable.
                if stamp:
                    draw.text((tx, iy), stamp, font=time_font, fill=colors["ink"])
                    tx += _text_width(draw, stamp, time_font) + field_gap
                draw.text((tx, iy), text, font=item_font, fill=colors["ink"])


def _render_habits(
    img: Image.Image, frame: dict[str, Any], *, eink: bool, colors,
) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    scale = _scale(height)
    pad = int(20 * scale)
    block = frame["habits"]

    title_font = _font("serif", int(28 * scale))
    row_font = _font("sans", int(17 * scale))
    note_font = _font("sans", int(12 * scale))
    label_size = int(11 * scale)

    draw.text((pad, pad), frame["display"]["name"], font=title_font, fill=colors["ink"])
    counts = block["counts"]
    # The score, at the right of the header, in the SAME serif as the name it
    # sits beside — a headline and its figure, not a label. It is the whole
    # reason the counts are computed before the hiding: with `hide_done_habits`
    # on, the list empties as the day goes and this is the only thing left that
    # remembers there was anything on it.
    tally = f"{counts['habits_done']}/{counts['habits_total']}"
    if counts["habits_total"]:
        draw.text((width - pad - _text_width(draw, tally, title_font), pad),
                  tally, font=title_font, fill=colors["ink"])
    y = pad + int(36 * scale)
    draw.line([(pad, y), (width - pad, y)], fill=colors["rule"], width=1)
    y += int(10 * scale)

    if not block["planned"]:
        # A preview is labelled as one. Nobody has opened today, so these rows
        # do not exist yet — the app's own rule is that only the owner opens a
        # day, and a screen in a hallway that drew this as a plan would be
        # claiming a commitment that was never made.
        _label(draw, (pad, y), block["preview_text"], label_size, colors["ink"],
               track=_TRACK_TIGHT)
        y += int(16 * scale)
        draw.text((pad, y), block["preview_hint"], font=note_font, fill=colors["muted"])
        y += int(20 * scale)

    row_h = int(28 * scale)
    glyph = int(15 * scale)

    def section(
        label: str, rows: list[dict], *, habit: bool, cursor: int, rest: int,
    ) -> tuple[int, int]:
        """Draw one block, and report how many rows never made it onto the panel.

        `rest` is what is queued BEHIND this section — the other block's rows —
        because the counter has to speak for the whole face, not for one block.
        A 2.9" panel fits two rows of seven, and a screen that quietly showed
        two and said nothing is the same lie as a task list that shows the first
        eight of forty. That is the thing this feature refuses to do elsewhere;
        it should not do it here either.
        """
        if not rows:
            return cursor, 0
        label_h = int(18 * scale)
        # No dangling header. A section title with nothing under it is worse
        # than no section at all: it says there is something there and then
        # does not show it.
        if cursor + label_h + row_h > height - pad:
            return cursor, len(rows)
        _label(draw, (pad, cursor), label, label_size, colors["muted"])
        cursor += label_h
        fits = max(0, int((height - pad - cursor) // row_h))
        shown = rows[:fits]
        dropped = len(rows) - len(shown)
        if (dropped or rest) and shown and len(shown) == fits:
            # Spend the last row on the count rather than on one more line the
            # reader cannot know is the last.
            shown = shown[:-1]
            dropped += 1
        for row in shown:
            gy = cursor + int(2 * scale)
            if habit:
                _habit_glyph(draw, pad, gy, glyph, colors, done=row["done"])
            else:
                draw.rectangle([pad, gy, pad + glyph, gy + glyph],
                               outline=colors["ink"], width=max(1, int(2 * scale)))
                if row["done"]:
                    _check(draw, pad, gy, glyph, colors)
            text = _fit(draw, row["text"], row_font,
                        width - 2 * pad - glyph - int(10 * scale))
            tx = pad + glyph + int(10 * scale)
            draw.text((tx, cursor), text, font=row_font, fill=colors["ink"])
            if row["done"]:
                # Struck through rather than greyed: on a panel one bit deep
                # there is no grey to be done in, and a line through the words
                # says the same thing at any depth.
                mid = cursor + int(11 * scale)
                draw.line([(tx, mid), (tx + _text_width(draw, text, row_font), mid)],
                          fill=colors["ink"], width=max(1, int(1.5 * scale)))
            cursor += row_h
        return cursor + int(10 * scale), dropped

    y, missed = section(block["heading"], block["habits"], habit=True,
                        cursor=y, rest=len(block["tasks"]))
    y, missed_tasks = section(block["day_heading"], block["tasks"], habit=False,
                              cursor=y, rest=0)
    missed += missed_tasks
    if missed:
        # Mono and untracked, like every other count the app draws. Placed on
        # the last line the panel has room for, which is why the sections give
        # one up when they overflow.
        _label(draw, (pad, min(y, height - pad - int(14 * scale))),
               f"+{missed}", max(9, int(11 * scale)), colors["muted"], track=0)

    if not block["habits"] and not block["tasks"]:
        # Two different silences, and they are worth telling apart: a day that
        # had things on it and has none left is a finished day, and a day that
        # never had any is an empty one. Only the first deserves a well done.
        done_any = counts["habits_done"] or counts["tasks_done"]
        message = block["all_done_text"] if done_any else block["empty_text"]
        draw.text((pad, y), message, font=row_font, fill=colors["ink"])


def _compose(
    frame: dict[str, Any], *, width: int, height: int, rotation: int,
    force_mono: bool = False,
) -> Image.Image:
    """Everything up to the encode: the drawn, rotated, thresholded image.

    Split out of `render_frame` so a format that is not a container — a packed
    framebuffer — can take the pixels without going through an encoder that
    would only have to be undone on the other side.

    The transposed canvas stays HERE rather than moving to a caller.
    `_render_calendar` and `_render_habits` read their geometry from `img.size`,
    so a caller that built its own canvas and forgot the transpose would get a
    seven-column month laid out landscape and then turned on its side — silently,
    with no error anywhere.

    `force_mono` selects the EINK PALETTE, not merely a threshold at the end,
    and the difference is the whole picture. It exists for `raw`, which is a
    one-bit format by definition: the alternative is a format whose byte width
    depends on how the display happens to be configured, and a microcontroller
    that sized its buffer from the documentation would be handed 24-bit BGR —
    1,152,054 bytes at 800×480 against the 48,000 it allocated.

    But thresholding a COLOUR render was only half of it, and the half that was
    missing was the visible one. `_RULE` is (206, 204, 200) — luma 204, well
    above the threshold — so on a display left on the default `color` palette
    every column separator, every week rule and the header rule converted to
    PAPER and vanished. What came back was floating text with nothing dividing
    one day from the next: precisely the failure the separators exist to
    prevent. `_marker` had the same shape of bug, filling in the calendar's own
    colour and ignoring the treatment, so a light-coloured calendar lost its
    chip mark entirely while `_plan_cell` had already reserved the width for it.
    A one-bit target is an eink target; it takes the eink palette.
    """
    eink = force_mono or frame["display"].get("palette") == "eink"
    colors = _EINK if eink else _COLOR
    # The canvas is the panel turned back the other way, so that layout happens
    # in the orientation a reader sees.
    canvas = (height, width) if rotation in (90, 270) else (width, height)
    # Always 8-bit or RGB here, never mode "1": every glyph is anti-aliased into
    # this buffer and the whole image is thresholded once at the end. See the
    # module docstring for why that beats drawing without anti-aliasing.
    img = Image.new("L" if eink else "RGB", canvas,
                    255 if eink else colors["paper"])
    if eink:
        # In eink mode the palette's tuples are fed to an 8-bit buffer, where
        # Pillow wants a scalar. Flattening here rather than keeping a second
        # palette table means one definition of "ink".
        colors = {k: (0 if v == (0, 0, 0) else 255) for k, v in _EINK.items()}
    if frame["display"]["mode"] == "habits":
        _render_habits(img, frame, eink=eink, colors=colors)
    else:
        _render_calendar(img, frame, eink=eink, colors=colors)
    if rotation:
        # Negative: PIL rotates counter-clockwise and `rotation` is stated
        # clockwise, which is how every panel datasheet states it.
        img = img.rotate(-rotation, expand=True)
    if eink or force_mono:
        # The one threshold, at the end. `dither=NONE` on purpose: Floyd
        # -Steinberg would turn the anti-aliased edge of every glyph into
        # scattered pixels that an eink panel's partial refresh leaves as ghosts.
        img = img.convert("1", dither=Image.Dither.NONE)
    return img


def render_frame(
    frame: dict[str, Any], *, width: int, height: int,
    rotation: int = 0, fmt: str = "png", invert: bool = False,
) -> tuple[bytes, str]:
    """Draw `frame` for a `width`×`height` panel. Returns (bytes, media type).

    `width` and `height` are the panel's FRAMEBUFFER — what the device expects
    to be handed — and `rotation` is how that framebuffer is turned to reach the
    glass. So a portrait panel driven through a landscape controller is laid out
    PORTRAIT and rotated at the end, rather than being laid out landscape and
    turned, which would leave a month grid in seven columns lying on its side.

    Three formats, for three kinds of client:

      * `png` — a browser, or anything with an image library. Note that it is
        saved with `optimize=True`, so libpng picks a filter PER ROW: a decoder
        needs all five unfilters (None/Sub/Up/Average/Paeth) as well as zlib.
        Measured on one 400×300 render: filter types 1, 2 and 3 all appeared.
      * `bmp` — a board whose display library reads a bitmap. Closer to the
        metal, but still a 62-byte container, stored BOTTOM-UP, with rows padded
        to a four-byte boundary.
      * `raw` — the packed one-bit framebuffer itself, and nothing else. See the
        branch below for what it is byte for byte.
    """
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180 or 270")
    if fmt not in ("png", "bmp", "raw"):
        raise ValueError("format must be png, bmp or raw")
    if width * height > MAX_PIXELS:
        # Refused here as well as at the route, so the bound holds for every
        # caller rather than for the one that happens to be in front of it —
        # the same reason `_fit` is not quadratic any more.
        raise ValueError(
            f"{width}×{height} is more than the {MAX_PIXELS:,} pixels a display "
            "render may cover")
    if invert and fmt != "raw":
        # Refused rather than ignored. A caller asking for an inverted PNG and
        # getting a normal one back has no way to tell, and the failure shows up
        # as a panel full of black.
        raise ValueError("invert applies only to raw")
    img = _compose(frame, width=width, height=height, rotation=rotation,
                   force_mono=(fmt == "raw"))
    if fmt == "raw":
        # PIL's mode "1" packing IS the framebuffer these panels want, with no
        # transformation at either end: eight pixels per byte, MSB leftmost,
        # rows padded to `ceil(width / 8)` — which is also MicroPython's
        # `framebuf.MONO_HLSB` stride — and bit 1 = white paper, 0 = black ink,
        # which is Waveshare's own convention (`Clear(0xff)` blanks a panel).
        # At 800×480 that is exactly 48,000 bytes in 100-byte rows.
        #
        # So the client is `sock.readinto(epd.buffer)`. No header to skip, no
        # row order to flip, no stride to unpad, no decompressor.
        body = img.tobytes()
        if invert:
            # For a controller whose driver takes 0 as white. Done on the packed
            # bytes and not on the image — see `_INVERT` for why every obvious
            # Pillow alternative returns a blank white panel instead. The row
            # padding at a width that is not a multiple of eight is flipped too;
            # those bits are off-panel for MONO_HLSB, so it costs nothing.
            body = body.translate(_INVERT)
        return body, _RAW_MEDIA
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png"
    # Explicit rather than a fallthrough. This used to be the `else`, which made
    # the allowlist above the only thing standing between a typo'd format and a
    # BMP served under the wrong content type.
    if fmt == "bmp":
        img.save(buf, "BMP")
        return buf.getvalue(), "image/bmp"
    raise ValueError(f"unhandled format {fmt!r}")
