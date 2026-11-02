package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/// The launcher icon is the favicon's mark, copied into two vector drawables.
/// The desktop icons are regenerated from the favicon by build_app_icon.py and
/// checked byte by byte; this is the same guard for the copy here, so a new
/// mark cannot ship to the desktop and quietly not to the phone.
class IconDriftTest {
    private val favicon = File("../frontend/public/favicon.svg").readText()

    private val sPath = Regex("<path d=\"([^\"]+)\"").find(favicon)!!.groupValues[1]
    private val dot = Regex("<circle cx=\"([\\d.]+)\" cy=\"([\\d.]+)\" r=\"([\\d.]+)\"")
        .find(favicon)!!.groupValues.drop(1).map { it.toDouble() }

    private fun pathData(drawable: String): List<String> =
        Regex("android:pathData=\"([^\"]+)\"")
            .findAll(File("src/main/res/drawable/$drawable.xml").readText())
            .map { it.groupValues[1] }.toList()

    private fun check(drawable: String) {
        val paths = pathData(drawable)
        assertEquals("$drawable: the S and the period", 2, paths.size)
        assertEquals("$drawable: the S differs from favicon.svg", sPath, paths[0])

        // The period, drawn as two arcs from its left edge: M(cx-r),cy a r,r … 2r,0 …
        val numbers = Regex("-?[\\d.]+").findAll(paths[1]).map { it.value.toDouble() }.toList()
        val (cx, cy, r) = dot
        assertEquals("$drawable: period x", cx - r, numbers[0], 1e-3)
        assertEquals("$drawable: period y", cy, numbers[1], 1e-3)
        assertEquals("$drawable: period radius", r, numbers[2], 1e-3)
        assertEquals("$drawable: period diameter", 2 * r, numbers[7], 1e-3)
    }

    @Test
    fun the_foreground_is_the_favicon_mark() = check("ic_launcher_foreground")

    @Test
    fun the_monochrome_layer_is_the_favicon_mark() = check("ic_launcher_monochrome")

    @Test
    fun the_colours_are_the_favicon_colours() {
        val fg = File("src/main/res/drawable/ic_launcher_foreground.xml").readText()
        val fill = Regex("<path d=\"[^\"]+\" fill=\"(#[0-9a-fA-F]{6})\"").find(favicon)!!.groupValues[1]
        val dotFill = Regex("<circle [^>]*fill=\"(#[0-9a-fA-F]{6})\"").find(favicon)!!.groupValues[1]
        val plate = Regex("<rect [^>]*fill=\"(#[0-9a-fA-F]{6})\"").find(favicon)!!.groupValues[1]
        assertTrue(fg.contains("android:fillColor=\"${fill.uppercase()}\""))
        assertTrue(fg.contains("android:fillColor=\"${dotFill.uppercase()}\""))
        val colours = File("src/main/res/values/colors.xml").readText()
        assertTrue(colours.contains("<color name=\"icon_plate\">${plate.uppercase()}</color>"))
    }
}
