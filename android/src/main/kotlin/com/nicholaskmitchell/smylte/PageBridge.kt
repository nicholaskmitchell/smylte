package com.nicholaskmitchell.smylte

import android.webkit.JavascriptInterface

/// What the page can ask of the window. Exposed as `window.SmylteAndroid` to
/// every script on the page, so every method is harmless or user-mediated,
/// validates its arguments through HostProtocol on the bridge thread, and never
/// blocks waiting for the main thread (Chromium may be serving the call while
/// the UI thread waits). Only primitives and strings cross.
///
/// The set of methods is pinned by PageBridgeTest, so adding one forces a
/// review. Each body runs inside runCatching: a Java exception would reach the
/// page as a JS exception.
class PageBridge(private val host: Host) {
    interface Host {
        /// Any thread; the host posts to the main thread.
        fun colour(colour: Int)

        /// The env JSON for a page announcing `caps`. Bridge thread; must not block.
        fun hello(caps: Set<String>): String

        /// How many layers the page has open, already clamped. Bridge thread; must not block.
        fun layers(depth: Int)

        /// One of the haptics HostProtocol knows. Bridge thread; the host posts to the main thread and decides there whether it plays.
        fun haptic(kind: HostProtocol.Haptic)

        /// Start a save; false when one is already pending. Bridge thread; must not block.
        fun save(request: SaveRequest): Boolean

        /// The page's first view is up. Bridge thread; the host posts to the main thread.
        fun ready()
    }

    /// The page's background colour, from ThemeColour.WATCH_SCRIPT. At worst
    /// the bars are repainted.
    @JavascriptInterface
    fun themeColour(hex: String?) {
        runCatching { ThemeColour.parse(hex)?.let(host::colour) }
    }

    /// Once per document. Answers what the page may want to know about the
    /// device, as JSON, and records what the page says it does.
    @JavascriptInterface
    fun hello(caps: String?): String =
        runCatching { host.hello(HostProtocol.parseCaps(caps)) }.getOrDefault(HostProtocol.NO_ENV)

    /// How many layers (dialogs, sheets, popovers) the page has open. While there is
    /// one, Back goes to the page to close it. At worst a script keeps Back inside
    /// the app, which history.pushState already can; Home and Recents still work.
    @JavascriptInterface
    fun layers(depth: Int) {
        runCatching { host.layers(HostProtocol.clampLayers(depth)) }
    }

    /// A haptic for what the user just did: "confirm", "reject", "toggleOn" or
    /// "toggleOff"; any other name is ignored. At worst a script buzzes the phone
    /// while it is being touched: the host plays one only while a finger is on
    /// the page or just after, at most twice a touch (HapticGate), and the
    /// system's touch feedback setting still decides.
    @JavascriptInterface
    fun haptic(kind: String?) {
        runCatching { HostProtocol.hapticNamed(kind)?.let(host::haptic) }
    }

    /// Asks to save a file through Android's own dialog; true when the request
    /// was accepted, and the outcome follows as an event. There is no touch
    /// gate: the picker is the user's consent, and an accessibility or keyboard
    /// activation produces no touch.
    @JavascriptInterface
    fun saveFile(name: String?, mime: String?, text: String?): Boolean =
        runCatching { SaveRequest.of(name, mime, text)?.let(host::save) ?: false }.getOrDefault(false)

    /// The page's first view is up: the app has signed in, or shows its sign-in
    /// or offline screen. The host stops holding the splash screen, if it still
    /// is. It takes nothing, so there is nothing to check; at worst a script
    /// ends the splash early.
    @JavascriptInterface
    fun ready() {
        runCatching { host.ready() }
    }
}
