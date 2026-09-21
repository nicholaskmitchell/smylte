using System.Drawing;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The hairlines the host draws, which until now could not be asserted at all.
///
/// They lived in `HeaderChrome`, which dlopens GTK, and in `FloatForm.OnPaint`,
/// which needs a message loop — so two clients derived the same line from two
/// different formulas gated on two different brightness tests, and nothing could
/// notice. That is the structural half of the bug; these are the arithmetic
/// half, and the numbers below are the ones measured against the real
/// stylesheet.
public sealed class ChromeTests
{
    private static Color Hex(string hex) => Theme.ParseHex(hex)!.Value;

    /// Relative luminance contrast, the WCAG ratio — the same arithmetic
    /// `Theme.Luminance` does, expressed the way a designer states a result.
    private static double Contrast(Color a, Color b)
    {
        var la = Theme.Luminance(a);
        var lb = Theme.Luminance(b);
        return (Math.Max(la, lb) + 0.05) / (Math.Min(la, lb) + 0.05);
    }

    /// What the PAGE draws its own rules at, restated here from tokens.css so
    /// the assertion is against the real target rather than against Seam's own
    /// implementation. `--rule` is the theme's ink at low alpha over `--bg`.
    private static Color PageRule(string bg, string ink, double alpha) =>
        Chrome.Over(Hex(ink), alpha, Hex(bg));

    public static TheoryData<string, string, double> ShippedThemes() => new()
    {
        // bg          --fg of that theme   --rule's alpha
        { "#FBFAF7", "#14131A", 0.13 },   // :root, light
        { "#0C0C10", "#ECEAF2", 0.14 },   // :root, dark
        { "#FBFBFC", "#1D1D1F", 0.11 },   // workspace, light
        { "#191919", "#F5F5F5", 0.13 },   // workspace, dark
    };

    [Theory]
    [MemberData(nameof(ShippedThemes))]
    public void Seam_matches_the_weight_of_the_page_rule_it_sits_against(
        string bg, string ink, double alpha)
    {
        var background = Hex(bg);
        var seam = Contrast(Chrome.Seam(background), background);
        var page = Contrast(PageRule(bg, ink, alpha), background);

        // The header bar's bottom border and `.topbar`'s sit twelve pixels
        // apart. Within a tenth of a contrast point reads as one line drawn
        // twice; the old shared value was 2.3x the page's on both dark themes,
        // which read as two different systems meeting.
        Assert.True(Math.Abs(seam - page) < 0.1,
            $"{bg}: seam {seam:F2}:1 against the page's {page:F2}:1");
    }

    [Theory]
    [MemberData(nameof(ShippedThemes))]
    public void WindowEdge_stays_visible_against_its_own_background(
        string bg, string ink, double alpha)
    {
        _ = ink; _ = alpha;
        var background = Hex(bg);

        // The floating window is frameless and GTK gives it no shadow, so this
        // hairline is the only thing separating it from the desktop. It has no
        // page to agree with and is allowed — required — to be louder than the
        // seam.
        Assert.True(Contrast(Chrome.WindowEdge(background), background) > 1.3);
        Assert.True(
            Contrast(Chrome.WindowEdge(background), background)
            > Contrast(Chrome.Seam(background), background),
            $"{bg}: the window edge must not be quieter than the page seam");
    }

    [Fact]
    public void Seam_and_WindowEdge_are_different_decisions()
    {
        // The whole point of the split. One value served both jobs and could
        // only be right for one of them; if these ever collapse back into the
        // same number on a dark theme, that regression is back.
        var dark = Hex("#0C0C10");
        Assert.NotEqual(Chrome.Seam(dark).ToArgb(), Chrome.WindowEdge(dark).ToArgb());
    }

    [Fact]
    public void WindowEdge_reads_darkness_the_same_way_the_caption_does()
    {
        // The divergence this replaced: FloatForm gated its ring on
        // `Color.GetBrightness()` (HSL lightness) while WindowChrome.Apply
        // picked caption glyphs with `Theme.IsDark` (WCAG luminance). On a
        // saturated mid-tone those disagree, so one window drew a darker ring
        // and lighter text from one colour.
        var purple = Hex("#7B61FF");
        Assert.True(Theme.IsDark(purple));                 // luminance says dark
        Assert.True(purple.GetBrightness() > 0.5f);        // HSL says light

        // Dark, so the edge lifts. Under the old test it dropped.
        Assert.True(Theme.Luminance(Chrome.WindowEdge(purple)) > Theme.Luminance(purple));
    }

    [Theory]
    [InlineData("#000000")]
    [InlineData("#FFFFFF")]
    public void Neither_hairline_throws_at_the_ends_of_the_range(string bg)
    {
        // Rounding at 0 and 255 can land a component just outside the byte
        // range, and `Color.FromArgb` throws on one that does — which would put
        // the one exception in a path whose whole premise is that it never
        // throws.
        var background = Hex(bg);
        Assert.NotEqual(0, Chrome.Seam(background).ToArgb());
        Assert.NotEqual(0, Chrome.WindowEdge(background).ToArgb());
    }

    [Fact]
    public void Over_composites_the_way_a_browser_does()
    {
        var black = Color.FromArgb(0, 0, 0);
        var white = Color.FromArgb(255, 255, 255);
        Assert.Equal(white.ToArgb(), Chrome.Over(black, 0.0, white).ToArgb());
        Assert.Equal(black.ToArgb(), Chrome.Over(black, 1.0, white).ToArgb());
        Assert.Equal(Color.FromArgb(128, 128, 128).ToArgb(),
            Chrome.Over(black, 0.5, white).ToArgb());
    }

    [Fact]
    public void Hex_round_trips_through_the_parser_both_clients_use()
    {
        foreach (var hex in new[] { "#FBFAF7", "#0C0C10", "#000000", "#FFFFFF", "#7B61FF" })
            Assert.Equal(hex, Chrome.Hex(Theme.ParseHex(hex)!.Value));
    }
}
