using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Smylte.Desktop;

/// The opt-in that reaches the taskbar.
///
/// `Form.Icon` cannot change the taskbar button on a default Windows 11 install.
/// With "Combine taskbar buttons" set to Always — the default — the button is a
/// GROUP, and per Raymond Chen the group's icon is looked up from a Start-menu
/// shortcut, then a desktop shortcut, then the executable. The window's own icon
/// is never consulted.
///
/// So this writes a Start-menu shortcut carrying the chosen icon and the same
/// AppUserModelID the process sets, which is what makes the shell match the two.
/// It is off by default and stays off unless asked: this client otherwise
/// installs nothing anywhere, and desktop/README.md makes a point of it ("That
/// is the whole install"). Turning it off removes the shortcut again.
///
/// Every path is best-effort. A shortcut is a nicety; failing to write one must
/// not cost anyone their window, and there are real reasons it can fail —
/// controlled folder access, a roaming profile, group policy on the Start menu.
internal static class ShellShortcut
{
    private static string LinkPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
        "Programs", "Smylte.lnk");

    /// Beside settings.json, because a shortcut references an icon FILE — an
    /// embedded resource is not addressable by the shell — and this is the one
    /// directory the client already owns per user.
    private static string IconPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "Smylte", "icon.ico");

    /// Bring the shortcut in line with the settings. Safe to call on every
    /// change; it rewrites rather than diffing, because the inputs (chosen icon,
    /// resolved theme, exe path) are all cheap to restate and a stale shortcut
    /// is the failure this exists to avoid.
    public static void Sync(Settings settings)
    {
        try
        {
            if (!settings.StartMenuShortcut)
            {
                if (File.Exists(LinkPath)) File.Delete(LinkPath);
                return;
            }

            var exe = Environment.ProcessPath;
            if (string.IsNullOrEmpty(exe)) return;

            if (!WriteIcon(IconLibrary.Parse(settings.IconChoice))) return;
            Write(exe, IconPath);
        }
        catch (Exception)
        {
            // Controlled folder access, policy, a read-only profile. The app is
            // unaffected; only the taskbar grouping is.
        }
    }

    /// Copy the chosen variant out of the exe's resources onto disk.
    ///
    /// The RESOLVED choice, not the literal one: a shortcut is a static file, so
    /// "Auto" has to be answered now. That is also this feature's one real
    /// wrinkle — the shortcut does not follow a later theme change until
    /// something calls Sync again, which is why MainForm re-syncs whenever the
    /// icon is applied.
    private static bool WriteIcon(IconChoice choice)
    {
        using var icon = IconLibrary.Load(choice);
        if (icon is null) return false;
        Directory.CreateDirectory(Path.GetDirectoryName(IconPath)!);
        // A temp-then-move, because the shell may have the current file open and
        // a half-written .ico is a broken shortcut rather than a missing one.
        var temp = IconPath + ".tmp";
        using (var stream = File.Create(temp)) icon.Save(stream);
        File.Move(temp, IconPath, overwrite: true);
        return true;
    }

    private static void Write(string target, string iconFile)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(LinkPath)!);
        var link = (IShellLinkW)new ShellLink();
        link.SetPath(target);
        link.SetWorkingDirectory(Path.GetDirectoryName(target) ?? "");
        link.SetDescription("Smylte — tasks and calendar");
        link.SetIconLocation(iconFile, 0);

        // Without this the shell has no way to associate the shortcut with the
        // running process, and the grouped button falls back to the exe's own
        // compiled icon — i.e. the whole feature quietly does nothing.
        var store = (IPropertyStore)link;
        var key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
        InitPropVariantFromString(Program.AppUserModelId, out var value);
        try
        {
            store.SetValue(ref key, ref value);
            store.Commit();
        }
        finally
        {
            PropVariantClear(ref value);
        }

        ((IPersistFile)link).Save(LinkPath, fRemember: true);
        Marshal.FinalReleaseComObject(link);
    }

    // ── the COM surface, declared rather than referenced ────────────────────
    //
    // These are the stock shell interfaces. They are hand-declared because the
    // alternative is a COM interop assembly for four methods, and because the
    // vtable order below is the contract — reordering a member compiles and then
    // calls the wrong function at runtime. Only the members used are named; the
    // unused slots are still declared, in order, so the layout is right.

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink { }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder file,
                     int maxPath, IntPtr findData, int flags);
        void GetIDList(out IntPtr pidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder name, int maxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder dir, int maxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder args, int maxArgs);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int showCmd);
        void SetShowCmd(int showCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder path,
                             int maxPath, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pathRel, int reserved);
        void Resolve(IntPtr hwnd, int flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PropertyKey(Guid formatId, uint propertyId)
    {
        public Guid FormatId = formatId;
        public uint PropertyId = propertyId;
    }

    /// Only ever holds a string here, but it must be laid out at the full native
    /// size or SetValue writes past the end of the managed struct.
    [StructLayout(LayoutKind.Sequential)]
    private struct PropVariant
    {
        public ushort Type;
        public ushort Reserved1, Reserved2, Reserved3;
        public IntPtr Value;
        public IntPtr Value2;
    }

    [DllImport("propsys.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void InitPropVariantFromString(
        [MarshalAs(UnmanagedType.LPWStr)] string value, out PropVariant variant);

    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PropVariant variant);
}
