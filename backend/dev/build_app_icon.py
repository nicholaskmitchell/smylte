"""Rebuild the Windows app icons, and the Apple touch icon, from the app's own SVG.

    python -m dev.build_app_icon

`frontend/public/favicon.svg` is the only place the "S." monogram is authored.
Every raster of it had, until this script, been cut by hand and committed with
no path back to that file — which is exactly how the shipped rasters came to
carry art that `d483f6e` ("Align favicon S monogram with sibling site
monograms") had already corrected in the SVG a month earlier.

Nothing imports it at runtime, and CI never runs it: the outputs are committed
binaries, the same posture as the display TTFs next door in
`build_display_fonts.py`. What CI does instead is *assert* they are correct —
see `desktop/Smylte.Desktop.Tests/AppIconTests.cs`.

**Why there are four icons.**

The old `app.ico` was cut from `apple-touch-icon.png`, and that was the whole
bug. iOS takes a full-bleed opaque square and masks, rounds and insets it
itself. Windows applies no mask, no radius, no inset and no shadow to a Win32
exe icon and composites whatever the file holds, literally.

A `.ico` carries exactly one image per size and has no light/dark variant
mechanism — that is an MSIX feature, and this is an unpackaged exe. Measured
across the composited acrylic range, `--accent` is the only brand colour that
clears 3:1 against BOTH taskbars (3.08:1 light, 3.82:1 dark); cream bottoms out
at 1.00 and `--fg` at 1.13. So a single shipped file has to be the accent one.

But that limit belongs to the FILE, not to the running program. A process can
read the current theme and set its window icon accordingly, which is what
`IconLibrary.cs` does — so the plated variants below become usable again on the
surfaces `Form.Icon` reaches. Hence: one compiled default that is safe
unattended, plus three alternates the app can switch between at runtime.

    app.ico          accent plate, paper S, ink period   <- stamped into the exe
    icon-paper.ico   cream plate, ink S, accent period    (best on a DARK taskbar)
    icon-ink.ico     ink plate, paper S, accent period    (best on a LIGHT taskbar)
    icon-mark.ico    bare accent mark, no plate           (theme-independent)

`app.ico` is the accent plate rather than the bare mark because it is the one
Explorer, a desktop shortcut and a pinned taskbar entry get, and none of those
can follow the theme — so it has to be the plated option that passes on both.

**Why three tiers per icon, and why the plated ones differ.**

Fraunces Medium Italic at opsz 46 is a display cut. Its thinnest stroke is
1.904 units on the 64 canvas, so below roughly 34px that hairline falls under
one device pixel and renders as a grey ghost — which is why the icon this
replaced decoded to five ink pixels at 16x16. The same fact is recorded in
`build_display_fonts.py`, where Fraunces is pinned to opsz 9 for the eink panel.

The fix is a uniform outward offset, and `solve_offset` sizes it per tier so the
thinnest stroke lands just over one device pixel at the SMALLEST size in that
tier. It is solved rather than tabulated because it depends on the mark's
scale, and the plated icons cannot use the same scale as the bare one: a plate
needs a margin, so its mark is smaller, so its strokes need a heavier offset to
survive — which in turn eats the interior apertures and the gap between letter
and period. `MARK_SCALE_PLATED = 5.4` is the tightest value where all four
floors still hold; below it the letter and its period start to merge at 16px,
and that failure is silent.

**Why the corners are rounded, at 12%.**

They are a departure from the editorial system's `border-radius: 0`, taken
deliberately: a hard-cornered full-bleed rectangle is the shape no other icon
on a Windows 11 taskbar has. Microsoft's own guidance specifies rounding (2px
at 48px, i.e. 4.2%), which measured too subtle to read at all; 12% is where the
tile stops looking like a screenshot. Worth knowing before tuning it: the radius
is only visible from about 48px up. At 16-24px it is one to three pixels of
corner, so it is not what makes the small sizes work — the mark scale and the
offset tiers are.

**Why the container is written by hand.**

Pillow's ICO writer fails quietly rather than loudly: `bitmap_format` is read
once outside its loop so formats cannot be mixed; any requested size larger than
the base image is dropped without a word; its for/else fallback silently
resamples from `append_images[-1]`; and it writes wPlanes=0. The container is
6 bytes plus 16 per entry — cheaper to write than to work around.

Entries are PNG at every size, not the more common BMP-below-256. The reason for
DIB frames is pre-Vista compatibility and the exe targets net8.0-windows; the
file this replaced was already PNG at all four sizes and rendered; and it is
~20 KB against ~300 KB, which matters for a binary reviewed in `git diff --stat`.
"""
from __future__ import annotations

