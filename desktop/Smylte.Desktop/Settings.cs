using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Smylte.Desktop;

/// Client configuration, in %APPDATA%\Smylte\settings.json.
///
/// The password is the only sensitive field and it is never written in the
/// clear: DPAPI encrypts it against the current Windows user, so a copied
/// settings.json is inert on another account or machine. Unprotect failing is
/// therefore an expected outcome, not an error — it means the file was roamed,
/// and the right response is to fall back to the app's own login screen.
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

    [JsonIgnore]
    public bool IsConfigured =>
        !string.IsNullOrWhiteSpace(ServerUrl) && !string.IsNullOrWhiteSpace(DataFolder);

    [JsonIgnore]
    public string WebRoot => Path.Combine(DataFolder, "web");

    [JsonIgnore]
    public string BrowserProfile => Path.Combine(DataFolder, "profile");

    private static string Dir => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Smylte");

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
        DataFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Smylte"),
    };

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        File.WriteAllText(FilePath, JsonSerializer.Serialize(this, Json));
    }

    public void SetPassword(string password)
    {
        if (string.IsNullOrEmpty(password)) { PasswordBlob = ""; return; }
        PasswordBlob = Convert.ToBase64String(ProtectedData.Protect(
            Encoding.UTF8.GetBytes(password), null, DataProtectionScope.CurrentUser));
    }

    public string GetPassword()
    {
        if (string.IsNullOrEmpty(PasswordBlob)) return "";
        try
        {
            return Encoding.UTF8.GetString(ProtectedData.Unprotect(
                Convert.FromBase64String(PasswordBlob), null, DataProtectionScope.CurrentUser));
        }
        catch (Exception)
        {
            return "";   // different user or machine; the web login screen takes over
        }
    }
}
