package com.nicholaskmitchell.smylte

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.View
import android.view.WindowInsetsController
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.ServiceWorkerClient
import android.webkit.ServiceWorkerController
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
    private var resumed = false
    /// Set by a reload into a new build, so Back cannot return to a page of
    /// the build it replaced.
    private var clearHistoryOnLoad = false
    private var restorePath: String? = null
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
            // Unsealed for the address it is about to be sent to, so a change
            // of server made while this ran yields "" rather than the new
            // server's password, sent to the old one.
            if (outcome.isSuccess) Session.ensureSignedIn(origin, settings.username, settings.passwordFor(origin))
            main.post {
                booting = false
                if (isDestroyed) return@post
                outcome.fold(
                    onSuccess = {
                        open()
                        offer(it)
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
            // Page zoom stays off. That is already WebView's default, and is
            // stated so nobody turns it on: the shell is a fixed 100dvh box
            // that clips (app.css `.shell`), so a zoom could only pan a cropped
            // layout. Text size is the zoom people need, and it follows the
            // system font size (applyTextZoom) and the app's own text size;
            // the system's magnification still works over any app.
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
        }
        // No edge effect. WebView draws its stretch (a glow on Android 11) over
        // the whole view, header and tab bar included, when the page's
        // scrolling reaches an end, so the whole app seemed to bounce.
        web.overScrollMode = View.OVER_SCROLL_NEVER
        applyTextZoom()
        // The app registers no service worker, and a service worker's requests
        // would bypass shouldInterceptRequest, and with it the files from disk
        // and their CSP. So none can fetch anything.
        ServiceWorkerController.getInstance().setServiceWorkerClient(object : ServiceWorkerClient() {
            override fun shouldInterceptRequest(request: WebResourceRequest): WebResourceResponse =
                LocalAssets.refused()
        })
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

    /// The page's text follows the system font size, while the app runs. WebView
    /// applies the system font scale itself only when it is created, and this
    /// activity handles font-size changes rather than being recreated
    /// (configChanges), so without this a change made while Smylte runs would
    /// wait for a cold start. The zoom is measured at the body text's size
    /// (TextZoom) through TypedValue rather than taken from fontScale, because
    /// Android 14 scales text non-linearly and TypedValue applies the curve
    /// native text gets. Once it is set, WebView never applies its own value
    /// again, so the host owns it from the first call.
    private fun applyTextZoom() {
        val metrics = resources.displayMetrics
        web.settings.textZoom = TextZoom.percent(
            TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, TextZoom.BODY_SP, metrics),
            TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, TextZoom.BODY_SP, metrics),
        )
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
        /// app too. Start the window again instead; onSaveInstanceState
        /// carries the page's path to the new one.
        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
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
    //
    // Two offers can be open at once: a newer web build waiting for a reload,
    // and a newer APK. Each is dismissed on its own and by identity, so "Not
    // now" hides THAT offer, and a newer one is offered again. The APK offer
    // also moves through steps (permission, download, installer, failure) that
    // must outlive the screen turning off, so they are state here, not just
    // text on a view.

    private sealed interface ClientStep {
        data object Offered : ClientStep
        data object NeedsPermission : ClientStep
        data class Downloading(val progress: String?) : ClientStep
        data object InstallerOpened : ClientStep
        /// `retried`: a failure that has already been tried again offers the
        /// release page instead of a third attempt.
        data class Failed(val message: String, val retried: Boolean) : ClientStep
    }

    /// The published APK, while it differs from the installed one.
    private var clientUpdate: ReleaseAsset? = null
    private var clientStep: ClientStep = ClientStep.Offered
    /// A verified APK waiting for the window to be in front, because Android
    /// may drop an activity start from an app in the background.
    private var pendingInstall = false
    /// The staged web build, while there is one.
    private var staged: BuildIdentity? = null
    private var dismissedClient: String? = null
    private var dismissedBuild: BuildIdentity? = null

    /// Take a check's answer. A different APK starts its offer afresh.
    private fun offer(outcome: Updater.Outcome) {
        val next = outcome.clientUpdate
        if (next?.digest != clientUpdate?.digest && clientStep !is ClientStep.Downloading) {
            clientStep = ClientStep.Offered
        }
        clientUpdate = next
        staged = outcome.staged
        refreshStrip()
    }

    private fun refreshStrip() {
        val client = clientUpdate
        val build = staged
        when {
            // A download under way is shown whatever else is pending; it is
            // the only step that is actually running.
            client != null && clientStep is ClientStep.Downloading -> showClient(client)
            // A reload takes a second and asks nothing of the user, so it
            // comes before any other step of the APK offer, all of which can
            // be dismissed.
            build != null && build != dismissedBuild ->
                showStrip(getString(R.string.web_staged), getString(R.string.reload), { dismissedBuild = build }) {
                    reloadIntoStaged()
                }
            client != null && client.digest != dismissedClient -> showClient(client)
            else -> strip.visibility = View.GONE
        }
    }

    private fun showClient(client: ReleaseAsset) {
        val dismiss = { dismissedClient = client.digest }
        when (val step = clientStep) {
            ClientStep.Offered ->
                showStrip(getString(R.string.client_outdated), getString(R.string.update), dismiss) { startClientUpdate() }
            ClientStep.NeedsPermission ->
                if (packageManager.canRequestPackageInstalls()) {
                    // Back from the settings screen with the permission given.
                    clientStep = ClientStep.Offered
                    showClient(client)
                } else {
                    showStrip(getString(R.string.allow_installs), getString(R.string.allow), dismiss) {
                        openInstallSettings()
                    }
                }
            is ClientStep.Downloading -> {
                showStrip(step.progress ?: getString(R.string.downloading), getString(R.string.update), dismiss) {}
                stripAction.isEnabled = false
                stripDismiss.isEnabled = false
            }
            ClientStep.InstallerOpened ->
                showStrip(getString(R.string.installer_opened), getString(R.string.update), dismiss) {
                    startClientUpdate()
                }
            is ClientStep.Failed ->
                // Kept until a check finds a different APK, so the reason does
                // not vanish with the screen. The first failure can be tried
                // again, since most are a dropped connection; after that, the
                // release page in the browser, where the APK can be downloaded
                // and installed by hand.
                if (step.retried) {
                    showStrip(step.message, getString(R.string.download), dismiss) {
                        openExternally(Uri.parse(Release.PAGE))
                    }
                } else {
                    showStrip(step.message, getString(R.string.try_again), dismiss) { startClientUpdate() }
                }
        }
    }

    private fun showStrip(text: String, action: String, onDismiss: () -> Unit, onAction: () -> Unit) {
        stripText.text = text
        stripAction.text = action
        stripAction.isEnabled = true
        stripDismiss.isEnabled = true
        stripAction.setOnClickListener { onAction() }
        stripDismiss.setOnClickListener {
            onDismiss()
            refreshStrip()
        }
        strip.visibility = View.VISIBLE
    }

    private fun openInstallSettings() {
        try {
            startActivity(
                Intent(
                    android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:$packageName"),
                ),
            )
        } catch (_: ActivityNotFoundException) {
            clientStep = ClientStep.Failed(getString(R.string.allow_installs), retried = true)
            refreshStrip()
        }
    }

    /// Download and verify the APK, then hand it to the system installer, which
    /// asks for confirmation and offers to open the new version when it is
    /// done. Smylte is closed while it installs; nothing here can restart it.
    private fun startClientUpdate() {
        if (!packageManager.canRequestPackageInstalls()) {
            clientStep = ClientStep.NeedsPermission
            refreshStrip()
            return
        }
        val retrying = clientStep is ClientStep.Failed
        clientStep = ClientStep.Downloading(null)
        refreshStrip()
        Background.updates.execute {
            val result = runCatching {
                updater.downloadClient { text ->
                    main.post {
                        if (isDestroyed || clientStep !is ClientStep.Downloading) return@post
                        clientStep = ClientStep.Downloading(text)
                        refreshStrip()
                    }
                }
            }
            main.post {
                if (isDestroyed) return@post
                result.fold(
                    onSuccess = { apk ->
                        if (apk == null) {
                            // Checked again just now: the installed APK is the
                            // published one after all.
                            clientUpdate = null
                            clientStep = ClientStep.Offered
                            refreshStrip()
                        } else {
                            pendingInstall = true
                            if (resumed) launchInstaller()
                        }
                    },
                    onFailure = {
                        clientStep = ClientStep.Failed(Updater.describe(it), retried = retrying)
                        refreshStrip()
                    },
                )
            }
        }
    }

    /// Open the SYSTEM package installer on the downloaded APK. Resolved to
    /// the system's own installer explicitly, so no other app that claims APK
    /// files can intercept the intent and pretend to install.
    private fun launchInstaller() {
        pendingInstall = false
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(ApkProvider.uri(this), ApkProvider.MIME)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        @Suppress("DEPRECATION")   // the ResolveInfoFlags overload is API 33
        val installer = packageManager
            .queryIntentActivities(intent, PackageManager.MATCH_SYSTEM_ONLY)
            .firstOrNull()?.activityInfo?.packageName
        if (installer == null) {
            clientStep = ClientStep.Failed(getString(R.string.no_installer), retried = true)
            refreshStrip()
            return
        }
        try {
            startActivity(intent.setPackage(installer))
            clientStep = ClientStep.InstallerOpened
        } catch (_: ActivityNotFoundException) {
            clientStep = ClientStep.Failed(getString(R.string.no_installer), retried = true)
        }
        refreshStrip()
    }

    /// Swap the staged build in and load the page again from it. The page is
    /// stopped first and loaded fresh after; a request it makes in between
    /// meets a build mid-swap, which costs nothing because the page is about
    /// to be replaced.
    private fun reloadIntoStaged() {
        val path = currentPath()
        staged = null
        refreshStrip()
        web.stopLoading()
        clearHistoryOnLoad = true
        showSplash(getString(R.string.starting), failed = false)
        Background.updates.execute {
            try {
                updater.web.promote()
            } catch (_: Exception) {
                // Rolled back; the installed build loads again.
            }
            // Read after the swap, on the same thread as every check, so a
            // check that ran just before this cannot leave a stale offer.
            val left = updater.web.staged()
            main.post {
                if (isDestroyed) return@post
                staged = left
                restorePath = path
                open()
                refreshStrip()
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
                    offer(outcome)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        web.onResume()
        if (pendingInstall) launchInstaller()
        // Back from the "install unknown apps" screen, or the installer.
        if (loaded) refreshStrip()
    }

    override fun onPause() {
        resumed = false
        CookieManager.getInstance().flush()
        web.onPause()
        super.onPause()
    }

    /// Every change listed in the manifest's configChanges arrives here instead
    /// of recreating the window. The activity's resources are updated before
    /// this is called, so applyTextZoom reads the new display metrics.
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        // Not set up when onCreate sent a first run to the settings screen.
        if (::web.isInitialized) applyTextZoom()
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
