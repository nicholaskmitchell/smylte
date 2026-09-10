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

    /// Bring the entry in line with the settings. Safe to call on every change;
    /// it rewrites rather than diffing, because the inputs (chosen icon,
    /// resolved scheme, binary path) are all cheap to restate and a stale entry
    /// is the failure this exists to avoid.
    ///
    /// Returns whether the requested state was reached, so `--install` can say
    /// something true on the way out. Nothing else looks at the answer.
    public static bool Sync(Settings settings, IconChoice resolved)
    {
        try
        {
            if (!settings.StartMenuShortcut)
            {
                if (File.Exists(Path)) File.Delete(Path);
                IconAssets.Remove(IconRoot, Program.AppId);
                Refresh();
                return true;
            }

            var exe = Environment.ProcessPath;
            if (string.IsNullOrEmpty(exe)) return false;

            // The RESOLVED choice, not the literal one. A desktop entry points
            // at a static file, so `Auto` has to be answered now — the same
            // wrinkle ShellShortcut has, and the same consequence: the entry
            // does not follow a later light/dark flip until something calls
            // Sync again, which is why the icon path re-syncs.
            if (!IconAssets.Export(resolved, IconRoot, Program.AppId)) return false;

            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
            File.WriteAllText(Path, Contents(exe), new UTF8Encoding(false));
            Refresh();
            return true;
        }
        catch (Exception)
        {
            // A read-only home, a policy-managed profile. The app is
            // unaffected; only the launcher is.
            return false;
        }
    }

    private static string Contents(string exe) =>
        $"""
        [Desktop Entry]
        Type=Application
        Name=Smylte
        Comment=Tasks and calendar
        Exec="{exe}"
        Icon={Program.AppId}
        Terminal=false
        Categories=Office;Calendar;ProjectManagement;
        StartupNotify=true
        StartupWMClass={Program.AppId}
        X-GNOME-UsesNotifications=true

        """;

    // Exec is quoted because a path can contain spaces, and it carries NO field
    // code (%u, %f): this client registers no MIME type and no URL scheme, and
    // a launcher that expands a field code the app cannot use is a launch that
    // fails for a reason nobody can see.

    /// Nudge the desktop into noticing. Both tools are optional and both are
    /// allowed to be missing — GNOME watches the applications directory itself,
    /// and these only shorten the wait on desktops that do not.
    private static void Refresh()
    {
        foreach (var (tool, argument) in new[]
        {
            ("update-desktop-database", System.IO.Path.Combine(DataHome, "applications")),
            ("gtk4-update-icon-cache", IconRoot),
        })
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
    }
}
