using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Where the floating window is allowed to open, and the unit conversion that
/// question has to be asked in.
///
/// The conversion is the reason this file exists. GTK measures in logical
/// pixels and Xlib in device pixels, the two are identical at scale 1, and an
/// X11 session is scale 1 unless someone sets `GDK_SCALE` — which is exactly
/// what a HiDPI user on X11 is told to do. So the client recorded the window's
/// position in one space and checked it against the other, and the bug could
/// only ever appear on the machines least likely to be the ones testing it.
public sealed class FloatPlacementTests
{
    private static readonly IReadOnlyList<ScreenRect> TwoMonitors = new[]
    {
        new ScreenRect(0, 0, 1920, 1080),        // primary
        new ScreenRect(1920, 0, 2560, 1440),     // a second, to its right
    };

    [Theory]
    [InlineData(0, 1, 0)]
    [InlineData(100, 1, 100)]
    [InlineData(100, 2, 200)]
    [InlineData(-12, 2, -24)]
    public void ToDevice_scales_up(int logical, int scale, int expected) =>
        Assert.Equal(expected, FloatPlacement.ToDevice(logical, scale));

    [Theory]
    [InlineData(200, 2, 100)]
    [InlineData(-24, 2, -12)]
    [InlineData(100, 1, 100)]
    public void ToLogical_scales_down(int device, int scale, int expected) =>
        Assert.Equal(expected, FloatPlacement.ToLogical(device, scale));

    [Fact]
    public void ToLogical_rounds_rather_than_truncating()
    {
        // A window at an odd device coordinate on a scale-2 display sits on a
        // half logical pixel. Truncating every read biases it one pixel toward
        // zero, and since every close writes what the last open read, the window
        // walks across the screen over a session.
        Assert.Equal(769, FloatPlacement.ToLogical(1537, 2));
        Assert.Equal(-769, FloatPlacement.ToLogical(-1537, 2));
    }

    [Fact]
    public void A_round_trip_at_any_scale_returns_the_same_position()
    {
        foreach (var scale in new[] { 1, 2, 3 })
            foreach (var logical in new[] { 0, 37, 960, 4000, -12 })
                Assert.Equal(logical,
                    FloatPlacement.ToLogical(FloatPlacement.ToDevice(logical, scale), scale));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void A_nonsense_scale_is_treated_as_one(int scale)
    {
        // A failed `GetScaleFactor` returning 0 would otherwise multiply every
        // position to the origin, which looks exactly like "it forgot where the
        // window was".
        Assert.Equal(100, FloatPlacement.ToDevice(100, scale));
        Assert.Equal(100, FloatPlacement.ToLogical(100, scale));
    }

    [Fact]
    public void A_window_on_the_second_monitor_is_reachable()
    {
        Assert.True(FloatPlacement.IsOnAScreen(2200, 300, 420, 280, TwoMonitors));
    }

    [Fact]
    public void The_scale_bug_reproduces_when_the_spaces_are_mixed()
    {
        // The window sits at logical (4000, 300), well inside the second
        // monitor, which spans x 1920-4480. On a scale-2 display X11 reports
        // that position as (8000, 600) — and the old code compared those device
        // numbers straight against monitor geometry that GTK reports in
        // logical pixels, where nothing extends past 4480 at all.
        const int logicalX = 4000, logicalY = 300;
        Assert.True(FloatPlacement.IsOnAScreen(logicalX, logicalY, 420, 280, TwoMonitors));
        var device = (X: FloatPlacement.ToDevice(logicalX, 2), Y: FloatPlacement.ToDevice(logicalY, 2));

        // What the bug did: device numbers against logical geometry.
        Assert.False(FloatPlacement.IsOnAScreen(device.X, device.Y, 420, 280, TwoMonitors));
        // What it does now: converted back at the boundary first.
        Assert.True(FloatPlacement.IsOnAScreen(
            FloatPlacement.ToLogical(device.X, 2), FloatPlacement.ToLogical(device.Y, 2),
            420, 280, TwoMonitors));
    }

    [Fact]
    public void A_window_on_a_monitor_that_is_gone_is_not_reachable()
    {
        var laptopOnly = new[] { new ScreenRect(0, 0, 1920, 1080) };
        Assert.False(FloatPlacement.IsOnAScreen(2200, 300, 420, 280, laptopOnly));
    }

    [Fact]
    public void A_negative_position_is_legitimate_when_enough_of_it_shows()
    {
        // The guard this replaced refused ANY negative coordinate, so a window
        // dragged so its left edge or title row sat just off the screen never
        // came back where it was left. X11 reports those faithfully and they are
        // a position like any other.
        Assert.True(FloatPlacement.IsOnAScreen(-40, -20, 420, 280, TwoMonitors));
        // Far enough off that nothing grabbable remains, and it is refused on
        // the merits rather than for its sign.
        Assert.False(FloatPlacement.IsOnAScreen(-400, -20, 420, 280, TwoMonitors));
        Assert.False(FloatPlacement.IsOnAScreen(-40, -270, 420, 280, TwoMonitors));
    }

    [Fact]
    public void The_visibility_floor_is_the_same_on_both_axes()
    {
        // Exactly at the floor counts; one pixel under it does not.
        var only = new[] { new ScreenRect(0, 0, 1920, 1080) };
        Assert.True(FloatPlacement.IsOnAScreen(1920 - FloatPlacement.MinVisible, 0, 420, 280, only));
        Assert.False(FloatPlacement.IsOnAScreen(1920 - FloatPlacement.MinVisible + 1, 0, 420, 280, only));
    }

    [Fact]
    public void A_window_that_was_never_opened_has_no_rectangle_to_place()
    {
        // FloatWidth and FloatHeight are 0 until the window has been opened
        // once, and answering "yes" for a 0x0 rectangle would restore a window
        // to a position nothing can see.
        Assert.False(FloatPlacement.IsOnAScreen(100, 100, 0, 0, TwoMonitors));
        Assert.False(FloatPlacement.IsOnAScreen(100, 100, 420, 0, TwoMonitors));
    }

    [Fact]
    public void No_monitors_at_all_is_not_a_reason_to_place_a_window()
    {
        Assert.False(FloatPlacement.IsOnAScreen(0, 0, 420, 280, Array.Empty<ScreenRect>()));
        Assert.False(FloatPlacement.IsOnAScreen(
            0, 0, 420, 280, new[] { new ScreenRect(0, 0, 0, 0) }));
    }
}
