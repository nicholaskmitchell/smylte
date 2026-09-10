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
        _window.SetTitle("Smylte");
        _window.SetDefaultSize(settings.WindowWidth, settings.WindowHeight);
        if (settings.WindowMaximized) _window.Maximize();
        _window.AddCssClass("smylte");

        // Client-side decorations. Not a style preference: the header bar is
        // the only surface on X11 or Wayland whose colour an application can
        // set, so making it ours is what lets `Appearance` mean anything at
        // all. See HeaderChrome for the alternative that was rejected.
        _header.SetShowTitleButtons(true);
        _window.SetTitlebar(_header);

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
        try
        {
            var progress = new Progress<string>(text => _splash.SetLabel(text));
            var update = await Updater
                .EnsureWebAssetsAsync(_settings, progress, CancellationToken.None)
                .ConfigureAwait(true);

            _server = new LocalServer(_settings.WebRoot, _settings.ServerUrl, _settings.Port);
            if (_server.Port != _settings.Port)
            {
                // Remembered, because localStorage is keyed by origin and the
                // origin includes the port — a port that moved on every launch
                // would throw away the offline cache and the saved theme.
                _settings.Port = _server.Port;
                TrySave();
            }
            _server.Bridge = this;
            _server.Start();

            _host = new WebHost(_settings);
            IconAssets.Install(_settings, _window.GetDisplay());

            _web = _host.NewView(chromeless: false);
            _web.SetVexpand(true);
            _stack.AddNamed(_web, "web");
            Notifications.Attach(_web, _app, _settings);

            await _host.SeedAsync(CancellationToken.None).ConfigureAwait(true);

            _web.LoadUri(_server.Origin + "/");
            _stack.SetVisibleChildName("web");
            _banner.SetVisible(update.ClientOutdated);
        }
        catch (Exception ex)
        {
            Program.Log(_settings, ex);
            Fail(ex.Message);
        }
    }

    /// Something in startup refused. The setup dialog is the usual answer — a
    /// wrong server address is by far the most common cause — so it is offered
    /// rather than just reported, exactly as the Windows client does.
    private void Fail(string message)
    {
        _splash.SetLabel(message + "\n\nOpen setup to change the server address.");
        _stack.SetVisibleChildName("splash");
        OpenSetup();
    }

    public void Present() => _window.Present();

    public void OpenSetup()
    {
        if (_setup is { } open) { open.Present(); return; }
        _setup = new SetupWindow(_app, _settings, saved =>
        {
            _setup = null;
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
        if (_float is { } floating) { _float = null; floating.Close(); }

        if (!_window.IsMaximized())
        {
            _settings.WindowWidth = _window.GetWidth();
            _settings.WindowHeight = _window.GetHeight();
        }
        _settings.WindowMaximized = _window.IsMaximized();
        TrySave();

        _server?.Dispose();
        _server = null;
        _host?.Dispose();
        _host = null;
    }

    private void TrySave()
    {
        try { _settings.Save(); } catch (Exception) { /* not worth blocking a close */ }
    }

    // ── chrome and icon ─────────────────────────────────────────────────────

    private void ApplyChrome(string? background)
    {
        var colour = Theme.ParseHex(background);
        if (colour is { } value) HeaderChrome.Apply(_window.GetDisplay(), value);
        else HeaderChrome.Reset(_window.GetDisplay());
    }

    private void ApplyIcon()
    {
        var resolved = IconAssets.Resolve(_settings);
        _window.SetIconName(IconAssets.IconName(resolved));
        _float?.SetIconName(IconAssets.IconName(resolved));
        // The entry carries a COPY of the resolved variant, so a light/dark
        // flip has to rewrite it — which is why this re-syncs rather than only
        // running when the toggle changes.
        DesktopEntry.Sync(_settings, resolved);
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
            startMenuShortcut = _settings.StartMenuShortcut,

            // Always true here, and not a version test the way it is on
            // Windows: this client draws its own header bar, so it takes an
            // arbitrary colour on every desktop.
            captionColour = true,

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

    void IDesktopBridge.Appearance(string? background) => Post(() =>
    {
        var colour = Theme.ParseHex(background);
        _settings.TitleBarColor = colour is null ? "" : background!.Trim();
        ApplyChrome(_settings.TitleBarColor);
        _float?.ApplyChrome();
        TrySave();
    });

    void IDesktopBridge.Icon(string? choice, bool startMenuShortcut) => Post(() =>
    {
        _settings.IconChoice = IconChoices.Parse(choice).ToString();
        _settings.StartMenuShortcut = startMenuShortcut;
        TrySave();
        ApplyIcon();
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
