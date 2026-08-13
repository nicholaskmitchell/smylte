using System.Diagnostics;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Smylte.Desktop;

/// The window: a WebView2 filling the frame, pointed at the local server.
///
/// WebView2 is Edge's engine, already present on Windows 10 and 11, so this is
/// not a bundled browser — it is the one the machine already has, hosted in a
/// native window that owns the server's lifetime and shuts it down on close.
public sealed class MainForm : Form
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

    public MainForm(Settings settings)
    {
        _settings = settings;

        Text = "Smylte";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        MinimumSize = new Size(720, 520);
        ClientSize = new Size(settings.WindowWidth, settings.WindowHeight);
        if (settings.WindowMaximized) WindowState = FormWindowState.Maximized;

        try { Icon = new Icon(typeof(MainForm), "app.ico"); }
        catch (Exception) { /* cosmetic */ }

        BuildNotice();

        // Docking follows z-order, so set it explicitly rather than relying on the
        // order things were added: the notice strip claims the top, and whichever
        // of splash / web is visible fills what is left.
        Controls.Add(_web);
        Controls.Add(_splash);
        Controls.Add(_notice);
        Controls.SetChildIndex(_notice, 0);
        Controls.SetChildIndex(_splash, 1);
        Controls.SetChildIndex(_web, 2);

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

        // Docking consumes space in z-order, so the Fill has to be added last or
        // it claims the whole strip and the buttons never appear. Index 0 docks
        // furthest right, which puts "Not now" on the outside.
        _notice.Controls.Add(dismiss);
        _notice.Controls.Add(download);
        _notice.Controls.Add(message);
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
            _server.Start();

            var environment = await CoreWebView2Environment
                .CreateAsync(userDataFolder: _settings.BrowserProfile)
                .ConfigureAwait(true);
            await _web.EnsureCoreWebView2Async(environment).ConfigureAwait(true);

            _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;

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
