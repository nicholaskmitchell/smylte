package com.nicholaskmitchell.smylte

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

    /// The capabilities a page announces in hello. The host acts on a token
    /// only by asking for it by name, so unknown tokens are simply never
    /// consulted. Input over MAX_CAPS_CHARS is ignored whole, and a token
    /// outside [a-z0-9]{1,16} is dropped; there is no trimming.
    fun parseCaps(raw: String?): Set<String> {
        if (raw == null || raw.length > MAX_CAPS_CHARS) return emptySet()
        return raw.split(',').take(MAX_CAPS).filter { CAP.matches(it) }.toSet()
    }

    /// What hello answers. It takes only a boolean, so nothing the page sends
    /// can reach the JSON.
    fun envJson(clock24: Boolean): String = """{"v":$ENV_VERSION,"clock24":$clock24}"""

    fun envEvent(env: String): String = """{"type":"env","env":$env}"""

    fun savedEvent(outcome: SaveOutcome): String = """{"type":"saved","outcome":"${outcome.wire}"}"""

    /// The script that delivers one event to the page. The detail is always
    /// built by this object from host values, never from a string the page
    /// sent. evaluateJavascript is not subject to the page's CSP, and this
    /// script fetches nothing.
    fun eventScript(detail: String): String =
        "window.dispatchEvent(new CustomEvent('$EVENT',{detail:$detail}));"

    /// May a save dialog open now? The window must be in front with the app's
    /// own page loaded, and the last dialog must have closed long enough ago.
    /// The comparison is on `now - lastPickerClosed`, so a negative elapsed
    /// time (a clock that went backwards) is refused.
    fun allowSave(resumed: Boolean, mainFrameOurs: Boolean, now: Long, lastPickerClosed: Long?): Boolean =
        resumed && mainFrameOurs && (lastPickerClosed == null || now - lastPickerClosed >= SAVE_BACKOFF_MS)

    /// Where a save's result is shown. The page that asked hears it; if that
    /// document has gone, or a restored activity has no page yet, a native
    /// toast says it instead.
    fun saveReport(restored: Boolean, askedBy: Int, current: Int, alive: Boolean): SaveReport =
        if (!restored && alive && askedBy == current) SaveReport.PAGE else SaveReport.TOAST

    /// Whether a finger is down after this event. A list of the actions that
    /// set it rather than a range: DOWN..MOVE would include UP (1). POINTER_UP
    /// leaves the state as it was, because another finger is still down.
    fun touching(actionMasked: Int, was: Boolean): Boolean = when (actionMasked) {
        ACTION_DOWN, ACTION_POINTER_DOWN, ACTION_MOVE -> true
        ACTION_UP, ACTION_CANCEL -> false
        else -> was
    }
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
