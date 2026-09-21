// Explicit, for the reason Theme.cs gives: the WinForms SDK adds System.Drawing
// to the implicit usings and a plain net8.0 project does not.
using System.Drawing;

namespace Smylte.Desktop;

/// The hairlines the HOST draws, and which of two jobs each one is doing.
///
/// Both clients paint chrome around a page whose colour they are told over the
/// bridge, and both need a line "a step off the background". That sounds like
/// one decision and is two, with opposite requirements — which is the bug this
/// file exists to fix. Until it did, one value served both, and it could only
/// be right for one of them:
///
///   Seam        CONTINUES the page. The bottom of the header bar and of the
///               update strip sit directly above `.topbar`, which draws its own
///               `border-bottom: 1px solid var(--rule)` twelve pixels lower. Two
///               lines, one job, so they have to look like one system — a seam
///               that shouts reads as the window and the page being different
///               surfaces, which is exactly what drawing our own title bar is
///               meant to avoid.
///   WindowEdge  SEPARATES the window from an unknown desktop. The floating
///               window is frameless and GTK gives it no shadow, so without a
///               visible edge it is a rectangle of page floating in whatever is
///               behind it. Here contrast is the whole point.
///
/// Measured, because the numbers are what made this worth splitting. The old
/// shared value was `Lift(0.35)` when dark and `Drop(0.15)` when light, and that
/// asymmetry is why it read as a bug only half the time:
///
///   theme             old shared edge      page's own --rule
///   :root dark        #616164  3.16:1      #2B2B30  1.39:1     2.28x too strong
///   workspace dark    #6A6A6A  3.25:1      #363636  1.45:1     2.23x too strong
///   :root light       #D5D4D2  1.42:1      #DDDCDA  1.31:1     1.08x, fine
///   workspace light   #D5D5D6  1.42:1      #E3E3E4  1.24:1     1.14x, fine
///
/// So on every dark theme the host's hairline was more than twice the weight of
/// every rule inside the page, and on every light one it matched. `Seam` below
/// reproduces the page's own construction instead of approximating it, which is
/// what makes it match on themes nobody has written yet.
///
/// Shared rather than duplicated for the reason Theme.cs is shared: two clients
/// answering the same question about the same `--bg` must not be able to answer
/// it differently. FloatForm.OnPaint used to derive its ring from
/// `ControlPaint.Light`/`Dark` gated on `Color.GetBrightness()` — HSL lightness,
/// where everything else in both clients uses `Theme.IsDark`'s relative
/// luminance. Those disagree on saturated mid-tones: for `#7B61FF` HSL says
/// light (so the ring went darker) and WCAG says dark (so the caption glyphs
/// went light), and a user with a purple theme got a window whose frame and
/// whose title text had drawn opposite conclusions from one colour.
public static class Chrome
{
    /// What the page composites its own `--rule` at. The shipped themes use
    /// 0.13 and 0.14 (`:root`) and 0.11 and 0.13 (the workspace preset); one
    /// value lands within a hundredth of a contrast point of all four, and a
    /// host that tried to track each theme's exact alpha would need the page to
    /// send a second colour it has no reason to send.
    private const double RuleAlpha = 0.13;

    /// A hairline that continues the page's own rule system.
    ///
    /// Built the way the page builds `--rule`: the theme's ink at low alpha over
    /// the background, rather than a shade of the background. That distinction
    /// is what makes it track — `--fg` and `--bg` move together in a custom
    /// theme, and a shade of `--bg` alone does not know that.
    public static Color Seam(Color background) =>
        Over(Theme.InkFor(background), RuleAlpha, background);

    /// A hairline that separates the window from whatever is behind it.
    ///
    /// A shade of the background rather than a contrasting colour, because a
    /// contrasting border would be a second decision nobody asked for — and
    /// deliberately stronger than `Seam`, because this one has no page to agree
    /// with. The asymmetry between the two directions is kept: lifting a
    /// near-black background needs more travel to become visible than dropping
    /// a near-white one does.
    public static Color WindowEdge(Color background) => Theme.IsDark(background)
        ? Color.FromArgb(Lift(background.R, 0.35), Lift(background.G, 0.35), Lift(background.B, 0.35))
        : Color.FromArgb(Drop(background.R, 0.15), Drop(background.G, 0.15), Drop(background.B, 0.15));

    /// `foreground` at `alpha` over an opaque `background`, the way a browser
    /// composites `rgba()` over the element beneath it.
    public static Color Over(Color foreground, double alpha, Color background)
    {
        static int Blend(int fg, int bg, double a) => Clamp((int)Math.Round(a * fg + (1 - a) * bg));
        return Color.FromArgb(
            Blend(foreground.R, background.R, alpha),
            Blend(foreground.G, background.G, alpha),
            Blend(foreground.B, background.B, alpha));
    }

    /// `#RRGGBB`, which is what both a GTK stylesheet and a COLORREF want to be
    /// built from. Upper case for no reason beyond matching what the CSS in
    /// HeaderChrome already emitted, so a diff of a rendered stylesheet is about
    /// colours rather than about case.
    public static string Hex(Color c) => $"#{c.R:X2}{c.G:X2}{c.B:X2}";

    private static int Lift(int v, double by) => Clamp((int)Math.Round(v + (255 - v) * by));
    private static int Drop(int v, double by) => Clamp((int)Math.Round(v * (1 - by)));

    /// Rounding at the ends of the range can land a hair outside it, and
    /// `Color.FromArgb` throws on a component it cannot fit in a byte — which
    /// would turn a cosmetic calculation into the one exception in a path whose
    /// whole premise is that it never throws.
    private static int Clamp(int v) => v < 0 ? 0 : v > 255 ? 255 : v;
}
