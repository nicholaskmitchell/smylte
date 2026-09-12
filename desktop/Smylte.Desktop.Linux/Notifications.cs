namespace Smylte.Desktop;

/// Turning the page's notifications into the desktop's.
///
/// WebKitGTK has no presenter of its own: returning FALSE from
/// `show-notification` means the notification is simply never shown. So this
/// takes it and re-raises it through `GNotification`, which reaches
/// `org.freedesktop.Notifications` on any desktop and GNOME's own shell on
/// GNOME.
///
/// **This is the second reason the desktop entry matters.** GNOME resolves a
/// notification's application name and icon from the `.desktop` file whose
/// basename matches the sending application id. With no entry installed the
/// notification still arrives — through the freedesktop fallback — but under a
/// generic icon and with no app name, which is worth saying in the Appearance
/// hint rather than leaving someone to wonder.
internal static class Notifications
{
    public static void Attach(WebKit.WebView view, Gtk.Application app, Settings settings)
    {
        view.OnShowNotification += (_, e) =>
        {
            try
            {
                var source = e.Notification;
                var notification = Gio.Notification.New(source.GetTitle() ?? "Smylte");

                var body = source.GetBody();
                if (!string.IsNullOrEmpty(body)) notification.SetBody(body);
                // The APP ID, not the variant name. The suffixed names
                // (`…Smylte-ink`) live in <DataFolder>/icons, which this
                // process adds to its own GtkIconTheme search path and no
                // notification daemon has ever heard of — gnome-shell, dunst
                // and mako all resolve against $XDG_DATA_HOME/icons and
                // $XDG_DATA_DIRS. The unsuffixed id is the one name the client
                // writes there, and only when the desktop entry is installed,
                // so this resolves in exactly the case where anything can.
                //
                // `g_themed_icon_new` has no fallback chain of its own, which
                // is why an unresolvable name here was not "the desktop entry's
                // icon instead" but an empty icon slot.
                notification.SetIcon(Gio.ThemedIcon.New(Program.AppId));

                // The tag, when the page sets one, is what makes a replacement
                // replace rather than stack — the focus surface re-raises the
                // same countdown as it changes. Falling back to the WebKit id
                // keeps every notification addressable either way.
                var id = source.GetTag();
                app.SendNotification(
                    string.IsNullOrEmpty(id) ? source.GetId().ToString() : id, notification);
            }
            catch (Exception ex)
            {
                Program.Log(settings, ex);
                // Returning false here would hand it back to WebKit, which
                // shows nothing. There is no better fallback than silence, and
                // a throw would take the process down.
            }
            return true;
        };
    }
}