import io
import os
import re
import struct

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SVG = os.path.join(ROOT, "frontend", "public", "favicon.svg")
DESKTOP = os.path.join(ROOT, "desktop", "Smylte.Desktop")
ICONS = os.path.join(DESKTOP, "icons")
TOUCH = os.path.join(ROOT, "frontend", "public", "apple-touch-icon.png")

# The design canvas the geometry below is expressed in, and the resolution every
# tier is rasterised at before being reduced. 8x the canvas, so a whole-pixel
# offset at master resolution stays whole.
CANVAS = 256
MASTER = CANVAS * 8

# Brand tokens. Nothing here is a derived or blended colour.
ACCENT = (0xC7, 0x5A, 0x26)   # --accent
PAPER = (0xF4, 0xF1, 0xE8)    # --paper
FG = (0x0E, 0x0E, 0x0C)       # --fg          (never #000000)
CREAM = (0xF3, 0xED, 0xE2)    # the favicon's own plate
INK = (0x1A, 0x18, 0x14)      # the favicon's own letter

# Mark bbox centre in the SVG's own 64-unit space, measured by flattening the
# path. This is the centre of S-UNION-PERIOD, not of the S: the favicon sits the
# S left of centre to make room for the period, and centring on the S alone
# would undo that.
MARK_CENTRE = (31.998, 30.940)

MARK_SCALE_BARE = 6.4     # 87.5% of the canvas — no plate, so no margin needed
MARK_SCALE_PLATED = 5.4   # 73.8%, leaving a 13% plate margin. See the docstring.
RADIUS_PCT = 12.0

# (file, plate, letter, period, mark scale). plate=None means no plate.
VARIANTS = (
    ("app.ico", ACCENT, PAPER, FG, MARK_SCALE_PLATED),
    ("icon-paper.ico", CREAM, INK, ACCENT, MARK_SCALE_PLATED),
    ("icon-ink.ico", FG, PAPER, ACCENT, MARK_SCALE_PLATED),
    ("icon-mark.ico", None, ACCENT, ACCENT, MARK_SCALE_BARE),
)

# Windows asks for 14 distinct sizes across its three request bands (title
# bar/tray 16/20/24/32/40/48/64, taskbar 24/30/36/48/60/72/96, Start pins
# 32/40/48/64/80/96/256), and 24 — the Windows 11 taskbar size at 100% scaling
# and a Microsoft bare-minimum size — was the one the old file omitted.
#
# 128 is on no Microsoft list. `ICONDIRENTRY.bWidth` is a byte and 256 is encoded
# as 0, and `Icon.Initialize` scores candidates on that raw byte, so the 256
# entry can never win at any requested size; without a 128, ICON_BIG (Alt-Tab,
# Task Manager) caps at 96 on a high-DPI display.
#
# Each tier names its sizes and the device-pixel width its thinnest stroke should
# reach at the SMALLEST of them. Seams are placed so that width stays continuous
# across them — the weight changes, the seam does not show.
TIERS = (
    ("A", (256, 128, 96, 80, 72, 64, 60, 48), None),
    ("B", (40, 36, 32, 30, 24), 1.30),
    ("C", (20, 16), 1.05),
)

# Source measurements in 64-unit space, from the flattened path: thinnest stroke
# and narrowest interior aperture by exact distance transform, gap by the nearest
# S point to the period's centre.
THIN_U, APERTURE_U, GAP_U = 1.904, 7.870, 5.153
PERIOD_U = 9.0   # the period's diameter, r=4.5

