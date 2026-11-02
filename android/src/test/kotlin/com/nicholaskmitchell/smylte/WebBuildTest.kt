package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/// Staging, swapping and recovering the web build, on a real filesystem.
/// The property that matters throughout: whatever fails, a build that was
/// working stays in place.
class WebBuildTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var base: File
    private lateinit var build: WebBuild

    @Before
    fun setUp() {
        base = tmp.newFolder("files")
        build = WebBuild(base)
    }

    private fun zip(vararg entries: Pair<String, String>): File {
        val file = tmp.newFile()
        ZipOutputStream(FileOutputStream(file)).use { out ->
            for ((name, body) in entries) {
                out.putNextEntry(ZipEntry(name))
                out.write(body.toByteArray())
                out.closeEntry()
            }
        }
        return file
    }

    private val v1 = BuildIdentity(1, "2026-11-01T00:00:00Z")
    private val v2 = BuildIdentity(2, "2026-11-02T00:00:00Z")

    private fun index() = File(build.root, "index.html").readText()

    @Test
    fun a_first_build_stages_and_promotes() {
        assertFalse(build.haveLocal())
        build.stage(zip("index.html" to "one", "assets/" to "", "assets/a.js" to "a"), v1)
        assertEquals(v1, build.staged())
        assertFalse(build.haveLocal())
        assertEquals(v1, build.promote())
        assertTrue(build.haveLocal())
        assertEquals("one", index())
        assertEquals("a", File(build.root, "assets/a.js").readText())
        assertEquals(v1, build.installed())
        assertNull(build.staged())
    }

    @Test
    fun a_second_build_replaces_the_first_and_leaves_no_old_copy() {
        build.stage(zip("index.html" to "one", "stale.js" to "s"), v1)
        build.promote()
        build.stage(zip("index.html" to "two"), v2)
        assertEquals("one", index())   // staging never touches what is served
        assertEquals(v2, build.promote())
        assertEquals("two", index())
        assertFalse(File(build.root, "stale.js").exists())
        assertFalse(File(base, "web.old").exists())
        assertEquals(v2, build.installed())
    }

    @Test
    fun nothing_staged_promotes_nothing() {
        assertNull(build.promote())
    }

    @Test
    fun an_interrupted_swap_is_recovered() {
        // A process killed between the two moves in promote(): the working
        // copy is in web.old and there is no web at all.
        build.stage(zip("index.html" to "one"), v1)
        build.promote()
        assertTrue(build.root.renameTo(File(base, "web.old")))
        assertTrue(build.haveLocal())
        assertEquals("one", index())
    }

    @Test
    fun an_archive_that_climbs_out_is_refused_and_stages_nothing() {
        for (name in listOf("../evil.txt", "assets/../../evil.txt", "/abs/evil.txt")) {
            try {
                build.stage(zip("index.html" to "x", name to "pwned"), v1)
                if (name.startsWith("/")) {
                    // An absolute entry name is joined under the destination by
                    // java.io.File, so it lands inside, which is safe. Check it.
                    assertTrue(File(base, "web.next/abs/evil.txt").isFile)
                    continue
                }
                fail("$name was accepted")
            } catch (_: IOException) {
                assertNull(build.staged())
                assertFalse(File(base, "evil.txt").exists())
                assertFalse(File(base.parentFile, "evil.txt").exists())
            }
        }
    }

    @Test
    fun an_archive_without_an_index_is_refused() {
        try {
            build.stage(zip("assets/a.js" to "a"), v1)
            fail("accepted a build with no index.html")
        } catch (_: IOException) {
            assertNull(build.staged())
            assertFalse(File(base, "web.next").exists())
        }
    }

    @Test
    fun a_failed_stage_leaves_the_installed_build_alone() {
        build.stage(zip("index.html" to "one"), v1)
        build.promote()
        try {
            build.stage(zip("../evil" to "x"), v2)
            fail("accepted")
        } catch (_: IOException) {
        }
        assertEquals("one", index())
        assertEquals(v1, build.installed())
        assertNull(build.promote())
    }

    @Test
    fun the_size_and_count_bounds_hold() {
        val dest = File(base, "out")
        try {
            WebBuild.extract(zip("a" to "12345", "b" to "67890"), dest, maxBytes = 8)
            fail("accepted 10 bytes under a bound of 8")
        } catch (_: IOException) {
        }
        try {
            WebBuild.extract(zip("a" to "1", "b" to "2", "c" to "3"), File(base, "out2"), maxEntries = 2)
            fail("accepted 3 entries under a bound of 2")
        } catch (_: IOException) {
        }
    }

    @Test
    fun a_staged_build_can_be_discarded() {
        build.stage(zip("index.html" to "x"), v1)
        build.discardStaged()
        assertNull(build.staged())
    }

    @Test
    fun an_unreadable_identity_reads_as_none() {
        build.stage(zip("index.html" to "x"), v1)
        File(base, "web.next/.smylte-build").writeText("not a number\n")
        assertNull(build.staged())
    }
}
