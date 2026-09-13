using System.Text.Json;

namespace Smylte.Desktop;

/// The window: a WebKitWebView filling the frame, pointed at the local server.
///
/// WebKitGTK is the engine GNOME already ships and the one the app's own layout
/// tier is tested against in CI, so this is the same trade the Windows client
/// makes with WebView2 — the rendering is the browser's, and what changes is
/// where the assets come from.
///
/// This is also the bridge. `LocalServer` serves `/desktop/*` by calling the
/// methods at the bottom of this file, and the contract they answer is the same
/// one MainForm answers on Windows, byte for byte — the SPA cannot tell which
/// host it is talking to except by the two optional keys added for the things
/// only one platform can do.
///
/// **Composition, not inheritance.** GirCore marks the regular constructors on
/// its native classes obsolete and says they will be removed — subclassing a
/// bound GObject is a dead end on a binding this project deliberately pins. So
/// each window here HOLDS a `Gtk.Window` rather than being one, which costs a
/// `_window.` prefix and buys a client that still compiles on the next GirCore.
internal sealed class MainWindow : IDesktopBridge
{
    private readonly Gtk.ApplicationWindow _window;
    private readonly Settings _settings;
    private readonly Gtk.Application _app;

    private readonly Gtk.Stack _stack = Gtk.Stack.New();
    private readonly Gtk.Label _splash = Gtk.Label.New("Starting…");
    private readonly Gtk.HeaderBar _header = Gtk.HeaderBar.New();
    private readonly UpdateBanner _banner;
    private readonly Gtk.Box _body = Gtk.Box.New(Gtk.Orientation.Vertical, 0);

    /// The way back to setup when there is no page to offer one.
    ///
    /// Hidden while the app is running, because the SPA has its own Settings
    /// and a second entry point would be noise. It appears the moment startup
    /// has nothing to show: an unconfigured client whose first-run dialog was
    /// cancelled used to sit on "Starting…" with no control anywhere and no
    /// way back short of a terminal — on the one screen where the terminal is
    /// the least likely thing the reader has open.
    private readonly Gtk.Button _setupPrompt = Gtk.Button.NewWithLabel("Setup…");

    /// What `ShowSetup` shows and hides, which is not always the button.
    ///
    /// In the header bar it IS the button: the strip around it is the title bar
    /// and has to stay. In the body it is the band the button sits in, because
    /// hiding only the button would leave an empty coloured strip above the
    /// page. Two containers, one visibility, so the three callers do not each
    /// have to know which title bar this window is wearing.
    private readonly Gtk.Widget _setupHost;

    /// The monogram, at the left of the header bar.
    ///
    /// GTK puts NO icon in a header bar: `gtk_window_set_icon_name` feeds the
    /// window manager, and with client-side decorations the window manager is
    /// not drawing anything to put it in. So the strip had the app's name and
    /// not its mark, and what appeared over a maximised window was the panel's
    /// icon rather than this one — which reads as an icon that only sometimes
    /// works. Exists only when the app draws the strip; with the system title
    /// bar the window manager draws the window icon itself.
    private readonly Gtk.Image _mark = Gtk.Image.New();

    private WebHost? _host;
    private WebKit.WebView? _web;
    private LocalServer? _server;
    private FloatWindow? _float;
    private SetupWindow? _setup;

    /// Read from HttpListener threads, written from the GTK thread. Volatile
    /// for the same reason MainForm's are: `State()` answers without hopping,
    /// so it must not read a stale cached value.
    private volatile bool _floating;
    private volatile bool _closing;

    /// Which start is the current one. Bumped by every StartAsync and by every
    /// Shutdown, and re-read after each await: a `--setup` save that lands
    /// while a slow first start is still downloading the web build used to run
    /// both to completion, and the loser left a LocalServer listening on a port
    /// nothing would ever close while the page moved to a second origin.
    private int _generation;

    /// The GTK thread's context, captured while on it. Every bridge call
    /// arrives on a listener thread and has to come back here.
    private readonly SynchronizationContext _ui;

