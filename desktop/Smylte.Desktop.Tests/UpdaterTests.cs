using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The two ways a failed update used to cost someone their working client.
///
/// Neither test touches the network: the release lookup and the asset download
/// are GitHub's, but the behaviour the findings are about is what happens around
/// them — whether a throw is fatal, and what the next launch makes of a
/// half-finished directory swap.
public sealed class UpdaterTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-up").FullName;
    private readonly Settings _settings;
    private readonly List<string> _log = new();

    public UpdaterTests()
    {
        _settings = new Settings { DataFolder = _dir };
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    private IProgress<string> Log => new Progress<string>(_log.Add);

    private static void MakeBuild(string dir, string marker)
    {
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "index.html"), marker);
    }

    // ── a failed download must not take the installed build with it ────────

    [Fact]
    public async Task A_download_that_throws_leaves_an_installed_client_openable()
    {
        // AUDIT: the release lookup degraded to "Offline — using the installed
        // build", but the download and swap that followed had no such guard, so a
        // dropped connection or a truncated zip threw straight out of startup
        // with a complete working build sitting on disk.
        var kept = await Updater.SwapOrKeepLocalAsync(
            () => throw new HttpRequestException("connection reset"),
            haveLocal: true, clientOutdated: false, log: Log);

        Assert.NotNull(kept);
        Assert.False(kept!.Updated);
        Assert.Contains("using the installed build", kept.Message, StringComparison.Ordinal);
        Assert.Contains("connection reset", kept.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task A_download_that_throws_on_a_first_run_still_surfaces_the_error()
    {
        // The control, and the half of this that must NOT change: with nothing on
        // disk there is nothing to fall back to, so swallowing the failure would
        // hand the user an empty window instead of a reason.
        await Assert.ThrowsAsync<HttpRequestException>(() => Updater.SwapOrKeepLocalAsync(
            () => throw new HttpRequestException("connection reset"),
            haveLocal: false, clientOutdated: false, log: Log));
    }

    [Fact]
    public async Task A_successful_swap_reports_nothing_and_lets_the_caller_continue()
    {
        // Returning null is how the caller knows to record the new asset id; a
        // guard that swallowed success would freeze the client on one build.
        var kept = await Updater.SwapOrKeepLocalAsync(
            () => Task.CompletedTask, haveLocal: true, clientOutdated: false, log: Log);

        Assert.Null(kept);
        Assert.Empty(_log);
    }

    [Fact]
    public async Task The_client_outdated_notice_survives_a_failed_download()
    {
        // It is decided from the release payload, which was already fetched
        // successfully — losing it because the *web* download failed would hide a
        // stale exe behind an unrelated error.
        var kept = await Updater.SwapOrKeepLocalAsync(
            () => throw new IOException("disk full"),
            haveLocal: true, clientOutdated: true, log: Log);

        Assert.True(kept!.ClientOutdated);
    }

    // ── a swap interrupted between the two moves ───────────────────────────

    [Fact]
    public void A_build_stranded_in_web_old_is_recovered_on_the_next_run()
    {
        // AUDIT: the swap is `web` -> `web.old`, then `web.new` -> `web`. A
        // process killed BETWEEN them — window closed, reboot, installer
        // terminated — left the only working copy in `web.old` and no `web` at
        // all, and nothing ever looked there again.
        MakeBuild(_settings.WebRoot + ".old", "the only copy");
        Assert.False(Directory.Exists(_settings.WebRoot));

        Updater.RecoverStrandedBuild(_settings);

        Assert.True(File.Exists(Path.Combine(_settings.WebRoot, "index.html")));
        Assert.Equal("the only copy", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));
        Assert.False(Directory.Exists(_settings.WebRoot + ".old"));
    }

    [Fact]
    public void A_current_build_is_never_replaced_by_a_leftover_old_one()
    {
        // The control, and the failure mode a careless recovery would introduce:
        // `web.old` outliving a *successful* swap must not overwrite the build
        // that replaced it — that would silently roll the client backwards.
        MakeBuild(_settings.WebRoot, "current");
        MakeBuild(_settings.WebRoot + ".old", "previous");

        Updater.RecoverStrandedBuild(_settings);

        Assert.Equal("current", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));
    }

    [Fact]
    public void A_stranded_build_counts_as_installed_when_startup_asks()
    {
        // The recovery is only worth anything if it runs BEFORE the "do we have a
        // build?" question every fallback below depends on. Ask the question the
        // way startup asks it: a launch that finds only `web.old` must answer yes,
        // or it treats an interrupted update as a first install.
        MakeBuild(_settings.WebRoot + ".old", "the only copy");

        Assert.True(Updater.HaveLocalBuild(_settings));
    }

    [Fact]
    public void A_machine_with_no_build_at_all_says_so()
    {
        // The control: recovery must not make an empty data folder look installed.
        Assert.False(Updater.HaveLocalBuild(_settings));
    }

    [Fact]
    public void A_genuine_first_run_is_left_alone()
    {
        // Neither directory exists: recovery has nothing to do and must not
        // create anything, or the download that follows would extract into a
        // directory it did not make.
        Updater.RecoverStrandedBuild(_settings);

        Assert.False(Directory.Exists(_settings.WebRoot));
        Assert.False(Directory.Exists(_settings.WebRoot + ".old"));
    }
}
