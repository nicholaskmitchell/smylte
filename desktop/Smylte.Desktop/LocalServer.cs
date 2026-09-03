using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Smylte.Desktop;

/// Serves the CI-built SPA off local disk and forwards /api to the real server.
///
/// The split is the whole point of the client: HTML, CSS, JS and fonts come from
/// disk at no network cost, while the API keeps talking to the one server that
/// owns the CalDAV write path. Nothing here is a cache of API data — the SPA
/// already keeps its own in localStorage.
public sealed class LocalServer : IDisposable
{
    private readonly HttpListener _listener = new();
    private readonly HttpClient _http;
    private readonly CancellationTokenSource _cts = new();
    private readonly string _root;
    private readonly Uri _upstream;
    private readonly string _csp;

    public int Port { get; }
    public string Origin => $"http://localhost:{Port}";

    public LocalServer(string webRoot, string serverUrl, int preferredPort)
    {
        _root = Path.GetFullPath(webRoot).TrimEnd(Path.DirectorySeparatorChar);
        _upstream = new Uri(serverUrl.TrimEnd('/') + "/");
        Port = ChoosePort(preferredPort);

        // Three deliberate choices, each of which breaks the proxy if reversed:
        //   UseCookies=false          the browser owns the session; this only relays it
        //   AutomaticDecompression    off, so encoded bytes and their Content-Encoding
        //                             header always travel as a matched pair
        //   Timeout=Infinite          /api/events is a stream, not a request
        _http = new HttpClient(new SocketsHttpHandler
        {
            UseCookies = false,
            AutomaticDecompression = DecompressionMethods.None,
            AllowAutoRedirect = false,
        })
        {
            Timeout = Timeout.InfiniteTimeSpan,
        };

        _listener.Prefixes.Add($"http://localhost:{Port}/");

        // Read ONCE, here, the way the backend does it (app.py reads the served
        // index.html at startup for the same reason). MainForm awaits
        // Updater.EnsureWebAssetsAsync before constructing this, so the file on
        // disk is already the build that will be served.
        _csp = PolicyFor(Path.Combine(_root, "index.html"));
    }

    // ── Content-Security-Policy ─────────────────────────────────────────────
    //
    // A PORT of backend/tasksd/csp.py, and it has to stay a faithful one. The
    // app's policy exists only as a response header the BACKEND attaches;
    // frontend/index.html carries no `http-equiv` meta (verified, zero
    // occurrences), so the document WebView2 runs — served from disk by
    // ServeStatic, which set exactly Content-Type and Cache-Control — had NO
    // policy at all. Not `default-src 'self'`, not `connect-src 'self'`, not
    // `object-src 'none'`, not the script-hash allowlist. On the one surface
    // that also holds a live session cookie for the real server.
    //
    // What that costs, concretely: a foreign CalDAV client writes a collection
    // property or an appearance value that slips past clean_color / cssColor /
    // the appearance allowlist — the exact class of bug the audit has recorded
    // twice as a url() beacon. In the browser it is blocked by img-src 'self'
    // and never leaves the machine. In this window it fetches, and with no
    // connect-src and no script-hash restriction, any script injection here can
    // exfiltrate to an arbitrary host from an origin holding tasks_session.
    //
    // The HASH is derived from the file actually served rather than written
    // down, for the reason csp.py gives: hardcoding it puts the same string in
    // two places that must agree, and the failure when they stop agreeing is a
    // blank window — the pre-paint script blocked. Vite rewrites that script on
    // build, so a constant copied from the source would already be wrong.

    /// A `<script>` with a body to hash, i.e. not a `src=` reference. Same
    /// pattern as csp.py's `_INLINE_SCRIPT`, deliberately not an HTML parser:
    /// this reads one file we ship ourselves, and a regex that is too eager errs
    /// toward hashing something harmless while one that is too lax fails to
    /// allowlist our own script — which is loud (the app does not paint) rather
    /// than silent.
    private static readonly Regex InlineScript = new(
        @"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>",
        RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);