    public MainWindow(Gtk.Application app, Settings settings)
    {
        _app = app;
        _settings = settings;
        _ui = SynchronizationContext.Current
              ?? throw new InvalidOperationException(
                  "MainWindow was built off the GTK thread; the bridge would have nowhere to post to.");

        _window = Gtk.ApplicationWindow.New(app);

        // The first moment a real display exists. Everything that gates on X11
        // — the pin the page is told about, the float window's remembered
        // position, skip-taskbar — reads this, so it has to come from the
        // display GDK opened rather than from the backend we asked for.
        X11Window.Active = X11Window.DisplayIsX11(_window.GetDisplay());
        _window.SetTitle("Smylte");
        _window.SetDefaultSize(settings.WindowWidth, settings.WindowHeight);
        if (settings.WindowMaximized) _window.Maximize();
        _window.AddCssClass("smylte");

        // Client-side decorations, unless the user has asked for the system's.
        //
        // Not a style preference either way: the header bar is the only surface
        // on X11 or Wayland whose colour an application can set, so making it
        // ours is what lets `Appearance` mean anything at all. See HeaderChrome.
        // The cost is the other half of the same fact — a window that declines a
        // server-side frame declines the window manager's decoration theme with
        // it, buttons, metrics, window icon and all — and `SystemTitleBar` is
        // which of the two the user would rather have.
        //
        // Not calling SetTitlebar is the whole of the other arm: `decorated`
        // stays true, so GTK asks the display server for a frame and gets one
        // from any window manager that draws them. A compositor that draws none
        // — GNOME's Wayland — has GTK build its own default header bar instead,
        // which still follows the system theme, which is still what was asked
        // for. SetupWindow has always worked this way; it is what `--setup`
        // looks like.
        _setupPrompt.OnClicked += (_, _) => OpenSetup();
        if (settings.SystemTitleBar)
        {
            // The Setup… button is the one control that has nowhere else to be:
            // it is the way back when there is no page to offer one. The update
            // strip is the precedent and the stylesheet already paints its
            // class, so it costs no new CSS.
            var strip = Gtk.Box.New(Gtk.Orientation.Horizontal, 8);
            strip.AddCssClass("smylte-banner");
            strip.Append(_setupPrompt);
            _body.Append(strip);
            _setupHost = strip;
        }
        else
        {
            _header.SetShowTitleButtons(true);
            // 16px is the size GTK's own header-bar icons are, and the art is
            // held legible at it by build_app_icon.py's four floors. Margins in
            // code rather than in HeaderChrome's stylesheet: that is a string
            // with no test, and this needs no cascade.
            _mark.SetPixelSize(16);
            _mark.SetMarginStart(8);
            _mark.SetMarginEnd(2);
            _header.PackStart(_mark);
            _header.PackStart(_setupPrompt);
            _window.SetTitlebar(_header);
            _setupHost = _setupPrompt;
        }
        ShowSetup(false);

        _splash.SetVexpand(true);
        _splash.SetHexpand(true);

        _stack.AddNamed(_splash, "splash");
        _stack.SetVexpand(true);
        _stack.SetVisibleChildName("splash");

        _banner = new UpdateBanner(settings, () => _window.Close());
        _body.Append(_banner.Widget);
        _body.Append(_stack);
        _window.SetChild(_body);

        // Before the page has said anything, so the frame is already themed
        // rather than flashing the system default while the SPA boots. Same
        // reason MainForm applies it in OnHandleCreated.
        ApplyChrome(settings.TitleBarColor);
        ApplyIcon();
        ColourScheme.Watch(() => _ui.Post(_ => ApplyIcon(), null));

        _window.OnCloseRequest += (_, _) => { Shutdown(); return false; };
    }

    // ── startup ─────────────────────────────────────────────────────────────

