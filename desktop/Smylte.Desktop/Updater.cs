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
        var haveLocal = File.Exists(Path.Combine(settings.WebRoot, "index.html"));

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
        await DownloadAndSwapAsync(settings, id, log, ct).ConfigureAwait(false);

        settings.LastAssetId = id;
        settings.LastAssetStamp = stamp;
        settings.Save();

        return new UpdateResult(true, "Updated to the latest build.", clientOutdated);
    }

    /// Is the published exe a different binary from the one running?
    ///
    /// Compared by content hash rather than a version number, because a version
    /// number has to be remembered — a forgotten bump would silently ship a client
    /// nobody is told about. A digest cannot be forgotten.
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

    private static async Task DownloadAndSwapAsync(
        Settings settings, long assetId, IProgress<string> log, CancellationToken ct)
    {
        var zipPath = Path.Combine(Path.GetTempPath(), $"smylte-web-{assetId}.zip");

        using (var http = MakeClient(settings))
        using (var req = new HttpRequestMessage(HttpMethod.Get,
                   $"https://api.github.com/repos/{Owner}/{Repo}/releases/assets/{assetId}"))
        {
            // The asset endpoint (rather than browser_download_url) is what makes
            // this work unchanged whether the repository is public or private.
            req.Headers.Accept.ParseAdd("application/octet-stream");

            using var resp = await http
                .SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();

            var source = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            await using (source.ConfigureAwait(false))
            await using (var file = File.Create(zipPath))
                await source.CopyToAsync(file, ct).ConfigureAwait(false);
        }

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
}
