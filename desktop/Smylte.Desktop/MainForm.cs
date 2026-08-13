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

        Controls.Add(_web);
        Controls.Add(_splash);
        _splash.BringToFront();

        Load += async (_, _) => await InitialiseAsync().ConfigureAwait(true);
    }

    private async Task InitialiseAsync()
    {
        var progress = new Progress<string>(text => _splash.Text = text);
        try
        {
            await Updater
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
            _web.BringToFront();
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