    /// The same order MainForm uses, and the order matters at three points:
    /// the web build must be on disk before LocalServer reads index.html for
    /// its Content-Security-Policy; the bridge must be attached before the page
    /// can ask for it; and the cookie must be in the jar before the first
    /// navigation, or the app opens on its own login screen.
    public async Task StartAsync()
    {
        var generation = ++_generation;

        // Cleared here rather than in the close handler: Shutdown() latches it
        // to mean "the main window is going away", and the setup-save path
        // calls Shutdown() and then comes straight back here. Left latched, the
        // next dock of the float window found `_closing` true, skipped
        // presenting the main window, and left the user with nothing on screen.
        _closing = false;
        ShowSetup(false);
        _splash.SetLabel("Starting…");

        // Built into locals and published to the fields only at the end, so a
        // start this one has overtaken can dispose exactly what it made.
        LocalServer? server = null;
        WebHost? host = null;

        try
        {
            // Gated on the generation, evaluated at DELIVERY. Progress<T>
            // captured the GTK context at construction, so the comparison runs
            // on the GTK thread — and an abandoned download reporting
            // "Downloading 40 MB…" over a live window's splash is the one way a
            // loser could still be seen after this change.
            var progress = new Progress<string>(text =>
            {
                if (generation == _generation) _splash.SetLabel(text);
            });
            var update = await Updater
                .EnsureWebAssetsAsync(_settings, progress, CancellationToken.None)
                .ConfigureAwait(true);

            if (generation != _generation) return;

            // CONSTRUCTED here, but not started and not persisted — see below.
            // Constructing binds nothing: ChoosePort probes a port and releases
            // it again, and Origin is computed from the number rather than from
            // a listener. The known cost of the gap this opens: a foreign
            // process can take the port between the probe and Start(), which is
            // now a whole login away rather than microseconds. That surfaces as
            // an HttpListenerException out of Start() and lands in the catch
            // below with `server` still owned here — the same place it landed
            // before, just later.
            server = new LocalServer(_settings.WebRoot, _settings.ServerUrl, _settings.Port);

            // WebHost's constructor may empty the cookie jar — see
            // Settings.CookieServer. That is a file delete rather than a
            // resource this start would hold, and both starts want the same
            // one, so it is safe to do before knowing who wins. The CLAIM it
            // records is persisted below, with everything else this start is
            // only allowed to write once it has won.
            host = new WebHost(_settings);
            IconAssets.Install(_settings, _window.GetDisplay());
            // Again, now that the names resolve. The constructor's ApplyIcon
            // runs before this and Program presents the window before it too,
            // so everything set there was set against an icon theme that had
            // never heard of these names. The WINDOW icon survives that — GTK
            // re-resolves it at the window-manager handshake — but a Gtk.Image
            // handed a name it cannot find just stays blank for good.
            ApplyIcon();

            var web = host.NewView(chromeless: false);
            web.SetVexpand(true);
            Notifications.Attach(web, _app, _settings);

            await host.SeedAsync(CancellationToken.None).ConfigureAwait(true);

            if (generation != _generation)
            {
                // Disposed, not published — and this is the whole reason the
                // listener is not bound yet. An overtaken start that had
                // already called Start() would hold the port until it got
                // here, which is past a login that can take twenty seconds;
                // the next start's ChoosePort would walk past the taken port
                // and PERSIST the moved one, so the SPA came back at a new
                // origin with an empty localStorage. The fix for that is not a
                // second owner for the listener, it is not acquiring one in the
                // first place — an object with two owners is how the obvious
                // version of this (`_starting`, disposed from Shutdown) turned
                // a leak into a double dispose.
                server.Dispose();
                host.Dispose();
                // Explicitly: GirCore pins the wrapper, so an unparented view
                // is not reclaimed by GC. It spawns no web process (nothing
                // loaded it), but the GObject and its ref on the shared
                // NetworkSession live for the rest of the process.
                web.Dispose();
                return;
            }

            // Past the check, so this start owns the process. Only NOW does
            // anything outside this method change: the socket binds and the two
            // settings decisions are written.
            TrySave();
            if (server.Port != _settings.Port)
            {
                // Remembered, because localStorage is keyed by origin and the
                // origin includes the port — a port that moved on every launch
                // would throw away the offline cache and the saved theme.
                _settings.Port = server.Port;
                TrySave();
            }
            server.Bridge = this;
            server.Start();

            _server = server;
            _host = host;
            _web = web;

            _stack.AddNamed(web, "web");
            web.LoadUri(server.Origin + "/");
            _stack.SetVisibleChildName("web");
            _banner.SetVisible(update.ClientOutdated);

            // Handed over: the catch below cleans up what this start still
            // owns, and past this line it owns nothing.
            server = null;
            host = null;
        }
        catch (Exception ex)
        {
            server?.Dispose();
            host?.Dispose();
            Program.Log(_settings, ex);
            if (generation == _generation) Fail(ex.Message);
        }
    }

