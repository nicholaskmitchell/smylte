package com.nicholaskmitchell.smylte

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

/// The server address and the optional credentials: the desktop clients' setup
/// dialog. Shown on first run, from the window when the app cannot start, and
/// from the launcher's "Server settings" shortcut.
class SetupActivity : Activity() {
    private lateinit var settings: Settings
    private lateinit var server: EditText
    private lateinit var username: EditText
    private lateinit var password: EditText
    private lateinit var token: EditText
    private lateinit var save: Button
    private lateinit var status: TextView
    /// What the password field was filled with, to tell a password typed for
    /// a new address from one carried over from the old one.
    private var shownPassword = ""
    private var shownOrigin = ""
    /// A check is under way; its "Checking…" is not worth restoring.
    private var checking = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)
        Insets.edgeToEdge(window, findViewById(R.id.setup_root))

        settings = Settings(this)
        server = findViewById(R.id.server)
        username = findViewById(R.id.username)
        password = findViewById(R.id.password)
        token = findViewById(R.id.token)
        save = findViewById(R.id.save)
        status = findViewById(R.id.status)

        shownOrigin = settings.origin
        // After a rotation the guard below may already have asked for the
        // password again, and the field then holds what was typed since. Only
        // that fact is kept across the restart, never the password itself:
        // instance state can be written to disk.
        shownPassword = if (savedInstanceState?.getBoolean(KEY_DROPPED) == true) "" else settings.password
        if (savedInstanceState == null) {
            server.setText(shownOrigin)
            username.setText(settings.username)
            password.setText(shownPassword)
            token.setText(settings.githubToken)
            if (settings.tokenRejected) status.setText(R.string.setup_token_rejected)
        } else {
            status.text = savedInstanceState.getCharSequence(KEY_STATUS)
        }

        @Suppress("DEPRECATION")   // the PackageInfoFlags overload is API 33
        val version = packageManager.getPackageInfo(packageName, 0).versionName ?: "dev"
        findViewById<TextView>(R.id.version).text = getString(R.string.setup_version, version)

        save.setOnClickListener { check() }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(KEY_DROPPED, shownPassword.isEmpty())
        if (!checking) outState.putCharSequence(KEY_STATUS, status.text)
    }

    /// Check the address answers as Smylte before saving it, as the desktop
    /// setup does: a typo found here is a sentence, found later it is a window
    /// that cannot reach its server.
    private fun check() {
        val parsed = ServerAddress.parse(server.text.toString())
        if (parsed is ServerAddress.Parsed.Bad) {
            status.text = parsed.message
            return
        }
        val origin = (parsed as ServerAddress.Parsed.Ok).origin
        val user = username.text.toString().trim()
        val typed = password.text.toString()
        // A saved password goes to the address it was saved for and no other.
        // Moved to a new address without being typed again, it is dropped
        // rather than sent there: a mistyped or planted address would
        // otherwise receive it without anyone entering it.
        val carriedOver = origin != shownOrigin && shownOrigin.isNotEmpty() &&
            shownPassword.isNotEmpty() && typed == shownPassword
        if (carriedOver) {
            // Asked rather than decided: whatever is in the field from now on
            // was typed for this address.
            shownPassword = ""
            password.setText("")
            password.requestFocus()
            status.setText(R.string.setup_password_dropped)
            return
        }
        val gh = token.text.toString().trim()

        save.isEnabled = false
        checking = true
        status.setText(R.string.setup_checking)
        // Its own thread rather than Background.updates, which may be busy
        // with a download that has nothing to do with this.
        Thread {
            val (ok, probed) = Session.probe(origin)
            var message = probed
            var saved = false
            // A token GitHub refuses would only be dropped later, in silence.
            val tokenRefused = ok && gh.isNotEmpty() && GitHub.tokenAccepted(gh) == false
            if (tokenRefused) message = getString(R.string.setup_token_refused)
            // Back, pressed while this ran, means "don't". A rotation is not
            // Back: the window is rebuilt, not finished, and the save goes on.
            if (ok && !tokenRefused && !isFinishing) {
                // Sealing touches the keystore, so not on the main thread, and
                // a keystore that refuses is a sentence, not a crash.
                try {
                    settings.save(origin, user, typed, gh)
                    saved = true
                } catch (e: Exception) {
                    message = getString(R.string.setup_not_saved, Updater.describe(e))
                }
            }
            val app = applicationContext
            runOnUiThread {
                checking = false
                if (saved) {
                    // From the application, because this window may have been
                    // rebuilt by a rotation meanwhile; CLEAR_TASK replaces
                    // whichever setup window is showing now.
                    app.startActivity(
                        Intent(app, MainActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK),
                    )
                }
                if (isDestroyed) return@runOnUiThread
                save.isEnabled = true
                status.text = message
                if (saved) finish()
            }
        }.start()
    }

    private companion object {
        const val KEY_DROPPED = "password_dropped"
        const val KEY_STATUS = "status"
    }
}
