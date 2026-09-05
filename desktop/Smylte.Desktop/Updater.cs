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
public sealed record UpdateResult(bool Updated, string Message, bool ClientOutdated);

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
    private const string ClientAssetName = "Smylte.exe";

    /// Where to send someone whose client is out of date. The release is rolling,
    /// so this link never changes and always has the current exe behind it.
    public const string ReleaseUrl =
        $"https://github.com/{Owner}/{Repo}/releases/tag/{Tag}";

    public static async Task<UpdateResult> EnsureWebAssetsAsync(
        Settings settings, IProgress<string> log, CancellationToken ct)
    {
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

        log.Report("Downloading the latest build…");
        if (await SwapOrKeepLocalAsync(
                () => DownloadAndSwapAsync(settings, id, log, ct),
                haveLocal, clientOutdated, log).ConfigureAwait(false) is { } kept)
            return kept;

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

    private static async Task DownloadAndSwapAsync(
        Settings settings, long assetId, IProgress<string> log, CancellationToken ct)
    {
        var zipPath = Path.Combine(Path.GetTempPath(), $"smylte-web-{assetId}.zip");
        await DownloadAssetAsync(settings, assetId, zipPath, "Downloading the latest build…", log, ct)
            .ConfigureAwait(false);

        log.Report("Installing…");

        var root = settings.WebRoot;
        var staging = root + ".new";
        var previous = root + ".old";

        foreach (var stale in new[] { staging, previous })
            if (Directory.Exists(stale)) Directory.Delete(stale, recursive: true);

        Directory.CreateDirectory(Path.GetDirectoryName(root)!);
        ZipFile.ExtractToDirectory(zipPath, staging);

        // Move the old copy aside rather than deleting it first, so a failure
        // between the two steps still leaves a working install to roll back to.
        if (Directory.Exists(root)) Directory.Move(root, previous);
        try
        {
            Directory.Move(staging, root);
        }
        catch (Exception)
        {
            if (!Directory.Exists(root) && Directory.Exists(previous)) Directory.Move(previous, root);
            throw;
        }

        if (Directory.Exists(previous)) Directory.Delete(previous, recursive: true);
        try { File.Delete(zipPath); } catch (Exception) { /* temp file; not worth failing over */ }
    }

    // ── replacing the client itself ─────────────────────────────────────────
    //
    // A running exe cannot be overwritten on Windows, but it CAN be renamed —
    // the image stays mapped under its new name. So the new client is
    // downloaded beside the old one, checked against the digest the release
    // publishes, the running file is moved aside, the new one takes its path,
    // and the new one is started with the old process's id so it can wait for
    // it to exit before taking the single-instance mutex. The old file is
    // deleted on that next start, once nothing is executing it.

    /// What the launched client is told, so it waits for this one to leave.
    public const string AfterUpdateFlag = "--after-update";

    /// Download the published exe, verify it and swap it into this exe's path.
    /// Returns the path to start. Throws with a sentence for the strip when
    /// anything along the way refuses; nothing is changed until the download
    /// has been checked, and a failed swap puts the old file back.
    public static async Task<string> ReplaceClientAsync(
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

        log.Report("Installing…");
        SwapClient(exe, staged);
        return exe;
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

    internal static string StagedClientPath(string exe) => exe + ".new";
    internal static string RetiredClientPath(string exe) => exe + ".old";

    /// Move the running file aside and the staged one into its place. A failure
    /// on the second move puts the first back, so the path never ends up empty.
    internal static void SwapClient(string exe, string staged)
    {
        var retired = RetiredClientPath(exe);
        if (File.Exists(retired)) File.Delete(retired);
        File.Move(exe, retired);
        try
        {
            File.Move(staged, exe);
        }
        catch (Exception)
        {
            if (!File.Exists(exe) && File.Exists(retired)) File.Move(retired, exe);
            throw;
        }
    }

    /// Delete what a previous replacement left beside the exe. Best effort:
    /// the retired file is deletable only once the process that ran it has
    /// exited, which is why the launched client waits for that first.
    internal static void RemoveStaleClient(string? exe)
    {
        if (exe is null) return;
        foreach (var stale in new[] { RetiredClientPath(exe), StagedClientPath(exe) })
        {
            try { if (File.Exists(stale)) File.Delete(stale); }
            catch (Exception) { /* still held, or read-only; the next start tries again */ }
        }
    }
}
