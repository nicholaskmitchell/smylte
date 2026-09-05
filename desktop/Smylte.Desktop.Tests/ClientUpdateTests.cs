using System.Security.Cryptography;
using System.Text.Json;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The client replacing itself: the parts that decide whether a downloaded
/// binary may take the running exe's path, and the file dance that gives it
/// that path without ever leaving the path empty.
///
/// Nothing here touches the network or a real process. The download is
/// GitHub's; what these pin is what happens around it — that an unverifiable
/// or mismatching binary is refused, that a failed swap puts the old file back,
/// and that the leftovers of a previous replacement are cleared.
public sealed class ClientUpdateTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-exe").FullName;

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    private string Write(string name, string contents)
    {
        var path = Path.Combine(_dir, name);
        File.WriteAllText(path, contents);
        return path;
    }

    private static string Sha256Of(string contents)
    {
        using var stream = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(contents));
        return "sha256:" + Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static JsonElement Asset(string json) => JsonDocument.Parse(json).RootElement.Clone();

    // ── the digest the release publishes ────────────────────────────────────

    [Fact]
    public void The_published_digest_is_read_only_when_it_is_a_sha256()
    {
        Assert.Equal("sha256:abc", Updater.PublishedDigest(Asset("""{"digest":"sha256:abc"}""")));
        Assert.Equal("SHA256:ABC", Updater.PublishedDigest(Asset("""{"digest":"SHA256:ABC"}""")));
        // Absent, empty, the wrong algorithm, or not a string: no digest, and
        // ReplaceClientAsync refuses rather than swapping in something unchecked.
        Assert.Null(Updater.PublishedDigest(Asset("""{"name":"Smylte.exe"}""")));
        Assert.Null(Updater.PublishedDigest(Asset("""{"digest":""}""")));
        Assert.Null(Updater.PublishedDigest(Asset("""{"digest":"md5:abc"}""")));
        Assert.Null(Updater.PublishedDigest(Asset("""{"digest":null}""")));
        Assert.Null(Updater.PublishedDigest(Asset("""{"digest":42}""")));
    }

    [Fact]
    public void A_download_matches_only_the_digest_of_its_own_bytes()
    {
        var path = Write("Smylte.exe.new", "the new client");
        Assert.True(Updater.DigestMatches(path, Sha256Of("the new client")));
        Assert.True(Updater.DigestMatches(path, Sha256Of("the new client").ToUpperInvariant()));
        Assert.False(Updater.DigestMatches(path, Sha256Of("a tampered client")));
    }

    // ── the swap ────────────────────────────────────────────────────────────

    [Fact]
    public void The_swap_puts_the_new_file_at_the_exes_path_and_keeps_the_old_beside_it()
    {
        var exe = Write("Smylte.exe", "old");
        var staged = Write("Smylte.exe.new", "new");

        Updater.SwapClient(exe, staged);

        Assert.Equal("new", File.ReadAllText(exe));
        Assert.Equal("old", File.ReadAllText(Updater.RetiredClientPath(exe)));
        Assert.False(File.Exists(staged));
    }

    [Fact]
    public void A_swap_whose_second_move_fails_puts_the_old_exe_back()
    {
        // The staged file is missing — the shape of any failure between the two
        // moves. The running exe had already been renamed aside by then, and a
        // path left empty is a client that does not start next time.
        var exe = Write("Smylte.exe", "old");
        var staged = Path.Combine(_dir, "Smylte.exe.new");

        Assert.ThrowsAny<IOException>(() => Updater.SwapClient(exe, staged));

        Assert.Equal("old", File.ReadAllText(exe));
        Assert.False(File.Exists(Updater.RetiredClientPath(exe)));
    }

    [Fact]
    public void A_retired_file_from_last_time_does_not_block_the_swap()
    {
        var exe = Write("Smylte.exe", "old");
        Write("Smylte.exe.old", "older still");
        var staged = Write("Smylte.exe.new", "new");

        Updater.SwapClient(exe, staged);

        Assert.Equal("new", File.ReadAllText(exe));
        Assert.Equal("old", File.ReadAllText(Updater.RetiredClientPath(exe)));
    }

    // ── the next start ──────────────────────────────────────────────────────

    [Fact]
    public void The_next_start_clears_what_the_replacement_left_behind()
    {
        var exe = Write("Smylte.exe", "new");
        Write("Smylte.exe.old", "old");
        Write("Smylte.exe.new", "half a download");

        Updater.RemoveStaleClient(exe);

        Assert.True(File.Exists(exe));
        Assert.False(File.Exists(Updater.RetiredClientPath(exe)));
        Assert.False(File.Exists(Updater.StagedClientPath(exe)));
        // And with nothing to clear, or no path at all, it is a no-op.
        Updater.RemoveStaleClient(exe);
        Updater.RemoveStaleClient(null);
    }

    [Fact]
    public void Progress_is_said_in_megabytes_with_the_total_when_known()
    {
        Assert.Equal("Downloading… 12 of 69 MB",
            Updater.ProgressText("Downloading…", 12L << 20, 69L << 20));
        Assert.Equal("Downloading… 12 MB", Updater.ProgressText("Downloading…", 12L << 20, null));
        // A total under a megabyte still reads as 1, never "of 0 MB".
        Assert.Equal("Downloading… 0 of 1 MB", Updater.ProgressText("Downloading…", 100, 500));
    }
}
