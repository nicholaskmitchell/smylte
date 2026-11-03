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
    /// cannot be unsealed. Either way the app's own sign-in screen takes over,
    /// so a lost key never locks anyone out.
    val password: String
        get() = passwordFor(origin)

    /// The password, unsealed for `origin`: "" unless it was saved for exactly
    /// that address. Anything about to SEND the password must ask for it this
    /// way, naming where it is going, so GCM's check of the sealed purpose is
    /// what stops it reaching any other server, whatever changed meanwhile.
    fun passwordFor(origin: String): String =
        PasswordVault.open(prefs.getString(PASSWORD, null), passwordPurpose(origin)) ?: ""

    val githubToken: String
        get() = PasswordVault.open(prefs.getString(TOKEN, null), TOKEN_PURPOSE) ?: ""

    /// Save what setup collected, in one write. Sealing happens first, so a
    /// keystore that refuses leaves the old settings exactly as they were;
    /// the exception is the caller's to report.
    ///
    /// A key entry the keystore can no longer use (seen after some OEM
    /// updates) gets one reset, and then BOTH values are sealed again under
    /// the new key: resetting between the two would leave the first sealed
    /// under a key that no longer exists.
    fun save(origin: String, username: String, password: String, githubToken: String) {
        val token = githubToken.trim()
        fun sealBoth(): Pair<String?, String?> = Pair(
            if (password.isEmpty()) null else PasswordVault.seal(password, passwordPurpose(origin)),
            if (token.isEmpty()) null else PasswordVault.seal(token, TOKEN_PURPOSE),
        )
        val (sealedPassword, sealedToken) = try {
            sealBoth()
        } catch (_: Exception) {
            PasswordVault.reset()
            sealBoth()
        }
        prefs.edit()
            .putString(ORIGIN, origin)
            .putString(USERNAME, username)
            .putString(PASSWORD, sealedPassword)
            .putString(TOKEN, sealedToken)
            .putBoolean(TOKEN_REJECTED, false)
            .apply()
    }

    /// Set when api.github.com refused the stored token (401). Updates carry
    /// on without it; setup says so until the token is replaced or removed.
    var tokenRejected: Boolean
        get() = prefs.getBoolean(TOKEN_REJECTED, false)
        set(v) = prefs.edit().putBoolean(TOKEN_REJECTED, v).apply()

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

    /// Whether the app lock is on (AppLock, LockScreen). This phone's own
    /// choice: never sent to the server or the account, and left alone by
    /// save(), so saving the server settings keeps it.
    var appLock: Boolean
        get() = prefs.getBoolean(APP_LOCK, false)
        set(v) = prefs.edit().putBoolean(APP_LOCK, v).apply()

    val configured: Boolean get() = origin.isNotEmpty()

    private companion object {
        const val ORIGIN = "origin"
        const val USERNAME = "username"
        const val PASSWORD = "password"
        const val TOKEN = "github_token"
        const val RELEASE_ETAG = "release_etag"
        const val LAST_CHECK = "last_check"
        const val THEME_COLOUR = "theme_colour"
        const val TOKEN_REJECTED = "github_token_rejected"
        const val APP_LOCK = "app_lock"

        const val TOKEN_PURPOSE = "github-token"
        fun passwordPurpose(origin: String) = "password for $origin"
    }
}
