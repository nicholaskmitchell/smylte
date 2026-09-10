namespace Smylte.Desktop;

/// First-run configuration, and what `--setup` reopens.
///
/// The same five fields the Windows dialog takes, in the same order, with the
/// same three gates on save — blank required fields, then an address that is
/// not a URL at all, then a probe whose failure is a WARNING rather than a wall
/// (a server that is temporarily down is not a reason to refuse to store a
/// correct address).
///
/// One field is new and it is not cosmetic: **the applications-menu entry is
/// asked for here**, checked, rather than defaulting on. On Windows the
/// equivalent toggle is off by default and buried in Appearance, because
/// without it the client installs nothing anywhere and the README makes a point
/// of that. On Linux, without an entry the app has no launcher, no app-grid
/// icon and no name on its notifications — so silently not having one is a
/// worse default, and silently installing one would contradict the promise.
/// Asking outright is the only option that does neither.
internal sealed class SetupWindow
{
    private readonly Gtk.Window _window;

    private readonly Settings _settings;
    private readonly Action<bool> _done;

    private readonly Gtk.Entry _server = Gtk.Entry.New();
    private readonly Gtk.Entry _username = Gtk.Entry.New();
    private readonly Gtk.Entry _password = Gtk.Entry.New();
    private readonly Gtk.Entry _folder = Gtk.Entry.New();
    private readonly Gtk.Entry _token = Gtk.Entry.New();
    private readonly Gtk.CheckButton _entry = Gtk.CheckButton.NewWithLabel(
        "Add Smylte to the applications menu");
    private readonly Gtk.Label _status = Gtk.Label.New("");
    private readonly Gtk.Button _test = Gtk.Button.NewWithLabel("Test connection");
    private readonly Gtk.Button _save = Gtk.Button.NewWithLabel("Save");
    private readonly Gtk.Button _cancel = Gtk.Button.NewWithLabel("Cancel");

    private bool _saved;

