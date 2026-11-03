package com.nicholaskmitchell.smylte

import java.util.Locale

/// The rules of the page bridge (PageBridge) and the messages the host sends
/// back to the page.
///
/// Kept free of Android classes, the JSON ones included (android.jar's copy is
/// a stub in a local unit test), so the JVM tests cover every decision made here.
/// MainActivity has no tests: what it decides goes through this object.
object HostProtocol {
    /// The DOM event the host dispatches on the page's window.
    const val EVENT = "smylte-android"

    /// Changes only when an existing env field changes meaning; adding one
    /// never does, because the page reads each field on its own.
    const val ENV_VERSION = 1

    /// What hello answers when the host failed: the page reads it as no env at
    /// all (it has no v).
    const val NO_ENV = "{}"

    /// The tones of the phone's accent palette that hello reports, in order: the
    /// system_accent1 colours of Material You (Android 12 and later), from 0
    /// (white) to 1000 (black). SystemAccent reads one named id per tone, and
    /// HostProtocolTest holds this list to android.ts's ACCENT_TONES.
    val ACCENT_TONES: List<Int> = listOf(0, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)

    const val MAX_CAPS_CHARS = 256
    const val MAX_CAPS = 16
    private val CAP = Regex("[a-z0-9]{1,16}")

    /// A script can call saveFile again the moment the picker closes. The
    /// picker needs no touch (TalkBack, Switch Access, Voice Access and
    /// keyboard activations produce none), so a new one instead waits this long
    /// after the last one closed.
    const val SAVE_BACKOFF_MS = 2_000L

    // MotionEvent's masked actions, restated because this object takes no
    // Android classes. HostProtocolTest holds them to MotionEvent's.
    const val ACTION_DOWN = 0
    const val ACTION_UP = 1
    const val ACTION_MOVE = 2
    const val ACTION_CANCEL = 3
    const val ACTION_POINTER_DOWN = 5

    enum class SaveOutcome(val wire: String) {
        SAVED("saved"),
        CANCELLED("cancelled"),
        FAILED("failed"),
    }

    enum class SaveReport { PAGE, TOAST }

    /// Where Back goes: the page's top layer, then its history, then the system;
    /// or, while the app is locked, the task to the back (MOVE_TO_BACK).
    enum class BackAction { PAGE, HISTORY, SYSTEM, MOVE_TO_BACK }

    /// The host only asks whether the page has a layer open; the bound keeps a
    /// hostile count meaningless.
    const val MAX_LAYERS = 16

    /// The haptics the page can ask for, by the name it sends. Any other name is
    /// ignored, so a page newer than this client can ask for one it lacks.
    enum class Haptic(val wire: String) {
        CONFIRM("confirm"),
        REJECT("reject"),
        TOGGLE_ON("toggleOn"),
        TOGGLE_OFF("toggleOff"),
    }

    // HapticFeedbackConstants, restated because this object takes no Android
    // classes. HostProtocolTest holds them to the platform's.
    const val FEEDBACK_CLOCK_TICK = 4
    const val FEEDBACK_CONFIRM = 16
    const val FEEDBACK_REJECT = 17
    const val FEEDBACK_TOGGLE_ON = 21
    const val FEEDBACK_TOGGLE_OFF = 22

    /// Android 14, which added TOGGLE_ON and TOGGLE_OFF.
    const val SDK_TOGGLE_FEEDBACK = 34

    /// How long after the last touch event a haptic may still play: long enough
    /// for a write that fails at once to answer the tap that started it, and
    /// short enough that a script cannot save a touch for later.
    const val HAPTIC_WINDOW_MS = 1_500L

    /// A tap's own haptic and the reject of the write it started.
    const val HAPTICS_PER_TOUCH = 2

    fun hapticNamed(name: String?): Haptic? = Haptic.values().firstOrNull { it.wire == name }

    /// The platform constant for a haptic. TOGGLE_ON and TOGGLE_OFF are Android
    /// 14's; before it both are CLOCK_TICK, because a constant the platform does
    /// not know plays nothing. CONFIRM and REJECT are Android 11's, the minimum
    /// version.
    fun hapticConstant(kind: Haptic, sdk: Int): Int = when (kind) {
        Haptic.CONFIRM -> FEEDBACK_CONFIRM
        Haptic.REJECT -> FEEDBACK_REJECT
        Haptic.TOGGLE_ON -> if (sdk >= SDK_TOGGLE_FEEDBACK) FEEDBACK_TOGGLE_ON else FEEDBACK_CLOCK_TICK
        Haptic.TOGGLE_OFF -> if (sdk >= SDK_TOGGLE_FEEDBACK) FEEDBACK_TOGGLE_OFF else FEEDBACK_CLOCK_TICK
    }

