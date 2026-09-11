// Explicit, not implicit. The WinForms SDK adds System.Drawing to the implicit
// usings and a plain net8.0 project does not, so a file linked into both has to
// say so itself or it compiles on Windows and fails everywhere else.
using System.Drawing;

namespace Smylte.Desktop;

/// Reading the colour the web app reports over the bridge, and deciding what is
/// legible on it.
///
/// Split out of WindowChrome so both clients can share it. Everything in
/// WindowChrome ITSELF is `dwmapi.dll` — a Linux client has no use for any of
/// it — but these two functions are neither Windows nor GTK: one parses the hex
/// the page sends, and the other answers "is this dark?" the way WCAG defines
/// it. Duplicating them into a second client would mean the two windows could
/// disagree about whether the same `--bg` needs light or dark chrome, which is
/// the kind of divergence nobody would notice until a screenshot looked wrong.
///
/// `System.Drawing.Color` is a plain struct and is available everywhere; only
/// `System.Drawing.Common`'s GDI+ types (Icon, Bitmap, Graphics) are
/// Windows-only. That is why this file can be linked into a `net8.0` project
/// and `IconLibrary.Load` cannot.
internal static class Theme
{
    /// Parse `#RGB` / `#RRGGBB` from the web side. Returns null for anything
    /// else — the bridge takes whatever the page sends, and the page's --bg can
    /// be a user-authored theme value.
    public static Color? ParseHex(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex)) return null;
        var s = hex.Trim().TrimStart('#');
        if (s.Length == 3) s = string.Concat(s[0], s[0], s[1], s[1], s[2], s[2]);
        if (s.Length != 6) return null;

        // Every character checked, because `NumberStyles.HexNumber` includes
        // AllowLeadingWhite and AllowTrailingWhite: `"#  FFFF"` survives the
        // Trim (the space is AFTER the hash), passes the length test at six,
        // and parses as 0x00FFFF. The result was a colour the page never asked
        // for rather than the null this documents — silently plausible, which
        // is the worst shape for a wrong answer.
        foreach (var c in s)
            if (!char.IsAsciiHexDigit(c)) return null;

        if (!int.TryParse(s, System.Globalization.NumberStyles.HexNumber,
                System.Globalization.CultureInfo.InvariantCulture, out var v))
            return null;
        return Color.FromArgb((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF);
    }

    /// Relative luminance, sRGB linearised — the same test caption text has to
    /// pass. Callers compare against 0.5, which is deliberately blunt: on
    /// Windows the only decision it drives is black-or-white caption glyphs and
    /// DWM offers nothing in between, and on Linux it picks between two ink
    /// colours for the header bar.
    public static double Luminance(Color c)
    {
        static double Channel(int v)
        {
            var s = v / 255.0;
            return s <= 0.03928 ? s / 12.92 : Math.Pow((s + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * Channel(c.R) + 0.7152 * Channel(c.G) + 0.0722 * Channel(c.B);
    }

    /// Is `background` dark enough to need light text on it?
    public static bool IsDark(Color background) => Luminance(background) < 0.5;

    /// The two ink colours the app itself uses, so chrome drawn by the host
    /// matches chrome drawn by the page. `#0E0E0C` is the app's --fg and
    /// `#F4F1E8` its paper; neither is pure black or pure white, and that is a
    /// deliberate choice of the design system rather than an accident here.
    public static Color InkFor(Color background) => IsDark(background)
        ? Color.FromArgb(0xF4, 0xF1, 0xE8)
        : Color.FromArgb(0x0E, 0x0E, 0x0C);
}
