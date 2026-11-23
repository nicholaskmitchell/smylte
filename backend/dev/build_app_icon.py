"""Make every platform's app icon from one drawing, `brand/app-icon.svg`.

    python -m dev.build_app_icon            # write them
    python -m dev.build_app_icon --check    # exit non-zero if any is stale

The icon is the drawn check: the app's own CheckInk frame in ink and its tick
in coral ink, on a paper plate. `brand/app-icon.svg` is the only place it is
drawn. Everything below is made from that file and the Field notes tokens in
`frontend/src/styles/ds/themes.css`, and committed:

    frontend/public/favicon.svg                 small cut, light, and dark under
                                                prefers-color-scheme
    frontend/public/apple-touch-icon.png        180 px, full cut, opaque, square
    desktop/Smylte.Desktop/app.ico              paper   <- stamped into the exe
    desktop/Smylte.Desktop/icons/icon-ink.ico   ink
    desktop/Smylte.Desktop/icons/icon-accent.ico  accent
    desktop/Smylte.Desktop/icons/icon-mark.ico  mark
    desktop/Smylte.Desktop.Linux/icons/{paper,ink,accent,mark}-{16..256}.png
    desktop/Smylte.Desktop.Linux/icons/{paper,ink,accent,mark}.svg
    android/src/main/res/drawable/ic_launcher_foreground.xml
    android/src/main/res/drawable/ic_launcher_monochrome.xml
    android/src/main/res/values/colors.xml      the icon_plate value only

Nothing imports this at runtime and CI never writes with it. CI runs
`--check` instead, through `backend/tests/test_app_icon.py`, and the desktop
and Android suites assert the outputs' pixels and paths on their own side.

**This breaks a design-system rule, on the owner's choice.** The design system
draws a favicon as the wordmark's letter, "Newsreader italic 500, accent
period". The owner chose the drawn check instead on 22 Nov 2026;
`docs/fieldnotes-gaps.md` records the deviation and the sentence to amend.

**Two cuts, one drawing.** At 48 px and up the strokes are the source's
`stroke-width` (frame 3.2, tick 4.4 units of 64: the app's own pen, 1.8 and
2.6 px on a 28 px check, scaled). At 40 px and down they are its
`data-small-width` (4.8 and 6.4), so the frame stays at least one device pixel
wide at 16 px (1.2 px) and the tick keeps whole coral pixels (at least 7 at
16 px, measured). The paths do not change between cuts, only the pen. The
favicon is the small cut, because a browser draws it at 16 CSS px.

**Why the variants, and why `app.ico` is paper.** Windows composites a Win32
exe icon literally: no mask, radius, inset or shadow, and one image per size
with no light/dark variant outside MSIX. No Field notes colour clears 3:1
against both a light (#F3F3F3) and a dark (#202020) taskbar: coral fill is
2.62:1 on light, coral ink 2.63:1 on dark, paper 1.05:1 on light. The drawn
check does not need one. On a light taskbar the paper plate disappears and
the ink frame (13.5:1) is the edge; on a dark one the plate (14.0:1) is. So
the compiled default, which Explorer, a desktop shortcut and a pinned entry
show and none of which can follow the theme, is the paper variant, the same
icon the web, iOS and Android get. A running process can follow the theme, so
`IconLibrary.cs` switches between the four at runtime:

    paper    bg plate, fg frame, accent tick              (light tokens)
    ink      bg plate, fg frame, accent tick              (dark tokens)
    accent   accent-fill plate, fg frame, bg-elev tick    (light tokens)
    mark     no plate, accent frame, accent-fill tick     (light tokens)

**Why the source carries colours at all.** So it can be opened and looked at.
They are the paper variant's, and `read_source` refuses to run if they differ
from the tokens; every other colour is read from `themes.css`, never typed.

**Why Pillow and not a browser.** The option the owner chose was rendered in
Chromium. These rasters were compared with those renders at 16, 24, 32 and 48
px and are the same drawing, and Pillow's output was byte-identical under
Pillow 12.3 and 13.0. A browser would add a 150 MB dependency and a
renderer whose antialiasing changes with every release.

**How a stroke is drawn.** `ImageDraw.line` has no round cap and only joins
segments with its own geometry, so a path is flattened to a polyline and drawn
as that line plus a disc of the pen's width at every vertex: exactly a round
cap and a round join. Every tier is drawn at MASTER (8x the 256 canvas) and
reduced with BOX, never LANCZOS: reducing coverage is an area average, and on
a hard-edged mark LANCZOS's negative lobes ring into a halo of low-alpha
pixels.

**Why the transparent ground carries a colour.** Pillow's RGBA reduce averages
the RGB of fully transparent pixels with everything else, so on a (0,0,0,0)
ground every edge is dragged toward black. The ground is the plate's colour,
or the frame's for the bare mark, which makes that average a no-op.

**Why the corners are rounded, at 12%.** On the desktop plates only, the icon's
own choice rather than a step of the app's radius scale: a hard-cornered tile is
the shape no other icon on a Windows 11 taskbar has, and Microsoft's own 2px at
48px measured too subtle to read. It is visible from about 48 px. The Apple
touch icon and the favicon stay square: iOS rounds the touch icon itself, and a
pre-rounded one would be clipped twice.

**Why the .ico container is written by hand.** Pillow's ICO writer fails
quietly: `bitmap_format` is read once outside its loop, a size larger than the
base image is dropped without a word, its for/else fallback resamples from
`append_images[-1]`, and it writes wPlanes=0. The container is 6 bytes plus 16
per entry. Every entry is a PNG: the exe targets net8.0-windows, so the DIB
frames pre-Vista needed buy nothing.

**Nothing reaches the working tree until every check has passed.** Every output
is a committed binary. Written eagerly, a refused run would leave rejected art
on disk, indistinguishable in `git status` from a good regeneration.
"""
from __future__ import annotations

