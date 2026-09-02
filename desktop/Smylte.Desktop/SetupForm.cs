namespace Smylte.Desktop;

/// First-run configuration, and the same dialog later via `Smylte.exe --setup`.
///
/// Not "from the window menu", as this said: the main window has no menu, and
/// never had one. The only other way in is MainForm's `Fail` path, which offers
/// it when the client could not start at all.
///
/// Laid out in code rather than with a designer: it is a handful of rows, and a
/// .Designer.cs adds a second file to keep in step for no benefit at this size.
public sealed class SetupForm : Form
{
    private readonly TextBox _server = new();
    private readonly TextBox _username = new();
    private readonly TextBox _password = new() { UseSystemPasswordChar = true };
    private readonly TextBox _folder = new();
    private readonly TextBox _token = new() { UseSystemPasswordChar = true };
    /// The same choice the Appearance section offers, here too because this
    /// dialog is reachable without the app running — and because a client that
    /// cannot start is exactly when you might want its icon back.
    private readonly ComboBox _icon = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly Label _status = new();
    private readonly Button _test = new() { Text = "Test connection" };
    private readonly Button _save = new() { Text = "Save", DialogResult = DialogResult.None };
    private readonly Button _cancel = new() { Text = "Cancel", DialogResult = DialogResult.Cancel };

    public Settings Result { get; }

    public SetupForm(Settings settings)
    {
        Result = settings;

        Text = "Smylte — Setup";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterScreen;
        MaximizeBox = false;
        MinimizeBox = false;
        AutoScaleMode = AutoScaleMode.Font;
        ClientSize = new Size(580, 440);

        try { Icon = IconLibrary.Load(IconLibrary.Parse(settings.IconChoice)) ?? Icon; }
        catch (Exception) { /* icon is cosmetic; never block setup on it */ }

        _server.Text = settings.ServerUrl;
        _username.Text = settings.Username;
        _password.Text = settings.GetPassword();
        _folder.Text = settings.DataFolder;
        _token.Text = settings.GitHubToken;

        // Display text to enum name, in the order the Appearance section lists
        // them. Auto leads because it is the default and the only one that keeps
        // up with the Windows theme on its own.
        _icon.Items.AddRange(new object[]
        {
            "Follow the Windows theme", "Cream plate", "Ink plate", "Accent plate", "Bare mark",
        });
        _icon.SelectedIndex = IconLibrary.Parse(settings.IconChoice) switch
        {
            IconChoice.Paper => 1, IconChoice.Ink => 2, IconChoice.Accent => 3,
            IconChoice.Mark => 4, _ => 0,
        };

        var browse = new Button { Text = "Browse…" };
        browse.Click += (_, _) => PickFolder();
        _test.Click += async (_, _) => await TestAsync().ConfigureAwait(true);
        _save.Click += async (_, _) => await SaveAsync().ConfigureAwait(true);

        Row(0, "Server address", _server);
        Row(1, "Username", _username);
        Row(2, "Password", _password);
        Row(3, "Data folder", _folder, browse);
        Row(4, "GitHub token", _token);
        Row(5, "App icon", _icon);

        Controls.Add(new Label
        {
            Text = "The server address is where Smylte is deployed, e.g. "
                 + "https://radicale.nicholaskmitchell.com.\n"
                 + "The password is stored encrypted for your Windows account, never in the clear.\n"
                 + "A GitHub token is optional — only useful if update checks hit a rate limit.",
            Location = new Point(24, 272),
            Size = new Size(532, 60),
            ForeColor = SystemColors.GrayText,
        });

        _status.Location = new Point(24, 340);
        _status.Size = new Size(532, 40);
        Controls.Add(_status);

        _test.Location = new Point(24, 392);
        _test.Size = new Size(130, 30);
        _save.Location = new Point(346, 392);
        _save.Size = new Size(100, 30);
        _cancel.Location = new Point(456, 392);
        _cancel.Size = new Size(100, 30);
        Controls.Add(_test);
        Controls.Add(_save);
        Controls.Add(_cancel);

        AcceptButton = _save;
        CancelButton = _cancel;
    }

