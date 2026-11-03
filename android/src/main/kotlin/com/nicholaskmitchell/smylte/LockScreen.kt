package com.nicholaskmitchell.smylte

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.ViewTreeObserver
import android.view.accessibility.AccessibilityEvent
import android.widget.Button
import android.widget.TextView

/// The app lock (AppLock) in one window. While the app is locked, the window's
/// content is hidden and the lock view stands in its place, asking through
/// Android's own prompt for a biometric or the phone's screen lock. While the
/// lock is on, Recents keeps no preview of the window.
///
/// Both activities hold one and report every onStart, onResume, onStop and
/// onDestroy to it (AppLockTest checks that they do), because the time away is
/// counted from the last of the app's windows to stop. Main thread only.
class LockScreen(
    private val activity: Activity,
    private val settings: Settings,
    /// Everything the window shows except the lock view, hidden as one, so
    /// nothing the window does behind the lock (a page that finishes loading,
    /// the update strip) can show through.
    private val content: ViewGroup,
    /// The lock view (layout/lock.xml).
    private val cover: View,
    /// Called on the main thread whenever the window locks or unlocks, after
    /// its views have changed.
    private val onChange: (locked: Boolean) -> Unit,
) {
    private val title: TextView = cover.findViewById(R.id.lock_title)
    private val status: TextView = cover.findViewById(R.id.lock_status)
    private val main = Handler(Looper.getMainLooper())
    private val contentAccessibility = content.importantForAccessibility
    /// The prompt on screen, so it is never opened twice and goes with the window.
    private var prompt: CancellationSignal? = null
    /// What setRecentsScreenshotEnabled was last given by this window; null
    /// until the first sync sets it. Not assumed to be the platform's starting
    /// true: the platform keeps the last value for the activity across a
    /// rebuilt window and the process's death.
    private var screenshots: Boolean? = null
    /// Between onStart and onStop.
    private var started = false
    /// This window has drawn since its last onStart (AppLock.shown).
    private var drawn = false
    /// The first frame after each start tells AppLock that the visit is real.
    /// A window Android starts and stops in the background never draws. Runs
    /// before every frame, so it reads a flag and nothing more.
    private val onDraw = ViewTreeObserver.OnDrawListener {
        if (started && !drawn) {
            drawn = true
            AppLock.shared.shown()
        }
    }

    /// Whether the window is showing the lock view.
    var locked = false
        private set

    init {
        // A page sends its own accessibility events (a live region's toast,
        // say) up through its parents, and hiding the views may not stop
        // them, so while locked the container drops them and TalkBack hears
        // nothing from behind the lock.
        content.accessibilityDelegate = object : View.AccessibilityDelegate() {
            override fun onRequestSendAccessibilityEvent(host: ViewGroup, child: View, event: AccessibilityEvent): Boolean =
                !locked && super.onRequestSendAccessibilityEvent(host, child, event)
        }
        // Asks first whether the lock still applies: a phone whose screen lock
        // has been removed has nothing to ask for.
        cover.findViewById<Button>(R.id.lock_unlock).setOnClickListener {
            sync()
            if (locked) ask()
        }
        activity.window.decorView.viewTreeObserver.addOnDrawListener(onDraw)
    }

    fun onStart() {
        AppLock.shared.started(SystemClock.elapsedRealtime())
        started = true
        drawn = false
        sync()
    }

    /// The prompt opens by itself once a visit (AppLock.promptsByItself),
    /// posted so that it opens over a window that has finished resuming, and
    /// only if the window is still started by then: Android can start, resume
    /// and stop a window in the background in one go.
    fun onResume() {
        sync()
        if (AppLock.shared.promptsByItself(isOn())) {
            main.post { if (!activity.isDestroyed && started && locked) ask() }
        }
    }

    /// The prompt goes with the window: Android may refuse it to an app that is
    /// not in front, and its answer would come to nobody.
    fun onStop() {
        started = false
        cancelPrompt()
        AppLock.shared.stopped(SystemClock.elapsedRealtime())
    }

    /// Also takes the draw listener off the window's decor, which a rebuilt
    /// window can keep (preserveWindow), so no destroyed activity is held. Read
    /// from the decor again: the observer it had before it was attached was
    /// merged into the window's then.
    fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        cancelPrompt()
        activity.window.decorView.viewTreeObserver.let { if (it.isAlive) it.removeOnDrawListener(onDraw) }
    }

    /// The lock view's text in a colour that reads on the window's background,
    /// which in MainActivity is the page's (applyThemeColour).
    fun textColour(colour: Int) {
        title.setTextColor(colour)
        status.setTextColor(colour)
    }

    /// Makes the window match the lock: hidden behind the lock view while
    /// locked, and out of Recents' previews while the lock is on. Cheap, so it
    /// runs at every start and resume, on Unlock, and when the switch changes.
    fun sync() {
        val on = isOn()
        val now = AppLock.shared.locked(on)
        guardWindow(on, now)
        if (now == locked) return
        locked = now
        // INVISIBLE rather than GONE, so the page keeps its size and is not
        // laid out again. Views inside an invisible one are neither drawn,
        // touched nor focused, and NO_HIDE_DESCENDANTS keeps them, the page's
        // own nodes included, out of what TalkBack reads.
        content.visibility = if (now) View.INVISIBLE else View.VISIBLE
        content.importantForAccessibility =
            if (now) View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS else contentAccessibility
        cover.visibility = if (now) View.VISIBLE else View.GONE
        if (now) {
            status.text = null
            // A keyboard left up for a field behind the lock has nothing to type into.
            activity.window.insetsController?.hide(WindowInsets.Type.ime())
        } else {
            cancelPrompt()
        }
        onChange(now)
    }

    /// Whether the lock is on: turned on, and the phone has a screen lock.
    fun isOn(): Boolean = settings.appLock && deviceSecure(activity)

    /// AppLock.recentsGuard and AppLock.secureWindow decide how; each is changed
    /// only when it differs, since every change is a call to the window manager.
    /// FLAG_SECURE also keeps the digital assistant from reading the hidden
    /// page's text while the window is locked, which hiding the views does not.
    private fun guardWindow(on: Boolean, locked: Boolean) {
        val guard = AppLock.recentsGuard(Build.VERSION.SDK_INT, on)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val enabled = guard != AppLock.RecentsGuard.NO_SCREENSHOT
            if (enabled != screenshots) {
                activity.setRecentsScreenshotEnabled(enabled)
                screenshots = enabled
            }
        }
        val secure = AppLock.secureWindow(Build.VERSION.SDK_INT, on, locked)
        val window = activity.window
        val isSecure = (window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE) != 0
        if (secure != isSecure) {
            if (secure) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
    }

    /// Android's own prompt: a biometric of the strongest class, or the phone's
    /// screen lock. Allowing the screen lock lets every phone that offers the
    /// lock unlock, sensor or not, and is also why the prompt has no cancel
    /// button of its own: the platform refuses one alongside it. Back cancels
    /// it. Only a success unlocks (Answer).
    private fun ask() {
        if (prompt != null) return
        val signal = CancellationSignal()
        prompt = signal
        try {
            BiometricPrompt.Builder(activity)
                .setTitle(activity.getString(R.string.lock_prompt_title))
                .setAllowedAuthenticators(
                    BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL,
                )
                // A recognised face is enough, with no extra tap, as on the
                // phone's own lock screen.
                .setConfirmationRequired(false)
                .build()
                .authenticate(signal, activity.mainExecutor, Answer(signal))
        } catch (_: RuntimeException) {
            // A phone that cannot build or show the prompt leaves the window
            // locked: never crashed and never open. Unlock tries again.
            prompt = null
            status.setText(R.string.lock_prompt_unavailable)
        }
    }

    private fun cancelPrompt() {
        prompt?.cancel()
        prompt = null
    }

    /// What the prompt answers. Only a success unlocks: a cancel, a timeout, a
    /// lockout or a missing sensor leaves the window locked, with Unlock to
    /// try again. A finger or face that is not recognised is the prompt's own
    /// business (onAuthenticationFailed): it says so and stays open.
    private inner class Answer(private val signal: CancellationSignal) : BiometricPrompt.AuthenticationCallback() {
        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) {
            settle()
            AppLock.shared.authenticated()
            if (!activity.isDestroyed) sync()
        }

        /// The system's own words, except for a cancel (AppLock.showsError).
        override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
            settle()
            if (!activity.isDestroyed) status.text = if (AppLock.showsError(errorCode)) errString else null
        }

        private fun settle() {
            if (prompt === signal) prompt = null
        }
    }

    companion object {
        /// Whether the phone has a screen lock (a PIN, pattern or password).
        /// Without one there is nothing to unlock with, so the lock is neither
        /// offered nor applied. No KeyguardManager counts as none.
        fun deviceSecure(context: Context): Boolean =
            context.getSystemService(KeyguardManager::class.java)?.isDeviceSecure == true
    }
}
