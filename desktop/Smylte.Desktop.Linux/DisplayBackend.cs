namespace Smylte.Desktop;

/// Which display server to ask GDK for, decided before GDK has looked.
///
/// **Why this changed, and what it costs.** The client used to default to X11
/// outright. Three of the floating window's four properties — staying above
/// other windows, opening where it was left, keeping out of the task list — are
/// EWMH, and Wayland has no protocol an ordinary client can use for any of
/// them, so asking for X11 was how they were had. Under a real X11 session that
/// is free. Under a Wayland session it is not, and the bill lands on the other
/// 99% of the app:
///
///   * XWayland has ONE scale factor for the whole display. A desk with a HiDPI
///     laptop panel and an ordinary external monitor cannot be served by one
///     number, so one of the two screens is always wrong.
///   * Under fractional scaling the compositor renders an XWayland surface at
///     an integer scale and then bitmap-stretches it. Text does not re-hint; it
///     blurs.
///
/// And the old guard made this the default path rather than an edge case: it
/// only fell back when `DISPLAY` was unset, which on any Wayland session with
/// XWayland — the stock configuration everywhere — it never is. So essentially
/// every GNOME Wayland user ran the whole app through XWayland, permanently, to
/// buy three properties of one optional window.
///
/// The trade is now the other way round and the client says so where it costs
/// something: the page is told `canPin: false`, and Settings → Desktop's hint
/// names `"Backend": "x11"` as the way to have the pin back. A blurry main
/// window every second of every session is a worse default than a floating
/// window that cannot pin.
///
/// **Why `auto` returns null rather than naming Wayland.** An explicit
/// `GDK_BACKEND` disables GDK's own fallback — that is exactly why asking for
/// X11 on a session with no X server kills the process with "cannot open
/// display" rather than degrading. Leaving it unset lets GDK apply its own
/// priority order, which already prefers Wayland when `WAYLAND_DISPLAY` is set,
/// and keeps the fallback. Naming the backend we would have chosen anyway would
/// only remove the safety net.
///
/// Pure, and its own file, for the reason `DesktopEntryText` is: everything
/// around it in Program.cs must not so much as name a GirCore type before the
/// environment is set, and this is the one part of that decision a test can
/// actually pin.
internal static class DisplayBackend
{
    public const string X11 = "x11";
    public const string Wayland = "wayland";

    /// The value for `GDK_BACKEND`, or null to leave it unset and let GDK
    /// decide.
    ///
    /// `setting` is `Settings.Backend`. The two explicit values are honoured
    /// when the session can actually provide them and fall back to `auto`
    /// otherwise — symmetric, which it was not: `"x11"` was guarded on
    /// `DISPLAY` and `"wayland"` was guarded on nothing, so a hand-edited
    /// settings.json asking for Wayland on an X11-only session set a backend
    /// GDK could not open and the process died before drawing anything. That is
    /// the same failure the X11 guard exists to prevent, on the arm nobody
    /// tested.
    public static string? Choose(string? setting, string? waylandDisplay, string? display)
    {
        var hasWayland = !string.IsNullOrEmpty(waylandDisplay);
        var hasX11 = !string.IsNullOrEmpty(display);

        switch (setting?.Trim().ToLowerInvariant())
        {
            case X11 when hasX11:
                return X11;
            case Wayland when hasWayland:
                return Wayland;

            // Everything else is `auto`, and that deliberately includes a
            // requested backend this session cannot give. An unknown string is
            // here too: this is a hand-edited field with no UI, and a typo
            // should cost the preference rather than the window.
            default:
                // Wayland is reachable, so GDK will pick it and we want it to:
                // native per-monitor and fractional scaling, no XWayland blur.
                if (hasWayland) return null;
                // No Wayland but an X server: naming it changes nothing GDK
                // would not do, so say nothing and keep GDK's fallback.
                if (hasX11) return null;
                // Neither. Nothing here can help; NativeCheck and GDK's own
                // failure will say so far better than a guess would.
                return null;
        }
    }

    /// What the client will be talking to, for the log line. Not a capability
    /// test — `X11Window.Active` is, and it reads the display GDK actually
    /// opened. This is only what was asked for.
    public static string Describe(string? chosen, string? waylandDisplay, string? display) =>
        chosen
        ?? (!string.IsNullOrEmpty(waylandDisplay) ? "wayland (GDK's choice)"
            : !string.IsNullOrEmpty(display) ? "x11 (GDK's choice)"
            : "no display server found");
}
