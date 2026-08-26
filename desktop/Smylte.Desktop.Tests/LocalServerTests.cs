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

/// The 2026-08-25 sweep, stage 2: the document WebView2 runs carries no
/// Content-Security-Policy.
///
/// **This finding is OPEN**, and this is its `xfail` — there is no xunit
/// equivalent, so it is written as the assertion it will be and marked with the
/// Skip below. Delete the Skip when the policy lands; the body does not change.
/// Same contract as the `xfail(strict=True)` pins in
/// `backend/tests/test_backlog_aug25_stage2.py` and the `it.fails` ones in the
/// SPA suites, except that a Skip cannot go red on its own the way an XPASS does
/// — so `docs/STAGES.md` records that this one has to be un-skipped by hand.
///
/// The app's CSP exists only as a response header the BACKEND attaches
/// (`tasksd/csp.py::CSPMiddleware`), derived at startup from the served
/// index.html so it can carry the sha256 of the inline pre-paint script.
/// `frontend/index.html` has no `http-equiv` meta — verified, zero occurrences —
/// so in the desktop client, where `ServeStatic` sets exactly Content-Type and
/// Cache-Control, the document has no policy at all: no `default-src 'self'`, no
/// `connect-src 'self'`, no `object-src 'none'`, no script-hash allowlist. On the
/// one surface that also holds a live session cookie for the real server.
///
/// Unlike the tests above this one, it has to START the server: the header set is
/// what is under test, and `Resolve` is pure path arithmetic that never sees a
/// response. A free port is chosen by `ChoosePort`, as the app does.
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

    // xunit has no `xfail`, and that matters more than it looks. A `Skip` would
    // stay skipped forever after the fix landed — green, silent, and exactly the
    // half of the harness `docs/STAGES.md` says is the point ("a green build no
    // longer means 'no known bugs', it means 'every known bug is exactly as
    // known'"). So the pin is written in two halves:
    //
    //   * this one is LIVE and asserts the DEFECT. It passes today and goes RED
    //     the moment a policy is emitted — which is the alarm an XPASS gives on
    //     the Python side, arrived at from the other direction.
    //   * the one below carries the corrected assertions and is skipped until
    //     then. Un-skipping it and deleting this one is the whole of the ritual.

    [Fact]
    public async Task TheDocumentStillCarriesNoPolicy()
    {
        using var http = new HttpClient();
        using var res = await http.GetAsync($"{_server.Origin}/");
        res.EnsureSuccessStatusCode();

        Assert.False(
            res.Headers.Contains("Content-Security-Policy"),
            "GOOD NEWS, AND AN ACTION: the desktop document now carries a "
            + "Content-Security-Policy, so this finding is fixed. Tick it off in "
            + "docs/AUDIT.md, flip its row in docs/STAGES.md, delete THIS test, and "
            + "un-skip TheDocumentCarriesAPolicy below — which is the assertion you "
            + "actually want kept.");
    }

    [Fact(Skip = "OPEN: ServeStatic sets only Content-Type and Cache-Control, so the "
               + "document WebView2 runs has no Content-Security-Policy at all. "
               + "Un-skip this and delete TheDocumentStillCarriesNoPolicy when it does.")]
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
}
