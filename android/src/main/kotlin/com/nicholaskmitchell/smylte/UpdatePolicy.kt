package com.nicholaskmitchell.smylte

import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest
import java.util.Locale

/// The update DECISIONS, kept apart from the I/O that feeds them so the JVM
/// tests can pin each one. Mirrors Updater.cs wherever the question is the same.
object UpdatePolicy {
    /// "sha256:<hex>" as the release states it, or null when it states none or
    /// states something else.
    fun publishedDigest(raw: String?): String? {
        if (raw == null || raw.length <= 7) return null
        if (!raw.startsWith("sha256:", ignoreCase = true)) return null
        val hex = raw.substring(7)
        if (hex.length != 64 || !hex.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) return null
        return "sha256:" + hex.lowercase(Locale.ROOT)
    }

    /// Is the published APK a different file from the installed one?
    ///
    /// Compared by content hash, as the desktop clients compare theirs: a
    /// version number has to be remembered, and a digest cannot be forgotten.
    /// CI re-publishes the APK only when android/ changed, so a different
    /// digest means a different app.
    ///
    /// Every uncertain answer is false. No digest, or an installed APK that
    /// could not be read, is not evidence of being out of date, and a false
    /// alarm sends someone through the installer for nothing.
    fun isClientOutdated(published: String?, local: String?): Boolean {
        val p = publishedDigest(published) ?: return false
        val l = publishedDigest(local) ?: return false
        return p != l
    }

    /// Does `remote` need downloading? Not when it is already what is installed
    /// or what is staged; a build staged earlier is promoted on the next start
    /// without being fetched again.
    fun needsDownload(remote: BuildIdentity, installed: BuildIdentity?, staged: BuildIdentity?): Boolean =
        remote != installed && remote != staged

    /// Does a web-build download match the digest the release published for it?
    ///
    /// When the release states no SHA-256 the build is accepted on TLS alone,
    /// as the desktop clients accept every web build. Refusing instead would
    /// turn a change in how GitHub reports digests into a first install that
    /// cannot complete. The APK is never accepted that way: Updater refuses an
    /// APK without a digest before it downloads anything.
    fun webBuildMatches(file: File, published: String?): Boolean {
        val expected = publishedDigest(published) ?: return true
        return sha256(file) == expected
    }

    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return "sha256:" + digest.digest().joinToString("") { "%02x".format(it) }
    }

    /// "Downloading… 1.2 of 3.4 MB". One decimal, because the APK is a fraction
    /// of a megabyte and "0 of 1 MB" reads as stuck.
    fun progressText(what: String, done: Long, total: Long): String {
        fun mb(n: Long) = String.format(Locale.ROOT, "%.1f", n / 1_048_576.0)
        return if (total > 0) "$what ${mb(done)} of ${mb(total)} MB" else "$what ${mb(done)} MB"
    }
}