    /// Something in startup refused. The setup dialog is the usual answer — a
    /// wrong server address is by far the most common cause — so it is offered
    /// rather than just reported, exactly as the Windows client does.
    private void Fail(string message)
    {
        _splash.SetLabel(message + "\n\nOpen setup to change the server address.");
        _stack.SetVisibleChildName("splash");
        ShowSetup(true);
        OpenSetup();
    }

    public void Present() => _window.Present();

    /// The empty state, for a client that has nothing to start.
    ///
    /// Set by the ONE caller that knows it — Program's activation path — rather
    /// than re-derived when a dialog closes. StartAsync clears it on entry, so
    /// there is exactly one writer in each direction.
    public void ShowUnconfigured()
    {
        _splash.SetLabel("Smylte is not configured yet.\n\nOpen setup to name the server to use.");
        _stack.SetVisibleChildName("splash");
        ShowSetup(true);
    }

    public void OpenSetup()
    {
        if (_setup is { } open) { open.Present(); return; }
        _setup = new SetupWindow(_app, _window, _settings, saved =>
        {
            _setup = null;
            // Cancelled: write NOTHING. The branch that used to be here asked
            // `_server is null` — "nothing is running right now" — and answered
            // it with "this client was never configured". Those diverge on the
            // most common path there is: the first launch after the first save
            // runs Shutdown + StartAsync with no local web build yet, so a
            // GitHub that cannot be reached throws rather than degrading, and
            // Fail's true message was overwritten with "not configured yet".
            // Byte-identical screens for two different problems, and the
            // misdirection is self-confirming — Setup reopens prefilled and
            // "Test connection" probes the user's own server, which answers.
            //
            // Nothing here knows why the dialog was opened. Program does, and
            // it says so up front by calling ShowUnconfigured.
            if (!saved) return;
            // Everything downstream of the settings is rebuilt rather than
            // patched: the server URL, the port, the data folder and the
            // credentials each feed something constructed at startup, and
            // half-applying them is how a client ends up talking to one server
            // and authenticated against another.
            Shutdown();
            _ = StartAsync();
        });
        _setup.Present();
    }

    private void Shutdown()
    {
        _closing = true;

        // Invalidates any start still in flight, so the one that is being torn
        // down here cannot publish a server over the top of the next one.
        _generation++;

        if (_float is { } floating) { _float = null; floating.Close(); }

        // The size guard is not paranoia. A destroyed GtkWindow answers 0x0,
        // and this runs twice on one path: close the main window with the setup
        // dialog open — the dialog is application-owned, so the process
        // survives — then Save, and Shutdown() runs again against a window GTK
        // has already torn down. 0x0 is persisted, SetDefaultSize(0, 0) on the
        // next launch realises a 64x17 window (measured), and nothing but a
        // hand-edit of settings.json gets it back.
        var width = _window.GetWidth();
        var height = _window.GetHeight();
        if (!_window.IsMaximized() && width > 0 && height > 0)
        {
            _settings.WindowWidth = width;
            _settings.WindowHeight = height;
        }
        _settings.WindowMaximized = _window.IsMaximized();
        TrySave();

        _server?.Dispose();
        _server = null;

        // Unparented, not just forgotten. A GtkStack owns the children added to
        // it, so a view merely dropped from the field stayed in the stack with
        // its WebKitWebProcess alive — and since StartAsync adds the new one
        // under the same name, the stack kept showing the DEAD page after a
        // setup-driven restart. `--setup`, save, repeat: one leaked web process
        // each time.
        if (_web is { } web)
        {
            _web = null;
            _stack.Remove(web);
        }

        _host?.Dispose();
        _host = null;
    }

    private void TrySave()
    {
        try { _settings.Save(); } catch (Exception) { /* not worth blocking a close */ }
    }

    // ── chrome and icon ─────────────────────────────────────────────────────

    /// Show or hide the way back to setup, wherever it ended up living.
    ///
    /// The container rather than the button, because in the body it is a strip
    /// with padding and a border of its own: hiding only the button would leave
    /// an empty coloured band above the page.
    private void ShowSetup(bool visible) => _setupHost.SetVisible(visible);

    private void ApplyChrome(string? background)
    {
        var colour = Theme.ParseHex(background);
        if (colour is { } value) HeaderChrome.Apply(_window.GetDisplay(), value);
        else HeaderChrome.Reset(_window.GetDisplay());
    }