import io
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from typing import NamedTuple

from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

# Every path below is relative to the repository root.
SOURCE = "brand/app-icon.svg"
THEMES = "frontend/src/styles/ds/themes.css"
FAVICON = "frontend/public/favicon.svg"
TOUCH = "frontend/public/apple-touch-icon.png"
DESKTOP = "desktop/Smylte.Desktop"
ICONS = "desktop/Smylte.Desktop/icons"
LINUX = "desktop/Smylte.Desktop.Linux/icons"
DRAWABLE = "android/src/main/res/drawable"
COLORS = "android/src/main/res/values/colors.xml"

UNIT = 64            # the source's canvas
CANVAS = 256         # the Linux SVGs' canvas
MASTER = CANVAS * 8  # every raster tier is drawn at this size, then reduced
RADIUS_PCT = 12.0    # desktop plates only

# The cut each size gets. Windows asks for these fifteen across its three
# request bands (title bar and tray 16/20/24/32/40/48/64, taskbar
# 24/30/36/48/60/72/96, Start 32/40/48/64/80/96/256). 128 is on no Microsoft
# list: `ICONDIRENTRY.bWidth` is a byte, 256 is written as 0, and Windows
# scores candidates on that raw byte, so without a 128 Alt-Tab caps at 96.
TIERS = (
    ("full", (256, 128, 96, 80, 72, 64, 60, 48)),
    ("small", (40, 36, 32, 30, 24, 20, 16)),
)

# What freedesktop's hicolor theme names. The same seven are
# `IconChoices.FreedesktopSizes` in desktop/Smylte.Desktop/IconChoice.cs, which
# LinuxIconTests holds to this list.
LINUX_SIZES = (256, 128, 64, 48, 32, 24, 16)

# Android: the full cut in the 108dp adaptive canvas, its (32, 32) on the centre,
# and all of it inside the 66dp circle every launcher mask leaves visible.
ANDROID_SCALE = 1.04
ANDROID_SHIFT = 54 - 32 * ANDROID_SCALE
SAFE_RADIUS_DP = 33.0

# Per size: both pens at least one device pixel wide, and at least this many
# opaque pixels of the tick's own colour (within 10), so the coral is a colour
# and not a tint.
FLOORS = {"frame": 1.00, "tick": 1.00, "tick px": 4}

