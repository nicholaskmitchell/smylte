using System.Runtime.InteropServices;

namespace Smylte.Desktop;

/// The three things the floating window needs and only X11 can give.
///
/// GTK4 removed `gtk_window_set_keep_above`, `set_skip_taskbar_hint` and
/// `gtk_window_move` from every backend — not because X11 stopped supporting
/// them, but because Wayland never did, and the toolkit will not carry an API
/// that works on one backend. Under Wayland that is final: xdg-shell has no
/// request to stay above other windows, no way to read or set an absolute
/// position, and no way to stay out of the task list; GNOME implements no
/// extension that would add them, and the one that exists elsewhere
/// (wlr-layer-shell) is not something Mutter has ever spoken.
///
/// Under X11 all three are ordinary EWMH, which every window manager has
/// honoured for twenty years — so the client asks for X11 by default and does
/// them here.
///
/// Declared by hand rather than pulled in as a binding, for the reason
/// ShellShortcut.cs gives for its COM: it is five functions and two atoms, and
/// the alternative is a dependency. GirCore publishes no GdkX11 package at all,
/// so there is no binding to prefer even if one were wanted.
///
/// Every call is guarded and every failure is silent. A floating window that
/// does not float is a shortfall; a client that will not start is not.
internal static class X11Window
{
    // GDK's X11 accessors live in libgtk-4.so.1 alongside the rest of GDK —
    // there is no separate libgdk-4.
    private const string GtkSo = "libgtk-4.so.1";
    private const string X11So = "libX11.so.6";

    [DllImport(GtkSo)] private static extern IntPtr gdk_x11_display_get_xdisplay(IntPtr display);
    [DllImport(GtkSo)] private static extern ulong gdk_x11_surface_get_xid(IntPtr surface);

    [DllImport(X11So)] private static extern IntPtr XInternAtom(IntPtr display, string name, bool onlyIfExists);
    [DllImport(X11So)] private static extern ulong XDefaultRootWindow(IntPtr display);
    [DllImport(X11So)] private static extern int XSendEvent(
        IntPtr display, ulong window, bool propagate, long eventMask, ref XEvent send);
    [DllImport(X11So)] private static extern int XMoveWindow(IntPtr display, ulong window, int x, int y);
    [DllImport(X11So)] private static extern int XTranslateCoordinates(
        IntPtr display, ulong source, ulong destination,
        int sourceX, int sourceY, out int destinationX, out int destinationY, out ulong child);
    [DllImport(X11So)] private static extern int XFlush(IntPtr display);

    private const int ClientMessage = 33;
    private const long SubstructureRedirectMask = 1L << 20;
    private const long SubstructureNotifyMask = 1L << 19;

    /// `_NET_WM_STATE` actions, from the EWMH spec.
    private const long Remove = 0, Add = 1;

    /// An XEvent is a union of 24 longs. The fields below are the ClientMessage
    /// arm; `Size = 192` pads the rest, because Xlib reads the whole union and a
    /// struct that stopped at the last named field would be an overread.
    [StructLayout(LayoutKind.Sequential, Size = 192)]
    private struct XEvent
    {
        public int Type;
        public IntPtr Serial;
        public int SendEvent;
        public IntPtr Display;
        public ulong Window;
        public IntPtr MessageType;
        public int Format;
        public long Data0, Data1, Data2, Data3, Data4;
    }

    /// True when this process is actually talking X11. Set once, from the
    /// backend the client asked GDK for in Program.Main — the only value that
    /// can be right, because GDK is never asked to choose.
    public static bool Active { get; set; }

    /// Whether the window stays above other windows.
    public static void SetAbove(Gtk.Window window, bool above) =>
        SetState(window, above, "_NET_WM_STATE_ABOVE");

    /// Whether the window appears in the task list. The floating window is a
    /// second view of an app that already has an entry; two would be wrong.
    /// SKIP_TASKBAR only — deliberately NOT SKIP_PAGER, so Alt-Tab and the
    /// window switcher still list it, which is how it is reached when it falls
    /// behind. That is the same split WinForms makes for `ShowInTaskbar`.
    public static void SetSkipTaskbar(Gtk.Window window, bool skip) =>
        SetState(window, skip, "_NET_WM_STATE_SKIP_TASKBAR");

    private static void SetState(Gtk.Window window, bool on, string atom)
    {
        try
        {
            if (!Active) return;
            if (!Handles(window, out var display, out var xid)) return;

            var message = new XEvent
            {
                Type = ClientMessage,
                Window = xid,
                MessageType = XInternAtom(display, "_NET_WM_STATE", false),
                Format = 32,
                Data0 = on ? Add : Remove,
                Data1 = (long)XInternAtom(display, atom, false),
                Data2 = 0,
                // Source indication 1 = "a normal application", which is what
                // the spec asks a client to say and what some window managers
                // check before honouring the request at all.
                Data3 = 1,
            };

            // To the ROOT window, not to our own: the window manager is the
            // recipient, and it is listening for substructure messages there.
            XSendEvent(display, XDefaultRootWindow(display), false,
                SubstructureRedirectMask | SubstructureNotifyMask, ref message);
            XFlush(display);
        }
        catch (Exception) { /* no X11, no libX11, an unmapped window */ }
    }

    /// Put the window at an absolute screen position.
    public static void Move(Gtk.Window window, int x, int y)
    {
        try
        {
            if (!Active) return;
            if (!Handles(window, out var display, out var xid)) return;
            XMoveWindow(display, xid, x, y);
            XFlush(display);
        }
        catch (Exception) { /* see above */ }
    }

    /// Where the window currently is, or null when that cannot be answered —
    /// which under Wayland is always, and is why the caller keeps whatever an
    /// earlier X11 session recorded rather than overwriting it with a guess.
    public static (int X, int Y)? Position(Gtk.Window window)
    {
        try
        {
            if (!Active) return null;
            if (!Handles(window, out var display, out var xid)) return null;
            var root = XDefaultRootWindow(display);
            if (XTranslateCoordinates(display, xid, root, 0, 0, out var x, out var y, out _) == 0)
                return null;
            return (x, y);
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static bool Handles(Gtk.Window window, out IntPtr display, out ulong xid)
    {
        display = IntPtr.Zero;
        xid = 0;

        var surface = window.GetSurface();
        if (surface is null) return false;      // not realised yet

        display = gdk_x11_display_get_xdisplay(window.GetDisplay().Handle.DangerousGetHandle());
        if (display == IntPtr.Zero) return false;

        xid = gdk_x11_surface_get_xid(surface.Handle.DangerousGetHandle());
        return xid != 0;
    }
}
