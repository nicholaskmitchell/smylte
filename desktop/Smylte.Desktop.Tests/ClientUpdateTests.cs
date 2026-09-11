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
    public void The_next_start_clears_the_file_the_replacement_moved_aside()
    {
        var exe = Write("Smylte.exe", "new");
        Write("Smylte.exe.old", "old");

        Updater.RemoveRetiredClient(exe);

        Assert.True(File.Exists(exe));
        Assert.False(File.Exists(Updater.RetiredClientPath(exe)));
        // And with nothing to clear, or no path at all, it is a no-op.
        Updater.RemoveRetiredClient(exe);
        Updater.RemoveRetiredClient(null);
    }

    [Fact]
    public void The_next_start_does_not_touch_a_download_that_is_still_running()
    {
        // This runs at the top of Main, in whichever process was launched —
        // before it knows whether it is even the primary instance. `<exe>.new`
        // is where a RUNNING instance writes a ~69 MB download for minutes at a
        // time, and on Linux unlink of an open file succeeds, so clicking the
        // launcher during an update used to destroy the staged file: the
        // downloader kept writing to an unlinked inode and the digest check
        // then failed with "could not find file". On Windows the same code was
        // harmless only because the open handle made File.Delete throw.
        var exe = Write("Smylte.exe", "running");
        var staged = Write("Smylte.exe.new", "half a download");

        Updater.RemoveRetiredClient(exe);

        Assert.True(File.Exists(staged));
        Assert.Equal("half a download", File.ReadAllText(staged));
    }

    [Fact]
    public void A_swap_interrupted_by_a_second_launch_still_has_something_to_restore()
    {
        // The severe half of the same ordering. A launch landing between the
        // two renames in SwapClient used to delete BOTH files, so the rollback
        // found no retired file, nothing was restored, and the exe path was
        // left empty while the desktop entry still pointed at it.
        var exe = Write("Smylte.exe", "old");
        File.Move(exe, Updater.RetiredClientPath(exe));      // mid-swap: exe is gone

        Updater.RemoveRetiredClient(exe);                    // the second launch

        // Deleting the retired file here is allowed — it is the documented job,
        // and the swap's own rollback is what owns the window. What must not
        // happen is the staged file going with it.
        Write("Smylte.exe.new", "new");
        Updater.SwapClient(Write("Smylte.exe", "old again"), Updater.StagedClientPath(exe));
        Assert.Equal("new", File.ReadAllText(exe));
    }

    // ── the flag the updater starts its replacement with ────────────────────

    public static TheoryData<string[], int> WellFormed()
    {
        var data = new TheoryData<string[], int>();
        data.Add(new[] { "--after-update", "1234" }, 1234);
        data.Add(new[] { "--setup", "--after-update", "7" }, 7);
        return data;
    }

    [Theory]
    [MemberData(nameof(WellFormed))]
    public void The_previous_pid_is_read_out_of_the_arguments(string[] args, int expected)
    {
        Assert.Equal(expected, Updater.AfterUpdatePid(args));
    }

    public static TheoryData<string[]> Malformed()
    {
        var data = new TheoryData<string[]>();
        data.Add(Array.Empty<string>());
        data.Add(new[] { "--setup" });
        data.Add(new[] { "--after-update" });                  // last, nothing after it
        data.Add(new[] { "--after-update", "not-a-pid" });
        data.Add(new[] { "--after-update", "" });
        return data;
    }

    [Theory]
    [MemberData(nameof(Malformed))]
    public void Anything_malformed_means_do_not_wait_rather_than_do_not_start(string[] args)
    {
        // All three ways of being wrong mean the same thing, and none of them
        // is a reason to refuse to launch. Untested until now, and the Windows
        // client did not even call it — it carried a second, hand-copied parse
        // of the same three lines, which is one more than this needs.
        Assert.Null(Updater.AfterUpdatePid(args));
    }

    // ── which binary this client is asking about, and whether it can run ────

    [Fact]
    public void The_client_asks_about_the_asset_for_the_system_it_is_running_on()
    {
        // One rolling release carries both clients, because there is one web
        // build and it is the same bytes for everybody. Each client must ask
        // about its own half: a Linux client comparing its digest against
        // Smylte.exe would offer an update to a binary it cannot execute, and
        // would offer it forever, since the digests can never match.
        Assert.Equal(
            OperatingSystem.IsWindows() ? "Smylte.exe" : "Smylte-linux-x86_64",
            Updater.ClientAssetName);

        // Both names are asserted whichever runner this is on, so a rename on
        // one platform cannot pass unnoticed on the other. They are also the
        // strings desktop-release.yml uploads and greps for.
        Assert.Equal("Smylte.exe", Updater.WindowsClientAsset);
        Assert.Equal("Smylte-linux-x86_64", Updater.LinuxClientAsset);
    }

    [Fact]
    public void A_staged_client_is_made_executable_before_it_takes_the_exe_path()
    {
        var staged = Write("Smylte.new", "the new client");
        Updater.MakeExecutable(staged);

        if (OperatingSystem.IsWindows())
        {
            // Windows has no mode bits and File.SetUnixFileMode throws there,
            // so the whole of the assertion is that this did not blow up.
            return;
        }

        var mode = File.GetUnixFileMode(staged);
        // The bit that matters. A downloaded file is 0644, the swap succeeds,
        // and the relaunch then fails with EACCES — an update that reports
        // success and leaves a client that will not start.
        Assert.True(mode.HasFlag(UnixFileMode.UserExecute));
        Assert.True(mode.HasFlag(UnixFileMode.UserRead));
        Assert.True(mode.HasFlag(UnixFileMode.UserWrite));
        // And nothing beyond 0755: a world-WRITABLE binary that the client then
        // executes on every launch would be a far worse bug than the one above.
        Assert.False(mode.HasFlag(UnixFileMode.GroupWrite));
        Assert.False(mode.HasFlag(UnixFileMode.OtherWrite));
    }

    [Fact]
    public void The_swap_keeps_the_executable_bit_it_was_given()
    {
        // The two halves are separate calls, so this pins that the second does
        // not undo the first — File.Move preserves the mode, but the ordering
        // is the kind of thing a later edit reshuffles.
        var exe = Write("Smylte", "old");
        var staged = Write("Smylte.new", "new");
        Updater.MakeExecutable(staged);
        Updater.SwapClient(exe, staged);

        Assert.Equal("new", File.ReadAllText(exe));
        if (OperatingSystem.IsWindows()) return;
        Assert.True(File.GetUnixFileMode(exe).HasFlag(UnixFileMode.UserExecute));
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
