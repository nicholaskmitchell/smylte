"""Rebuild the Windows app icon, and the Apple touch icon, from the app's own SVG.

    python -m dev.build_app_icon

`frontend/public/favicon.svg` is the only place the "S." monogram is authored.
Every raster of it has, until now, been cut by hand and committed with no path
back to that file — which is exactly how the two shipped rasters ended up
carrying art that `d483f6e` ("Align favicon S monogram with sibling site
monograms") had already corrected in the SVG a month earlier. They are ~7%
small and ~3 units left of centre. This script exists so that stops being
possible.

Nothing imports it at runtime, and CI never runs it: the outputs are committed
binaries, the same posture as the display TTFs next door in
`build_display_fonts.py`. What CI does instead is *assert* the .ico is correct —
see `desktop/Smylte.Desktop.Tests/AppIconTests.cs`.

**Why the Windows icon is not the favicon.**

The old `app.ico` was cut from `apple-touch-icon.png`, and that is the whole
bug. iOS takes a full-bleed opaque square and masks, rounds and insets it
itself. Windows does none of that — there is no mask, no corner radius, no safe
area and no shadow applied to an unpackaged Win32 exe icon. Whatever the file
contains is composited literally onto the taskbar.

So the cream plate, which the OS hides on iOS, is drawn in full on Windows, and
it fails on both themes at once: 1.05:1 against the light taskbar (#F3F3F3 —
invisible, a warm smudge that reads as a rendering fault) and 13.98:1 against
the dark one (#202020 — the brightest object on the bar). A Win32 .ico carries
exactly one image per size and there is no MSIX `altform-unplated` escape
hatch, so "pick a theme and be wrong on the other" is permanent, not a phase.

Measured against the whole composited acrylic range, `--accent` #C75A26 is the
ONLY brand colour that clears 3:1 on both taskbars — 3.08:1 light, 3.82:1 dark.
Every other token bottoms out where it cannot be seen: cream 1.00, --paper
1.02, --bg 1.01, --fg 1.13, the favicon's ink 1.04. That is not a stylistic
finding, it is the constraint. Hence: no plate, and the mark itself in accent.

The cost is real and worth naming — the terminal period stops being a *colour*
gesture and is distinguished by form alone. All three two-tone alternatives were
measured and die on one theme.

`apple-touch-icon.png` keeps the plate, because iOS still masks it. The two
platforms diverging is the point.

**Why three tiers rather than one master, resampled.**

Fraunces Medium Italic at opsz 46 is a display cut. Its thinnest stroke is
1.904 units on the 64 canvas, so below ~34px that hairline is under one device
pixel and renders as a grey ghost — which is why the shipped 16x16 decodes to
five ink pixels and no letterform. This is the same fact `build_display_fonts.py`
records for the eink panel, where it pins opsz to 9 for exactly this reason.

Here the fix is a uniform outward offset, sized per tier so the thinnest stroke
lands just over one device pixel at the SMALLEST size in that tier:

    A  48-256  W = 0     letterform verbatim, stroke contrast 3.30:1
    B  24-40   W = 2.0   contrast 2.97:1
    C  16-20   W = 4.5   contrast 2.68:1, thinnest stroke 1.04px at 16

Tier seams are placed so the device-pixel stroke width is continuous across
them (48px 2.28 -> 40px 2.22; 24px 1.33 -> 20px 1.30): the weight changes but
the seam is invisible. Moving the offset in step with size is what a real opsz
axis does, approximated with the one lever an outline gives you.

At tier C the period also stops being a disc. A 3.4px circle rasterises to a
dozen partially-lit pixels and reads as an antialiasing accident; a square of
the same reach snaps to a solid block. It is 54 units and not something rounder
because 54's reach along the S-to-period separation axis (27 / 0.9350 = 28.88)
matches the disc's 28.80, which preserves the gap a bigger square would eat.
That gap is the tightest number in the design — 1.92px at 16 — and it fails
SILENTLY, by the S and the period merging into one blob. `floors()` checks it.

**Why the sizes.**

Windows asks for 14 distinct sizes across its three bands (title bar/tray
16/20/24/32/40/48/64, taskbar 24/30/36/48/60/72/96, Start pins
32/40/48/64/80/96/256). The old file had four of them. Microsoft's stated bare
minimum is 16/24/32/48/256 and the missing one was 24 — the Windows 11 taskbar
size at 100% scaling, the single most visible surface there is.

128 is on no Microsoft list and is here for a different reason:
`ICONDIRENTRY.bWidth` is a byte, 256 is encoded as 0, and
`System.Drawing.Icon.Initialize` scores candidates on that raw byte — so the 256
entry is unreachable from managed code at any requested size. Without a 128,
ICON_BIG (Alt-Tab, Task Manager) caps at 96 on a high-DPI display.

**Why the container is written by hand.**

Pillow's ICO writer cannot do this job, and fails quietly rather than loudly:
`bitmap_format` is read once outside its loop so formats cannot be mixed; any
requested size larger than the base image is dropped without a word; its
for/else fallback silently resamples from `append_images[-1]`; and it writes
wPlanes=0. The container is a 6-byte header plus 16 bytes per entry. Writing it
is cheaper than working around a writer that does the wrong thing invisibly.

Entries are PNG at every size, not the more common BMP-below-256. The reason for
DIB frames is pre-Vista compatibility, and the exe targets net8.0-windows; the
old file was already PNG at all four sizes and rendered; and it is ~20 KB
against ~300 KB, which matters for a binary a reviewer reads in `git diff
--stat` every time the art moves.
"""
from __future__ import annotations

