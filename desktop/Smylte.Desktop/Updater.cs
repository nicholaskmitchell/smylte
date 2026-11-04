using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;

namespace Smylte.Desktop;

/// <param name="ClientOutdated">
/// The published Smylte.exe is not the one running. The client cannot replace
/// itself, so this only ever drives a notice.
/// </param>
/// <param name="Later">
/// Set when the launch stopped waiting for the update check and opened the
/// installed build: the check, still running. Its own result arrives when it
/// finishes, so the window can still raise the client notice from it. A build
/// it downloads is staged for the next start rather than swapped under the
/// page that is being served from it.
/// </param>
public sealed record UpdateResult(
    bool Updated, string Message, bool ClientOutdated, Task<UpdateResult>? Later = null);

/// Keeps the local copy of the web build in step with what CI published.
///
/// The client never builds anything and never clones the repository: CI runs the
/// same typecheck, tests and `vite build` the deploy already depends on, then
/// attaches the result to a rolling `desktop-latest` release. This reads that
/// release and unpacks it. That is what makes the exe a thing you install once.
public static class Updater
{
    private const string Owner = "nicholaskmitchell";
    private const string Repo = "smylte";
    private const string Tag = "desktop-latest";
    private const string AssetName = "smylte-web.zip";

    /// The client binary for the OS this process is running on.
    ///
    /// One release carries both, because there is one web build and it is
    /// platform-neutral — `smylte-web.zip` is the same bytes for everybody, and
    /// splitting the release would mean two things to keep in step for no gain.
    /// The client asset is the only per-platform half, and each client only
    /// ever asks about its own: a Linux client comparing digests against
    /// Smylte.exe would offer an update to a binary it cannot run.
    internal const string WindowsClientAsset = "Smylte.exe";
    internal const string LinuxClientAsset = "Smylte-linux-x86_64";

    internal static string ClientAssetName =>
        OperatingSystem.IsWindows() ? WindowsClientAsset : LinuxClientAsset;

    /// Where to send someone whose client is out of date. The release is rolling,
    /// so this link never changes and always has the current exe behind it.
    public const string ReleaseUrl =
        $"https://github.com/{Owner}/{Repo}/releases/tag/{Tag}";

    /// How long a launch with a build already on disk waits for the update
    /// check before opening that build.
    ///
    /// The check used to gate the first paint outright: a GitHub API call under
    /// a five-minute timeout, then the download, then the sign-in, all before
    /// the page existed. On a cold start, with DNS, TLS and a slow or half-open
    /// route all still to be paid for, that was a window with nothing in it for
    /// fifteen seconds. An answer inside this budget is used as it always was,
    /// so the usual case (a fast "up to date", or a small build that downloads
    /// quickly) is unchanged; a slower one finishes in the background and its
    /// build is in place on the next start.
    internal static readonly TimeSpan LaunchPatience = TimeSpan.FromSeconds(3);

    /// The check a launch gave up waiting for, while it is still running. One
    /// per process: a second start (a setup save) must not race a download that
    /// is still writing the same zip and the same staging folder.
    private static Task<UpdateResult>? _background;
    private static readonly object BackgroundLock = new();

    public static Task<UpdateResult> EnsureWebAssetsAsync(
        Settings settings, IProgress<string> log, CancellationToken ct) =>
        EnsureWebAssetsAsync(
            settings, gate => RefreshAsync(settings, gate, log, ct), LaunchPatience, ct);

