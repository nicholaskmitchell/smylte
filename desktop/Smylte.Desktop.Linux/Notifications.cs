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
                notification.SetIcon(Gio.ThemedIcon.New(
                    IconAssets.IconName(IconAssets.Resolve(settings))));

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
