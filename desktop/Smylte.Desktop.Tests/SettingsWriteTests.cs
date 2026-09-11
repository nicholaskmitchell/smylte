using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// How settings.json reaches the disk, and who can read it afterwards.
///
/// Two failures, both silent, both only reachable off Windows — which is why
/// they arrived with the Linux client and why this file is new:
///
///   **Mode.** `File.WriteAllText` creates 0666 with the umask applied, so 0644
///   nearly everywhere. settings.json carries the server address, the username,
///   the GitHub token in CLEARTEXT and the encrypted password — and the key
///   that decrypts that password is deliberately written 0600 two directories
///   away. Protecting the key and publishing the token is not a threat model.
///
///   **Torn writes.** Truncating in place and then writing means a crash, a
///   full disk or a kill mid-write leaves a half-written file, and `Load`'s
///   `catch` answers that with a DEFAULT settings object — so the failure
///   presents as "the app forgot everything, and offers to set it up again"
///   rather than as an error anybody could act on.
///
/// Windows keeps the same code path minus the mode, so these run there too and
/// assert the half that applies.
/// Shares a collection with the other class that moves the XDG variables.
///
/// xunit runs test CLASSES in parallel by default — each one is its own
/// collection — and the environment is process-wide, so two classes pointing
/// `XDG_CONFIG_HOME` at two different temp directories at the same time are a
/// flake that reproduces about one run in three and never on the machine of
/// whoever is looking. Naming the same collection is what serialises them.
[Collection("xdg")]
public sealed class SettingsWriteTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("smylte-write").FullName;
    private readonly string? _config = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");

    public SettingsWriteTests() =>
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(_root, "config"));

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", _config);
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    private static Settings Saved()
    {
        var settings = Settings.Load();
        settings.ServerUrl = "https://example.invalid";
        settings.Username = "someone";
        settings.Save();
        return settings;
    }

    [Fact]
    public void Settings_json_is_readable_only_by_its_owner()
    {
        if (OperatingSystem.IsWindows()) return;   // ACLs, not a mode

        Saved();
        var mode = File.GetUnixFileMode(Settings.FilePath);

        // The same three bits PasswordProtector sets on the key file. Stated as
        // "nobody else at all" rather than as an octal, because the failure is
        // any of the six group/other bits being on.
        Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, mode);
    }

    [Fact]
    public void The_mode_is_set_as_the_file_is_created_not_after()
    {
        if (OperatingSystem.IsWindows()) return;

        // A chmod after the write leaves a window — however short — in which
        // the cleartext token is world-readable, and a reader that is already
        // watching the directory does not need it to be long. There is no way
        // to observe that window from here, so what is asserted instead is the
        // property that closes it: the file the bytes go into is the one that
        // carries the mode, so a temp file is never left behind wearing 0644.
        Saved();
        var leftovers = Directory.GetFiles(Path.GetDirectoryName(Settings.FilePath)!, "*.tmp");
        Assert.Empty(leftovers);
    }

    [Fact]
    public void A_save_that_dies_midway_leaves_the_previous_settings_intact()
    {
        var first = Saved();
        var before = File.ReadAllText(Settings.FilePath);

        // The torn write, simulated where it actually happens: a temp file that
        // never became the real one. An in-place truncate would have destroyed
        // `before` by this point; a write-then-rename cannot.
        File.WriteAllText(Settings.FilePath + ".tmp", "{ \"ServerUrl\": \"half");

        Assert.Equal(before, File.ReadAllText(Settings.FilePath));
        var reloaded = Settings.Load();
        Assert.Equal(first.ServerUrl, reloaded.ServerUrl);
        Assert.Equal(first.Username, reloaded.Username);
    }

    [Fact]
    public void Saving_over_an_existing_file_replaces_it_whole()
    {
        var settings = Saved();
        settings.ServerUrl = "https://elsewhere.invalid";
        settings.Save();

        var text = File.ReadAllText(Settings.FilePath);
        Assert.Contains("elsewhere.invalid", text);
        // A rename onto a shorter file cannot leave the old tail behind; an
        // in-place write without a truncate could.
        Assert.DoesNotContain("example.invalid", text);
        Assert.Equal("https://elsewhere.invalid", Settings.Load().ServerUrl);
    }

    // ── the browser profile ─────────────────────────────────────────────────

    [Fact]
    public void The_browser_profile_is_a_directory_nobody_else_can_enter()
    {
        if (OperatingSystem.IsWindows()) return;

        // What lives in here is cookies.sqlite, and what lives in THAT is the
        // seven-day session cookie — the whole perimeter for the account, since
        // the proxy keeps Max-Age when it rewrites Set-Cookie for the local
        // origin. libsoup creates the jar 0644; the directory is what actually
        // stops another local account reading it.
        var profile = Path.Combine(_root, "data", "profile");
        Settings.CreatePrivateDirectory(profile);

        Assert.Equal(
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute,
            File.GetUnixFileMode(profile));
    }

    [Fact]
    public void An_existing_profile_from_an_older_build_is_narrowed_rather_than_left()
    {
        if (OperatingSystem.IsWindows()) return;

        // `Directory.CreateDirectory(path, mode)` does NOT apply the mode to a
        // directory that already exists, so without the explicit narrowing
        // every installation that predates this fix would keep its 0755 — and
        // those are exactly the ones with a jar in them already.
        var profile = Path.Combine(_root, "legacy", "profile");
        Directory.CreateDirectory(profile);
        File.SetUnixFileMode(profile,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
            UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherExecute);

        Settings.CreatePrivateDirectory(profile);

        var mode = File.GetUnixFileMode(profile);
        Assert.False(mode.HasFlag(UnixFileMode.OtherRead));
        Assert.False(mode.HasFlag(UnixFileMode.OtherExecute));
        Assert.False(mode.HasFlag(UnixFileMode.GroupRead));
    }

    [Fact]
    public void Narrowing_a_path_that_is_not_there_is_not_an_error()
    {
        // The jar does not exist when SetPersistentStorage returns — libsoup
        // creates it lazily — so the client calls this on a path that usually
        // is not there yet. It must be a no-op rather than a throw inside a
        // constructor.
        Settings.MakePrivate(Path.Combine(_root, "nothing", "here.sqlite"));
    }
}
