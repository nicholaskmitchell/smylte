namespace Smylte.Desktop;

/// A monitor's rectangle, in whatever coordinate space the caller is working
/// in. Plain ints rather than `Gdk.Rectangle` or `Screen.WorkingArea` for the
/// reason FloatRing takes plain ints: both clients ask this question, neither
/// one's rectangle type can be linked into the other, and the arithmetic is the
/// part worth asserting.
public readonly record struct ScreenRect(int X, int Y, int Width, int Height);

/// Where the floating window is allowed to open, and the unit conversion that
/// question has to be asked in.
///
/// **The bug this exists to stop.** GTK4 and X11 do not measure in the same
/// pixels. Everything GTK hands back — `gtk_widget_get_width`,
/// `gdk_monitor_get_geometry` — is in LOGICAL pixels, already divided by the
/// window's scale factor. Everything Xlib takes and returns —
/// `XMoveWindow`, `XTranslateCoordinates` — is in DEVICE pixels. At scale 1
/// they are the same number, which is why this was invisible: X11 sessions run
/// at scale 1 unless someone sets `GDK_SCALE`, and setting `GDK_SCALE=2` is
/// precisely what a HiDPI user on X11 is told to do.
///
/// So on such a machine the float window recorded its position in device
/// pixels, then compared it against monitor geometry in logical ones. On a
/// two-monitor desk the saved position was typically double the coordinate
/// space it was checked against, so `OnAScreen` either rejected it outright —
/// "opens where you left it", one of the three things this client defaults to
/// X11 in order to have, silently not happening — or matched the wrong monitor
/// and put the window there.
///
/// Everything below is logical unless a name says otherwise, and X11Window is
/// the only place the two spaces meet.
public static class FloatPlacement
{
    /// How much of the window has to land on some monitor for the position to
    /// be worth restoring, in logical pixels on each axis. Enough to grab and
    /// drag back; not so much that a deliberately tucked-away window is moved.
    public const int MinVisible = 40;

    /// GTK's scale factor is an integer and at least 1. A zero or negative
    /// here would come from a call that failed rather than from a real display,
    /// and multiplying a position by it would put the window at the origin.
    public static int SaneScale(int scale) => scale < 1 ? 1 : scale;

    public static int ToDevice(int logical, int scale) => logical * SaneScale(scale);

    /// Rounding, not truncation. A window at device x=1537 on a scale-2 display
    /// is at logical 768.5; truncating every read biases the position one pixel
    /// left on each open-and-close cycle, which over a session walks the window
    /// across the screen.
    public static int ToLogical(int device, int scale)
    {
        var s = SaneScale(scale);
        // Symmetric about zero, because a window dragged off the left edge has
        // a negative device coordinate and must not round the wrong way.
        return (int)Math.Round(device / (double)s, MidpointRounding.AwayFromZero);
    }

    /// Would a window at this rectangle be reachable?
    ///
    /// The Windows client asks each screen's WORKING area; GTK4 removed
    /// `gdk_monitor_get_workarea`, so the Linux caller passes plain geometry.
    /// The difference is a window that could land under a panel rather than off
    /// the screen entirely — a nuisance the user can drag out of rather than a
    /// window they cannot reach.
    public static bool IsOnAScreen(
        int x, int y, int width, int height, IReadOnlyList<ScreenRect> monitors)
    {
        // A zero or negative size is not a rectangle anything can overlap, and
        // answering "yes" for one would restore a window to a position that
        // cannot be seen. Callers reach this with 0x0 when a window was never
        // opened.
        if (width <= 0 || height <= 0) return false;

        foreach (var m in monitors)
        {
            if (m.Width <= 0 || m.Height <= 0) continue;
            var overlapX = Math.Min(x + width, m.X + m.Width) - Math.Max(x, m.X);
            var overlapY = Math.Min(y + height, m.Y + m.Height) - Math.Max(y, m.Y);
            if (overlapX >= MinVisible && overlapY >= MinVisible) return true;
        }
        return false;
    }
}