import io
import os
import re
import struct

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.normpath(os.path.join(HERE, "..", "..", "frontend", "public", "favicon.svg"))
ICO = os.path.normpath(os.path.join(HERE, "..", "..", "desktop", "Smylte.Desktop", "app.ico"))
TOUCH = os.path.normpath(os.path.join(HERE, "..", "..", "frontend", "public", "apple-touch-icon.png"))

# The design canvas the geometry below is expressed in, and the resolution every
# tier is rasterised at before being reduced to a target size. 8x the canvas, so
# both tier offsets (2.0 and 4.5 units) land on a whole number of master pixels.
CANVAS = 256
MASTER = CANVAS * 8

ACCENT = (0xC7, 0x5A, 0x26)

# Mark bbox centre in the SVG's own 64-unit space, measured by flattening the
# path. Note this is the centre of S-UNION-PERIOD, not of the S: the favicon
# deliberately sits the S left of centre to make room for the period, and
# centring on the S alone would undo that.
MARK_CENTRE = (31.998, 30.940)
SCALE = 6.4  # 4.0 (64 -> 256) x 1.60 enlargement, giving a 87.5% live area

# Tier -> (sizes, outward offset in canvas units). See the docstring.
TIERS = (
    ("A", (256, 128, 96, 80, 72, 64, 60, 48), 0.0),
    ("B", (40, 36, 32, 30, 24), 2.0),
    ("C", (20, 16), 4.5),
)

# Tier C's square period, in canvas units. Sized to match the disc's reach along
# the S-to-period separation axis so the gap survives; see the docstring.
SQUARE_PERIOD = 54.0

# Source measurements, in 64-unit space, used to report the floors. Derived from
# the flattened path (thin/thick/aperture by exact distance transform, gap by
# nearest S point to the period centre) rather than re-measured on every run.
THIN_U = 1.904
APERTURE_U = 7.870
GAP_U = 5.153

FLOORS = {"thin": 1.00, "aperture": 2.00, "period": 3.00, "gap": 1.50}


