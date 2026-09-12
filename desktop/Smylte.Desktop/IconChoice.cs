namespace Smylte.Desktop;

/// Which app icon the window wears, and how "Auto" decides.
///
/// The names match what `backend/dev/build_app_icon.py` emits and what the
/// Appearance section sends over the bridge; they are persisted verbatim in
/// settings.json, so renaming one silently resets everybody's choice.
public enum IconChoice
{
    /// Follow the system theme: the plate that contrasts with it.
    Auto,
    /// Cream plate, ink letter, accent period — the web favicon's colours.
    Paper,
    /// Near-black plate, paper letter, accent period.
    Ink,
    /// Burnt-orange plate, paper letter, ink period. Also the compiled default.
    Accent,
    /// The letter alone on transparency, in accent. No plate.
    Mark,
}

/// Parsing the persisted choice and resolving Auto — the half of the icon story
/// that is neither Windows nor GTK.
///
/// Split out of IconLibrary so both clients share it. What stayed behind there
/// is genuinely Windows: reading `SystemUsesLightTheme` out of the registry, and
/// `System.Drawing.Icon` over a multi-frame `.ico`. What is here is the part
/// that must not diverge — the five names on the wire, the lenient parse, and
/// the CONTRAST rule that says a dark shell gets the cream plate rather than the
/// matching one. If the Linux client re-derived that rule it could quietly
/// invert it, and the symptom would be an icon nobody can see against the bar it
/// sits on, which is exactly the failure the rule exists to prevent.
public static class IconChoices
{
    /// Light and dark are answered by the plate that CONTRASTS with the shell,
    /// not by the plate that matches it. On a dark taskbar or dash the cream
    /// tile reads; on a light one the near-black tile does. Measured on
    /// Windows, the reverse pairing bottoms out near 1.0:1 — indistinguishable
    /// from the bar it sits on.
    private const IconChoice ForLightShell = IconChoice.Ink;
    private const IconChoice ForDarkShell = IconChoice.Paper;

    /// Lenient on purpose: this value comes out of a hand-editable
    /// settings.json and is cosmetic, so an unknown string falls back to Auto
    /// rather than refusing to start.
    ///
    /// The leading-letter test is not decoration. `Enum.TryParse` accepts the
    /// UNDERLYING NUMBER as readily as the name, so `"2"` parsed as Ink and
    /// `"3"` as Accent — which is the one way "an unknown value falls back to
    /// Auto" was not true. A hand-edited file that says `"IconChoice": "3"` is
    /// a file someone got wrong, and answering it with a specific variant
    /// rather than the default is a wrong answer delivered confidently. It also
    /// welded the enum's declaration ORDER into the persisted format, so
    /// inserting a variant would have silently rewritten those users' choice.
    ///
    /// The COMMA is the other half, and the digit check does not cover it.
    /// `Enum.TryParse` accepts a comma-separated list and ORs the members
    /// together even for an enum with no [Flags] — so `"Paper,Ink"` is 1|2 = 3,
    /// which is `Accent`. A settings.json naming two variants resolved
    /// confidently to a THIRD one, and `Enum.IsDefined` waves it through
    /// because 3 is a real member. Measured:
    ///
    ///     Parse("Paper,Ink")         -> Accent
    ///     Parse("Auto,Mark")         -> Mark
    ///     Parse("Mark,Accent,Paper") -> Auto   (7 is undefined, so caught)
    ///
    /// Nothing writes either shape — the app persists `choice.ToString()` — so
    /// refusing both takes nothing away from a settings.json this client wrote.
    public static IconChoice Parse(string? value)
    {
        var trimmed = value?.Trim();
        if (string.IsNullOrEmpty(trimmed)) return IconChoice.Auto;
        if (!char.IsAsciiLetter(trimmed[0])) return IconChoice.Auto;
        if (trimmed.Contains(',')) return IconChoice.Auto;

        return Enum.TryParse<IconChoice>(trimmed, ignoreCase: true, out var choice)
            && Enum.IsDefined(choice)
            ? choice
            : IconChoice.Auto;
    }

    /// The choice `Auto` resolves to, given what the shell is currently drawing.
    /// Never returns Auto.
    public static IconChoice Resolve(IconChoice choice, bool systemUsesLightTheme) => choice switch
    {
        IconChoice.Auto => systemUsesLightTheme ? ForLightShell : ForDarkShell,
        _ => choice,
    };

    /// The sizes the freedesktop hicolor theme names, and the ones
    /// `backend/dev/build_app_icon.py` emits for the GTK client.
    ///
    /// Here rather than in the Linux project so that three things can be held
    /// to one list: the generator that writes the files, the client that
    /// unpacks them, and the test that asserts they all exist. A size present
    /// in two of the three is a missing icon at exactly one scale factor,
    /// which nobody notices until a screenshot.
    ///
    /// Seven, where the Windows `.ico` carries fifteen. The extra eight are all
    /// workarounds for Win32 lookup rules — a byte-wide width field, three
    /// request bands to satisfy at once — that an icon theme does not have: it
    /// takes the nearest size at or above what it wants and scales down.
    public static readonly int[] FreedesktopSizes = { 16, 24, 32, 48, 64, 128, 256 };
}
