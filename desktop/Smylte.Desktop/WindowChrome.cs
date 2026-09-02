using System.Runtime.InteropServices;

namespace Smylte.Desktop;

/// Paints the window's caption bar — the strip carrying minimise, maximise and
/// close — to match the theme the web app is showing.
///
/// WinForms does not own that strip; the desktop window manager does, and the
/// only supported way to influence it is DwmSetWindowAttribute. What that buys
/// depends on the Windows build, and the difference is worth knowing rather than
/// discovering:
///
///   Windows 11 22000+   DWMWA_CAPTION_COLOR takes an arbitrary COLORREF, so the
///                       caption can literally be the app's own --bg token, and
///                       a custom theme carries through to the frame.
///   Windows 10 1809+    Only DWMWA_USE_IMMERSIVE_DARK_MODE, i.e. light or dark.
///                       A custom --bg is honoured as whichever of the two it is
///                       nearer, which is the whole of what the OS offers.
///
/// Both calls are attempted and both are allowed to fail: an unsupported
/// attribute returns a failure HRESULT rather than throwing, older builds
/// numbered the dark-mode attribute 19 instead of 20, and none of this is worth
/// a crash. A window with the stock caption is a cosmetic shortfall.
internal static class WindowChrome
{
    private const int DwmwaUseImmersiveDarkMode = 20;
    private const int DwmwaUseImmersiveDarkModePre20H1 = 19;
    private const int DwmwaBorderColor = 34;
    private const int DwmwaCaptionColor = 35;
    private const int DwmwaTextColor = 36;

    /// DWM reads and writes this as "default", i.e. hand the frame back to the OS.
    private const uint ColorDefault = 0xFFFFFFFF;

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    /// Apply `background` to the caption, choosing readable caption text.
    ///
    /// `background` is the app's own --bg, which index.html already computes
    /// before first paint for the mobile browser chrome — so the value crossing
    /// the bridge is the same one the page is painted with, not an approximation.
    public static void Apply(IntPtr hwnd, Color background)
    {
        if (hwnd == IntPtr.Zero) return;

        // Relative luminance, the same test the caption text has to pass. 0.5 is
        // deliberately blunt: the only decision it drives is black-or-white
        // caption glyphs, and DWM offers nothing in between.
        var dark = Luminance(background) < 0.5;

        var flag = dark ? 1 : 0;
        if (DwmSetWindowAttribute(hwnd, DwmwaUseImmersiveDarkMode, ref flag, sizeof(int)) != 0)
            DwmSetWindowAttribute(hwnd, DwmwaUseImmersiveDarkModePre20H1, ref flag, sizeof(int));

        // Windows 11 only. Failure here is the Windows 10 path and is expected:
        // the dark-mode flag above has already done what that build supports.
        var caption = ToColorRef(background);
        DwmSetWindowAttribute(hwnd, DwmwaCaptionColor, ref caption, sizeof(int));

        var text = ToColorRef(dark ? Color.FromArgb(0xF4, 0xF1, 0xE8) : Color.FromArgb(0x0E, 0x0E, 0x0C));
        DwmSetWindowAttribute(hwnd, DwmwaTextColor, ref text, sizeof(int));

        // The 1px frame, so the window does not sit in a light hairline on a
        // dark desktop. Same colour as the caption: a contrasting border would
        // be a second decision nobody asked for.
        DwmSetWindowAttribute(hwnd, DwmwaBorderColor, ref caption, sizeof(int));
    }

    /// Hand the caption back to Windows, for when the app has no theme to apply
    /// yet — before the SPA has loaded, and in SetupForm, which shows no page.
    public static void Reset(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return;
        var value = unchecked((int)ColorDefault);
        DwmSetWindowAttribute(hwnd, DwmwaCaptionColor, ref value, sizeof(int));
        DwmSetWindowAttribute(hwnd, DwmwaTextColor, ref value, sizeof(int));
        DwmSetWindowAttribute(hwnd, DwmwaBorderColor, ref value, sizeof(int));
    }

    /// COLORREF is 0x00BBGGRR — byte-reversed from the 0xRRGGBB everyone writes
    /// CSS in, and getting it backwards yields a plausible wrong colour rather
    /// than an error.
    private static int ToColorRef(Color c) => c.R | (c.G << 8) | (c.B << 16);

    private static double Luminance(Color c)
    {
        static double Channel(int v)
        {
            var s = v / 255.0;
            return s <= 0.03928 ? s / 12.92 : Math.Pow((s + 0.055) / 1.055, 2.4);
        }
        return 0.2126 * Channel(c.R) + 0.7152 * Channel(c.G) + 0.0722 * Channel(c.B);
    }

    /// Parse `#RGB` / `#RRGGBB` from the web side. Returns null for anything
    /// else — the bridge takes whatever the page sends, and the page's --bg can
    /// be a user-authored theme value.
    public static Color? ParseHex(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex)) return null;
        var s = hex.Trim().TrimStart('#');
        if (s.Length == 3) s = string.Concat(s[0], s[0], s[1], s[1], s[2], s[2]);
        if (s.Length != 6 || !int.TryParse(s, System.Globalization.NumberStyles.HexNumber,
                System.Globalization.CultureInfo.InvariantCulture, out var v))
            return null;
        return Color.FromArgb((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF);
    }
}
