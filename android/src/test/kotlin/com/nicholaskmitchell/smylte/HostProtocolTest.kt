package com.nicholaskmitchell.smylte

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
        assertFalse(HostProtocol.allowSave(true, true, now, 8_001L))
        assertTrue(HostProtocol.allowSave(true, true, now, 8_000L))
        assertTrue(HostProtocol.allowSave(true, true, now, null))
        assertFalse(HostProtocol.allowSave(true, true, now, 10_500L))
        assertFalse(HostProtocol.allowSave(false, true, now, null))
        assertFalse(HostProtocol.allowSave(true, false, now, null))
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
        assertEquals(tokens.toSet(), HostProtocol.parseCaps(caps))
    }

    @Test

    fun the_page_reads_every_env_field() {
        // The page acts on env fields now: it writes `clock24` to the account.
        // A field renamed on one side alone would leave the page silently
        // reading nothing. The version is pinned by the test above.
        val ts = File("../frontend/src/android.ts").readText()
        val fields = Regex(""""([A-Za-z0-9_]+)":""").findAll(HostProtocol.envJson(true))
            .map { it.groupValues[1] }.filter { it != "v" }.toList()
        assertTrue("the env carries no fields", fields.isNotEmpty())
        for (field in fields) {
            assertTrue(field, Regex("""\.$field\b""").containsMatchIn(ts))
        }
    }

    @Test

    fun the_protocol_takes_no_android_classes() {
        val source = File("src/main/kotlin/com/nicholaskmitchell/smylte/HostProtocol.kt").readLines()
        assertTrue(source.none { it.trimStart().startsWith("import android.") })
        assertTrue(source.none { it.contains("org.json") })
    }
}
