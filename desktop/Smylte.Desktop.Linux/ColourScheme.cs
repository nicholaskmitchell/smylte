namespace Smylte.Desktop;

/// Is the desktop drawing itself light or dark?
///
/// The Windows client reads `SystemUsesLightTheme` out of the registry and
/// listens for `WM_SETTINGCHANGE` / `ImmersiveColorSet`. The freedesktop
/// equivalent is the **XDG settings portal**: one D-Bus call for the value, one
/// signal for changes, and it is what GNOME, KDE and libadwaita all agree on —
/// so an app that reads it follows the same switch the rest of the desktop does.
///
/// Deliberately not `org.gnome.desktop.interface color-scheme` via GSettings.
/// That would be GNOME-only, and worse, `g_settings_new` on a schema that is not
/// installed does not fail — it aborts the process. A missing portal here is a
/// caught exception and a sensible default.
///
/// The default when nothing answers is LIGHT, matching what `IconLibrary`'s own
/// `catch` returns on Windows: on a system too bare to have a portal, one of the
/// two plates has to be picked, and picking the same one both clients pick keeps
/// the two behaving alike.
internal static class ColourScheme
{
    private const string PortalBus = "org.freedesktop.portal.Desktop";
    private const string PortalPath = "/org/freedesktop/portal/desktop";
    private const string SettingsInterface = "org.freedesktop.portal.Settings";
    private const string Namespace = "org.freedesktop.appearance";
    private const string Key = "color-scheme";

    /// 0 = no preference, 1 = prefer dark, 2 = prefer light. Only 1 is dark:
    /// "no preference" is the desktop saying it has not been told, which is
    /// light in practice and is what every other client treats it as.
    private const uint PreferDark = 1;

    public static bool SystemUsesLightTheme()
    {
        try
        {
            return Read() != PreferDark;
        }
        catch (Exception)
        {
            // No portal, no session bus, a portal that does not carry the
            // appearance namespace. All the same answer.
            return true;
        }
    }

    private static uint Read()
    {
        var bus = Gio.DBusConnection.Get(Gio.BusType.Session);
        var reply = bus.CallSync(
            PortalBus, PortalPath, SettingsInterface, "Read",
            GLib.Variant.NewTuple(new[] { GLib.Variant.NewString(Namespace), GLib.Variant.NewString(Key) }),
            null, Gio.DBusCallFlags.None, 2000, null);

        // **The portal nests the value TWICE**, and that is the documented
        // reason `ReadOne` was added and this method deprecated: `Read` was
        // meant to hand back one layer of variant and hands back two, so the
        // reply is (v) holding a v holding the u. Unwrapping once left a
        // variant where the uint was expected; `g_variant_get_uint32` then
        // failed its type check, logged a GLib CRITICAL and returned 0 — which
        // is not PreferDark, so every desktop in the world read as light and
        // the catch that exists to supply that default was never reached.
        //
        // Unwrapped in a loop rather than exactly twice, because `ReadOne`
        // nests once and a portal old enough to lack it nests twice, and this
        // has to be right on both.
        var boxed = reply.GetChildValue(0);
        for (var depth = 0; depth < 4 && boxed.GetTypeString() == "v"; depth++)
            boxed = boxed.GetVariant();

        // Checked, not assumed. A shape this does not recognise throws, and the
        // caller's catch turns that into the documented light default — which
        // is the difference between defaulting and silently misreading.
        if (boxed.GetTypeString() != "u")
            throw new InvalidOperationException(
                $"The settings portal answered {Key} with {boxed.GetTypeString()}, not a uint32.");

        return boxed.GetUint32();
    }

    /// Call `onChanged` whenever the desktop's colour scheme flips.
    ///
    /// The counterpart of the Windows client's `WM_SETTINGCHANGE` handling, and
    /// it matters for the same reason: `Auto` picks the plate that CONTRASTS
    /// with the shell, so an icon chosen at launch is the wrong one the moment
    /// somebody switches to dark. Best-effort — a missing portal costs the
    /// live update, not the icon.
    public static void Watch(Action onChanged)
    {
        try
        {
            var bus = Gio.DBusConnection.Get(Gio.BusType.Session);
            bus.SignalSubscribe(
                PortalBus, SettingsInterface, "SettingChanged", PortalPath, Namespace,
                Gio.DBusSignalFlags.None,
                (_, _, _, _, _, parameters) =>
                {
                    // (namespace, key, value). Only the appearance key matters;
                    // the portal emits this for every setting it carries.
                    try
                    {
                        var key = parameters.GetChildValue(1).GetString(out _);
                        if (key == Key) onChanged();
                    }
                    catch (Exception) { /* a shape we do not recognise */ }
                });
        }
        catch (Exception) { /* no portal; the value read at launch stands */ }
    }
}
