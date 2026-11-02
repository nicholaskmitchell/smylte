package com.nicholaskmitchell.smylte

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

/// The server address typed into setup, reduced to the one thing the client
/// uses: an https ORIGIN.
///
/// The Android client loads the app at the server's own origin and serves its
/// files from disk (AssetRoutes), so every API call is an ordinary same-origin
/// request and the session cookie is the server's, unmodified. That only works
/// at the origin's root, because the app asks for `/api/…` and `/assets/…` by
/// absolute path, so a path in the address is refused rather than ignored.
///
/// https only. The server sets its session cookie `Secure` by default
/// (SMYLTE_COOKIE_SECURE), so over plain http the sign-in would never stick.
/// Android also refuses cleartext unless the manifest opts in, and this one
/// does not.
object ServerAddress {
    sealed interface Parsed {
        data class Ok(val origin: String) : Parsed
        data class Bad(val message: String) : Parsed
    }

    fun parse(input: String): Parsed {
        var text = input.trim()
        if (text.isEmpty()) return Parsed.Bad("Enter the address you open Smylte at in a browser.")
        if (!text.contains("://")) text = "https://$text"

        val uri = try {
            URI(text)
        } catch (_: URISyntaxException) {
            return Parsed.Bad("That is not a valid web address.")
        }

        val scheme = uri.scheme?.lowercase(Locale.ROOT)
        if (scheme == "http") {
            return Parsed.Bad("Use https://. Smylte's sign-in cookie is only sent over https.")
        }
        if (scheme != "https") return Parsed.Bad("That is not an https:// address.")

        val host = uri.host?.lowercase(Locale.ROOT)
        if (host.isNullOrEmpty()) return Parsed.Bad("That address has no host name.")
        if (uri.rawUserInfo != null) return Parsed.Bad("Leave the user name out of the address.")

        val path = uri.rawPath ?: ""
        if ((path.isNotEmpty() && path != "/") || uri.rawQuery != null || uri.rawFragment != null) {
            return Parsed.Bad(
                "Use the server's address without a path: Smylte runs at the root of its domain."
            )
        }

        // 443 is the default and is dropped, so the origin compares equal to the
        // one the WebView reports for the same server.
        val port = uri.port
        if (port == 0 || port > 65535) return Parsed.Bad("That port is not valid.")
        val origin = if (port == -1 || port == 443) "https://$host" else "https://$host:$port"
        return Parsed.Ok(origin)
    }
}
