using System.Drawing;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The two pieces of appearance logic both clients share: the colour the page
/// sends over the bridge, and which icon variant `Auto` means.
///
/// Neither had a test before, for a structural reason rather than an oversight:
/// they lived inside `WindowChrome` and `IconLibrary`, which are `dwmapi` and
/// the registry respectively, so this project could not link either file. Now
/// that the Linux client needs the same answers, the portable halves are their
/// own files (`Theme.cs`, `IconChoice.cs`) and can be asserted — which matters
/// more than it looks, because the failure mode of both is a plausible WRONG
/// answer rather than an exception. A backwards contrast rule still produces an
/// icon; it is just one nobody can see.
public sealed class ThemeTests
{
    [Theory]
    [InlineData("#FBFAF7", 0xFB, 0xFA, 0xF7)]   // the app's light --bg
    [InlineData("#0C0C10", 0x0C, 0x0C, 0x10)]   // and its dark one
    [InlineData("FBFAF7", 0xFB, 0xFA, 0xF7)]    // the hash is optional
    [InlineData("#abc", 0xAA, 0xBB, 0xCC)]      // three digits double
    [InlineData("  #C75A26  ", 0xC7, 0x5A, 0x26)]
    public void ParseHex_reads_the_forms_the_page_sends(string hex, int r, int g, int b)
    {
        var colour = Theme.ParseHex(hex);
        Assert.NotNull(colour);
        Assert.Equal(Color.FromArgb(r, g, b).ToArgb(), colour!.Value.ToArgb());
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("rebeccapurple")]     // a named colour: the page normalises, but a
    [InlineData("rgb(12, 12, 16)")]   // hand-written theme can reach here first
    [InlineData("#12345")]            // five digits
    [InlineData("#gggggg")]
    [InlineData("#  FFFF")]           // see below
    [InlineData("# 12 34")]
    [InlineData("#\tFFFFF")]
    public void ParseHex_returns_null_for_anything_it_cannot_read(string? hex)
    {
        // Null is the contract, not an error: `IDesktopBridge.Appearance` documents
        // that an unparseable value hands the frame back to the OS. A throw here
        // would turn a user-authored theme into a crash.
        Assert.Null(Theme.ParseHex(hex));
    }

    [Fact]
    public void ParseHex_does_not_read_a_space_as_a_zero()
    {
        // `NumberStyles.HexNumber` includes AllowLeadingWhite and
        // AllowTrailingWhite, and the Trim only removes space OUTSIDE the hash.
        // So "#  FFFF" survived the trim, passed the six-character length test
        // with two spaces in it, and parsed as 0x00FFFF — cyan, a colour the
        // page never sent.
        //
        // What makes it worth its own test rather than one more InlineData
        // above: the SAME value without the spaces is correctly refused, so the
        // failure is "adding whitespace turns a rejected value into an accepted
        // wrong one", which reads as impossible until it is written down.
        Assert.Null(Theme.ParseHex("#FFFF"));        // four digits: refused
        Assert.Null(Theme.ParseHex("#  FFFF"));      // six characters: was cyan
    }

    [Fact]
    public void IsDark_agrees_with_the_two_shipped_backgrounds()
    {
        Assert.False(Theme.IsDark(Theme.ParseHex("#FBFAF7")!.Value));
        Assert.True(Theme.IsDark(Theme.ParseHex("#0C0C10")!.Value));
        // And the workspace preset's pair, which is closer to the boundary.
        Assert.False(Theme.IsDark(Theme.ParseHex("#FBFBFC")!.Value));
        Assert.True(Theme.IsDark(Theme.ParseHex("#191919")!.Value));
    }

    [Fact]
    public void InkFor_never_returns_pure_black_or_pure_white()
    {
        // The design system's two ink values, and the reason they are not
        // #000000/#FFFFFF is the same reason build_app_icon.py refuses them.
        // Asserting it here stops a "simplification" from reintroducing them.
        foreach (var bg in new[] { "#FBFAF7", "#0C0C10" })
        {
            var ink = Theme.InkFor(Theme.ParseHex(bg)!.Value);
            Assert.NotEqual(Color.FromArgb(0, 0, 0).ToArgb(), ink.ToArgb());
            Assert.NotEqual(Color.FromArgb(255, 255, 255).ToArgb(), ink.ToArgb());
        }
    }

