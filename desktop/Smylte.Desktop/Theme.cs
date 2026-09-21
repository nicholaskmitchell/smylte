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

    /// Parse any colour the PAGE can legitimately put in `--bg`.
    ///
    /// `ParseHex` above is deliberately narrow and stays that way: it is the
    /// wire format, it is what the bridge's contract documents, and its tests
    /// pin the whitespace trap that made a wrong answer look plausible. This is
    /// the wider gate in front of it, and it exists because the narrow one was
    /// load-bearing for something it was never told about.
    ///
    /// **What went wrong.** The Appearance editor accepts any CSS colour for
    /// `--bg` — `AppearancePanel.tsx` says so outright, because the design
    /// system is authored in OKLCH — and `appearance.ts`'s `isColor` allows
    /// `oklch()`, `color-mix()`, four- and eight-digit hex and the rest. The
    /// page normalises through a canvas before sending, but a canvas hands back
    /// `color(srgb …)` for a colour that did not start in sRGB and `rgba(…)`
    /// for one with alpha. Neither is hex, so `ParseHex` returned null, the
    /// bridge read that as "the page has no colour to report" and handed the
    /// frame back to the system — which on Linux clears ONE display-wide
    /// stylesheet and so takes the header's colour, the float window's entire
    /// visible edge and the update strip's legibility with it. A user who
    /// picked a purple background got a client that looked half-themed and a
    /// float window with no border at all.
    ///
    /// The page-side fix (see `toHex` in desktop.ts) now reads the composited
    /// bytes back out of the canvas, so a current build sends hex whatever the
    /// author typed. This is the other half: the web build updates itself on
    /// every launch and the binary does not, so a client routinely runs a page
    /// older than itself — and one that has always sent `rgba()` for a
    /// translucent theme.
    ///
    /// Deliberately NOT a CSS colour parser. `oklch()`, `lab()` and `hsl()` are
    /// absent because converting them correctly is a colour-space library, the
    /// page already has one in the engine it is running on, and a host that got
    /// the conversion subtly wrong would paint a title bar a plausible WRONG
    /// colour — which is worse than the honest null this returns.
    public static Color? ParseColour(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        var text = value.Trim();
        return ParseHex(text) ?? ParseHexAlpha(text) ?? ParseFunctional(text);
    }

    /// `#RGBA` and `#RRGGBBAA`. Composited rather than truncated: the page is
    /// showing that colour over the canvas, which CSS says is white, so white
    /// is what the title bar has to match. Dropping the alpha instead would
    /// paint the frame a colour that is nowhere on screen.
    private static Color? ParseHexAlpha(string text)
    {
        var s = text.TrimStart('#');
        if (s.Length == 4) s = string.Concat(s[0], s[0], s[1], s[1], s[2], s[2], s[3], s[3]);
        if (s.Length != 8) return null;
        foreach (var c in s)
            if (!char.IsAsciiHexDigit(c)) return null;

        static int Byte(string s, int at) =>
            int.Parse(s.AsSpan(at, 2), System.Globalization.NumberStyles.HexNumber,
                System.Globalization.CultureInfo.InvariantCulture);

        return Flatten(Byte(s, 0), Byte(s, 2), Byte(s, 4), Byte(s, 6) / 255.0);
    }

    /// `rgb()`, `rgba()` and `color(srgb …)`, in the comma and the space-slash
    /// spellings CSS Color 4 allows for each.
    private static Color? ParseFunctional(string text)
    {
        var open = text.IndexOf('(');
        if (open <= 0 || !text.EndsWith(")", StringComparison.Ordinal)) return null;

        var name = text[..open].Trim().ToLowerInvariant();
        var inner = text[(open + 1)..^1];

        // Commas and the alpha slash are both just separators once the function
        // is known, because position is what carries the meaning in all three
        // of these. A nested function would break that — and cannot appear,
        // since none of the three take one.
        if (inner.Contains('(')) return null;
        var parts = inner
            .Replace(',', ' ')
            .Replace('/', ' ')
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        // `color()` names its space first, and sRGB is the only one worth
        // taking: it is what a canvas serialises to, and every other space
        // would need the conversion this method exists to refuse.
        //
        // The two spellings also differ in UNIT, which is the trap here.
        // `rgb()` writes channels 0-255; `color(srgb …)` writes them 0-1. A
        // percentage means the same thing in both. Getting this backwards
        // turns `color(srgb 0.5 0.5 0.5)` into near-black rather than grey —
        // a plausible wrong colour, which is the failure mode this whole file
        // is written against.
        var unitIsOne = false;
        if (name == "color")
        {
            if (parts.Length < 4) return null;
            // srgb-linear is a different transfer function, not a different
            // gamut, and treating it as srgb would be exactly the plausible
            // wrong answer this file refuses to give.
            if (parts[0].ToLowerInvariant() != "srgb") return null;
            parts = parts[1..];
            unitIsOne = true;
        }
        else if (name is not ("rgb" or "rgba"))
        {
            return null;
        }

        if (parts.Length is not (3 or 4)) return null;

        var channels = new int[3];
        for (var i = 0; i < 3; i++)
        {
            if (Channel(parts[i], unitIsOne) is not { } v) return null;
            channels[i] = (int)Math.Round(v);
        }

        var alpha = 1.0;
        if (parts.Length == 4)
        {
            // Alpha is 0-1 in every one of these spellings, and a percentage
            // is out of 100 as usual.
            if (Number(parts[3]) is not { } a) return null;
            alpha = parts[3].EndsWith("%", StringComparison.Ordinal) ? a / 100.0 : a;
        }

        return Flatten(channels[0], channels[1], channels[2], alpha);
    }

    /// One colour channel, as a 0-255 value.
    ///
    /// `unitIsOne` is the `color(srgb …)` convention, where a bare number runs
    /// 0-1 rather than 0-255. A percentage is 0-100 either way.
    private static double? Channel(string token, bool unitIsOne)
    {
        if (Number(token) is not { } value) return null;
        if (token.EndsWith("%", StringComparison.Ordinal)) return value / 100.0 * 255.0;
        return unitIsOne ? value * 255.0 : value;
    }

    /// One number, percent sign stripped if present. InvariantCulture, because
    /// the page always writes `0.5` and a host running under a comma-decimal
    /// locale would otherwise read that as 5 — a wrong colour rather than an
    /// error, on machines nobody testing this is likely to be using.
    private static double? Number(string token)
    {
        var text = token.EndsWith("%", StringComparison.Ordinal) ? token[..^1] : token;
        return double.TryParse(text, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var value)
            ? value
            : null;
    }

    /// What an opaque backdrop means here: CSS says the canvas beneath the root
    /// element is white, and `--bg` is the root's background — so white is what
    /// a translucent one is actually showing over, and what the title bar has
    /// to match. Named once rather than written at each use, because if that
    /// ever stops being true it has to stop being true in one place.
    private static readonly Color Backdrop = Color.FromArgb(0xFF, 0xFF, 0xFF);

    /// Clamp to the ranges CSS clamps to, and composite any alpha over the
    /// backdrop. Shares `Chrome.Over` so "what does translucent mean here" has
    /// one answer in the codebase rather than two.
    private static Color Flatten(int r, int g, int b, double alpha)
    {
        static int Clamp(int v) => v < 0 ? 0 : v > 255 ? 255 : v;
        var opaque = Color.FromArgb(Clamp(r), Clamp(g), Clamp(b));

        // Alpha is clamped BEFORE the blend, not after. CSS clamps it to 0-1,
        // and `Over` is a linear interpolation — so an out-of-range alpha does
        // not saturate, it extrapolates: `rgba(0, 0, 0, 5)` would compute
        // `5*0 - 4*255` and only then get clipped to black, and
        // `rgba(255, 255, 255, -1)` would overshoot the other way. Both are
        // plausible wrong colours rather than the clamped ones CSS specifies.
        //
        // The 1.0 case then short-circuits as a matter of exactness rather than
        // speed: `Over` at alpha 1 already returns `opaque`, and this is the
        // path every ordinary colour takes.
        alpha = alpha < 0.0 ? 0.0 : alpha > 1.0 ? 1.0 : alpha;
        return alpha >= 1.0 ? opaque : Chrome.Over(opaque, alpha, Backdrop);
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
