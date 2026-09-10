namespace Smylte.Desktop;

/// The floating focus window: the same page at a small size, frameless, above
/// everything else.
///
/// It is a second view on the SAME `WebKit.NetworkSession` as the main window,
/// which is what makes it the same logged-in user looking at the same clock —
/// the two agree to the second and either can be closed without the other
/// losing anything.
///
/// **Three of its four properties are X11-only, and that is why the client asks
/// for X11.** Staying above other windows, opening where it was left, and
/// keeping out of the task list are all EWMH, all honoured by every window
/// manager, and all absent from Wayland with no extension GNOME implements.
/// Under `"Backend": "wayland"` the window still opens, still drags, still
/// resizes and still docks — it just cannot do those three, and the page is
/// told so through `canPin` rather than being left with a control that does
/// nothing.
///
/// **The drag is the host's, not the page's.** On Windows the WebView2 runtime
/// answers the hit test from the page's `app-region: drag` regions and moves
/// the window natively. WebKitGTK implements no such thing, so the CSS in
/// `app.css` is inert here and the host does the move itself, from a gesture on
/// the window. That gesture runs INSIDE event dispatch, which is what makes it
/// work under Wayland too: `BeginMove` is validated against a live input
/// serial, and an HTTP round trip through the bridge does not have one.
internal sealed class FloatWindow
{
    private readonly Gtk.Window _window;

    /// Logical pixels, and the same four numbers the page's stylesheet and the
    /// browser layout test are built on: 420×280 to open, 320×200 at the floor,
    /// minus a six-pixel ring, so the page's viewport is 408×268 down to
    /// 308×188.
    private const int OpenWidth = 420, OpenHeight = 280;
    private const int MinWidth = 320, MinHeight = 200;
    private const int Ring = 6;

    /// How far a press has to travel before it becomes a window move rather
    /// than a click. Below this the gesture never claims the sequence, so the
    /// page still gets its press and release and its buttons still work.
    private const double DragThreshold = 6;

    private readonly Settings _settings;
    private readonly Action _onClosed;
    private readonly WebKit.WebView _web;
    private readonly Gtk.Box _ring = Gtk.Box.New(Gtk.Orientation.Vertical, 0);

    private bool _moving;
    private RingEdge _edge;

    public FloatWindow(Gtk.Application app, Settings settings, WebHost host, string url, Action onClosed)
    {
        _settings = settings;
        _onClosed = onClosed;

        _window = Gtk.Window.New();
        _window.SetApplication(app);
        _window.SetTitle("Smylte — Focus");
        _window.SetDecorated(false);
        _window.SetResizable(true);
        _window.AddCssClass("smylte");

        // NOT transient-for the main window, on purpose. An owned window hides
        // with its owner, and the main window is sent away the instant this
        // opens — the same reason FloatForm takes no Owner on Windows.

        _web = host.NewView(chromeless: true);
        _web.SetVexpand(true);
        _web.SetHexpand(true);

        // The ring is the window's own six pixels of frame: a box with padding,
        // styled by HeaderChrome from the same `--bg` the header bar gets, with
        // a one-pixel inset hairline so the window does not float in a shape
        // with no edge. GTK gives an undecorated window no shadow, and faking
        // one would need margin outside the content — which would make the
        // window larger than its visible rectangle and break the 420×280 the
        // page's own layout test pins.
        _ring.AddCssClass("float-ring");
        _ring.Append(_web);
        _window.SetChild(_ring);

        // Alt-Tab shows the live countdown, the way DocumentTitleChanged does
        // on Windows.
        _web.OnNotify += (_, e) =>
        {
            if (e.Pspec.GetName() == "title" && _web.GetTitle() is { Length: > 0 } title)
                _window.SetTitle(title);
        };

        InstallGestures();

        _window.OnCloseRequest += (_, _) =>
        {
            Remember();
            _onClosed();
            return false;
        };

        _web.LoadUri(url);
    }

