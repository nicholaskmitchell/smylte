using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;

namespace Smylte.Desktop;

public sealed record UpdateResult(bool Updated, string Message);

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

    public static async Task<UpdateResult> EnsureWebAssetsAsync(
        Settings settings, IProgress<string> log, CancellationToken ct)
    {
        var haveLocal = File.Exists(Path.Combine(settings.WebRoot, "index.html"));

        JsonElement asset;
        try
        {
            log.Report("Checking for updates…");
            asset = await FindAssetAsync(settings, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or KeyNotFoundException)
        {
            // Offline, rate-limited, or the release is not there yet. An installed
            // client must still open; only a first run has nothing to fall back to.
            if (haveLocal) return new UpdateResult(false, "Offline — using the installed build.");
            throw new InvalidOperationException(
                "Could not reach GitHub to download the app, and there is no local copy yet. "
                + "Check the connection. If this keeps happening, a GitHub token in settings "
                + "raises the API rate limit.", ex);
        }

        var id = asset.GetProperty("id").GetInt64();
        var stamp = asset.TryGetProperty("updated_at", out var u) ? u.GetString() ?? "" : "";

        if (haveLocal && id == settings.LastAssetId && stamp == settings.LastAssetStamp)
            return new UpdateResult(false, "Up to date.");

        log.Report("Downloading the latest build…");
        await DownloadAndSwapAsync(settings, id, log, ct).ConfigureAwait(false);

        settings.LastAssetId = id;
        settings.LastAssetStamp = stamp;
        settings.Save();

        return new UpdateResult(true, "Updated to the latest build.");
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

    private static async Task<JsonElement> FindAssetAsync(Settings settings, CancellationToken ct)
    {
        using var http = MakeClient(settings);
        using var req = new HttpRequestMessage(HttpMethod.Get,
            $"https://api.github.com/repos/{Owner}/{Repo}/releases/tags/{Tag}");
        req.Headers.Accept.ParseAdd("application/vnd.github+json");

        using var resp = await http.SendAsync(req, ct).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        using var doc = JsonDocument.Parse(body);

        foreach (var candidate in doc.RootElement.GetProperty("assets").EnumerateArray())
        {
            if (candidate.GetProperty("name").GetString() != AssetName) continue;
            return candidate.Clone();   // the JsonDocument is about to be disposed
        }
        throw new KeyNotFoundException($"The {Tag} release has no {AssetName} asset.");
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