FLOORS = {"thin": 1.00, "aperture": 2.00, "period": 3.00, "gap": 1.50}


def parse_svg(path: str) -> tuple[str, tuple[float, float, float]]:
    """Return the S path's `d` and the period's (cx, cy, r), from the SVG itself.

    Deliberately not a general SVG parser. It reads the two shapes this file has
    always had and raises if it stops having them, because a favicon that grew a
    third element is a design change that should reach this script through a
    person rather than through a silent partial read.
    """
    svg = open(path, encoding="utf-8").read()
    d = re.search(r'<path[^>]*\sd="([^"]+)"', svg)
    circle = re.search(r'<circle[^>]*\scx="([\d.]+)"[^>]*\scy="([\d.]+)"[^>]*\sr="([\d.]+)"', svg)
    if not d or not circle:
        raise SystemExit(f"{path}: expected one <path> and one <circle>; the mark has changed shape")
    return d.group(1), tuple(float(g) for g in circle.groups())


def flatten(d: str, *, segments: int = 32) -> list[tuple[float, float]]:
    """Flatten an absolute M/L/Q/Z path into one closed polygon.

    The favicon's S is a single closed contour of quadratics — the output of a
    glyph-to-outline conversion — so this handles exactly that and refuses
    anything else rather than guessing.
    """
    tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    pts: list[tuple[float, float]] = []
    i, cmd = 0, None
    cur = (0.0, 0.0)
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                continue
        if cmd in ("M", "L"):
            cur = (float(tokens[i]), float(tokens[i + 1]))
            pts.append(cur)
            i += 2
            if cmd == "M":
                cmd = "L"   # an implicit repeat after M is a lineto, per the spec
        elif cmd == "Q":
            cx, cy = float(tokens[i]), float(tokens[i + 1])
            x, y = float(tokens[i + 2]), float(tokens[i + 3])
            x0, y0 = cur
            for s in range(1, segments + 1):
                t = s / segments
                u = 1 - t
                pts.append((u * u * x0 + 2 * u * t * cx + t * t * x,
                            u * u * y0 + 2 * u * t * cy + t * t * y))
            cur = (x, y)
            i += 4
        else:
            raise SystemExit(f"unsupported path command {cmd!r}; the mark has changed shape")
    return pts


def place(pts, centre, scale, size):
    """Map 64-unit coordinates onto a square raster of `size`, centring `centre`."""
    f = scale * size / CANVAS
    cx, cy = centre
    return [(size / 2 + (x - cx) * f, size / 2 + (y - cy) * f) for x, y in pts]


def solve_offset(scale: float, smallest: int, target_px: float | None) -> float:
    """The outward offset, in canvas units, that puts the thinnest stroke at
    `target_px` device pixels at `smallest`. None means no offset at all."""
    if target_px is None:
        return 0.0
    return max(0.0, target_px * CANVAS / smallest - THIN_U * scale)


def square_period(scale: float) -> float:
    """Side of the hard-cornered period used below 24px, in canvas units.

    Sized so its reach along the S-to-period separation axis (unit vector
    -0.9350, -0.3546) matches the disc's, which is what preserves the gap: a
    square merely inscribed in the disc's bounding box would eat it.
    """
    return 0.9375 * PERIOD_U * scale


def floors(scale: float, offset: float, size: int, *, squared: bool) -> dict[str, float]:
    """The four numbers that decide whether a size is legible, in device pixels.

    Each is one source dimension moved by the offset: it adds W to every stroke,
    takes W out of every interior aperture, and closes the letter-to-period gap
    by W/2 on the letter's side — plus another W/2 on the period's, unless the
    small tier has replaced it with an unstroked square.
    """
    f = size / CANVAS
    period = max(3.0, round(square_period(scale) * f)) if squared \
        else (PERIOD_U * scale + offset) * f
    growth = 0.0 if squared else offset / 2
    return {
        "thin": (THIN_U * scale + offset) * f,
        "aperture": (APERTURE_U * scale - offset) * f,
        "period": period,
        "gap": GAP_U * scale * f - (offset / 2 + growth) * f,
    }


