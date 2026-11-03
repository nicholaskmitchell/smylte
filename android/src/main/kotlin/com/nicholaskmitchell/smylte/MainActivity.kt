package com.nicholaskmitchell.smylte

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import android.text.format.DateFormat
import android.util.TypedValue
import android.view.View
import android.view.ViewTreeObserver
import android.view.WindowInsetsController
import android.webkit.CookieManager
import android.webkit.JsPromptResult
import android.webkit.JsResult
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
import java.io.File
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/// The window: a WebView showing the app at the server's own origin, with its
/// files answered from the downloaded web build (LocalAssets), plus the
/// start-up splash, the update strip and the app lock (LockScreen).
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

    /// The app lock in this window.
    private lateinit var lock: LockScreen

    private val main = Handler(Looper.getMainLooper())

    private var booting = false
    private var loaded = false
    private var resumed = false
    /// Set by a reload into a new build, so Back cannot return to a page of
    /// the build it replaced.
    private var clearHistoryOnLoad = false
    private var restorePath: String? = null
    private var lastBackgroundCheck = 0L
    /// Start-up has opened the page, so the WebView shows unless the app is locked (showPage).
    private var pageShown = false
    /// The WebView's own accessibility importance, restored when the lock lets go.
    private var webAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
    /// Pickers' answers that came back while the window was locked, in order (runHeld).
    private val heldResults = mutableListOf<HeldResult>()
    /// The window was locked when it started, so the splash hold ends at once (HostProtocol.splashRelease).
    private var splashLocked = false
    /// Between onStart and onStop. A picker's answer that comes before onStart
    /// waits for it (HostProtocol.holdsResult).
    private var started = false

    private var backCallback: Any? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    /// What hello() answers. Written on the main thread, read on the bridge thread.
    @Volatile private var envJson = HostProtocol.envJson(clock24 = false)
    /// Counts committed documents, so a save's result reaches only the document
    /// that asked. Also read on the bridge thread, by layers().
    @Volatile private var docGeneration = 0
    /// How many layers the page says are open. Main thread.
    private var pageLayers = 0
    /// Claimed on the bridge thread, so two calls cannot both open a picker.
    private val saveBusy = AtomicBoolean(false)
    /// The payload while the picker is open; null after a restore that could not read it back.
    private var saveRequest: SaveRequest? = null
    private var saveDocument = 0
    /// The picker was opened by an earlier instance of this activity, which has no page now.
    private var saveRestored = false
    private var pickerOpen = false
    private var lastPickerClosed: Long? = null

    /// Whether the page may play a haptic now. Main thread: the touch listener and the posted haptic both run there.
    private val hapticGate = HapticGate()

    /// While true the window does not draw, so the platform's splash screen
    /// stays up (holdSplash). Main thread; read before every frame, so a flag
    /// and nothing more.
    private var splashHeld = false
    private var splashHeldSince = 0L
    /// The page announced HostProtocol.CAP_READY, so its load no longer ends
    /// the hold; its ready() does. Written on the bridge thread by hello.
    @Volatile private var splashWantsReady = false
    private var splashPageReady = false
    private var splashPageFinished = false
    private var splashFailed = false
    // The cap ends the hold outright, without asking splashRelease again, so
    // no rounding of the elapsed time can leave the window held past it.
    private val splashCap = Runnable { splashHeld = false }

    /// A picker's answer that came back to a locked window.
    private class HeldResult(val requestCode: Int, val resultCode: Int, val data: Intent?)

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
        envJson = currentEnv()
        restoreSave(savedInstanceState)

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
        webAccessibility = web.importantForAccessibility
        lock = LockScreen(this, settings, findViewById(R.id.main_content), findViewById(R.id.lock), ::onLockChanged)
        holdSplash(savedInstanceState)

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
        pageShown = false
        showPage()
        // The failure screen's Retry and Server settings must never wait
        // behind the platform splash.
        if (failed) {
            splashFailed = true
            releaseSplashIfDue()
        }
    }

    private fun open() {
        val path = restorePath ?: "/"
        restorePath = null
        splash.visibility = View.GONE
        pageShown = true
        showPage()
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

    // ── the splash screen ───────────────────────────────────────────────────

    /// Keeps the platform's splash screen (Android 12 and later) up until the
    /// app's first view is ready, rather than following it with this window's
    /// own "Starting…" and then an empty page. The system removes its splash
    /// at the window's first frame, so the window simply does not draw until
    /// then. HostProtocol.splashRelease says what ends the hold, and its cap
    /// ends it in any case. The listener runs before every frame while the
    /// hold lasts, so it reads a flag and nothing more.
    ///
    /// Only a fresh launch from the launcher holds (HostProtocol.holdsSplash).
    /// The splash's exit animation is left to the system: on Android 12 and
    /// 12L, taking it over can change how the window fits the system bars,
    /// which Insets depends on.
    private fun holdSplash(savedInstanceState: Bundle?) {
        val fromLauncher = intent?.let {
            it.action == Intent.ACTION_MAIN && it.hasCategory(Intent.CATEGORY_LAUNCHER)
        } == true
        if (!HostProtocol.holdsSplash(Build.VERSION.SDK_INT, savedInstanceState != null, fromLauncher)) return
        splashHeld = true
        val now = SystemClock.uptimeMillis()
        splashHeldSince = HostProtocol.splashSince(now, Process.getStartUptimeMillis())
        val content = findViewById<View>(android.R.id.content)
        content.viewTreeObserver.addOnPreDrawListener(object : ViewTreeObserver.OnPreDrawListener {
            override fun onPreDraw(): Boolean {
                if (splashHeld) return false
                // Fetched again rather than kept: the observer the view had
                // before it was attached is merged into the window's then, and
                // removing a listener from it would throw.
                content.viewTreeObserver.removeOnPreDrawListener(this)
                return true
            }
        })
        main.postDelayed(splashCap, HostProtocol.SPLASH_CAP_MS - (now - splashHeldSince))
    }

    /// Ends the hold once HostProtocol.splashRelease says so. Nothing needs to
    /// ask for a frame: a draw the listener cancelled is tried again on the
    /// next one. Main thread.
    private fun releaseSplashIfDue() {
        if (!splashHeld) return
        val elapsed = SystemClock.uptimeMillis() - splashHeldSince
        val due = HostProtocol.splashRelease(
            elapsed, splashFailed, splashPageReady, splashWantsReady, splashPageFinished, splashLocked,
        )
        if (!due) return
        splashHeld = false
        main.removeCallbacks(splashCap)
    }

    // ── the app lock ────────────────────────────────────────────────────────

    /// The WebView shows only when start-up has opened the page and the app is
    /// not locked. Its own visibility, and not only its container's
    /// (LockScreen), so WebView treats the page as hidden while it is locked,
    /// and a page that finishes loading behind the lock stays hidden. The only
    /// place the WebView's visibility changes (AppLockTest).
    private fun showPage() {
        val locked = lock.locked
        web.visibility = if (pageShown && !locked) View.VISIBLE else View.INVISIBLE
        web.importantForAccessibility =
            if (locked) View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS else webAccessibility
    }

    /// The lock took hold or let go (LockScreen.sync).
    private fun onLockChanged(locked: Boolean) {
        showPage()
        syncBack()
        if (locked) {
            // A locked start shows the lock view at once: holding the platform's
            // splash would only keep the prompt waiting, and the page is hidden
            // either way (HostProtocol.splashRelease).
            splashLocked = true
            releaseSplashIfDue()
            // A date picker left open would stand over the lock view.
            if (showingOurPage()) web.evaluateJavascript(HostProtocol.CLOSE_PICKER_SCRIPT, null)
        } else {
            runHeld()
        }
    }

    /// Work that waits for the window to be started and unlocked: picker
    /// answers that came back before then, in order, and an install whose
    /// download finished meanwhile. Runs when the lock lets go and on every
    /// resume, which also covers an answer that came before onStart (Android 11)
    /// and a window that comes back unlocked with a save held from before
    /// Android restarted the app.
    private fun runHeld() {
        if (HostProtocol.holdsResult(started, lock.locked)) return
        val held = heldResults.toList()
        heldResults.clear()
        for (result in held) deliverResult(result.requestCode, result.resultCode, result.data)
        if (pendingInstall && resumed) launchInstaller()
    }

    // ── the WebView ─────────────────────────────────────────────────────────

    // SetJavaScriptEnabled: it is the app. ClickableViewAccessibility: the touch
    // listener only watches.
    @SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
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
        // Haptics answer touches (HapticGate), so the gate sees every touch on
        // the page. The listener only watches and returns false, so the WebView
        // still handles each touch, clicks and accessibility included; the lint
        // check it suppresses is about listeners that consume touches.
        web.setOnTouchListener { _, event ->
            hapticGate.onTouch(event.actionMasked, SystemClock.uptimeMillis())
            false
        }
        // The app registers no service worker, and a service worker's requests
        // would bypass shouldInterceptRequest, and with it the files from disk
        // and their CSP. So none can fetch anything.
        ServiceWorkerController.getInstance().setServiceWorkerClient(object : ServiceWorkerClient() {
            override fun shouldInterceptRequest(request: WebResourceRequest): WebResourceResponse =
                LocalAssets.refused()
        })
        // Every script on the page can call it; PageBridge says what each
        // method may do.
        web.addJavascriptInterface(PageBridge(Bridge()), "SmylteAndroid")
        web.webViewClient = Client()
        web.webChromeClient = Chrome()
        // A page from before saveFile still exports through a blob download,
        // which the WebView cannot hand to Android, so it is told so.
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

    // ── the page bridge ─────────────────────────────────────────────────────

    private inner class Bridge : PageBridge.Host {
        override fun colour(colour: Int) {
            main.post {
                if (isDestroyed) return@post
                applyThemeColour(colour)
                settings.themeColour = colour
            }
        }

        // A page that announces ready will say when its first view is up, so
        // its load no longer ends the splash hold. Set here on the bridge
        // thread rather than posted, so it is in place before the page's load
        // event can reach onPageFinished. No other capability is consulted.
        override fun hello(caps: Set<String>): String {
            if (HostProtocol.CAP_READY in caps) splashWantsReady = true
            return envJson
        }

        override fun layers(depth: Int) {
            // Read at the call, so a report still queued when the next document
            // starts is known as the old page's.
            val document = docGeneration
            main.post {
                if (isDestroyed) return@post
                pageLayers = HostProtocol.layersAfterReport(pageLayers, depth, document, docGeneration)
                syncBack()
            }
        }

        /// The one-argument performHapticFeedback, so the system's touch feedback
        /// setting and the view's own still decide, as for native controls.
        override fun haptic(kind: HostProtocol.Haptic) {
            main.post {
                if (isDestroyed) return@post
                if (hapticGate.allow(SystemClock.uptimeMillis(), resumed, showingOurPage())) {
                    web.performHapticFeedback(HostProtocol.hapticConstant(kind, Build.VERSION.SDK_INT))
                }
            }
        }

        override fun save(request: SaveRequest): Boolean {
            if (!saveBusy.compareAndSet(false, true)) return false
            main.post { launchSave(request) }
            return true
        }

        override fun ready() {
            main.post {
                if (isDestroyed) return@post
                splashPageReady = true
                releaseSplashIfDue()
            }
        }
    }

    /// What hello reports: the phone's 12/24-hour setting and, on Android 12 and
    /// later, its accent palette. Main thread.
    private fun currentEnv(): String =
        HostProtocol.envJson(DateFormat.is24HourFormat(this), SystemAccent.read(this))

    /// Tell the page when the facts hello reported have changed. It runs in
    /// onResume, so a Settings change made while away is picked up (a
    /// ContentObserver is skipped because its notifications are unconfirmed),
    /// and in onConfigurationChanged, because a locale change changes the
    /// default. A new wallpaper palette reaches the page either way: a rebuilt
    /// window's page asks hello afresh, and a window that is not rebuilt
    /// (configChanges lists assetsPaths) sends it from here.
    private fun refreshEnv() {
        val next = currentEnv()
        if (next == envJson) return
        envJson = next
        sendEvent(HostProtocol.envEvent(next))
    }

    private fun showingOurPage(): Boolean = loaded && web.url?.let { isOurs(Uri.parse(it)) } == true

    private fun canWalkBack(): Boolean = loaded && web.canGoBack()

    /// One DOM event to the app's own document; never to a page anywhere else.
    private fun sendEvent(detail: String) {
        if (isDestroyed || !showingOurPage()) return
        web.evaluateJavascript(HostProtocol.eventScript(detail), null)
    }

    /// The picker cannot overwrite a file (it appends "(1)") and the host
    /// writes only to the URI it returns, so the worst a script gets is a save
    /// dialog the user can cancel.
    private fun launchSave(request: SaveRequest) {
        if (isDestroyed) {
            saveBusy.set(false)
            return
        }
        val ours = showingOurPage()
        if (!HostProtocol.allowSave(resumed, ours, SystemClock.uptimeMillis(), lastPickerClosed, lock.locked)) {
            saveBusy.set(false)
            sendEvent(HostProtocol.savedEvent(HostProtocol.SaveOutcome.FAILED))
            return
        }
        saveRequest = request
        saveDocument = docGeneration
        saveRestored = false
        pickerOpen = true
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(request.mime)
            .putExtra(Intent.EXTRA_TITLE, request.name)
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(intent, REQUEST_SAVE)
        } catch (_: ActivityNotFoundException) {
            saveRequest = null
            pickerOpen = false
            saveBusy.set(false)
            sendEvent(HostProtocol.savedEvent(HostProtocol.SaveOutcome.FAILED))
        }
    }

    /// Mode "wt" truncates. After a failed write the host deletes nothing: a
    /// provider might have returned an existing document, and deleting it would
    /// lose the user's file.
    private fun finishSave(resultCode: Int, data: Intent?) {
        pickerOpen = false
        lastPickerClosed = SystemClock.uptimeMillis()
        stashFile().delete()   // the payload is in memory from here on
        val request = saveRequest
        val uri = if (resultCode == RESULT_OK) data?.data else null
        if (uri == null) {
            completeSave(HostProtocol.SaveOutcome.CANCELLED)
            return
        }
        if (request == null) {
            completeSave(HostProtocol.SaveOutcome.FAILED)
            return
        }
        val resolver = contentResolver
        Background.files.execute {
            val written = runCatching {
                resolver.openOutputStream(uri, "wt")?.use {
                    it.write(request.text.toByteArray(Charsets.UTF_8))
                    true
                } ?: false
            }.getOrDefault(false)
            main.post {
                completeSave(if (written) HostProtocol.SaveOutcome.SAVED else HostProtocol.SaveOutcome.FAILED)
            }
        }
    }

    /// applicationContext is used for the toast because this instance may
    /// already be destroyed.
    private fun completeSave(outcome: HostProtocol.SaveOutcome) {
        val report = HostProtocol.saveReport(saveRestored, saveDocument, docGeneration, alive = !isDestroyed)
        saveRequest = null
        saveRestored = false
        saveBusy.set(false)
        when (report) {
            HostProtocol.SaveReport.PAGE -> sendEvent(HostProtocol.savedEvent(outcome))
            HostProtocol.SaveReport.TOAST -> when (outcome) {
                HostProtocol.SaveOutcome.SAVED -> R.string.file_saved
                HostProtocol.SaveOutcome.FAILED -> R.string.file_not_saved
                HostProtocol.SaveOutcome.CANCELLED -> null   // the user's own act needs no word
            }?.let { Toast.makeText(applicationContext, it, Toast.LENGTH_LONG).show() }
        }
    }

    /// The picker can outlive this activity, through process death, recreate()
    /// after a renderer crash, or a wallpaper palette change, and Android
    /// delivers its result to the new one. The slot stays claimed even when the
    /// payload is unreadable, so a page call cannot take over a picker the user
    /// is already looking at.
    private fun restoreSave(state: Bundle?) {
        val stash = stashFile()
        if (state?.getBoolean(KEY_SAVE_OPEN) == true) {
            val text = runCatching { stash.readText() }.getOrNull()
            saveRequest = SaveRequest.of(state.getString(KEY_SAVE_NAME), state.getString(KEY_SAVE_MIME), text)
            saveBusy.set(true)
            saveRestored = true
            pickerOpen = true
            if (state.containsKey(KEY_HELD_SAVE_CODE)) {
                @Suppress("DEPRECATION")   // the Class overload is API 33
                val data = state.getParcelable<Intent>(KEY_HELD_SAVE_DATA)
                heldResults += HeldResult(REQUEST_SAVE, state.getInt(KEY_HELD_SAVE_CODE), data)
            }
        }
        stash.delete()   // read once; a stale one from a killed process goes too
    }

    private fun stashFile() = File(cacheDir, STASH)

    private inner class Client : WebViewClient() {
        /// A new document. A save the last one started reports through a toast
        /// instead (saveReport).
        override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
            docGeneration++
            // The old page cannot report its layers going, so a new document
            // starts at none.
            pageLayers = 0
            syncBack()
        }

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
            // A page that never announced ready (a web build from before it)
            // has nothing more to say, so its load can end the splash hold
            // (HostProtocol.splashRelease).
            splashPageFinished = true
            releaseSplashIfDue()
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

        // alert, confirm, prompt and beforeunload. WebView's own dialog for one
        // would stand over the lock view, in a window FLAG_SECURE does not
        // cover, with whatever text the script chose. The app never uses them,
        // so while it is locked they are answered as if dismissed.

        override fun onJsAlert(view: WebView, url: String?, message: String?, result: JsResult): Boolean =
            refusedWhileLocked(result) || super.onJsAlert(view, url, message, result)

        override fun onJsConfirm(view: WebView, url: String?, message: String?, result: JsResult): Boolean =
            refusedWhileLocked(result) || super.onJsConfirm(view, url, message, result)

        override fun onJsPrompt(
            view: WebView,
            url: String?,
            message: String?,
            defaultValue: String?,
            result: JsPromptResult,
        ): Boolean = refusedWhileLocked(result) || super.onJsPrompt(view, url, message, defaultValue, result)

        override fun onJsBeforeUnload(view: WebView, url: String?, message: String?, result: JsResult): Boolean =
            refusedWhileLocked(result) || super.onJsBeforeUnload(view, url, message, result)

        private fun refusedWhileLocked(result: JsResult): Boolean {
            if (!lock.locked) return false
            result.cancel()
            return true
        }
    }

    @Deprecated("Activity result API; this client takes no AndroidX")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQUEST_FILE && requestCode != REQUEST_SAVE) {
            @Suppress("DEPRECATION")
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        // A picker can come back to a locked window: it stayed open
        // AppLock.AWAY_MS or more, or Android ended the app meanwhile. Its
        // answer waits for the unlock (runHeld), so the page takes it, and says
        // how it went, where the user can see it. On Android 11 it can also come
        // before onStart, which is where the lock takes hold again, so it waits
        // for that too.
        if (HostProtocol.holdsResult(started, lock.locked)) {
            heldResults += HeldResult(requestCode, resultCode, data)
            return
        }
        deliverResult(requestCode, resultCode, data)
    }

    private fun deliverResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_FILE) {
            fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            fileCallback = null
        } else {
            finishSave(resultCode, data)
        }
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
        val text = if (dark) 0xFF1A1814.toInt() else 0xFFF4F1E8.toInt()
        splashText.setTextColor(text)
        lock.textColour(text)
    }

    // ── back ────────────────────────────────────────────────────────────────

    /// Back closes the page's top layer, then walks its history, then leaves;
    /// while the app is locked it moves the task to the back. On 13 and later
    /// that is an OnBackInvokedCallback held only while there is a layer or
    /// history to walk, or while the app is locked, so the system's own
    /// back-to-home gesture plays otherwise; and an app targeting 16 is never
    /// sent onBackPressed at all.
    private fun syncBack() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val want = HostProtocol.wantsBackCallback(pageLayers, showingOurPage(), canWalkBack(), lock.locked)
        val registered = backCallback
        if (want && registered == null) {
            // Registered for a reason that has since gone, so drop it and the
            // next Back reaches the system.
            val callback = OnBackInvokedCallback { if (!routeBack()) syncBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
            backCallback = callback
        } else if (!want && registered != null) {
            onBackInvokedDispatcher.unregisterOnBackInvokedCallback(registered as OnBackInvokedCallback)
            backCallback = null
        }
    }

    /// False when Back is not the app's to handle: no layer, no history, and not locked.
    private fun routeBack(): Boolean {
        when (HostProtocol.backAction(pageLayers, showingOurPage(), canWalkBack(), lock.locked)) {
            HostProtocol.BackAction.PAGE -> sendEvent(HostProtocol.backEvent())
            HostProtocol.BackAction.HISTORY -> web.goBack()
            HostProtocol.BackAction.MOVE_TO_BACK -> moveTaskToBack(true)
            HostProtocol.BackAction.SYSTEM -> return false
        }
        return true
    }

    /// Android 11 and 12 only. On 13 and later the OnBackInvokedCallback in
    /// syncBack is what runs, which is what the lint check asks for; it cannot
    /// see that this override is the fallback for the versions without one.
    @SuppressLint("GestureBackNavigation")
    @Deprecated("Used below Android 13 only; see syncBack")
    override fun onBackPressed() {
        if (!routeBack()) @Suppress("DEPRECATION") super.onBackPressed()
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
                            if (resumed && !lock.locked) launchInstaller()
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
        lock.onStart()
        started = true
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
        refreshEnv()
        lock.onResume()
        runHeld()
        // Back from the "install unknown apps" screen, or the installer.
        if (loaded) refreshStrip()
    }

    override fun onPause() {
        resumed = false
        hapticGate.reset()
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
        if (::web.isInitialized) {
            applyTextZoom()
            refreshEnv()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (loaded) outState.putString(KEY_PATH, currentPath())
        // The payload is at most 512 Ki characters and is written only while a
        // picker is open, which is the only time a process death could lose it.
        if (pickerOpen) {
            outState.putBoolean(KEY_SAVE_OPEN, true)
            saveRequest?.let { r ->
                runCatching { stashFile().apply { parentFile?.mkdirs() }.writeText(r.text) }
                outState.putString(KEY_SAVE_NAME, r.name)
                outState.putString(KEY_SAVE_MIME, r.mime)
            }
            // The picker has answered, but to a locked window, so the answer waits
            // for the unlock. It goes with the payload, so a window rebuilt
            // meanwhile writes the file after its own unlock instead of waiting for
            // an answer that has already come.
            heldResults.lastOrNull { it.requestCode == REQUEST_SAVE }?.let {
                outState.putInt(KEY_HELD_SAVE_CODE, it.resultCode)
                outState.putParcelable(KEY_HELD_SAVE_DATA, it.data)
            }
        }
    }

    override fun onStop() {
        started = false
        lock.onStop()
        super.onStop()
    }

    override fun onDestroy() {
        main.removeCallbacks(splashCap)
        if (::lock.isInitialized) lock.onDestroy()
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
        const val REQUEST_SAVE = 2
        const val KEY_SAVE_OPEN = "save_open"
        const val KEY_SAVE_NAME = "save_name"
        const val KEY_SAVE_MIME = "save_mime"
        const val KEY_HELD_SAVE_CODE = "held_save_code"
        const val KEY_HELD_SAVE_DATA = "held_save_data"
        const val STASH = "export/pending"
        const val RECHECK_MS = 6 * 60 * 60 * 1000L
        const val RETRY_MS = 15 * 60 * 1000L
    }
}