    public void Open()
    {
        Place();
        _window.Present();
        ApplyChrome();
        // After Present, because both need a realised surface: an X11 window
        // has no XID until it is mapped, and a state message sent before that
        // goes to a window that does not exist yet.
        ApplyPinned();
        X11Window.SetSkipTaskbar(_window, true);
    }

    public void Present() => _window.Present();

    public void Close() => _window.Close();

    public void SetIconName(string name) => _window.SetIconName(name);

    public void ApplyChrome()
    {
        // The ring's colour follows the app's own --bg, which is the same value
        // the main window's header is painted with — the stylesheet is shared,
        // so a theme change reaches here through the same bridge call.
        var colour = Theme.ParseHex(_settings.TitleBarColor);
        if (colour is { } value) HeaderChrome.Apply(_window.GetDisplay(), value);
    }

    public void ApplyPinned() => X11Window.SetAbove(_window, _settings.FloatPinned);

    /// The bridge's `drag` verb. Reached only when the page asks — which, with
    /// the gesture below installed, it does not: the host reports
    /// `nativeDrag: false`, and this is the path that answers it. Kept because
    /// the route is part of the contract and `LocalServerBridgeTests` asserts
    /// it reaches the bridge and answers 200.
    public void BeginDrag()
    {
        // Deliberately a no-op beyond a nudge. A move started from an HTTP
        // round trip has no live input serial, so Wayland refuses it outright
        // and X11 accepts it with a stale timestamp — inconsistent enough that
        // the gesture is the real answer and this is not worth a second
        // mechanism that works on one backend.
        _window.Present();
    }

    // ── moving and resizing ─────────────────────────────────────────────────

    private void InstallGestures()
    {
        var drag = Gtk.GestureDrag.New();

        // CAPTURE phase, so the ring and the drag see the press before the
        // webview swallows it. Without this a press anywhere on the page is the
        // page's and the window can never be moved, since the page's own
        // `app-region` does nothing here.
        drag.SetPropagationPhase(Gtk.PropagationPhase.Capture);

        drag.OnDragBegin += (gesture, e) =>
        {
            _moving = false;
            _edge = FloatRing.HitTest(_window.GetWidth(), _window.GetHeight(), Ring, (int)e.StartX, (int)e.StartY);

            if (_edge == RingEdge.None) return;
            if (gesture.GetDevice() is not { } device) return;

            // A press on the ring is unambiguous — there is no page there — so
            // the resize starts at once rather than waiting for movement.
            _moving = true;
            gesture.SetState(Gtk.EventSequenceState.Claimed);
            Toplevel()?.BeginResize(Edge(_edge), device, (int)gesture.GetButton(),
                e.StartX, e.StartY, gesture.GetCurrentEventTime());
        };

        drag.OnDragUpdate += (gesture, e) =>
        {
            if (_moving) return;
            if (Math.Abs(e.OffsetX) < DragThreshold && Math.Abs(e.OffsetY) < DragThreshold) return;
            if (gesture.GetDevice() is not { } device) return;

            // Past the threshold on the page itself: this is a window move. The
            // whole page is the drag handle, which is what `app-region: drag`
            // says on Windows — and the known cost, stated rather than hidden,
            // is that a press that starts on a button and then travels moves
            // the window instead of pressing it. Asking the page where its
            // controls are would mean a new bridge verb, and the bridge is
            // deliberately not a general "call the host" channel.
            _moving = true;
            gesture.SetState(Gtk.EventSequenceState.Claimed);
            gesture.GetStartPoint(out var startX, out var startY);
            Toplevel()?.BeginMove(device, (int)gesture.GetButton(),
                startX, startY, gesture.GetCurrentEventTime());
        };

        drag.OnDragEnd += (_, _) =>
        {
            _moving = false;
            // After a move or a resize, never per pixel — the same rule
            // FloatForm follows by writing on WM_EXITSIZEMOVE rather than on
            // every WM_MOVE.
            Remember();
        };

        _window.AddController(drag);

        // Escape docks. The page also binds it — `useEscape(floating ? dock :
        // onLeave)` — but the page only sees it while it has focus, and a
        // window whose page has not loaded yet still has to be closable.
        var keys = Gtk.EventControllerKey.New();
        keys.OnKeyPressed += (_, e) =>
        {
            if (e.Keyval != Gdk.Constants.KEY_Escape) return false;
            _window.Close();
            return true;
        };
        _window.AddController(keys);
    }

