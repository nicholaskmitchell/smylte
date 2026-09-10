using System.Runtime.InteropServices;

namespace Smylte.Desktop;

/// The engine, and the one session both windows share.
///
/// This is the counterpart of the `CoreWebView2Environment` the Windows client
/// creates once and hands to both forms. On WebKitGTK the equivalent is a
/// `WebKitNetworkSession` rooted at a directory, passed to every view as a
/// CONSTRUCT property — there is no `webkit_web_view_new_with_session`, so the
/// only way in is `g_object_new`, which GirCore spells `NewWithProperties`.
///
/// Sharing it is not an optimisation. The floating window is the same page at a
/// small size and has to be the same logged-in user; a second session would
/// give it a second cookie jar and its own login screen.
internal sealed class WebHost : IDisposable
{
    /// GirCore's own resolver asks for exactly this soname, and so does
    /// NativeCheck. The two functions below are declared by hand because
    /// GirCore generates no awaitable wrapper for them — see SeedAsync.
    private const string WebKitSo = "libwebkitgtk-6.0.so.4";

    private readonly Settings _settings;
    public WebKit.NetworkSession Session { get; }

    public WebHost(Settings settings)
    {
        _settings = settings;

        var profile = settings.BrowserProfile;
        var cache = Path.Combine(profile, "cache");
        Directory.CreateDirectory(profile);
        Directory.CreateDirectory(cache);

        Session = WebKit.NetworkSession.New(profile, cache);

        // WebView2 persists cookies for a user-data folder implicitly; WebKit
        // does not, and without this every launch starts signed out and the
        // stored password is spent on every start. The file lands inside the
        // profile the user chose, beside localStorage, so "delete the data
        // folder" still means what it means on Windows.
        Session.GetCookieManager().SetPersistentStorage(
            Path.Combine(profile, "cookies.sqlite"), WebKit.CookiePersistentStorage.Sqlite);
    }

    /// A view bound to the shared session, configured the way the Windows
    /// client configures its two.
    ///
    /// `chromeless` is the floating window: no context menu there, matching
    /// `AreDefaultContextMenusEnabled = false` on the small window and `true` on
    /// the main one. Two WebView2 settings have no counterpart and need none —
    /// WebKitGTK draws no status bar (that popup is an Edge feature) and binds
    /// no zoom keys of its own, so `IsStatusBarEnabled` and
    /// `IsZoomControlEnabled` are already the behaviour their `false` asked for.
    public WebKit.WebView NewView(bool chromeless)
    {
        var view = WebKit.WebView.NewWithProperties(new[]
        {
            new GObject.ConstructArgument("network-session", new GObject.Value(Session)),
        });

        var settings = view.GetSettings();

        // The focus surface plays a chime when an interval ends, and nobody
        // clicks a floating clock before it does. This is the per-view analogue
        // of the WebView2 client's `--autoplay-policy=no-user-gesture-required`
        // — and unlike that one it does not have to be an environment-wide
        // decision, because WebKit hangs it off the view.
        settings.SetMediaPlaybackRequiresUserGesture(false);
        settings.SetEnableDeveloperExtras(false);
        settings.SetEnableBackForwardNavigationGestures(false);
        view.SetSettings(settings);

        // Unhandled, a permission request is DENIED, so the notifications the
        // focus surface raises would silently never appear. Same grant the
        // Windows client makes, and the same one only: nothing else is allowed.
        view.OnPermissionRequest += (_, e) =>
        {
            if (e.Request is not WebKit.NotificationPermissionRequest request) return false;
            request.Allow();
            return true;
        };

        if (chromeless) view.OnContextMenu += (_, _) => true;

        return view;
    }

