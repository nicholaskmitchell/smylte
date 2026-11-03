package com.nicholaskmitchell.smylte

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class HostProtocolTest {
    private fun name(n: String?) = SaveRequest.of(n, "application/json", "{}")?.name

    // The same palette as the frontend's test fixture (src/test/accent.ts).
    private val PALETTE = listOf(
        0xFFFFFFFF, 0xFFFEFBFF, 0xFFEDF0FF, 0xFFD8E2FF, 0xFFADC6FF, 0xFF7EABFF, 0xFF4D8EFF,
        0xFF2173E8, 0xFF005AC1, 0xFF004494, 0xFF002E69, 0xFF001A41, 0xFF000000,
    ).map { it.toInt() }

    // ── capabilities ────────────────────────────────────────────────────────

    @Test

    fun caps_are_well_formed_tokens() {
        assertEquals(setOf("save", "ready"), HostProtocol.parseCaps("save,ready"))
        assertEquals(setOf("save"), HostProtocol.parseCaps("save,Save,,a-b,${"x".repeat(17)}, ready"))
        assertEquals(emptySet<String>(), HostProtocol.parseCaps(null))
    }

    @Test

    fun the_seventeenth_cap_is_dropped() {
        val caps = HostProtocol.parseCaps((1..17).joinToString(",") { "c$it" })
        assertEquals((1..16).map { "c$it" }.toSet(), caps)
    }

    @Test

    fun oversized_caps_are_ignored_whole() {
        val over = "save," + "a,".repeat(126)
        assertEquals(257, over.length)
        assertEquals(emptySet<String>(), HostProtocol.parseCaps(over))
        val limit = "save," + "a,".repeat(125) + "b"
        assertEquals(256, limit.length)
        assertTrue("save" in HostProtocol.parseCaps(limit))
    }

    // ── messages ────────────────────────────────────────────────────────────

    @Test

    fun env_json_is_exact() {
        assertEquals("""{"v":1,"clock24":true}""", HostProtocol.envJson(true))
        assertEquals("""{"v":1,"clock24":false}""", HostProtocol.envJson(false))
    }

    @Test

    fun env_json_carries_the_accent_palette() {
        assertEquals(
            """{"v":1,"clock24":true,"accent":["#ffffff","#fefbff","#edf0ff","#d8e2ff","#adc6ff","#7eabff","#4d8eff","#2173e8","#005ac1","#004494","#002e69","#001a41","#000000"]}""",
            HostProtocol.envJson(true, PALETTE),
        )
    }

    @Test

    fun a_palette_of_the_wrong_size_is_left_out() {
        val bare = """{"v":1,"clock24":false}"""
        assertEquals(bare, HostProtocol.envJson(false, null))
        assertEquals(bare, HostProtocol.envJson(false, emptyList()))
        assertEquals(bare, HostProtocol.envJson(false, PALETTE.take(12)))
        assertEquals(bare, HostProtocol.envJson(false, PALETTE + PALETTE[0]))
    }

    @Test

    fun accent_colours_are_opaque_lowercase_hex() {
        assertEquals("#005ac1", HostProtocol.accentHex(0xFF005AC1.toInt()))
        assertEquals("#ffffff", HostProtocol.accentHex(0x80FFFFFF.toInt()))
        assertEquals("#ffffff", HostProtocol.accentHex(-1))
        assertEquals("#000000", HostProtocol.accentHex(0))
        assertEquals("#000001", HostProtocol.accentHex(1))
    }

    @Test

    fun accent_tones_are_material_yous() {
        assertEquals(listOf(0, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000), HostProtocol.ACCENT_TONES)
    }

    @Test

    fun events_are_exact() {
        assertEquals(
            """{"type":"env","env":{"v":1,"clock24":true}}""",
            HostProtocol.envEvent(HostProtocol.envJson(true)),
        )
        assertEquals("""{"type":"saved","outcome":"saved"}""", HostProtocol.savedEvent(HostProtocol.SaveOutcome.SAVED))
        assertEquals(
            """{"type":"saved","outcome":"cancelled"}""",
            HostProtocol.savedEvent(HostProtocol.SaveOutcome.CANCELLED),
        )
        assertEquals("""{"type":"saved","outcome":"failed"}""", HostProtocol.savedEvent(HostProtocol.SaveOutcome.FAILED))
        assertEquals(
            """window.dispatchEvent(new CustomEvent('smylte-android',{detail:{"type":"saved","outcome":"saved"}}));""",
            HostProtocol.eventScript(HostProtocol.savedEvent(HostProtocol.SaveOutcome.SAVED)),
        )
        assertEquals("""{"type":"back"}""", HostProtocol.backEvent())
        assertEquals(
            """window.dispatchEvent(new CustomEvent('smylte-android',{detail:{"type":"back"}}));""",
            HostProtocol.eventScript(HostProtocol.backEvent()),
        )
    }

    // ── a file to save ──────────────────────────────────────────────────────

    @Test

    fun only_json_is_saved() {
        assertNotNull(SaveRequest.of("a", "application/json", "{}"))
        for (mime in listOf("text/plain", "text/csv", "text/calendar", "APPLICATION/JSON", "", null)) {
            assertNull("$mime", SaveRequest.of("a", mime, "{}"))
        }
    }

    @Test

    fun the_extension_always_matches() {
        assertEquals("notes.txt.json", name("notes.txt"))
        assertEquals("x.json", name("x.JSON"))
        assertEquals("mine.smylte-theme.json", name("mine.smylte-theme.json"))
    }

    @Test

    fun names_are_sanitised() {
        assertEquals("abc.json", name("a/b\\c:.."))
        assertEquals("etcpasswd.json", name("../../etc/passwd"))
        assertEquals("smylte-theme.json", name(".smylte-theme.json"))
        assertEquals("abc.json", name("a\u0000b\nc\u007f"))
        assertEquals("ab.json", name("a\u202Eb"))
        assertEquals("ab.json", name("a*?\"<>|b"))
    }

    @Test

    fun an_empty_name_is_the_default() {
        for (n in listOf("", "   ", "...", "///", ".json")) assertEquals("smylte-export.json", name(n))
    }

    @Test

    fun names_are_cut_to_100() {
        val long = name("a".repeat(150))!!
        assertEquals("a".repeat(95) + ".json", long)
        assertEquals(100, long.length)
        // The pair straddles the cut, so it goes whole rather than in half.
        assertEquals("a".repeat(94) + ".json", name("a".repeat(94) + "😀" + "b"))
    }

    @Test

    fun sanitising_is_idempotent() {
        val inputs = listOf(
            "notes.txt", "x.JSON", "mine.smylte-theme.json", "a/b\\c:..", "../../etc/passwd", ".smylte-theme.json",
            "a\u0000b\nc\u007f", "a\u202Eb", "a*?\"<>|b", "", "   ", "...", "///", ".json",
            "a".repeat(150), "a".repeat(94) + "😀" + "b", "a".repeat(90) + ".json" + "bbbbbb",
        )
        for (n in inputs) {
            val once = name(n)!!
            assertEquals(n, once, name(once))
        }
    }

    @Test

    fun text_up_to_512_KiB() {
        assertNotNull(SaveRequest.of("a", "application/json", "x".repeat(524288)))
        assertNull(SaveRequest.of("a", "application/json", "x".repeat(524289)))
    }

    @Test

    fun nulls_are_refused() {
        assertNull(SaveRequest.of(null, "application/json", "{}"))
        assertNull(SaveRequest.of("a", null, "{}"))
        assertNull(SaveRequest.of("a", "application/json", null))
    }

    // ── the save gate and where its result goes ─────────────────────────────

    @Test

    fun a_save_waits_after_a_picker() {
        val now = 10_000L
        assertFalse(HostProtocol.allowSave(true, true, now, 8_001L, locked = false))
        assertTrue(HostProtocol.allowSave(true, true, now, 8_000L, locked = false))
        assertTrue(HostProtocol.allowSave(true, true, now, null, locked = false))
        assertFalse(HostProtocol.allowSave(true, true, now, 10_500L, locked = false))
        assertFalse(HostProtocol.allowSave(false, true, now, null, locked = false))
        assertFalse(HostProtocol.allowSave(true, false, now, null, locked = false))
    }

    @Test

    fun no_save_dialog_opens_over_the_lock() {
        assertFalse(HostProtocol.allowSave(true, true, 10_000L, null, locked = true))
    }

    @Test

    fun the_page_is_out_of_sight_when_stopped_or_locked() {
        assertFalse(HostProtocol.pageOutOfSight(started = true, locked = false))
        assertTrue(HostProtocol.pageOutOfSight(started = true, locked = true))
        assertTrue(HostProtocol.pageOutOfSight(started = false, locked = false))
        assertTrue(HostProtocol.pageOutOfSight(started = false, locked = true))
    }

    @Test

    fun a_pickers_answer_waits_for_a_started_unlocked_window() {
        assertFalse(HostProtocol.holdsResult(started = true, locked = false))
        assertTrue(HostProtocol.holdsResult(started = true, locked = true))
        // Android 11: the answer comes before onStart, where the lock may yet
        // take hold, so it waits even though the window says it is unlocked.
        assertTrue(HostProtocol.holdsResult(started = false, locked = false))
        assertTrue(HostProtocol.holdsResult(started = false, locked = true))
    }

    @Test

    fun locking_closes_only_a_date_or_time_fields_picker() {
        val js = HostProtocol.CLOSE_PICKER_SCRIPT
        assertTrue(js.contains("document.activeElement"))
        assertTrue(js.contains("e instanceof HTMLInputElement"))
        assertTrue(js.contains("/^(date|time|datetime-local|month|week)\$/.test(e.type)"))
        assertTrue(js.endsWith("e.blur();})();"))
        // It blurs and does nothing else to the page.
        assertEquals(1, Regex("""\.blur\(""").findAll(js).count())
        // The one "=" is its own variable's: nothing on the page is assigned.
        assertEquals(1, js.count { it == '=' })
        assertTrue(js.contains("var e=document.activeElement;"))
        assertFalse(js.contains("dispatchEvent"))
    }

    @Test

    fun a_save_reports_to_the_page_that_asked_only() {
        assertEquals(HostProtocol.SaveReport.PAGE, HostProtocol.saveReport(false, 3, 3, true))
        assertEquals(HostProtocol.SaveReport.TOAST, HostProtocol.saveReport(false, 3, 4, true))
        assertEquals(HostProtocol.SaveReport.TOAST, HostProtocol.saveReport(true, 3, 3, true))
        assertEquals(HostProtocol.SaveReport.TOAST, HostProtocol.saveReport(false, 3, 3, false))
    }

    // ── touch ───────────────────────────────────────────────────────────────

    @Test

    fun touch_constants_are_motion_events() {
        assertEquals(MotionEvent.ACTION_DOWN, HostProtocol.ACTION_DOWN)
        assertEquals(MotionEvent.ACTION_UP, HostProtocol.ACTION_UP)
        assertEquals(MotionEvent.ACTION_MOVE, HostProtocol.ACTION_MOVE)
        assertEquals(MotionEvent.ACTION_CANCEL, HostProtocol.ACTION_CANCEL)
        assertEquals(MotionEvent.ACTION_POINTER_DOWN, HostProtocol.ACTION_POINTER_DOWN)
    }

    @Test

    fun touching_follows_fingers() {
        val pointerUp = 6
        val outside = 4
        val hoverMove = 7
        for (a in listOf(HostProtocol.ACTION_DOWN, HostProtocol.ACTION_POINTER_DOWN, HostProtocol.ACTION_MOVE)) {
            assertTrue("$a", HostProtocol.touching(a, false))
        }
        for (a in listOf(HostProtocol.ACTION_UP, HostProtocol.ACTION_CANCEL, pointerUp, outside, hoverMove)) {
            assertFalse("$a", HostProtocol.touching(a, false))
        }
        assertFalse(HostProtocol.touching(HostProtocol.ACTION_UP, true))
        assertFalse(HostProtocol.touching(HostProtocol.ACTION_CANCEL, true))
        assertTrue(HostProtocol.touching(pointerUp, true))
        assertTrue(HostProtocol.touching(outside, true))
        assertTrue(HostProtocol.touching(HostProtocol.ACTION_MOVE, true))
    }

    @Test

    fun a_lifted_finger_is_not_down() {
        // The range DOWN..MOVE includes UP, which left a lifted finger "down".
        val events = listOf(HostProtocol.ACTION_DOWN, HostProtocol.ACTION_MOVE, HostProtocol.ACTION_UP)
        assertFalse(events.fold(false) { was, a -> HostProtocol.touching(a, was) })
    }

    @Test

    fun a_second_finger_lifting_keeps_the_first() {
        val pointerUp = 6
        val events = listOf(
            HostProtocol.ACTION_DOWN, HostProtocol.ACTION_POINTER_DOWN, pointerUp,
            HostProtocol.ACTION_MOVE, HostProtocol.ACTION_UP,
        )
        var was = false
        val states = events.map { a -> HostProtocol.touching(a, was).also { was = it } }
        assertEquals(listOf(true, true, true, true, false), states)
    }

    // ── haptics ─────────────────────────────────────────────────────────────

    private fun tapped(upAt: Long) = HapticGate().apply {
        onTouch(HostProtocol.ACTION_DOWN, upAt - 80)
        onTouch(HostProtocol.ACTION_UP, upAt)
    }

    @Test

    fun haptic_names_are_exact() {
        assertEquals(HostProtocol.Haptic.CONFIRM, HostProtocol.hapticNamed("confirm"))
        assertEquals(HostProtocol.Haptic.REJECT, HostProtocol.hapticNamed("reject"))
        assertEquals(HostProtocol.Haptic.TOGGLE_ON, HostProtocol.hapticNamed("toggleOn"))
        assertEquals(HostProtocol.Haptic.TOGGLE_OFF, HostProtocol.hapticNamed("toggleOff"))
        for (name in listOf(null, "", "Confirm", "confirm ", "dragStart", "drop", "x".repeat(100_000))) {
            assertNull("$name".take(20), HostProtocol.hapticNamed(name))
        }
    }

    @Test

    fun haptic_constants_are_the_platforms() {
        assertEquals(HapticFeedbackConstants.CLOCK_TICK, HostProtocol.FEEDBACK_CLOCK_TICK)
        assertEquals(HapticFeedbackConstants.CONFIRM, HostProtocol.FEEDBACK_CONFIRM)
        assertEquals(HapticFeedbackConstants.REJECT, HostProtocol.FEEDBACK_REJECT)
        assertEquals(HapticFeedbackConstants.TOGGLE_ON, HostProtocol.FEEDBACK_TOGGLE_ON)
        assertEquals(HapticFeedbackConstants.TOGGLE_OFF, HostProtocol.FEEDBACK_TOGGLE_OFF)
        assertEquals(Build.VERSION_CODES.UPSIDE_DOWN_CAKE, HostProtocol.SDK_TOGGLE_FEEDBACK)
    }

    @Test

    fun toggles_fall_back_before_android_14() {
        for (sdk in 30..33) {
            assertEquals("$sdk", 4, HostProtocol.hapticConstant(HostProtocol.Haptic.TOGGLE_ON, sdk))
            assertEquals("$sdk", 4, HostProtocol.hapticConstant(HostProtocol.Haptic.TOGGLE_OFF, sdk))
            assertEquals("$sdk", 16, HostProtocol.hapticConstant(HostProtocol.Haptic.CONFIRM, sdk))
            assertEquals("$sdk", 17, HostProtocol.hapticConstant(HostProtocol.Haptic.REJECT, sdk))
        }
        for (sdk in 34..36) {
            assertEquals("$sdk", 21, HostProtocol.hapticConstant(HostProtocol.Haptic.TOGGLE_ON, sdk))
            assertEquals("$sdk", 22, HostProtocol.hapticConstant(HostProtocol.Haptic.TOGGLE_OFF, sdk))
            assertEquals("$sdk", 16, HostProtocol.hapticConstant(HostProtocol.Haptic.CONFIRM, sdk))
            assertEquals("$sdk", 17, HostProtocol.hapticConstant(HostProtocol.Haptic.REJECT, sdk))
        }
    }

    @Test

    fun a_haptic_answers_a_touch_only() {
        assertFalse(HapticGate().allow(1_000, true, true))
    }

    @Test

    fun a_haptic_plays_while_a_finger_is_down() {
        val gate = HapticGate()
        gate.onTouch(HostProtocol.ACTION_DOWN, 1_000)
        assertTrue(gate.allow(60_000, true, true))
    }

    @Test

    fun a_haptic_plays_up_to_1500_ms_after_the_finger_lifts() {
        assertTrue(tapped(1_000).allow(2_499, true, true))
        assertTrue(tapped(1_000).allow(2_500, true, true))
        assertFalse(tapped(1_000).allow(2_501, true, true))
    }

    @Test

    fun a_lifted_finger_closes_the_gate() {
        // The range DOWN..MOVE would have left the gate open after the UP.
        val gate = HapticGate()
        gate.onTouch(HostProtocol.ACTION_DOWN, 100)
        gate.onTouch(HostProtocol.ACTION_MOVE, 500)
        gate.onTouch(HostProtocol.ACTION_UP, 1_000)
        assertFalse(gate.allow(2_501, true, true))
    }

    @Test

    fun two_haptics_a_touch() {
        val gate = tapped(1_000)
        assertTrue(gate.allow(1_010, true, true))
        // No minimum gap: a write refused at once still gets its reject.
        assertTrue(gate.allow(1_015, true, true))
        assertFalse(gate.allow(1_020, true, true))
        gate.onTouch(HostProtocol.ACTION_DOWN, 1_100)
        assertTrue(gate.allow(1_100, true, true))
        val other = HapticGate()
        other.onTouch(HostProtocol.ACTION_DOWN, 100)
        assertTrue(other.allow(110, true, true))
        assertTrue(other.allow(120, true, true))
        other.onTouch(HostProtocol.ACTION_POINTER_DOWN, 130)
        assertFalse(other.allow(140, true, true))
    }

    @Test

    fun no_haptic_in_the_background_or_on_another_page() {
        val gate = tapped(1_000)
        assertFalse(gate.allow(1_010, resumed = false, pageIsOurs = true))
        assertFalse(gate.allow(1_010, resumed = true, pageIsOurs = false))
        // A refusal costs nothing.
        assertTrue(gate.allow(1_010, true, true))
        assertTrue(gate.allow(1_010, true, true))
    }

    @Test

    fun leaving_closes_the_gate() {
        val gate = HapticGate()
        gate.onTouch(HostProtocol.ACTION_DOWN, 1_000)
        gate.reset()
        assertFalse(gate.allow(1_001, true, true))
        gate.onTouch(HostProtocol.ACTION_DOWN, 1_002)
        assertTrue(gate.allow(1_003, true, true))
    }

    @Test

    fun a_clock_that_went_backwards_is_refused() {
        assertFalse(tapped(2_000).allow(1_999, true, true))
    }

    // ── back ────────────────────────────────────────────────────────────────

    @Test

    fun back_closes_the_pages_top_layer_first() {
        assertEquals(HostProtocol.BackAction.PAGE, HostProtocol.backAction(1, pageIsOurs = true, canGoBack = true, locked = false))
        assertEquals(HostProtocol.BackAction.PAGE, HostProtocol.backAction(1, pageIsOurs = true, canGoBack = false, locked = false))
        assertEquals(HostProtocol.BackAction.HISTORY, HostProtocol.backAction(0, pageIsOurs = true, canGoBack = true, locked = false))
        assertEquals(HostProtocol.BackAction.SYSTEM, HostProtocol.backAction(0, pageIsOurs = true, canGoBack = false, locked = false))
    }

    @Test

    fun a_page_that_is_not_ours_gets_no_back() {
        assertEquals(HostProtocol.BackAction.HISTORY, HostProtocol.backAction(2, pageIsOurs = false, canGoBack = true, locked = false))
        assertEquals(HostProtocol.BackAction.SYSTEM, HostProtocol.backAction(2, pageIsOurs = false, canGoBack = false, locked = false))
    }

    @Test

    fun the_callback_is_held_only_while_back_stays_in_the_app() {
        assertTrue(HostProtocol.wantsBackCallback(1, pageIsOurs = true, canGoBack = true, locked = false))
        assertTrue(HostProtocol.wantsBackCallback(1, pageIsOurs = true, canGoBack = false, locked = false))
        assertTrue(HostProtocol.wantsBackCallback(0, pageIsOurs = true, canGoBack = true, locked = false))
        assertFalse(HostProtocol.wantsBackCallback(0, pageIsOurs = true, canGoBack = false, locked = false))
        assertTrue(HostProtocol.wantsBackCallback(2, pageIsOurs = false, canGoBack = true, locked = false))
        assertFalse(HostProtocol.wantsBackCallback(2, pageIsOurs = false, canGoBack = false, locked = false))
    }

    @Test

    fun back_leaves_a_locked_window_without_closing_it() {
        // Nothing reaches a page the user cannot see, and the window is not
        // finished, so what the page had open is still there after the unlock.
        for (layers in 0..1) {
            for (canGoBack in listOf(false, true)) {
                assertEquals(
                    HostProtocol.BackAction.MOVE_TO_BACK,
                    HostProtocol.backAction(layers, pageIsOurs = true, canGoBack = canGoBack, locked = true),
                )
                assertTrue(HostProtocol.wantsBackCallback(layers, pageIsOurs = true, canGoBack = canGoBack, locked = true))
            }
        }
    }

    @Test

    fun layer_counts_are_clamped() {
        assertEquals(0, HostProtocol.clampLayers(Int.MIN_VALUE))
        assertEquals(0, HostProtocol.clampLayers(-1))
        assertEquals(0, HostProtocol.clampLayers(0))
        assertEquals(3, HostProtocol.clampLayers(3))
        assertEquals(16, HostProtocol.clampLayers(16))
        assertEquals(16, HostProtocol.clampLayers(17))
        assertEquals(16, HostProtocol.clampLayers(Int.MAX_VALUE))
        assertEquals(16, HostProtocol.MAX_LAYERS)
    }

    @Test

    fun a_report_from_a_replaced_document_is_dropped() {
        assertEquals(2, HostProtocol.layersAfterReport(held = 0, depth = 2, reportedIn = 4, current = 4))
        assertEquals(0, HostProtocol.layersAfterReport(held = 0, depth = 2, reportedIn = 3, current = 4))
        assertEquals(1, HostProtocol.layersAfterReport(held = 1, depth = 0, reportedIn = 3, current = 4))
        assertEquals(0, HostProtocol.layersAfterReport(held = 1, depth = 0, reportedIn = 4, current = 4))
    }

    // ── the splash screen ───────────────────────────────────────────────────

    private fun release(
        elapsed: Long = 100,
        failed: Boolean = false,
        pageReady: Boolean = false,
        wantsReady: Boolean = false,
        pageFinished: Boolean = false,
        locked: Boolean = false,
    ) = HostProtocol.splashRelease(elapsed, failed, pageReady, wantsReady, pageFinished, locked)

    @Test

    fun a_locked_window_ends_the_splash() {
        assertTrue(release(elapsed = 0, wantsReady = true, locked = true))
        assertFalse(release(elapsed = 0, wantsReady = true))
    }

    @Test

    fun splash_constants_are_the_platforms() {
        assertEquals(Build.VERSION_CODES.S, HostProtocol.SDK_SPLASH_SCREEN)
        assertEquals("ready", HostProtocol.CAP_READY)
        assertEquals(3_000L, HostProtocol.SPLASH_CAP_MS)
        // A window that has never drawn has no input focus, and a key event
        // that waits 5 s for one is an ANR.
        assertTrue(HostProtocol.SPLASH_CAP_MS < 5_000L)
    }

    @Test

    fun the_splash_cap_counts_from_the_process_start_on_a_cold_launch() {
        val cap = HostProtocol.SPLASH_CAP_MS
        val cold = HostProtocol.COLD_START_MS
        fun since(now: Long, processStart: Long = 10_000, firstWindow: Boolean = true) =
            HostProtocol.splashSince(now, processStart, firstWindow)
        // Cold: the process's first window, 800 ms after it started, when the
        // splash went up.
        assertEquals(10_000L, since(10_800))
        assertEquals(10_000L, since(10_000 + cap - 1))
        // Still cold when reaching the window took the whole cap or more: a
        // slow start is not taken for a warm one, whose hold would come on top.
        assertEquals(10_000L, since(10_000 + cap))
        assertEquals(10_000L, since(10_000 + cold - 1))
        // A first window long after the process started: the process was
        // running before the tap, so the cap counts from now.
        assertEquals(10_000L + cold, since(10_000 + cold))
        assertEquals(900_000L, since(900_000))
        // Not the process's first window: warm, however young the process.
        assertEquals(10_800L, since(10_800, firstWindow = false))
        // A start in the future counts from now; simultaneous, from that moment.
        assertEquals(10_000L, since(10_000, processStart = 12_000))
        assertEquals(10_000L, since(10_000, processStart = 10_000))
        assertTrue(cold > cap)
    }

    @Test

    fun a_launch_that_used_up_the_cap_holds_nothing() {
        val cap = HostProtocol.SPLASH_CAP_MS
        assertEquals(cap, HostProtocol.splashLeft(now = 5_000, since = 5_000))
        assertEquals(2_200L, HostProtocol.splashLeft(now = 10_800, since = 10_000))
        assertEquals(1L, HostProtocol.splashLeft(now = 10_000 + cap - 1, since = 10_000))
        assertEquals(0L, HostProtocol.splashLeft(now = 10_000 + cap, since = 10_000))
        assertTrue(HostProtocol.splashLeft(now = 10_000 + 2 * cap, since = 10_000) < 0)
        // The window holds only with time left, and the cap's timer is set to it.
        val code = File("src/main/kotlin/com/nicholaskmitchell/smylte/MainActivity.kt").readText()
        val hold = code.substringAfter("private fun holdSplash(").substringBefore("private fun processStart()")
        val skip = hold.indexOf("if (left <= 0) return")
        assertTrue(skip >= 0)
        assertTrue(skip < hold.indexOf("splashHeld = true"))
        assertTrue(hold.contains("main.postDelayed(splashCap, left)"))
        // On 13 and later the start counts from when it was asked for.
        assertTrue(code.contains("Process.getStartRequestedUptimeMillis()"))
        // The first window is told once a process, at its creation, before
        // anything can return early, and that is what the cap is counted by.
        assertEquals(1, Regex("""createdBefore = true""").findAll(code).count())
        assertTrue(hold.contains("HostProtocol.splashSince(now, processStart(), firstWindow)"))
        val create = code.substringAfter("override fun onCreate(").substringBefore("holdSplash(savedInstanceState, firstWindow)")
        val read = create.indexOf("val firstWindow = !createdBefore")
        assertTrue(read >= 0)
        assertTrue(create.indexOf("createdBefore = true") > read)
        // Before the early return of a phone that is not set up yet.
        val early = Regex("""^\s+return$""", RegexOption.MULTILINE).find(create)
        assertTrue(early != null)
        assertTrue(create.indexOf("createdBefore = true") < early!!.range.first)
    }

    @Test

    fun the_splash_is_held_only_on_a_fresh_launch_from_the_launcher() {
        assertTrue(HostProtocol.holdsSplash(31, restored = false, fromLauncher = true))
        assertTrue(HostProtocol.holdsSplash(36, restored = false, fromLauncher = true))
        // Android 11 has no platform splash.
        assertFalse(HostProtocol.holdsSplash(30, restored = false, fromLauncher = true))
        // Rebuilt from saved state: no splash in front of it.
        assertFalse(HostProtocol.holdsSplash(34, restored = true, fromLauncher = true))
        // Opened by the settings screen, which may have no splash either.
        assertFalse(HostProtocol.holdsSplash(34, restored = false, fromLauncher = false))
    }

    @Test

    fun nothing_ends_the_splash_early() {
        assertFalse(release(elapsed = 0))
        assertFalse(release(elapsed = 2_999))
        assertFalse(release(wantsReady = true))
    }

    @Test

    fun the_pages_ready_ends_the_splash() {
        assertTrue(release(pageReady = true, wantsReady = true))
        // From a page that never announced it: at worst the splash ends early.
        assertTrue(release(pageReady = true))
    }

    @Test

    fun the_failure_screen_ends_the_splash() {
        assertTrue(release(elapsed = 0, failed = true, wantsReady = true))
    }

    @Test

    fun the_cap_ends_the_splash() {
        assertFalse(release(elapsed = 2_999, wantsReady = true))
        assertTrue(release(elapsed = 3_000, wantsReady = true))
        assertTrue(release(elapsed = Long.MAX_VALUE, wantsReady = true))
    }

    @Test

    fun an_old_page_ends_the_splash_when_it_has_loaded() {
        assertFalse(release(wantsReady = false, pageFinished = false))
        assertTrue(release(wantsReady = false, pageFinished = true))
    }

    @Test

    fun a_new_page_is_waited_for_after_it_has_loaded() {
        assertFalse(release(wantsReady = true, pageFinished = true))
        assertTrue(release(wantsReady = true, pageFinished = true, pageReady = true))
        assertTrue(release(elapsed = 3_000, wantsReady = true, pageFinished = true))
    }

    @Test

    fun a_clock_that_went_backwards_ends_the_splash() {
        assertTrue(release(elapsed = -1, wantsReady = true))
    }

    @Test

    fun the_splash_waits_on_nothing_that_needs_a_drawn_window() {
        // While the window does not draw, a visual-state callback may never
        // come, and a listener on the splash's exit changes how the window fits
        // the bars on Android 12 and 12L.
        val activity = File("src/main/kotlin/com/nicholaskmitchell/smylte/MainActivity.kt").readText()
        for (name in listOf("onPageCommitVisible", "postVisualStateCallback", "setOnExitAnimationListener")) {
            assertFalse(name, activity.contains(name))
        }
    }

    // ── drift and purity ────────────────────────────────────────────────────

    @Test

    fun the_page_speaks_the_same_protocol() {
        val ts = File("../frontend/src/android.ts").readText()
        assertTrue(ts.contains("export const ANDROID_EVENT = '${HostProtocol.EVENT}'"))
        val version = Regex("""const ENV_VERSION = (\d+)""").find(ts)?.groupValues?.get(1)
        assertEquals(HostProtocol.ENV_VERSION.toString(), version)
        for (outcome in HostProtocol.SaveOutcome.values()) {
            assertTrue(outcome.wire, ts.contains("'${outcome.wire}'"))
        }
        val caps = Regex("""const CAPS = '([^']*)'""").find(ts)?.groupValues?.get(1)
        assertNotNull("no CAPS in android.ts", caps)
        assertTrue("CAPS is empty", caps!!.isNotEmpty())
        val tokens = caps.split(',')
        // The host holds the splash screen for this capability, so the page must
        // announce it (App.ready.test.tsx proves it is fulfilled).
        assertTrue(HostProtocol.CAP_READY, HostProtocol.CAP_READY in tokens)
        assertEquals(tokens.toSet(), HostProtocol.parseCaps(caps))
    }

    @Test

    fun the_page_reads_every_env_field() {
        // The page acts on env fields now: it writes `clock24` to the account
        // and paints `accent`. A field renamed on one side alone would leave
        // the page silently reading nothing. The version is pinned by the test
        // above.
        val ts = File("../frontend/src/android.ts").readText()
        val fields = Regex(""""([A-Za-z0-9_]+)":""")
            .findAll(HostProtocol.envJson(true, List(HostProtocol.ACCENT_TONES.size) { 0 }))
            .map { it.groupValues[1] }.filter { it != "v" }.toList()
        assertTrue("the env carries no fields", fields.isNotEmpty())
        for (field in fields) {
            assertTrue(field, Regex("""\.$field\b""").containsMatchIn(ts))
        }
    }

    @Test

    fun the_page_reads_the_same_accent_tones() {
        val ts = File("../frontend/src/android.ts").readText()
        val match = Regex("""export const ACCENT_TONES[^=]*= \[([^\]]*)\]""").find(ts)
        assertNotNull("android.ts has no ACCENT_TONES", match)
        val tones = match!!.groupValues[1].split(',').map { it.trim().toInt() }
        assertEquals(HostProtocol.ACCENT_TONES, tones)
    }

    @Test

    fun the_page_answers_every_event_type() {
        val ts = File("../frontend/src/android.ts").readText()
        val events = listOf(
            HostProtocol.envEvent(HostProtocol.envJson(true)),
            HostProtocol.savedEvent(HostProtocol.SaveOutcome.SAVED),
            HostProtocol.backEvent(),
        )
        for (event in events) {
            val type = Regex(""""type":"(\w+)"""").find(event)?.groupValues?.get(1)
            assertNotNull(event, type)
            assertTrue(type, ts.contains("msg.type === '$type'"))
        }
    }

    @Test

    fun the_page_names_the_same_haptics() {
        val ts = File("../frontend/src/android.ts").readText()
        val line = Regex("""export type HapticKind = ([^\n]+)""").find(ts)?.groupValues?.get(1)
        assertNotNull("no HapticKind in android.ts", line)
        val names = Regex("""'(\w+)'""").findAll(line!!).map { it.groupValues[1] }.toSet()
        assertTrue("HapticKind is empty", names.isNotEmpty())
        assertEquals(HostProtocol.Haptic.values().map { it.wire }.toSet(), names)
    }

    @Test

    fun haptics_honour_the_system_setting() {
        // The one-argument call lets the phone's touch feedback setting decide;
        // a flag or a permission would be a way around it.
        val activity = File("src/main/kotlin/com/nicholaskmitchell/smylte/MainActivity.kt").readText()
        assertFalse(activity.contains("FLAG_IGNORE"))
        assertFalse(activity.contains("HapticFeedbackEnabled"))
        assertFalse(File("src/main/AndroidManifest.xml").readText().contains("android.permission.VIBRATE"))
    }

    @Test

    fun the_protocol_takes_no_android_classes() {
        val source = File("src/main/kotlin/com/nicholaskmitchell/smylte/HostProtocol.kt").readLines()
        assertTrue(source.none { it.trimStart().startsWith("import android.") })
        assertTrue(source.none { it.contains("org.json") })
    }

    // ── the WebView ─────────────────────────────────────────────────────────

    @Test
    fun the_webview_major_version_is_read_from_its_version_name() {
        assertEquals(133, HostProtocol.webViewMajor("133.0.6943.137"))
        assertEquals(83, HostProtocol.webViewMajor("83.0.4103.106"))
        assertEquals(107, HostProtocol.webViewMajor(" 107.0.5304.105 "))
        assertEquals(140, HostProtocol.webViewMajor("140"))
        assertNull(HostProtocol.webViewMajor(null))
        assertNull(HostProtocol.webViewMajor(""))
        assertNull(HostProtocol.webViewMajor("unknown"))
        assertNull(HostProtocol.webViewMajor("0.1"))
        assertNull(HostProtocol.webViewMajor("-5.0"))
    }

    @Test
    fun a_webview_older_than_107_is_too_old_and_an_unreadable_one_is_not() {
        assertEquals(107, HostProtocol.MIN_WEBVIEW_MAJOR)
        assertTrue(HostProtocol.webViewTooOld("83.0.4103.106"))
        assertTrue(HostProtocol.webViewTooOld("106.0.5249.126"))
        assertFalse(HostProtocol.webViewTooOld("107.0.5304.105"))
        assertFalse(HostProtocol.webViewTooOld("133.0.6943.137"))
        assertFalse(HostProtocol.webViewTooOld(null))
        assertFalse(HostProtocol.webViewTooOld("unknown"))
    }

    @Test
    fun the_minimum_webview_follows_the_frontends_build_target() {
        // MIN_WEBVIEW_MAJOR is Chrome 107 because the frontend builds with
        // Vite 7's default target. A build.target of its own, or another major
        // of Vite, can change what the page needs: update the minimum with it.
        val config = File("../frontend/vite.config.ts").readText()
        assertFalse(Regex("""\btarget\s*:""").containsMatchIn(config))
        val pkg = File("../frontend/package.json").readText()
        assertTrue(Regex(""""vite"\s*:\s*"\^7\.""").containsMatchIn(pkg))
    }

    @Test
    fun boot_checks_the_webview_before_start_up() {
        val source = File("src/main/kotlin/com/nicholaskmitchell/smylte/MainActivity.kt").readText()
        val boot = source.substringAfter("private fun boot() {").substringBefore("\n    }\n")
        val check = boot.indexOf("outdatedWebView()?.let {")
        assertTrue(check >= 0)
        assertTrue(check < boot.indexOf("booting = true"))
        assertTrue(check < boot.indexOf("Background.updates.execute"))
        assertTrue(boot.contains("showSplash(it, failed = true)"))
        val outdated = source.substringAfter("private fun outdatedWebView(): String? {").substringBefore("\n    }\n")
        assertTrue(outdated.contains("WebView.getCurrentWebViewPackage() ?: return null"))
        assertTrue(outdated.contains("if (!HostProtocol.webViewTooOld(provider.versionName)) return null"))
    }
}
