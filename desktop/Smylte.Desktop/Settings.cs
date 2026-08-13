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

    /// Only needed while the repository is private; release-asset downloads are
    /// anonymous otherwise. A fine-grained PAT with Contents:read is enough.
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
