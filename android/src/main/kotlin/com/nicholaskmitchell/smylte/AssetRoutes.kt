package com.nicholaskmitchell.smylte

import java.io.File
import java.io.IOException
import java.util.Locale

/// Which requests the client answers from disk, and with which file.
///
/// The desktop clients serve the app from a loopback HTTP server and proxy
/// `/api` to the real server. This client does the same split without a
/// server: the WebView loads the app at the REAL server's origin, and
/// `shouldInterceptRequest` answers the static files from the downloaded web
/// build, while `/api` is left to the WebView's own network stack. That keeps
/// the parts that matter exactly as a browser has them (the session cookie as
/// the server set it, same-origin API calls, the SSE stream) and opens no port
/// on the device, which on a phone any other app could connect to.
///
/// The split is LocalServer.HandleAsync's, kept identical on purpose, so the
/// web build cannot tell the hosts apart by which paths reach the server.
/// Kept free of android.* so the JVM unit tests run it as it ships.
object AssetRoutes {
    enum class Kind {
        /// Not ours to answer: another origin, an API call, or a method a
        /// file cannot answer. The WebView fetches it from the network.
        NETWORK,

        /// `/desktop/*`. This client has no desktop bridge, and answering 404
        /// is how the web build knows (desktop.ts `readState`), so the desktop
        /// settings never render here. Answered locally so it holds offline.
        NOT_FOUND,

        /// A file from the web build, or the SPA fallback.
        STATIC,
    }

    fun classify(sameOrigin: Boolean, method: String, path: String): Kind {
        if (!sameOrigin) return Kind.NETWORK
        if (path == "/api" || path.startsWith("/api/")) return Kind.NETWORK
        if (path.startsWith("/desktop/")) return Kind.NOT_FOUND
        val m = method.uppercase(Locale.ROOT)
        if (m != "GET" && m != "HEAD") return Kind.NETWORK
        return Kind.STATIC
    }

    /// Does a request's scheme, host and port name this origin? `port` is -1
    /// when the URL states none. The host comparison ignores case because DNS
    /// does; the origin was lowercased when it was saved (ServerAddress).
    fun isSameOrigin(origin: String, scheme: String?, host: String?, port: Int): Boolean {
        if (scheme == null || host == null) return false
        if (!scheme.equals("https", ignoreCase = true)) return false
        val effective = if (port == -1 || port == 443) "" else ":$port"
        return origin == "https://" + host.lowercase(Locale.ROOT) + effective
    }

    /// The file under `root` that the DECODED url path names, or null when it
    /// is not a regular file inside `root`, which the caller turns into the
    /// SPA fallback: `/book/<token>` and the tab routes are client-side.
    ///
    /// This guard is where a mistake would be a security bug rather than a
    /// cosmetic one, the same as LocalServer.Resolve, and it has the same
    /// shape: canonicalise, then require the result to sit strictly inside the
    /// canonical root. Two refusals are added here:
    ///
    ///   * a NUL anywhere, which java.io.File cannot represent; and
    ///   * any segment starting with a dot. That covers `.` and `..` outright
    ///     rather than only after canonicalisation, and it keeps
    ///     `.smylte-build` (WebBuild's record of where the build came from)
    ///     from being served. Vite emits no dotfiles.
    fun resolve(root: File, decodedPath: String): File? {
        var relative = decodedPath.trimStart('/')
        if (relative.isEmpty()) relative = "index.html"
        if (relative.indexOf('\u0000') >= 0) return null
        if (relative.split('/').any { it.startsWith(".") }) return null

        return try {
            val base = root.canonicalPath
            val full = File(root, relative).canonicalFile
            if (!full.path.startsWith(base + File.separator)) null
            else if (full.isFile) full else null
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        }
    }

    /// MIME type for a served file, and whether it is text (WebResourceResponse
    /// takes the charset separately). The same table as LocalServer's.
    data class Mime(val type: String, val text: Boolean)

    private val MIME = mapOf(
        "html" to Mime("text/html", true),
        "js" to Mime("text/javascript", true),
        "css" to Mime("text/css", true),
        "json" to Mime("application/json", true),
        "svg" to Mime("image/svg+xml", false),
        "png" to Mime("image/png", false),
        "ico" to Mime("image/x-icon", false),
        "woff2" to Mime("font/woff2", false),
        "woff" to Mime("font/woff", false),
        "txt" to Mime("text/plain", true),
        "map" to Mime("application/json", true),
        "webmanifest" to Mime("application/manifest+json", true),
    )

    fun mimeFor(file: File): Mime =
        MIME[file.extension.lowercase(Locale.ROOT)] ?: Mime("application/octet-stream", false)
}