    /// `authoritative` is the difference between the user having just answered
    /// the question and this being a refresh.
    ///
    /// Follow, not Sync, on a refresh: this fires on every colour-scheme change
    /// and on every start, from a settings copy that may be older than the file
    /// on disk. Sync acts on `off` as an instruction to REMOVE, which is how a
    /// launcher installed from a terminal while the app was open vanished by
    /// itself. Follow only ever brings an existing entry up to date.
    private void ApplyIcon(bool authoritative = false)
    {
        var resolved = IconAssets.Resolve(_settings);
        _window.SetIconName(IconAssets.IconName(resolved));
        _float?.SetIconName(IconAssets.IconName(resolved));
        // The header bar's copy, so the mark follows the setting and the Auto
        // light/dark flip exactly as the window icon does. Harmless with the
        // system title bar: the widget is simply not in anything.
        _mark.SetFromIconName(IconAssets.IconName(resolved));
        if (authoritative) DesktopEntry.Sync(_settings, resolved);
        else DesktopEntry.Follow(_settings, resolved);
    }

    // ── the floating window ─────────────────────────────────────────────────

    private void OpenFloat()
    {
        if (_float is { } open) { open.Present(); return; }
        if (_host is null || _server is null) return;

        _float = new FloatWindow(_app, _settings, _host, _server.Origin + "/focus?float=1", () =>
        {
            _float = null;
            _floating = false;
            // Every exit path — the page's Dock control, Escape, the window
            // manager's close — funnels through here, so the main window comes
            // back from all three without any of them knowing about the others.
            if (!_closing) _window.Present();
        });
        _float.SetIconName(IconAssets.IconName(IconAssets.Resolve(_settings)));
        _float.Open();
        _floating = true;

        // Float, then send this one away — in that order, so there is never a
        // moment with neither window on screen.
        _window.Minimize();
    }

    // ── IDesktopBridge ──────────────────────────────────────────────────────
    //
    // Every one of these arrives on an HttpListener thread. Three of them must
    // COMPLETE before LocalServer writes the response, because the response is
    // State() and the page reconciles its Float, Dock and pin controls from it;
    // the rest may be posted and forgotten.
    //
    // The blocking three cannot use SynchronizationContext.Send, which looks
    // like the answer and is not: GirCore implements Send as
    // g_main_context_invoke, which RETURNS IMMEDIATELY. It would silently give
    // fire-and-forget semantics, and the symptom would be a pin toggle that
    // snaps back to its old value one paint later. So they post a closure that
    // completes a TaskCompletionSource and wait on that. It cannot deadlock:
    // the caller is always a listener thread and never the GTK thread.

    private void Post(Action action) => _ui.Post(_ =>
    {
        try { action(); }
        catch (Exception ex) { Program.Log(_settings, ex); }
    }, null);

    private void Invoke(Action action)
    {
        var done = new TaskCompletionSource();
        _ui.Post(_ =>
        {
            try { action(); }
            catch (Exception ex) { Program.Log(_settings, ex); }
            finally { done.TrySetResult(); }
        }, null);
        // Bounded. A GTK thread that is wedged must not wedge the local server
        // with it; a stale answer is better than a request that never returns.
        done.Task.Wait(TimeSpan.FromSeconds(5));
    }

    string IDesktopBridge.State()
    {
        var choice = IconChoices.Parse(_settings.IconChoice);
        var light = ColourScheme.SystemUsesLightTheme();
        return JsonSerializer.Serialize(new
        {
            available = true,
            choice = choice.ToString(),
            resolved = IconChoices.Resolve(choice, light).ToString(),
            systemUsesLightTheme = light,
            // The file, not the field. `--install` writes the entry from its
            // own process while this one still holds the settings it loaded at
            // startup, so the field can be stale in exactly the case the user
            // is looking at the checkbox to find out.
            startMenuShortcut = DesktopEntry.Installed,

            // Always true here, and not a version test the way it is on
            // Windows: this client draws its own header bar, so it takes an
            // arbitrary colour on every desktop.
            captionColour = true,

            // What the user has asked for, as opposed to what this client can
            // do. With the system title bar on, the strip is the window
            // manager's: its decoration theme, its buttons, its window icon —
            // and no colour, because nothing on X11 or Wayland lets a client
            // tint a frame it did not draw. Absent from an older client's
            // answer, which is how a newer page knows not to offer the toggle.
            systemTitleBar = _settings.SystemTitleBar,

            floating = _floating,
            pinned = _settings.FloatPinned,

            // WebKitGTK does not implement `app-region`, so the page's own drag
            // regions are inert and the host has to move the window itself.
            // The page-visible meaning of the key is unchanged — false means
            // "ask the host on every press" — and false is the only honest
            // answer here.
            nativeDrag = false,

            // Additive and OPTIONAL, both of them. The Windows client sends
            // neither, and a page that sees neither must behave exactly as it
            // does today — which is why the page tests `canPin !== false`
            // rather than `canPin === true`.
            platform = "linux",
            canPin = X11Window.Active,
        });
    }