def parse_svg(path: str) -> tuple[str, tuple[float, float, float]]:
    """Return the S path's `d` and the period's (cx, cy, r), from the SVG itself.

    Deliberately not a general SVG parser. It reads the two shapes this file has
    always had, and raises if the file stops having them — which is the right
    failure, because a favicon that grew a third element is a design change that
    should reach this script through a human, not through a silent partial read.
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
            # An implicit repeat after M is a lineto, per the SVG spec.
            if cmd == "M":
                cmd = "L"
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


def render_tier(s_path, period, offset: float) -> Image.Image:
    """Rasterise one tier's art as an 8-bit coverage mask at MASTER resolution.

    Colour is applied after reduction, so the reduce is a pure coverage average
    and no colour fringing can enter. The offset is drawn here, at master
    resolution, and never as a filter on a reduced image — a reduced-then-
    dilated mark is a different, heavier shape than the one the floors below
    were computed for.
    """
    mask = Image.new("L", (MASTER, MASTER), 0)
    draw = ImageDraw.Draw(mask)

    poly = place(s_path, MARK_CENTRE, SCALE, MASTER)
    draw.polygon(poly, fill=255)
    if offset:
        # A stroke of width `offset` centred on the contour puts offset/2 outside
        # it; the inner half lands on already-filled pixels. joint="curve" gives
        # round joins, which the acute terminals of an italic S need — a miter
        # would throw visible whiskers.
        width = round(offset * MASTER / CANVAS)
        draw.line(poly + [poly[0]], fill=255, width=width, joint="curve")

    cx, cy, r = period
    (px, py), = place([(cx, cy)], MARK_CENTRE, SCALE, MASTER)
    pr = (r * SCALE + offset / 2) * MASTER / CANVAS
    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=255)
    return mask


def stamp_square_period(mask: Image.Image, period, size: int) -> None:
    """Replace tier C's disc with a whole-pixel square, in place, at final size.

    This is the hinting pass. At 16px the nominal disc is 3.38px and rasterises
    to a dozen partially-lit pixels; Microsoft's own rule is that at least half
    an icon's pixels clear 3.0:1 on both themes, and partial coverage is exactly
    what fails it. Snapping to whole device pixels converts those into full ones.
    Drawn after the reduce, so nothing softens the corners.
    """
    cx, cy, _ = period
    (px, py), = place([(cx, cy)], MARK_CENTRE, SCALE, size)
    side = max(3, round(SQUARE_PERIOD * size / CANVAS))
    x0 = round(px - side / 2)
    y0 = round(py - side / 2)
    ImageDraw.Draw(mask).rectangle((x0, y0, x0 + side - 1, y0 + side - 1), fill=255)


def floors(size: int, tier: str, offset: float) -> dict[str, float]:
    """The four numbers that decide whether a size is legible, in device pixels.

    Computed rather than measured because each is a single source dimension
    moved by the tier offset: the offset adds W to every stroke, takes W out of
    every interior aperture, and closes the S-to-period gap by W/2 on the S side
    (plus another W/2 on the period side, unless tier C has replaced it with an
    unstroked square).
    """
    f = SCALE * size / CANVAS
    period_growth = 0.0 if tier == "C" else offset / 2
    period = (SQUARE_PERIOD * size / CANVAS if tier == "C"
              else (2 * 4.5 * SCALE + offset) * size / CANVAS)
    return {
        "thin": THIN_U * f + offset * size / CANVAS,
        "aperture": APERTURE_U * f - offset * size / CANVAS,
        "period": period,
        "gap": GAP_U * f - (offset / 2 + period_growth) * size / CANVAS,
    }


def png(mask: Image.Image) -> bytes:
    """An RGBA PNG of the accent colour, cut by `mask`. Colortype 6, no interlace."""
    img = Image.new("RGBA", mask.size, ACCENT + (0,))
    img.putalpha(mask)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    blob = buf.getvalue()
    depth, ctype, _, _, interlace = struct.unpack_from(">BBBBB", blob, 24)
    if (depth, ctype, interlace) != (8, 6, 0):
        raise SystemExit(f"PNG came out depth={depth} colortype={ctype} interlace={interlace}")
    return blob


def write_ico(frames: list[tuple[int, bytes]], path: str) -> None:
    """Pack (size, png bytes) into an .ico. See the docstring for why by hand.

    Roslyn copies wPlanes/wBitCount verbatim out of the directory and into the
    exe's RT_GROUP_ICON for PNG entries — it only overrides them when the payload
    starts with a 40-byte BITMAPINFOHEADER — so these have to be right here.
    The old file declared 24bpp on frames that had no alpha channel at all.
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


