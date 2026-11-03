package com.nicholaskmitchell.smylte

/// When Smylte asks for the phone's biometrics or screen lock (the app lock,
/// turned on in Server settings: Settings.appLock). It locks when the process
/// starts, and when the app comes back AWAY_MS or more after the last of its
/// windows stopped. A window rebuilt by a configuration change, or a short
/// trip to a picker or a system screen, is back long before that, so neither
/// locks.
///
/// One instance, `shared`, holds the state for the whole process: the two
/// windows agree, and a rebuilt window finds the lock as its predecessor left
/// it. LockScreen does what this decides.
///
/// Kept free of Android classes, so the JVM tests cover every decision. It is
/// not thread-safe: the windows' lifecycle and the prompt's answers all run on
/// the main thread.
class AppLock {
    /// Nobody has unlocked this process yet, so a process start locks.
    private var locked = true
    /// How many of the app's windows are started (visible).
    private var visible = 0
    /// When the last visible window stopped, on SystemClock.elapsedRealtime;
    /// null while one is visible, and before any has stopped.
    private var leftAt: Long? = null
    /// The prompt has opened by itself during this visit.
    private var prompted = false

    /// A window started, at `now` on SystemClock.elapsedRealtime, which counts
    /// deep sleep, so a phone left asleep is away. The first window to start
    /// when none was visible begins a visit, and locks again if the app was
    /// away AWAY_MS or more.
    fun started(now: Long) {
        if (visible == 0) {
            val left = leftAt
            if (left != null && relocks(now - left)) locked = true
            leftAt = null
            prompted = false
        }
        visible += 1
    }

    /// A window stopped. When it was the last visible one, the time away
    /// starts. A stop without a start (never expected) leaves the count at
    /// zero rather than below it, which would stop every later return from
    /// counting as one.
    fun stopped(now: Long) {
        if (visible > 0) visible -= 1
        if (visible == 0) leftAt = now
    }

    /// Whether the windows hide their content now. `on`: the lock is turned on
    /// and the phone has a screen lock. When it is not, the app is unlocked
    /// until the next reason to lock. Turned off, there is nothing to ask;
    /// with no screen lock, nothing could answer, and whoever holds the phone
    /// can open the app anyway. So turning the lock on, or setting a screen
    /// lock again, locks nothing until the next start or return.
    fun locked(on: Boolean): Boolean {
        if (!on) locked = false
        return locked
    }

    /// The prompt succeeded. Nothing else unlocks: a cancel, a lockout or a
    /// missing sensor leaves the app locked (AppLockTest checks the only caller).
    fun authenticated() {
        locked = false
    }

    /// Whether a window that is locked when it resumes opens the prompt by
    /// itself. Once a visit: after a cancel, or on moving between the app's own
    /// windows, the lock view's Unlock asks instead, so a cancelled prompt does
    /// not come straight back.
    fun promptsByItself(on: Boolean): Boolean {
        if (!locked(on) || prompted) return false
        prompted = true
        return true
    }

    /// How a window stays out of Recents' previews while the lock is on.
    enum class RecentsGuard {
        /// The lock is off: Recents shows the window as usual.
        NONE,
        /// Activity.setRecentsScreenshotEnabled(false), Android 13 and later.
        NO_SCREENSHOT,
        /// FLAG_SECURE, the only way on Android 11 and 12. It also blocks
        /// screenshots; README.md says why that is accepted.
        SECURE,
    }

    companion object {
        /// The time away after which the app locks again. The setting's note
        /// and README.md say it in words (AppLockTest).
        const val AWAY_MS = 5 * 60 * 1000L

        /// Android 13, which added Activity.setRecentsScreenshotEnabled.
        const val SDK_RECENTS_SCREENSHOT = 33

        // BiometricPrompt's error codes, restated because this class takes no
        // Android classes. AppLockTest holds them to the platform's.
        const val ERROR_CANCELED = 5
        const val ERROR_USER_CANCELED = 10

        /// The process's one lock.
        val shared = AppLock()

        /// Whether a return after `awayMs` locks again. A time below zero (a
        /// clock that went backwards, which elapsedRealtime never does) locks
        /// too: a lock in doubt stays locked.
        fun relocks(awayMs: Long): Boolean = awayMs < 0 || awayMs >= AWAY_MS

        /// Recents' preview is taken when a window leaves, before anyone knows
        /// whether the app will be locked when it is next seen, so it is kept
        /// blank for as long as the lock is on, not only while it is locked.
        fun recentsGuard(sdk: Int, on: Boolean): RecentsGuard = when {
            !on -> RecentsGuard.NONE
            sdk >= SDK_RECENTS_SCREENSHOT -> RecentsGuard.NO_SCREENSHOT
            else -> RecentsGuard.SECURE
        }

        /// Whether the window carries FLAG_SECURE. Besides the Recents guard,
        /// whenever it is locked, on every Android version: the digital
        /// assistant's "use text from screen" is handed the whole view tree,
        /// hidden views included, unless the window is secure, and a hidden
        /// page's text must not reach it before the unlock. A secure window is
        /// the one thing it skips; the lock view loses nothing by it.
        fun secureWindow(sdk: Int, on: Boolean, locked: Boolean): Boolean =
            locked || recentsGuard(sdk, on) == RecentsGuard.SECURE

        /// Whether the lock view shows the system's words for a prompt error.
        /// Not for a cancel: the user did it, or it came with the window leaving.
        fun showsError(code: Int): Boolean = code != ERROR_CANCELED && code != ERROR_USER_CANCELED
    }
}
