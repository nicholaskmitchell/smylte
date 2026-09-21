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
/// **Split in two, and the split is a bug fix rather than an arrangement.** The
/// first class exercises `Migrate` directly, in memory, and runs everywhere. The
/// second drives it through `Load`/`Save` and is Linux-only, because on Windows
/// it cannot be made safe: `Settings.ConfigHome` resolves `%APPDATA%` through
/// the shell's known-folder API, which does not consult `XDG_CONFIG_HOME` — so
/// the environment variables that isolate these tests on Linux do nothing there
/// and `Settings.FilePath` is the real installed client's file. An earlier
/// version of this file had no such guard, which meant two things on the
/// windows-latest CI leg: `A_fresh_install_is_already_current` was
/// order-dependent on a file the other facts had just created, and a developer
/// running the suite on their own Windows machine had their actual
/// settings.json overwritten with the legacy fixture below — server address,
/// username, encrypted password and GitHub token gone.
///
/// `SettingsPathTests` already guards every one of its cases the same way for
/// the same reason. Putting the logic coverage in a class that needs no
/// filesystem is what keeps the Windows leg from losing it entirely.
public sealed class SettingsMigrationTests
{
    /// A settings object as an OLDER client's file deserialises: no version
    /// recorded, because the field did not exist when it was written.
    private static Settings Legacy(string backend) => new()
    {
        ServerUrl = "https://smylte.example.com",
        Backend = backend,
        SettingsVersion = 0,
    };

    [Fact]
    public void An_installed_client_pinned_to_x11_is_promoted_to_auto()
    {
        // The whole point: without this the fix ships to nobody who already has
        // the client, which is everybody who has the problem.
        var settings = Legacy("x11");
        Assert.True(settings.Migrate());
        Assert.Equal("auto", settings.Backend);
        Assert.Equal(1, settings.SettingsVersion);
    }

    [Theory]
    [InlineData("X11")]
    [InlineData("  x11  ")]
    public void The_promotion_is_not_fooled_by_case_or_padding(string stored)
    {
        var settings = Legacy(stored);
        settings.Migrate();
        Assert.Equal("auto", settings.Backend);
    }

    [Theory]
    [InlineData("wayland")]
    [InlineData("auto")]
    [InlineData("")]
    public void Any_other_value_is_left_exactly_as_it_was(string stored)
    {
        var settings = Legacy(stored);
        settings.Migrate();
        Assert.Equal(stored, settings.Backend);
    }

    [Fact]
    public void The_promotion_does_not_run_twice()
    {
        // Someone who read the hint, set x11 back deliberately and restarted
        // must keep it. The version field is what distinguishes "the default
        // nobody chose" from "a choice", and it is only absent once.
        var settings = Legacy("x11");
        settings.SettingsVersion = 1;

        Assert.False(settings.Migrate());
        Assert.Equal("x11", settings.Backend);
    }

    [Fact]
    public void Migrating_reports_whether_it_changed_anything()
    {
        // `Load` persists on true and not on false, so a Migrate that claimed a
        // change it had not made would rewrite settings.json on every launch,
        // and one that denied a change it HAD made would never record the
        // version — which is the loop this return value exists to close.
        Assert.True(Legacy("x11").Migrate());
        Assert.True(Legacy("wayland").Migrate());          // the version still moves
        var current = Legacy("auto");
        current.SettingsVersion = 1;
        Assert.False(current.Migrate());
    }

