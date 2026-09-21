using System.Text.Json;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The one-time promotion that lets a changed default reach a client that is
/// already installed.
///
/// `Save()` writes every property, so an installed settings.json holds an
/// explicit value for every field — including the ones nobody has ever touched.
/// That means changing a default reaches NEW installs only, and for the XWayland
/// fix that is precisely backwards: the machines with the problem are the ones
/// already running.
///
/// Shares the `xdg` collection for the reason SettingsPathTests gives: the
/// environment is process-wide and xunit runs classes in parallel, so two
/// classes moving `XDG_CONFIG_HOME` at once is a one-in-three flake that never
/// reproduces for whoever is looking at it.
[Collection("xdg")]
public sealed class SettingsMigrationTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("smylte-migrate").FullName;
    private readonly string? _config = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
    private readonly string? _data = Environment.GetEnvironmentVariable("XDG_DATA_HOME");

    public SettingsMigrationTests()
    {
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(_root, "config"));
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "data"));
    }

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", _config);
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", _data);
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    /// Write a settings.json the way an OLDER client would have — by hand,
    /// rather than through `Save()`, so the version field is genuinely absent
    /// rather than defaulted.
    private static void WriteLegacy(string json)
    {
        Directory.CreateDirectory(Settings.Dir);
        File.WriteAllText(Settings.FilePath, json);
    }

    [Fact]
    public void An_installed_client_pinned_to_x11_is_promoted_to_auto()
    {
        WriteLegacy("""
            { "ServerUrl": "https://smylte.example.com", "Backend": "x11" }
            """);

        var settings = Settings.Load();

        // The whole point: without this the fix ships to nobody who already has
        // the client, which is everybody who has the problem.
        Assert.Equal("auto", settings.Backend);
        Assert.Equal(1, settings.SettingsVersion);
    }

    [Fact]
    public void An_explicit_wayland_is_left_alone()
    {
        WriteLegacy("""{ "Backend": "wayland" }""");
        Assert.Equal("wayland", Settings.Load().Backend);
    }

    [Fact]
    public void The_promotion_does_not_run_twice()
    {
        // Someone who read the hint, set x11 back deliberately and restarted
        // must keep it. The version field is what distinguishes "the default
        // nobody chose" from "a choice", and it is only absent once.
        WriteLegacy("""{ "Backend": "x11", "SettingsVersion": 1 }""");
        Assert.Equal("x11", Settings.Load().Backend);
    }

    [Fact]
    public void A_fresh_install_is_already_current()
    {
        // No file at all. Marking it version 0 would run every future migration
        // against a brand new install.
        Assert.False(File.Exists(Settings.FilePath));
        var settings = Settings.Load();
        Assert.Equal(1, settings.SettingsVersion);
        Assert.Equal("auto", settings.Backend);
    }

    [Fact]
    public void A_corrupt_file_still_starts_over_rather_than_throwing()
    {
        WriteLegacy("{ not json at all");
        var settings = Settings.Load();
        Assert.Equal("auto", settings.Backend);
        Assert.Equal(1, settings.SettingsVersion);
    }

    [Fact]
    public void Migrating_preserves_everything_else_in_the_file()
    {
        // A migration that quietly dropped the server address or the stored
        // password would be far worse than the thing it is fixing.
        WriteLegacy("""
            {
              "ServerUrl": "https://smylte.example.com",
              "Username": "nick",
              "PasswordBlob": "AAAA",
              "GitHubToken": "ghp_x",
              "Port": 47821,
              "Backend": "x11",
              "IconChoice": "Ink",
              "FloatPinned": false,
              "TitleBarColor": "#0C0C10"
            }
            """);

        var settings = Settings.Load();
        Assert.Equal("https://smylte.example.com", settings.ServerUrl);
        Assert.Equal("nick", settings.Username);
        Assert.Equal("AAAA", settings.PasswordBlob);
        Assert.Equal("ghp_x", settings.GitHubToken);
        Assert.Equal(47821, settings.Port);
        Assert.Equal("Ink", settings.IconChoice);
        Assert.False(settings.FloatPinned);
        Assert.Equal("#0C0C10", settings.TitleBarColor);
        Assert.Equal("auto", settings.Backend);
    }

    [Fact]
    public void The_promoted_value_survives_a_save_and_reload()
    {
        WriteLegacy("""{ "Backend": "x11" }""");
        var settings = Settings.Load();
        settings.Save();

        // Migrate does not save on its own — the next ordinary Save persists it.
        // If that round trip ever stopped carrying the version, the promotion
        // would run again on every launch and undo a deliberate x11 every time.
        var reloaded = Settings.Load();
        Assert.Equal("auto", reloaded.Backend);
        Assert.Equal(1, reloaded.SettingsVersion);

        var onDisk = JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(Settings.FilePath));
        Assert.Equal(1, onDisk.GetProperty("SettingsVersion").GetInt32());
    }
}
