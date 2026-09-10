using System.Runtime.CompilerServices;

namespace Smylte.Desktop;

internal static class Program
{
    /// Reverse-DNS, and it is three things at once: the D-Bus name that makes
    /// this a single-instance application, the Wayland `app_id` and X11
    /// `WM_CLASS` the shell matches a window to a launcher by, and the basename
    /// of the desktop entry. All three have to be the same string or the dash
    /// shows a running window under a generic icon — so it is written once,
    /// here, and everything else reads it.
    ///
    /// No version segment, for the reason the Windows client's AppUserModelID
    /// gives: this is the app's identity across upgrades, and a bump would
    /// orphan a pinned launcher.
    internal const string AppId = "com.nicholaskmitchell.Smylte";

    private static int Main(string[] args)
    {
        // ── everything before Gtk() must not name a GirCore type ────────────
        //
        // Not a style rule. GirCore resolves its native libraries from a module
        // initialiser that runs the first time the JIT compiles a method
        // MENTIONING one of its types — so a stray `Gtk.Window` in a method
        // reached before the environment is set would dlopen GTK with the wrong
        // backend, or dlopen a library this system does not have and take the
        // process down before any of the reporting below could run. The GTK
        // half lives in its own [MethodImpl(NoInlining)] method for the same
        // reason: inlining it up here would drag the type references with it.

        var settings = Settings.Load();

        if (args.Any(a => a.Equals("--check", StringComparison.OrdinalIgnoreCase)))
            return Check();

        // The display backend, chosen before GDK looks. See Settings.Backend for
        // why X11 is the default; the short version is that three of the
        // floating window's four properties have no Wayland protocol an
        // ordinary client can use.
        var backend = settings.Backend?.Trim().ToLowerInvariant();

        // Asking for X11 when there is no X server to ask is worse than not
        // asking: GDK does not fall back when GDK_BACKEND is set explicitly, it
        // fails to open the display and the process dies with `cannot open
        // display` — for a DEFAULT setting, on a Wayland session that simply
        // has no XWayland. DISPLAY is the cheap, reliable tell: XWayland sets
        // it, and a session without one does not.
        if (backend == "x11" && string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DISPLAY")))
            backend = null;

        if (backend is "x11" or "wayland")
            Environment.SetEnvironmentVariable("GDK_BACKEND", backend);

        // WebKitGTK's DMA-BUF renderer draws nothing at all on the NVIDIA
        // proprietary driver: the window and its header bar appear, the page
        // area stays white, and no error is printed anywhere. It is the single
        // most likely way this client looks broken on a machine where it is
        // fine, so the common cause is detected rather than documented.
        // /proc/driver/nvidia/version exists only when the proprietary module
        // is loaded — nouveau does not create it — which is exactly the
        // population that needs this.
        if (settings.DisableDmabufRenderer || File.Exists("/proc/driver/nvidia/version"))
            Environment.SetEnvironmentVariable("WEBKIT_DISABLE_DMABUF_RENDERER", "1");

        var missing = NativeCheck.Missing();
        if (missing.Count > 0)
        {
            NativeCheck.Report(NativeCheck.Explain(missing), settings.DataFolder);
            return 1;
        }

        // A client the updater just swapped in is started BY the one it
        // replaces, which is still running. Wait for it to leave before asking
        // for the single-instance name, or this launch is answered as a remote
        // activation — it would raise the old window and exit, and the update
        // would look like it did nothing at all. Only then can the retired file
        // be deleted.
        if (Updater.AfterUpdatePid(args) is { } previous) Updater.WaitForPreviousClient(previous);
        Updater.RemoveStaleClient(Environment.ProcessPath);

        // BEFORE Gtk(), and that is the point of it being its own path.
        // Writing a desktop entry is file IO — it opens no window and needs no
        // compositor — but `Gtk.Module.Initialize` calls `gtk_init`, which
        // fails outright with "Failed to open display" over SSH or from a TTY.
        // Which is exactly where somebody who wants a launcher without opening
        // the app would be typing this.
        foreach (var (flag, wanted) in new[] { ("--install", true), ("--uninstall", false) })
        {
            if (args.Any(a => a.Equals(flag, StringComparison.OrdinalIgnoreCase)))
                return Install(settings, wanted);
        }

        return Gtk(args, settings);
    }

    /// `--check`: do the native libraries this client needs resolve?
    ///
    /// Exists for CI. Everything else about this client needs a display and a
    /// compositor, which no runner has — but whether GirCore's sonames match
    /// what a distribution actually installs is exactly the kind of thing that
    /// breaks silently and is worth a red build. It answers that and nothing
    /// more: symbols resolving is not the same as the app rendering, and the
    /// README should not let it be read as such.
    private static int Check()
    {
        var missing = NativeCheck.Missing();
        if (missing.Count > 0)
        {
            Console.Error.Write(NativeCheck.Explain(missing));
            return 1;
        }
        Console.WriteLine("All native libraries resolved.");
        return 0;
    }

    /// `--install` / `--uninstall`: write or remove the desktop entry and the
    /// icons it points at, and persist the same field the Appearance toggle
    /// sets, so the two never disagree.
    ///
    /// Gio only — never Gtk. The colour scheme comes over D-Bus, which has
    /// nothing to do with a display, and reading it is what lets `Auto` pick
    /// the right plate for an entry that cannot follow a theme afterwards.
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Install(Settings settings, bool wanted)
    {
        GLib.UnhandledException.SetHandler(ex => Log(settings, ex));
        Gio.Module.Initialize();

        settings.StartMenuShortcut = wanted;
        try { settings.Save(); }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Could not save settings: {ex.Message}");
            return 1;
        }

        if (!DesktopEntry.Sync(settings, IconAssets.Resolve(settings)))
        {
            Console.Error.WriteLine(
                $"Could not write {DesktopEntry.Path}. Check that the directory is writable.");
            return 1;
        }

        Console.WriteLine(wanted
            ? $"Installed {DesktopEntry.Path}"
            : $"Removed {DesktopEntry.Path}");
        return 0;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Gtk(string[] args, Settings settings)
    {
        // FIRST, before any window exists. With no handler installed, GirCore
        // prints an exception that reaches a native callback boundary and calls
        // Environment.Exit(1) — so every signal handler in this client would be
        // a process-killer by default. That is the opposite of how the shared
        // code is written: it is full of deliberate `catch (Exception)` blocks
        // whose whole premise is that a cosmetic failure costs you the icon,
        // never the window. This is the Linux equivalent of that premise.
        GLib.UnhandledException.SetHandler(ex => Log(settings, ex));

        // EXPLICIT, and it has to be. GirCore's `Module.Initialize` is not a
        // [ModuleInitializer] — it is an ordinary method that registers the
        // DllImport resolver mapping the logical names in the generated
        // bindings ("Gtk", "WebKit", "Soup") onto real sonames. Gtk's runs
        // itself when an Application is constructed, which is why the window
        // came up; WebKit's and Soup's do not, and without them the first
        // WebKit call fails with `Unable to load shared library 'WebKit'`
        // while everything around it works. Found by running it, not by
        // reading it — the build is clean either way.
        //
        // After the environment and the preflight above: this is what dlopens
        // the libraries, so it must not run before they have been checked for.
        global::Gtk.Module.Initialize();
        WebKit.Module.Initialize();
        Soup.Module.Initialize();

        // What the backend actually turned out to be, which is the only thing
        // that can answer whether the floating window may stay on top. Read
        // back from the environment rather than from the setting, because the
        // DISPLAY check above can have overruled it.
        X11Window.Active = Environment.GetEnvironmentVariable("GDK_BACKEND") == "x11";

        var wantsSetup = args.Any(a =>
            a.Equals("--setup", StringComparison.OrdinalIgnoreCase) ||
            a.Equals("/setup", StringComparison.OrdinalIgnoreCase));

        var app = global::Gtk.Application.New(AppId, Gio.ApplicationFlags.HandlesCommandLine);

        // GTK derives the X11 WM_CLASS from the program name, which would
        // otherwise be the binary's — `Smylte-linux-x86_64`. The shell matches
        // a window to its launcher on that string, so without this the dash
        // shows a running window as an unnamed generic entry even with the
        // desktop file installed.
        GLib.Functions.SetPrgname(AppId);
        global::Gtk.Window.SetDefaultIconName(AppId);

        MainWindow? window = null;

        app.OnActivate += (_, _) =>
        {
            if (window is { } existing) { existing.Present(); return; }
            window = new MainWindow(app, settings);
            window.Present();

            // An unconfigured client has nothing to start: LocalServer builds a
            // Uri from the server address and throws on an empty one. Windows
            // shows the dialog BEFORE the window for the same reason; here the
            // window exists first because GTK owns the application lifetime and
            // a dialog with no window behind it would end the process when it
            // closed.
            if (!settings.IsConfigured || wantsSetup) window.OpenSetup();
            else _ = window.StartAsync();
        };

        // Where the Windows client tells a second launch "close it first, then
        // run --setup again", this one can just do it: OnCommandLine runs in
        // the PRIMARY instance, so the flag reaches the window that is already
        // open. Worth the asymmetry — the Windows message exists because a
        // second process cannot reach the first, not because being told to
        // close the app is good.
        app.OnCommandLine += (_, e) =>
        {
            // `out int argc`, not `out _`: the lambda's own discarded sender is
            // named `_`, so a discard here would bind to it and pass a
            // Gio.Application where an int belongs.
            var line = e.CommandLine.GetArguments(out int _) ?? Array.Empty<string>();
            var setup = wantsSetup || line.Any(a =>
                a.Equals("--setup", StringComparison.OrdinalIgnoreCase) ||
                a.Equals("/setup", StringComparison.OrdinalIgnoreCase));
            app.Activate();
            if (setup) window?.OpenSetup();
            return 0;
        };

        // WithSynchronizationContext, not plain Run: it installs the context
        // that puts `await` continuations back on the GTK thread. The startup
        // path is shared with the Windows client and is written as ordinary
        // async code — without this, the first continuation after an await
        // would touch a widget from a thread pool thread.
        return app.RunWithSynchronizationContext(args);
    }

    /// Somewhere to put what went wrong, since there is no Event Viewer and a
    /// launcher swallows stderr. Bounded to the last run: this is a breadcrumb
    /// for someone reporting a problem, not a log to grow forever.
    internal static void Log(Settings settings, Exception ex)
    {
        Console.Error.WriteLine(ex);
        try
        {
            var dir = string.IsNullOrEmpty(settings.DataFolder) ? Path.GetTempPath() : settings.DataFolder;
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "errors.log"),
                $"{DateTime.UtcNow:O}  {ex}{Environment.NewLine}");
        }
        catch (Exception) { /* the report is a nicety; staying up is not */ }
    }
}
