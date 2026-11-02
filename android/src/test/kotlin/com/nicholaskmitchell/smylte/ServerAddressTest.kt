package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerAddressTest {
    private fun ok(input: String) =
        (ServerAddress.parse(input) as? ServerAddress.Parsed.Ok)?.origin
            ?: throw AssertionError("refused $input: ${ServerAddress.parse(input)}")

    private fun bad(input: String) =
        assertTrue("accepted $input", ServerAddress.parse(input) is ServerAddress.Parsed.Bad)

    @Test
    fun an_https_address_becomes_its_origin() {
        assertEquals("https://smylte.example.com", ok("https://smylte.example.com"))
        assertEquals("https://smylte.example.com", ok("https://smylte.example.com/"))
        assertEquals("https://smylte.example.com", ok("  https://Smylte.Example.COM/  "))
        assertEquals("https://smylte.example.com", ok("smylte.example.com"))
        assertEquals("https://smylte.example.com", ok("https://smylte.example.com:443"))
        assertEquals("https://smylte.example.com:8443", ok("https://smylte.example.com:8443/"))
        assertEquals("https://smylte.example.com", ok("HTTPS://smylte.example.com"))
    }

    @Test
    fun anything_that_is_not_an_https_origin_is_refused() {
        bad("")
        bad("   ")
        bad("http://smylte.example.com")
        bad("ftp://smylte.example.com")
        bad("https://smylte.example.com/app")
        bad("https://smylte.example.com/?x=1")
        bad("https://smylte.example.com/#x")
        bad("https://user:pw@smylte.example.com")
        bad("https://")
        bad("https://exa mple.com")
        bad("javascript:alert(1)")
        bad("file:///etc/passwd")
    }
}