    /// The capabilities a page announces in hello. The host acts on a token
    /// only by asking for it by name, so unknown tokens are simply never
    /// consulted. Input over MAX_CAPS_CHARS is ignored whole, and a token
    /// outside [a-z0-9]{1,16} is dropped; there is no trimming.
    fun parseCaps(raw: String?): Set<String> {
        if (raw == null || raw.length > MAX_CAPS_CHARS) return emptySet()
        return raw.split(',').take(MAX_CAPS).filter { CAP.matches(it) }.toSet()
    }

    /// What hello answers. It takes a boolean and colours the host read itself,
    /// formatted here, so nothing the page sends can reach the JSON. The accent
    /// palette is left out when there is none (Android 11) and when it does not
    /// hold exactly one colour per tone, so the page never sees a partial one.
    fun envJson(clock24: Boolean, accent: List<Int>? = null): String {
        val palette = accent?.takeIf { it.size == ACCENT_TONES.size }
            ?.joinToString(",", prefix = ",\"accent\":[", postfix = "]") { "\"${accentHex(it)}\"" }
            ?: ""
        return """{"v":$ENV_VERSION,"clock24":$clock24$palette}"""
    }

    /// One palette colour as the page reads it: `#rrggbb`, lowercase, with the
    /// alpha masked off (the platform's colours are opaque ARGB ints).
    fun accentHex(argb: Int): String = "#%06x".format(Locale.ROOT, argb and 0xFFFFFF)

    fun envEvent(env: String): String = """{"type":"env","env":$env}"""

    fun savedEvent(outcome: SaveOutcome): String = """{"type":"saved","outcome":"${outcome.wire}"}"""

    /// Back, for the page to close its top layer (layers.ts).
    fun backEvent(): String = """{"type":"back"}"""

    /// The script that delivers one event to the page. The detail is always
    /// built by this object from host values, never from a string the page
    /// sent. evaluateJavascript is not subject to the page's CSP, and this
    /// script fetches nothing.
    fun eventScript(detail: String): String =
        "window.dispatchEvent(new CustomEvent('$EVENT',{detail:$detail}));"

    /// May a save dialog open now? The window must be in front with the app's
    /// own page loaded and not locked: no dialog opens over the lock, where
    /// nobody can have asked for one, and its file name is the page's text. The
    /// last dialog must also have closed long enough ago. The comparison is on
    /// `now - lastPickerClosed`, so a negative elapsed time (a clock that went
    /// backwards) is refused.
    fun allowSave(resumed: Boolean, mainFrameOurs: Boolean, now: Long, lastPickerClosed: Long?, locked: Boolean): Boolean =
        !locked && resumed && mainFrameOurs && (lastPickerClosed == null || now - lastPickerClosed >= SAVE_BACKOFF_MS)

    /// Whether a picker's answer waits rather than reaching the page now: while
    /// the window is locked, and until it has started. On Android 11 and early
    /// builds of 12 an answer can arrive before onStart, which is where the
    /// lock takes hold again after a long stay in the picker, so `locked` may
    /// not yet say what it will. A held answer is delivered at the resume or the
    /// unlock, whichever comes later (MainActivity.runHeld).
    fun holdsResult(started: Boolean, locked: Boolean): Boolean = !started || locked

    /// Run in the page as the window locks. A date or time field's picker is a
    /// dialog of its own, above the lock view and outside its FLAG_SECURE, and
    /// hiding the WebView does not close it as it closes a select's list.
    /// Blurring its field does (Blink's ChooserOnlyTemporalInputTypeView::Blur).
    /// Only such a field is touched, so no other field's blur handler runs.
    const val CLOSE_PICKER_SCRIPT =
        "(function(){var e=document.activeElement;" +
            "if(e instanceof HTMLInputElement&&/^(date|time|datetime-local|month|week)\$/.test(e.type))e.blur();})();"

    /// Where a save's result is shown. The page that asked hears it; if that
    /// document has gone, or a restored activity has no page yet, a native
    /// toast says it instead.
    fun saveReport(restored: Boolean, askedBy: Int, current: Int, alive: Boolean): SaveReport =
        if (!restored && alive && askedBy == current) SaveReport.PAGE else SaveReport.TOAST

    fun clampLayers(depth: Int): Int = depth.coerceIn(0, MAX_LAYERS)

    /// A report from a document that has since been replaced is dropped: the new
    /// one started at none (onPageStarted), and the old page's layers went with it.
    fun layersAfterReport(held: Int, depth: Int, reportedIn: Int, current: Int): Int =
        if (reportedIn == current) depth else held

