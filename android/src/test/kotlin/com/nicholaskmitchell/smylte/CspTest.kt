package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/// The CSP port. backend/tests/test_csp.py compares the DIRECTIVE LIST with
/// csp.py; this pins the exact header and the hashing, with vectors taken from
/// csp.py itself (`inline_script_hashes`), so the two cannot disagree about
/// what a script's hash is.
class CspTest {
    private val noScript = "default-src 'self'; base-uri 'none'; object-src 'none'; " +
        "frame-ancestors 'none'; form-action 'self'; img-src 'self'; connect-src 'self'; " +
        "script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
        "font-src 'self' https://fonts.gstatic.com"

    @Test
    fun with_nothing_to_hash_it_is_csp_py_build_policy_with_no_hashes() {
        assertEquals(noScript, Csp.policyFor(null))
        assertEquals(noScript, Csp.policyFor("<html></html>"))
    }

    @Test
    fun inline_scripts_hash_as_csp_py_hashes_them() {
        val html = "<script>console.log(1)</script><script src=\"/a.js\"></script>" +
            "<SCRIPT type=\"x\">\nvar a = \"é\";\n</SCRIPT>"
        assertEquals(
            listOf(
                "'sha256-CihokcEcBW4atb/CW/XWsvWwbTjqwQlE9nj9ii5ww5M='",
                "'sha256-I444i+co4t4zpiKgvY0ahbLJVbOwBASz2WBOdVs2exU='",
            ),
            Csp.inlineScriptHashes(html),
        )
        assertTrue(
            Csp.policyFor(html).contains(
                "script-src 'self' 'sha256-CihokcEcBW4atb/CW/XWsvWwbTjqwQlE9nj9ii5ww5M=' " +
                    "'sha256-I444i+co4t4zpiKgvY0ahbLJVbOwBASz2WBOdVs2exU='; ",
            ),
        )
    }

    @Test
    fun the_load_bearing_directives_hold() {
        val policy = Csp.policyFor("<script>x</script>")
        assertFalse("script-src must never gain 'unsafe-inline'", policy.substringAfter("script-src").substringBefore(";").contains("unsafe-inline"))
        val style = policy.substringAfter("style-src").substringBefore(";")
        assertFalse("style-src must never gain a hash", style.contains("sha256"))
        assertFalse("style-src must never gain a nonce", style.contains("nonce"))
        assertTrue(policy.contains("connect-src 'self'"))
        assertFalse(policy.endsWith(";"))
    }

    @Test
    fun the_real_index_html_has_exactly_one_inline_script_to_hash() {
        // The pre-paint script. If this goes to zero the page still paints but
        // flashes; if it grows, a new inline script was added that the policy
        // now has to carry.
        val index = File("../frontend/index.html")
        assertTrue("run from android/: ${index.absolutePath}", index.isFile)
        assertEquals(1, Csp.inlineScriptHashes(index.readText()).size)
    }
}
