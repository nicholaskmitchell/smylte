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

    // ── the floating focus window ─────────────────────────────────────────
    //
    // Four verbs rather than one "window(action)" call, so the interface stays
    // a list of things the page may ask for and the string dispatch lives in
    // LocalServer, where it is tested. Every one is answered with State(), which
    // carries `floating`, `pinned` and `nativeDrag` for the page to reconcile.

    /// Open the focus surface in its own small window, on top of other windows,
    /// and send this one to the taskbar. Called again while it is open, it
    /// brings the floating window forward instead.
    void Float();

    /// Close the floating window and bring this one back to where it was.
    void Dock();

    /// Whether the floating window stays above other windows. Remembered.
    void Pin(bool onTop);

    /// Start a native move of the floating window from a press on its page.
    /// The FALLBACK: the page normally marks itself `app-region: drag` and the
    /// WebView2 runtime moves the window itself; this is for a runtime too old
    /// to do that, and it only works while the mouse button is still down.
    void Drag();
}