    /// While the app is locked, Back never reaches the page, which the user
    /// cannot see, and never finishes the window either, which would drop
    /// whatever the page had open: it moves the task to the back. Otherwise the
    /// page's top layer first, then its history, then the system (which
    /// leaves). A page that is not the app's own cannot be sent the event.
    fun backAction(layers: Int, pageIsOurs: Boolean, canGoBack: Boolean, locked: Boolean): BackAction = when {
        locked -> BackAction.MOVE_TO_BACK
        layers > 0 && pageIsOurs -> BackAction.PAGE
        canGoBack -> BackAction.HISTORY
        else -> BackAction.SYSTEM
    }

    /// Hold an OnBackInvokedCallback only while Back stays in the app, or while
    /// the app is locked, so the system's back-to-home animation plays
    /// otherwise.
    fun wantsBackCallback(layers: Int, pageIsOurs: Boolean, canGoBack: Boolean, locked: Boolean): Boolean =
        backAction(layers, pageIsOurs, canGoBack, locked) != BackAction.SYSTEM

    /// Whether a finger is down after this event. A list of the actions that
    /// set it rather than a range: DOWN..MOVE would include UP (1). POINTER_UP
    /// leaves the state as it was, because another finger is still down.
    fun touching(actionMasked: Int, was: Boolean): Boolean = when (actionMasked) {
        ACTION_DOWN, ACTION_POINTER_DOWN, ACTION_MOVE -> true
        ACTION_UP, ACTION_CANCEL -> false
        else -> was
    }

    // ── the splash screen ───────────────────────────────────────────────────

    /// The capability a page announces in hello when it will call ready(): the
    /// host then waits for that call rather than ending the splash hold when the
    /// page has loaded.
    const val CAP_READY = "ready"

    /// Android 12, the first version with a platform splash screen.
    const val SDK_SPLASH_SCREEN = 31

    /// The longest the splash screen is held. Start-up is serial (a release
    /// check when the last is over ten minutes old, the session check, the page,
    /// the app's own /api/me), so a slow network takes longer than this, and the
    /// window's own "Starting…" then shows how far it got. Well under 5 s,
    /// because a window that has never drawn has no input focus, and a key event
    /// that waits that long for one is an ANR.
    const val SPLASH_CAP_MS = 3_000L

    /// The longest a cold start can take to reach its first window and still
    /// be taken for one. Its own measure, not the cap: a slow phone can take
    /// longer than the cap to get there, and its splash has been up all along.
    const val COLD_START_MS = 10_000L

    /// When the cap starts counting. On a cold launch (this process's first
    /// window, created soon after the process started) that is the process's
    /// start, because the platform splash has been up since the tap that
    /// started it, and the cap has to bound what the user sees: the time to
    /// reach onCreate (inflating the WebView, loading its provider) would
    /// otherwise come on top of it, and eat into the 5 s margin. Otherwise the
    /// process was already running when the tap came, so it counts from now. A
    /// start in the future (a clock that went backwards) counts from now.
    fun splashSince(now: Long, processStart: Long, firstWindow: Boolean): Long =
        if (firstWindow && now - processStart in 0 until COLD_START_MS) processStart else now

    /// How much of the cap is left. At zero or below nothing is held: a cold
    /// start that took the whole cap to reach its window shows it at once.
    fun splashLeft(now: Long, since: Long): Long = SPLASH_CAP_MS - (now - since)

    /// Whether onCreate holds the splash screen. Only a fresh launch from the
    /// launcher is sure to have one in front of the window: a window rebuilt
    /// from saved state after a renderer crash or a wallpaper change has none,
    /// nor may the window the settings screen opens, and holding their first
    /// draw would show a blank window instead. Android 11 has no platform splash.
    fun holdsSplash(sdk: Int, restored: Boolean, fromLauncher: Boolean): Boolean =
        sdk >= SDK_SPLASH_SCREEN && !restored && fromLauncher

    /// Whether a held splash screen ends now. The first of: the page said its
    /// first view is up (ready(), callable by any script, so at worst the splash
    /// ends early); a page that never announced CAP_READY (a web build from
    /// before it) has loaded; start-up failed, so the failure screen must show;
    /// the window is locked, so its lock view shows at once (holding the splash
    /// would only keep the prompt waiting, and the page is hidden either way);
    /// the cap has passed. "Loaded" is onPageFinished, which comes after the
    /// page's scripts and so after its hello. It is never onPageCommitVisible,
    /// which rests on a visual-state callback that needs a drawn window, and
    /// which can come before hello. An elapsed time below zero (a clock that
    /// went backwards) ends it too, because a hold must never outlast its cap.
    fun splashRelease(
        elapsedMs: Long,
        failed: Boolean,
        pageReady: Boolean,
        wantsReady: Boolean,
        pageFinished: Boolean,
        locked: Boolean,
    ): Boolean =
        failed || locked || pageReady || (pageFinished && !wantsReady) || elapsedMs < 0 || elapsedMs >= SPLASH_CAP_MS
}

