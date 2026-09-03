using System.Net;
using System.Net.Http.Headers;
using System.Text;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The static-file resolver and the cookie rewriter.
///
/// Audit finding: the Windows client had no tests at all, and these are the two
/// places in it where a mistake is a security bug — one decides which files on
/// disk a page can read, the other decides what the browser does with a session
/// cookie. Both were previously covered only by reading them.
public sealed class LocalServerTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-ls").FullName;
    private readonly LocalServer _server;
    private readonly string _root;

    public LocalServerTests()
    {
        _root = Path.Combine(_dir, "web");
        Directory.CreateDirectory(Path.Combine(_root, "assets"));
        File.WriteAllText(Path.Combine(_root, "index.html"), "<!doctype html>");
        File.WriteAllText(Path.Combine(_root, "assets", "app.js"), "export {}");

        // A file just outside the root, and a sibling directory whose name merely
        // starts with the root's — the prefix check has to reject both.
        File.WriteAllText(Path.Combine(_dir, "secret.txt"), "not yours");
        Directory.CreateDirectory(Path.Combine(_dir, "webby"));
        File.WriteAllText(Path.Combine(_dir, "webby", "secret.txt"), "also not yours");

        // Never Start()ed: Resolve is pure path arithmetic and binding a port
        // would make the suite depend on what else is listening.
        _server = new LocalServer(_root, "https://tasks.example.test", 48231);
    }

    public void Dispose()
    {
        _server.Dispose();
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    // ── the traversal guard ────────────────────────────────────────────────

    [Theory]
    [InlineData("/../secret.txt")]                      // plain
    [InlineData("/assets/../../secret.txt")]            // climbing back out
    [InlineData("/%2e%2e/secret.txt")]                  // percent-encoded
    [InlineData("/%2e%2e%2fsecret.txt")]                // separator encoded too
    public void Resolve_refuses_a_path_outside_the_web_root(string url)
    {
        Assert.Null(_server.Resolve(url));
    }

    [Fact]
    public void Resolve_refuses_a_sibling_directory_that_starts_with_the_root_name()
    {
        // Worth its own test because it is the case a naive `StartsWith(_root)`
        // lets through: "/tmp/x/webby/secret.txt" does start with "/tmp/x/web".
        // The separator in the comparison is what makes it fail.
        Assert.Null(_server.Resolve("/../webby/secret.txt"));
    }

    // ── the control: ordinary requests still work ──────────────────────────

    [Fact]
    public void Resolve_returns_a_real_asset()
    {
        var hit = _server.Resolve("/assets/app.js");
        Assert.NotNull(hit);
        Assert.Equal(Path.Combine(_root, "assets", "app.js"), hit);
    }

    [Fact]
    public void Resolve_maps_the_bare_root_to_index_html()
    {
        Assert.Equal(Path.Combine(_root, "index.html"), _server.Resolve("/"));
    }

    [Fact]
    public void Resolve_returns_null_for_a_client_side_route()
    {
        // Not a rejection — the caller turns null into the SPA fallback, which is
        // how /book/<token> and the tab routes reach index.html.
        Assert.Null(_server.Resolve("/book/abc123"));
    }

    // ── the cookie rewriter ────────────────────────────────────────────────

    [Fact]
    public void LocaliseCookie_drops_domain_and_secure_and_downgrades_samesite()
    {
        var localised = LocalServer.LocaliseCookie(
            "session=abc; Path=/; Domain=tasks.example.test; Secure; HttpOnly; SameSite=None");

        Assert.DoesNotContain("Domain=", localised, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Secure", localised, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("SameSite=Lax", localised, StringComparison.OrdinalIgnoreCase);
        // The parts that carry the session must survive intact.
        Assert.Contains("session=abc", localised, StringComparison.Ordinal);
        Assert.Contains("HttpOnly", localised, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Path=/", localised, StringComparison.Ordinal);
    }

    [Fact]
    public void LocaliseCookie_leaves_an_ordinary_cookie_alone()
    {
        // The control. A cookie with none of the three attributes must come back
        // byte-for-byte, or the rewriter is chewing on cookies it has no business
        // touching.
        const string plain = "theme=dark; Path=/; Max-Age=31536000; SameSite=Lax";
        Assert.Equal(plain, LocalServer.LocaliseCookie(plain));
    }

    [Fact]
    public void LocaliseCookie_keeps_samesite_strict()
    {
        // Only None has to go (it is invalid without Secure, which is also going).
        const string strict = "session=abc; Path=/; SameSite=Strict";
        Assert.Equal(strict, LocalServer.LocaliseCookie(strict));
    }
}

/// The document WebView2 runs carries the same Content-Security-Policy the
/// browser deployment gets.
///
/// **CLOSED** (2026-08-25 sweep, stage 2). This shipped as a PAIR, because xunit
/// has no `xfail` and a `Skip` stays skipped after the fix lands — green, silent,
/// and exactly the half of the harness `docs/STAGES.md` exists to defend. So a
/// live test asserted the DEFECT and went red the moment a policy was emitted,
/// and these carry the assertions actually worth keeping. Un-skipping them and
/// deleting that one was the whole of the ritual, and it has been performed —
/// the alarm fired with its own instructions, which is what it was for.
///
/// What was wrong: the app's CSP existed only as a response header the BACKEND
/// attaches
/// (`tasksd/csp.py::CSPMiddleware`), derived at startup from the served
/// index.html so it can carry the sha256 of the inline pre-paint script.
/// `frontend/index.html` has no `http-equiv` meta — verified, zero occurrences —
/// so in the desktop client, where `ServeStatic` set exactly Content-Type and
/// Cache-Control, the document had no policy at all: no `default-src 'self'`, no
/// `connect-src 'self'`, no `object-src 'none'`, no script-hash allowlist. On the
/// one surface that also holds a live session cookie for the real server.
///
/// Unlike the tests above this one, these have to START the server: the header
/// set is what is under test, and `Resolve` is pure path arithmetic that never
/// sees a response. A free port is chosen by `ChoosePort`, as the app does.
public sealed class LocalServerCspTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-csp").FullName;
    private readonly LocalServer _server;

    // The shape frontend/index.html actually has: a pre-paint script inline in
    // the document, which is why the backend's policy carries a hash rather than
    // just 'self'.
    private const string InlineScript = "document.documentElement.dataset.theme='dark'";

    public LocalServerCspTests()
    {
        var root = Path.Combine(_dir, "web");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "index.html"),
            $"<!doctype html><html><head><script>{InlineScript}</script></head><body></body></html>");

        _server = new LocalServer(root, "https://tasks.example.test", 48311);
        _server.Start();
    }

    public void Dispose()
    {
        _server.Dispose();
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    [Fact]
    public async Task TheDocumentCarriesAPolicy()
    {
        using var http = new HttpClient();
        using var res = await http.GetAsync($"{_server.Origin}/");
        res.EnsureSuccessStatusCode();

        Assert.True(res.Headers.TryGetValues("Content-Security-Policy", out var csp),
            "the desktop document is served with no Content-Security-Policy; every "
            + "directive the browser deployment relies on is silently absent here");

        var policy = string.Join(" ", csp!);
        // The CLASS of the corrected answer, not a particular directive string:
        // any real policy bounds the default fetch directive. What must not pass
        // is an empty header, or one naming only a field already allowlisted
        // elsewhere.
        Assert.Contains("default-src", policy);
        Assert.Contains("'self'", policy);

        // Asked for in the same breath by the finding, and free once a header is
        // being written at all.
        Assert.True(res.Headers.TryGetValues("X-Content-Type-Options", out var nosniff)
            && string.Join(" ", nosniff!).Contains("nosniff"),
            "no X-Content-Type-Options: nosniff on the static response");
    }

    [Fact]
    public async Task ThePolicyCarriesTheHashOfTheScriptActuallyServed()
    {
        // The half that makes the policy real rather than decorative, and the
        // desktop twin of test_csp.py's
        // `test_the_header_carries_the_hash_of_the_index_that_is_actually_served`.
        //
        // A `script-src 'self'` with no hash BLOCKS the inline pre-paint script,
        // which is a blank window — so a policy that merely exists is not the
        // corrected answer. The hash has to come from the file on disk: Vite
        // rewrites that script on build, so anything written down in the C#
        // would already disagree with what is shipped.
        //
        // Computed here rather than by calling `PolicyFor`, deliberately: a test
        // that asked the production code would agree with any hashing bug it has.
        var expected = "'sha256-" + Convert.ToBase64String(
            System.Security.Cryptography.SHA256.HashData(
                System.Text.Encoding.UTF8.GetBytes(InlineScript))) + "'";

        using var http = new HttpClient();
        using var res = await http.GetAsync($"{_server.Origin}/");
        res.EnsureSuccessStatusCode();
        var policy = string.Join(" ", res.Headers.GetValues("Content-Security-Policy"));

        Assert.Contains(expected, policy);
        // `script-src` must never gain 'unsafe-inline': CSP3 ignores it while a
        // hash is present and honours it the moment the hash goes away, silently
        // turning a real policy into a decorative one. csp.py asserts the same
        // thing on the backend side.
        Assert.DoesNotContain("unsafe-inline", policy.Split("script-src")[1].Split(';')[0]);
    }

    [Fact]
    public async Task EveryStaticResponseCarriesExactlyOnePolicy()
    {
        // CSPMiddleware attaches the header to every response and says why: it
        // costs one header on an asset and means there is no path, present or
        // future, that quietly escapes the policy. The SPA fallback is the case
        // that matters — /book/<token> and every tab route serve the document
        // through `Resolve(...) ?? index.html`, so a policy hung off the URL
        // rather than off the response would miss all of them.
        using var http = new HttpClient();
        using var document = await http.GetAsync($"{_server.Origin}/");
        using var route = await http.GetAsync($"{_server.Origin}/book/abc123");

        var first = string.Join(" ", document.Headers.GetValues("Content-Security-Policy"));
        Assert.Contains("default-src 'self'", first);
        Assert.Equal(first, string.Join(" ", route.Headers.GetValues("Content-Security-Policy")));
        // Exactly one, never two: browsers enforce the INTERSECTION of every
        // policy present, so a duplicate is indistinguishable from a deliberate
        // tightening.
        Assert.Single(document.Headers.GetValues("Content-Security-Policy"));
    }
}


