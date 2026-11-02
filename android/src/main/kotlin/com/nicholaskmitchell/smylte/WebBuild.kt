package com.nicholaskmitchell.smylte

import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.zip.ZipInputStream

/// The downloaded web build on disk, and the only code that changes it.
///
///     web/        the build being served
///     web.next/   a complete build waiting to be swapped in
///     web.old/    the previous build, for the moment a swap is in flight
///
/// The desktop updater downloads and swaps in one step, because it runs before
/// its window exists. This client also checks while the app is open (after a
/// long time in the background), and a build must never be swapped out from
/// under a page that is running from it. So the two steps are apart: `stage`
/// unpacks into web.next whenever a check finds something new, and `promote`
/// swaps it in only at a moment nothing is loaded from `web`: at start-up, or
/// when the user asks to reload.
///
/// Each build carries its own record of the upload it came from
/// (`.smylte-build`), so the identity moves with the directory in the same
/// rename and there is no second copy in settings to disagree with it.
/// AssetRoutes never serves a dot-file.
///
/// Free of android.*, so the JVM unit tests exercise it on a real filesystem.
class WebBuild(base: File) {
    val root = File(base, "web")
    private val next = File(base, "web.next")
    private val previous = File(base, "web.old")

    /// Put back a build stranded by an interrupted swap, then say whether a
    /// usable build is on disk. Recovery first, because every "can the app
    /// open?" decision reads this answer (Updater.cs HaveLocalBuild).
    fun haveLocal(): Boolean {
        recoverStranded()
        return File(root, "index.html").isFile
    }

    /// `promote` moves `web` aside and then `web.next` into place. A process
    /// killed between the two leaves the only working copy in web.old; one
    /// killed after both leaves a web.old nothing needs.
    fun recoverStranded() {
        if (!previous.exists()) return
        if (root.exists()) {
            previous.deleteRecursively()
            return
        }
        try {
            move(previous, root)
        } catch (_: IOException) {
            // Best effort; a fresh download still follows.
        }
    }

    fun installed(): BuildIdentity? = readIdentity(root)

    /// The staged build's identity, or null when nothing complete is staged.
    fun staged(): BuildIdentity? =
        if (File(next, "index.html").isFile) readIdentity(next) else null

    /// Unpack `zip` into web.next as the build `identity` names, replacing
    /// whatever was staged. Throws, leaving nothing staged, when the archive is
    /// unsafe, oversized, or not a web build. `web` is not touched.
    fun stage(zip: File, identity: BuildIdentity) {
        next.deleteRecursively()
        try {
            extract(zip, next)
            if (!File(next, "index.html").isFile) {
                throw IOException("The downloaded build has no index.html.")
            }
            writeIdentity(next, identity)
        } catch (e: Exception) {
            next.deleteRecursively()
            throw e
        }
    }

    /// Swap the staged build in. Returns its identity, or null when there was
    /// nothing to promote. Only call this while nothing is loaded from `web`.
    ///
    /// The old copy is moved aside rather than deleted first, so a failure
    /// between the two moves still leaves a working build to roll back to.
    fun promote(): BuildIdentity? {
        val identity = staged() ?: return null
        recoverStranded()
        previous.deleteRecursively()
        if (root.exists()) move(root, previous)
        try {
            move(next, root)
        } catch (e: IOException) {
            if (!root.exists() && previous.isDirectory) move(previous, root)
            throw e
        }
        previous.deleteRecursively()
        return identity
    }

    /// Drop a staged build, e.g. one the installed build has already caught up
    /// with.
    fun discardStaged() {
        next.deleteRecursively()
    }

    private fun move(from: File, to: File) {
        Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE)
    }

    companion object {
        private const val IDENTITY_FILE = ".smylte-build"

        /// Bounds on what one archive may unpack to. The real build is a few
        /// megabytes in a few hundred files; these exist so a corrupt or hostile
        /// archive fails rather than filling the phone.
        const val MAX_BYTES = 256L * 1024 * 1024
        const val MAX_ENTRIES = 20_000

        fun readIdentity(dir: File): BuildIdentity? = try {
            val lines = File(dir, IDENTITY_FILE).readLines()
            val id = lines.getOrNull(0)?.toLongOrNull()
            val stamp = lines.getOrNull(1)
            if (id != null && stamp != null) BuildIdentity(id, stamp) else null
        } catch (_: IOException) {
            null
        }

        private fun writeIdentity(dir: File, identity: BuildIdentity) {
            File(dir, IDENTITY_FILE).writeText("${identity.id}\n${identity.updatedAt}\n")
        }

        /// Unpack `zip` into `dest`, refusing any entry that would land outside
        /// it ("zip slip"). Android 14 refuses `..` entries itself for apps
        /// targeting it; this check does not rely on that.
        fun extract(zip: File, dest: File, maxBytes: Long = MAX_BYTES, maxEntries: Int = MAX_ENTRIES) {
            if (!dest.mkdirs() && !dest.isDirectory) throw IOException("Could not create $dest.")
            val destPath = dest.canonicalPath
            val base = destPath + File.separator
            var total = 0L
            var entries = 0
            ZipInputStream(BufferedInputStream(FileInputStream(zip))).use { zin ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val entry = zin.nextEntry ?: break
                    if (++entries > maxEntries) throw IOException("The build archive has too many files.")
                    val target = File(dest, entry.name).canonicalFile
                    if (!target.path.startsWith(base)) {
                        // A "./" directory entry names `dest` itself: harmless.
                        if (entry.isDirectory && target.path == destPath) continue
                        throw IOException("The build archive has an unsafe path: ${entry.name}")
                    }
                    if (entry.isDirectory) {
                        if (!target.mkdirs() && !target.isDirectory) throw IOException("Could not create $target.")
                        continue
                    }
                    val parent = target.parentFile ?: throw IOException("No parent for $target.")
                    if (!parent.mkdirs() && !parent.isDirectory) throw IOException("Could not create $parent.")
                    FileOutputStream(target).use { out ->
                        while (true) {
                            val n = zin.read(buffer)
                            if (n < 0) break
                            total += n
                            if (total > maxBytes) throw IOException("The build archive is too large.")
                            out.write(buffer, 0, n)
                        }
                    }
                }
            }
        }
    }
}