    public SetupWindow(Gtk.Application app, Settings settings, Action<bool> done)
    {
        _settings = settings;
        _done = done;

        _window = Gtk.Window.New();
        _window.SetApplication(app);
        _window.SetTitle("Smylte setup");
        _window.SetDefaultSize(620, 480);
        _window.SetModal(false);

        _password.SetVisibility(false);
        _token.SetVisibility(false);
        _server.SetPlaceholderText("https://tasks.example.com");
        _folder.SetPlaceholderText(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Smylte"));

        _server.SetText(settings.ServerUrl);
        _username.SetText(settings.Username);
        _password.SetText(settings.GetPassword());
        _folder.SetText(settings.DataFolder);
        _token.SetText(settings.GitHubToken);
        _entry.SetActive(settings.StartMenuShortcut);

        var grid = Gtk.Grid.New();
        grid.SetRowSpacing(10);
        grid.SetColumnSpacing(12);
        grid.SetMarginTop(20);
        grid.SetMarginBottom(20);
        grid.SetMarginStart(20);
        grid.SetMarginEnd(20);

        var row = 0;
        Row(grid, ref row, "Server address", _server, Browse: null);
        Row(grid, ref row, "Username", _username, Browse: null);
        Row(grid, ref row, "Password", _password, Browse: null);

        var browse = Gtk.Button.NewWithLabel("Browse…");
        browse.OnClicked += async (_, _) => await ChooseFolderAsync().ConfigureAwait(true);
        Row(grid, ref row, "Data folder", _folder, browse);

        Row(grid, ref row, "GitHub token", _token, Browse: null);

        grid.Attach(_entry, 1, row++, 1, 1);

        var help = Gtk.Label.New(
            "The password is stored encrypted against this account on this machine, "
            + "so a copied settings.json cannot be used elsewhere. The GitHub token is "
            + "optional and is stored in the clear — it only raises the hourly limit on "
            + "update checks.");
        help.SetWrap(true);
        help.SetXalign(0);
        help.AddCssClass("dim-label");
        grid.Attach(help, 0, row++, 2, 1);

        _status.SetXalign(0);
        _status.SetWrap(true);
        grid.Attach(_status, 0, row++, 2, 1);

        var actions = Gtk.Box.New(Gtk.Orientation.Horizontal, 8);
        actions.SetHalign(Gtk.Align.End);
        actions.Append(_test);
        actions.Append(_cancel);
        actions.Append(_save);
        _test.SetHalign(Gtk.Align.Start);
        _test.SetHexpand(true);
        grid.Attach(actions, 0, row, 2, 1);

        _window.SetChild(grid);

        _test.OnClicked += async (_, _) => await ProbeAsync().ConfigureAwait(true);
        _save.OnClicked += async (_, _) => await SaveAsync().ConfigureAwait(true);
        _cancel.OnClicked += (_, _) => _window.Close();

        // The dialog shows no page, so it has no theme to apply — the frame is
        // the system's, which is what Reset means.
        HeaderChrome.Reset(_window.GetDisplay());

        _window.OnCloseRequest += (_, _) => { _done(_saved); return false; };
    }

    public void Present() => _window.Present();

    private static void Row(Gtk.Grid grid, ref int row, string label, Gtk.Entry field, Gtk.Button? Browse)
    {
        var caption = Gtk.Label.New(label);
        caption.SetXalign(0);
        grid.Attach(caption, 0, row, 1, 1);

        field.SetHexpand(true);
        if (Browse is null)
        {
            grid.Attach(field, 1, row, 1, 1);
        }
        else
        {
            var box = Gtk.Box.New(Gtk.Orientation.Horizontal, 8);
            box.Append(field);
            box.Append(Browse);
            grid.Attach(box, 1, row, 1, 1);
        }
        row++;
    }

    private async Task ChooseFolderAsync()
    {
        try
        {
            var dialog = Gtk.FileDialog.New();
            dialog.SetTitle("Where should Smylte keep its downloaded app files?");
            var folder = await dialog.SelectFolderAsync(_window).ConfigureAwait(true);
            if (folder?.GetPath() is { Length: > 0 } path) _folder.SetText(path);
        }
        catch (Exception)
        {
            // Dismissed, or no portal, or a GTK too old for FileDialog. The
            // field is a plain text entry and typing a path has always been
            // allowed, so the worst case costs the picker and nothing else.
            if (string.IsNullOrWhiteSpace(_folder.GetText()))
                Say("Could not open a folder picker — type the path instead.", ok: false);
        }
    }

    private async Task ProbeAsync()
    {
        _test.SetSensitive(false);
        Say("Checking…", ok: true);
        var (ok, message) = await Session
            .ProbeAsync(_server.GetText().Trim(), CancellationToken.None)
            .ConfigureAwait(true);
        Say(message, ok);
        _test.SetSensitive(true);
    }

    private async Task SaveAsync()
    {
        var server = _server.GetText().Trim().TrimEnd('/');
        var folder = _folder.GetText().Trim();

        if (string.IsNullOrWhiteSpace(server) || string.IsNullOrWhiteSpace(folder))
        {
            Say("A server address and a data folder are both required.", ok: false);
            return;
        }

        // The parse gate, and it is not decoration: LocalServer builds a Uri
        // from this string and THROWS on one it cannot parse, so an unparseable
        // address here guarantees a client that cannot start.
        if (!Uri.TryCreate(server, UriKind.Absolute, out var parsed)
            || (parsed.Scheme != "http" && parsed.Scheme != "https"))
        {
            Say("That is not a valid http:// or https:// address.", ok: false);
            return;
        }

        _save.SetSensitive(false);
        var (reachable, message) = await Session
            .ProbeAsync(server, CancellationToken.None).ConfigureAwait(true);
        _save.SetSensitive(true);

        if (!reachable)
        {
            // A warning, not a wall. A server that is briefly down is not a
            // reason to refuse a correct address.
            Say(message + "  Saving anyway.", ok: false);
        }

        _settings.ServerUrl = server;
        _settings.Username = _username.GetText().Trim();
        _settings.SetPassword(_password.GetText());
        _settings.DataFolder = folder;
        _settings.GitHubToken = _token.GetText().Trim();
        _settings.StartMenuShortcut = _entry.GetActive();

        try
        {
            Directory.CreateDirectory(_settings.DataFolder);
            _settings.Save();
        }
        catch (Exception ex)
        {
            Say("Could not save: " + ex.Message, ok: false);
            return;
        }

        _saved = true;
        _window.Close();
    }

    private void Say(string message, bool ok)
    {
        _status.SetLabel(message);
        _status.RemoveCssClass(ok ? "error" : "success");
        _status.AddCssClass(ok ? "success" : "error");
    }
}
