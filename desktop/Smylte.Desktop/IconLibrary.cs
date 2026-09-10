using System.Reflection;
using Microsoft.Win32;

namespace Smylte.Desktop;

/// Loads the icon variants the exe carries, and picks one.
///
/// **What this can and cannot change.** Setting `Form.Icon` reaches the title
/// bar, Alt-Tab and Task Manager, and it reaches the taskbar button only for
/// someone who has set "Combine taskbar buttons: Never". On the Windows 11
/// default of "Always", the taskbar shows a GROUP icon, and per Raymond Chen
/// the group icon is looked up from a Start-menu shortcut, then a desktop
/// shortcut, then the executable — never the window's own icon. Explorer, the
/// desktop and any pinned entry likewise read the exe's compiled resource.
///
/// So the choice here is real but partial, and `ShellShortcut` is the opt-in
/// that covers the rest. The Appearance section says which is which rather than
/// letting an unchanged taskbar read as a bug.
///
/// **Why Auto is possible at all.** A .ico holds one image per size and has no
/// light/dark variant mechanism outside MSIX, which is why the compiled default
/// has to be the one colour that clears 3:1 against both taskbars. A running
/// process has no such limit: it can read the theme and choose. That is the
/// whole reason the plated variants exist.
public static class IconLibrary
{
    private static readonly Dictionary<IconChoice, string> Resources = new()
    {
        [IconChoice.Paper] = "icon-paper.ico",
        [IconChoice.Ink] = "icon-ink.ico",
        [IconChoice.Accent] = "app.ico",
        [IconChoice.Mark] = "icon-mark.ico",
    };

    /// Forwarders, so every existing caller keeps reading `IconLibrary.Parse`
    /// and `IconLibrary.Resolve`. The rules themselves live in IconChoices,
    /// which the Linux client links; only the registry read below is Windows.
    public static IconChoice Parse(string? value) => IconChoices.Parse(value);

    /// True when Windows is drawing the taskbar and system chrome light.
    ///
    /// `SystemUsesLightTheme`, not `AppsUseLightTheme`: the two are set
    /// independently and it is the SYSTEM one that governs the surface these
    /// icons sit on. Absent on Windows builds that predate the setting, where
    /// light is the right assumption.
    public static bool SystemUsesLightTheme()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            return key?.GetValue("SystemUsesLightTheme") is not int v || v != 0;
        }
        catch (Exception)
        {
            return true;
        }
    }

    /// The choice `Auto` resolves to right now. Never returns Auto.
    public static IconChoice Resolve(IconChoice choice) =>
        IconChoices.Resolve(choice, SystemUsesLightTheme());

    /// The icon for `choice`, or null if it cannot be loaded.
    ///
    /// Null rather than a throw because every caller treats the icon as
    /// cosmetic: a missing resource should cost you the monogram, never the
    /// window. Falls back to the compiled default before giving up, so a typo in
    /// a persisted choice degrades to the shipped icon rather than to none.
    public static Icon? Load(IconChoice choice)
    {
        var resolved = Resolve(choice);
        return Read(Resources[resolved]) ?? Read(Resources[IconChoice.Accent]);
    }

    private static Icon? Read(string resource)
    {
        try
        {
            var name = typeof(IconLibrary).Namespace + "." + resource;
            using var stream = typeof(IconLibrary).Assembly.GetManifestResourceStream(name);
            // Icon(Stream) sizes itself from SM_CXICON, exactly as
            // Icon(Type, string) does, and WinForms then re-runs the directory
            // best-fit at the current DPI for ICON_SMALL. Nothing here needs to
            // pick a size; the file carries all fifteen.
            return stream is null ? null : new Icon(stream);
        }
        catch (Exception)
        {
            return null;
        }
    }
}
