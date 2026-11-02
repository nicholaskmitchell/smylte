package com.nicholaskmitchell.smylte

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/// A start that cannot open the app at all. The message is what the window shows.
class StartupFailure(message: String) : Exception(message)

/// Keeps the web build and the app itself in step with what CI published.
///
/// The same contract as desktop/Smylte.Desktop/Updater.cs: the client never
/// builds anything. CI runs the typecheck, the tests and `vite build` and
/// attaches the result to the rolling `desktop-latest` release; this reads
/// that release, unpacks the web build, and notices when the APK itself
/// changed.
///
/// Everything here blocks, and runs on Background.updates.
class Updater(private val context: Context, private val settings: Settings) {
    val web = WebBuild(context.filesDir)
    private val releaseCache = File(context.filesDir, "release.json")
    private val downloads = File(context.cacheDir, "updates")

    /// What the window needs after a check.
    data class Outcome(
        /// The published APK, when it is not the one installed.
        val clientUpdate: ReleaseAsset?,
        /// Whether a newer web build is unpacked and waiting for a reload.
        val webStaged: Boolean,
    )

    /// The start-up pass: check the release, fetch a newer web build if there
    /// is one, and swap it in before anything is loaded from disk.
    ///
    /// An installed build must always open. Only a first run, which has
    /// nothing to fall back to, fails here. The metadata check is bounded
    /// tightly when there is a build to fall back to, because a slow network
    /// should cost a moment rather than hold the app shut. Whatever this
    /// misses, the next check (MainActivity.onStart) catches.
    fun startUp(progress: (String) -> Unit): Outcome {
        val fallback = web.haveLocal() || web.staged() != null
        var assets: List<ReleaseAsset>? = null
        try {
            progress("Checking for updates…")
            assets = fetchAssets(if (fallback) GitHub.QUICK else GitHub.NORMAL)
        } catch (e: Exception) {
            if (!fallback) {
                throw StartupFailure(
                    "Could not reach GitHub to download the app, and there is no copy on this phone yet. " +
                        "Check the connection and try again. If this keeps happening, a GitHub token in " +
                        "Settings raises GitHub's rate limit. (${describe(e)})",
                )
            }
        }

        if (assets != null) {
            val webAsset = assets.find { it.name == Release.WEB_ASSET }
            if (webAsset == null && !fallback) {
                throw StartupFailure(
                    "The ${Release.TAG} release has no ${Release.WEB_ASSET}, and there is no copy on this phone yet.",
                )
            }
            if (webAsset != null) {
                try {
                    stageWeb(webAsset, progress)
                } catch (e: Exception) {
                    // An update is an improvement, not a precondition for
                    // opening the app (Updater.cs SwapOrKeepLocalAsync).
                    if (!fallback) throw StartupFailure("Could not download the app: ${describe(e)}")
                }
            }
        }

        try {
            web.promote()
        } catch (_: Exception) {
            // The installed build is still in place; promote rolled back.
        }
        if (!web.haveLocal()) throw StartupFailure("The app could not be unpacked on this phone.")
        return Outcome(assets?.let { outdatedClient(it) }, web.staged() != null)
    }

    /// The check made while the app is open. Stages a newer web build for the
    /// next reload but never swaps it in: the page is running from `web`.
    fun check(): Outcome {
        val assets = fetchAssets(GitHub.NORMAL)
        assets.find { it.name == Release.WEB_ASSET }?.let { stageWeb(it) {} }
        return Outcome(outdatedClient(assets), web.staged() != null)
    }

    /// The release's assets.
    ///
    /// Conditional on the last ETag: GitHub does not count a 304 against the
    /// anonymous limit of 60 an hour, which a phone on a carrier's shared
    /// address can otherwise run out of through no fault of its own.
    fun fetchAssets(timeouts: GitHub.Timeouts): List<ReleaseAsset> {
        val etag = settings.releaseEtag.takeIf { it.isNotEmpty() && releaseCache.isFile }
        val conn = GitHub.open(
            "${Release.API}/releases/tags/${Release.TAG}",
            settings.githubToken,
            "application/vnd.github+json",
            timeouts,
            etag,
        )
        try {
            val assets = when (val code = conn.responseCode) {
                304 -> try {
                    parseAssets(releaseCache.readText())
                } catch (e: IOException) {
                    // A cached body that cannot be read would otherwise be
                    // answered 304 forever. Forget it, so the next check
                    // fetches the release in full.
                    settings.releaseEtag = ""
                    releaseCache.delete()
                    throw e
                }
                in 200..299 -> {
                    val body = conn.inputStream.bufferedReader().use { it.readText() }
                    val parsed = parseAssets(body)   // parsed before it is cached
                    val partial = File(releaseCache.path + ".part")
                    partial.writeText(body)
                    if (!partial.renameTo(releaseCache)) throw IOException("Could not save the release.")
                    settings.releaseEtag = conn.getHeaderField("ETag") ?: ""
                    parsed
                }
                else -> throw IOException("GitHub answered $code.")
            }
            settings.lastCheck = System.currentTimeMillis()
            return assets
        } finally {
            conn.disconnect()
        }
    }

