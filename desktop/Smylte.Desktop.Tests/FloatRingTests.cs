using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The floating window's six-pixel resize ring.
///
/// Worth a test file of its own because its failure modes are all silent. A
/// corner band that is too small is a corner nobody can grab on the first try;
/// one that is too large steals presses from the page's controls; an inverted
/// edge resizes the wrong side. None of them throws, and until this arithmetic
/// was lifted out of `FloatForm` no test could reach it — it lived inside a
/// WinForms message loop that this suite cannot start.
///
/// The numbers are the ones the page's own stylesheet and
/// `frontend/src/layout.browser.test.tsx` are built on: 420×280 to open,
/// 320×200 at the floor, six pixels of ring, so the viewport is 408×268 down to
/// 308×188.
public sealed class FloatRingTests
{
    private const int W = 420, H = 280, R = 6;

    /// The floor the floating window clamps to, so the sweep below covers
    /// the smallest size a user can actually reach as well as the ones they
    /// cannot.
    private const int MinWidth = 320, MinHeight = 200;

    [Theory]
    // The four edges, sampled at the middle of each so no corner band applies.
    [InlineData(0, 140, RingEdge.Left)]
    [InlineData(W - 1, 140, RingEdge.Right)]
    [InlineData(210, 0, RingEdge.Top)]
    [InlineData(210, H - 1, RingEdge.Bottom)]
    // The four corners, at the very pixel.
    [InlineData(0, 0, RingEdge.TopLeft)]
    [InlineData(W - 1, 0, RingEdge.TopRight)]
    [InlineData(0, H - 1, RingEdge.BottomLeft)]
    [InlineData(W - 1, H - 1, RingEdge.BottomRight)]
    public void The_ring_answers_the_edge_it_is_on(int x, int y, RingEdge expected)
    {
        Assert.Equal(expected, FloatRing.HitTest(W, H, R, x, y));
    }

    [Theory]
    [InlineData(210, 140)]          // the middle of the page
    [InlineData(R, R)]              // the first pixel inside the ring
    [InlineData(W - R - 1, H - R - 1)]
    public void The_page_is_not_the_ring(int x, int y)
    {
        // The common answer, and the one that matters most: a press here has to
        // reach the app, not start a resize.
        Assert.Equal(RingEdge.None, FloatRing.HitTest(W, H, R, x, y));
    }

    [Fact]
    public void A_corner_is_wider_than_the_ring_is_thick()
    {
        // Three rings' width, i.e. eighteen pixels at six. A corner only as big
        // as the ring is thick is a six-pixel target, which is a corner people
        // miss — the reason the Windows original multiplies by three.
        Assert.Equal(RingEdge.TopLeft, FloatRing.HitTest(W, H, R, 17, 0));
        Assert.Equal(RingEdge.TopLeft, FloatRing.HitTest(W, H, R, 0, 17));
        // And it stops there: one pixel further along is a plain edge.
        Assert.Equal(RingEdge.Top, FloatRing.HitTest(W, H, R, 18, 0));
        Assert.Equal(RingEdge.Left, FloatRing.HitTest(W, H, R, 0, 18));
    }

    [Fact]
    public void Every_corner_band_is_the_same_size()
    {
        // Symmetry, stated as an assertion because the four branches are
        // written out separately and a transposed `width` for `height` in one
        // of them reads perfectly well.
        Assert.Equal(RingEdge.TopRight, FloatRing.HitTest(W, H, R, W - 18, 0));
        Assert.Equal(RingEdge.Top, FloatRing.HitTest(W, H, R, W - 19, 0));
        Assert.Equal(RingEdge.BottomLeft, FloatRing.HitTest(W, H, R, 0, H - 18));
        Assert.Equal(RingEdge.Bottom, FloatRing.HitTest(W, H, R, 210, H - 1));
    }