    /// The launch policy, with the network half passed in so it can be tested
    /// without GitHub. `refresh` is handed the gate it must pass before it may
    /// touch the live build.
    internal static async Task<UpdateResult> EnsureWebAssetsAsync(
        Settings settings, Func<SwapGate, Task<UpdateResult>> refresh, TimeSpan patience,
        CancellationToken ct)
    {
        // A build a previous run downloaded after its window was up goes live
        // now, before anything serves from the folder. Local and quick.
        PromoteStagedBuild(settings);

        lock (BackgroundLock)
        {
            if (_background is { IsCompleted: false } running)
                return new UpdateResult(false, "Checking for updates in the background.", false, running);
        }

        // Asked before the refresh starts, which asks it again: both recover a
        // stranded build, and the two must not race to move the same folder.
        var haveLocal = HaveLocalBuild(settings);
        var gate = new SwapGate();
        var work = refresh(gate);

        // A first run has nothing to open instead, so it waits as long as it takes.
        if (!haveLocal) return await work.ConfigureAwait(false);

        var first = await Task.WhenAny(work, Task.Delay(patience, ct)).ConfigureAwait(false);
        if (first == work) return await work.ConfigureAwait(false);

        // Only if the refresh has not already begun swapping: a swap in progress
        // is a couple of directory renames, and the folder must not be served
        // half-moved. Waiting for it is the cheaper answer.
        if (!gate.TryGiveUp()) return await work.ConfigureAwait(false);

        lock (BackgroundLock) _background = work;
        return new UpdateResult(false, "Checking for updates in the background.", false, work);
    }

    /// Who may touch the live build: the refresh, by swapping a new one in, or
    /// the launch, by serving the old one. Exactly one of them wins.
    internal sealed class SwapGate
    {
        private const int Waiting = 0, Swapping = 1, GaveUp = 2;
        private int _state;

        /// The refresh asks before it swaps. False means the window is already
        /// serving the installed build: stage the new one instead.
        public bool TryBeginSwap() =>
            Interlocked.CompareExchange(ref _state, Swapping, Waiting) == Waiting;

        /// The launch asks before it stops waiting. False means a swap has begun.
        public bool TryGiveUp() =>
            Interlocked.CompareExchange(ref _state, GaveUp, Waiting) == Waiting;
    }