    /// Download and stage `asset` unless it is already installed or staged.
    fun stageWeb(asset: ReleaseAsset, progress: (String) -> Unit) {
        val remote = asset.identity
        if (remote == web.installed()) {
            web.discardStaged()   // anything staged is older than what runs
            return
        }
        if (!UpdatePolicy.needsDownload(remote, web.installed(), web.staged())) return

        val zip = File(downloads, "smylte-web-${asset.id}.zip")
        try {
            GitHub.downloadAsset(asset.id, settings.githubToken, zip, "Downloading the latest build…", progress)
            if (!UpdatePolicy.webBuildMatches(zip, asset.digest)) {
                throw IOException("The download did not match the digest the release publishes.")
            }
            progress("Installing…")
            web.stage(zip, remote)
        } finally {
            zip.delete()
        }
    }

    /// The published APK when it differs from the installed one, else null.
    fun outdatedClient(assets: List<ReleaseAsset>): ReleaseAsset? {
        val asset = assets.find { it.name == Release.CLIENT_ASSET } ?: return null
        return if (UpdatePolicy.isClientOutdated(asset.digest, installedDigest())) asset else null
    }

    /// The SHA-256 of the installed APK, which Android keeps byte for byte as it
    /// was installed. Null when it cannot be read.
    private fun installedDigest(): String? = try {
        UpdatePolicy.sha256(File(context.applicationInfo.sourceDir))
    } catch (_: Exception) {
        null
    }

    /// Download the published APK and check it every way that can be checked
    /// here, so that what reaches the installer is the file CI signed and
    /// one Android will accept. Throws with a sentence for the strip.
    ///
    /// The digest is required, not optional as it is for the web build: an
    /// unverifiable app is not handed to the installer. Android itself then
    /// refuses anything not signed with this app's key; the signer and
    /// version checks below only turn that refusal into a sentence someone can
    /// act on, before the installer has opened.
    fun downloadClient(asset: ReleaseAsset, progress: (String) -> Unit): File {
        val digest = UpdatePolicy.publishedDigest(asset.digest)
            ?: throw IOException("The release states no digest for the app, so a download could not be checked.")
        val apk = ApkProvider.file(context)
        apk.delete()
        try {
            GitHub.downloadAsset(asset.id, settings.githubToken, apk, "Downloading the new app…", progress)
            if (UpdatePolicy.sha256(apk) != digest) {
                throw IOException("The downloaded app did not match the digest the release publishes; nothing was changed.")
            }
            checkArchive(apk)
            return apk
        } catch (e: Exception) {
            apk.delete()
            throw e
        }
    }

    @Suppress("DEPRECATION")   // the int-flag overloads are the ones API 30 has
    private fun checkArchive(apk: File) {
        val pm = context.packageManager
        val flags = PackageManager.GET_SIGNING_CERTIFICATES
        val archive = pm.getPackageArchiveInfo(apk.path, flags)
            ?: throw IOException("The downloaded file is not an Android app.")
        if (archive.packageName != context.packageName) throw IOException("The downloaded app is not Smylte.")

        val installed = pm.getPackageInfo(context.packageName, flags)
        if (archive.longVersionCode < installed.longVersionCode) {
            throw IOException(
                "The published app is older than this one, so Android would refuse it. " +
                    "This copy was probably built locally.",
            )
        }

        val ours = currentSigners(installed)
        val theirs = acceptedSigners(archive)
        if (ours != null && theirs != null && !theirs.containsAll(ours)) {
            throw IOException(
                "The published app is signed with a different key from this one, so Android would refuse " +
                    "to update it. Uninstall Smylte and install it again from the release page.",
            )
        }
    }

    private fun currentSigners(info: PackageInfo): Set<String>? =
        info.signingInfo?.apkContentsSigners?.let(::digests)

    /// The new APK's signers, plus the keys it proves it rotated from: an APK
    /// that rotated its key is still a valid update for the old one.
    private fun acceptedSigners(info: PackageInfo): Set<String>? {
        val signing = info.signingInfo ?: return null
        val current = signing.apkContentsSigners?.let(::digests) ?: return null
        val past = if (signing.hasMultipleSigners()) emptySet()
        else signing.signingCertificateHistory?.let(::digests) ?: emptySet()
        return current + past
    }

    private fun digests(signatures: Array<Signature>): Set<String> = signatures.map {
        MessageDigest.getInstance("SHA-256").digest(it.toByteArray()).joinToString("") { b -> "%02x".format(b) }
    }.toSet()

    companion object {
        fun parseAssets(body: String): List<ReleaseAsset> = try {
            val array = JSONObject(body).optJSONArray("assets")
            if (array == null) {
                emptyList()
            } else {
                (0 until array.length()).map { i ->
                    val a = array.getJSONObject(i)
                    ReleaseAsset(
                        id = a.getLong("id"),
                        name = a.getString("name"),
                        updatedAt = a.optString("updated_at", ""),
                        digest = if (a.has("digest") && !a.isNull("digest")) a.getString("digest") else null,
                    )
                }
            }
        } catch (e: JSONException) {
            throw IOException("GitHub's answer could not be read.", e)
        }

        fun describe(e: Throwable): String = e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
    }
}
