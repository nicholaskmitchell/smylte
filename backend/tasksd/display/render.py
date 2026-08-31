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


def _text_width(draw: ImageDraw.ImageDraw, s: str, font) -> int:
    return int(draw.textlength(s, font=font))


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
    text = text.upper()
    if not text:
        return 0.0
    font = _font("mono", size)
    gap = size * track
    width = sum(draw.textlength(c, font=font) for c in text) + gap * (len(text) - 1)
    x = (right - width) if right is not None else xy[0]
    for char in text:
        draw.text((x, xy[1]), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + gap
    return width


def _fit(draw: ImageDraw.ImageDraw, s: str, font, width: int) -> str:
    """`s`, shortened with an ellipsis until it fits `width`.

    A binary search would be faster and is not worth it: the strings are event
    titles, and the loop runs a handful of times on the few that overflow. What
    matters is that it returns "" rather than a lone ellipsis when there is no
    room at all — a column of "…" tells the reader nothing except that the
    layout is wrong.
    """
    if not s:
        return ""
    if _text_width(draw, s, font) <= width:
        return s
    ellipsis = "…"
    if _text_width(draw, ellipsis, font) > width:
        return ""
    cut = s
    while cut and _text_width(draw, cut + ellipsis, font) > width:
        cut = cut[:-1]
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
    small = _item_scale(scale)
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
            shown = items[:room]
            spare = len(items) - len(shown) + cell["hidden"]
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
            for i, item in enumerate(shown):
                iy = item_top + i * item_h
                src = treatments.get(item["source"], {})
                _marker(draw, cx, iy + int(3 * scale), marker_size,
                        treatment=src.get("treatment", "solid"),
                        color=src.get("color") or _ACCENT, eink=eink, colors=colors)
                tx = cx + marker_size + int(4 * scale)
                room_w = int(col_w - (tx - x) - 4 * scale)
                # The clock leads the title, in mono — the app sets every time
                # it draws in mono (`.task-meta .due`), and here it also buys
                # tabular figures, so the times line up down the column instead
                # of ragging. A wall calendar is read for WHEN before WHAT, and
                # a fixed left edge is what makes the column scannable.
                if src.get("initial"):
                    tx += _label(draw, (tx, iy + int(1 * small)), src["initial"],
                                 int(11 * small), colors["ink"], track=0) + int(3 * small)
                if item["time"]:
                    stamp = item["time"]
                    draw.text((tx, iy), stamp, font=time_font, fill=colors["ink"])
                    used = _text_width(draw, stamp, time_font) + int(4 * small)
                    tx += used
                    room_w -= used
                text = _fit(draw, item["text"], item_font, room_w)
                if text:
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

    def section(label: str, rows: list[dict], *, habit: bool, cursor: int) -> int:
        if not rows:
            return cursor
        _label(draw, (pad, cursor), label, label_size, colors["muted"])
        cursor += int(18 * scale)
        for row in rows:
            if cursor + row_h > height - pad:
                break
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
        return cursor + int(10 * scale)

    y = section(block["heading"], block["habits"], habit=True, cursor=y)
    y = section(block["day_heading"], block["tasks"], habit=False, cursor=y)

    if not block["habits"] and not block["tasks"]:
        # Two different silences, and they are worth telling apart: a day that
        # had things on it and has none left is a finished day, and a day that
        # never had any is an empty one. Only the first deserves a well done.
        done_any = counts["habits_done"] or counts["tasks_done"]
        message = block["all_done_text"] if done_any else block["empty_text"]
        draw.text((pad, y), message, font=row_font, fill=colors["ink"])


def render_frame(
    frame: dict[str, Any], *, width: int, height: int,
    rotation: int = 0, fmt: str = "png",
) -> tuple[bytes, str]:
    """Draw `frame` for a `width`×`height` panel. Returns (bytes, media type).

    `width` and `height` are the panel's FRAMEBUFFER — what the device expects
    to be handed — and `rotation` is how that framebuffer is turned to reach the
    glass. So a portrait panel driven through a landscape controller is laid out
    PORTRAIT and rotated at the end, rather than being laid out landscape and
    turned, which would leave a month grid in seven columns lying on its side.
    """
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180 or 270")
    if fmt not in ("png", "bmp"):
        raise ValueError("format must be png or bmp")
    eink = frame["display"].get("palette") == "eink"
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
    if eink:
        # The one threshold, at the end. `dither=NONE` on purpose: Floyd
        # -Steinberg would turn the anti-aliased edge of every glyph into
        # scattered pixels that an eink panel's partial refresh leaves as ghosts.
        img = img.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png"
    img.save(buf, "BMP")
    return buf.getvalue(), "image/bmp"