    /// Post, deliberately: `State()` carries nothing this changes, and the page
    /// throws the answer away (`void call(...)`). It also fires on every theme
    /// change, so blocking a listener thread on the GTK thread for it would put
    /// a round trip in the path of a colour the user is dragging.
    void IDesktopBridge.Appearance(string? background) => Post(() =>
    {
        // The same two steps MainForm has always taken, in the same order: a
        // value the host cannot read normalises to empty — which hands the
        // frame back to the system, as the interface documents — and then an
        // unchanged value returns without writing anything.
        //
        // The early-out is not a micro-optimisation here. This fires on every
        // colour the user drags, and it is a POST any process on loopback can
        // send; without it, each one queued a closure on the GTK main loop that
        // repainted two windows and wrote settings.json, for a colour that had
        // not moved.
        var value = Theme.ParseHex(background) is null ? "" : background!.Trim();
        if (value == _settings.TitleBarColor) return;

        _settings.TitleBarColor = value;
        ApplyChrome(value);
        _float?.ApplyChrome();
        TrySave();
    });

    /// Invoke, with Float/Dock/Pin — not Post. The page reconciles its dropdown
    /// and its checkbox from this call's answer, and that answer is `State()`,
    /// so the change has to have landed before it is read. Posted, the reply
    /// carries the OLD choice and the page sets the control back to what the
    /// user just changed it from.
    void IDesktopBridge.Icon(string? choice, bool startMenuShortcut) => Invoke(() =>
    {
        _settings.IconChoice = IconChoices.Parse(choice).ToString();
        _settings.StartMenuShortcut = startMenuShortcut;
        TrySave();
        // The one call that may REMOVE the entry, because this is the one that
        // is the user answering. LocalServer refuses the request outright when
        // it carries no `startMenuShortcut`, so `false` here always means
        // somebody unticked the box.
        ApplyIcon(authoritative: true);
    });

    /// Invoke, with Icon above, for the same reason: the page reconciles its
    /// checkbox from the State() this POST is answered with.
    ///
    /// And then it does nothing to the window, which is the whole of what is
    /// worth knowing here. `gtk_window_set_titlebar` on a REALIZED window warns
    /// and returns; the only way to make it take is to unrealize the window,
    /// which destroys the WebKit surface the page is living on. So the setting
    /// is written and the window is rebuilt on the next launch — and the page's
    /// hint says so, because a toggle that appears to do nothing is worse than
    /// one that says when it will.
    ///
    /// `TitleBarColor` is left alone, and ApplyChrome still runs on every
    /// Appearance: the same display-wide stylesheet paints the window's own
    /// background, the float window's ring and the update strip. Only the
    /// `headerbar` rules in it stop matching anything.
    void IDesktopBridge.TitleBar(bool system) => Invoke(() =>
    {
        _settings.SystemTitleBar = system;
        TrySave();
    });

    void IDesktopBridge.Float() => Invoke(OpenFloat);

    void IDesktopBridge.Dock() => Invoke(() => _float?.Close());

    void IDesktopBridge.Pin(bool onTop) => Invoke(() =>
    {
        _settings.FloatPinned = onTop;
        TrySave();
        // Persisted even when it cannot be applied. Under Wayland the page has
        // been told `canPin: false` and shows no control, but someone who later
        // sets `"Backend": "x11"` should get the preference they last stated,
        // not the default.
        _float?.ApplyPinned();
    });

    void IDesktopBridge.Drag() => Post(() => _float?.BeginDrag());
}
