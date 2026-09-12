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

        // And a sibling that differs from the root only in CASE. On Linux this
        // is a second directory; on Windows it aliases the first. Either way
        // nothing may be served through it — see the test below for why the two
        // filesystems make the same assertion for different reasons.
        Directory.CreateDirectory(Path.Combine(_dir, "WEB"));
        File.WriteAllText(Path.Combine(_dir, "WEB", "secret.txt"), "not yours either");

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

    [Fact]
    public void Resolve_refuses_a_sibling_that_differs_from_the_root_only_in_case()
    {
        // The guard used to compare OrdinalIgnoreCase, which is the NTFS rule
        // applied to a path that may not be on NTFS. On a case-sensitive
        // filesystem "…/Smylte/WEB/secret.txt" is a genuinely different
        // directory and the check accepted it — a traversal, in the one place
        // in this client where that is a security bug rather than a cosmetic
        // one. The `webby` case above never caught it: that one fails on
        // length, not on case.
        //
        // Non-vacuous on BOTH filesystems, which is the point of asserting it
        // here rather than only on the Linux runner:
        //   case-sensitive    WEB is a second directory, and serving out of it
        //                     is the escape.
        //   case-insensitive  WEB aliases web, so this reaches a real file
        //                     through a spelling the guard was never meant to
        //                     accept — still a refusal, for a weaker reason.
        Assert.Null(_server.Resolve("/../WEB/secret.txt"));
    }

    [Fact]
    public void Resolve_still_serves_the_root_through_its_own_spelling()
    {
        // The control for the case test above. Tightening the comparison must
        // not cost the ordinary path, and "it refuses everything" would satisfy
        // every traversal assertion in this file on its own.
        Assert.NotNull(_server.Resolve("/index.html"));
    }

    // ── the control: ordinary requests still work ──────────────────────────

    [Fact]
    public void Disposing_twice_is_not_an_error()
    {
        // The startup path has two places that can own a server — the field
        // and a local inside StartAsync — and until Dispose became idempotent
        // the second call threw: `_cts.Cancel()` is the first statement and
        // `_cts.Dispose()` the last, and Cancel-after-Dispose is an
        // ObjectDisposedException. It landed in a catch block that disposed the
        // same server again, so the exception escaped a fire-and-forgotten Task
        // and took the rest of the cleanup with it.
        var started = new LocalServer(_root, "https://tasks.example.test", 48731);
        started.Start();
        started.Dispose();
        started.Dispose();

        // And on one that was constructed and never started, which is the
        // shape an overtaken start now disposes.
        var idle = new LocalServer(_root, "https://tasks.example.test", 48732);
        idle.Dispose();
        idle.Dispose();
    }

    [Fact]
    public void Constructing_a_server_does_not_take_the_port()
    {
        // Load-bearing for the startup ordering: MainWindow constructs a
        // LocalServer before it knows whether it has been overtaken and only
        // calls Start() once it has won. If constructing bound the socket, an
        // overtaken start would hold the port across a twenty-second login and
        // the next start would silently move to another one — persisting it,
        // so the SPA came back at a new origin with an empty localStorage.
        using var first = new LocalServer(_root, "https://tasks.example.test", 48741);
        using var second = new LocalServer(_root, "https://tasks.example.test", 48741);

        Assert.Equal(48741, first.Port);
        Assert.Equal(48741, second.Port);

        // There was a third assertion here — that once one of them STARTS, the
        // next one would not choose the same port — and it was wrong to make.
        // It passed on an IPv4-only machine and failed on the GitHub runner,
        // because it asserts the operating system rather than this code:
        //
        //   `HttpListener` on Unix resolves the prefix host and binds ONE
        //   address, while `ChoosePort`'s `IsFree` probes 127.0.0.1. Where
        //   `localhost` has only an A record those are the same socket and the
        //   probe sees the listener; where it also has a AAAA record they can
        //   be different families, and the probe reports a busy port free.
        //
        // Which is worth knowing — `IsFree` is blind to the other family, so
        // on a dual-stack box two instances can pick the same port and the
        // second `Start()` throws — but it is pre-existing shared code, it is
        // not what this test is for, and the single-instance lock means two
        // instances should not be racing for a port in the first place.
        //
        // What the startup ordering actually needs is above: constructing
        // binds nothing. That is true on every machine.
    }

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

    /// Sends the page's own Origin unless told otherwise, because that is what
    /// a browser does: per the Fetch standard, Origin is appended to every
    /// request whose method is not GET or HEAD, same-origin included. Pass an
    /// explicit origin to impersonate another page, or `""` to send none at
    /// all — which is what curl does, and is now refused.
    private async Task<HttpResponseMessage> PostAsync(string path, string json, string? origin = null)
    {
        using var http = new HttpClient();
        using var req = new HttpRequestMessage(HttpMethod.Post, $"{_server.Origin}{path}")
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        };
        var value = origin ?? _server.Origin;
        if (value.Length > 0) req.Headers.TryAddWithoutValidation("Origin", value);
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
    public async Task TheIconRouteReachesTheBridgeAndAnswersWithItsState()
    {
        // Untested until now, on either platform — and it is the one bridge
        // route whose argument decides whether a FILE in the user's home
        // exists: the Start-menu shortcut on Windows, the desktop entry and its
        // icon tree on Linux.
        using var res = await PostAsync(
            "/desktop/icon", "{\"choice\":\"Ink\",\"startMenuShortcut\":true}");

        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        // The answer is State(), because the page reconciles the dropdown and
        // the checkbox from it rather than from what it sent.
        Assert.Equal(_bridge.State(), await res.Content.ReadAsStringAsync());
        Assert.Equal(new[] { "icon:Ink:True" }, _bridge.Calls);
    }

    [Fact]
    public async Task AnIconPostThatOmitsTheShortcutFlagIsRefusedRatherThanReadAsOff()
    {
        // `Bool` reads an absent key as false, so a POST carrying only
        // `{"choice":"Ink"}` used to arrive at the host as
        // `Icon("Ink", startMenuShortcut: false)` — which DELETES the user's
        // launcher entry and its icons, and answers 200 so the page tickes the
        // box off to match. Nothing in the app sends that shape; `setIcon`
        // always passes both, which is why this is malformed rather than a
        // request to turn the shortcut off.
        //
        // The same rule `pin` already followed, for the same reason: absent and
        // false must not read the same on a field that changes something.
        foreach (var body in new[]
        {
            "{\"choice\":\"Ink\"}",
            "{}",
            "{\"choice\":\"Ink\",\"startMenuShortcut\":\"yes\"}",
            "{\"choice\":\"Ink\",\"startMenuShortcut\":null}",
        })
        {
            using var res = await PostAsync("/desktop/icon", body);
            Assert.Equal(HttpStatusCode.BadRequest, res.StatusCode);
        }
        Assert.Empty(_bridge.Calls);
    }

    [Fact]
    public async Task TheAppearanceRouteTakesWhateverTheThemeIsAndNeverRefuses()
    {
        // The opposite contract to the icon route above, deliberately: `--bg`
        // can be a user-authored theme value, so the host parses it and hands
        // the frame back to the system when it cannot — `Theme.ParseHex`
        // returning null is the documented answer, not a 400. A refusal here
        // would turn a bad custom theme into a failed request on every colour
        // the user drags.
        foreach (var body in new[]
        {
            "{\"background\":\"#0C0C10\"}",
            "{\"background\":\"rebeccapurple\"}",
            "{\"background\":\"\"}",
            "{}",
        })
        {
            using var res = await PostAsync("/desktop/appearance", body);
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        }
        Assert.Equal(
            new[] { "appearance:#0C0C10", "appearance:rebeccapurple", "appearance:", "appearance:" },
            _bridge.Calls);
    }

    [Fact]
    public async Task TheIconAndAppearanceRoutesAreClosedToAnotherOriginToo()
    {
        // The window route has this test; these two did not, and they are
        // reachable by exactly the same means.
        using var icon = await PostAsync(
            "/desktop/icon", "{\"choice\":\"Ink\",\"startMenuShortcut\":false}",
            origin: "https://evil.example");
        Assert.Equal(HttpStatusCode.Forbidden, icon.StatusCode);

        using var appearance = await PostAsync(
            "/desktop/appearance", "{\"background\":\"#000000\"}", origin: "https://evil.example");
        Assert.Equal(HttpStatusCode.Forbidden, appearance.StatusCode);

        Assert.Empty(_bridge.Calls);
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
    public async Task AMutatingRouteRefusesARequestThatSendsNoOriginAtAll()
    {
        // The guard used to be "reject a WRONG Origin", which reads as a guard
        // and is not one: absence was trust. Measured from a raw socket against
        // the real file — no Origin, no Sec-Fetch-*, no User-Agent, HTTP/1.0 —
        // pin, float, icon, appearance, dock and drag all executed.
        //
        // A browser cannot produce this shape on a POST. Fetch appends Origin
        // to every request whose method is not GET or HEAD, same-origin
        // included, so a POST with none is curl, a scanner, or another account
        // on the machine.
        foreach (var (path, body) in new[]
        {
            ("/desktop/window", "{\"action\":\"float\"}"),
            ("/desktop/window", "{\"action\":\"pin\",\"pinned\":true}"),
            ("/desktop/icon", "{\"choice\":\"Ink\",\"startMenuShortcut\":false}"),
            ("/desktop/appearance", "{\"background\":\"#000000\"}"),
        })
        {
            using var res = await PostAsync(path, body, origin: "");
            Assert.Equal(HttpStatusCode.Forbidden, res.StatusCode);
        }
        Assert.Empty(_bridge.Calls);
    }

    [Fact]
    public async Task TheReadOnlyStateRouteStillAnswersARequestWithNoOrigin()
    {
        // And it must, because the page cannot send one: a same-origin GET
        // carries no Origin by spec. Requiring one here — the obvious next
        // keystroke after the test above — would 403 `readState`, and every
        // desktop-only control in the SPA would silently stop rendering.
        using var http = new HttpClient();
        using var res = await http.GetAsync($"{_server.Origin}/desktop/state");

        Assert.Equal(HttpStatusCode.OK, res.StatusCode);
        Assert.Equal(_bridge.State(), await res.Content.ReadAsStringAsync());
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
        // 405, not 403 — the Origin requirement sits AFTER the method gate, so a
        // wrong method still reads as a wrong method. Swap the two and this is
        // the test that notices.
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
