package com.nicholaskmitchell.smylte

import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.io.InputStream

/// Answers the WebView's requests for the app's own files from the web build
/// on disk. The routing decisions are AssetRoutes'; this turns them into
/// responses. Called on the WebView's IO threads.
class LocalAssets(private val root: File, private val origin: String) {
    /// The policy of the document most recently served, attached to every
    /// other response too, as CSPMiddleware does on the server: one header on
    /// an asset costs nothing and leaves no path that escapes the policy.
    @Volatile
    private var policy = Csp.policyFor(null)

    fun answer(request: WebResourceRequest): WebResourceResponse? {
        val url = request.url
        val same = AssetRoutes.isSameOrigin(origin, url.scheme, url.host, url.port)
        val path = url.path?.takeIf { it.isNotEmpty() } ?: "/"
        return when (AssetRoutes.classify(same, request.method ?: "GET", path)) {
            AssetRoutes.Kind.NETWORK -> null
            AssetRoutes.Kind.NOT_FOUND -> respond(404, "Not Found", JSON, ByteArrayInputStream(EMPTY_JSON), "no-store")
            AssetRoutes.Kind.STATIC -> serve(path)
        }
    }

    private fun serve(path: String): WebResourceResponse {
        val index = File(root, "index.html")
        val file = AssetRoutes.resolve(root, path) ?: index
        if (!file.isFile) return respond(404, "Not Found", TEXT, ByteArrayInputStream(ByteArray(0)), "no-store")
        val mime = AssetRoutes.mimeFor(file)
        return try {
            if (mime.type == "text/html") {
                // The policy is derived from the bytes this response carries,
                // so the hash always matches the script the page runs, even
                // across a build swap between two loads.
                val bytes = file.readBytes()
                policy = Csp.policyFor(String(bytes, Charsets.UTF_8))
                // Re-read on every load, or an updated build would keep
                // pointing at the previous bundle.
                respond(200, "OK", mime, ByteArrayInputStream(bytes), "no-cache")
            } else {
                // Content-hashed by Vite, or carrying a ?v= query.
                respond(200, "OK", mime, FileInputStream(file), "public, max-age=31536000, immutable")
            }
        } catch (_: IOException) {
            // Not a silent fall through to the network: that would mix files
            // from two different builds into one page.
            respond(500, "Internal Server Error", TEXT, ByteArrayInputStream(ByteArray(0)), "no-store")
        }
    }

    private fun respond(
        status: Int,
        reason: String,
        mime: AssetRoutes.Mime,
        body: InputStream,
        cacheControl: String,
    ): WebResourceResponse = WebResourceResponse(
        mime.type,
        if (mime.text) "utf-8" else null,
        status,
        reason,
        mapOf(
            "Content-Security-Policy" to policy,
            "X-Content-Type-Options" to "nosniff",
            "Cache-Control" to cacheControl,
        ),
        body,
    )

    private companion object {
        val JSON = AssetRoutes.Mime("application/json", true)
        val TEXT = AssetRoutes.Mime("text/plain", true)
        val EMPTY_JSON = "{}".toByteArray()
    }
}

/// The one thing the page can tell this host: its background colour, from the
/// watcher ThemeColour.WATCH_SCRIPT installs. Called on a WebView thread.
///
/// Exposed as `window.SmylteAndroid`. It takes a colour string and does
/// nothing else, so anything that can call it can at worst repaint the bars.
class ThemeBridge(private val onColour: (Int) -> Unit) {
    @JavascriptInterface
    fun themeColour(hex: String?) {
        ThemeColour.parse(hex)?.let(onColour)
    }
}
