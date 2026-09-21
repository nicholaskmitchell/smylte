using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Which display server the Linux client asks GDK for.
///
/// This is one `if` and it decided how the whole app renders. Forcing X11 puts
/// a Wayland session through XWayland, which has a single scale factor for the
/// entire display and bitmap-stretches under fractional scaling — so on a
/// two-monitor desk one screen is always wrong and text is soft on it. The old
/// fallback only triggered when `DISPLAY` was unset, which on a Wayland session
/// with XWayland it never is, so the fallback never fired and every GNOME
/// Wayland user got XWayland permanently.
///
/// Untestable before, because the decision was inline in `Program.Main` — a
/// method that must not so much as name a GirCore type.
public sealed class DisplayBackendTests
{
    private const string OnWayland = "wayland-0";
    private const string OnX11 = ":0";

    [Fact]
    public void A_wayland_session_is_left_to_GDK_by_default()
    {
        // Null, not "wayland". An explicit GDK_BACKEND disables GDK's own
        // fallback — which is exactly why naming x11 on a session without an X
        // server kills the process — and GDK already prefers Wayland when there
        // is one. Naming it would remove the safety net and change nothing else.
        Assert.Null(DisplayBackend.Choose("auto", OnWayland, OnX11));
        Assert.Null(DisplayBackend.Choose("auto", OnWayland, null));
    }

    [Fact]
    public void An_x11_session_is_also_left_to_GDK_by_default()
    {
        Assert.Null(DisplayBackend.Choose("auto", null, OnX11));
    }

    [Fact]
    public void The_regression_that_made_XWayland_universal()
    {
        // A stock GNOME Wayland session: WAYLAND_DISPLAY set, and DISPLAY also
        // set because XWayland is running. The old rule was "x11 unless DISPLAY
        // is empty", so this — the commonest Linux desktop configuration there
        // is — took the XWayland path every time.
        Assert.NotEqual(DisplayBackend.X11, DisplayBackend.Choose("auto", OnWayland, OnX11));
    }

    [Fact]
    public void An_explicit_x11_is_still_honoured_where_it_can_be()
    {
        // The documented escape hatch, and what Settings → Desktop's hint tells
        // a user whose floating-window pin has gone. It has to keep working, on
        // a Wayland session too — XWayland is what makes the pin possible there.
        Assert.Equal(DisplayBackend.X11, DisplayBackend.Choose("x11", OnWayland, OnX11));
        Assert.Equal(DisplayBackend.X11, DisplayBackend.Choose("x11", null, OnX11));
        Assert.Equal(DisplayBackend.X11, DisplayBackend.Choose("X11", null, OnX11));
        Assert.Equal(DisplayBackend.X11, DisplayBackend.Choose("  x11  ", null, OnX11));
    }

    [Fact]
    public void An_explicit_wayland_is_honoured_where_it_can_be()
    {
        Assert.Equal(DisplayBackend.Wayland, DisplayBackend.Choose("wayland", OnWayland, OnX11));
        Assert.Equal(DisplayBackend.Wayland, DisplayBackend.Choose("WAYLAND", OnWayland, null));
    }

    [Fact]
    public void Neither_explicit_value_is_handed_to_GDK_when_the_session_lacks_it()
    {
        // X11 with no X server was already guarded. Wayland with no compositor
        // was NOT — the guard was written on one arm only, so a hand-edited
        // settings.json asking for Wayland on an X11 session set a backend GDK
        // could not open and the process died before drawing anything, with the
        // same "cannot open display" the other guard exists to prevent.
        Assert.Null(DisplayBackend.Choose("x11", OnWayland, null));
        Assert.Null(DisplayBackend.Choose("wayland", null, OnX11));
        Assert.Null(DisplayBackend.Choose("x11", null, null));
        Assert.Null(DisplayBackend.Choose("wayland", null, null));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("auto")]
    [InlineData("AUTO")]
    [InlineData("xwayland")]      // plausible and wrong
    [InlineData("mir")]
    public void Anything_unrecognised_is_auto(string? setting)
    {
        // A hand-edited field with no UI: a typo should cost the preference,
        // not the window.
        Assert.Null(DisplayBackend.Choose(setting, OnWayland, OnX11));
        Assert.Null(DisplayBackend.Choose(setting, null, OnX11));
    }

    [Fact]
    public void Describe_names_what_GDK_will_pick_when_we_do_not()
    {
        Assert.Equal("x11", DisplayBackend.Describe("x11", OnWayland, OnX11));
        Assert.Contains("wayland", DisplayBackend.Describe(null, OnWayland, OnX11));
        Assert.Contains("x11", DisplayBackend.Describe(null, null, OnX11));
        Assert.Contains("no display server", DisplayBackend.Describe(null, null, null));
    }
}
