package com.nicholaskmitchell.smylte

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/// The few GitHub requests the updater makes.
///
/// Redirects are followed by hand. A release asset is served from a redirect to
/// a CDN host, and the optional token must reach api.github.com and nothing
/// else, so it is attached per hop, only to that host, and a redirect off https
/// is refused rather than followed.
object GitHub {
    private const val API_HOST = "api.github.com"
    private const val MAX_REDIRECTS = 5

    class Timeouts(val connectMs: Int, val readMs: Int)

    /// Short, for the check that runs before an installed build opens: a slow
    /// network should cost a moment, not hold the app shut.
    val QUICK = Timeouts(4_000, 8_000)
    val NORMAL = Timeouts(15_000, 30_000)

    /// Open `url` and return the connection with its status read. The caller
    /// disconnects it.
    ///
    /// A token api.github.com answers 401 to (expired, revoked, mistyped) is
    /// reported through `onTokenRejected` and the request is made again
    /// without it. Without that, a stale token would quietly stop every
    /// update while the app kept opening on its old build.
    fun open(
        url: String,
        token: String?,
        accept: String,
        timeouts: Timeouts,
        ifNoneMatch: String? = null,
        onTokenRejected: (() -> Unit)? = null,
    ): HttpURLConnection {
        val conn = openOnce(url, token, accept, timeouts, ifNoneMatch)
        if (conn.responseCode != 401 || token.isNullOrBlank()) return conn
        conn.disconnect()
        onTokenRejected?.invoke()
        return openOnce(url, null, accept, timeouts, ifNoneMatch)
    }

    /// Does api.github.com accept `token`? True or false when it answered,
    /// null when it could not be asked. /rate_limit costs no quota.
    fun tokenAccepted(token: String): Boolean? = try {
        val conn = openOnce("https://$API_HOST/rate_limit", token, "application/vnd.github+json", QUICK, null)
        try {
            when (conn.responseCode) {
                in 200..299 -> true
                401 -> false
                else -> null
            }
        } finally {
            conn.disconnect()
        }
    } catch (_: IOException) {
        null
    }

    private fun openOnce(
        url: String,
        token: String?,
        accept: String,
        timeouts: Timeouts,
        ifNoneMatch: String?,
    ): HttpURLConnection {
        var target = URL(url)
        var hops = 0
        while (true) {
            if (target.protocol != "https") throw IOException("Refused a redirect to ${target.protocol}.")
            val conn = target.openConnection() as HttpURLConnection
            conn.instanceFollowRedirects = false
            conn.connectTimeout = timeouts.connectMs
            conn.readTimeout = timeouts.readMs
            conn.useCaches = false
            // GitHub rejects requests without a User-Agent outright.
            conn.setRequestProperty("User-Agent", "Smylte-Android/1.0")
            conn.setRequestProperty("Accept", accept)
            if (!token.isNullOrBlank() && target.host.equals(API_HOST, ignoreCase = true)) {
                conn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
            }
            if (ifNoneMatch != null && hops == 0) conn.setRequestProperty("If-None-Match", ifNoneMatch)

            val code = try {
                conn.responseCode
            } catch (e: IOException) {
                conn.disconnect()
                throw e
            }
            if (code in 300..399 && code != 304) {
                val location = conn.getHeaderField("Location")
                conn.disconnect()
                if (location.isNullOrEmpty()) throw IOException("GitHub redirected without a location.")
                if (++hops > MAX_REDIRECTS) throw IOException("Too many redirects from GitHub.")
                target = URL(target, location)
                continue
            }
            return conn
        }
    }

    /// The most any one download may be. The web build is a few megabytes and
    /// the APK a fraction of one; this exists so a wrong or hostile asset
    /// fails rather than filling the phone.
    const val MAX_DOWNLOAD = 128L * 1024 * 1024

    /// Download release asset `assetId` to `dest`, reporting progress. Throws
    /// on any failure; `dest` may then hold a partial file.
    fun downloadAsset(
        assetId: Long,
        token: String?,
        dest: File,
        what: String,
        progress: (String) -> Unit,
        onTokenRejected: (() -> Unit)? = null,
    ) {
        // The asset endpoint, not browser_download_url: it works unchanged
        // whether the repository is public or private.
        val conn = open(
            "${Release.API}/releases/assets/$assetId", token, "application/octet-stream", NORMAL,
            onTokenRejected = onTokenRejected,
        )
        try {
            if (conn.responseCode !in 200..299) throw IOException("GitHub answered ${conn.responseCode}.")
            val total = conn.contentLengthLong
            if (total > MAX_DOWNLOAD) throw IOException("The download is too large ($total bytes).")
            dest.parentFile?.mkdirs()
            conn.inputStream.use { input ->
                FileOutputStream(dest).use { out ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    var shown = 0L
                    progress(UpdatePolicy.progressText(what, 0, total))
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        done += n
                        if (done > MAX_DOWNLOAD) throw IOException("The download is too large.")
                        out.write(buffer, 0, n)
                        if (done - shown >= 256 * 1024) {
                            shown = done
                            progress(UpdatePolicy.progressText(what, done, total))
                        }
                    }
                    if (total > 0 && done != total) throw IOException("The download was cut short.")
                }
            }
        } finally {
            conn.disconnect()
        }
    }
}