    [Fact]
    public void Migrating_touches_nothing_but_the_backend_and_the_version()
    {
        // A migration that quietly dropped the server address or the stored
        // password would be far worse than the thing it is fixing.
        var settings = new Settings
        {
            ServerUrl = "https://smylte.example.com",
            Username = "nick",
            PasswordBlob = "AAAA",
            GitHubToken = "ghp_x",
            DataFolder = "/somewhere",
            Port = 51234,
            IconChoice = "Ink",
            FloatPinned = false,
            FloatX = 40,
            FloatY = 50,
            TitleBarColor = "#0C0C10",
            Backend = "x11",
            SettingsVersion = 0,
        };

        settings.Migrate();

        Assert.Equal("https://smylte.example.com", settings.ServerUrl);
        Assert.Equal("nick", settings.Username);
        Assert.Equal("AAAA", settings.PasswordBlob);
        Assert.Equal("ghp_x", settings.GitHubToken);
        Assert.Equal("/somewhere", settings.DataFolder);
        // Not the default (47821), so a migration that reset the object rather
        // than mutating it would show up here.
        Assert.Equal(51234, settings.Port);
        Assert.Equal("Ink", settings.IconChoice);
        Assert.False(settings.FloatPinned);
        Assert.Equal(40, settings.FloatX);
        Assert.Equal(50, settings.FloatY);
        Assert.Equal("#0C0C10", settings.TitleBarColor);
        Assert.Equal("auto", settings.Backend);
    }
}

/// `Load` and `Save` around the promotion — the part that needs a real file.
///
/// Linux only, and the guard is load-bearing rather than defensive: see the
/// note on the class above. Shares the `xdg` collection for the reason
/// SettingsPathTests gives — the environment is process-wide and xunit runs
/// classes in parallel, so two classes moving `XDG_CONFIG_HOME` at once is a
/// one-in-three flake that never reproduces for whoever is looking at it.
[Collection("xdg")]
public sealed class SettingsMigrationFileTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("smylte-migrate").FullName;
    private readonly string? _config = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
    private readonly string? _data = Environment.GetEnvironmentVariable("XDG_DATA_HOME");

    public SettingsMigrationFileTests()
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

    /// True on the platform where `Settings.FilePath` actually follows the
    /// environment this class sets. Every fact below returns early otherwise
    /// rather than writing to a path it does not control.
    private static bool Isolated => !OperatingSystem.IsWindows();

    /// Write a settings.json the way an OLDER client would have — by hand,
    /// rather than through `Save()`, so the version field is genuinely absent
    /// rather than defaulted.
    private static void WriteLegacy(string json)
    {
        Directory.CreateDirectory(Settings.Dir);
        File.WriteAllText(Settings.FilePath, json);
    }

    [Fact]
    public void Loading_an_older_file_promotes_it_and_writes_it_back_at_once()
    {
        if (!Isolated) return;

        WriteLegacy("""
            { "ServerUrl": "https://smylte.example.com", "Backend": "x11" }
            """);

        var settings = Settings.Load();
        Assert.Equal("auto", settings.Backend);

        // PERSISTED BY LOAD, with no Save of our own. Plenty of runs never
        // reach an ordinary save — `--check` and `--install` return first, a
        // missing native library returns 1 — and an unrecorded version means
        // the promotion runs again next launch, silently undoing a deliberate
        // `x11` every time.
        var onDisk = JsonSerializer.Deserialize<JsonElement>(File.ReadAllText(Settings.FilePath));
        Assert.Equal(1, onDisk.GetProperty("SettingsVersion").GetInt32());
        Assert.Equal("auto", onDisk.GetProperty("Backend").GetString());
        Assert.Equal("https://smylte.example.com", onDisk.GetProperty("ServerUrl").GetString());
    }

    [Fact]
    public void A_deliberate_x11_set_after_the_promotion_survives_a_restart()
    {
        if (!Isolated) return;

        // The end-to-end shape of the trap: promote, then let the user do what
        // Settings → Desktop's hint tells them to do, then restart.
        WriteLegacy("""{ "Backend": "x11" }""");
        Settings.Load();

        var text = File.ReadAllText(Settings.FilePath).Replace("\"auto\"", "\"x11\"");
        File.WriteAllText(Settings.FilePath, text);

        Assert.Equal("x11", Settings.Load().Backend);
    }

    [Fact]
    public void A_fresh_install_is_already_current()
    {
        if (!Isolated) return;

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
        if (!Isolated) return;

        WriteLegacy("{ not json at all");
        var settings = Settings.Load();
        Assert.Equal("auto", settings.Backend);
        Assert.Equal(1, settings.SettingsVersion);
    }
}