    private Gdk.Toplevel? Toplevel() => _window.GetSurface() as Gdk.Toplevel;

    private static Gdk.SurfaceEdge Edge(RingEdge edge) => edge switch
    {
        RingEdge.Left => Gdk.SurfaceEdge.West,
        RingEdge.Right => Gdk.SurfaceEdge.East,
        RingEdge.Top => Gdk.SurfaceEdge.North,
        RingEdge.Bottom => Gdk.SurfaceEdge.South,
        RingEdge.TopLeft => Gdk.SurfaceEdge.NorthWest,
        RingEdge.TopRight => Gdk.SurfaceEdge.NorthEast,
        RingEdge.BottomLeft => Gdk.SurfaceEdge.SouthWest,
        _ => Gdk.SurfaceEdge.SouthEast,
    };

    // ── where it opens, and what it remembers ───────────────────────────────

    /// Where the window opens: at the size it was, and — on X11 — where it was.
    ///
    /// No DPI arithmetic, unlike the Windows client. GTK sizes in logical
    /// pixels and the compositor owns fractional scaling, so a window restored
    /// on a differently scaled monitor is already the size its owner chose.
    /// `FloatDpi` is written as 0, which is the sentinel the Windows side
    /// already reads as "no rescale" — one field, two clients, no new branch.
    private void Place()
    {
        var width = _settings.FloatWidth > 0 ? _settings.FloatWidth : OpenWidth;
        var height = _settings.FloatHeight > 0 ? _settings.FloatHeight : OpenHeight;
        _window.SetDefaultSize(width, height);
        _ring.SetSizeRequest(MinWidth, MinHeight);

        if (!X11Window.Active) return;                       // the compositor places it
        if (_settings.FloatX < 0 || _settings.FloatY < 0) return;
        if (!OnAScreen(_settings.FloatX, _settings.FloatY, width, height)) return;

        X11Window.Move(_window, _settings.FloatX, _settings.FloatY);
    }

    /// Would a window at this rectangle be reachable? The Windows client asks
    /// each screen's WORKING area; GTK4 removed `gdk_monitor_get_workarea`, so
    /// this asks the monitor's geometry instead. The difference is a window
    /// that could land under a panel rather than off the screen entirely, which
    /// is a nuisance the user can drag out of rather than a window they cannot
    /// reach.
    private bool OnAScreen(int x, int y, int width, int height)
    {
        try
        {
            var monitors = _window.GetDisplay().GetMonitors();
            for (uint i = 0; i < monitors.GetNItems(); i++)
            {
                if (monitors.GetObject(i) is not Gdk.Monitor monitor) continue;
                monitor.GetGeometry(out var area);
                var overlapX = Math.Min(x + width, area.X + area.Width) - Math.Max(x, area.X);
                var overlapY = Math.Min(y + height, area.Y + area.Height) - Math.Max(y, area.Y);
                if (overlapX >= 40 && overlapY >= 40) return true;
            }
        }
        catch (Exception)
        {
            return false;
        }
        return false;
    }

    private void Remember()
    {
        try
        {
            if (_window.GetWidth() <= 0 || _window.GetHeight() <= 0) return;
            _settings.FloatWidth = _window.GetWidth();
            _settings.FloatHeight = _window.GetHeight();

            // Under Wayland the position cannot be read, and writing a guess
            // would overwrite what an earlier X11 session recorded — so the
            // fields are left exactly as they are, and flipping the backend
            // back restores the window where it was.
            if (X11Window.Position(_window) is { } at)
            {
                _settings.FloatX = at.X;
                _settings.FloatY = at.Y;
            }
            _settings.FloatDpi = 0;
            _settings.Save();
        }
        catch (Exception) { /* not worth blocking a move */ }
    }
}