    private static async Task<UpdateResult> RefreshAsync(
        Settings settings, SwapGate gate, IProgress<string> log, CancellationToken ct)
    {
        // Off the caller's thread from the first line: the launch is timing this
        // task against its patience, and a synchronous stretch here (the hash of
        // our own exe, below) would be time the timer never got to count.
        await Task.Yield();

        var haveLocal = HaveLocalBuild(settings);

        JsonElement release;
        try
        {
            log.Report("Checking for updates…");
            release = await FetchReleaseAsync(settings, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            // Offline or rate-limited. An installed client must still open; only a
            // first run has nothing to fall back to.
            if (haveLocal) return new UpdateResult(false, "Offline — using the installed build.", false);
            throw new InvalidOperationException(
                "Could not reach GitHub to download the app, and there is no local copy yet. "
                + "Check the connection. If this keeps happening, a GitHub token in settings "
                + "raises the API rate limit.", ex);
        }

        // Free: the exe's digest is in the release payload already fetched, so
        // noticing a new client costs no extra request.
        var clientOutdated = IsClientOutdated(FindAsset(release, ClientAssetName), settings);

        if (FindAsset(release, AssetName) is not { } asset)
        {
            if (haveLocal) return new UpdateResult(false, "Up to date.", clientOutdated);
            throw new InvalidOperationException(
                $"The {Tag} release has no {AssetName} asset, and there is no local copy yet.");
        }

        var id = asset.GetProperty("id").GetInt64();
        var stamp = asset.TryGetProperty("updated_at", out var u) ? u.GetString() ?? "" : "";

        if (haveLocal && id == settings.LastAssetId && stamp == settings.LastAssetStamp)
            return new UpdateResult(false, "Up to date.", clientOutdated);
        if (haveLocal && StagedAsset(settings) == (id, stamp))
            return new UpdateResult(false, "The latest build is ready for the next start.", clientOutdated);

        log.Report("Downloading the latest build…");
        var installed = false;
        if (await SwapOrKeepLocalAsync(
                async () => installed = await DownloadAndInstallAsync(
                    settings, gate, id, stamp, log, ct).ConfigureAwait(false),
                haveLocal, clientOutdated, log).ConfigureAwait(false) is { } kept)
            return kept;

        if (!installed)
            return new UpdateResult(false, "The latest build is ready for the next start.", clientOutdated);

        settings.LastAssetId = id;
        settings.LastAssetStamp = stamp;
        settings.Save();

        return new UpdateResult(true, "Updated to the latest build.", clientOutdated);
    }

    /// Run the download and swap, degrading to the installed build if it throws.
    /// Returns null when the swap succeeded and the caller should carry on.
    ///
    /// The release LOOKUP already degrades this way when it fails; the download
    /// did not, so a dropped connection, a truncated zip or a failed directory
    /// move threw straight out of startup with a complete working build sitting
    /// on disk. An update is an improvement, not a precondition for opening the
    /// app. Only when `haveLocal` — a first run has nothing to fall back to and
    /// must still surface the error.
    ///
    /// Taking a delegate rather than inlining the try/catch is what lets the
    /// guard be tested without a GitHub round-trip: the property that matters is
    /// "a throw here is fatal on a first run and survivable once a build exists".
    internal static async Task<UpdateResult?> SwapOrKeepLocalAsync(
        Func<Task> swap, bool haveLocal, bool clientOutdated, IProgress<string> log)
    {
        try
        {
            await swap().ConfigureAwait(false);
            return null;
        }
        catch (Exception ex) when (haveLocal)
        {
            log.Report("Update failed — using the installed build.");
            return new UpdateResult(
                false, $"Update failed ({ex.Message}) — using the installed build.", clientOutdated);
        }
    }

    /// Recover anything a previous run stranded, then say whether a usable build
    /// is on disk. The order is the point — every "can the app still open?"
    /// decision below reads this answer, so the recovery has to have happened
    /// before it is computed, not after.
    internal static bool HaveLocalBuild(Settings settings)
    {
        RecoverStrandedBuild(settings);
        return File.Exists(Path.Combine(settings.WebRoot, "index.html"));
    }

    /// Put back a build stranded by an interrupted swap.
    ///
    /// `DownloadAndSwapAsync` moves `web` aside to `web.old` and then moves
    /// `web.new` into place. The catch there covers a throw from the second
    /// move — but a process killed BETWEEN them (the window closed, a reboot,
    /// the installer terminated) leaves the only working copy in `web.old` with
    /// no `web` at all, and nothing ever looked there again: the next run simply
    /// saw `haveLocal == false` and treated it as a first install.
    internal static void RecoverStrandedBuild(Settings settings)
    {
        var root = settings.WebRoot;
        var previous = root + ".old";
        if (Directory.Exists(root) || !Directory.Exists(previous)) return;
        try { Directory.Move(previous, root); }
        catch (Exception) { /* best effort; the download below still runs */ }
    }

    /// Is the published exe a different binary from the one running?
    ///
    /// Compared by content hash rather than a version number, because a version
    /// number has to be remembered — a forgotten bump would silently ship a client
    /// nobody is told about. A digest cannot be forgotten.
    ///
    /// What makes a digest an honest signal is the other end: desktop-release.yml
    /// re-publishes the exe only when desktop/Smylte.Desktop changed, because a
    /// self-contained bundle is never the same bytes twice and uploading it on
    /// every push made every push look like a new client.
    ///
    /// Every uncertain path returns false. A missing digest field, an unreadable
    /// exe, an unexpected format: none of those are evidence of being out of date,
    /// and a false alarm here sends someone to re-download 69 MB for nothing.
    private static bool IsClientOutdated(JsonElement? clientAsset, Settings settings)
    {
        if (clientAsset is not { } asset) return false;
        if (!asset.TryGetProperty("digest", out var field)) return false;
        if (field.GetString() is not { Length: > 0 } published) return false;

        var local = LocalClientDigest(settings);
        return local is not null && !string.Equals(local, published, StringComparison.OrdinalIgnoreCase);
    }

    private static string? LocalClientDigest(Settings settings)
    {
        var path = Environment.ProcessPath;
        if (path is null || !File.Exists(path)) return null;

        try
        {
            var stamp = File.GetLastWriteTimeUtc(path).Ticks.ToString(CultureInfo.InvariantCulture);
            if (settings.ClientDigestStamp == stamp && settings.ClientDigest.Length > 0)
                return settings.ClientDigest;

            using var stream = File.OpenRead(path);
            var digest = "sha256:" + Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();

            settings.ClientDigest = digest;
            settings.ClientDigestStamp = stamp;
            settings.Save();
            return digest;
        }
        catch (Exception)
        {
            return null;   // cannot read our own exe; say nothing rather than guess
        }
    }

    private static JsonElement? FindAsset(JsonElement release, string name)
    {
        if (!release.TryGetProperty("assets", out var assets)) return null;
        foreach (var asset in assets.EnumerateArray())
            if (asset.TryGetProperty("name", out var n) && n.GetString() == name)
                return asset;
        return null;
    }

    private static HttpClient MakeClient(Settings settings)
    {
        var http = new HttpClient(new SocketsHttpHandler
        {
            AutomaticDecompression = DecompressionMethods.All,
        })
        {
            Timeout = TimeSpan.FromMinutes(5),
        };

        // GitHub rejects requests without a User-Agent outright.
        http.DefaultRequestHeaders.UserAgent.ParseAdd("Smylte-Desktop/1.0");
        if (!string.IsNullOrWhiteSpace(settings.GitHubToken))
            http.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", settings.GitHubToken.Trim());
        return http;
    }

    private static async Task<JsonElement> FetchReleaseAsync(Settings settings, CancellationToken ct)
    {
        using var http = MakeClient(settings);
        using var req = new HttpRequestMessage(HttpMethod.Get,
            $"https://api.github.com/repos/{Owner}/{Repo}/releases/tags/{Tag}");
        req.Headers.Accept.ParseAdd("application/vnd.github+json");

        using var resp = await http.SendAsync(req, ct).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(body);
        return doc.RootElement.Clone();   // the JsonDocument is about to be disposed
    }

    /// Fetch one release asset to `destination`, saying how far along it is.
    private static async Task DownloadAssetAsync(
        Settings settings, long assetId, string destination, string what,
        IProgress<string> log, CancellationToken ct)
    {
        using var http = MakeClient(settings);
        using var req = new HttpRequestMessage(HttpMethod.Get,
            $"https://api.github.com/repos/{Owner}/{Repo}/releases/assets/{assetId}");
        // The asset endpoint (rather than browser_download_url) is what makes
        // this work unchanged whether the repository is public or private.
        req.Headers.Accept.ParseAdd("application/octet-stream");

        using var resp = await http
            .SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        var total = resp.Content.Headers.ContentLength;
        var source = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await using (source.ConfigureAwait(false))
        await using (var file = File.Create(destination))
        {
            // Progress by the megabyte: the exe is ~69 MB and a label that says
            // "Downloading…" for a minute reads as hung.
            var buffer = new byte[1 << 16];
            long done = 0, shown = 0;
            int n;
            while ((n = await source.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
            {
                await file.WriteAsync(buffer.AsMemory(0, n), ct).ConfigureAwait(false);
                done += n;
                if (done - shown >= 4 << 20)
                {
                    shown = done;
                    log.Report(ProgressText(what, done, total));
                }
            }
        }
    }

    internal static string ProgressText(string what, long done, long? total)
    {
        var mb = done >> 20;
        return total is { } t
            ? $"{what} {mb} of {Math.Max(1, t >> 20)} MB"
            : $"{what} {mb} MB";
    }

    /// Download and unpack the build, then put it live, or, when the window is
    /// already serving the installed one, stage it for the next start. True when
    /// it went live.
    private static async Task<bool> DownloadAndInstallAsync(
        Settings settings, SwapGate gate, long assetId, string stamp,
        IProgress<string> log, CancellationToken ct)
    {
        var zipPath = Path.Combine(Path.GetTempPath(), $"smylte-web-{assetId}.zip");
        await DownloadAssetAsync(settings, assetId, zipPath, "Downloading the latest build…", log, ct)
            .ConfigureAwait(false);

        log.Report("Installing…");

        var staging = settings.WebRoot + ".new";
        if (Directory.Exists(staging)) Retry(() => Directory.Delete(staging, recursive: true));
        Directory.CreateDirectory(Path.GetDirectoryName(settings.WebRoot)!);
        ZipFile.ExtractToDirectory(zipPath, staging);
        try { File.Delete(zipPath); } catch (Exception) { /* temp file; not worth failing over */ }

        if (gate.TryBeginSwap())
        {
            SwapIn(settings.WebRoot, staging);
            return true;
        }

        Stage(settings, staging, assetId, stamp);
        return false;
    }

    /// Put `incoming` where `root` is, keeping the old copy until the new one is
    /// in place so a failure between the two steps still leaves a working
    /// install to roll back to.
    ///
    /// Every move and delete is retried. On Windows a folder that was written a
    /// moment ago is routinely held for a few hundred milliseconds by the
    /// antivirus scanner or the search indexer, and the move fails with "access
    /// denied" though nothing is wrong. Unretried, that failed the update, and
    /// because the leftover `.old` then failed to delete at the top of the next
    /// attempt, it went on failing until a restart let go of it. The final
    /// delete of the old copy cannot fail the update at all: the new build is
    /// already live, and the next start clears it.
    internal static void SwapIn(string root, string incoming)
    {
        var previous = root + ".old";
        if (Directory.Exists(previous)) Retry(() => Directory.Delete(previous, recursive: true));

        if (Directory.Exists(root)) Retry(() => Directory.Move(root, previous));
        try
        {
            Retry(() => Directory.Move(incoming, root));
        }
        catch (Exception)
        {
            if (!Directory.Exists(root) && Directory.Exists(previous)) Directory.Move(previous, root);
            throw;
        }

        try { if (Directory.Exists(previous)) Retry(() => Directory.Delete(previous, recursive: true)); }
        catch (Exception) { /* live already; RecoverStrandedBuild ignores it while `root` exists */ }
    }

    /// The file inside a staged build that says which release asset it is.
    private const string StagedMarker = ".smylte-asset";

    internal static string StagedRoot(Settings settings) => settings.WebRoot + ".next";

    /// Keep a downloaded build for the next start. Written into the folder
    /// rather than into settings: this runs on a background thread while the
    /// window owns the settings, and the marker and the build it describes then
    /// move together or not at all.
    internal static void Stage(Settings settings, string unpacked, long assetId, string stamp)
    {
        var next = StagedRoot(settings);
        if (Directory.Exists(next)) Retry(() => Directory.Delete(next, recursive: true));
        File.WriteAllText(Path.Combine(unpacked, StagedMarker),
            assetId.ToString(CultureInfo.InvariantCulture) + "\n" + stamp);
        Retry(() => Directory.Move(unpacked, next));
    }

    /// Which asset is staged, or null when nothing usable is.
    internal static (long Id, string Stamp)? StagedAsset(Settings settings)
    {
        var next = StagedRoot(settings);
        try
        {
            if (!File.Exists(Path.Combine(next, "index.html"))) return null;
            var lines = File.ReadAllText(Path.Combine(next, StagedMarker)).Split('\n', 2);
            if (!long.TryParse(lines[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var id))
                return null;
            return (id, lines.Length > 1 ? lines[1] : "");
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// Make a staged build the live one, before anything serves from the folder.
    /// Best effort: a build that will not move is left staged and the installed
    /// one opens, which is what would have happened without it.
    internal static void PromoteStagedBuild(Settings settings)
    {
        var next = StagedRoot(settings);
        if (!Directory.Exists(next)) return;

        if (StagedAsset(settings) is not { } staged)
        {
            // Half-written or from a build that predates the marker: not
            // something to serve. Cleared so it is not looked at again.
            try { Directory.Delete(next, recursive: true); } catch (Exception) { }
            return;
        }

        try
        {
            RecoverStrandedBuild(settings);
            SwapIn(settings.WebRoot, next);
            // After the move, so a swap that fails leaves the build staged and
            // still named. Served, it would only be a stray dotfile.
            try { File.Delete(Path.Combine(settings.WebRoot, StagedMarker)); } catch (Exception) { }
        }
        catch (Exception)
        {
            return;
        }

        settings.LastAssetId = staged.Id;
        settings.LastAssetStamp = staged.Stamp;
        try { settings.Save(); } catch (Exception) { /* checked again next start; costs a download */ }
    }

    /// A file-system call retried through the transient refusals Windows hands
    /// out while something else briefly holds a file. A handful of tries over
    /// about a second and a half; past that the refusal is real.
    internal static void Retry(Action io, int attempts = 6)
    {
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                io();
                return;
            }
            catch (Exception ex) when (attempt < attempts
                                       && ex is IOException or UnauthorizedAccessException)
            {
                Thread.Sleep(50 * attempt);
            }
        }
    }

    // ── replacing the client itself ─────────────────────────────────────────
    //
    // THE RUNNING CLIENT NEVER MOVES ITS OWN FILE. It used to: download beside
    // itself, rename the running exe aside, move the new one into its path and
    // start it. Renaming a running image is legal on both systems, but the
    // client is a compressed single-file bundle, and the runtime reads an
    // assembly out of the bundle the first time it is needed, BY PATH. After
    // the rename that path was the new binary, so the first assembly the old
    // process had not loaded yet (System.IO.Pipes, reached by Process.Start)
    // failed with "Could not load file or assembly", the strip said so, and the
    // update only finished when someone restarted by hand.
    //
    // So it takes one hop. The old client downloads and checks `<exe>.new`,
    // starts it with `--finish-update <exe> --after-update <pid>` and leaves.
    // That process, running from its own file, waits for the old one to exit,
    // copies itself over `<exe>` (a copy, not a move: it is running too) and
    // starts `<exe> --after-update <its pid>`, before it has opened a window.
    // The installed client waits for the hop to exit and deletes `<exe>.new`.
    //
    // The wait is not Windows scaffolding: the Linux client takes its
    // single-instance slot as a D-Bus name, and a second process that starts
    // while the first still owns it becomes a remote activation of the OLD
    // window. An update that appears to do nothing is worse than one that fails.

    /// What the downloaded client is told: which path it is to install itself at.
    public const string FinishUpdateFlag = "--finish-update";

    /// The path in `--finish-update <path>`, or null when there is none.
    public static string? FinishUpdateTarget(string[] args)
    {
        var at = Array.IndexOf(args, FinishUpdateFlag);
        if (at < 0 || at + 1 >= args.Length) return null;
        return args[at + 1] is { Length: > 0 } target ? target : null;
    }

    /// Start the downloaded client on its hop, telling it where to install
    /// itself and whom to wait for. The caller leaves right after.
    public static void StartReplacement(string staged, string exe)
    {
        // UseShellExecute false: on Linux the shell-execute path is xdg-open,
        // which would hand an executable to whatever opens files of its type.
        var start = new System.Diagnostics.ProcessStartInfo(staged)
        {
            UseShellExecute = false,
            WorkingDirectory = Path.GetDirectoryName(exe) ?? "",
        };
        foreach (var arg in HandOffArguments(exe, Environment.ProcessId)) start.ArgumentList.Add(arg);
        System.Diagnostics.Process.Start(start);
    }

    internal static string[] HandOffArguments(string exe, int pid) =>
        new[] { FinishUpdateFlag, exe, AfterUpdateFlag, pid.ToString(CultureInfo.InvariantCulture) };

    /// The hop: run at the very top of Main, before any window. True when the
    /// installed client has been started and this process should exit; false
    /// when it could not be, and this process should simply carry on as the
    /// client, from where it is, rather than leave nothing on screen.
    public static bool FinishUpdate(string target, string[] args)
    {
        if (AfterUpdatePid(args) is { } previous) WaitForPreviousClient(previous);

        var self = Environment.ProcessPath;
        if (self is null || SamePath(self, target)) return false;

        try
        {
            InstallClient(target, self);
        }
        catch (Exception)
        {
            return false;
        }

        try
        {
            var start = new System.Diagnostics.ProcessStartInfo(target)
            {
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(target) ?? "",
            };
            start.ArgumentList.Add(AfterUpdateFlag);
            start.ArgumentList.Add(Environment.ProcessId.ToString(CultureInfo.InvariantCulture));
            System.Diagnostics.Process.Start(start);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static bool SamePath(string a, string b) =>
        string.Equals(Path.GetFullPath(a), Path.GetFullPath(b),
            OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);

    /// What the launched client is told, so it waits for this one to leave.
    public const string AfterUpdateFlag = "--after-update";

    /// The process id in `--after-update <pid>`, or null when the flag is
    /// absent or malformed.
    ///
    /// Here rather than in either Program.cs because both clients parse it and
    /// the parse has three ways to be wrong that all look alike from the
    /// outside — the flag last with nothing after it, a non-numeric argument,
    /// and the flag never passed at all. All three mean the same thing (do not
    /// wait) and none of them is a reason to refuse to start.
    public static int? AfterUpdatePid(string[] args)
    {
        var at = Array.IndexOf(args, AfterUpdateFlag);
        if (at < 0 || at + 1 >= args.Length) return null;
        return int.TryParse(args[at + 1], out var pid) ? pid : null;
    }

    /// Block until the client this one is replacing has exited, so its
    /// single-instance claim is released. Bounded: a process that will not exit
    /// is not a reason never to start.
    public static void WaitForPreviousClient(int pid)
    {
        try { System.Diagnostics.Process.GetProcessById(pid).WaitForExit(30_000); }
        catch (ArgumentException) { /* already gone */ }
        catch (Exception) { /* cannot watch it; carry on */ }
    }

    /// Download the published exe beside this one and verify it. Returns the
    /// staged path, for StartReplacement; nothing at this exe's path changes
    /// here (see the section note). Throws with a sentence for the strip when
    /// anything along the way refuses.
    public static async Task<string> PrepareClientAsync(
        Settings settings, IProgress<string> log, CancellationToken ct)
    {
        var exe = Environment.ProcessPath;
        if (exe is null || !File.Exists(exe))
            throw new InvalidOperationException("This client cannot find its own exe to replace.");

        log.Report("Checking the release…");
        var release = await FetchReleaseAsync(settings, ct).ConfigureAwait(false);
        if (FindAsset(release, ClientAssetName) is not { } asset)
            throw new InvalidOperationException($"The {Tag} release has no {ClientAssetName}.");
        // Refused rather than trusted: an unverifiable binary is not swapped in.
        var digest = PublishedDigest(asset)
            ?? throw new InvalidOperationException(
                "The release states no digest for the client, so a download could not be checked.");

        var staged = StagedClientPath(exe);
        var id = asset.GetProperty("id").GetInt64();
        await DownloadAssetAsync(settings, id, staged, "Downloading the new client…", log, ct)
            .ConfigureAwait(false);

        if (!DigestMatches(staged, digest))
        {
            try { File.Delete(staged); } catch (Exception) { /* best effort */ }
            throw new InvalidOperationException(
                "The downloaded client did not match the digest the release publishes; nothing was changed.");
        }

        // A downloaded file is 0644, and 0644 is not executable. Nothing else
        // in the swap notices — the rename succeeds, the process starts the new
        // client, and the exec fails with a message no user can act on. Set it
        // before the file is anywhere anyone could run it from.
        MakeExecutable(staged);

        return staged;
    }

    /// "sha256:<hex>" as the release states it, or null when it does not.
    internal static string? PublishedDigest(JsonElement asset)
    {
        if (!asset.TryGetProperty("digest", out var field)) return null;
        if (field.ValueKind != JsonValueKind.String) return null;
        var value = field.GetString();
        return value is { Length: > 7 } && value.StartsWith("sha256:", StringComparison.OrdinalIgnoreCase)
            ? value
            : null;
    }

    /// Is the file's SHA-256 the one the release published?
    internal static bool DigestMatches(string path, string published)
    {
        using var stream = File.OpenRead(path);
        var actual = "sha256:" + Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        return string.Equals(actual, published, StringComparison.OrdinalIgnoreCase);
    }

    /// Give the staged client the mode a launcher needs. Windows has no such
    /// concept and `File.SetUnixFileMode` throws there, so the guard is the
    /// call, not an optimisation.
    internal static void MakeExecutable(string path)
    {
        if (OperatingSystem.IsWindows()) return;
        File.SetUnixFileMode(path,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
            UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
    }

    internal static string StagedClientPath(string exe) => exe + ".new";
    internal static string RetiredClientPath(string exe) => exe + ".old";

    /// Put a copy of `source` at `target`, keeping the old file aside until the
    /// copy is in place. `target`'s process has exited by now; `source` is the
    /// running hop, which is why it is copied rather than moved. A failed copy
    /// puts the old file back, so the path never ends up empty.
    internal static void InstallClient(string target, string source)
    {
        var retired = RetiredClientPath(target);
        if (File.Exists(retired)) Retry(() => File.Delete(retired));
        if (File.Exists(target)) Retry(() => File.Move(target, retired));
        try
        {
            Retry(() => File.Copy(source, target));
            MakeExecutable(target);
        }
        catch (Exception)
        {
            if (!File.Exists(target) && File.Exists(retired)) File.Move(retired, target);
            throw;
        }
    }

    /// Delete the downloaded client the hop ran from. Only from a client that
    /// was started by the hop (`--after-update`), and after waiting for it:
    /// then nothing is downloading into the file and nothing is running it.
    /// Any other launch must leave it alone; see RemoveRetiredClient.
    public static void RemoveStagedClient(string? exe)
    {
        if (exe is null) return;
        var staged = StagedClientPath(exe);
        try { if (File.Exists(staged)) Retry(() => File.Delete(staged)); }
        catch (Exception) { /* a stray copy; the next download truncates it */ }
    }

    /// Delete the file a previous replacement moved aside. Best effort: the
    /// retired file is deletable only once the process that ran it has exited,
    /// which is why the launched client waits for that first.
    ///
    /// **The RETIRED file only, never the staged one.** `<exe>.new` is where a
    /// running instance writes a ~69 MB download for minutes at a time, and
    /// this runs at the top of Main in whichever process was launched — before
    /// it knows whether it is even the primary instance. On Windows the
    /// difference never showed: `File.Delete` on a file the downloader holds
    /// open fails with a sharing violation. On Linux unlink succeeds, so
    /// clicking the launcher while an update downloaded destroyed the staged
    /// file (the downloader kept writing to an unlinked inode, and the digest
    /// check then failed with "could not find file"), and a launch landing
    /// between the two renames of the old swap deleted BOTH files and left the
    /// exe path empty with nothing for the rollback to restore.
    ///
    /// A staged file abandoned by a killed download is not leaked in exchange:
    /// `DownloadAssetAsync` opens it with `File.Create`, which truncates.
    internal static void RemoveRetiredClient(string? exe)
    {
        if (exe is null) return;
        var retired = RetiredClientPath(exe);
        try { if (File.Exists(retired)) File.Delete(retired); }
        catch (Exception) { /* still held, or read-only; the next start tries again */ }
    }
}