    private void Row(int index, string label, Control field, Button? trailing = null)
    {
        var y = 24 + index * 40;
        Controls.Add(new Label
        {
            Text = label,
            Location = new Point(24, y + 3),
            Size = new Size(115, 20),
        });
        field.Location = new Point(145, y);
        field.Size = new Size(trailing is null ? 411 : 306, 23);
        Controls.Add(field);

        if (trailing is null) return;
        trailing.Location = new Point(461, y - 1);
        trailing.Size = new Size(95, 25);
        Controls.Add(trailing);
    }

    private void PickFolder()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Where should Smylte keep its downloaded app files?",
            UseDescriptionForTitle = true,
            SelectedPath = Directory.Exists(_folder.Text) ? _folder.Text : "",
        };
        if (dialog.ShowDialog(this) == DialogResult.OK) _folder.Text = dialog.SelectedPath;
    }

    private async Task<bool> TestAsync()
    {
        _status.ForeColor = SystemColors.GrayText;
        _status.Text = "Checking…";
        _test.Enabled = _save.Enabled = false;
        try
        {
            var (ok, message) = await Session.ProbeAsync(_server.Text.Trim(), CancellationToken.None)
                .ConfigureAwait(true);
            _status.ForeColor = ok ? Color.FromArgb(0, 110, 60) : Color.FromArgb(170, 30, 20);
            _status.Text = message;
            return ok;
        }
        finally
        {
            _test.Enabled = _save.Enabled = true;
        }
    }

    private async Task SaveAsync()
    {
        if (string.IsNullOrWhiteSpace(_server.Text) || string.IsNullOrWhiteSpace(_folder.Text))
        {
            _status.ForeColor = Color.FromArgb(170, 30, 20);
            _status.Text = "A server address and a data folder are both required.";
            return;
        }

        // An address that will not PARSE is a different failure from one that
        // will not answer, and only the second is worth overriding. `LocalServer`
        // constructs `new Uri(serverUrl.TrimEnd('/') + "/")`, which throws for a
        // relative string — so saving an unparseable address guarantees the
        // client cannot start, and the override prompt was actively steering the
        // user into it: type the README's own example without the scheme
        // ("radicale.nicholaskmitchell.com", the likeliest slip there is) and the
        // dialog said the server "could not be reached", so answering Yes was
        // the reasonable read. Then every launch failed with "Invalid URI" until
        // they worked out the scheme was missing.
        var typed = _server.Text.Trim();
        if (!Uri.TryCreate(typed.TrimEnd('/'), UriKind.Absolute, out var parsed)
            || (parsed.Scheme != "http" && parsed.Scheme != "https"))
        {
            _status.ForeColor = Color.FromArgb(170, 30, 20);
            _status.Text = "That is not a valid http:// or https:// address.";
            return;
        }

        // A failing probe is a warning, not a wall: the server may just be down
        // right now, and the client works offline against its installed build.
        if (!await TestAsync().ConfigureAwait(true))
        {
            var proceed = MessageBox.Show(this,
                "That server could not be reached. Save these settings anyway?",
                "Smylte", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (proceed != DialogResult.Yes) return;
        }

        Result.ServerUrl = _server.Text.Trim().TrimEnd('/');
        Result.Username = _username.Text.Trim();
        Result.SetPassword(_password.Text);
        Result.DataFolder = _folder.Text.Trim();
        Result.GitHubToken = _token.Text.Trim();
        Result.IconChoice = (_icon.SelectedIndex switch
        {
            1 => IconChoice.Paper, 2 => IconChoice.Ink, 3 => IconChoice.Accent,
            4 => IconChoice.Mark, _ => IconChoice.Auto,
        }).ToString();

        try
        {
            Directory.CreateDirectory(Result.DataFolder);
            Result.Save();
        }
        catch (Exception ex)
        {
            _status.ForeColor = Color.FromArgb(170, 30, 20);
            _status.Text = $"Could not save: {ex.Message}";
            return;
        }

        DialogResult = DialogResult.OK;
        Close();
    }
}
