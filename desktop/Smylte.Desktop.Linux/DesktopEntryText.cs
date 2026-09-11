namespace Smylte.Desktop;

/// The text of the desktop entry, and the escaping the Exec line needs.
///
/// Split out of DesktopEntry for one reason: everything else in that file
/// touches GTK, the icon theme or the filesystem, and this is a pure string
/// function that was wrong in a way only a test would have caught.
internal static class DesktopEntryText
{
    public static string Contents(string exe, string appId) =>
        $"""
        [Desktop Entry]
        Type=Application
        Name=Smylte
        Comment=Tasks and calendar
        Exec="{ExecArgument(exe)}"
        Icon={appId}
        Terminal=false
        Categories=Office;Calendar;ProjectManagement;
        StartupNotify=true
        StartupWMClass={appId}
        X-GNOME-UsesNotifications=true

        """;

    // Exec carries NO field code (%u, %f): this client registers no MIME type
    // and no URL scheme, and a launcher that expands a field code the app
    // cannot use is a launch that fails for a reason nobody can see.

    /// Is this a path an entry can be written for at all?
    ///
    /// A newline is the one thing no amount of escaping survives: the key-file
    /// format is one key per line, and `\n` written as an escape would be
    /// un-escaped before `g_shell_parse_argv` ever sees it, splitting the
    /// command. Refusing is the honest answer, and the caller already has a
    /// "could not write the entry" path for it.
    public static bool CanWrite(string exe) =>
        !string.IsNullOrEmpty(exe) && !exe.Contains('\n') && !exe.Contains('\r');

    /// The executable path, escaped for the inside of Exec's double quotes.
    ///
    /// **Escaped TWICE, and that is the spec rather than belt and braces.** The
    /// value passes through two parsers in turn — the key-file parser, which
    /// reads `\\` as one backslash, and then the Exec parser, which reads `\"`
    /// inside quotes as one quote. Each gets its own pass, which is why the
    /// spec's own worked example of a literal backslash in an argument is four
    /// of them.
    ///
    /// The quoting was already there, so a space was already safe. What was not
    /// safe is everything else a path may contain, none of it hypothetical:
    ///
    ///   `%`   GLib's `expand_application_parameters` reads the next character
    ///         as a field code and drops both. A binary kept in
    ///         `~/Apps/Smylte 100%/` produced `Exec=".../Smylte 100Smylte-…"`,
    ///         a path that does not exist — so the entry appeared in the app
    ///         grid and clicking it did nothing, with no error written anywhere.
    ///   `"`   ends the quoted argument early; `g_shell_parse_argv` then either
    ///         splits the line into different argv words or fails outright on
    ///         an unterminated quote.
    ///   `\`   is consumed by the key-file unescape before quoting is even
    ///         considered.
    ///   `$` ``` are what the spec names alongside those two as reserved inside
    ///         double quotes.
    ///
    /// Not command injection — GLib parses Exec with `g_shell_parse_argv`, not
    /// with a shell — but a launcher that silently runs the wrong path.
    ///
    /// The ORDER matters twice over: the backslash is doubled before the
    /// characters that are escaped WITH a backslash, or their new backslashes
    /// get doubled too; and `%` is done after those, so the escapes' own
    /// characters are not re-processed.
    public static string ExecArgument(string exe)
    {
        // Layer one: the Exec parser, inside double quotes. The spec names
        // exactly these four as needing a backslash there.
        var quoted = exe
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("`", "\\`")
            .Replace("$", "\\$");

        // Field codes. `%` is not a key-file escape, so it takes no second
        // pass; `%%` is how the Exec parser spells a literal one.
        quoted = quoted.Replace("%", "%%");

        // Layer two: the key-file parser, which is what actually reads this
        // file. Every backslash written above has to survive it.
        return quoted.Replace("\\", "\\\\");
    }
}
