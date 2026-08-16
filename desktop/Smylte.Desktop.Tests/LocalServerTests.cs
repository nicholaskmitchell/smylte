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
