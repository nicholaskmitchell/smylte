using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The Exec line of the desktop entry.
///
/// A `.desktop` file is read by two parsers in sequence — GLib's key-file
/// parser, then the Exec parser (`g_shell_parse_argv`) — and the specification
/// says so explicitly, which is why a literal backslash in an argument is
/// written as four. Interpolating a path into `Exec="{exe}"` and stopping there
/// is wrong for every character either parser reserves, and a filesystem path
/// may contain all of them.
///
/// **Asserted against a parser, not against an inverse of the escaper.** The
/// first version of this file un-escaped with the mirror image of the code
/// under test, and that is a test that cannot fail the way it needs to: with
/// the escaping deleted entirely, a path containing `"` round-tripped clean,
/// because a forgiving inverse and a missing escape cancel out. What is here
/// instead is a tokeniser that behaves the way the real pair does — an
/// unescaped quote ENDS the argument — so the assertion is "the launcher execs
/// exactly one argument and it is the path", which is the thing that matters
/// and the thing that broke.
public sealed class DesktopEntryTextTests
{
    private static string ExecLine(string exe) =>
        DesktopEntryText.Contents(exe, "com.example.App")
            .Split('\n').Single(l => l.StartsWith("Exec=", StringComparison.Ordinal))
            .Trim()["Exec=".Length..];

    /// GLib's key-file string unescape: `\\`, `\s`, `\n`, `\t`, `\r`. Anything
    /// else after a backslash is passed through, which is what GLib does after
    /// warning about it.
    private static string KeyFile(string raw)
    {
        var output = new System.Text.StringBuilder();
        for (var i = 0; i < raw.Length; i++)
        {
            if (raw[i] != '\\' || i + 1 >= raw.Length) { output.Append(raw[i]); continue; }
            output.Append(raw[++i] switch
            {
                '\\' => '\\', 's' => ' ', 'n' => '\n', 't' => '\t', 'r' => '\r',
                var other => other,
            });
        }
        return output.ToString();
    }

    /// The Exec parser: whitespace-separated arguments, double quotes group,
    /// a backslash inside quotes escapes the next character, `%%` is a literal
    /// per cent and `%X` is a field code the launcher expands (here: dropped,
    /// which is what GLib does with one it does not recognise).
    ///
    /// Deliberately strict about the quote. An argument that opens one and never
    /// closes it is a parse failure in `g_shell_parse_argv`, and an entry that
    /// fails to parse is a menu item that does nothing.
    private static List<string> ParseExec(string value)
    {
        var arguments = new List<string>();
        var current = new System.Text.StringBuilder();
        var quoted = false;
        var started = false;

        for (var i = 0; i < value.Length; i++)
        {
            var c = value[i];
            if (quoted)
            {
                if (c == '\\' && i + 1 < value.Length) { current.Append(value[++i]); continue; }
                if (c == '"') { quoted = false; continue; }
                if (c == '%' && i + 1 < value.Length)
                {
                    if (value[i + 1] == '%') { current.Append('%'); i++; continue; }
                    i++; continue;                      // a field code: expanded away
                }
                current.Append(c);
                continue;
            }
            if (c == '"') { quoted = true; started = true; continue; }
            if (char.IsWhiteSpace(c))
            {
                if (started) { arguments.Add(current.ToString()); current.Clear(); started = false; }
                continue;
            }
            if (c == '%' && i + 1 < value.Length)
            {
                started = true;
                if (value[i + 1] == '%') { current.Append('%'); i++; continue; }
                i++; continue;
            }
            started = true;
            current.Append(c);
        }

        Assert.False(quoted, $"unterminated quote in Exec={value}");
        if (started) arguments.Add(current.ToString());
        return arguments;
    }

    private static List<string> Launched(string exe) => ParseExec(KeyFile(ExecLine(exe)));

    [Theory]
    [InlineData("/usr/local/bin/Smylte-linux-x86_64")]
    [InlineData("/home/u/Downloads/Smylte linux x86_64")]      // already safe: it is quoted
    [InlineData("/home/u/Apps/Smylte 100%/Smylte")]            // %/ is read as a field code
    [InlineData("/home/u/$HOME/Smylte")]
    [InlineData("/home/u/`id`/Smylte")]
    [InlineData("/home/u/say \"hi\"/Smylte")]
    [InlineData("/home/u/back\\slash/Smylte")]
    [InlineData("/home/u/100%/$(id) `id` \"q\" \\x/Smylte")]   // all of them at once
    public void The_launcher_execs_the_path_and_nothing_else(string exe)
    {
        // One argument, and it is the binary. Anything else is a launcher that
        // runs something the user did not install.
        Assert.Equal(new[] { exe }, Launched(exe));
    }

    [Fact]
    public void A_per_cent_in_the_path_is_not_read_as_a_field_code()
    {
        // The concrete regression: `~/Apps/Smylte 100%/Smylte` used to exec
        // `~/Apps/Smylte 100Smylte` — a path that does not exist — because
        // GLib drops `%` and the character after it. The entry appeared in the
        // app grid and clicking it did nothing, silently.
        Assert.Equal("\"/tmp/100%%/Smylte\"", ExecLine("/tmp/100%/Smylte"));
        Assert.Equal(new[] { "/tmp/100%/Smylte" }, Launched("/tmp/100%/Smylte"));
    }

    [Fact]
    public void A_quote_in_the_path_does_not_end_the_argument()
    {
        // Unescaped, this is either a different argv or an unterminated quote —
        // and ParseExec above asserts on the second, so both are caught.
        Assert.Single(Launched("/tmp/a\"b/Smylte"));
    }

    [Fact]
    public void A_path_that_no_escaping_can_carry_is_refused_rather_than_mangled()
    {
        // One key per line, so a newline cannot be written at all — the escape
        // would be undone before the Exec parser saw it and would split the
        // command. The caller turns this into "could not write the entry",
        // which is a thing the user can act on.
        Assert.True(DesktopEntryText.CanWrite("/tmp/Smylte"));
        Assert.False(DesktopEntryText.CanWrite("/tmp/two\nlines/Smylte"));
        Assert.False(DesktopEntryText.CanWrite("/tmp/carriage\rreturn/Smylte"));
        Assert.False(DesktopEntryText.CanWrite(""));
    }

    [Fact]
    public void The_entry_still_says_what_it_has_to_say()
    {
        // The three strings that have to agree with `g_set_prgname` and with
        // the filename, or the shell shows a running window under a generic
        // icon rather than under the launcher it came from.
        var text = DesktopEntryText.Contents("/tmp/Smylte", "com.example.App");
        Assert.Contains("StartupWMClass=com.example.App", text);
        Assert.Contains("Icon=com.example.App", text);
        Assert.Contains("Type=Application", text);
        Assert.DoesNotContain("%u", text);
        Assert.DoesNotContain("%f", text);
    }
}
