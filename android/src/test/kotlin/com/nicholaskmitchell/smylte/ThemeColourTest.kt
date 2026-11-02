package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeColourTest {
    @Test
    fun hex_parses_to_an_opaque_colour() {
        assertEquals(0xFFFBFAF7.toInt(), ThemeColour.parse("#FBFAF7"))
        assertEquals(0xFFFBFAF7.toInt(), ThemeColour.parse(" #fbfaf7 "))
        assertEquals(0xFFAABBCC.toInt(), ThemeColour.parse("#abc"))
    }

    @Test
    fun anything_else_is_not_a_colour() {
        assertNull(ThemeColour.parse(null))
        assertNull(ThemeColour.parse(""))
        assertNull(ThemeColour.parse("FBFAF7"))
        assertNull(ThemeColour.parse("#FBFAF"))
        assertNull(ThemeColour.parse("#FBFAF7FF"))
        assertNull(ThemeColour.parse("#GGGGGG"))
        assertNull(ThemeColour.parse("oklch(0.2 0.02 250)"))
        assertNull(ThemeColour.parse("#-12345"))
    }

    @Test
    fun the_shipped_backgrounds_get_readable_icons() {
        assertTrue(ThemeColour.wantsDarkIcons(ThemeColour.parse("#FBFAF7")!!))   // Classic light
        assertTrue(ThemeColour.wantsDarkIcons(ThemeColour.parse("#FBFBFC")!!))   // Workspace light
        assertFalse(ThemeColour.wantsDarkIcons(ThemeColour.parse("#0C0C10")!!))  // Classic dark
        assertFalse(ThemeColour.wantsDarkIcons(ThemeColour.parse("#191919")!!))  // Workspace dark
        // The accent, by the numbers rather than by eye: black 4.9:1, white 4.3:1.
        assertTrue(ThemeColour.wantsDarkIcons(ThemeColour.parse("#C75A26")!!))
    }
}
