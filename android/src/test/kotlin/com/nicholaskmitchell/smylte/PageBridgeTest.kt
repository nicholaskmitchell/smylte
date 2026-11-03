package com.nicholaskmitchell.smylte

import android.webkit.JavascriptInterface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.lang.reflect.Modifier

class PageBridgeTest {
    private class FakeHost(
        private val env: String = """{"v":1,"clock24":true}""",
        private val accept: Boolean = true,
        private val fail: Boolean = false,
    ) : PageBridge.Host {
        val colours = mutableListOf<Int>()
        val caps = mutableListOf<Set<String>>()
        val saves = mutableListOf<SaveRequest>()
        val depths = mutableListOf<Int>()
        val haptics = mutableListOf<HostProtocol.Haptic>()
        var readies = 0

        override fun colour(colour: Int) {
            if (fail) throw IllegalStateException("host failed")
            colours += colour
        }

        override fun hello(caps: Set<String>): String {
            if (fail) throw IllegalStateException("host failed")
            this.caps += caps
            return env
        }

        override fun layers(depth: Int) {
            if (fail) throw IllegalStateException("host failed")
            depths += depth
        }

        override fun haptic(kind: HostProtocol.Haptic) {
            if (fail) throw IllegalStateException("host failed")
            haptics += kind
        }

        override fun save(request: SaveRequest): Boolean {
            if (fail) throw IllegalStateException("host failed")
            saves += request
            return accept
        }

        override fun ready() {
            if (fail) throw IllegalStateException("host failed")
            readies += 1
        }
    }

    @Test

    fun the_page_can_call_exactly_these_methods() {
        val methods = PageBridge::class.java.declaredMethods
            .filter { Modifier.isPublic(it.modifiers) && !it.isSynthetic }
        assertEquals(
            setOf("themeColour", "hello", "saveFile", "layers", "haptic", "ready"),
            methods.map { it.name }.toSet(),
        )
        for (m in methods) {
            assertTrue(m.name, m.isAnnotationPresent(JavascriptInterface::class.java))
        }
    }

    @Test

    fun release_builds_keep_the_bridge_by_its_name() {
        val rules = File("proguard-rules.pro").readText()
        assertTrue(rules.contains("-keepclassmembers class com.nicholaskmitchell.smylte.PageBridge"))
        assertFalse(rules.contains("ThemeBridge"))
    }

    @Test

    fun only_a_colour_reaches_the_host() {
        val host = FakeHost()
        val bridge = PageBridge(host)
        bridge.themeColour("#112233")
        assertEquals(listOf(0xFF112233.toInt()), host.colours)
        bridge.themeColour("oklch(0.2 0.02 250)")
        bridge.themeColour(null)
        bridge.themeColour("")
        assertEquals(1, host.colours.size)
    }

    @Test

    fun hello_answers_the_hosts_env_with_parsed_caps() {
        val host = FakeHost()
        assertEquals("""{"v":1,"clock24":true}""", PageBridge(host).hello("save,ready,BAD"))
        assertEquals(listOf(setOf("save", "ready")), host.caps)
    }

    @Test

    fun a_failing_host_fails_quietly() {
        val bridge = PageBridge(FakeHost(fail = true))
        assertEquals("{}", bridge.hello("save"))
        bridge.themeColour("#112233")
        assertFalse(bridge.saveFile("a", "application/json", "{}"))
        bridge.layers(1)
        bridge.haptic("confirm")
        bridge.ready()
    }

    @Test

    fun ready_reaches_the_host_each_time() {
        val host = FakeHost()
        val bridge = PageBridge(host)
        // The host ends its hold on the first call, and a later one changes
        // nothing there.
        bridge.ready()
        bridge.ready()
        assertEquals(2, host.readies)
    }

    @Test

    fun layer_counts_reach_the_host_clamped() {
        val host = FakeHost()
        val bridge = PageBridge(host)
        bridge.layers(2)
        bridge.layers(-3)
        bridge.layers(1000)
        assertEquals(listOf(2, 0, 16), host.depths)
    }

    @Test

    fun only_known_haptics_reach_the_host() {
        val host = FakeHost()
        val bridge = PageBridge(host)
        for (kind in listOf("confirm", "reject", "toggleOn", "toggleOff")) bridge.haptic(kind)
        for (kind in listOf("dragStart", "drop", "Confirm", "", null, "x".repeat(100_000))) bridge.haptic(kind)
        assertEquals(
            listOf(
                HostProtocol.Haptic.CONFIRM, HostProtocol.Haptic.REJECT,
                HostProtocol.Haptic.TOGGLE_ON, HostProtocol.Haptic.TOGGLE_OFF,
            ),
            host.haptics,
        )
    }

    @Test

    fun the_page_declares_exactly_these_methods() {
        val ts = File("../frontend/src/android.ts").readText()
        val body = Regex("""interface AndroidBridge \{(.*?)\n\}""", RegexOption.DOT_MATCHES_ALL)
            .find(ts)?.groupValues?.get(1)
        assertNotNull("no AndroidBridge in android.ts", body)
        val declared = body!!.lines().mapNotNull { Regex("""^\s*(\w+)\?:""").find(it)?.groupValues?.get(1) }.toSet()
        val exposed = PageBridge::class.java.declaredMethods
            .filter { it.isAnnotationPresent(JavascriptInterface::class.java) }
            .map { it.name }.toSet()
        assertEquals(exposed, declared)
    }

    @Test

    fun an_invalid_save_never_reaches_the_host() {
        val host = FakeHost()
        val bridge = PageBridge(host)
        assertFalse(bridge.saveFile("a", "application/json", "x".repeat(SaveRequest.MAX_TEXT_CHARS + 1)))
        assertFalse(bridge.saveFile("a", "text/plain", "{}"))
        assertFalse(bridge.saveFile("a", "application/json", null))
        assertFalse(bridge.saveFile("a", null, "{}"))
        assertTrue(host.saves.isEmpty())
    }

    @Test

    fun a_valid_save_reaches_the_host_sanitised() {
        val host = FakeHost()
        assertTrue(PageBridge(host).saveFile("../Mine.txt", "application/json", "{}"))
        assertEquals("Mine.txt.json", host.saves[0].name)
    }

    @Test

    fun the_hosts_refusal_is_the_pages_answer() {
        assertFalse(PageBridge(FakeHost(accept = false)).saveFile("a", "application/json", "{}"))
    }
}
