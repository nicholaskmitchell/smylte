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
/// version test — the strip is ours on every desktop that will let us have it.
///
/// **What that costs, which is the other half of the same fact.** A window that
/// declines a server-side frame declines ALL of it. The window manager's
/// decoration theme — KWin's Aurorae buttons, their icons and metrics, the
/// frame, the window icon it would draw in the caption — is drawn by the window
/// manager for windows it decorates, and this is not one of them. Someone who
/// has themed their decorations sees none of it here, and there is no property
/// on either display server that would let us have the frame and the colour at
/// once. (KWin reads `_KDE_NET_WM_COLOR_SCHEME`, an X11 property naming a
/// Plasma `.colors` file, and tints its decoration from it — KDE on X11 only,
/// needing raw XChangeProperty interop and a generated colour-scheme file per
/// background the page reports. Stated so it is not rediscovered as an option.)
///
/// The two are exclusive, so `Settings.SystemTitleBar` makes it a choice rather
/// than a decision baked into the build: with it on, MainWindow never calls
/// SetTitlebar and everything below still applies — the window's own
/// background, the float ring, the update strip — because only the header-bar
/// rules stop matching anything.
///
/// **That last clause used to be false, and the class below is why it is true
/// now.** The rules were written against the bare `headerbar` node, which is
/// the CSS name of every GtkHeaderBar in the tree — including the one GTK
/// BUILDS ITSELF for a decorated window whose compositor draws no frame. That
/// is not a corner case: it is GNOME on Wayland, the single commonest desktop
/// this client runs on. So `SystemTitleBar: true` there stopped the app
/// supplying a header bar and then painted GTK's replacement in the app's own
/// colours anyway — the setting appeared to do nothing, and the one
/// configuration it was written for was the one it silently failed in. Under
/// X11 with a window manager that draws real frames there IS no such widget,
/// so it worked, which is how it went unnoticed. The rules now carry the class
/// MainWindow puts on the strip it owns, so they can only reach ours.
internal static class HeaderChrome
{
    /// On the GtkHeaderBar this client sets as its own titlebar, and on nothing
    /// else. See the note above: the bare node name also matches the one GTK
    /// synthesises when the user has asked for the system's.
    public const string HeaderClass = "smylte-header";

    /// One provider for the whole display, replaced in place. A second provider
    /// per repaint would stack: GTK keeps every one that is added, and the last
    /// wins only until something re-sorts them by priority.
    private static Gtk.CssProvider? _provider;

    /// Above the theme, below the user's own gtk.css. `GTK_STYLE_PROVIDER_PRIORITY_APPLICATION`.
    private const uint ApplicationPriority = 600;

    public static void Apply(Gdk.Display display, Color background)
    {
        var bg = Chrome.Hex(background);
        var fg = Chrome.Hex(Theme.InkFor(background));

        // TWO hairlines, not one, and which is which is the whole of Chrome.cs.
        //
        // `seam` is for the lines that CONTINUE the page: the bottom of the
        // header bar and of the update strip both sit directly above
        // `.topbar`, which draws `border-bottom: 1px solid var(--rule)` twelve
        // pixels lower. One value served both jobs before, and on every dark
        // theme it came out at 3.2:1 against the background where the page's
        // own rules are 1.4:1 — a bright grey line above a barely-there one,
        // which is what "the borders are inconsistent" looks like from the
        // outside.
        //
        // `edge` is for the float window's ring, which has no page to agree
        // with: it is a frameless window on an unknown desktop, and there
        // contrast is the point rather than the problem.
        var seam = Chrome.Hex(Chrome.Seam(background));
        var edge = Chrome.Hex(Chrome.WindowEdge(background));

        // `headerbar.smylte-header`, NOT the bare node: see the class note at
        // the top of this file. `box-shadow: none` removes Adwaita's own bottom
        // hairline, which would otherwise sit on top of the seam and double it.
        Load(display, $$"""
            window.smylte { background: {{bg}}; }
            window.smylte headerbar.{{HeaderClass}} {
                background: {{bg}};
                background-image: none;
                box-shadow: none;
                border-bottom: 1px solid {{seam}};
                color: {{fg}};
            }
            window.smylte headerbar.{{HeaderClass}} label { color: {{fg}}; }
            .float-ring {
                background: {{bg}};
                box-shadow: inset 0 0 0 1px {{edge}};
                padding: 6px;
            }
            /* The update strip. Without these three lines it had a class and
               no rule anywhere, so it drew the GTK theme's own label colour on
               top of the page's --bg — black on near-black under every dark
               theme, which is the state the strip is most likely to be seen
               in. It is chrome the host draws, so it is painted from the same
               two colours the header bar is. */
            .smylte-banner {
                background: {{bg}};
                color: {{fg}};
                border-bottom: 1px solid {{seam}};
                padding: 6px;
            }
            .smylte-banner label { color: {{fg}}; }
            """);
    }

    /// Hand the COLOUR back to the theme, for before the page has said anything
    /// — the moment before the SPA boots, and whenever the page reports a
    /// background the host cannot read.
    ///
    /// The provider is ONE object for the whole display, so this is not a
    /// per-window call and must not be treated as one. The setup dialog used to
    /// call it on open, which stripped the main window's header colour and the
    /// float ring's frame along with its own — a dialog cannot "reset its own"
    /// chrome when the chrome is shared. Only the main window calls this now,
    /// and only when it has no colour to apply.
    ///
    /// **It used to load the empty string, and that was the real bug behind the
    /// colour-parsing one.** Widening the parser makes this path rarer; it does
    /// not make it safe, and it is still reachable — `toHex` hands the host the
    /// raw value whenever a 2D canvas is unavailable or refuses, and a colour
    /// space nothing here converts will exist again. Clearing every rule took
    /// three things with it that have nothing to do with the header's colour:
    /// the float window's `padding` and inset hairline, which are its ONLY
    /// visible border, so a frameless window became a rectangle of page with no
    /// edge; the update strip's padding; and the strip's colours — which is how
    /// it went back to drawing the GTK theme's label colour on the page's own
    /// background, the black-on-near-black state the rules below were written
    /// to fix.
    ///
    /// So what is emitted here is everything EXCEPT the colours. Geometry is
    /// always correct, and a widget told neither foreground nor background gets
    /// both from the GTK theme — which pairs them legibly by construction,
    /// whatever theme that is. That is the property the empty string threw away.
    public static void Reset(Gdk.Display display) => Load(display, """
        /* Structure only. No `background` and no `color` anywhere: the theme's
           own pairing is the one thing guaranteed to be readable when the page
           has not told us what it is painting. */
        .float-ring {
            padding: 6px;
            box-shadow: inset 0 0 0 1px alpha(currentColor, 0.3);
        }
        .smylte-banner {
            padding: 6px;
            border-bottom: 1px solid alpha(currentColor, 0.3);
        }
        """);

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

    // The hairline arithmetic used to live here, as one function doing two
    // jobs. It is `Chrome.Seam` and `Chrome.WindowEdge` now — shared with the
    // Windows client, which was deriving its float ring from a different
    // brightness test entirely, and unit-tested, which it could never be while
    // it sat in a file that dlopens GTK.
}
