namespace Smylte.Desktop;

/// What the web app may ask of the window it is running inside.
///
/// Deliberately tiny and deliberately one-way: the page states a preference,
/// the host applies and persists it, and the fresh state comes back. There is no
/// general "call the host" channel here, because the page is the one piece of
/// this client that updates itself from a GitHub release on every launch.
///
/// Implemented by MainForm and handed to LocalServer, which serves it at
/// /desktop/*. In a browser those paths reach the deployed server instead and
/// 404, which is exactly how the SPA tells the two apart.
public interface IDesktopBridge
{
    /// Current host state as a JSON object: what the settings UI renders from.
    string State();

    /// Paint the caption bar to match the page. `background` is the app's own
    /// --bg as #RRGGBB; null or unparseable hands the frame back to Windows.
    void Appearance(string? background);

    /// Choose the window icon, and whether to keep a Start-menu shortcut — the
    /// one lever that reaches the grouped taskbar button.
    void Icon(string? choice, bool startMenuShortcut);
}
