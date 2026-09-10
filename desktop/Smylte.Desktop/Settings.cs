using System.Text.Json;
using System.Text.Json.Serialization;

namespace Smylte.Desktop;

/// Client configuration, in `%APPDATA%\Smylte\settings.json` on Windows and
/// `~/.config/Smylte/settings.json` on Linux — one line, `SpecialFolder.ApplicationData`,
/// which .NET already maps to `$XDG_CONFIG_HOME`.
///
/// The password is the only sensitive field and it is never written in the
/// clear. PasswordProtector encrypts it against the current user — DPAPI on
/// Windows, a key derived from a 0600 file beside this one on Linux — so a
/// copied settings.json is inert on another account or machine. Failing to
/// decrypt is therefore an expected outcome, not an error: it means the file
/// was roamed, and the right response is to fall back to the app's own login
/// screen.
public sealed class Settings
{
    public string ServerUrl { get; set; } = "";
    public string Username { get; set; } = "";

    /// Base64 of the DPAPI (CurrentUser) blob. Never the password itself.
    public string PasswordBlob { get; set; } = "";

    public string DataFolder { get; set; } = "";

    /// Optional. The repository is public, so release assets download without
    /// one; this exists because anonymous GitHub API access is capped at 60
    /// requests an hour per IP. A launch spends one, which is ample on a normal
    /// connection and not necessarily ample behind a shared or CGNAT address.
    /// A fine-grained PAT with Contents:read is enough.
    public string GitHubToken { get; set; } = "";

    /// Deliberately stable across launches. localStorage is keyed by origin and
    /// the origin includes the port, so a port that moved would silently throw
    /// away the offline cache, the saved theme and the tab preferences on every
    /// start. LocalServer only picks a different one if this is genuinely taken.
    public int Port { get; set; } = 47821;

    /// What the last downloaded web build was, so an unchanged release is a
    /// single API call rather than a re-download.
    public long LastAssetId { get; set; }
    public string LastAssetStamp { get; set; } = "";

    /// SHA-256 of this exe, and the write time it was computed for. Hashing 69 MB
    /// on every launch to notice a new client would be silly; hashing it once per
    /// binary is free. The stamp is what makes the cache safe to trust.
    public string ClientDigest { get; set; } = "";
    public string ClientDigestStamp { get; set; } = "";

    /// Which app icon the window wears: Auto, Paper, Ink, Accent or Mark.
    /// Parsed leniently by IconLibrary — an unknown value falls back to Auto
    /// rather than refusing to start, because this is a cosmetic field that a
    /// hand-edited settings.json can easily get wrong.
    public string IconChoice { get; set; } = "Auto";

    /// Opt-in. Writes a Start-menu shortcut carrying the chosen icon and this
    /// app's AppUserModelID, which is the only supported way to reach the
    /// GROUPED taskbar button — the window's own icon never drives it. Off by
    /// default because the client otherwise installs nothing anywhere, and
    /// desktop/README.md makes a point of that.
    public bool StartMenuShortcut { get; set; }

    /// The last background the web app reported, as #RRGGBB, so the caption bar
    /// is already themed on the next launch instead of flashing the system
    /// default until the SPA has booted and pushed its colour over the bridge.
    /// Empty means "never reported" — leave the frame to Windows.
    public string TitleBarColor { get; set; } = "";

    public int WindowWidth { get; set; } = 1280;
    public int WindowHeight { get; set; } = 860;
    public bool WindowMaximized { get; set; }

    /// The floating focus window. Position and size are physical pixels of the
    /// monitor it was last on, the convention WindowWidth/Height already keep,
    /// with the DPI they were recorded at beside them so a restore on a
    /// differently scaled monitor rescales rather than landing off by the
    /// ratio. A width of 0 means never opened, so the default size applies;
    /// an off-screen rectangle (a monitor that is gone) falls back the same way.
    public int FloatX { get; set; } = -1;
    public int FloatY { get; set; } = -1;
    public int FloatWidth { get; set; }
    public int FloatHeight { get; set; }
    public int FloatDpi { get; set; }

    /// Whether the floating window stays above other windows. On by default:
    /// a floating clock that opens behind the thing you are working in is not
    /// floating.
    public bool FloatPinned { get; set; } = true;

    /// An escape hatch with no UI, for a hand-edited settings.json only. True
    /// lets the WebView2 runtime move the window from the page's own drag
    /// regions; false routes every drag through the bridge instead. Exists
    /// because CI cannot open a window, so the native path is proven only on
    /// real machines — and one where it misbehaves should not be stuck.
    ///
    /// Linux ignores it and always reports `nativeDrag: false`: WebKitGTK has
    /// no `app-region` support at all, so the bridge path is not a fallback
    /// there, it is the only path.
    public bool FloatNativeDrag { get; set; } = true;

    // ── Linux only ────────────────────────────────────────────────────────
    //
    // Read before GTK is touched and ignored entirely by the Windows client.
    // Both are the same shape as FloatNativeDrag above: no UI, a hand-edited
    // settings.json, and an escape hatch for a machine where the default is
    // wrong — because the failures they address cannot be reproduced in CI.

