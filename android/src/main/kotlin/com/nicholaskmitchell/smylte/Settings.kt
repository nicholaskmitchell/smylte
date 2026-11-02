package com.nicholaskmitchell.smylte

import android.content.Context
import android.content.SharedPreferences

/// What the client remembers, in the app's private SharedPreferences.
///
/// The password and the GitHub token are sealed by PasswordVault; everything
/// else is plain, as on the desktop. Nothing here is backed up (see the
/// manifest).
class Settings(context: Context) {
    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences("smylte", Context.MODE_PRIVATE)

    /// The server's https origin, "" until setup has run.
    var origin: String
        get() = prefs.getString(ORIGIN, "") ?: ""
        set(v) = prefs.edit().putString(ORIGIN, v).apply()

    var username: String
        get() = prefs.getString(USERNAME, "") ?: ""
        set(v) = prefs.edit().putString(USERNAME, v).apply()

    /// The password, or "" when none is stored or it cannot be unsealed (a
    /// keystore reset, say). Either way the app's own sign-in screen takes
    /// over, so a lost key never locks anyone out.
    var password: String
        get() = PasswordVault.open(prefs.getString(PASSWORD, null)) ?: ""
        set(v) = prefs.edit().putString(PASSWORD, if (v.isEmpty()) null else PasswordVault.seal(v)).apply()

    var githubToken: String
        get() = PasswordVault.open(prefs.getString(TOKEN, null)) ?: ""
        set(v) = prefs.edit().putString(TOKEN, if (v.isBlank()) null else PasswordVault.seal(v.trim())).apply()

    /// The ETag of the last release body fetched. GitHub does not count a 304
    /// against the rate limit, which matters on a shared mobile address.
    var releaseEtag: String
        get() = prefs.getString(RELEASE_ETAG, "") ?: ""
        set(v) = prefs.edit().putString(RELEASE_ETAG, v).apply()

    /// When the release was last read successfully, in epoch milliseconds.
    var lastCheck: Long
        get() = prefs.getLong(LAST_CHECK, 0L)
        set(v) = prefs.edit().putLong(LAST_CHECK, v).apply()

    /// The last background the page reported, so the next start paints the
    /// bars in it before the page has loaded. 0 when none is known.
    var themeColour: Int
        get() = prefs.getInt(THEME_COLOUR, 0)
        set(v) = prefs.edit().putInt(THEME_COLOUR, v).apply()

    val configured: Boolean get() = origin.isNotEmpty()

    private companion object {
        const val ORIGIN = "origin"
        const val USERNAME = "username"
        const val PASSWORD = "password"
        const val TOKEN = "github_token"
        const val RELEASE_ETAG = "release_etag"
        const val LAST_CHECK = "last_check"
        const val THEME_COLOUR = "theme_colour"
    }
}