/// A file the page asked to save, after the host has checked it. Only `of`
/// makes one, so every instance has an allowed type, a safe name and bounded
/// text.
class SaveRequest private constructor(val name: String, val mime: String, val text: String) {
    companion object {
        const val MAX_TEXT_CHARS = 512 * 1024
        const val MAX_NAME_CHARS = 100
        const val DEFAULT_STEM = "smylte-export"

        /// The one file the page saves is a theme (R2). A type added here gets
        /// its extension here.
        val EXTENSIONS: Map<String, String> = mapOf("application/json" to ".json")

        private const val RESERVED = "/\\:*?\"<>|"

        /// Null unless the type is allowed (an exact match) and the text and
        /// name are present and within bounds. The size is checked first, so an
        /// oversized payload costs nothing else.
        fun of(name: String?, mime: String?, text: String?): SaveRequest? {
            if (text == null || text.length > MAX_TEXT_CHARS) return null
            val ext = EXTENSIONS[mime] ?: return null
            if (name == null) return null
            return SaveRequest(fileName(name, ext), mime!!, text)
        }

        /// A name that is one plain file name ending in `ext`, whatever the
        /// page sent. Control characters and format characters (Cf: bidi
        /// overrides, zero-width marks) are dropped with the characters a file
        /// name may not hold, so a name cannot be made to display a false
        /// extension. The extension always matches the type.
        private fun fileName(name: String, ext: String): String {
            val kept = name.filterNot {
                it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() || it in RESERVED
            }
            var stem = kept.trim()
            // Before the leading dots go: a name that is only the extension
            // is empty, not "json".
            if (stem.endsWith(ext, ignoreCase = true)) stem = stem.dropLast(ext.length)
            stem = stem.trim().trimStart('.').trim()
            stem = stem.trimEnd { it.isWhitespace() || it == '.' }
            val room = MAX_NAME_CHARS - ext.length
            if (stem.length > room) {
                var cut = room
                // Never end on half of a surrogate pair.
                if (stem[cut - 1].isHighSurrogate()) cut -= 1
                stem = stem.take(cut).trimEnd { it.isWhitespace() || it == '.' }
            }
            if (stem.isEmpty()) stem = DEFAULT_STEM
            return stem + ext
        }
    }
}

/// Whether a haptic may play. A haptic always answers a touch: the page asks
/// for one on a tap that completes or toggles, and when the app reports a
/// failure. The gate is open while a finger is on the page and for
/// HAPTIC_WINDOW_MS after the last touch event, at most HAPTICS_PER_TOUCH times
/// in one touch. Any script can ask, so these bounds are what a hostile one
/// gets. TalkBack, Switch Access and a keyboard produce no touch, so they get
/// none; TalkBack gives its own.
///
/// It is not thread-safe: MainActivity calls it on the main thread only.
class HapticGate {
    private var touching = false
    private var lastTouch: Long? = null
    private var playedThisTouch = 0

    /// Every MotionEvent the page receives, by masked action. A first finger
    /// down starts a new touch, with its own allowance.
    fun onTouch(actionMasked: Int, now: Long) {
        if (actionMasked == HostProtocol.ACTION_DOWN) playedThisTouch = 0
        touching = HostProtocol.touching(actionMasked, touching)
        lastTouch = now
    }

    /// The window left the front. A touch cut off as it went may never send
    /// its UP here, and what was touched before is no reason to buzz on return.
    fun reset() {
        touching = false
        lastTouch = null
    }

    /// True when a haptic may play now; it then counts. A refusal costs
    /// nothing. Elapsed time is compared, so a clock that went backwards is refused.
    fun allow(now: Long, resumed: Boolean, pageIsOurs: Boolean): Boolean {
        val touched = lastTouch
        val recent = touching || (touched != null && now - touched in 0L..HostProtocol.HAPTIC_WINDOW_MS)
        if (!resumed || !pageIsOurs || !recent || playedThisTouch >= HostProtocol.HAPTICS_PER_TOUCH) return false
        playedThisTouch += 1
        return true
    }
}
