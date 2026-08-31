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
_REGULAR = os.path.join(_FONT_DIR, "Inter-Regular.ttf")
_BOLD = os.path.join(_FONT_DIR, "Inter-Bold.ttf")

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
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    """One FreeType face per (weight, size). Cached: a month grid asks for the
    same four sizes a few hundred times, and each `truetype()` call re-reads and
    re-parses 150KB from disk."""
    return ImageFont.truetype(_BOLD if bold else _REGULAR, size)


def _text_width(draw: ImageDraw.ImageDraw, s: str, font) -> int:
    return int(draw.textlength(s, font=font))


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


def _render_calendar(
    img: Image.Image, frame: dict[str, Any], *, eink: bool, colors,
) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    scale = _scale(height)
    pad = int(16 * scale)
    cal = frame["calendar"]
    treatments = {s["id"]: s for s in frame["sources"]}

    title_font = _font(True, int(26 * scale))
    head_font = _font(True, int(12 * scale))
    day_font = _font(True, int(13 * scale))
    item_font = _font(False, int(12 * scale))

    # Header: the month, and the display's own name at the right. The name is
    # there because a household with two panels needs to know which one it is
    # looking at when one of them is showing last week.
    draw.text((pad, pad), cal["title"], font=title_font, fill=colors["ink"])
    name = _fit(draw, frame["display"]["name"], head_font, width // 3)
    if name:
        draw.text((width - pad - _text_width(draw, name, head_font), pad + int(10 * scale)),
                  name, font=head_font, fill=colors["muted"])
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
        x = pad + col_w * i
        draw.text((x + int(4 * scale), top + int(3 * scale)), label.upper(),
                  font=head_font, fill=colors["muted"])

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

    item_h = int(15 * scale)
    marker_size = int(7 * scale)
    for r, week in enumerate(cal["weeks"]):
        y = grid_top + row_h * r
        draw.line([(pad, y), (width - pad, y)], fill=colors["rule"], width=1)
        for c, cell in enumerate(week):
            x = pad + col_w * c
            cx, cy = int(x + 4 * scale), int(y + 3 * scale)
            number = _font(True, int(13 * scale)) if cell["today"] else day_font
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
                fill = colors["ink"] if cell["in_month"] else colors["muted"]
                font = day_font if cell["in_month"] else _font(False, int(13 * scale))
                draw.text((cx + int(3 * scale), cy), cell["label"], font=font, fill=fill)

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
                more = f"+{spare}"
                draw.text((x + col_w - _text_width(draw, more, item_font) - 4 * scale,
                           cy + int(3 * scale)),
                          more, font=item_font, fill=colors["muted"])
            for i, item in enumerate(shown):
                iy = item_top + i * item_h
                src = treatments.get(item["source"], {})
                _marker(draw, cx, iy + int(3 * scale), marker_size,
                        treatment=src.get("treatment", "solid"),
                        color=src.get("color") or _ACCENT, eink=eink, colors=colors)
                tx = cx + marker_size + int(4 * scale)
                prefix = f"{src['initial']} " if src.get("initial") else ""
                # The clock leads the title. A wall calendar is read for WHEN
                # before WHAT, and a time at a fixed left edge can be scanned
                # down the column; one trailing a title of variable length
                # cannot.
                label = f"{prefix}{item['time']} {item['text']}".strip() if item["time"] \
                    else f"{prefix}{item['text']}".strip()
                label = _fit(draw, label, item_font, int(col_w - (tx - x) - 4 * scale))
                if label:
                    draw.text((tx, iy), label, font=item_font, fill=colors["ink"])


def _render_habits(
    img: Image.Image, frame: dict[str, Any], *, eink: bool, colors,
) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    scale = _scale(height)
    pad = int(20 * scale)
    block = frame["habits"]

    title_font = _font(True, int(24 * scale))
    label_font = _font(True, int(11 * scale))
    row_font = _font(False, int(17 * scale))
    note_font = _font(False, int(12 * scale))

    draw.text((pad, pad), frame["display"]["name"], font=title_font, fill=colors["ink"])
    counts = block["counts"]
    # The score, at the right of the header. It is the whole reason the counts
    # are computed before the hiding: with `hide_done_habits` on, the list
    # empties as the day goes and this is the only thing left that remembers
    # there was anything on it.
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
        draw.text((pad, y), block["preview_text"], font=label_font, fill=colors["muted"])
        y += int(14 * scale)
        draw.text((pad, y), block["preview_hint"], font=note_font, fill=colors["muted"])
        y += int(20 * scale)

    row_h = int(28 * scale)
    glyph = int(15 * scale)

    def section(label: str, rows: list[dict], *, habit: bool, cursor: int) -> int:
        if not rows:
            return cursor
        draw.text((pad, cursor), label.upper(), font=label_font, fill=colors["muted"])
        cursor += int(16 * scale)
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