# --check: how far a committed raster's channel may sit from a fresh one.
TOLERANCE = 2

LIGHT = ':root[data-surface="app"]'
DARK = ':root[data-surface="app"][data-theme="dark"]'

# (container, Linux stem, plate, frame, tick), each colour a (block, token)
# in themes.css. The plate is None for the bare mark.
VARIANTS = (
    ("app.ico", "paper", (LIGHT, "--bg"), (LIGHT, "--fg"), (LIGHT, "--accent")),
    ("icon-ink.ico", "ink", (DARK, "--bg"), (DARK, "--fg"), (DARK, "--accent")),
    ("icon-accent.ico", "accent", (LIGHT, "--accent-fill"), (LIGHT, "--fg"), (LIGHT, "--bg-elev")),
    ("icon-mark.ico", "mark", None, (LIGHT, "--accent"), (LIGHT, "--accent-fill")),
)

SVG_NS = "{http://www.w3.org/2000/svg}"
GENERATED = ("Generated by backend/dev/build_app_icon.py from brand/app-icon.svg. "
             "Edit that, then run it.")


class Stroke(NamedTuple):
    d: str
    colour: str   # '#RRGGBB', upper case
    full: float   # pen width in source units, 48 px and up
    small: float  # pen width in source units, 40 px and down

    def width(self, cut: str) -> float:
        return self.full if cut == "full" else self.small


def read_tokens(root: str = ROOT) -> dict[str, dict[str, str]]:
    """The hex tokens of the two Field notes blocks in themes.css.

    {selector: {"--bg": "#F3EDE1", ...}}, upper case. The first rule whose
    selector is exactly LIGHT or DARK; comments stripped first, because the
    file annotates values in place.
    """
    css = re.sub(r"/\*.*?\*/", "", open(os.path.join(root, THEMES), encoding="utf-8").read(), flags=re.S)
    found: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = selector.strip()
        if selector in (LIGHT, DARK) and selector not in found:
            found[selector] = {name: value.upper() for name, value in
                               re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", body)}
    for selector in (LIGHT, DARK):
        if selector not in found:
            raise SystemExit(f"{THEMES}: no `{selector}` block")
    return found


def colour(tokens: dict[str, dict[str, str]], ref: tuple[str, str]) -> str:
    selector, name = ref
    if name not in tokens[selector]:
        raise SystemExit(f"{THEMES}: `{selector}` has no hex {name}")
    return tokens[selector][name]


def rgb(hex_colour: str) -> tuple[int, int, int]:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def read_source(root: str = ROOT) -> tuple[str, Stroke, Stroke]:
    """The plate colour and the two strokes, from brand/app-icon.svg.

    Deliberately not a general SVG reader. It reads the three shapes the icon
    is and refuses anything else, because a source that grew a fourth shape is
    a design change that should reach this script through a person, not be
    silently dropped from every platform's icon.
    """
    svg = ET.parse(os.path.join(root, SOURCE)).getroot()
    if svg.get("viewBox") != f"0 0 {UNIT} {UNIT}":
        raise SystemExit(f"{SOURCE}: the viewBox must be 0 0 {UNIT} {UNIT}")
    shapes = [(el.tag.replace(SVG_NS, ""), el.get("class")) for el in svg]
    if shapes != [("rect", "plate"), ("path", "frame"), ("path", "tick")]:
        raise SystemExit(f"{SOURCE}: expected rect.plate, path.frame and path.tick, in that "
                         f"order and nothing else; found {shapes}")
    plate, frame, tick = list(svg)
    strokes = []
    for el in (frame, tick):
        if (el.get("fill"), el.get("stroke-linecap"), el.get("stroke-linejoin")) != ("none", "round", "round"):
            raise SystemExit(f"{SOURCE}: path.{el.get('class')} must be fill none, round caps, round joins")
        try:
            strokes.append(Stroke(el.get("d"), el.get("stroke").upper(),
                                  float(el.get("stroke-width")), float(el.get("data-small-width"))))
        except (TypeError, ValueError, AttributeError):
            raise SystemExit(f"{SOURCE}: path.{el.get('class')} needs d, stroke, stroke-width "
                             f"and data-small-width") from None
    return plate.get("fill", "").upper(), strokes[0], strokes[1]


def check_source_colours(tokens, plate: str, frame: Stroke, tick: Stroke) -> None:
    for part, have, ref in (("plate", plate, (LIGHT, "--bg")), ("frame", frame.colour, (LIGHT, "--fg")),
                            ("tick", tick.colour, (LIGHT, "--accent"))):
        want = colour(tokens, ref)
        if have != want:
            raise SystemExit(f"{SOURCE}: the {part} is {have}, but Field notes light {ref[1]} is {want}")


def flatten(d: str, *, segments: int = 32) -> list[tuple[float, float]]:
    """Flatten an absolute M/L/C/Z path into a polyline.

    A closed path ends on its first point again. Anything else (relative
    commands, arcs, quadratics) is refused rather than guessed at.
    """
    tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    pts: list[tuple[float, float]] = []
    i, cmd, cur, closed = 0, None, (0.0, 0.0), False
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                closed = True
                continue
        if cmd in ("M", "L"):
            cur = (float(tokens[i]), float(tokens[i + 1]))
            pts.append(cur)
            i += 2
            if cmd == "M":
                cmd = "L"   # an implicit repeat after M is a lineto, per the spec
        elif cmd == "C":
            (x1, y1), (x2, y2), (x, y) = ((float(tokens[i + j]), float(tokens[i + j + 1])) for j in (0, 2, 4))
            x0, y0 = cur
            for s in range(1, segments + 1):
                t = s / segments
                u = 1 - t
                pts.append((u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x,
                            u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y))
            cur = (x, y)
            i += 6
        else:
            raise SystemExit(f"unsupported path command {cmd!r}; the icon has changed shape")
    if closed and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def pen(draw: ImageDraw.ImageDraw, d: str, width: float, colour: tuple[int, int, int], k: float) -> None:
    """One stroke with round caps and joins: the polyline, then a disc of the
    pen's width on every vertex. `width` is in output pixels, `k` maps source
    units to output pixels."""
    pts = [(x * k, y * k) for x, y in flatten(d)]
    draw.line(pts, fill=colour + (255,), width=max(1, round(width)))
    r = width / 2
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour + (255,))


