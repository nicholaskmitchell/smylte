using System.Text.Json;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Where the release is read from: GitLab's copy first, GitHub's when GitLab
/// cannot say everything a client needs. Nothing here touches the network.
public sealed class ReleaseSourceTests
{
    private const string WebSum = "sha256:da6acd88ab1b437e22b7e56f86a2f070e6c3c2b37d7736ceb2406c5068357e7b";
    private const string ExeSum = "sha256:35e3082f34f8c669a1a7d5c27b1090ba5fb39273ead3da733d1ec12b40f611f8";

    private static JsonElement Json(string json) => JsonDocument.Parse(json).RootElement.Clone();

    private static string Link(string name) =>
        $$"""{"name":"{{name}}","url":"https://example.com/{{name}}","direct_asset_url":"https://example.com/d/{{name}}"}""";

    private static JsonElement GitLab(string description, params string[] links) => Json(
        "{\"description\":" + JsonSerializer.Serialize(description)
        + ",\"assets\":{\"links\":[" + string.Join(",", links) + "]}}");

    private static readonly string Notes =
        "Rolling client build from deadbeef.\n\nChecksums (each download is checked against these):\n"
        + $"- smylte-web.zip: {WebSum}\n- Smylte.exe: {ExeSum}\n";

    [Fact]
    public void GitLabs_copy_gives_each_file_its_link_and_checksum()
    {
        var release = Updater.ParseGitLabRelease(
            GitLab(Notes, Link("smylte-web.zip"), Link("Smylte.exe")), "smylte-web.zip", "Smylte.exe");

        Assert.NotNull(release);
        Assert.True(release.FromGitLab);
        var web = release.Find("smylte-web.zip")!;
        Assert.Equal(WebSum, web.Digest);
        Assert.Equal(WebSum, web.Key);
        Assert.Equal("https://example.com/d/smylte-web.zip", web.Url);
        Assert.True(web.ViaGitLab);
    }

    [Fact]
    public void Checksums_survive_backticks_and_windows_line_ends()
    {
        var notes = $"- `smylte-web.zip`: `{WebSum.ToUpperInvariant().Replace("SHA256", "sha256")}`\r\n";
        var release = Updater.ParseGitLabRelease(GitLab(notes, Link("smylte-web.zip")), "smylte-web.zip");
        Assert.Equal(WebSum, release!.Find("smylte-web.zip")!.Digest);
    }

    [Fact]
    public void A_copy_without_checksums_is_not_used()
    {
        // What GitLab holds until the first publish that writes them.
        var release = Updater.ParseGitLabRelease(
            GitLab("Rolling client build from deadbeef.", Link("smylte-web.zip"), Link("Smylte.exe")),
            "smylte-web.zip", "Smylte.exe");
        Assert.Null(release);
    }

    [Fact]
    public void A_required_file_without_a_link_or_checksum_sends_the_client_to_GitHub()
    {
        Assert.Null(Updater.ParseGitLabRelease(GitLab(Notes, Link("smylte-web.zip")), "smylte-web.zip", "Smylte.exe"));
        var noExeSum = $"- smylte-web.zip: {WebSum}\n";
        Assert.Null(Updater.ParseGitLabRelease(
            GitLab(noExeSum, Link("smylte-web.zip"), Link("Smylte.exe")), "smylte-web.zip", "Smylte.exe"));
    }

    [Fact]
    public void Only_https_links_are_followed()
    {
        var plain = """{"name":"smylte-web.zip","url":"http://example.com/smylte-web.zip"}""";
        Assert.Null(Updater.ParseGitLabRelease(GitLab(Notes, plain), "smylte-web.zip"));
    }

    [Fact]
    public void GitHubs_release_is_keyed_by_digest_or_else_by_id_and_upload_time()
    {
        var release = Updater.ParseGitHubRelease(Json($$"""
            {"assets":[
              {"name":"smylte-web.zip","id":7,"digest":"{{WebSum}}","updated_at":"2026-11-04T20:10:46Z",
               "browser_download_url":"https://example.com/smylte-web.zip"},
              {"name":"Smylte.exe","id":8,"updated_at":"2026-11-04T20:10:48Z"}
            ]}
            """));

        Assert.False(release.FromGitLab);
        Assert.Equal(WebSum, release.Find("smylte-web.zip")!.Key);
        Assert.Equal(7, release.Find("smylte-web.zip")!.GitHubId);
        Assert.False(release.Find("smylte-web.zip")!.ViaGitLab);
        Assert.Null(release.Find("Smylte.exe")!.Digest);
        Assert.Equal("8:2026-11-04T20:10:48Z", release.Find("Smylte.exe")!.Key);
    }

    [Fact]
    public void Both_sources_key_the_same_build_alike()
    {
        // So a client that reads GitLab one day and GitHub the next does not
        // download the same build twice.
        var gitLab = Updater.ParseGitLabRelease(GitLab(Notes, Link("smylte-web.zip")), "smylte-web.zip")!;
        var gitHub = Updater.ParseGitHubRelease(Json(
            $$"""{"assets":[{"name":"smylte-web.zip","id":7,"digest":"{{WebSum.ToUpperInvariant().Replace("SHA256", "sha256")}}"}]}"""));
        Assert.Equal(gitLab.Find("smylte-web.zip")!.Key, gitHub.Find("smylte-web.zip")!.Key);
    }

    private static readonly ReleaseInfo FromGitHub = new(false, []);
    private static readonly ReleaseInfo FromGitLab = new(true, []);

    [Fact]
    public async Task GitLab_is_asked_first()
    {
        var askedGitHub = false;
        var release = await Updater.FetchReleaseAsync(
            () => Task.FromResult<ReleaseInfo?>(FromGitLab),
            () => { askedGitHub = true; return Task.FromResult(FromGitHub); },
            CancellationToken.None);
        Assert.Same(FromGitLab, release);
        Assert.False(askedGitHub);
    }

    [Fact]
    public async Task GitLab_failing_or_unusable_means_asking_GitHub()
    {
        Assert.Same(FromGitHub, await Updater.FetchReleaseAsync(
            () => throw new HttpRequestException("down"), () => Task.FromResult(FromGitHub), CancellationToken.None));
        Assert.Same(FromGitHub, await Updater.FetchReleaseAsync(
            () => Task.FromException<ReleaseInfo?>(new TaskCanceledException("slow")),
            () => Task.FromResult(FromGitHub), CancellationToken.None));
        Assert.Same(FromGitHub, await Updater.FetchReleaseAsync(
            () => Task.FromResult<ReleaseInfo?>(null), () => Task.FromResult(FromGitHub), CancellationToken.None));
    }

    [Fact]
    public async Task GitHub_failing_too_is_what_the_caller_hears()
    {
        await Assert.ThrowsAsync<HttpRequestException>(() => Updater.FetchReleaseAsync(
            () => throw new HttpRequestException("GitLab down"),
            () => throw new HttpRequestException("GitHub down"),
            CancellationToken.None));
    }

    [Fact]
    public async Task A_cancelled_check_does_not_go_on_to_GitHub()
    {
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        var askedGitHub = false;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => Updater.FetchReleaseAsync(
            () => throw new TaskCanceledException(),
            () => { askedGitHub = true; return Task.FromResult(FromGitHub); },
            cts.Token));
        Assert.False(askedGitHub);
    }
}
