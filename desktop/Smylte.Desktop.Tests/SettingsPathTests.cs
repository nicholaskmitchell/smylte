using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Where the client puts its own files.
///
/// One assertion, made three ways, and it is worth a file because the failure it
/// guards is silent from every direction. `Environment.GetFolderPath(folder)`
/// defaults to `SpecialFolderOption.None`, which VERIFIES the directory and
/// returns an EMPTY STRING when it does not exist — so `Path.Combine("",
/// "Smylte", "settings.json")` is a RELATIVE path, and the file holding the
/// encrypted password is written into whatever the working directory happened
/// to be. It saves, it loads, and it follows the user around by `cd`.
///
/// Not reachable on Windows, where `%APPDATA%` always exists. Very reachable on
/// Linux: a fresh account, a minimal container, a service user, or anyone whose
/// `~/.config` no XDG application has created yet. It was found by pointing
/// XDG_DATA_HOME at a directory that was not there and watching a desktop entry
/// land in the current directory.
///
/// These run on both runners. The Windows leg proves the fix costs nothing
/// there; the Linux leg is the one that can actually go red.
/// Shares a collection with the other class that moves the XDG variables.
///
/// xunit runs test CLASSES in parallel by default — each one is its own
/// collection — and the environment is process-wide, so two classes pointing
/// `XDG_CONFIG_HOME` at two different temp directories at the same time are a
/// flake that reproduces about one run in three and never on the machine of
/// whoever is looking. Naming the same collection is what serialises them.
[Collection("xdg")]
public sealed class SettingsPathTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("smylte-xdg").FullName;
    private readonly string? _config = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
    private readonly string? _data = Environment.GetEnvironmentVariable("XDG_DATA_HOME");

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", _config);
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", _data);
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    [Fact]
    public void The_settings_directory_is_absolute_even_when_nothing_has_created_it()
    {
        if (OperatingSystem.IsWindows()) return;   // %APPDATA% is always there

        // Deliberately not created. This is the state of a home directory no
        // XDG application has written to yet.
        var missing = Path.Combine(_root, "never-made", "config");
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", missing);

        Assert.True(Path.IsPathRooted(Settings.Dir),
            $"Settings.Dir is relative ({Settings.Dir}); settings.json would follow the CWD");
        Assert.StartsWith(missing, Settings.Dir, StringComparison.Ordinal);
    }

    [Fact]
    public void The_data_directory_is_absolute_even_when_nothing_has_created_it()
    {
        if (OperatingSystem.IsWindows()) return;

        var missing = Path.Combine(_root, "never-made", "data");
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", missing);

        Assert.True(Path.IsPathRooted(Settings.DataHome),
            $"Settings.DataHome is relative ({Settings.DataHome})");
        Assert.StartsWith(missing, Settings.DataHome, StringComparison.Ordinal);
    }

    [Fact]
    public void Asking_for_the_directory_is_what_creates_it()
    {
        if (OperatingSystem.IsWindows()) return;

        // `SpecialFolderOption.Create` is the whole fix, and this is the half
        // that makes the path usable rather than merely absolute.
        var missing = Path.Combine(_root, "made-on-demand");
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", missing);

        Assert.Equal(Path.Combine(missing, "Smylte"), Settings.Dir);
        Assert.True(Directory.Exists(missing));
    }

    [Fact]
    public void The_two_homes_are_not_the_same_directory()
    {
        // Config and data are different XDG roots, and conflating them would put
        // the downloaded web build beside the credentials — which is the layout
        // desktop/README.md documents as separate.
        Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(_root, "c"));
        Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "d"));
        if (OperatingSystem.IsWindows()) return;

        Assert.NotEqual(Settings.ConfigHome, Settings.DataHome);
    }
}
