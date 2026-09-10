using System.Drawing;

namespace Smylte.Desktop;

/// Painting the window's own title bar to match the page.
///
/// **Why this is a stylesheet and not an API call.** On Windows the caption
/// strip belongs to the desktop window manager and `DwmSetWindowAttribute` is
/// the only supported way in — which is why the Windows client can only offer
/// an arbitrary colour on Windows 11, and reports that to the page as
/// `captionColour`. X11 and Wayland have nothing equivalent: no EWMH property
/// names a frame's colour, and no Wayland protocol does either. The only way to
/// honour the page's `--bg` at all is to stop asking the window manager for a
/// frame and draw one — a `GtkHeaderBar` set as the window's titlebar, which is
/// client-side decoration and is what every GNOME app already does.
///
/// The rejected alternative, stated because a reader will wonder: keep the
/// server-side frame and drop the feature on Linux. That would leave a window
/// whose title bar is the system grey above a page that is any colour the user
/// chose, on the one platform where the app is allowed to draw it properly.
///
/// So `captionColour` is `true` here, always, and unlike Windows it is not a
/// version test — the strip is ours on every desktop.
internal static class HeaderChrome
{
    /// One provider for the whole display, replaced in place. A second provider
    /// per repaint would stack: GTK keeps every one that is added, and the last
    /// wins only until something re-sorts them by priority.
    private static Gtk.CssProvider? _provider;

    /// Above the theme, below the user's own gtk.css. `GTK_STYLE_PROVIDER_PRIORITY_APPLICATION`.
    private const uint ApplicationPriority = 600;

    public static void Apply(Gdk.Display display, Color background)
    {
        var bg = Hex(background);
        var fg = Hex(Theme.InkFor(background));
        var edge = Hex(Edge(background));

        // `headerbar` rather than a class, so the rule reaches the strip GTK
        // builds for the window rather than a widget of ours. `box-shadow: none`
        // removes Adwaita's own bottom hairline, which reads as a seam against
        // a page that continues the same colour.
        Load(display, $$"""
            window.smylte { background: {{bg}}; }
            window.smylte headerbar {
                background: {{bg}};
                background-image: none;
                box-shadow: none;
                border-bottom: 1px solid {{edge}};
                color: {{fg}};
            }
            window.smylte headerbar label { color: {{fg}}; }
            .float-ring {
                background: {{bg}};
                box-shadow: inset 0 0 0 1px {{edge}};
            }
            """);
    }

    /// Hand the frame back to the theme, for before the page has said anything
    /// — the setup dialog, and the moment before the SPA boots.
    public static void Reset(Gdk.Display display) => Load(display, "");

    private static void Load(Gdk.Display display, string css)
    {
        try
        {
            if (_provider is null)
            {
                _provider = Gtk.CssProvider.New();
                Gtk.StyleContext.AddProviderForDisplay(display, _provider, ApplicationPriority);
            }
            // LoadFromData, not LoadFromString: the latter arrived in GTK 4.12
            // and this client is expected to run on whatever GTK the
            // distribution ships. The older call is deprecated in the headers
            // and still exported, which is the combination that keeps working.
            _provider.LoadFromData(css, -1);
        }
        catch (Exception)
        {
            // A stylesheet that will not parse costs the colour, not the window.
        }
    }

    /// The hairline around the floating window and under the header. The
    /// analogue of the Windows client's `ControlPaint.Light(bg, 0.35)` /
    /// `Dark(bg, 0.15)`: a shade of the background rather than a contrasting
    /// colour, because a contrasting border would be a second decision nobody
    /// asked for.
    private static Color Edge(Color c) => Theme.IsDark(c)
        ? Color.FromArgb(Lift(c.R, 0.35), Lift(c.G, 0.35), Lift(c.B, 0.35))
        : Color.FromArgb(Drop(c.R, 0.15), Drop(c.G, 0.15), Drop(c.B, 0.15));

    private static int Lift(int v, double by) => (int)Math.Round(v + (255 - v) * by);
    private static int Drop(int v, double by) => (int)Math.Round(v * (1 - by));

    private static string Hex(Color c) => $"#{c.R:X2}{c.G:X2}{c.B:X2}";
}