    /// `"x11"` or `"wayland"`. X11 is the default because three things the
    /// floating window needs — staying above other windows, opening where it
    /// was left, and keeping out of the taskbar — have no Wayland protocol an
    /// ordinary client can use, and GNOME implements no extension that would
    /// give them. Under XWayland all three work. The cost is that XWayland can
    /// look soft on a fractionally scaled display, which is why this is a
    /// setting and not a decision.
    public string Backend { get; set; } = "x11";

    /// Forces `WEBKIT_DISABLE_DMABUF_RENDERER=1`. WebKitGTK's DMA-BUF renderer
    /// paints nothing at all on the NVIDIA proprietary driver — a window frame
    /// around a white rectangle, with no error anywhere. The client already
    /// sets the variable when it finds `/proc/driver/nvidia/version`; this is
    /// for the machines that need it and do not look like that.
    public bool DisableDmabufRenderer { get; set; }

    [JsonIgnore]
    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ServerUrl) && !string.IsNullOrWhiteSpace(DataFolder);

    [JsonIgnore]
    public string WebRoot => Path.Combine(DataFolder, "web");

    [JsonIgnore]
    public string BrowserProfile => Path.Combine(DataFolder, "profile");

    /// `%APPDATA%\Smylte` on Windows; `$XDG_CONFIG_HOME/Smylte`, i.e.
    /// `~/.config/Smylte`, on Linux — .NET already maps ApplicationData that
    /// way, so no second spelling is needed to be XDG-correct.
    ///
    /// `internal` rather than `private` so PasswordProtector can put its key
    /// file beside settings.json. It is the one directory this client owns per
    /// user on both systems, and a second way of naming it would be a second
    /// thing to keep in step.
    internal static string Dir => Path.Combine(ConfigHome, "Smylte");

    /// `$XDG_CONFIG_HOME` / `%APPDATA%`, and `$XDG_DATA_HOME` / `%LOCALAPPDATA%`.
    internal static string ConfigHome => Home(Environment.SpecialFolder.ApplicationData, ".config");
    internal static string DataHome => Home(Environment.SpecialFolder.LocalApplicationData, ".local/share");

    /// A user directory that is always ABSOLUTE, even on a machine where it does
    /// not exist yet.
    ///
    /// `Environment.GetFolderPath(folder)` defaults to `SpecialFolderOption.None`,
    /// which VERIFIES the directory and returns an EMPTY STRING when it is
    /// missing or unreadable. Everything downstream then does
    /// `Path.Combine("", "Smylte", "settings.json")` and writes a relative path —
    /// so on a fresh account, a minimal container, or any user whose
    /// `~/.config` no XDG application has created yet, the file holding the
    /// encrypted password lands in whatever the working directory happened to
    /// be. Silent, and impossible to notice from inside the app: it saves, it
    /// loads, and it follows the user around by `cd`.
    ///
    /// Found by running the Linux client with XDG_DATA_HOME pointed at a
    /// directory that did not exist, which is why it is fixed here rather than
    /// only there — `%APPDATA%` always exists, so Windows was never going to
    /// show this, but the line was the same line.
    ///
    /// `Create` asks for the directory to be made (0700 on Unix) and returns
    /// the path. It can still come back empty if creation fails, so `$HOME` is
    /// the floor beneath it, and the current directory beneath that — by then
    /// there is nowhere better, and an absolute path is still better than a
    /// relative one.
    private static string Home(Environment.SpecialFolder folder, string fallback)
    {
        var path = Environment.GetFolderPath(folder, Environment.SpecialFolderOption.Create);
        if (!string.IsNullOrEmpty(path)) return path;

        var home = Environment.GetEnvironmentVariable("HOME");
        return Path.GetFullPath(string.IsNullOrEmpty(home) ? fallback : Path.Combine(home, fallback));
    }

    private static string FilePath => Path.Combine(Dir, "settings.json");

    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    public static Settings Load()
    {
        try
        {
            if (File.Exists(FilePath))
                return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? Fresh();
        }
        catch (Exception)
        {
            // A corrupt settings file must not brick the client — start over.
        }
        return Fresh();
    }

    private static Settings Fresh() => new()
    {
        DataFolder = Path.Combine(DataHome, "Smylte"),
    };

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        File.WriteAllText(FilePath, JsonSerializer.Serialize(this, Json));
    }

    // Both sides of the password now go through PasswordProtector, which picks
    // DPAPI on Windows and a key derived from a 0600 file beside this one
    // everywhere else. The signatures and the contract are unchanged — an empty
    // string out of GetPassword still means "show the app's own login screen" —
    // and a Windows blob written before that file existed still reads.
    public void SetPassword(string password) => PasswordBlob = PasswordProtector.Protect(password);

    public string GetPassword() => PasswordProtector.Unprotect(PasswordBlob);
}
