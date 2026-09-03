using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Smylte.Desktop;

/// The window: a WebView2 filling the frame, pointed at the local server.
///
/// WebView2 is Edge's engine, already present on Windows 10 and 11, so this is
/// not a bundled browser — it is the one the machine already has, hosted in a
/// native window that owns the server's lifetime and shuts it down on close.
public sealed class MainForm : Form, IDesktopBridge
{
    private readonly Settings _settings;
    private readonly WebView2 _web = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly Label _splash = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        Text = "Starting…",
    };

    private readonly Panel _notice = new() { Dock = DockStyle.Top, Height = 36, Visible = false };

    private LocalServer? _server;
    /// Kept, where it used to be a local: the floating window's WebView2 shares
    /// it, and two views on one environment are what share the profile and so
    /// the session cookie.
    private CoreWebView2Environment? _environment;

    private FloatForm? _float;
    // Read by State() off the listener thread, written on the UI thread.
    private volatile bool _floating;
    private volatile bool _nativeDrag;
    /// Where to put this window back when the floating one is docked.
    private FormWindowState _stateBeforeFloat = FormWindowState.Normal;
    private bool _closing;

    public MainForm(Settings settings)
    {
        _settings = settings;

        Text = "Smylte";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        MinimumSize = new Size(720, 520);
        ClientSize = new Size(settings.WindowWidth, settings.WindowHeight);
        if (settings.WindowMaximized) WindowState = FormWindowState.Maximized;

        ApplyIcon();

        BuildNotice();

        // Docking follows z-order, and it goes from the HIGHEST child index down:
        // the control at the back is laid out first and takes the outer edge,
        // and a DockStyle.Fill claims the whole remaining rectangle without
        // leaving anything for a control laid out after it.
        //
        // The indices used to be the other way round — notice 0, splash 1, web 2
        // — under a comment claiming the same intent. That gave `_web` the whole
        // client rectangle and then placed `_notice` in the top 36px ON TOP of
        // it, covering the SPA's header row and swallowing every click in that
        // band. The strip has to be laid out FIRST to consume its own height, so
        // it takes the highest index and the two Fill children take what is left.
        Controls.Add(_web);
        Controls.Add(_splash);
        Controls.Add(_notice);
        Controls.SetChildIndex(_notice, 2);
        Controls.SetChildIndex(_splash, 1);
        Controls.SetChildIndex(_web, 0);

        Load += async (_, _) => await InitialiseAsync().ConfigureAwait(true);
    }

    /// Shown when the published exe is a different binary from this one. The
    /// client cannot replace itself while running, so the honest thing is to say
    /// so and link to the download rather than pretend it is handled.
    private void BuildNotice()
    {
        _notice.BackColor = Color.FromArgb(255, 244, 214);
        _notice.Padding = new Padding(12, 0, 8, 0);

        var message = new Label
        {
            Text = "A newer Smylte client is available. The app itself is up to date — "
                 + "this updates the window around it.",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            ForeColor = Color.FromArgb(90, 60, 0),
            AutoEllipsis = true,
        };

        var dismiss = new Button
        {
            Text = "Not now",
            Dock = DockStyle.Right,
            Width = 90,
            FlatStyle = FlatStyle.Flat,
        };
        dismiss.Click += (_, _) => _notice.Visible = false;

        var download = new Button
        {
            Text = "Download",
            Dock = DockStyle.Right,
            Width = 100,
            FlatStyle = FlatStyle.Flat,
        };
        download.Click += (_, _) =>
        {
            try
            {
                Process.Start(new ProcessStartInfo(Updater.ReleaseUrl) { UseShellExecute = true });
            }
            catch (Exception)
            {
                MessageBox.Show(this, Updater.ReleaseUrl, "Smylte — download link");
            }
        };

        // The same inversion, inside the strip, and the comment here used to state
        // the mechanism backwards: `Controls.Add` appends, so the LAST control
        // added has the highest index and is docked FIRST — which is exactly what
        // makes a Fill claim the whole strip. The label went last, took all of
        // it, and the two Right-docked buttons were then painted over its right
        // end rather than beside it.
        //
        // Fill FIRST, so the buttons consume their widths from the right before
        // the label is given the remainder. `download` before `dismiss` keeps
        // "Not now" on the outside, which is the layout the old comment
        // described and did not produce.
        _notice.Controls.Add(message);
        _notice.Controls.Add(download);
        _notice.Controls.Add(dismiss);
    }

    private async Task InitialiseAsync()
    {
        var progress = new Progress<string>(text => _splash.Text = text);
        try
        {
            var update = await Updater
                .EnsureWebAssetsAsync(_settings, progress, CancellationToken.None)
                .ConfigureAwait(true);

            ((IProgress<string>)progress).Report("Starting…");

            _server = new LocalServer(_settings.WebRoot, _settings.ServerUrl, _settings.Port);
            if (_server.Port != _settings.Port)
            {
                _settings.Port = _server.Port;
                _settings.Save();
            }
            _server.Bridge = this;
            _server.Start();

            _environment = await CoreWebView2Environment
                .CreateAsync(
                    userDataFolder: _settings.BrowserProfile,
                    options: new CoreWebView2EnvironmentOptions
                    {
                        // The floating focus window plays a chime at the end of
                        // an interval, and a browser refuses audio no gesture in
                        // THAT document asked for — a window nobody has clicked
                        // in would stay silent. Environment-wide, because
                        // options are fixed when the environment is made; the
                        // only effect on this window is that its chime works
                        // before anything is pressed too.
                        AdditionalBrowserArguments = "--autoplay-policy=no-user-gesture-required",
                    })
                .ConfigureAwait(true);
            await _web.EnsureCoreWebView2Async(_environment).ConfigureAwait(true);

            _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            // Unhandled, a page's request to notify is refused outright. The
            // focus surface asks only from a click and only with its setting on.
            _web.CoreWebView2.PermissionRequested += (_, e) =>
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.Notifications)
                    e.State = CoreWebView2PermissionState.Allow;
            };

            await SeedSessionAsync().ConfigureAwait(true);

            _web.CoreWebView2.Navigate(_server.Origin + "/");
            _splash.Visible = false;
            _web.Visible = true;
            _notice.Visible = update.ClientOutdated;
        }
        catch (WebView2RuntimeNotFoundException)
        {
            Fail("The Microsoft Edge WebView2 runtime is missing.\n\n"
               + "It ships with Windows 11 and current Windows 10, but can be installed from "
               + "microsoft.com/edge/webview2 if this machine does not have it.", offerSetup: false);
        }
        catch (Exception ex)
        {
            Fail(ex.Message, offerSetup: true);
        }
    }

    // ── window dressing ─────────────────────────────────────────────────────

    /// WM_SETTINGCHANGE with "ImmersiveColorSet" is how Windows announces that
    /// the light/dark setting moved. Only Auto cares — it is the mode whose
    /// answer depends on the taskbar — but re-resolving unconditionally is a
    /// no-op for the fixed choices and saves a special case.
    private const int WmSettingChange = 0x001A;

    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);
        if (m.Msg == WmSettingChange && m.LParam != IntPtr.Zero
            && Marshal.PtrToStringAuto(m.LParam) == "ImmersiveColorSet")
        {
            ApplyIcon();
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        // The caption cannot be painted before there is a window to paint. The
        // colour comes from settings rather than from the page, because the page
        // has not loaded yet — this is what stops the frame flashing the system
        // default on every launch until the SPA boots and reports its --bg.
        ApplyChrome(_settings.TitleBarColor);
    }

    private void ApplyIcon()
    {
        // Cosmetic, all the way down: a missing or unreadable icon costs the
        // monogram, never the window.
        try { Icon = IconLibrary.Load(IconLibrary.Parse(_settings.IconChoice)) ?? Icon; }
        catch (Exception) { /* cosmetic */ }
    }

    private void ApplyChrome(string? background)
    {
        try
        {
            var colour = WindowChrome.ParseHex(background);
            if (colour is null) WindowChrome.Reset(Handle);
            else WindowChrome.Apply(Handle, colour.Value);
        }
        catch (Exception) { /* cosmetic */ }
    }

    // ── IDesktopBridge ──────────────────────────────────────────────────────
    //
    // Every one of these arrives on an HttpListener thread, so each hops to the
    // UI thread before touching a window. `State` is the exception and has to
    // be: it returns a value, so it cannot fire-and-forget, and it reads only
    // the settings object and two flags written under the UI thread.
    //
    // Two kinds of hop. `Appearance` and `Icon` BeginInvoke — nothing waits on
    // them. `Float`, `Dock` and `Pin` Invoke, and have to: LocalServer answers
    // every bridge call with State(), and the page reconciles its pin toggle
    // and its Float/Dock controls from that answer, so an answer written before
    // the UI thread had run would say the old thing and the toggle would snap
    // back. `Drag` BeginInvokes, because it returns nothing and the press it
    // answers is already a few milliseconds old.

    string IDesktopBridge.State()
    {
        var choice = IconLibrary.Parse(_settings.IconChoice);
        return JsonSerializer.Serialize(new
        {
            available = true,
            choice = choice.ToString(),
            // What Auto currently resolves to, so the settings UI can show the
            // live answer rather than the word "Auto" and nothing else.
            resolved = IconLibrary.Resolve(choice).ToString(),
            systemUsesLightTheme = IconLibrary.SystemUsesLightTheme(),
            startMenuShortcut = _settings.StartMenuShortcut,
            // Windows 10 can only do light or dark; an arbitrary caption colour
            // is Windows 11 22000+. The page uses this to say which it will get
            // instead of promising a colour the OS will ignore.
            captionColour = Environment.OSVersion.Version.Build >= 22000,
            // The floating focus window. Absent from an older exe's answer,
            // which is how a newer web build knows not to offer it.
            floating = _floating,
            pinned = _settings.FloatPinned,
            // Whether the runtime moves the window from the page's own drag
            // regions, or the page has to ask the bridge for every drag.
            nativeDrag = _nativeDrag,
        });
    }

    void IDesktopBridge.Float()
    {
        Invoke(() =>
        {
            if (_environment is null || _server is null || _closing) return;
            if (_float is null || _float.IsDisposed)
            {
                _stateBeforeFloat = WindowState == FormWindowState.Minimized
                    ? FormWindowState.Normal : WindowState;
                _float = new FloatForm(
                    _settings, _environment, _server.Origin + "/focus?float=1",
                    nativeDragReady: ready => _nativeDrag = ready);
                _float.FormClosed += (_, _) => OnDocked();
                _float.Show();
                _floating = true;
            }
            // Float, then minimise, then activate — in that order, so focus
            // lands on the floating window rather than on whatever the taskbar
            // hands it to when this one drops.
            WindowState = FormWindowState.Minimized;
            _float.Activate();
        });
    }

    void IDesktopBridge.Dock()
    {
        // Every way the floating window closes — this, Escape on its page,
        // Alt+F4 — ends in FormClosed, so OnDocked is the one restore path.
        Invoke(() => _float?.Close());
    }

    void IDesktopBridge.Pin(bool onTop)
    {
        Invoke(() =>
        {
            _settings.FloatPinned = onTop;
            try { _settings.Save(); } catch (Exception) { /* cosmetic */ }
            if (_float is { IsDisposed: false }) _float.TopMost = onTop;
        });
    }

    void IDesktopBridge.Drag()
    {
        BeginInvoke(() => _float?.BeginDrag());
    }

    private void OnDocked()
    {
        _float = null;
        _floating = false;
        _nativeDrag = false;
        if (_closing) return;
        WindowState = _stateBeforeFloat;
        Activate();
    }

    void IDesktopBridge.Appearance(string? background)
    {
        BeginInvoke(() =>
        {
            var value = WindowChrome.ParseHex(background) is null ? "" : background!;
            if (value == _settings.TitleBarColor) return;
            _settings.TitleBarColor = value;
            _settings.Save();
            ApplyChrome(value);
            // The floating window's ring is the same colour, and follows.
            if (_float is { IsDisposed: false }) _float.ApplyChrome(value);
        });
    }

    void IDesktopBridge.Icon(string? choice, bool startMenuShortcut)
    {
        BeginInvoke(() =>
        {
            _settings.IconChoice = IconLibrary.Parse(choice).ToString();
            _settings.StartMenuShortcut = startMenuShortcut;
            _settings.Save();
            ApplyIcon();
            ShellShortcut.Sync(_settings);
        });
    }

    /// Trade the stored credentials for a session cookie and hand it to the
    /// webview, so the app opens already signed in.
    ///
    /// Every failure path here is deliberately silent: an expired password, a
    /// server that has just gone down, a roamed settings file DPAPI will not
    /// decrypt. In all of them the right answer is to navigate anyway and let
    /// the app's own login screen do its job, which is exactly what it is for.
    private async Task SeedSessionAsync()
    {
        var cookies = await Session
            .LoginAsync(_settings.ServerUrl, _settings.Username, _settings.GetPassword(),
                        CancellationToken.None)
            .ConfigureAwait(true);
        if (cookies.Count == 0) return;

        var manager = _web.CoreWebView2.CookieManager;
        foreach (var raw in cookies)
        {
            if (Session.ParseCookie(raw) is not { } parsed) continue;
            var cookie = manager.CreateCookie(parsed.Name, parsed.Value, "localhost", "/");
            cookie.IsSecure = false;
            cookie.IsHttpOnly = true;
            manager.AddOrUpdateCookie(cookie);
        }
    }

    private void Fail(string message, bool offerSetup)
    {
        _splash.Text = "Could not start.";

        if (!offerSetup)
        {
            MessageBox.Show(this, message, "Smylte", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
            return;
        }

        var answer = MessageBox.Show(this,
            message + "\n\nOpen settings?",
            "Smylte", MessageBoxButtons.YesNo, MessageBoxIcon.Error);

        if (answer == DialogResult.Yes)
        {
            using var setup = new SetupForm(_settings);
            if (setup.ShowDialog(this) == DialogResult.OK)
            {
                MessageBox.Show(this, "Settings saved. Smylte will restart now.",
                    "Smylte", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Application.Restart();
                return;
            }
        }
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // The floating window goes first, and OnDocked must not restore this
        // one on the way out: Application.Run ends when THIS form closes, and a
        // top-level window left behind would keep the process alive with no
        // taskbar button to find it by.
        _closing = true;
        if (_float is { IsDisposed: false }) _float.Close();

        // Only a restored window has a size worth remembering; a maximized one
        // would otherwise record the screen and never shrink back.
        if (WindowState == FormWindowState.Normal)
        {
            _settings.WindowWidth = ClientSize.Width;
            _settings.WindowHeight = ClientSize.Height;
        }
        _settings.WindowMaximized = WindowState == FormWindowState.Maximized;
        try { _settings.Save(); } catch (Exception) { /* not worth blocking the close */ }

        _server?.Dispose();
        base.OnFormClosing(e);
    }
}
