package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.io.File

class TextZoomTest {
    private val density = 2.625f

    @Test fun the_default_size_is_no_zoom() {
        assertEquals(100, TextZoom.percent(15f * density, 15f * density))
    }

    @Test fun a_linear_scale_is_its_own_percentage() {
        // Android 11 to 13: sp is dp times fontScale.
        assertEquals(85, TextZoom.percent(0.85f * 15f * density, 15f * density))
        assertEquals(115, TextZoom.percent(1.15f * 15f * density, 15f * density))
        assertEquals(130, TextZoom.percent(19.5f, 15f))
        assertEquals(200, TextZoom.percent(30f, 15f))
    }

    @Test fun the_zoom_is_the_converted_size_not_the_font_scale() {
        // Under a non-linear curve, 15sp drawn at 27dp is 180%, whatever
        // fontScale says.
        assertEquals(180, TextZoom.percent(27f * density, 15f * density))
    }

    @Test fun nothing_android_offers_is_capped() {
        for (p in 85..200) assertEquals("$p%", p, TextZoom.percent(p * 15f / 100f, 15f))
    }

    @Test fun the_bounds_hold_beyond_every_setting() {
        assertEquals(50, TextZoom.percent(1f, 15f))
        assertEquals(50, TextZoom.percent(7.5f, 15f))
        assertEquals(300, TextZoom.percent(45f, 15f))
        assertEquals(300, TextZoom.percent(100f, 15f))
    }

    @Test fun nonsense_metrics_mean_no_zoom() {
        val pairs = listOf(
            15f to 0f, 15f to -15f, 0f to 15f, -15f to 15f,
            Float.NaN to 15f, 15f to Float.NaN,
            Float.POSITIVE_INFINITY to 15f, 15f to Float.POSITIVE_INFINITY,
        )
        for ((sp, dp) in pairs) assertEquals("$sp/$dp", 100, TextZoom.percent(sp, dp))
    }

    @Test fun the_body_size_is_the_stylesheets() {
        val css = File("../frontend/src/styles/tokens.css").readText()
        val body = Regex("""(?m)^body\s*\{([^}]*)\}""").find(css)?.groupValues?.get(1)
        assertNotNull("no body rule in tokens.css", body)
        val px = Regex("""font-size:\s*calc\(\s*([\d.]+)px\s*\*\s*var\(--fs-scale\)\s*\)""")
            .find(body!!)?.groupValues?.get(1)?.toFloat()
        assertNotNull("no body font-size in tokens.css", px)
        assertEquals(TextZoom.BODY_SP, px!!, 0f)
    }
}
