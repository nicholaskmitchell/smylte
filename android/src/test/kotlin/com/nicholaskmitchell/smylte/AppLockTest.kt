package com.nicholaskmitchell.smylte

import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class AppLockTest {
    private val sources = "src/main/kotlin/com/nicholaskmitchell/smylte"
    private val away = AppLock.AWAY_MS

    /// A lock whose prompt has succeeded, with one window visible since `at`.
    private fun unlocked(at: Long = 0) = AppLock().apply {
        started(at)
        authenticated()
    }

    private fun AppLock.isLocked() = locked(on = true)

    private fun source(name: String) = File("$sources/$name").readText()

    private fun mainSources() = File(sources).listFiles { f -> f.extension == "kt" }!!.sortedBy { it.name }

    /// A source with every run of whitespace made one space, so a pin survives rewrapping.
    private fun flat(name: String) = source(name).replace(Regex("\\s+"), " ")

    /// `code` from `start` up to `end`, both found after `start`'s position.
    private fun between(code: String, start: String, end: String): String {
        val from = code.indexOf(start)
        assertTrue(start, from >= 0)
        val to = code.indexOf(end, from + start.length)
        assertTrue(end, to >= 0)
        return code.substring(from, to)
    }

    /// The arguments of every call to `fn` in `code`, each up to its closing parenthesis.
    private fun callArgs(code: String, fn: String): List<String> =
        Regex(Regex.escape("$fn(")).findAll(code).map { m ->
            var depth = 1
            var i = m.range.last + 1
            while (depth > 0) {
                when (code[i]) {
                    '(' -> depth += 1
                    ')' -> depth -= 1
                }
                i += 1
            }
            code.substring(m.range.last + 1, i - 1).trim().trimEnd(',').trim()
        }.toList()

    // ── constants and the state machine ─────────────────────────────────────

    @Test

    fun constants_are_the_platforms() {
        assertEquals(300_000L, AppLock.AWAY_MS)
        assertEquals(Build.VERSION_CODES.TIRAMISU, AppLock.SDK_RECENTS_SCREENSHOT)
        assertEquals(BiometricPrompt.BIOMETRIC_ERROR_CANCELED, AppLock.ERROR_CANCELED)
        assertEquals(BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED, AppLock.ERROR_USER_CANCELED)
    }

    @Test

    fun a_process_start_locks() {
        val lock = AppLock()
        lock.started(1_000)
        assertTrue(lock.isLocked())
        val first = AppLock()
        first.started(0)
        assertTrue(first.isLocked())
    }

    @Test

    fun under_five_minutes_away_stays_unlocked() {
        val lock = unlocked()
        lock.stopped(10_000)
        lock.started(10_000 + away - 1)
        assertFalse(lock.isLocked())
    }

    @Test

    fun five_minutes_or_more_away_locks_again() {
        val lock = unlocked()
        lock.stopped(10_000)
        lock.started(10_000 + away)
        assertTrue(lock.isLocked())

        val asleep = unlocked()
        asleep.stopped(10_000)
        asleep.started(10_000 + 6 * 60 * 60 * 1000L)
        assertTrue(asleep.isLocked())
        // Only the prompt unlocks, so a quick return does not.
        asleep.stopped(30_000_000)
        asleep.started(30_000_001)
        assertTrue(asleep.isLocked())
    }

    @Test

    fun a_rebuilt_window_does_not_lock() {
        val lock = unlocked()
        lock.stopped(50_000)
        lock.started(50_020)
        assertFalse(lock.isLocked())

        val never = AppLock()
        never.started(0)
        never.stopped(50_000)
        never.started(50_020)
        assertTrue(never.isLocked())
    }

    @Test

    fun the_time_away_counts_from_the_last_window_to_stop() {
        val lock = unlocked()
        // The settings open over the app, which is covered and stops.
        lock.started(1_000)
        lock.stopped(2_000)
        // The app has been away for longer than the limit, but the settings
        // have not, so the clock starts only when they leave.
        lock.stopped(2_000 + 3 * away)
        lock.started(2_000 + 3 * away + away - 1)
        assertFalse(lock.isLocked())
    }

    @Test

    fun a_short_trip_to_a_picker_does_not_lock_and_a_long_one_does() {
        val lock = unlocked()
        val t = 10_000L
        lock.stopped(t)
        lock.started(t + 60_000)
        assertFalse(lock.isLocked())
        val t2 = t + 61_000
        lock.stopped(t2)
        lock.started(t2 + away)
        assertTrue(lock.isLocked())
    }

    @Test

    fun relocks_at_five_minutes_and_on_a_clock_that_went_backwards() {
        assertFalse(AppLock.relocks(0))
        assertFalse(AppLock.relocks(away - 1))
        assertTrue(AppLock.relocks(away))
        assertTrue(AppLock.relocks(Long.MAX_VALUE))
        assertTrue(AppLock.relocks(-1))
        assertTrue(AppLock.relocks(Long.MIN_VALUE))

        val lock = unlocked()
        lock.stopped(10_000)
        lock.started(9_999)
        assertTrue(lock.isLocked())
    }

    @Test

    fun a_stray_stop_does_not_break_the_count() {
        val lock = unlocked()
        lock.stopped(10)
        lock.stopped(20)
        lock.started(30)
        assertFalse(lock.isLocked())
        // A count left at -1 would never lock again.
        lock.stopped(40)
        lock.started(40 + away)
        assertTrue(lock.isLocked())
    }

    // ── when the lock is off or the phone has no screen lock ────────────────

    @Test

    fun a_lock_that_is_off_never_locks() {
        val lock = AppLock()
        lock.started(0)
        assertFalse(lock.locked(on = false))
        lock.stopped(1_000)
        lock.started(1_000 + 10 * away)
        assertFalse(lock.locked(on = false))
        assertFalse(lock.promptsByItself(on = false))
    }

    @Test

    fun turning_the_lock_on_locks_nothing_until_the_next_start_or_return() {
        val lock = AppLock()
        lock.started(0)
        assertFalse(lock.locked(on = false))
        assertFalse(lock.locked(on = true))
        lock.stopped(1_000)
        lock.started(1_000 + away - 1)
        assertFalse(lock.locked(on = true))
        lock.stopped(2_000_000)
        lock.started(2_000_000 + away)
        assertTrue(lock.locked(on = true))
    }

    @Test

    fun a_phone_without_a_screen_lock_is_never_locked() {
        // The lock is on in Settings, but with no screen lock there is nothing to
        // unlock with, so the caller says it is not on.
        val lock = AppLock()
        lock.started(0)
        assertFalse(lock.locked(on = false))
        lock.stopped(1_000)
        lock.started(1_000 + away)
        assertFalse(lock.locked(on = false))
    }

    @Test

    fun removing_the_screen_lock_unlocks_until_the_next_start_or_return() {
        val lock = AppLock()
        lock.started(0)
        assertTrue(lock.locked(on = true))
        lock.stopped(1_000)
        lock.started(61_000)
        assertFalse(lock.locked(on = false))
        // The screen lock is back, and the app stays open until the next return.
        lock.stopped(62_000)
        lock.started(122_000)
        assertFalse(lock.locked(on = true))
        lock.stopped(123_000)
        lock.started(123_000 + away)
        assertTrue(lock.locked(on = true))
    }

    // ── the prompt and Recents ──────────────────────────────────────────────

    @Test

    fun the_prompt_opens_by_itself_once_a_visit() {
        val lock = AppLock()
        lock.started(0)
        assertTrue(lock.promptsByItself(on = true))
        assertFalse(lock.promptsByItself(on = true))
        // A second window in the same visit.
        lock.started(1)
        assertFalse(lock.promptsByItself(on = true))
        // A new visit, and the app is still locked.
        lock.stopped(2)
        lock.stopped(3)
        lock.started(4)
        assertTrue(lock.promptsByItself(on = true))
        lock.authenticated()
        lock.stopped(5)
        lock.started(6)
        assertFalse(lock.promptsByItself(on = true))
    }

    @Test

    fun cancels_show_no_message_and_other_errors_do() {
        assertFalse(AppLock.showsError(5))
        assertFalse(AppLock.showsError(10))
        listOf(
            BiometricPrompt.BIOMETRIC_ERROR_HW_UNAVAILABLE,
            BiometricPrompt.BIOMETRIC_ERROR_TIMEOUT,
            BiometricPrompt.BIOMETRIC_ERROR_LOCKOUT,
            BiometricPrompt.BIOMETRIC_ERROR_LOCKOUT_PERMANENT,
            BiometricPrompt.BIOMETRIC_ERROR_HW_NOT_PRESENT,
            BiometricPrompt.BIOMETRIC_ERROR_NO_DEVICE_CREDENTIAL,
        ).forEach { assertTrue("error $it", AppLock.showsError(it)) }
    }

    @Test

    fun recents_stays_blank_while_the_lock_is_on() {
        assertEquals(AppLock.RecentsGuard.NO_SCREENSHOT, AppLock.recentsGuard(33, true))
        assertEquals(AppLock.RecentsGuard.NO_SCREENSHOT, AppLock.recentsGuard(36, true))
        assertEquals(AppLock.RecentsGuard.SECURE, AppLock.recentsGuard(30, true))
        assertEquals(AppLock.RecentsGuard.SECURE, AppLock.recentsGuard(32, true))
        assertEquals(AppLock.RecentsGuard.NONE, AppLock.recentsGuard(30, false))
        assertEquals(AppLock.RecentsGuard.NONE, AppLock.recentsGuard(36, false))
    }

    @Test

    fun a_locked_window_is_secure_on_every_android_version() {
        // The assistant's "use text from screen" reads hidden views too, and
        // only a secure window is skipped, so locked means secure everywhere.
        listOf(30, 32, 33, 36).forEach { assertTrue("sdk $it", AppLock.secureWindow(it, on = true, locked = true)) }
        // A lock view can stand while the lock is not on (the screen lock was
        // removed this instant): still secure until the window unlocks.
        assertTrue(AppLock.secureWindow(36, on = false, locked = true))
    }

    @Test

    fun an_unlocked_window_is_secure_only_where_recents_needs_it() {
        assertTrue(AppLock.secureWindow(30, on = true, locked = false))
        assertTrue(AppLock.secureWindow(32, on = true, locked = false))
        assertFalse(AppLock.secureWindow(33, on = true, locked = false))
        assertFalse(AppLock.secureWindow(36, on = true, locked = false))
        assertFalse(AppLock.secureWindow(30, on = false, locked = false))
        assertFalse(AppLock.secureWindow(36, on = false, locked = false))
    }

    @Test

    fun the_window_is_secured_with_the_new_lock_state() {
        // sync() must pass the state it has just read, not the window's old
        // one, or the first frame of a locked start would not be secure.
        val source = File("$sources/LockScreen.kt").readText()
        val sync = source.substringAfter("fun sync()").substringBefore("private fun isOn()")
        val lockedAt = sync.indexOf("val now = AppLock.shared.locked(on)")
        val guardAt = sync.indexOf("guardWindow(on, now)")
        assertTrue(lockedAt >= 0)
        assertTrue(guardAt > lockedAt)
        assertTrue(guardAt < sync.indexOf("if (now == locked) return"))
        assertTrue(source.contains("AppLock.secureWindow(Build.VERSION.SDK_INT, on, locked)"))
    }

    // ── source scans ────────────────────────────────────────────────────────

    @Test

    fun only_the_prompts_success_unlocks() {
        val call = ".authenticated()"
        val callers = mainSources().filter { it.name != "AppLock.kt" && it.readText().contains(call) }
        assertEquals(listOf("LockScreen.kt"), callers.map { it.name })
        val code = source("LockScreen.kt")
        assertEquals(1, code.windowed(call.length).count { it == call })
        val s = code.indexOf("override fun onAuthenticationSucceeded")
        val c = code.indexOf(call)
        assertTrue(s in 0 until c)
        val next = code.indexOf("override fun", s + 1)
        assertTrue(next == -1 || next > c)
        assertTrue(code.contains("override fun onAuthenticationError"))
    }

    @Test

    fun the_prompt_allows_the_screen_lock_and_has_no_cancel_button() {
        val code = source("LockScreen.kt").replace(Regex("\\s+"), " ")
        assertTrue(
            code.contains(
                "BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL",
            ),
        )
        assertFalse(code.contains("setNegativeButton"))
        assertFalse(code.contains("setDeviceCredentialAllowed"))
        val manifest = File("src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android.permission.USE_BIOMETRIC"))
        assertFalse(manifest.contains("USE_FINGERPRINT"))
        mainSources().forEach { assertFalse(it.name, it.readText().contains("import androidx.")) }
    }

    @Test

    fun both_windows_report_their_lifecycle() {
        for (name in listOf("MainActivity.kt", "SetupActivity.kt")) {
            val code = source(name)
            assertEquals(name, 1, code.windowed("LockScreen(".length).count { it == "LockScreen(" })
            for (call in listOf("lock.onStart()", "lock.onResume()", "lock.onStop()", "lock.onDestroy()")) {
                assertEquals("$name $call", 1, code.windowed(call.length).count { it == call })
            }
        }
    }

    @Test

    fun the_time_away_counts_sleep() {
        val code = source("LockScreen.kt")
        val clock = "SystemClock.elapsedRealtime()"
        assertEquals(2, code.windowed(clock.length).count { it == clock })
        assertFalse(code.contains("uptimeMillis"))
        assertFalse(code.contains("currentTimeMillis"))
    }

    @Test

    fun the_page_is_shown_only_where_the_lock_is_asked() {
        val code = source("MainActivity.kt")
        val sets = Regex("""web\.visibility\s*=""").findAll(code).toList()
        assertEquals(1, sets.size)
        val fn = code.indexOf("private fun showPage()")
        assertTrue(fn >= 0)
        val next = code.indexOf("private fun", fn + 1)
        assertTrue(sets[0].range.first in fn until next)
    }

    // ── the wiring that carries the lock (each was a mutation no test caught) ──

    @Test

    fun the_window_is_made_secure_and_cleared_as_the_rule_says() {
        assertTrue(
            flat("LockScreen.kt").contains(
                "if (secure != isSecure) { " +
                    "if (secure) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE) " +
                    "else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }",
            ),
        )
    }

    @Test

    fun the_lock_is_on_only_with_the_setting_and_a_screen_lock() {
        assertTrue(flat("LockScreen.kt").contains("private fun isOn(): Boolean = settings.appLock && deviceSecure(activity)"))
    }

    @Test

    fun the_setting_starts_off_and_saving_the_server_keeps_it() {
        val code = flat("Settings.kt")
        assertTrue(code.contains("get() = prefs.getBoolean(APP_LOCK, false)"))
        assertTrue(code.contains("set(v) = prefs.edit().putBoolean(APP_LOCK, v).apply()"))
        val save = between(source("Settings.kt"), "fun save(", "\n    }\n")
        assertFalse(save.contains("APP_LOCK"))
        assertFalse(save.contains("appLock"))
        assertFalse(save.contains(".clear()"))
        // Read and written in one place each, and named once.
        assertEquals(3, Regex("""\bAPP_LOCK\b""").findAll(source("Settings.kt")).count())
        // Only the switch turns it on or off.
        val writers = mainSources().filter { it.name != "Settings.kt" && it.readText().contains("settings.appLock =") }
        assertEquals(listOf("SetupActivity.kt"), writers.map { it.name })
    }

    @Test

    fun while_locked_the_content_is_hidden_from_sight_and_talkback() {
        val sync = between(flat("LockScreen.kt"), "fun sync()", "private fun isOn()")
        val changed = sync.indexOf("locked = now")
        for (line in listOf(
            "content.visibility = if (now) View.INVISIBLE else View.VISIBLE",
            "content.importantForAccessibility = if (now) View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS " +
                "else contentAccessibility",
            "cover.visibility = if (now) View.VISIBLE else View.GONE",
        )) {
            assertTrue(line, sync.indexOf(line) > changed)
        }
        assertTrue(changed > sync.indexOf("if (now == locked) return"))
        // The page's own events stop at the container while locked.
        assertTrue(flat("LockScreen.kt").contains("!locked && super.onRequestSendAccessibilityEvent(host, child, event)"))
    }

    @Test

    fun the_page_itself_is_hidden_while_locked() {
        val show = between(flat("MainActivity.kt"), "private fun showPage()", "private fun ")
        assertTrue(show.contains("val locked = lock.locked"))
        assertTrue(show.contains("web.visibility = if (pageShown && !locked) View.VISIBLE else View.INVISIBLE"))
        assertTrue(
            show.contains(
                "web.importantForAccessibility = if (locked) View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS " +
                    "else webAccessibility",
            ),
        )
    }

    @Test

    fun every_rule_the_lock_changes_is_told_whether_it_is_locked() {
        val code = flat("MainActivity.kt")
        val expected = mapOf(
            "HostProtocol.allowSave" to 1,
            "HostProtocol.backAction" to 1,
            "HostProtocol.wantsBackCallback" to 1,
            "HostProtocol.holdsResult" to 2,
        )
        for ((fn, count) in expected) {
            val calls = callArgs(code, fn)
            assertEquals(fn, count, calls.size)
            calls.forEach { assertTrue("$fn($it)", it.endsWith("lock.locked")) }
        }
        callArgs(code, "HostProtocol.holdsResult").forEach { assertEquals("started, lock.locked", it) }
    }

    @Test

    fun a_pickers_answer_waits_until_the_window_has_started_and_is_unlocked() {
        val code = flat("MainActivity.kt")
        val result = between(code, "override fun onActivityResult(", "private fun deliverResult(")
        val hold = result.indexOf(
            "if (HostProtocol.holdsResult(started, lock.locked)) { heldResults += HeldResult(requestCode, resultCode, data) return }",
        )
        assertTrue(hold >= 0)
        assertTrue(result.indexOf("deliverResult(requestCode, resultCode, data)") > hold)
        val run = between(code, "private fun runHeld()", "private fun ")
        assertTrue(run.startsWith("private fun runHeld() { if (HostProtocol.holdsResult(started, lock.locked)) return "))
        // Delivered from those two places only.
        assertEquals(3, callArgs(code, "deliverResult").size)
        // `started` follows the lock's own start and stop.
        assertTrue(code.contains("lock.onStart() started = true"))
        assertTrue(between(code, "override fun onStop()", "override fun onDestroy()").contains("started = false"))
        assertEquals(1, code.windowed("started = true".length).count { it == "started = true" })
        // Its declaration and onStop.
        assertEquals(2, code.windowed("started = false".length).count { it == "started = false" })
    }

    @Test

    fun back_while_locked_moves_the_settings_to_the_back_too() {
        val code = flat("SetupActivity.kt")
        assertTrue(code.contains("findViewById(R.id.lock), ::syncBack)"))
        val sync = between(code, "private fun syncBack(locked: Boolean)", "override fun onBackPressed()")
        assertTrue(sync.contains("if (locked && registered == null) { val callback = OnBackInvokedCallback { moveTaskToBack(true) }"))
        assertTrue(sync.contains("} else if (!locked && registered != null) {"))
        assertTrue(code.contains("if (lock.locked) moveTaskToBack(true) else @Suppress(\"DEPRECATION\") super.onBackPressed()"))
    }

    @Test

    fun the_pages_own_dialogs_are_refused_while_locked() {
        val chrome = between(flat("MainActivity.kt"), "private inner class Chrome", "override fun onActivityResult(")
        for (fn in listOf("onJsAlert", "onJsConfirm", "onJsPrompt", "onJsBeforeUnload")) {
            assertTrue(fn, Regex("""= refusedWhileLocked\(result\) \|\| super\.$fn\(""").containsMatchIn(chrome))
        }
        assertTrue(
            chrome.contains("private fun refusedWhileLocked(result: JsResult): Boolean { if (!lock.locked) return false result.cancel() return true }"),
        )
    }

    @Test

    fun locking_closes_a_date_picker_left_open() {
        val change = between(flat("MainActivity.kt"), "private fun onLockChanged(locked: Boolean)", "private fun ")
        val branch = between(change, "if (locked) {", "} else {")
        assertTrue(branch.contains("if (showingOurPage()) web.evaluateJavascript(HostProtocol.CLOSE_PICKER_SCRIPT, null)"))
    }

    @Test

    fun the_setting_and_the_readme_say_five_minutes() {
        val minutes = AppLock.AWAY_MS / 60_000
        val strings = File("src/main/res/values/strings.xml").readText()
        for (name in listOf("lock_setting_note", "lock_setting_note_secure")) {
            val text = Regex("""<string name="$name">([^<]*)</string>""").find(strings)!!.groupValues[1]
            assertTrue(name, text.contains("$minutes minutes"))
        }
        assertTrue(File("README.md").readText().contains("$minutes minutes or more"))
    }

    @Test

    fun the_lock_takes_no_android_classes() {
        val imports = File("$sources/AppLock.kt").readLines().filter { it.trim().startsWith("import android.") }
        assertEquals(emptyList<String>(), imports)
    }
}