def build_ico(s_path, period) -> list[tuple[int, dict[str, float], str]]:
    frames, report = [], []
    for tier, sizes, offset in TIERS:
        master = render_tier(s_path, period, offset)
        for size in sizes:
            # BOX, not LANCZOS. This is a coverage mask, and reducing it is
            # supposed to be an area average — which is exactly what BOX is at
            # an integer ratio. LANCZOS is a photographic filter whose negative
            # lobes ring, and on a hard-edged mark the ringing lands as a halo
            # of low-alpha pixels around every stroke. Measured against
            # Microsoft's "at least half the icon clears 3.0:1 on both themes"
            # rule, LANCZOS costs 12-18 points at every size below 96 (16px
            # 31.1% vs 42.9%, 32px 42.4% vs 60.9%, 48px 51.0% vs 69.5%) because
            # every one of those halo pixels is lit and fails the ratio.
            mask = master.resize((size, size), Image.BOX)
            if tier == "C":
                stamp_square_period(mask, period, size)
            frames.append((size, png(mask)))
            report.append((size, floors(size, tier, offset), tier))
    frames.sort(key=lambda f: -f[0])
    write_ico(frames, ICO)
    return sorted(report, key=lambda r: -r[0])


def build_touch(s_path, period, size: int = 180) -> None:
    """The Apple touch icon: the favicon, plated, at 180px.

    Unchanged in construction on purpose. iOS masks and rounds a full-bleed
    opaque square itself, so the plate that is wrong on Windows is right here;
    all this fixes is that the shipped file predates `d483f6e` and carries the
    un-aligned monogram. Colours are the SVG's own, so nothing drifts.
    """
    ss = 8
    img = Image.new("RGB", (size * ss, size * ss), (0xF3, 0xED, 0xE2))
    draw = ImageDraw.Draw(img)
    centre, scale = (32.0, 32.0), 4.0  # the favicon's own framing, not the icon's
    draw.polygon(place(s_path, centre, scale, size * ss), fill=(0x1A, 0x18, 0x14))
    cx, cy, r = period
    (px, py), = place([(cx, cy)], centre, scale, size * ss)
    pr = r * scale * (size * ss) / CANVAS
    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(0xC7, 0x5A, 0x26))
    img.resize((size, size), Image.BOX).save(TOUCH, format="PNG", optimize=True)


def main() -> None:
    d, period = parse_svg(SVG)
    s_path = flatten(d)

    xs = [p[0] for p in s_path]
    ys = [p[1] for p in s_path]
    print(f"source  S bbox x {min(xs):.3f}..{max(xs):.3f}  y {min(ys):.3f}..{max(ys):.3f}"
          f"  ({len(s_path)} points)")

    report = build_ico(s_path, period)
    build_touch(s_path, period)

    print(f"\n{ICO}  {os.path.getsize(ICO) / 1024:.1f} KB, {len(report)} entries")
    print(f"{'size':>5} {'tier':>5} {'thin':>7} {'aperture':>9} {'period':>7} {'gap':>7}")
    bad = 0
    for size, f, tier in report:
        flags = "".join(" !" if f[k] < FLOORS[k] else "  " for k in ("thin", "aperture", "period", "gap"))
        bad += flags.count("!")
        print(f"{size:>5} {tier:>5} {f['thin']:>7.2f} {f['aperture']:>9.2f}"
              f"{f['period']:>7.2f} {f['gap']:>7.2f}  {flags.strip()}")
    print(f"floors: " + "  ".join(f"{k} >= {v:.2f}" for k, v in FLOORS.items()))
    print(f"\n{TOUCH}  {os.path.getsize(TOUCH) / 1024:.1f} KB")
    if bad:
        raise SystemExit(f"{bad} floor violation(s); the art is not shippable")


if __name__ == "__main__":
    main()
