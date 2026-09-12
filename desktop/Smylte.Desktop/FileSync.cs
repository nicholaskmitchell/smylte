namespace Smylte.Desktop;

/// Writing a file only when its contents would actually change.
///
/// Small, and it earns a file because of what it gates rather than what it
/// does. The Linux client materialises eight icon files every time it touches
/// the desktop entry — on every launch, on every light/dark flip, and on every
/// `/desktop/icon` POST — and then spawns `gtk4-update-icon-cache` with a
/// ten-second wait to tell the desktop about it. The files were byte-identical
/// nearly every time, so the refresh had nothing to refresh, and a POST anyone
/// on loopback can send was an amplifier for a process spawn.
///
/// Compared by CONTENT, not by timestamp: the writer rewrote unconditionally,
/// so mtime says "changed" on every launch and answers the wrong question.
///
/// Portable, and linked into the test project, because the branch that decides
/// nothing happened is exactly the branch a test has to pin — a `Same` that
/// always answered false would restore the old behaviour silently, and a `Same`
/// that always answered true would ship a stale icon set with the suite green.
internal static class FileSync
{
    /// Is `target` already exactly these bytes?
    ///
    /// False for a file that is not there, cannot be read, or is a different
    /// length — all of which mean "write it", which is the safe answer.
    public static bool Same(byte[] wanted, string target)
    {
        try
        {
            if (!File.Exists(target)) return false;
            var existing = File.ReadAllBytes(target);
            return existing.Length == wanted.Length
                && existing.AsSpan().SequenceEqual(wanted);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// Write `bytes` to `target`, and report whether anything moved.
    ///
    /// Temp-then-rename, because something may have the current file open and a
    /// half-written PNG is a broken icon rather than a missing one — the same
    /// reasoning ShellShortcut.WriteIcon states for its own.
    ///
    /// Returns false only when the write failed; `changed` is false both when
    /// it failed and when there was nothing to do, so a caller deciding whether
    /// to refresh a cache must read `changed` and not the return value.
    public static bool Write(byte[] bytes, string target, out bool changed)
    {
        changed = false;
        try
        {
            if (Same(bytes, target)) return true;

            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            var temp = target + ".tmp";
            File.WriteAllBytes(temp, bytes);
            File.Move(temp, target, overwrite: true);
            changed = true;
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
