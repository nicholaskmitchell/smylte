package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/// The launcher icon is brand/app-icon.svg's frame and tick, written into two
/// vector drawables by backend/dev/build_app_icon.py. backend/tests/test_app_icon.py
/// checks every generated file is current; this is the same guard from the
/// phone's side, so a new drawing cannot ship to the desktop and the web and
/// quietly not to the phone. Each tag is found first and its attributes read
/// from inside it, so attribute order cannot decide the answer.
class IconDriftTest {
    private val source = File("../brand/app-icon.svg").readText()

    /// The attributes of one tag, by name.
    private fun attributes(tag: String): Map<String, String> =
        Regex("([\\w:-]+)=\"([^\"]*)\"").findAll(tag).associate { it.groupValues[1] to it.groupValues[2] }

    private fun shape(cls: String): Map<String, String> {
        val tags = Regex("<(?:rect|path)\\b[^>]*>").findAll(source).map { attributes(it.value) }
            .filter { it["class"] == cls }.toList()
        assertEquals("brand/app-icon.svg: one $cls", 1, tags.size)
        return tags[0]
    }

    private val frame = shape("frame")
    private val tick = shape("tick")

    private fun paths(drawable: String): List<Map<String, String>> =
        Regex("<path\\b[^>]*>").findAll(File("src/main/res/drawable/$drawable.xml").readText())
            .map { attributes(it.value) }.toList()

    private fun check(drawable: String, frameColour: String, tickColour: String) {
        val paths = paths(drawable)
        assertEquals("$drawable: the frame and the tick", 2, paths.size)
        for ((path, stroke, colour) in listOf(Triple(paths[0], frame, frameColour), Triple(paths[1], tick, tickColour))) {
            val what = "$drawable ${stroke["class"]}"
            assertEquals("$what: path", stroke["d"], path["android:pathData"])
            assertEquals("$what: pen", stroke.getValue("stroke-width").toDouble(),
                path.getValue("android:strokeWidth").toDouble(), 1e-9)
            assertEquals("$what: colour", colour, path["android:strokeColor"])
            assertEquals("$what: cap", "round", path["android:strokeLineCap"])
            assertEquals("$what: join", "round", path["android:strokeLineJoin"])
            assertEquals("$what: a stroke, not a fill", null, path["android:fillColor"])
        }
    }

    @Test
    fun the_foreground_is_the_source_in_its_own_colours() =
        check("ic_launcher_foreground", frame.getValue("stroke").uppercase(), tick.getValue("stroke").uppercase())

    @Test
    fun the_monochrome_layer_is_the_source_in_one_ink() =
        check("ic_launcher_monochrome", "#FF000000", "#FF000000")

    @Test
    fun the_plate_is_the_source_plate() {
        val plate = shape("plate").getValue("fill").uppercase()
        val colours = File("src/main/res/values/colors.xml").readText()
        assertTrue("colors.xml: icon_plate is not $plate",
            colours.contains("<color name=\"icon_plate\">$plate</color>"))
    }
}
