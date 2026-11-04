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

    // ── a launch does not wait on GitHub for long ──────────────────────────

    private static readonly TimeSpan Short = TimeSpan.FromMilliseconds(50);

    [Fact]
    public async Task A_slow_check_opens_the_installed_build_and_finishes_later()
    {
        // The cold start that sat on an empty window: the release lookup gated
        // the first paint with a five-minute timeout. With a build on disk the
        // launch now stops waiting after its patience and hands back the check
        // still running, and the check is told it may not swap.
        MakeBuild(_settings.WebRoot, "installed");
        var answer = new TaskCompletionSource<UpdateResult>();
        Updater.SwapGate? seen = null;

        var result = await Updater.EnsureWebAssetsAsync(_settings, gate =>
        {
            seen = gate;
            return answer.Task;
        }, Short, CancellationToken.None);

        Assert.False(result.Updated);
        Assert.NotNull(result.Later);
        Assert.False(seen!.TryBeginSwap());

        answer.SetResult(new UpdateResult(false, "staged", ClientOutdated: true));
        Assert.True((await result.Later!).ClientOutdated);
    }

    [Fact]
    public async Task A_quick_check_is_used_as_it_always_was()
    {
        MakeBuild(_settings.WebRoot, "installed");

        var result = await Updater.EnsureWebAssetsAsync(_settings,
            _ => Task.FromResult(new UpdateResult(true, "Updated.", false)),
            TimeSpan.FromSeconds(30), CancellationToken.None);

        Assert.True(result.Updated);
        Assert.Null(result.Later);
    }

    [Fact]
    public async Task A_first_run_waits_as_long_as_the_download_takes()
    {
        // Nothing on disk to open instead, so patience does not apply.
        var result = await Updater.EnsureWebAssetsAsync(_settings, async gate =>
        {
            await Task.Delay(Short * 4);
            Assert.True(gate.TryBeginSwap());
            return new UpdateResult(true, "Updated.", false);
        }, Short, CancellationToken.None);

        Assert.True(result.Updated);
        Assert.Null(result.Later);
    }

    [Fact]
    public async Task A_swap_already_under_way_is_waited_for()
    {
        // The refresh won the gate just before the patience ran out: the folder
        // is mid-move, and serving it then would serve half a build.
        MakeBuild(_settings.WebRoot, "installed");
        var swapping = new TaskCompletionSource();

        var launch = Updater.EnsureWebAssetsAsync(_settings, async gate =>
        {
            Assert.True(gate.TryBeginSwap());
            await swapping.Task;
            return new UpdateResult(true, "Updated.", false);
        }, Short, CancellationToken.None);

        await Task.Delay(Short * 4);
        Assert.False(launch.IsCompleted);
        swapping.SetResult();

        var result = await launch;
        Assert.True(result.Updated);
        Assert.Null(result.Later);
    }

    // ── a build fetched after the window opened ────────────────────────────

    [Fact]
    public void A_staged_build_goes_live_on_the_next_start()
    {
        MakeBuild(_settings.WebRoot, "old");
        var unpacked = _settings.WebRoot + ".new";
        MakeBuild(unpacked, "new");

        Updater.Stage(_settings, unpacked, 42, "2026-11-04T00:00:00Z");
        Assert.Equal((42L, "2026-11-04T00:00:00Z"), Updater.StagedAsset(_settings));
        Assert.Equal("old", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));

        Updater.PromoteStagedBuild(_settings);

        Assert.Equal("new", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));
        Assert.False(Directory.Exists(Updater.StagedRoot(_settings)));
        Assert.False(Directory.Exists(_settings.WebRoot + ".old"));
        Assert.False(File.Exists(Path.Combine(_settings.WebRoot, ".smylte-asset")));
        Assert.Equal(42, _settings.LastAssetId);
        Assert.Equal("2026-11-04T00:00:00Z", _settings.LastAssetStamp);
    }

    [Fact]
    public void A_staged_folder_without_its_marker_is_discarded_not_served()
    {
        // Half-written: the move into `.next` is the last step of staging, but
        // a folder from anywhere else has no claim to be served.
        MakeBuild(_settings.WebRoot, "installed");
        MakeBuild(Updater.StagedRoot(_settings), "unknown");

        Updater.PromoteStagedBuild(_settings);

        Assert.Equal("installed", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));
        Assert.False(Directory.Exists(Updater.StagedRoot(_settings)));
    }

    [Fact]
    public void A_swap_leaves_the_new_build_live_and_no_old_copy()
    {
        MakeBuild(_settings.WebRoot, "old");
        MakeBuild(_settings.WebRoot + ".old", "older, left by a run that could not delete it");
        var incoming = _settings.WebRoot + ".new";
        MakeBuild(incoming, "new");

        Updater.SwapIn(_settings.WebRoot, incoming);

        Assert.Equal("new", File.ReadAllText(Path.Combine(_settings.WebRoot, "index.html")));
        Assert.False(Directory.Exists(incoming));
        Assert.False(Directory.Exists(_settings.WebRoot + ".old"));
    }

    [Fact]
    public void A_file_briefly_held_by_something_else_is_retried()
    {
        // Windows' scanner or indexer holding a just-written folder: refused
        // twice, then fine. Unretried, the update failed until a restart.
        var tries = 0;
        Updater.Retry(() =>
        {
            if (++tries < 3) throw new UnauthorizedAccessException("in use");
        });
        Assert.Equal(3, tries);
    }

    [Fact]
    public void A_refusal_that_lasts_is_still_reported()
    {
        var tries = 0;
        Assert.Throws<IOException>(() => Updater.Retry(() =>
        {
            tries++;
            throw new IOException("really in use");
        }, attempts: 3));
        Assert.Equal(3, tries);
    }
}
