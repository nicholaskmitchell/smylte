using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Writing a file only when it would change.
///
/// The thing under test is a branch that does nothing, which is exactly the
/// kind of thing that rots unnoticed. What it gates: the Linux client
/// materialises eight icon files whenever it touches the desktop entry — every
/// launch, every light/dark flip, every `/desktop/icon` POST — and then spawns
/// `gtk4-update-icon-cache` with a ten-second wait to announce the change. The
/// files were identical nearly every time.
///
/// Both failure directions are silent and neither throws. A `Same` stuck on
/// false restores the spawn-every-launch behaviour with nothing to show for it;
/// a `Same` stuck on true ships a stale icon set and a cache that never learns
/// about the new one.
public sealed class FileSyncTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("smylte-sync").FullName;

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch (IOException) { }
    }

    private string Path(string name) => System.IO.Path.Combine(_root, name);

    private static byte[] Png(byte tail) => [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, tail];

    [Fact]
    public void The_first_write_lands_and_reports_a_change()
    {
        var target = Path("nested/deeper/accent-48.png");
        Assert.True(FileSync.Write(Png(1), target, out var changed));

        Assert.True(changed);
        Assert.Equal(Png(1), File.ReadAllBytes(target));
    }

    [Fact]
    public void Writing_the_same_bytes_again_reports_no_change()
    {
        var target = Path("accent-48.png");
        FileSync.Write(Png(1), target, out _);
        var stamp = File.GetLastWriteTimeUtc(target);

        Assert.True(FileSync.Write(Png(1), target, out var changed));

        Assert.False(changed);
        // And it did not touch the file at all — mtime is what an icon cache
        // and a file watcher key on, so rewriting identical bytes is a change
        // as far as everything downstream is concerned.
        Assert.Equal(stamp, File.GetLastWriteTimeUtc(target));
    }

    [Fact]
    public void Different_bytes_of_the_same_length_are_a_change()
    {
        // Length is the cheap test and it is not sufficient: two icon variants
        // at the same size are the same PNG structure with different pixels,
        // and comparing lengths alone would call them equal.
        var target = Path("accent-48.png");
        FileSync.Write(Png(1), target, out _);

        Assert.True(FileSync.Write(Png(2), target, out var changed));

        Assert.True(changed);
        Assert.Equal(Png(2), File.ReadAllBytes(target));
    }

    [Fact]
    public void A_truncated_file_is_rewritten()
    {
        // The state a half-finished write leaves behind. It must not read as
        // "already correct" on the strength of its first bytes.
        var target = Path("accent-48.png");
        FileSync.Write(Png(1), target, out _);
        File.WriteAllBytes(target, Png(1)[..4]);

        Assert.True(FileSync.Write(Png(1), target, out var changed));

        Assert.True(changed);
        Assert.Equal(Png(1), File.ReadAllBytes(target));
    }

    [Fact]
    public void An_empty_file_and_empty_bytes_are_the_same_thing()
    {
        var target = Path("empty");
        Assert.True(FileSync.Write([], target, out var first));
        Assert.True(first);
        Assert.True(FileSync.Write([], target, out var second));
        Assert.False(second);
    }

    [Fact]
    public void No_temp_file_is_left_behind()
    {
        // The rename is what makes a half-written icon impossible; a `.tmp`
        // surviving it would be a stray file inside the user's icon theme,
        // where gtk4-update-icon-cache would then try to read it.
        var target = Path("accent-48.png");
        FileSync.Write(Png(1), target, out _);
        FileSync.Write(Png(2), target, out _);

        Assert.Empty(Directory.GetFiles(_root, "*.tmp"));
    }

    [Fact]
    public void A_path_that_cannot_be_written_fails_without_throwing()
    {
        // A read-only home or a policy-managed profile. Every caller here is
        // best-effort — a client with no icon is a working client — so this
        // must report failure rather than take the window down with it.
        var blocker = Path("blocker");
        File.WriteAllText(blocker, "not a directory");

        Assert.False(FileSync.Write(Png(1), System.IO.Path.Combine(blocker, "x.png"), out var changed));
        Assert.False(changed);
    }

    [Fact]
    public void Same_answers_false_for_a_file_that_is_not_there()
    {
        Assert.False(FileSync.Same(Png(1), Path("never-written.png")));
    }
}