    /// Trade the stored credentials for a session cookie and put it in the
    /// shared jar, so the app opens already signed in.
    ///
    /// **Await this before navigating.** WebView2's `AddOrUpdateCookie` returns
    /// when the cookie is stored; WebKit's is asynchronous, and a navigation
    /// that races it lands on the login screen — which looks exactly like a
    /// wrong password and is not.
    ///
    /// Every failure is silent and lands on that same login screen, which is
    /// what `Session.LoginAsync` returning nothing already means on Windows. So
    /// this is allowed to be best-effort in a way the rest of startup is not.
    public async Task SeedAsync(CancellationToken ct)
    {
        var cookies = await Session_LoginAsync(ct).ConfigureAwait(true);
        if (cookies.Count == 0) return;

        var manager = Session.GetCookieManager();
        foreach (var raw in cookies)
        {
            if (Smylte.Desktop.Session.ParseCookie(raw) is not { } parsed) continue;

            // Re-scoped to localhost, exactly as MainForm does it: the cookie is
            // being handed to a page served from the local origin, so the
            // original attributes no longer apply. -1 is a session cookie.
            var cookie = Soup.Cookie.New(parsed.Name, parsed.Value, "localhost", "/", -1);
            cookie.SetSecure(false);
            cookie.SetHttpOnly(true);
            try { await AddCookieAsync(manager, cookie, ct).ConfigureAwait(true); }
            catch (Exception) { /* the login screen is the fallback, and it works */ }
        }
    }

    private Task<IReadOnlyList<string>> Session_LoginAsync(CancellationToken ct) =>
        Smylte.Desktop.Session.LoginAsync(
            _settings.ServerUrl, _settings.Username, _settings.GetPassword(), ct);

    // ── webkit_cookie_manager_add_cookie, by hand ───────────────────────────
    //
    // GirCore binds the `_finish` half of this pair but generates no awaitable
    // wrapper for the pair itself, so the only alternatives were to drive its
    // Internal callback types — which are generated, and move between 0.8.x
    // releases — or to declare the two functions. Declared, for the reason
    // ShellShortcut.cs declares its COM by hand: it is two functions, and the
    // alternative is a dependency on something that is not a contract.
    //
    // The delegate is held in a field for the life of the call. A collected
    // callback that GLib then invokes is a crash in native code with no managed
    // stack, and it would happen rarely enough to look like anything else.

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void AsyncReady(IntPtr source, IntPtr result, IntPtr userData);

    [DllImport(WebKitSo)]
    private static extern void webkit_cookie_manager_add_cookie(
        IntPtr manager, IntPtr cookie, IntPtr cancellable, AsyncReady? callback, IntPtr userData);

    [DllImport(WebKitSo)]
    [return: MarshalAs(UnmanagedType.I1)]
    private static extern bool webkit_cookie_manager_add_cookie_finish(
        IntPtr manager, IntPtr result, out IntPtr error);

    /// The GError the pair hands back on failure. Freed rather than ignored:
    /// this runs once per cookie per launch, so a leak here is small — but it
    /// is a leak in the one path that only ever runs when something is already
    /// going wrong, which is the worst place to have to reason about one.
    [DllImport("libglib-2.0.so.0")]
    private static extern void g_error_free(IntPtr error);

    private readonly List<AsyncReady> _pending = new();

    private Task AddCookieAsync(WebKit.CookieManager manager, Soup.Cookie cookie, CancellationToken ct)
    {
        var done = new TaskCompletionSource();
        var managerHandle = manager.Handle.DangerousGetHandle();

        AsyncReady callback = (_, result, _) =>
        {
            try
            {
                webkit_cookie_manager_add_cookie_finish(managerHandle, result, out var error);
                if (error != IntPtr.Zero) g_error_free(error);
            }
            catch (Exception) { /* the seed is best-effort; see SeedAsync */ }
            done.TrySetResult();
        };
        _pending.Add(callback);

        webkit_cookie_manager_add_cookie(
            managerHandle, cookie.Handle.DangerousGetHandle(), IntPtr.Zero, callback, IntPtr.Zero);

        // Bounded. A seed that never completes must not hold the window shut;
        // the app would rather open on the login screen than not open.
        return Task.WhenAny(done.Task, Task.Delay(TimeSpan.FromSeconds(5), ct));
    }

    public void Dispose() => _pending.Clear();
}