    [Fact]
    public void At_the_size_floor_the_corner_bands_do_not_swallow_the_page()
    {
        // 320×200 is the smallest the window goes. Three rings is 18 either
        // side, which is comfortably inside 320 — but the clamp exists for the
        // pathological case, and this pins that the floor is not it: the middle
        // of the page is still the page.
        Assert.Equal(RingEdge.None, FloatRing.HitTest(320, 200, R, 160, 100));
        Assert.Equal(RingEdge.TopLeft, FloatRing.HitTest(320, 200, R, 0, 0));
        Assert.Equal(RingEdge.Right, FloatRing.HitTest(320, 200, R, 319, 100));
    }

    [Fact]
    public void A_window_smaller_than_its_own_ring_does_not_answer_nonsense()
    {
        // Not reachable through the UI — the minimum size forbids it — but it
        // is reachable through a hand-edited settings.json, and the clamp is
        // what stops the corner bands from overlapping into a state where
        // opposite edges both claim the same pixel.
        //
        // **The assertion has to name a wrong answer.** This test used to end
        // `Assert.Contains(hit, Enum.GetValues<RingEdge>())`, which is true of
        // every possible return value — so the clamp it exists to defend could
        // be deleted with the suite still green. The concrete failure is this:
        // at 10x8 with a six-pixel ring, the corner band is 18 pixels wide and
        // every pixel in the window is "near" BOTH the left edge and the right
        // one. Left is tested first, so the top-RIGHT corner answers TopLeft
        // and a drag there resizes the window from the opposite side.
        Assert.Equal(RingEdge.TopRight, FloatRing.HitTest(10, 8, R, 9, 0));
        Assert.Equal(RingEdge.BottomRight, FloatRing.HitTest(10, 8, R, 9, 7));
        Assert.Equal(RingEdge.TopLeft, FloatRing.HitTest(10, 8, R, 0, 0));
        Assert.Equal(RingEdge.BottomLeft, FloatRing.HitTest(10, 8, R, 0, 7));
    }

    [Theory]
    [InlineData(10, 8)]
    [InlineData(12, 12)]
    [InlineData(20, 14)]
    [InlineData(MinWidth, MinHeight)]
    [InlineData(W, H)]
    public void A_press_on_one_side_never_answers_the_other(int width, int height)
    {
        // The property the clamp holds, swept over every pixel: nothing on the
        // right half may name a left edge, and nothing in the bottom half may
        // name a top one — which is what makes a resize drag pull the border
        // under the pointer rather than the one across the window.
        //
        // Per AXIS, and only where two rings fit in it. In a window narrower
        // than twelve pixels the left and right bands genuinely overlap and one
        // of them has to win; that degenerate case is pinned by the four
        // explicit corners above rather than by a property that cannot hold.
        // Every size a user can reach — the floor is 320x200 — satisfies both.
        for (var x = 0; x < width; x++)
        {
            for (var y = 0; y < height; y++)
            {
                var name = FloatRing.HitTest(width, height, R, x, y).ToString();
                if (width >= 2 * R)
                {
                    if (x >= (width + 1) / 2) Assert.DoesNotContain("Left", name);
                    if (x < width / 2) Assert.DoesNotContain("Right", name);
                }
                if (height >= 2 * R)
                {
                    if (y >= (height + 1) / 2) Assert.DoesNotContain("Top", name);
                    if (y < height / 2) Assert.DoesNotContain("Bottom", name);
                }
            }
        }
    }

    [Theory]
    [InlineData(-1, 10)]
    [InlineData(10, -1)]
    [InlineData(W, 10)]
    [InlineData(10, H)]
    public void A_point_outside_the_window_is_not_on_its_ring(int x, int y)
    {
        Assert.Equal(RingEdge.None, FloatRing.HitTest(W, H, R, x, y));
    }

    [Fact]
    public void A_ring_of_zero_is_all_page()
    {
        // The degenerate configuration, and the safe answer for it: every press
        // reaches the app rather than every press starting a resize.
        Assert.Equal(RingEdge.None, FloatRing.HitTest(W, H, 0, 0, 0));
        Assert.Equal(RingEdge.None, FloatRing.HitTest(W, H, 0, 210, 140));
    }
}
