package com.nicholaskmitchell.smylte

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowInsetsController
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import java.util.Locale

/// The window: a WebView showing the app at the server's own origin, with its
/// files answered from the downloaded web build (LocalAssets), plus the
/// start-up splash and the update strip.
class MainActivity : Activity() {
    private lateinit var settings: Settings
    private lateinit var updater: Updater
    private lateinit var assets: LocalAssets
    private lateinit var origin: String

    private lateinit var root: View
    private lateinit var web: WebView
    private lateinit var splash: View
    private lateinit var splashText: TextView
    private lateinit var splashActions: View
    private lateinit var strip: View
    private lateinit var stripText: TextView
    private lateinit var stripAction: Button
    private lateinit var stripDismiss: Button

    private val main = Handler(Looper.getMainLooper())

    private var booting = false
    private var loaded = false
    /// Set by a reload into a new build, so Back cannot return to a page of
    /// the build it replaced.
    private var clearHistoryOnLoad = false
    private var restorePath: String? = null

    private var clientUpdate: ReleaseAsset? = null
    private var webStaged = false
    private var stripDismissed = false
    /// Set while the strip is in the middle of something and must not be redrawn.
    private var stripBusy = false
    private var lastBackgroundCheck = 0L

    private var backCallback: Any? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = Settings(this)
        if (!settings.configured) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }
        origin = settings.origin
        updater = Updater(this, settings)
        assets = LocalAssets(updater.web.root, origin)
        restorePath = savedInstanceState?.getString(KEY_PATH)

        setContentView(R.layout.activity_main)
        root = findViewById(R.id.root)
        web = findViewById(R.id.web)
        splash = findViewById(R.id.splash)
        splashText = findViewById(R.id.splash_text)
        splashActions = findViewById(R.id.splash_actions)
        strip = findViewById(R.id.strip)
        stripText = findViewById(R.id.strip_text)
        stripAction = findViewById(R.id.strip_action)
        stripDismiss = findViewById(R.id.strip_dismiss)

        Insets.edgeToEdge(window, root)
        settings.themeColour.takeIf { it != 0 }?.let(::applyThemeColour)

        findViewById<Button>(R.id.retry).setOnClickListener { boot() }
        findViewById<Button>(R.id.open_settings).setOnClickListener {
            startActivity(Intent(this, SetupActivity::class.java))
        }
        stripDismiss.setOnClickListener {
            stripDismissed = true
            strip.visibility = View.GONE
        }

        // The cookie store is initialised here, on the main thread, because
        // the start-up thread reads and writes it before any WebView loads.
        CookieManager.getInstance().setAcceptCookie(true)
        configureWebView()
        boot()
    }

    // ── start-up ────────────────────────────────────────────────────────────

    private fun boot() {
        if (booting) return
        booting = true
        showSplash(getString(R.string.starting), failed = false)
        val origin = origin
        Background.updates.execute {
            val outcome = try {
                Result.success(updater.startUp { text -> main.post { if (!isDestroyed) splashText.text = text } })
            } catch (e: StartupFailure) {
                Result.failure(e)
            } catch (e: Exception) {
                Result.failure(StartupFailure("Smylte could not start: ${Updater.describe(e)}"))
            }
            if (outcome.isSuccess) Session.ensureSignedIn(origin, settings.username, settings.password)
            main.post {
                booting = false
                if (isDestroyed) return@post
                outcome.fold(
                    onSuccess = {
                        clientUpdate = it.clientUpdate
                        webStaged = it.webStaged
                        open()
                        refreshStrip()
                    },
                    onFailure = { showSplash(it.message ?: getString(R.string.starting), failed = true) },
                )
            }
        }
    }

    private fun showSplash(text: String, failed: Boolean) {
        splash.visibility = View.VISIBLE
        splashText.text = text
        splashActions.visibility = if (failed) View.VISIBLE else View.GONE
        // The splash has no background of its own, so the page must not show
        // through it.
        web.visibility = View.INVISIBLE
    }

    private fun open() {
        val path = restorePath ?: "/"
        restorePath = null
        splash.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl(origin + path)
        loaded = true
    }

    /// Where the page is now, as a path on the origin, or "/" when it is
    /// somewhere else (or nowhere yet).
    private fun currentPath(): String {
        val url = web.url?.let(Uri::parse) ?: return "/"
        if (!AssetRoutes.isSameOrigin(origin, url.scheme, url.host, url.port)) return "/"
        val path = url.encodedPath?.takeIf { it.startsWith("/") } ?: "/"
        return path + (url.encodedQuery?.let { "?$it" } ?: "")
    }

    // ── the WebView ─────────────────────────────────────────────────────────

    @SuppressLint("SetJavaScriptEnabled")   // it is the app
    private fun configureWebView() {
        WebView.setWebContentsDebuggingEnabled(
            (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0,
        )
        // Transparent until the page paints, so the root's colour (the page's
        // last background) shows rather than a white flash in a dark theme.
        web.setBackgroundColor(0)
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true          // the app keeps its cache in localStorage
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)  // target=_blank arrives as a navigation below
            javaScriptCanOpenWindowsAutomatically = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setGeolocationEnabled(false)
            // The focus timer's chime plays when a phase ends, not on a tap.
            mediaPlaybackRequiresUserGesture = false
        }
        web.addJavascriptInterface(
            ThemeBridge { colour ->
                main.post {
                    if (isDestroyed) return@post
                    applyThemeColour(colour)
                    settings.themeColour = colour
                }
            },
            "SmylteAndroid",
        )
        web.webViewClient = Client()
        web.webChromeClient = Chrome()
        web.setDownloadListener { url, _, _, _, _ ->
            if (url.startsWith("https://") || url.startsWith("http://")) openExternally(Uri.parse(url))
            else Toast.makeText(this, R.string.export_unavailable, Toast.LENGTH_LONG).show()
        }
    }

    private fun isOurs(url: Uri): Boolean = AssetRoutes.isSameOrigin(origin, url.scheme, url.host, url.port)

    private inner class Client : WebViewClient() {
        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
            assets.answer(request)

        /// The app stays in the window; everything else goes to the app that
        /// handles it, and only from a tap. A script that sends the page to
        /// another origin without one is simply stopped.
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            if (isOurs(url)) return false
            if (request.isForMainFrame && request.hasGesture()) openExternally(url)
            return true
        }

        override fun onPageFinished(view: WebView, url: String) {
            if (isOurs(Uri.parse(url))) {
                view.evaluateJavascript(ThemeColour.WATCH_SCRIPT, null)
                if (clearHistoryOnLoad) {
                    clearHistoryOnLoad = false
                    view.clearHistory()
                }
            }
            syncBack()
        }

        override fun doUpdateVisitedHistory(view: WebView, url: String, isReload: Boolean) {
            syncBack()
        }

        /// A renderer that died takes the WebView with it, and by default the
        /// app too. Start the window again instead.
        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            // onSaveInstanceState carries the page's path to the new window.
            if (!isDestroyed) recreate()
            return true
        }
    }

    private inner class Chrome : WebChromeClient() {
        /// `<input type="file">`: the theme import.
        override fun onShowFileChooser(
            view: WebView,
            callback: ValueCallback<Array<Uri>>,
            params: FileChooserParams,
        ): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = callback
            return try {
                @Suppress("DEPRECATION")
                startActivityForResult(params.createIntent(), REQUEST_FILE)
                true
            } catch (_: ActivityNotFoundException) {
                fileCallback = null
                false
            }
        }
    }

    @Deprecated("Activity result API; this client takes no AndroidX")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_FILE) {
            fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileCallback = null
            return
        }
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
    }

    private fun openExternally(url: Uri) {
        val scheme = url.scheme?.lowercase(Locale.ROOT)
        if (scheme !in setOf("https", "http", "mailto", "tel")) return
        try {
            startActivity(Intent(Intent.ACTION_VIEW, url).addCategory(Intent.CATEGORY_BROWSABLE))
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_app_for_link, Toast.LENGTH_SHORT).show()
        }
    }

    // ── the bars ────────────────────────────────────────────────────────────

    private fun applyThemeColour(colour: Int) {
        root.setBackgroundColor(colour)
        val dark = ThemeColour.wantsDarkIcons(colour)
        val mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
            WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
        window.insetsController?.setSystemBarsAppearance(if (dark) mask else 0, mask)
        splashText.setTextColor(if (dark) 0xFF1A1814.toInt() else 0xFFF4F1E8.toInt())
    }

    // ── back ────────────────────────────────────────────────────────────────

    /// Back walks the page's history, then leaves. On 13 and later that is an
    /// OnBackInvokedCallback registered only while there is history to walk,
    /// so the system's own back-to-home gesture plays when there is not; and
    /// an app targeting 16 is never sent onBackPressed at all.
    private fun syncBack() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val want = web.canGoBack()
        val registered = backCallback
        if (want && registered == null) {
            val callback = OnBackInvokedCallback { if (web.canGoBack()) web.goBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
            backCallback = callback
        } else if (!want && registered != null) {
            onBackInvokedDispatcher.unregisterOnBackInvokedCallback(registered as OnBackInvokedCallback)
            backCallback = null
        }
    }

    /// Android 11 and 12 only. On 13 and later the OnBackInvokedCallback in
    /// syncBack is what runs, which is what the lint check asks for; it cannot
    /// see that this override is the fallback for the versions without one.
    @SuppressLint("GestureBackNavigation")
    @Deprecated("Used below Android 13 only; see syncBack")
    override fun onBackPressed() {
        if (loaded && web.canGoBack()) web.goBack()
        else @Suppress("DEPRECATION") super.onBackPressed()
    }

    // ── the update strip ────────────────────────────────────────────────────

    private fun refreshStrip() {
        if (stripBusy) return
        when {
            stripDismissed -> strip.visibility = View.GONE
            clientUpdate != null -> showStrip(getString(R.string.client_outdated), getString(R.string.update)) {
                startClientUpdate()
            }
            webStaged -> showStrip(getString(R.string.web_staged), getString(R.string.reload)) { reloadIntoStaged() }
            else -> strip.visibility = View.GONE
        }
    }

    private fun showStrip(text: String, action: String, onAction: () -> Unit) {
        stripText.text = text
        stripAction.text = action
        stripAction.isEnabled = true
        stripDismiss.isEnabled = true
        stripAction.setOnClickListener { onAction() }
        strip.visibility = View.VISIBLE
    }

    /// Download, verify, then hand the APK to the system installer, which asks
    /// for confirmation and offers to open the new version when it is done.
    /// Smylte is closed while it installs; nothing here can restart it.
    private fun startClientUpdate() {
        val asset = clientUpdate ?: return
        if (!packageManager.canRequestPackageInstalls()) {
            showStrip(getString(R.string.allow_installs), getString(R.string.allow)) {
                try {
                    startActivity(
                        Intent(
                            android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:$packageName"),
                        ),
                    )
                } catch (_: ActivityNotFoundException) {
                    offerDownloadPage(getString(R.string.allow_installs))
                }
            }
            return
        }
        stripBusy = true
        stripAction.isEnabled = false
        stripDismiss.isEnabled = false
        Background.updates.execute {
            val result = runCatching {
                updater.downloadClient(asset) { text -> main.post { if (!isDestroyed) stripText.text = text } }
            }
            main.post {
                stripBusy = false
                if (isDestroyed) return@post
                result.fold(
                    onSuccess = { launchInstaller() },
                    onFailure = { offerDownloadPage(Updater.describe(it)) },
                )
            }
        }
    }

    private fun launchInstaller() {
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(ApkProvider.uri(this), ApkProvider.MIME)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            startActivity(intent)
            showStrip(getString(R.string.installer_opened), getString(R.string.update)) { startClientUpdate() }
        } catch (_: ActivityNotFoundException) {
            offerDownloadPage("No installer on this phone would open the update.")
        }
    }

    /// The fallback when the in-app update cannot finish: the release page, in
    /// the browser, where the APK can be downloaded and installed by hand.
    private fun offerDownloadPage(message: String) {
        showStrip(message, getString(R.string.download)) { openExternally(Uri.parse(Release.PAGE)) }
    }

    /// Swap the staged build in and load the page again from it. The page is
    /// stopped first and loaded fresh after; a request it makes in between
    /// meets a build mid-swap, which costs nothing because the page is about
    /// to be replaced.
    private fun reloadIntoStaged() {
        val path = currentPath()
        webStaged = false
        strip.visibility = View.GONE
        web.stopLoading()
        clearHistoryOnLoad = true
        showSplash(getString(R.string.starting), failed = false)
        Background.updates.execute {
            try {
                updater.web.promote()
            } catch (_: Exception) {
                // Rolled back; the installed build loads again.
            }
            main.post {
                if (isDestroyed) return@post
                restorePath = path
                open()
            }
        }
    }

    // ── lifecycle ───────────────────────────────────────────────────────────

    override fun onStart() {
        super.onStart()
        // Android keeps an app's process for days. A start-up check alone
        // would then leave a phone on an old build for as long as Smylte stays
        // in memory, so a return to the app after hours away checks again. A
        // newer web build is staged and offered, never swapped under the page.
        val now = System.currentTimeMillis()
        if (loaded && !booting && now - settings.lastCheck > RECHECK_MS && now - lastBackgroundCheck > RETRY_MS) {
            lastBackgroundCheck = now
            Background.updates.execute {
                val outcome = try {
                    updater.check()
                } catch (_: Exception) {
                    null
                }
                main.post {
                    if (isDestroyed || outcome == null) return@post
                    clientUpdate = outcome.clientUpdate
                    webStaged = outcome.webStaged
                    refreshStrip()
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
        // Back from the "install unknown apps" screen: offer Update again.
        if (loaded) refreshStrip()
    }

    override fun onPause() {
        CookieManager.getInstance().flush()
        web.onPause()
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (loaded) outState.putString(KEY_PATH, currentPath())
    }

    override fun onDestroy() {
        if (::web.isInitialized) {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
            web.destroy()
        }
        super.onDestroy()
    }

    private companion object {
        const val KEY_PATH = "path"
        const val REQUEST_FILE = 1
        const val RECHECK_MS = 6 * 60 * 60 * 1000L
        const val RETRY_MS = 15 * 60 * 1000L
    }
}
