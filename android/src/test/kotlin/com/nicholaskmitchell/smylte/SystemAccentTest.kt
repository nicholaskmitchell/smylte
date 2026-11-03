package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

class SystemAccentTest {
    private val sources = "src/main/kotlin/com/nicholaskmitchell/smylte"

    @Test

    fun the_palette_is_read_by_name_in_tone_order() {
        val code = File("$sources/SystemAccent.kt").readLines()
            .filterNot { it.trimStart().startsWith("//") }
            .joinToString("\n")
        val tones = Regex("""android\.R\.color\.system_accent1_(\d+)""").findAll(code)
            .map { it.groupValues[1].toInt() }.toList()
        assertEquals(HostProtocol.ACCENT_TONES, tones)
    }

    @Test

    fun every_name_is_the_platforms() {
        val ids = HostProtocol.ACCENT_TONES.map { tone ->
            android.R.color::class.java.getField("system_accent1_$tone").getInt(null)
        }
        assertEquals(ids.size, ids.toSet().size)
    }

    @Test

    fun the_window_reports_the_palette_with_the_clock() {
        // So no path builds the env without the palette: both facts are read in
        // currentEnv, and only there.
        val activity = File("$sources/MainActivity.kt").readText()
        assertEquals(1, Regex(Regex.escape("SystemAccent.read(this)")).findAll(activity).count())
        assertEquals(1, Regex(Regex.escape("DateFormat.is24HourFormat(this)")).findAll(activity).count())
    }
}
