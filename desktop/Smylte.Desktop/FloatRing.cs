namespace Smylte.Desktop;

/// Which edge or corner of the floating window's ring a point is on.
///
/// Ordered so `None` is the default, and named for the geometry rather than for
/// either platform's constants: Windows answers WM_NCHITTEST with `HT*` codes
/// and GTK asks for a `GdkSurfaceEdge`, and both are a switch away from this.
public enum RingEdge
{
    None,
    Left, Right, Top, Bottom,
    TopLeft, TopRight, BottomLeft, BottomRight,
}

/// The floating window's six-pixel resize ring, as arithmetic.
///
/// Lifted out of FloatForm when the Linux client needed the same answer from a
/// gesture rather than from a hit-test message. That was worth doing on its own
/// merits: it is thirty lines of corner arithmetic whose failure mode is a
/// window whose bottom-right corner cannot be grabbed, or one where a press
/// three pixels inside the page starts a resize instead of reaching the app —
/// neither of which throws, and neither of which any test could reach while it
/// lived inside a WinForms message loop.
///
/// Everything is integers in one coordinate space: the window's own, origin at
/// its top-left, `ring` pixels of frame on every side. No DPI enters — the
/// caller has already resolved that (Windows scales the padding, GTK sizes in
/// logical pixels), which is why this can be shared at all.
public static class FloatRing
{
    /// How much wider a corner's grab area is than a plain edge's. Three rings,
    /// i.e. eighteen pixels at the default six — a corner that is only as big
    /// as the ring is thick is a corner nobody can hit on the first try.
    private const int CornerRings = 3;

    public static RingEdge HitTest(int width, int height, int ring, int x, int y)
    {
        // Outside the window, or inside the page: not ours. The inner test is
        // first-class rather than a fallthrough because the page occupies all
        // but `ring` pixels and is by far the common answer.
        if (x < 0 || y < 0 || x >= width || y >= height) return RingEdge.None;
        if (ring <= 0) return RingEdge.None;
        if (x >= ring && x < width - ring && y >= ring && y < height - ring) return RingEdge.None;

        // A window narrower than two rings has no inside at all; clamping keeps
        // the corner bands from overlapping into nonsense at the size floor.
        var corner = Math.Min(ring * CornerRings, Math.Min(width, height) / 2);

        var onLeft = x < ring;
        var onRight = x >= width - ring;
        var onTop = y < ring;
        var onBottom = y >= height - ring;

        var nearLeft = x < corner;
        var nearRight = x >= width - corner;
        var nearTop = y < corner;
        var nearBottom = y >= height - corner;

        if (onTop || onBottom)
        {
            if (nearLeft) return onTop ? RingEdge.TopLeft : RingEdge.BottomLeft;
            if (nearRight) return onTop ? RingEdge.TopRight : RingEdge.BottomRight;
            return onTop ? RingEdge.Top : RingEdge.Bottom;
        }
        if (onLeft)
        {
            if (nearTop) return RingEdge.TopLeft;
            if (nearBottom) return RingEdge.BottomLeft;
            return RingEdge.Left;
        }
        if (onRight)
        {
            if (nearTop) return RingEdge.TopRight;
            if (nearBottom) return RingEdge.BottomRight;
            return RingEdge.Right;
        }
        return RingEdge.None;
    }
}
