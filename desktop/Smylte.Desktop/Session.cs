using System.Net;
using System.Text;
using System.Text.Json;

namespace Smylte.Desktop;

/// Talking to the real server directly, outside the proxy — used to check a URL
/// in the setup dialog and to trade the stored credentials for a session cookie
/// before the first navigation.
public static class Session
{
    private static HttpClient MakeClient() => new(new SocketsHttpHandler
    {
        UseCookies = false,          // the caller wants the raw Set-Cookie back
        AllowAutoRedirect = false,
    })
    {
        Timeout = TimeSpan.FromSeconds(20),
    };

    private static Uri Api(string serverUrl, string path) =>
        new(new Uri(serverUrl.TrimEnd('/') + "/"), path);

    /// Is there a Smylte server at this URL? Called by the setup dialog, so the
    /// failure text is what the user reads.
    public static async Task<(bool Ok, string Message)> ProbeAsync(
        string serverUrl, CancellationToken ct)
    {
        if (!Uri.TryCreate(serverUrl.TrimEnd('/'), UriKind.Absolute, out var parsed)
            || (parsed.Scheme != "http" && parsed.Scheme != "https"))
            return (false, "That is not a valid http:// or https:// address.");

        try
        {
            using var http = MakeClient();
            using var resp = await http.GetAsync(Api(serverUrl, "api/me"), ct).ConfigureAwait(false);

            // Unauthenticated is a perfectly good answer here — it still proves
            // something is listening and that it is the app rather than a proxy.
            if (resp.StatusCode == HttpStatusCode.Unauthorized) return (true, "Found it.");
            if (!resp.IsSuccessStatusCode)
                return (false, $"The server answered {(int)resp.StatusCode}.");

            var body = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            using var doc = JsonDocument.Parse(body);
            return doc.RootElement.TryGetProperty("authenticated", out _)
                ? (true, "Found it.")
                : (false, "Something answered, but it does not look like Smylte.");
        }
        catch (JsonException)
        {
            return (false, "Something answered, but it does not look like Smylte.");
        }
        catch (Exception ex)
        {
            return (false, $"Could not reach it: {ex.Message}");
        }
    }

    /// Log in and hand back the raw Set-Cookie values, for injection into the
    /// WebView2 cookie store. An empty list means the caller should just show the
    /// app's own login screen — a wrong stored password must not brick anything.
    public static async Task<IReadOnlyList<string>> LoginAsync(
        string serverUrl, string username, string password, CancellationToken ct)
    {
        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
            return Array.Empty<string>();

        try
        {
            using var http = MakeClient();
            var payload = JsonSerializer.Serialize(new { username, password });
            using var content = new StringContent(payload, Encoding.UTF8, "application/json");
            using var resp = await http
                .PostAsync(Api(serverUrl, "api/login"), content, ct).ConfigureAwait(false);

            if (!resp.IsSuccessStatusCode) return Array.Empty<string>();
            return resp.Headers.TryGetValues("Set-Cookie", out var cookies)
                ? cookies.ToList()
                : Array.Empty<string>();
        }
        catch (Exception)
        {
            return Array.Empty<string>();
        }
    }

    /// Split a Set-Cookie value into the name and value the WebView2 cookie API
    /// wants. Attributes are dropped: the cookie is being re-scoped to localhost
    /// for this session, so the originals no longer apply.
    public static (string Name, string Value)? ParseCookie(string setCookie)
    {
        var pair = setCookie.Split(';', 2)[0];
        var eq = pair.IndexOf('=');
        if (eq <= 0) return null;
        return (pair[..eq].Trim(), pair[(eq + 1)..].Trim());
    }
}
