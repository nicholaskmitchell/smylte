package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files

/// The request split and the traversal guard: the places in this client where a
/// mistake is a security bug rather than a cosmetic one. The resolver cases are
/// LocalServerTests' for the desktop's guard, run on a case-sensitive
/// filesystem, which is what Android has.
class AssetRoutesTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var base: File
    private lateinit var root: File

    @Before
    fun setUp() {
        base = tmp.newFolder("Smylte")
        root = File(base, "web").apply { mkdirs() }
        File(root, "index.html").writeText("<!doctype html>")
        File(root, "assets").mkdirs()
        File(root, "assets/app.js").writeText("1")
        File(root, ".smylte-build").writeText("1\nstamp\n")
        File(root, "assets/.hidden").writeText("x")
        File(base, "secret.txt").writeText("secret")
        File(base, "WEB").mkdirs()
        File(base, "WEB/secret.txt").writeText("secret")
        File(base, "webby").mkdirs()
        File(base, "webby/secret.txt").writeText("secret")
    }

    private fun resolve(path: String) = AssetRoutes.resolve(root, path)

    // ── the split ────────────────────────────────────────────────────────────

    @Test
    fun api_calls_go_to_the_network() {
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(true, "GET", "/api/me"))
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(true, "POST", "/api/login"))
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(true, "GET", "/api"))
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(true, "GET", "/api/events"))
    }

    @Test
    fun a_path_that_only_starts_with_api_is_a_file_route() {
        assertEquals(AssetRoutes.Kind.STATIC, AssetRoutes.classify(true, "GET", "/apiary"))
    }

    @Test
    fun another_origin_is_never_answered_from_disk() {
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(false, "GET", "/index.html"))
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(false, "GET", "/desktop/state"))
    }

    @Test
    fun the_desktop_bridge_is_absent_here_for_every_method() {
        assertEquals(AssetRoutes.Kind.NOT_FOUND, AssetRoutes.classify(true, "GET", "/desktop/state"))
        assertEquals(AssetRoutes.Kind.NOT_FOUND, AssetRoutes.classify(true, "POST", "/desktop/appearance"))
    }

    @Test
    fun a_write_to_a_page_route_is_not_answered_from_disk() {
        assertEquals(AssetRoutes.Kind.NETWORK, AssetRoutes.classify(true, "POST", "/oauth/authorize"))
        assertEquals(AssetRoutes.Kind.STATIC, AssetRoutes.classify(true, "get", "/book/abc"))
        assertEquals(AssetRoutes.Kind.STATIC, AssetRoutes.classify(true, "HEAD", "/"))
    }

    @Test
    fun same_origin_matches_scheme_host_and_port() {
        val o = "https://smylte.example.com"
        assertTrue(AssetRoutes.isSameOrigin(o, "https", "smylte.example.com", -1))
        assertTrue(AssetRoutes.isSameOrigin(o, "https", "smylte.example.com", 443))
        assertTrue(AssetRoutes.isSameOrigin(o, "HTTPS", "Smylte.Example.com", -1))
        assertFalse(AssetRoutes.isSameOrigin(o, "http", "smylte.example.com", -1))
        assertFalse(AssetRoutes.isSameOrigin(o, "https", "smylte.example.com", 8443))
        assertFalse(AssetRoutes.isSameOrigin(o, "https", "evil.example.com", -1))
        assertFalse(AssetRoutes.isSameOrigin(o, "https", "smylte.example.com.evil.net", -1))
        assertFalse(AssetRoutes.isSameOrigin(o, null, "smylte.example.com", -1))
        assertFalse(AssetRoutes.isSameOrigin(o, "https", null, -1))
        assertTrue(AssetRoutes.isSameOrigin("https://h:8443", "https", "h", 8443))
        assertFalse(AssetRoutes.isSameOrigin("https://h:8443", "https", "h", -1))
    }

    // ── the guard ────────────────────────────────────────────────────────────

    @Test
    fun the_root_is_the_index() {
        assertEquals(File(root, "index.html").canonicalFile, resolve("/"))
        assertEquals(File(root, "index.html").canonicalFile, resolve(""))
    }

    @Test
    fun a_real_file_resolves() {
        assertEquals(File(root, "assets/app.js").canonicalFile, resolve("/assets/app.js"))
    }

    @Test
    fun a_client_route_falls_through_to_the_spa() {
        assertNull(resolve("/book/abc"))
        assertNull(resolve("/assets/"))
        assertNull(resolve("/assets"))
    }

    @Test
    fun climbing_out_of_the_root_is_refused() {
        assertNull(resolve("/../secret.txt"))
        assertNull(resolve("/assets/../../secret.txt"))
        assertNull(resolve("/./../secret.txt"))
    }

    @Test
    fun a_differently_cased_sibling_is_refused() {
        // `…/Smylte/WEB` is a different directory on a case-sensitive
        // filesystem, and a case-insensitive prefix check would let it through.
        assertNull(resolve("/../WEB/secret.txt"))
    }

    @Test
    fun a_sibling_with_a_longer_name_is_refused() {
        assertNull(resolve("/../webby/secret.txt"))
    }

    @Test
    fun dot_segments_are_refused_even_inside_the_root() {
        assertNull(resolve("/assets/../index.html"))
        assertNull(resolve("/.smylte-build"))
        assertNull(resolve("/assets/.hidden"))
    }

    @Test
    fun a_nul_is_refused() {
        assertNull(resolve("/index.html\u0000.png"))
    }

    @Test
    fun a_leading_double_slash_stays_inside_the_root() {
        assertNull(resolve("//etc/passwd"))
        assertEquals(File(root, "assets/app.js").canonicalFile, resolve("//assets/app.js"))
    }

    @Test
    fun a_symlink_out_of_the_root_is_refused() {
        Files.createSymbolicLink(File(root, "link").toPath(), base.toPath())
        assertNull(resolve("/link/secret.txt"))
    }

    @Test
    fun mime_types_follow_the_desktop_table() {
        assertEquals(AssetRoutes.Mime("text/html", true), AssetRoutes.mimeFor(File("index.html")))
        assertEquals(AssetRoutes.Mime("text/javascript", true), AssetRoutes.mimeFor(File("a.JS")))
        assertEquals(AssetRoutes.Mime("font/woff2", false), AssetRoutes.mimeFor(File("f.woff2")))
        assertEquals(AssetRoutes.Mime("application/octet-stream", false), AssetRoutes.mimeFor(File("x.bin")))
    }
}