/// The desktop bridge as the page reaches it: /desktop/* on the local server.
///
/// The bridge's IMPLEMENTATION is a window and cannot run here, but its
/// contract can — the route parsing, the guards and the answer — against a
/// fake that records what it was asked. This is where the floating window's
/// `/desktop/window` route is proven, since the form behind it is only ever
/// compiled on a Windows runner and only ever seen on a real machine.
///
/// Started, like the CSP tests above, because a route is a response. A free
/// port distinct from theirs, so the two classes can run side by side.
public sealed class LocalServerBridgeTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-bridge").FullName;
    private readonly LocalServer _server;
    private readonly FakeBridge _bridge = new();

    private sealed class FakeBridge : IDesktopBridge
    {
        public readonly List<string> Calls = new();
        public string State() => "{\"available\":true,\"floating\":false,\"pinned\":true}";
        public void Appearance(string? background) => Calls.Add($"appearance:{background}");
        public void Icon(string? choice, bool startMenuShortcut) => Calls.Add($"icon:{choice}:{startMenuShortcut}");
        public void Float() => Calls.Add("float");
        public void Dock() => Calls.Add("dock");
        public void Pin(bool onTop) => Calls.Add($"pin:{onTop}");
        public void Drag() => Calls.Add("drag");
    }

    public LocalServerBridgeTests()
    {
        var root = Path.Combine(_dir, "web");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "index.html"), "<!doctype html>");
        _server = new LocalServer(root, "https://tasks.example.test", 48411) { Bridge = _bridge };
        _server.Start();
    }

    public void Dispose()
    {
        _server.Dispose();
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    private async Task<HttpResponseMessage> PostAsync(string path, string json, string? origin = null)
    {
        using var http = new HttpClient();
        using var req = new HttpRequestMessage(HttpMethod.Post, $"{_server.Origin}{path}")
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };
        if (origin is not null) req.Headers.TryAddWithoutValidation("Origin", origin);
        return await http.SendAsync(req);
    }

    [Fact]
    public async Task TheWindowRouteReachesTheBridgeAndAnswersWithItsState()
    {
        using var res = await PostAsync("/desktop/window", "{\"action\":\"pin\",\"pinned\":false}");
        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        Assert.Equal(_bridge.State(), await res.Content.ReadAsStringAsync());
        Assert.True(res.Headers.CacheControl?.NoStore, "host state must never be cached");

        foreach (var action in new[] { "float", "dock", "drag" })
        {
            using var r = await PostAsync("/desktop/window", $"{{\"action\":\"{action}\"}}");
            Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        }
        Assert.Equal(new[] { "pin:False", "float", "dock", "drag" }, _bridge.Calls);
    }

    [Fact]
    public async Task AnActionTheHostDoesNotKnowIsRefusedAndNothingIsCalled()
    {
        using var unknown = await PostAsync("/desktop/window", "{\"action\":\"explode\"}");
        Assert.Equal(HttpStatusCode.BadRequest, unknown.StatusCode);
        // `pin` with nothing to pin to, and with a string where a boolean goes:
        // both are 400, not "pinned: false".
        using var bare = await PostAsync("/desktop/window", "{\"action\":\"pin\"}");
        Assert.Equal(HttpStatusCode.BadRequest, bare.StatusCode);
        using var stringy = await PostAsync("/desktop/window", "{\"action\":\"pin\",\"pinned\":\"yes\"}");
        Assert.Equal(HttpStatusCode.BadRequest, stringy.StatusCode);
        using var junk = await PostAsync("/desktop/window", "not json");
        Assert.Equal(HttpStatusCode.BadRequest, junk.StatusCode);
        Assert.Empty(_bridge.Calls);
    }

    [Fact]
    public async Task ThePageOnAnotherOriginCannotDriveTheWindow()
    {
        using var res = await PostAsync("/desktop/window", "{\"action\":\"float\"}", origin: "https://evil.example");
        Assert.Equal(HttpStatusCode.Forbidden, res.StatusCode);
        Assert.Empty(_bridge.Calls);
        // The page's own origin is fine, in either case.
        using var ok = await PostAsync("/desktop/window", "{\"action\":\"float\"}", origin: _server.Origin.ToUpperInvariant());
        Assert.Equal(HttpStatusCode.OK, ok.StatusCode);
    }

    [Fact]
    public async Task TheRouteIsPostOnlyAndAbsentWithoutAWindow()
    {
        using var http = new HttpClient();
        using var get = await http.GetAsync($"{_server.Origin}/desktop/window");
        Assert.Equal(HttpStatusCode.MethodNotAllowed, get.StatusCode);

        using var state = await http.GetAsync($"{_server.Origin}/desktop/state");
        Assert.Equal(HttpStatusCode.OK, state.StatusCode);
        Assert.Equal(_bridge.State(), await state.Content.ReadAsStringAsync());

        // In a real browser these paths reach the deployed server and 404; with
        // no window behind the local one they answer the same, which is how the
        // page tells the two apart.
        _server.Bridge = null;
        using var gone = await PostAsync("/desktop/window", "{\"action\":\"float\"}");
        Assert.Equal(HttpStatusCode.NotFound, gone.StatusCode);
        Assert.Empty(_bridge.Calls);
    }
}
