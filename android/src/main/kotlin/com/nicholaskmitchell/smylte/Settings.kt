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
    val origin: String
        get() = prefs.getString(ORIGIN, "") ?: ""

    val username: String
        get() = prefs.getString(USERNAME, "") ?: ""

    /// The password for the CURRENT server, or "" when none is stored or it
    /// cannot be unsealed. It is sealed for the address it was saved with
    /// (PasswordVault), so after the address changes it reads as "" until it
    /// is saved again. Either way the app's own sign-in screen takes over, so
    /// a lost key never locks anyone out.
    val password: String
        get() = PasswordVault.open(prefs.getString(PASSWORD, null), passwordPurpose(origin)) ?: ""

    val githubToken: String
        get() = PasswordVault.open(prefs.getString(TOKEN, null), TOKEN_PURPOSE) ?: ""

    /// Save what setup collected, in one write. Sealing happens first, so a
    /// keystore that refuses leaves the old settings exactly as they were;
    /// the exception is the caller's to report.
    fun save(origin: String, username: String, password: String, githubToken: String) {
        val sealedPassword = if (password.isEmpty()) null else PasswordVault.seal(password, passwordPurpose(origin))
        val token = githubToken.trim()
        val sealedToken = if (token.isEmpty()) null else PasswordVault.seal(token, TOKEN_PURPOSE)
        prefs.edit()
            .putString(ORIGIN, origin)
            .putString(USERNAME, username)
            .putString(PASSWORD, sealedPassword)
            .putString(TOKEN, sealedToken)
            .apply()
    }

    /// The ETag of the last release body fetched, for conditional checks
    /// (Updater.fetchAssets says what they do and do not save).
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

        const val TOKEN_PURPOSE = "github-token"
        fun passwordPurpose(origin: String) = "password for $origin"
    }
}
