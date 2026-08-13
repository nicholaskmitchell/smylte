using System.Net;
using System.Net.Sockets;
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

        var bytes = File.ReadAllBytes(file);
        ctx.Response.ContentLength64 = bytes.Length;
        ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
    }

    /// null when the path is not a real file, which the caller turns into the
    /// SPA fallback — /book/&lt;token&gt; and the tab routes are client-side.
    private string? Resolve(string urlPath)
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
