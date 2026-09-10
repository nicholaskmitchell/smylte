using System.Reflection;

namespace Smylte.Desktop;

/// The four icon variants the binary carries, and getting them somewhere the
/// desktop can see them.
///
/// **Why this is unpacking files rather than loading an image.** The Windows
/// client sets `Form.Icon` from an embedded `.ico`. GTK4 removed the equivalent:
/// a window's icon is set by NAME and looked up in the icon theme, and there is
/// no "set this window's icon to these pixels". So the four variants are
/// unpacked once into the client's own data folder, that folder is added to the
/// icon theme's search path, and switching variants afterwards is a single
/// `SetIconName` — which is cheaper than the Windows path, not dearer.
///
/// **Where Linux is better than Windows, and the docs should say so.** On
/// Windows the window's own icon never reaches the grouped taskbar button; only
/// a Start-menu shortcut does, which is why `ShellShortcut` exists. Here the
/// same `SetIconName` reaches the title bar, Alt-Tab and the window switcher
/// with nothing installed anywhere. The desktop entry buys something different
/// — the app grid, search, and an icon for the launcher rather than for the
/// window — which is why the toggle is still worth having and why its hint text
/// has to say a different thing on each platform.
internal static class IconAssets
{
    /// Shared with the generator and the test suite — see
    /// IconChoices.FreedesktopSizes for why the list lives there.
    internal static int[] Sizes => IconChoices.FreedesktopSizes;

    /// The variant names as the generator spells them, lowercased from the
    /// IconChoice members. `Auto` is absent on purpose: it is never a file.
    internal static string FileName(IconChoice resolved, int size) =>
        $"{resolved.ToString().ToLowerInvariant()}-{size}.png";

    internal static string SvgName(IconChoice resolved) =>
        $"{resolved.ToString().ToLowerInvariant()}.svg";

    /// The icon-theme name for a variant, e.g.
    /// `com.nicholaskmitchell.Smylte-ink`. The unsuffixed id is reserved for
    /// the desktop entry, which cannot follow a theme and gets a copy of
    /// whichever variant is resolved at the time.
    internal static string IconName(IconChoice resolved) =>
        $"{Program.AppId}-{resolved.ToString().ToLowerInvariant()}";

    /// What `Auto` means right now.
    public static IconChoice Resolve(Settings settings) =>
        IconChoices.Resolve(IconChoices.Parse(settings.IconChoice), ColourScheme.SystemUsesLightTheme());

    /// `<DataFolder>/icons` — a private hicolor tree, added to the search path
    /// rather than installed, so the window icon works without the client
    /// having written anything outside its own folder. That matters: the
    /// Windows README makes a point that the client installs nothing anywhere,
    /// and this keeps that true for everything except the opt-in entry.
    public static string ThemeDirectory(Settings settings) =>
        Path.Combine(settings.DataFolder, "icons");

    /// Unpack every variant at every size, plus the scalable SVGs, and hand the
    /// directory to the icon theme.
    ///
    /// Rewrites rather than diffing, for the reason ShellShortcut gives about
    /// its own shortcut: the inputs are cheap to restate, and a half-updated
    /// icon tree is the failure this exists to avoid. Best-effort throughout —
    /// a client with no icon is a working client.
    public static void Install(Settings settings, Gdk.Display display)
    {
        var root = ThemeDirectory(settings);
        try
        {
            foreach (var choice in new[] { IconChoice.Paper, IconChoice.Ink, IconChoice.Accent, IconChoice.Mark })
            {
                foreach (var size in Sizes)
                {
                    var target = Path.Combine(root, "hicolor", $"{size}x{size}", "apps",
                        IconName(choice) + ".png");
                    Unpack(FileName(choice, size), target);
                }
                Unpack(SvgName(choice),
                    Path.Combine(root, "hicolor", "scalable", "apps", IconName(choice) + ".svg"));
            }

            // No index.theme and no icon cache, deliberately. GTK scans a search
            // path directly when there is no cache; a STALE cache, by contrast,
            // wins over the directory and is worse than none.
            Gtk.IconTheme.GetForDisplay(display).AddSearchPath(root);
        }
        catch (Exception)
        {
            // Read-only home, full disk. The window falls back to whatever the
            // theme has for the application id, which is usually nothing — a
            // generic icon, which is what the Windows client's own `catch`
            // around its icon load settles for too.
        }
    }

    /// Write one variant's files out under `name`, for the desktop entry, which
    /// references an icon FILE rather than a resource and so needs the resolved
    /// choice materialised. Returns false if nothing could be written.
    public static bool Export(IconChoice resolved, string root, string name)
    {
        var wrote = false;
        foreach (var size in Sizes)
        {
            var target = Path.Combine(root, "hicolor", $"{size}x{size}", "apps", name + ".png");
            if (Unpack(FileName(resolved, size), target)) wrote = true;
        }
        Unpack(SvgName(resolved), Path.Combine(root, "hicolor", "scalable", "apps", name + ".svg"));
        return wrote;
    }

    /// Remove what Export wrote. Used when the entry is turned back off, so the
    /// toggle leaves nothing behind — the same symmetry ShellShortcut keeps.
    public static void Remove(string root, string name)
    {
        foreach (var size in Sizes)
            Delete(Path.Combine(root, "hicolor", $"{size}x{size}", "apps", name + ".png"));
        Delete(Path.Combine(root, "hicolor", "scalable", "apps", name + ".svg"));
    }

    private static void Delete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch (Exception) { /* best effort */ }
    }

    private static bool Unpack(string resource, string target)
    {
        try
        {
            using var stream = typeof(IconAssets).Assembly
                .GetManifestResourceStream("icons." + resource);
            if (stream is null) return false;

            Directory.CreateDirectory(Path.GetDirectoryName(target)!);

            // Temp-then-move, because the shell may have the current file open
            // and a half-written PNG is a broken icon rather than a missing one
            // — the same reasoning ShellShortcut.WriteIcon states.
            var temp = target + ".tmp";
            using (var file = File.Create(temp)) stream.CopyTo(file);
            File.Move(temp, target, overwrite: true);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
