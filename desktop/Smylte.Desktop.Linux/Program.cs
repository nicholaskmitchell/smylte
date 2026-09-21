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

        // The display backend, chosen before GDK looks. DisplayBackend carries
        // the whole argument, including why the default stopped being a flat
        // "x11" — the short version is that forcing XWayland to buy three
        // properties of the floating window cost every Wayland user a blurry,
        // single-scale main window on every monitor they own.
        var wayland = Environment.GetEnvironmentVariable("WAYLAND_DISPLAY");
        var display = Environment.GetEnvironmentVariable("DISPLAY");
        var backend = DisplayBackend.Choose(settings.Backend, wayland, display);

        // NativeEnv, not Environment.SetEnvironmentVariable — see that file.
        // The managed API writes a dictionary the runtime keeps to itself; GDK
        // reads getenv(3), so this asked for X11 and silently got whatever GDK
        // would have chosen anyway.
        if (backend is not null)
            NativeEnv.Set("GDK_BACKEND", backend);

        // WebKitGTK's DMA-BUF renderer draws nothing at all on the NVIDIA
        // proprietary driver: the window and its header bar appear, the page
        // area stays white, and no error is printed anywhere. It is the single
        // most likely way this client looks broken on a machine where it is
        // fine, so the common cause is detected rather than documented.
        // /proc/driver/nvidia/version exists only when the proprietary module
        // is loaded — nouveau does not create it — which is exactly the
        // population that needs this.
        if (settings.DisableDmabufRenderer || File.Exists("/proc/driver/nvidia/version"))
            NativeEnv.Set("WEBKIT_DISABLE_DMABUF_RENDERER", "1");

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
        Updater.RemoveRetiredClient(Environment.ProcessPath);

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

        // X11Window.Active is NOT set here. The environment is a request; the
        // display is the answer, and the two can differ — GDK ignores a backend
        // it cannot open and picks another. MainWindow asks the display it
        // actually got, because a capability flag derived from an intention is
        // what told the page it could pin on a session where it could not.

        // Not readonly, and that is the point: it is consumed by the first
        // activation and cleared. Left set, it was re-read on every later
        // activation — so after one `--setup` launch, every subsequent click on
        // the launcher reopened the setup dialog over the running app for the
        // rest of the session.
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
            var setupNow = wantsSetup;
            wantsSetup = false;

            // This is the ONLY place that knows there is nothing to start, so
            // it is the only place that says so. MainWindow used to re-derive
            // it when the dialog closed, from `_server is null` — which also
            // means "a start is still running" and "a start just failed", and
            // answered both with "not configured yet".
            if (!settings.IsConfigured)
            {
                window.ShowUnconfigured();
                window.OpenSetup();
                return;
            }

            // Configured: START, and open the dialog over the top when asked.
            // Both halves, not one or the other — a cold `--setup` that only
            // opened the dialog left nothing behind it, so cancelling sat on
            // "Starting…" forever. This also makes a cold `--setup` behave
            // exactly like one delivered to a running instance, which removes
            // an asymmetry rather than adding one.
            _ = window.StartAsync();
            if (setupNow) window.OpenSetup();
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
            var setup = line.Any(a =>
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

    /// How large errors.log may get before it is started again. A stack trace
    /// is a couple of kilobytes, so this is hundreds of them — far more than
    /// anyone reporting a problem will read, and small enough that a client
    /// looping on a failing signal handler cannot fill a disk with it.
    private const long LogLimit = 256 * 1024;

    /// Somewhere to put what went wrong, since there is no Event Viewer and a
    /// launcher swallows stderr. A breadcrumb for someone reporting a problem,
    /// not a log to grow forever.
    ///
    /// It said that second sentence already and did not do it: `AppendAllText`
    /// with nothing trimming the file. Every handler in this client routes here
    /// — that is the whole point of the GLib.UnhandledException handler — so a
    /// signal that throws on every frame writes a stack trace on every frame,
    /// into the user's data folder, unbounded. Rotated rather than truncated so
    /// the run that is failing right now cannot be the one whose evidence is
    /// thrown away.
    internal static void Log(Settings settings, Exception ex)
    {
        Console.Error.WriteLine(ex);
        try
        {
            var dir = string.IsNullOrEmpty(settings.DataFolder) ? Path.GetTempPath() : settings.DataFolder;
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "errors.log");

            var file = new FileInfo(path);
            if (file.Exists && file.Length > LogLimit)
            {
                // One generation back, replaced each time. Two files bounded at
                // the limit is the whole budget; `File.Move` with overwrite is
                // atomic, so there is no window with neither.
                try { File.Move(path, path + ".1", overwrite: true); }
                catch (Exception) { File.Delete(path); }
            }

            File.AppendAllText(path, $"{DateTime.UtcNow:O}  {ex}{Environment.NewLine}");
        }
        catch (Exception) { /* the report is a nicety; staying up is not */ }
    }
}