    /// The policy for the document at `indexPath`, or the no-inline-script
    /// policy if it cannot be read. Never throws: a missing or unreadable
    /// index.html means the updater has not landed a build yet, and refusing to
    /// construct the server over it would turn a recoverable state into a dead
    /// window.
    internal static string PolicyFor(string indexPath)
    {
        var hashes = new List<string>();
        try
        {
            foreach (Match m in InlineScript.Matches(File.ReadAllText(indexPath)))
                hashes.Add("'sha256-" + Convert.ToBase64String(
                    SHA256.HashData(Encoding.UTF8.GetBytes(m.Groups[1].Value))) + "'");
        }
        catch (IOException) { /* no build on disk yet — 'self' alone still binds */ }
        catch (UnauthorizedAccessException) { }

        var scriptSrc = hashes.Count == 0
            ? "script-src 'self'"
            : "script-src 'self' " + string.Join(" ", hashes);
        // Directive for directive, in order, with csp.py's `"; "` join and no
        // trailing semicolon. Two of these are load-bearing in a way that is easy
        // to undo by accident and are commented there: script-src must never gain
        // 'unsafe-inline' (ignored while a hash is present, honoured the moment
        // the hash goes away), and style-src must never gain a hash or a nonce
        // (either makes browsers ignore 'unsafe-inline', which this SPA cannot
        // live without — every calendar and list colour is an inline style).
        return string.Join("; ", new[]
        {
            "default-src 'self'",
            "base-uri 'none'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "img-src 'self'",
            "connect-src 'self'",
            scriptSrc,
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
        });
    }

    public void Start()
    {
        _listener.Start();
        _ = Task.Run(AcceptLoop);
    }

    private async Task AcceptLoop()
    {
        while (!_cts.IsCancellationRequested)
        {
            HttpListenerContext ctx;
            try
            {
                ctx = await _listener.GetContextAsync().ConfigureAwait(false);
            }
            catch (HttpListenerException) { return; }   // listener stopped
            catch (ObjectDisposedException) { return; }
            catch (InvalidOperationException) { return; }

            _ = Task.Run(() => HandleAsync(ctx));
        }
    }

    private async Task HandleAsync(HttpListenerContext ctx)
    {
        try
        {
            var path = ctx.Request.Url?.AbsolutePath ?? "/";
            if (path.StartsWith("/api/", StringComparison.Ordinal)
                || path.Equals("/api", StringComparison.Ordinal))
                await ProxyAsync(ctx).ConfigureAwait(false);
            else if (path.StartsWith("/desktop/", StringComparison.Ordinal))
                await DesktopAsync(ctx, path).ConfigureAwait(false);
            else
                ServeStatic(ctx, path);
        }
        catch (OperationCanceledException)
        {
            // The window closed, or the browser walked away from an SSE stream.
        }
        catch (HttpRequestException)
        {
            TrySetStatus(ctx, 502);   // server unreachable; the SPA surfaces it
        }
        catch (Exception)
        {
            TrySetStatus(ctx, 500);
        }
        finally
        {
            try { ctx.Response.Close(); } catch (Exception) { /* client already gone */ }
        }
    }

    // ── the desktop bridge ──────────────────────────────────────────────────

    /// Set by MainForm. Null in any context that has no window to talk to, in
    /// which case /desktop/* answers 404 — which is also what the SPA sees when
    /// it is running in a real browser against the deployed server, and is how
    /// it knows not to offer the desktop-only settings at all.
    public IDesktopBridge? Bridge { get; set; }