def render(frame: Stroke, tick: Stroke, cut: str, plate, ink, coral, *, size: int = MASTER,
           radius_pct: float = RADIUS_PCT) -> Image.Image:
    """One variant and cut as RGBA at `size`. plate None means no plate."""
    ground = plate if plate is not None else ink
    img = Image.new("RGBA", (size, size), ground + (0,))
    draw = ImageDraw.Draw(img)
    if plate is not None:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius_pct / 100 * size, fill=plate + (255,))
    k = size / UNIT
    pen(draw, frame.d, frame.width(cut) * k, ink, k)
    pen(draw, tick.d, tick.width(cut) * k, coral, k)
    return img


def count_near(img: Image.Image, colour: tuple[int, int, int]) -> int:
    """Opaque pixels within RGB distance 10 of `colour`."""
    data = img.tobytes()
    return sum(1 for i in range(0, len(data), 4)
               if data[i + 3] >= 250 and (data[i] - colour[0]) ** 2 + (data[i + 1] - colour[1]) ** 2
               + (data[i + 2] - colour[2]) ** 2 <= 100)


def geometry(frame: Stroke, tick: Stroke) -> tuple[float, float]:
    """(the closest any pen comes to the canvas edge, in source units, over both
    cuts; the farthest any pen of the full cut reaches from the centre, in dp on
    Android's canvas)."""
    margin = min(min(x, y, UNIT - x, UNIT - y) - s.width(cut) / 2
                 for cut in ("full", "small") for s in (frame, tick) for x, y in flatten(s.d))
    reach = max(math.hypot(x - UNIT / 2, y - UNIT / 2) + s.full / 2
                for s in (frame, tick) for x, y in flatten(s.d)) * ANDROID_SCALE
    return margin, reach