    [Fact]
    public void InkFor_contrasts_with_its_background()
    {
        // The whole job of the function, stated as the property rather than as
        // the two literals: light ink on dark, dark ink on light.
        var dark = Theme.ParseHex("#0C0C10")!.Value;
        var light = Theme.ParseHex("#FBFAF7")!.Value;
        Assert.True(Theme.Luminance(Theme.InkFor(dark)) > Theme.Luminance(dark));
        Assert.True(Theme.Luminance(Theme.InkFor(light)) < Theme.Luminance(light));
    }
}

public sealed class IconChoiceTests
{
    [Theory]
    [InlineData("Auto", IconChoice.Auto)]
    [InlineData("paper", IconChoice.Paper)]
    [InlineData("INK", IconChoice.Ink)]
    [InlineData("Accent", IconChoice.Accent)]
    [InlineData("Mark", IconChoice.Mark)]
    public void Parse_reads_the_five_names_in_any_case(string value, IconChoice expected)
    {
        Assert.Equal(expected, IconChoices.Parse(value));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("Cream")]      // a plausible near-miss for Paper
    [InlineData("3")]
    public void Parse_falls_back_to_Auto_rather_than_refusing(string? value)
    {
        // settings.json is hand-editable and this field is cosmetic, so an
        // unknown value must not be able to stop the client starting. Stated as
        // deliberate in Settings.cs; asserted here.
        Assert.Equal(IconChoice.Auto, IconChoices.Parse(value));
    }

    [Theory]
    [InlineData("Paper,Ink")]        // 1 | 2 = 3, which IS Accent
    [InlineData("Auto,Mark")]        // 0 | 4 = 4, which IS Mark
    [InlineData("paper, ink")]
    [InlineData("Mark,Accent,Paper")]
    public void Parse_does_not_accept_a_list_of_names(string value)
    {
        // `Enum.TryParse` accepts a comma-separated list and ORs the members
        // together — for an enum with no [Flags] attribute, which this one does
        // not have. `Enum.IsDefined` then waves the result through because the
        // number happens to name a real member. Measured:
        //
        //     Parse("Paper,Ink") -> Accent
        //     Parse("Auto,Mark") -> Mark
        //
        // A settings.json naming two variants resolved confidently to a THIRD,
        // which is the same failure the digit guard below exists to close and
        // is not covered by it. Nothing writes this shape — the app persists
        // `choice.ToString()` — so refusing it takes nothing away.
        Assert.Equal(IconChoice.Auto, IconChoices.Parse(value));
    }

    [Fact]
    public void Parse_does_not_accept_a_number_for_a_name()
    {
        // Enum.TryParse takes "0" as Auto and "2" as Ink, which would make a
        // typo in settings.json silently pick a variant. Both land on Auto
        // above; this pins the one that would otherwise be a WRONG icon rather
        // than the default one.
        Assert.Equal(IconChoice.Auto, IconChoices.Parse("2"));
    }

    [Fact]
    public void Resolve_answers_a_light_shell_with_the_dark_plate_and_the_reverse()
    {
        // The measured rule, and the one worth a test: the plate that CONTRASTS
        // with the shell, not the one that matches it. Inverted, the icon
        // measures about 1.0:1 against the bar it sits on — present, correct,
        // and invisible. Nothing about that failure throws.
        Assert.Equal(IconChoice.Ink, IconChoices.Resolve(IconChoice.Auto, systemUsesLightTheme: true));
        Assert.Equal(IconChoice.Paper, IconChoices.Resolve(IconChoice.Auto, systemUsesLightTheme: false));
    }

    [Theory]
    [InlineData(IconChoice.Paper)]
    [InlineData(IconChoice.Ink)]
    [InlineData(IconChoice.Accent)]
    [InlineData(IconChoice.Mark)]
    public void Resolve_leaves_a_fixed_choice_alone_whatever_the_shell_is_doing(IconChoice choice)
    {
        Assert.Equal(choice, IconChoices.Resolve(choice, systemUsesLightTheme: true));
        Assert.Equal(choice, IconChoices.Resolve(choice, systemUsesLightTheme: false));
    }

    [Fact]
    public void Resolve_never_returns_Auto()
    {
        // The page reads `resolved` to say which plate is in use, so Auto coming
        // back would render as a choice that does not exist.
        foreach (var choice in Enum.GetValues<IconChoice>())
        foreach (var light in new[] { true, false })
            Assert.NotEqual(IconChoice.Auto, IconChoices.Resolve(choice, light));
    }
}
