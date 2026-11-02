package com.nicholaskmitchell.smylte

import android.webkit.CookieManager
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/// Talking to the server directly, outside the WebView: checking an address in
/// setup, and signing in with the stored credentials before the first page
/// load (Session.cs on the desktop).
///
/// Simpler than the desktop's, because nothing is re-scoped. The page runs at
/// the server's own origin, so the Set-Cookie the server sends is handed to the
/// WebView's cookie store exactly as sent, attributes and all.
object Session {
    private const val COOKIE = "smylte_session"

    private fun connect(
        origin: String,
        path: String,
        method: String = "GET",
        connectMs: Int = 8_000,
        readMs: Int = 15_000,
    ): HttpURLConnection {
        val conn = URL("$origin$path").openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.instanceFollowRedirects = false
        conn.useCaches = false
        conn.connectTimeout = connectMs
        conn.readTimeout = readMs
        return conn
    }

    /// Is there a Smylte server at `origin`? The message is what setup shows.
    fun probe(origin: String): Pair<Boolean, String> = try {
        val conn = connect(origin, "/api/me")
        try {
            val code = conn.responseCode
            when {
                // Unauthenticated is a perfectly good answer: something is
                // listening, and it is the app rather than a proxy.
                code == 401 -> true to "Found it."
                code !in 200..299 -> false to "The server answered $code."
                JSONObject(conn.inputStream.bufferedReader().readText()).has("authenticated") ->
                    true to "Found it."
                else -> false to "Something answered, but it does not look like Smylte."
            }
        } finally {
            conn.disconnect()
        }
    } catch (_: JSONException) {
        false to "Something answered, but it does not look like Smylte."
    } catch (e: IOException) {
        false to "Could not reach it: ${e.message ?: e.javaClass.simpleName}"
    } catch (e: Exception) {
        false to "Could not check it: ${e.message ?: e.javaClass.simpleName}"
    }

    /// Make sure the WebView holds a live session, signing in with the stored
    /// credentials if it does not. Every failure is silent: the app's own
    /// sign-in screen is the fallback, and a wrong stored password must not
    /// stop the app opening.
    ///
    /// The existing session is checked first. The desktop signs in on every
    /// launch, which on a phone, where Android ends the process whenever it
    /// likes, would mean a fresh scrypt on the server for most openings.
    ///
    /// Nothing at all happens without stored credentials: there would be
    /// nothing to do with the answer, and this runs before the app opens.
    /// With them, the waits are short for the same reason; a server that is
    /// unreachable from here is the page's to report, not the splash's.
    fun ensureSignedIn(origin: String, username: String, password: String) {
        if (username.isEmpty() || password.isEmpty()) return
        val cookies = CookieManager.getInstance()
        try {
            val held = cookies.getCookie(origin)
            if (held != null && held.split(';').any { it.trim().startsWith("$COOKIE=") }) {
                val conn = connect(origin, "/api/me", connectMs = 4_000, readMs = 6_000)
                try {
                    conn.setRequestProperty("Cookie", held)
                    if (conn.responseCode in 200..299) return
                } finally {
                    conn.disconnect()
                }
            }
            val conn = connect(origin, "/api/login", "POST", connectMs = 4_000, readMs = 10_000)
            try {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                val body = JSONObject().put("username", username).put("password", password).toString()
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                if (conn.responseCode !in 200..299) return
                val set = conn.headerFields.entries
                    .filter { (name, _) -> name != null && name.equals("Set-Cookie", ignoreCase = true) }
                    .flatMap { it.value }
                for (value in set) cookies.setCookie(origin, value)
                cookies.flush()
            } finally {
                conn.disconnect()
            }
        } catch (_: Exception) {
            // Offline, refused, or a cookie store that would not take it: the
            // page's own sign-in handles every one of them. Caught broadly
            // because this runs on the update thread, where anything uncaught
            // ends the process.
        }
    }
}
