package com.nicholaskmitchell.smylte

import java.security.MessageDigest
import java.util.Base64

/// Content-Security-Policy for the document this client serves from disk.
///
/// A PORT of backend/smylted/csp.py, and it has to stay a faithful one, for the
/// reason desktop/Smylte.Desktop/LocalServer.cs gives for its own copy: the
/// app's policy exists only as a header the BACKEND attaches, and a document
/// served off disk never passes through the backend. Without this the page
/// would run with no policy at all, on the one surface that also holds a live
/// session cookie for the real server, and here at the real server's origin.
///
/// backend/tests/test_csp.py reads this file and fails if the directive list
/// drifts from csp.py's, the same way it reads LocalServer.cs.
///
/// The script hash is derived from the file actually served, never written
/// down: Vite rewrites the pre-paint script on every build, and a stale hash is
/// a blank window.
object Csp {
    /// A `<script>` with a body to hash, i.e. not a `src=` reference. The same
    /// pattern as csp.py's `_INLINE_SCRIPT`, deliberately not an HTML parser.
    private val INLINE_SCRIPT = Regex(
        "<script(?![^>]*\\bsrc\\s*=)[^>]*>(.*?)</script>",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )

    /// `'sha256-…'` for every inline script in `html`.
    fun inlineScriptHashes(html: String): List<String> =
        INLINE_SCRIPT.findAll(html).map { m ->
            val digest = MessageDigest.getInstance("SHA-256")
                .digest(m.groupValues[1].toByteArray(Charsets.UTF_8))
            "'sha256-" + Base64.getEncoder().encodeToString(digest) + "'"
        }.toList()

    /// The policy for a document whose text is `html`, or the no-inline-script
    /// policy when there is none. Never throws.
    fun policyFor(html: String?): String {
        val hashes = if (html == null) emptyList() else inlineScriptHashes(html)
        val scriptSrc = if (hashes.isEmpty()) {
            "script-src 'self'"
        } else {
            "script-src 'self' " + hashes.joinToString(" ")
        }
        // Directive for directive, in csp.py's order, with its "; " join and no
        // trailing semicolon. script-src must never gain 'unsafe-inline' and
        // style-src must never gain a hash or a nonce; csp.py says why.
        return listOf(
            "default-src 'self'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "img-src 'self'",
            "connect-src 'self'",
            scriptSrc,
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
        ).joinToString("; ")
    }
}
