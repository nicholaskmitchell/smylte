using System.Drawing;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// `Theme.ParseColour` — the gate in front of `ParseHex`, and the thing that
/// stops a legitimate custom theme taking the window's chrome apart.
///
/// The failure it closes is worth restating, because it does not look like a
/// parser bug from either end. The Appearance editor accepts any CSS colour for
/// `--bg` by design. The page normalises through a canvas. A canvas serialises a
/// non-sRGB colour as `color(srgb …)` and a translucent one as `rgba(…)`. Only
/// `ParseHex` read the result, so both came back null — and null means "hand the
/// frame back to the system", which on Linux clears one display-wide stylesheet
/// and takes the header colour, the update strip's legibility and the floating
/// window's only visible border with it.
public sealed class ColourParseTests
{
    private static void Reads(string value, int r, int g, int b)
    {
        var colour = Theme.ParseColour(value);
        Assert.NotNull(colour);
        Assert.Equal(Color.FromArgb(r, g, b).ToArgb(), colour!.Value.ToArgb());
    }

    [Theory]
    [InlineData("#0C0C10", 0x0C, 0x0C, 0x10)]
    [InlineData("#abc", 0xAA, 0xBB, 0xCC)]
    [InlineData("  #C75A26  ", 0xC7, 0x5A, 0x26)]
    public void Everything_ParseHex_read_it_still_reads(string value, int r, int g, int b) =>
        Reads(value, r, g, b);

    [Theory]
    [InlineData("rgb(12, 12, 16)", 12, 12, 16)]
    [InlineData("rgb(12,12,16)", 12, 12, 16)]
    [InlineData("rgb(12 12 16)", 12, 12, 16)]
    [InlineData("RGB(12, 12, 16)", 12, 12, 16)]
    [InlineData("rgba(12, 12, 16, 1)", 12, 12, 16)]
    [InlineData("rgb(12 12 16 / 1)", 12, 12, 16)]
    [InlineData("rgb(100%, 0%, 0%)", 255, 0, 0)]
    public void Reads_the_rgb_forms_a_canvas_hands_back(string value, int r, int g, int b) =>
        Reads(value, r, g, b);

    [Theory]
    // What WebKit and Chromium serialise an oklch() or lab() colour to once it
    // has been through a canvas. This is the exact shape that used to come back
    // null and blank the stylesheet.
    [InlineData("color(srgb 0 0 0)", 0, 0, 0)]
    [InlineData("color(srgb 1 1 1)", 255, 255, 255)]
    [InlineData("color(srgb 0.5 0.5 0.5)", 128, 128, 128)]
    [InlineData("color(srgb 0.047 0.047 0.063)", 12, 12, 16)]
    public void Reads_the_srgb_colour_function(string value, int r, int g, int b) =>
        Reads(value, r, g, b);

    [Fact]
    public void Composites_alpha_over_white_rather_than_dropping_it()
    {
        // Black at half alpha is mid grey on screen, and mid grey is what the
        // title bar has to be for the frame to match the page. Truncating to
        // the RGB would paint it black — a colour that is nowhere on screen.
        //
        // The three are one off each other on purpose, and the arithmetic is
        // the point: a hex alpha byte is n/255, so `80` is 0.502 rather than
        // 0.5 and composites to 127, while the decimal 0.5 composites to
        // exactly 127.5 and rounds to 128. `88` is 0.533, giving 119.
        Reads("#00000080", 127, 127, 127);
        Reads("rgba(0, 0, 0, 0.5)", 128, 128, 128);
        Reads("#0008", 119, 119, 119);
        // Fully transparent resolves to the backdrop, not to the channel values.
        Reads("rgba(0, 0, 0, 0)", 255, 255, 255);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("rebeccapurple")]                 // a keyword: the page normalises these
    [InlineData("oklch(0.2 0.02 250)")]           // see below
    [InlineData("lab(50% 40 59.5)")]
    [InlineData("hsl(120 50% 50%)")]
    [InlineData("color-mix(in oklch, red 50%, blue)")]
    [InlineData("color(display-p3 1 0 0)")]       // a real colour, a gamut we cannot convert
    [InlineData("color(srgb-linear 1 1 1)")]      // a different transfer function
    [InlineData("rgb(12, 12)")]
    [InlineData("rgb(12, 12, 16, 1, 1)")]
    [InlineData("rgb(a, b, c)")]
    [InlineData("rgb(12, 12, 16")]
    [InlineData("#12345")]
    [InlineData("#gggggggg")]
    public void Refuses_what_it_cannot_convert_exactly(string? value)
    {
        // Deliberately NOT a CSS colour library. Converting OKLCH or Lab
        // correctly is a colour-space implementation; the page already has one
        // in the engine it is running on and now uses it (see `toHex`), and a
        // host that got the conversion subtly wrong would paint a title bar a
        // plausible WRONG colour. Null is documented to hand the frame back,
        // which is the honest answer.
        Assert.Null(Theme.ParseColour(value));
    }

    [Fact]
    public void Clamps_rather_than_throwing_on_out_of_range_components()
    {
        // CSS clamps these; `Color.FromArgb` throws on them. A theme with a
        // typo must not be the one thing in this path that takes the process
        // down.
        Reads("rgb(300, -20, 16)", 255, 0, 16);
        Reads("color(srgb 2 -1 0.5)", 255, 0, 128);

        // Alpha too. Not a bug that shipped — the two early-outs it replaced
        // covered these — but the invariant is worth pinning, because the
        // blend is a linear interpolation and therefore EXTRAPOLATES rather
        // than saturating: anyone who later routes an out-of-range alpha
        // straight into `Chrome.Over` gets 5*0 - 4*255, not the opaque black
        // CSS specifies.
        Reads("rgba(0, 0, 0, 5)", 0, 0, 0);
        Reads("rgba(0, 0, 0, -1)", 255, 255, 255);
        Reads("rgba(255, 255, 255, -3)", 255, 255, 255);
    }

    [Fact]
    public void Reads_a_decimal_point_under_a_comma_decimal_locale()
    {
        // The page always writes `0.5`. A host running under de-DE with
        // current-culture parsing would read that as 5 and clamp the alpha to
        // opaque — a wrong colour rather than an error, on machines nobody
        // testing this is likely to be using.
        var original = System.Globalization.CultureInfo.CurrentCulture;
        try
        {
            System.Globalization.CultureInfo.CurrentCulture =
                new System.Globalization.CultureInfo("de-DE");
            Reads("rgba(0, 0, 0, 0.5)", 128, 128, 128);
            Reads("color(srgb 0.5 0.5 0.5)", 128, 128, 128);
        }
        finally
        {
            System.Globalization.CultureInfo.CurrentCulture = original;
        }
    }

    [Fact]
    public void ParseHex_is_unchanged_and_still_narrow()
    {
        // The wire format's own contract, restated here because ParseColour
        // sits in front of it now: widening the narrow one instead of adding a
        // gate would have taken the whitespace trap its tests pin with it.
        Assert.Null(Theme.ParseHex("rgb(12, 12, 16)"));
        Assert.Null(Theme.ParseHex("#00000080"));
        Assert.Null(Theme.ParseHex("#  FFFF"));
    }
}
