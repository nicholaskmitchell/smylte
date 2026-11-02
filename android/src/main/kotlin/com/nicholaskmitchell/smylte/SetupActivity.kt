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

        if (savedInstanceState == null) {
            server.setText(settings.origin)
            username.setText(settings.username)
            password.setText(settings.password)
            token.setText(settings.githubToken)
        }

        @Suppress("DEPRECATION")   // the PackageInfoFlags overload is API 33
        val version = packageManager.getPackageInfo(packageName, 0).versionName ?: "dev"
        findViewById<TextView>(R.id.version).text = getString(R.string.setup_version, version)

        save.setOnClickListener { check() }
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
        val pass = password.text.toString()
        val gh = token.text.toString().trim()

        save.isEnabled = false
        status.setText(R.string.setup_checking)
        // Its own thread rather than Background.updates, which may be busy
        // with a download that has nothing to do with this.
        Thread {
            val (ok, message) = Session.probe(origin)
            if (ok) {
                // Sealing touches the keystore, so not on the main thread.
                settings.origin = origin
                settings.username = user
                settings.password = pass
                settings.githubToken = gh
            }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                save.isEnabled = true
                status.text = message
                if (!ok) return@runOnUiThread
                server.setText(origin)
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK),
                )
                finish()
            }
        }.start()
    }
}