    /// Host controls the page is allowed to drive: which app icon the window
    /// wears, and what colour its caption bar is.
    ///
    /// This is the only route that is neither a proxied API call nor a file off
    /// disk, so it gets its own guards rather than inheriting either one's.
    /// HttpListener is bound to localhost already; `IsLocal` restates that, and
    /// the Origin check keeps a page on some other origin — anything the webview
    /// might be navigated to — from driving the window it is displayed in. Both
    /// are cheap, and the alternative is an open control channel on a fixed
    /// well-known port on the user's machine.
    private async Task DesktopAsync(HttpListenerContext ctx, string path)
    {
        var bridge = Bridge;
        if (bridge is null) { TrySetStatus(ctx, 404); return; }
        if (!ctx.Request.IsLocal) { TrySetStatus(ctx, 403); return; }

        var origin = ctx.Request.Headers["Origin"];
        if (!string.IsNullOrEmpty(origin)
            && !string.Equals(origin, Origin, StringComparison.OrdinalIgnoreCase))
        {
            TrySetStatus(ctx, 403);
            return;
        }

        if (path == "/desktop/state" && ctx.Request.HttpMethod == "GET")
        {
            await WriteJsonAsync(ctx, bridge.State()).ConfigureAwait(false);
            return;
        }

        if (ctx.Request.HttpMethod != "POST") { TrySetStatus(ctx, 405); return; }

        JsonElement body;
        try
        {
            using var reader = new StreamReader(ctx.Request.InputStream, Encoding.UTF8);
            var text = await reader.ReadToEndAsync().ConfigureAwait(false);
            body = JsonDocument.Parse(text).RootElement;
        }
        catch (Exception)
        {
            TrySetStatus(ctx, 400);
            return;
        }

        switch (path)
        {
            case "/desktop/appearance":
                bridge.Appearance(Str(body, "background"));
                break;
            case "/desktop/icon":
                bridge.Icon(Str(body, "choice"), Bool(body, "startMenuShortcut"));
                break;
            case "/desktop/window":
                // The floating focus window. An action the host does not know,
                // or a `pin` without a boolean to pin to, is a 400 rather than a
                // silent no-op: the page reconciles from the State() this
                // answers with, and a request that changed nothing must not
                // read as one that did.
                switch (Str(body, "action"))
                {
                    case "float": bridge.Float(); break;
                    case "dock": bridge.Dock(); break;
                    case "drag": bridge.Drag(); break;
                    case "pin":
                        if (BoolOrNull(body, "pinned") is not { } onTop)
                        {
                            TrySetStatus(ctx, 400);
                            return;
                        }
                        bridge.Pin(onTop);
                        break;
                    default:
                        TrySetStatus(ctx, 400);
                        return;
                }
                break;
            default:
                TrySetStatus(ctx, 404);
                return;
        }
        await WriteJsonAsync(ctx, bridge.State()).ConfigureAwait(false);
    }

    private static string? Str(JsonElement o, string name) =>
        o.ValueKind == JsonValueKind.Object && o.TryGetProperty(name, out var v)
        && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    private static bool Bool(JsonElement o, string name) =>
        o.ValueKind == JsonValueKind.Object && o.TryGetProperty(name, out var v)
        && v.ValueKind == JsonValueKind.True;

