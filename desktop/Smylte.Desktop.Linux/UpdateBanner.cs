using System.Diagnostics;

namespace Smylte.Desktop;

/// The strip that offers to replace the client itself.
///
/// Shown when the published binary is a different one from this. The client
/// cannot write over itself while it is running, but it CAN rename itself aside
/// and start the replacement, so the strip offers exactly that — the same
/// mechanism, and the same three buttons, as the Windows client's notice band.
///
/// The strip says the WINDOW changed, not the app: the web build updates itself
/// on every launch and needs nobody's permission, so anything this offers is
/// about the frame around it.
internal sealed class UpdateBanner
{
    private readonly Settings _settings;

    /// How to close the window this strip lives in. A callback rather than the
    /// window itself, because MainWindow holds its `Gtk.Window` rather than
    /// being one — see the note on that class — and handing the widget over
    /// would put a second owner on it.
    private readonly Action _closeWindow;

    private readonly Gtk.Box _box = Gtk.Box.New(Gtk.Orientation.Horizontal, 8);
    private readonly Gtk.Label _message = Gtk.Label.New(
        "A newer Smylte client is available. The app itself is up to date — "
        + "this updates the window around it.");
    private readonly Gtk.Button _update = Gtk.Button.NewWithLabel("Update");
    private readonly Gtk.Button _download = Gtk.Button.NewWithLabel("Download");
    private readonly Gtk.Button _dismiss = Gtk.Button.NewWithLabel("Not now");

    public Gtk.Widget Widget => _box;

    public UpdateBanner(Settings settings, Action closeWindow)
    {
        _settings = settings;
        _closeWindow = closeWindow;

        _box.AddCssClass("smylte-banner");
        _box.SetVisible(false);
        _box.SetMarginTop(0);

        _message.SetHexpand(true);
        _message.SetXalign(0);
        _message.SetEllipsize(Pango.EllipsizeMode.End);
        _message.SetMarginStart(12);

        _download.SetVisible(false);

        _box.Append(_message);
        _box.Append(_dismiss);
        _box.Append(_download);
        _box.Append(_update);

        _dismiss.OnClicked += (_, _) => _box.SetVisible(false);

        _download.OnClicked += (_, _) =>
        {
            // The one place UseShellExecute is right on Linux: it maps to
            // xdg-open, which is exactly what opening a URL wants. Launching the
            // replacement BINARY through it would be wrong — xdg-open on an
            // executable can hand it to a text editor — which is why the swap
            // below starts the process directly.
            try { Process.Start(new ProcessStartInfo(Updater.ReleaseUrl) { UseShellExecute = true }); }
            catch (Exception) { _message.SetLabel(Updater.ReleaseUrl); }
        };

        _update.OnClicked += async (_, _) => await ReplaceAsync().ConfigureAwait(true);
    }

    public void SetVisible(bool visible) => _box.SetVisible(visible);

    private async Task ReplaceAsync()
    {
        _update.SetSensitive(false);
        _dismiss.SetSensitive(false);
        var progress = new Progress<string>(text => _message.SetLabel(text));

        try
        {
            var exe = await Updater
                .ReplaceClientAsync(_settings, progress, CancellationToken.None)
                .ConfigureAwait(true);

            _message.SetLabel("Restarting…");

            // UseShellExecute FALSE. The new client is an executable file, and
            // on Linux the shell-execute path is xdg-open, which would consult
            // the desktop's handler for it rather than running it.
            var start = new ProcessStartInfo(exe)
            {
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(exe) ?? "",
            };
            start.ArgumentList.Add(Updater.AfterUpdateFlag);
            start.ArgumentList.Add(Environment.ProcessId.ToString());
            Process.Start(start);

            _closeWindow();
        }
        catch (Exception ex)
        {
            // Every refusal along the way carries a sentence meant for this
            // label — an unwritable directory, a release that states no digest
            // to check against. Offer the download page instead of leaving the
            // reader with nothing to do.
            _message.SetLabel(ex.Message);
            _update.SetVisible(false);
            _download.SetVisible(true);
            _dismiss.SetSensitive(true);
        }
    }
}