def render_tier(s_path, period, plate, letter, dot, scale, offset) -> Image.Image:
    """Rasterise one tier as an RGBA image at MASTER resolution.

    The offset is drawn here, at master resolution, and never as a filter on a
    reduced image: a reduced-then-dilated mark is a different, heavier shape than
    the one `floors` was computed for.
    """
    # The transparent ground carries the mark's own colour, not black. Pillow's
    # RGBA reduce is not premultiplied, so it averages the RGB of fully
    # transparent pixels in with everything else: on a (0,0,0,0) ground every
    # edge is dragged toward black, which shows as a dark fringe around the
    # rounded corners and — because a 14/255 ink channel divided by a 64-pixel
    # box rounds to zero — produces genuinely #000000 pixels at low alpha.
    # Filling the ground with the colour the edge is fading out of makes the
    # average a no-op instead.
    ground = plate if plate is not None else letter
    img = Image.new("RGBA", (MASTER, MASTER), ground + (0,))
    draw = ImageDraw.Draw(img)

    if plate is not None:
        radius = RADIUS_PCT / 100 * MASTER
        draw.rounded_rectangle((0, 0, MASTER - 1, MASTER - 1), radius=radius, fill=plate + (255,))

    poly = place(s_path, MARK_CENTRE, scale, MASTER)
    draw.polygon(poly, fill=letter + (255,))
    if offset:
        # A stroke of width `offset` centred on the contour puts offset/2 outside
        # it; the inner half lands on already-filled pixels. joint="curve" gives
        # round joins, which the acute terminals of an italic S need — a miter
        # would throw visible whiskers.
        width = round(offset * MASTER / CANVAS)
        draw.line(poly + [poly[0]], fill=letter + (255,), width=width, joint="curve")

    cx, cy, r = period
    (px, py), = place([(cx, cy)], MARK_CENTRE, scale, MASTER)
    pr = (r * scale + offset / 2) * MASTER / CANVAS
    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=dot + (255,))
    return img


def stamp_square_period(img: Image.Image, period, dot, scale, size: int) -> None:
    """Replace the small tier's disc with a whole-pixel square, at final size.

    This is the hinting pass. At 16px the nominal disc is about 3px across and
    rasterises to a dozen partially-lit pixels; Microsoft's rule is that at least
    half an icon's pixels clear 3.0:1 on both themes, and partial coverage is
    exactly what fails it. Snapping to whole device pixels turns those into full
    ones. Drawn after the reduce, so nothing softens the corners.
    """
    cx, cy, _ = period
    (px, py), = place([(cx, cy)], MARK_CENTRE, scale, size)
    side = max(3, round(square_period(scale) * size / CANVAS))
    x0, y0 = round(px - side / 2), round(py - side / 2)
    ImageDraw.Draw(img).rectangle((x0, y0, x0 + side - 1, y0 + side - 1), fill=dot + (255,))