def png(img: Image.Image) -> bytes:
    """PNG bytes for one frame. Colortype 6, 8-bit, non-interlaced."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    blob = buf.getvalue()
    depth, ctype, _, _, interlace = struct.unpack_from(">BBBBB", blob, 24)
    if (depth, ctype, interlace) != (8, 6, 0):
        raise SystemExit(f"PNG came out depth={depth} colortype={ctype} interlace={interlace}")
    return blob


def pack_ico(frames: list[tuple[int, bytes]]) -> bytes:
    """Pack (size, png bytes) into an .ico. See the docstring for why by hand.

    Roslyn copies wPlanes/wBitCount verbatim out of the directory into the exe's
    RT_GROUP_ICON for PNG entries, so these have to be right here.
    """
    head = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(head) + 16 * len(frames)
    entries, payloads = b"", b""
    for size, blob in frames:
        b = 0 if size == 256 else size   # 0 means 256 in a byte-wide field
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(blob), offset)
        payloads += blob
        offset += len(blob)
    return head + entries + payloads


def ico_frames(blob: bytes) -> dict[int, bytes]:
    """{size: png bytes} out of an .ico."""
    frames = {}
    for i in range(struct.unpack_from("<H", blob, 4)[0]):
        width, _, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", blob, 6 + 16 * i)
        frames[width or 256] = blob[offset:offset + length]
    return frames


def scale_path(d: str, k: float) -> str:
    """Every coordinate of an absolute path times k."""
    return re.sub(r"-?\d*\.?\d+", lambda m: f"{float(m.group()) * k:.2f}", d)


def svg_stroke(d: str, colour: str, width: float) -> str:
    return (f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width:g}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def favicon(frame: Stroke, tick: Stroke, light: tuple[str, str, str], dark: tuple[str, str, str]) -> str:
    """The small cut, in Field notes light, and in dark under prefers-color-scheme.
    Square: a tab icon is not masked."""
    def group(cls, plate, ink, coral):
        return (f'  <g class="{cls}">\n'
                f'    <rect width="{UNIT}" height="{UNIT}" fill="{plate}"/>\n'
                f'    {svg_stroke(frame.d, ink, frame.small)}\n'
                f'    {svg_stroke(tick.d, coral, tick.small)}\n'
                f'  </g>\n')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {UNIT} {UNIT}" width="{UNIT}" height="{UNIT}">\n'
            f'  <!-- {GENERATED} -->\n'
            f'  <style>.d{{display:none}}@media (prefers-color-scheme:dark){{.l{{display:none}}.d{{display:inline}}}}</style>\n'
            + group("l", *light) + group("d", *dark) + '</svg>\n')


def linux_svg(frame: Stroke, tick: Stroke, plate, ink: str, coral: str) -> str:
    """One variant on the 256 canvas, full cut, for sizes no PNG covers."""
    k = CANVAS / UNIT
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS} {CANVAS}" '
            f'width="{CANVAS}" height="{CANVAS}">']
    if plate is not None:
        body.append(f'<rect width="{CANVAS}" height="{CANVAS}" rx="{RADIUS_PCT / 100 * CANVAS:.3f}" '
                    f'fill="{plate.lower()}"/>')
    body.append(svg_stroke(scale_path(frame.d, k), ink.lower(), frame.full * k))
    body.append(svg_stroke(scale_path(tick.d, k), coral.lower(), tick.full * k))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def drawable(frame: Stroke, tick: Stroke, ink: str, coral: str, *, monochrome: bool) -> str:
    """An adaptive-icon layer: the full cut in the 108dp canvas."""
    note = ("\n     This is the monochrome layer for themed icons; the launcher reads only\n"
            "     its alpha.") if monochrome else ""

    def path(s: Stroke, c: str) -> str:
        return (f'        <path\n'
                f'            android:pathData="{s.d}"\n'
                f'            android:strokeColor="{c}"\n'
                f'            android:strokeWidth="{s.full:g}"\n'
                f'            android:strokeLineCap="round"\n'
                f'            android:strokeLineJoin="round" />\n')
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<!-- {GENERATED}\n'
            f'     The frame and the tick in the icon\'s 64-unit space, scaled {ANDROID_SCALE:g} and centred\n'
            '     in the 108dp adaptive-icon canvas, inside the 66dp circle every launcher\n'
            f'     mask leaves visible. IconDriftTest fails if this and the source differ.{note} -->\n'
            '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    android:width="108dp"\n'
            '    android:height="108dp"\n'
            '    android:viewportWidth="108"\n'
            '    android:viewportHeight="108">\n'
            '    <group\n'
            f'        android:scaleX="{ANDROID_SCALE:g}"\n'
            f'        android:scaleY="{ANDROID_SCALE:g}"\n'
            f'        android:translateX="{ANDROID_SHIFT:g}"\n'
            f'        android:translateY="{ANDROID_SHIFT:g}">\n'
            + path(frame, ink) + path(tick, coral) +
            '    </group>\n'
            '</vector>\n')


def recolour_plate(root: str, plate: str) -> str:
    """colors.xml with icon_plate set to `plate` and nothing else touched."""
    xml = open(os.path.join(root, COLORS), encoding="utf-8").read()
    out, n = re.subn(r'(<color name="icon_plate">)#[0-9A-Fa-f]{6}(</color>)', rf"\g<1>{plate}\g<2>", xml)
    if n != 1:
        raise SystemExit(f"{COLORS}: expected one icon_plate colour, found {n}")
    return out


def build(root: str = ROOT) -> tuple[dict[str, bytes], list[str], int]:
    """Every output in memory: ({relative path: bytes}, report lines, floor violations)."""
    tokens = read_tokens(root)
    plate_hex, frame, tick = read_source(root)
    check_source_colours(tokens, plate_hex, frame, tick)

    out: dict[str, bytes] = {}
    lines: list[str] = []
    bad = 0

    margin, reach = geometry(frame, tick)
    corner = RADIUS_PCT / 100 * UNIT
    lines.append(f"{SOURCE}  edge margin {margin:.2f} units (>= {corner:.2f}), "
                 f"Android reach {reach:.2f} dp (<= {SAFE_RADIUS_DP:.1f})")
    if margin < corner:
        lines.append("  ! a pen reaches into the plate's rounded corner")
        bad += 1
    if reach > SAFE_RADIUS_DP:
        lines.append("  ! the Android foreground leaves the 66dp safe circle")
        bad += 1
    lines.append("")

    for name, stem, plate_ref, frame_ref, tick_ref in VARIANTS:
        plate = rgb(colour(tokens, plate_ref)) if plate_ref else None
        ink, coral = rgb(colour(tokens, frame_ref)), rgb(colour(tokens, tick_ref))
        frames, rows = [], []
        for cut, sizes in TIERS:
            master = render(frame, tick, cut, plate, ink, coral)
            for size in sizes:
                img = master.resize((size, size), Image.BOX)
                blob = png(img)
                frames.append((size, blob))
                if size in LINUX_SIZES:
                    out[f"{LINUX}/{stem}-{size}.png"] = blob   # the same bytes as the .ico frame
                f = {"frame": frame.width(cut) * size / UNIT, "tick": tick.width(cut) * size / UNIT,
                     "tick px": count_near(img, coral)}
                flags = " ".join("!" if f[k] < FLOORS[k] else " " for k in FLOORS)
                bad += flags.count("!")
                rows.append(f"  {size:>5} {cut:>5} {f['frame']:>6.2f} {f['tick']:>6.2f} {f['tick px']:>7}  {flags}")
        missing = set(LINUX_SIZES) - {s for s, _ in frames}
        if missing:
            raise SystemExit(f"{stem}: {sorted(missing)} are in no tier; add them to TIERS")
        frames.sort(key=lambda f: -f[0])
        path = f"{DESKTOP if name == 'app.ico' else ICONS}/{name}"
        out[path] = pack_ico(frames)
        out[f"{LINUX}/{stem}.svg"] = linux_svg(
            frame, tick, colour(tokens, plate_ref) if plate_ref else None,
            colour(tokens, frame_ref), colour(tokens, tick_ref)).encode("utf-8")
        lines.append(f"{path}  {len(out[path]) / 1024:.1f} KB, {len(frames)} entries; {LINUX}/{stem}-*.png + {stem}.svg")
        lines.append(f"  {'size':>5} {'cut':>5} {'frame':>6} {'tick':>6} {'tick px':>7}")
        lines.extend(sorted(rows, key=lambda r: -int(r.split()[0])))
        lines.append("")

    paper = [colour(tokens, (LIGHT, t)) for t in ("--bg", "--fg", "--accent")]
    night = [colour(tokens, (DARK, t)) for t in ("--bg", "--fg", "--accent")]
    touch = render(frame, tick, "full", rgb(paper[0]), rgb(paper[1]), rgb(paper[2]), size=180 * 8, radius_pct=0)
    buf = io.BytesIO()
    touch.resize((180, 180), Image.BOX).convert("RGB").save(buf, format="PNG", optimize=True)
    out[TOUCH] = buf.getvalue()
    out[FAVICON] = favicon(frame, tick, tuple(paper), tuple(night)).encode("utf-8")
    out[f"{DRAWABLE}/ic_launcher_foreground.xml"] = drawable(frame, tick, paper[1], paper[2], monochrome=False).encode("utf-8")
    out[f"{DRAWABLE}/ic_launcher_monochrome.xml"] = drawable(frame, tick, "#FF000000", "#FF000000", monochrome=True).encode("utf-8")
    out[COLORS] = recolour_plate(root, paper[0]).encode("utf-8")
    lines.append("floors: " + "  ".join(f"{k} >= {v:g}" for k, v in FLOORS.items()))
    return out, lines, bad


def strays(root: str, out: dict[str, bytes]) -> list[str]:
    """.ico files in ICONS that are no variant: the csproj embeds every one."""
    folder = os.path.join(root, ICONS)
    have = {f for f in os.listdir(folder) if f.endswith(".ico")} if os.path.isdir(folder) else set()
    return sorted(f"{ICONS}/{f}" for f in have - {p.rsplit('/', 1)[1] for p in out if p.startswith(ICONS + "/")})


def same_pixels(a: bytes, b: bytes) -> bool:
    ia, ib = Image.open(io.BytesIO(a)), Image.open(io.BytesIO(b))
    if ia.size != ib.size or ia.mode != ib.mode:
        return False
    return max(hi for _, hi in ImageChops.difference(ia, ib).getextrema()) <= TOLERANCE


def stale(root: str, out: dict[str, bytes]) -> list[str]:
    """The outputs whose committed copy is not what `build` makes, plus strays.

    Text is compared exactly. A raster is compared by its pixels, within
    TOLERANCE per channel, not by its bytes: zlib may compress the same pixels
    differently from one build to the next.
    """
    found = strays(root, out)
    for path, blob in out.items():
        full = os.path.join(root, path)
        if not os.path.exists(full):
            found.append(path)
            continue
        disk = open(full, "rb").read()
        if path.endswith(".ico"):
            a, b = ico_frames(blob), ico_frames(disk)
            ok = a.keys() == b.keys() and all(same_pixels(a[s], b[s]) for s in a)
        elif path.endswith(".png"):
            ok = same_pixels(blob, disk)
        else:
            ok = blob == disk
        if not ok:
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--check"]):
        raise SystemExit("usage: python -m dev.build_app_icon [--check]")
    out, lines, bad = build(ROOT)
    print("\n".join(lines))
    # Before anything is written, which is the point: a refused run leaves the
    # working tree exactly as it found it.
    if bad:
        raise SystemExit(f"{bad} floor violation(s); the art is not shippable")
    if args == ["--check"]:
        found = stale(ROOT, out)
        if found:
            raise SystemExit("stale: " + ", ".join(found) + "\nrun: cd backend && python -m dev.build_app_icon")
        print("every output is current")
        return
    extra = strays(ROOT, out)
    if extra:
        raise SystemExit(f"not a variant any more: {', '.join(extra)}. git rm it; "
                         f"Smylte.Desktop.csproj embeds every .ico in {ICONS}")
    for path, blob in out.items():
        full = os.path.join(ROOT, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(blob)
    print(f"wrote {len(out)} files")


if __name__ == "__main__":
    main()
