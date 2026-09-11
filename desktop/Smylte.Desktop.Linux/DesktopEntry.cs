using System.Diagnostics;
using System.Text;

namespace Smylte.Desktop;

/// The opt-in that gives Smylte a launcher.
///
/// This is `ShellShortcut.cs` for Linux, and it is 184 lines of hand-declared
/// COM replaced by writing an INI file. What it buys is also different, and the
/// difference is why the same wire field means two things:
///
///   Windows   `Form.Icon` cannot change the GROUPED taskbar button, so a
///             Start-menu shortcut is the only way to reach it. Without one,
///             choosing an icon appears to do nothing where people look.
///   Linux     `SetIconName` already reaches the title bar, Alt-Tab and the
///             window switcher with nothing installed. The entry buys the app
///             grid, search, a launcher icon, and an app NAME on notifications
///             — GNOME resolves those from the desktop file, and a running
///             window with no entry is matched by app id to nothing.
///
/// Off by default, because this client otherwise installs nothing anywhere and
/// `desktop/README.md` makes a point of that. The first-run dialog asks
/// outright rather than assuming, which is the honest way to have both.
///
/// Every path is best-effort, exactly as ShellShortcut's are: a launcher is a
/// nicety, and failing to write one must not cost anyone their window.
internal static class DesktopEntry
{
    /// `$XDG_DATA_HOME`, which is where a per-user entry and its icons go.
    ///
    /// Through Settings rather than through `GetFolderPath` directly, because
    /// the default overload returns an empty string for a directory that does
    /// not exist yet — and a relative `applications/…​.desktop` is an entry no
    /// launcher will ever find. See Settings.Home for the whole of it.
    private static string DataHome => Settings.DataHome;

    /// The basename MUST equal the application id. Three things have to agree
    /// or the shell shows a running window under a generic icon: this filename,
    /// the `StartupWMClass` below, and the `g_set_prgname` call in Program.cs.
    /// Wayland matches on the app id alone; X11 matches on `WM_CLASS`, which is
    /// what the other two are for.
    public static string Path => System.IO.Path.Combine(
        DataHome, "applications", Program.AppId + ".desktop");

    private static string IconRoot => System.IO.Path.Combine(DataHome, "icons");

    /// Is there an entry on disk right now?
    ///
    /// The file is the truth, not the setting, and the two can disagree:
    /// `--install` runs in its own process (before GTK, so it works over SSH),
    /// writes the entry and sets the field — while an instance that is already
    /// open still holds the copy of settings.json it loaded at startup and
    /// overwrites the field on its next save. Reporting the FILE to the page
    /// means the Appearance checkbox tells the truth either way, and the next
    /// thing the user changes there writes the truth back.
    public static bool Installed => File.Exists(Path);

    /// Bring the entry in line with the settings, in both directions.
    ///
    /// For the two callers that actually decide: the Appearance toggle and
    /// `--install` / `--uninstall`. Everything else wants Follow.
    ///
    /// Returns whether the requested state was reached, so `--install` can say
    /// something true on the way out. Nothing else looks at the answer.
    public static bool Sync(Settings settings, IconChoice resolved)
    {
        try
        {
            if (settings.StartMenuShortcut) return Write(resolved);

            var existed = File.Exists(Path);
            if (existed) File.Delete(Path);
            IconAssets.Remove(IconRoot, Program.AppId);
            // Only when something was actually removed. Unconditionally, this
            // rewrote ~/.local/share/applications/mimeinfo.cache on every
            // launch of every user who had declined the launcher.
            if (existed) Refresh(applications: true);
            return true;
        }
        catch (Exception)
        {
            // A read-only home, a policy-managed profile. The app is
            // unaffected; only the launcher is.
            return false;
        }
    }

    /// Keep an existing entry current, and never remove one.
    ///
    /// The entry carries a COPY of the resolved variant, so a light/dark flip
    /// has to rewrite it — that is why the icon path calls this rather than
    /// only running when the toggle changes. What it must NOT do is act on the
    /// `off` half of a setting it did not read this second: this runs from
    /// ApplyIcon, which fires on every colour-scheme change and on every start,
    /// and a stale `false` there is what silently deleted a launcher somebody
    /// had just installed from a terminal.
    public static void Follow(Settings settings, IconChoice resolved)
    {
        try
        {
            if (settings.StartMenuShortcut || Installed) Write(resolved);
        }
        catch (Exception) { /* see Sync */ }
    }

    private static bool Write(IconChoice resolved)
    {
        var exe = Environment.ProcessPath;
        // CanWrite, not just a null check: a newline in the path cannot be
        // represented on a `key=value` line whatever the escaping, and half an
        // entry is worse than none.
        if (exe is null || !DesktopEntryText.CanWrite(exe)) return false;

        // The RESOLVED choice, not the literal one. A desktop entry points
        // at a static file, so `Auto` has to be answered now — the same
        // wrinkle ShellShortcut has, and the same consequence: the entry
        // does not follow a later light/dark flip until something calls
        // this again, which is why the icon path re-syncs.
        if (!IconAssets.Export(resolved, IconRoot, Program.AppId)) return false;

        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);

        // Compared before writing, so an unchanged entry does not restart the
        // desktop database. This runs on every launch.
        var contents = Contents(exe);
        var changed = !File.Exists(Path) || File.ReadAllText(Path) != contents;
        if (changed) File.WriteAllText(Path, contents, new UTF8Encoding(false));

        Refresh(applications: changed);
        return true;
    }

    internal static string Contents(string exe) =>
        DesktopEntryText.Contents(exe, Program.AppId);

    /// Nudge the desktop into noticing. Both tools are optional and both are
    /// allowed to be missing — GNOME watches the applications directory itself,
    /// and these only shorten the wait on desktops that do not.
    ///
    /// **Off the calling thread.** Two processes with a ten-second wait each is
    /// up to twenty seconds, and every caller here is on the GTK thread: this
    /// ran inside the MainWindow constructor and inside the bridge's `Icon`
    /// handler, where it froze the window and — since the bridge answers on a
    /// bounded wait — could make the page's own icon dropdown snap back.
    ///
    /// `applications` is false when the entry on disk did not change, which is
    /// every launch of an installed client: rewriting mimeinfo.cache to say
    /// what it already says is work nobody asked for.
    private static void Refresh(bool applications)
    {
        var tools = new List<(string Tool, string Argument)>
        {
            // The THEME directory, not the search-path root. gtk4-update-icon-cache
            // writes an icon-theme.cache beside an index.theme and refuses a
            // directory that holds neither, so pointing it at `icons/` could
            // never have succeeded — `icons/hicolor/` is the theme.
            ("gtk4-update-icon-cache", System.IO.Path.Combine(IconRoot, "hicolor")),
        };
        if (applications)
            tools.Insert(0, ("update-desktop-database",
                System.IO.Path.Combine(DataHome, "applications")));

        Task.Run(() =>
        {
            foreach (var (tool, argument) in tools)
            {
                try
                {
                    var info = new ProcessStartInfo(tool) { UseShellExecute = false };
                    info.ArgumentList.Add(argument);
                    using var process = Process.Start(info);
                    process?.WaitForExit(10_000);
                }
                catch (Exception) { /* not installed, and not needed */ }
            }
        });
    }
}