def png(img: Image.Image) -> bytes:
    """PNG bytes for one frame. Colortype 6, 8-bit, non-interlaced."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    blob = buf.getvalue()
    depth, ctype, _, _, interlace = struct.unpack_from(">BBBBB", blob, 24)
    if (depth, ctype, interlace) != (8, 6, 0):
        raise SystemExit(f"PNG came out depth={depth} colortype={ctype} interlace={interlace}")
    return blob


def write_ico(frames: list[tuple[int, bytes]], path: str) -> None:
    """Pack (size, png bytes) into an .ico. See the docstring for why by hand.

    Roslyn copies wPlanes/wBitCount verbatim out of the directory into the exe's
    RT_GROUP_ICON for PNG entries — it only overrides them when the payload opens
    with a 40-byte BITMAPINFOHEADER — so these have to be right here. The file
    this replaced declared 24bpp on frames that had no alpha channel at all.
    """
    head = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(head) + 16 * len(frames)
    entries, payloads = b"", b""
    for size, blob in frames:
        # 0 means 256 in a byte-wide field. Not doubled: that is the BMP variant.
        b = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(blob), offset)
        payloads += blob
        offset += len(blob)
    with open(path, "wb") as fh:
        fh.write(head + entries + payloads)


def build_variant(s_path, period, name, plate, letter, dot, scale) -> list[tuple]:
    frames, report = [], []
    for tier, sizes, target in TIERS:
        offset = solve_offset(scale, min(sizes), target)
        master = render_tier(s_path, period, plate, letter, dot, scale, offset)
        for size in sizes:
            # BOX, not LANCZOS. Reducing coverage is supposed to be an area
            # average, which is what BOX is at an integer ratio. LANCZOS is a
            # photographic filter whose negative lobes ring, and on a hard-edged
            # mark the ringing lands as a halo of low-alpha pixels around every
            # stroke; measured against Microsoft's "at least half the icon clears
            # 3.0:1 on both themes" rule it costs 12-18 points at every size
            # below 96, because every halo pixel is lit and fails the ratio.
            img = master.resize((size, size), Image.BOX)
            if tier == "C":
                stamp_square_period(img, period, dot, scale, size)
            frames.append((size, png(img)))
            report.append((size, tier, floors(scale, offset, size, squared=tier == "C")))
    frames.sort(key=lambda f: -f[0])
    path = os.path.join(DESKTOP if name == "app.ico" else ICONS, name)
    write_ico(frames, path)
    return sorted(report, key=lambda r: -r[0]), path


def build_touch(s_path, period, size: int = 180) -> None:
    """The Apple touch icon: the favicon, plated, at 180px.

    Unchanged in construction on purpose. iOS masks and rounds a full-bleed
    opaque square itself, so the plate that is wrong on Windows is right here —
    and the corners must stay square, because pre-rounding art the system will
    round again clips it. All this fixes is that the shipped file predates
    `d483f6e` and carries the un-aligned monogram. Colours are the SVG's own.
    """
    ss = 8
    img = Image.new("RGB", (size * ss, size * ss), CREAM)
    draw = ImageDraw.Draw(img)
    centre, scale = (32.0, 32.0), 4.0   # the favicon's own framing, not the icon's
    draw.polygon(place(s_path, centre, scale, size * ss), fill=INK)
    cx, cy, r = period
    (px, py), = place([(cx, cy)], centre, scale, size * ss)
    pr = r * scale * (size * ss) / CANVAS
    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=ACCENT)
    img.resize((size, size), Image.BOX).save(TOUCH, format="PNG", optimize=True)


def main() -> None:
    d, period = parse_svg(SVG)
    s_path = flatten(d)
    os.makedirs(ICONS, exist_ok=True)

    xs = [p[0] for p in s_path]
    ys = [p[1] for p in s_path]
    print(f"source  S bbox x {min(xs):.3f}..{max(xs):.3f}  y {min(ys):.3f}..{max(ys):.3f}"
          f"  ({len(s_path)} points)\n")

    bad = 0
    for name, plate, letter, dot, scale in VARIANTS:
        report, path = build_variant(s_path, period, name, plate, letter, dot, scale)
        fill = 35.004 * scale / CANVAS * 100
        print(f"{os.path.relpath(path, ROOT)}  {os.path.getsize(path) / 1024:.1f} KB, "
              f"{len(report)} entries, mark {fill:.1f}% of canvas")
        print(f"  {'size':>5} {'tier':>4} {'thin':>7} {'aperture':>9} {'period':>7} {'gap':>7}")
        for size, tier, f in report:
            flags = "".join(" !" if f[k] < FLOORS[k] else "  " for k in FLOORS)
            bad += flags.count("!")
            print(f"  {size:>5} {tier:>4} {f['thin']:>7.2f} {f['aperture']:>9.2f}"
                  f"{f['period']:>7.2f} {f['gap']:>7.2f}  {flags.strip()}")
        print()

    build_touch(s_path, period)
    print("floors: " + "  ".join(f"{k} >= {v:.2f}" for k, v in FLOORS.items()))
    print(f"{os.path.relpath(TOUCH, ROOT)}  {os.path.getsize(TOUCH) / 1024:.1f} KB")
    if bad:
        raise SystemExit(f"{bad} floor violation(s); the art is not shippable")


if __name__ == "__main__":
    main()