    /// A JSON boolean, or null for anything else — for a field where "absent"
    /// and "false" must not read the same, as `Bool` above lets them.
    private static bool? BoolOrNull(JsonElement o, string name)
    {
        if (o.ValueKind != JsonValueKind.Object || !o.TryGetProperty(name, out var v)) return null;
        return v.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => null,
        };
    }

    private static async Task WriteJsonAsync(HttpListenerContext ctx, string json)
    {
        var bytes = Encoding.UTF8.GetBytes(json);
        ctx.Response.StatusCode = 200;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.ContentLength64 = bytes.Length;
        // Never cached: it is live host state, and the SPA re-reads it to decide
        // whether the desktop-only settings exist at all.
        ctx.Response.Headers["Cache-Control"] = "no-store";
        await ctx.Response.OutputStream.WriteAsync(bytes).ConfigureAwait(false);
    }

    // ── proxy ───────────────────────────────────────────────────────────────

    /// Headers that describe *this* hop and must not be relayed to the next one.
    /// Content-Length is in here because every proxied response is chunked.
    private static readonly HashSet<string> HopByHop = new(StringComparer.OrdinalIgnoreCase)
    {
        "Connection", "Keep-Alive", "Proxy-Authenticate", "Proxy-Authorization",
        "TE", "Trailer", "Transfer-Encoding", "Upgrade", "Host", "Content-Length",
    };

    private async Task ProxyAsync(HttpListenerContext ctx)
    {
        var ct = _cts.Token;
        var target = new Uri(_upstream, ctx.Request.Url!.PathAndQuery.TrimStart('/'));

        using var req = new HttpRequestMessage(new HttpMethod(ctx.Request.HttpMethod), target);
        if (ctx.Request.HasEntityBody)
            req.Content = new StreamContent(ctx.Request.InputStream);

        foreach (var name in ctx.Request.Headers.AllKeys)
        {
            if (name is null || HopByHop.Contains(name)) continue;
            var value = ctx.Request.Headers[name];
            if (value is null) continue;
            if (!req.Headers.TryAddWithoutValidation(name, value))
                req.Content?.Headers.TryAddWithoutValidation(name, value);
        }
        req.Headers.Host = _upstream.IsDefaultPort
            ? _upstream.Host
            : $"{_upstream.Host}:{_upstream.Port}";

        using var up = await _http
            .SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct)
            .ConfigureAwait(false);

        ctx.Response.StatusCode = (int)up.StatusCode;
        CopyHeaders(up.Headers, ctx.Response);
        CopyHeaders(up.Content.Headers, ctx.Response);

        if (ctx.Response.StatusCode is 204 or 304) return;

        // Chunked, and flushed after every read. Both are required, and getting
        // either wrong fails silently rather than loudly: /api/events is the SSE
        // stream every live update in the app rides on (see api.ts subscribe()),
        // and a buffering proxy leaves it connected but permanently empty.
        ctx.Response.SendChunked = true;

        var src = await up.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await using (src.ConfigureAwait(false))
        {
            var buffer = new byte[8192];
            int read;
            while ((read = await src.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
            {
                await ctx.Response.OutputStream
                    .WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
                await ctx.Response.OutputStream.FlushAsync(ct).ConfigureAwait(false);
            }
        }
    }

    private static void CopyHeaders(
        IEnumerable<KeyValuePair<string, IEnumerable<string>>> from, HttpListenerResponse to)
    {
        foreach (var header in from)
        {
            if (HopByHop.Contains(header.Key)) continue;

            var isCookie = string.Equals(header.Key, "Set-Cookie", StringComparison.OrdinalIgnoreCase);
            foreach (var value in header.Value)
            {
                try
                {
                    to.AppendHeader(header.Key, isCookie ? LocaliseCookie(value) : value);
                }
                catch (ArgumentException)
                {
                    // HttpListener reserves a handful of headers (Date, Server).
                    // Losing them is harmless; failing the response is not.
                }
            }
        }
    }

    private static readonly Regex CookieDomain =
        new(@";\s*Domain=[^;]*", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex CookieSecure =
        new(@";\s*Secure\b", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex CookieSameSiteNone =
        new(@";\s*SameSite\s*=\s*None\b", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    /// Re-point a cookie minted for the real host at http://localhost.
    ///
    /// Domain goes because it pins the cookie to a host the browser is no longer
    /// talking to. Secure goes because this origin is plain HTTP — Chromium does
    /// treat localhost as trustworthy and might keep it anyway, but relying on
    /// that is a bet with no upside. SameSite=None has to go with Secure, since
    /// the pair is only valid together; Lax is right regardless, because from the
    /// browser's side every request here is now same-origin.
    internal static string LocaliseCookie(string raw)
    {
        var cookie = CookieDomain.Replace(raw, "");
        cookie = CookieSameSiteNone.Replace(cookie, "; SameSite=Lax");
        return CookieSecure.Replace(cookie, "");
    }

    // ── static files ────────────────────────────────────────────────────────

    private static readonly Dictionary<string, string> Mime = new(StringComparer.OrdinalIgnoreCase)
    {
        [".html"] = "text/html; charset=utf-8",
        [".js"] = "text/javascript; charset=utf-8",
        [".css"] = "text/css; charset=utf-8",
        [".json"] = "application/json; charset=utf-8",
        [".svg"] = "image/svg+xml",
        [".png"] = "image/png",
        [".ico"] = "image/x-icon",
        [".woff2"] = "font/woff2",
        [".woff"] = "font/woff",
        [".txt"] = "text/plain; charset=utf-8",
        [".map"] = "application/json",
        [".webmanifest"] = "application/manifest+json",
    };

    private void ServeStatic(HttpListenerContext ctx, string urlPath)
    {
        var file = Resolve(urlPath) ?? Path.Combine(_root, "index.html");
        if (!File.Exists(file)) { ctx.Response.StatusCode = 404; return; }

        var ext = Path.GetExtension(file);
        ctx.Response.ContentType = Mime.TryGetValue(ext, out var mime)
            ? mime : "application/octet-stream";

        // index.html has to be re-read every launch or an updated build would
        // keep pointing at the previous bundle. Everything else is either
        // content-hashed by Vite or carries a ?v= query.
        ctx.Response.AddHeader("Cache-Control",
            ext.Equals(".html", StringComparison.OrdinalIgnoreCase)
                ? "no-cache"
                : "public, max-age=31536000, immutable");

        // On EVERY static response, not just the document — CSPMiddleware makes
        // the same choice and gives the same reason: it costs one header on an
        // asset and means there is no path, present or future, that quietly
        // escapes the policy. AddHeader REPLACES where AppendHeader would add a
        // second; browsers enforce the intersection of every policy present, so
        // a duplicate is indistinguishable from a deliberate tightening.
        ctx.Response.AddHeader("Content-Security-Policy", _csp);
        ctx.Response.AddHeader("X-Content-Type-Options", "nosniff");

        var bytes = File.ReadAllBytes(file);
        ctx.Response.ContentLength64 = bytes.Length;
        ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
    }

    /// null when the path is not a real file, which the caller turns into the
    /// SPA fallback — /book/&lt;token&gt; and the tab routes are client-side.
    /// `internal` rather than private so the test project — which links this
    /// file rather than referencing the WinForms assembly — can reach it. This
    /// guard is one of the two places in the client where a mistake is a
    /// security bug rather than a cosmetic one.
    internal string? Resolve(string urlPath)
    {
        var relative = Uri.UnescapeDataString(urlPath).TrimStart('/');
        if (relative.Length == 0) relative = "index.html";

        var full = Path.GetFullPath(Path.Combine(
            _root, relative.Replace('/', Path.DirectorySeparatorChar)));

        // Anything that climbed out of the web root is not ours to serve.
        if (!full.StartsWith(_root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            return null;

        return File.Exists(full) ? full : null;
    }

    // ── plumbing ────────────────────────────────────────────────────────────

    private static void TrySetStatus(HttpListenerContext ctx, int status)
    {
        try { ctx.Response.StatusCode = status; } catch (Exception) { /* headers sent */ }
    }

    private static int ChoosePort(int preferred)
    {
        for (var port = preferred; port < preferred + 50; port++)
            if (IsFree(port)) return port;

        // Fifty consecutive ports taken is not a real scenario, but falling back
        // to an ephemeral one beats refusing to start. The cost is that the SPA
        // sees a new origin and starts from an empty localStorage.
        var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        var chosen = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        return chosen;
    }

    private static bool IsFree(int port)
    {
        try
        {
            var probe = new TcpListener(IPAddress.Loopback, port);
            probe.Start();
            probe.Stop();
            return true;
        }
        catch (SocketException)
        {
            return false;
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        try { _listener.Stop(); } catch (Exception) { /* already stopped */ }
        try { _listener.Close(); } catch (Exception) { /* already closed */ }
        _http.Dispose();
        _cts.Dispose();
    }
}
