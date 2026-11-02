package com.nicholaskmitchell.smylte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class UpdatePolicyTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val a = "sha256:" + "a".repeat(64)
    private val b = "sha256:" + "b".repeat(64)

    @Test
    fun a_digest_is_read_only_when_it_is_a_sha256() {
        assertEquals(a, UpdatePolicy.publishedDigest(a))
        assertEquals(a, UpdatePolicy.publishedDigest("SHA256:" + "A".repeat(64)))
        assertNull(UpdatePolicy.publishedDigest(null))
        assertNull(UpdatePolicy.publishedDigest(""))
        assertNull(UpdatePolicy.publishedDigest("sha256:"))
        assertNull(UpdatePolicy.publishedDigest("sha256:abc"))
        assertNull(UpdatePolicy.publishedDigest("sha512:" + "a".repeat(128)))
        assertNull(UpdatePolicy.publishedDigest("sha256:" + "g".repeat(64)))
    }

    @Test
    fun only_two_known_different_digests_mean_out_of_date() {
        assertTrue(UpdatePolicy.isClientOutdated(a, b))
        assertFalse(UpdatePolicy.isClientOutdated(a, a))
        assertFalse(UpdatePolicy.isClientOutdated(a, a.uppercase().replace("SHA256", "sha256")))
        assertFalse(UpdatePolicy.isClientOutdated(null, b))
        assertFalse(UpdatePolicy.isClientOutdated(a, null))
        assertFalse(UpdatePolicy.isClientOutdated("garbage", b))
    }

    @Test
    fun a_build_already_installed_or_staged_is_not_fetched_again() {
        val v1 = BuildIdentity(1, "t1")
        val v2 = BuildIdentity(2, "t2")
        assertFalse(UpdatePolicy.needsDownload(v1, installed = v1, staged = null))
        assertFalse(UpdatePolicy.needsDownload(v2, installed = v1, staged = v2))
        assertTrue(UpdatePolicy.needsDownload(v2, installed = v1, staged = null))
        assertTrue(UpdatePolicy.needsDownload(v1, installed = null, staged = null))
        // Same id, re-uploaded with --clobber: a new build.
        assertTrue(UpdatePolicy.needsDownload(BuildIdentity(1, "t9"), installed = v1, staged = null))
    }

    @Test
    fun a_web_build_is_checked_against_its_digest_when_there_is_one() {
        val file = tmp.newFile().apply { writeText("abc") }
        val right = "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assertEquals(right, UpdatePolicy.sha256(file))
        assertTrue(UpdatePolicy.webBuildMatches(file, right))
        assertTrue(UpdatePolicy.webBuildMatches(file, right.uppercase().replace("SHA256", "sha256")))
        assertFalse(UpdatePolicy.webBuildMatches(file, a))
        // No digest, or one this client cannot read: TLS alone, as on desktop.
        assertTrue(UpdatePolicy.webBuildMatches(file, null))
        assertTrue(UpdatePolicy.webBuildMatches(file, "sha512:abc"))
    }

    @Test
    fun progress_reads_in_tenths_of_a_megabyte() {
        assertEquals("Downloading 0.2 of 0.5 MB", UpdatePolicy.progressText("Downloading", 209_715, 524_288))
        assertEquals("Downloading 1.0 MB", UpdatePolicy.progressText("Downloading", 1_048_576, -1))
    }
}
