using System.Runtime.InteropServices;
using System.Text;

namespace Smylte.Desktop;

/// Are the libraries this client draws with actually installed?
///
/// **Why this exists at all.** The Windows client has one runtime dependency
/// and Windows ships it; WebView2 missing is a case rare enough that catching
/// `WebView2RuntimeNotFoundException` covers it. Here the two libraries are the
/// distribution's, and a machine can legitimately not have them — a server
/// install, a minimal spin, a non-GNOME desktop that never pulled WebKitGTK in.
/// What happens then is the problem: GirCore resolves its `DllImport`s the
/// first time a bound type is touched, so the failure arrives as a
/// `TypeInitializationException` out of a static constructor, before there is
/// any GTK with which to draw a dialog explaining it. The user sees a process
/// that exits with a stack trace, or under a launcher, nothing at all.
///
/// So the check runs FIRST, in managed code, using only `NativeLibrary` — and
/// says the package name. `sudo dnf install webkitgtk6.0` is a fix; "Unhandled
/// exception. System.TypeInitializationException" is not.
///
/// **Nothing here may touch a GirCore type.** Referencing one is enough: the
/// JIT loads the assembly when it compiles the method, its module initialiser
/// runs, and the dlopen this exists to pre-empt has already happened and
/// already failed. That is why this file imports nothing from Gtk.
internal static class NativeCheck
{
    /// Soname, what it is, and the Fedora package that carries it. The sonames
    /// are the ones GirCore's own resolver asks for — checking a different
    /// spelling would prove nothing about whether the binding will load.
    private static readonly (string Soname, string What, string Fedora)[] Required =
    {
        ("libgtk-4.so.1", "GTK 4, the toolkit the window is drawn with", "gtk4"),
        ("libwebkitgtk-6.0.so.4", "WebKitGTK, the engine the app runs in", "webkitgtk6.0"),
        ("libsoup-3.0.so.0", "libsoup, which WebKitGTK does its networking with", "libsoup3"),
    };

    /// The libraries that could not be loaded, in the order above. Empty is the
    /// good answer.
    public static IReadOnlyList<(string Soname, string What, string Fedora)> Missing()
    {
        var missing = new List<(string, string, string)>();
        foreach (var lib in Required)
        {
            // TryLoad, not Load: a failure here is the thing being measured, and
            // a throw would make the reporting path the exceptional one.
            if (!NativeLibrary.TryLoad(lib.Soname, out _)) missing.Add(lib);
        }
        return missing;
    }

    /// What to print when something is missing. One paragraph, then the command
    /// that fixes it — because the reader is at a terminal or a log file, and
    /// this is the only chance to say anything at all.
    public static string Explain(IReadOnlyList<(string Soname, string What, string Fedora)> missing)
    {
        var text = new StringBuilder();
        text.AppendLine("Smylte could not start: it needs libraries this system does not have.");
        text.AppendLine();
        foreach (var (soname, what, _) in missing)
            text.AppendLine($"  {soname}  —  {what}");
        text.AppendLine();
        text.AppendLine("On Fedora:");
        text.AppendLine($"  sudo dnf install {string.Join(' ', missing.Select(m => m.Fedora))}");
        text.AppendLine();
        text.AppendLine("On Debian or Ubuntu the same libraries are called");
        text.AppendLine("  libgtk-4-1, libwebkitgtk-6.0-4, libsoup-3.0-0");
        return text.ToString();
    }

    /// Say it somewhere a person will see it.
    ///
    /// Three attempts, in order of how likely the reader is to be looking:
    /// stderr always, because a terminal launch is how most people first run a
    /// downloaded binary; a log file beside the client's own data, because a
    /// launcher swallows stderr entirely; and a desktop notification or dialog
    /// through whichever of three tools exists, because a double-click from a
    /// file manager shows neither of the first two. Every one is best-effort —
    /// the process is already failing, and failing to explain the failure must
    /// not itself throw.
    public static void Report(string message, string? logDirectory)
    {
        Console.Error.Write(message);

        if (!string.IsNullOrEmpty(logDirectory))
        {
            try
            {
                Directory.CreateDirectory(logDirectory);
                File.WriteAllText(Path.Combine(logDirectory, "startup-error.log"), message);
            }
            catch (Exception) { /* nowhere to write; stderr already has it */ }
        }

        foreach (var (tool, args) in new[]
        {
            ("zenity", new[] { "--error", "--no-wrap", "--title=Smylte", "--text=" + message }),
            ("kdialog", new[] { "--error", message }),
            ("notify-send", new[] { "-u", "critical", "Smylte", message }),
        })
        {
            try
            {
                var info = new System.Diagnostics.ProcessStartInfo(tool) { UseShellExecute = false };
                foreach (var a in args) info.ArgumentList.Add(a);
                using var process = System.Diagnostics.Process.Start(info);
                if (process is null) continue;
                process.WaitForExit(15_000);
                return;                       // one of them worked; do not stack dialogs
            }
            catch (Exception) { /* not installed; try the next */ }
        }
    }
}
