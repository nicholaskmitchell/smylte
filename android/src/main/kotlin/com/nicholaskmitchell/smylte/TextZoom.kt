package com.nicholaskmitchell.smylte

import kotlin.math.roundToInt

/// The WebView's text zoom, from the system font size.
///
/// The ratio is measured, not taken from Configuration.fontScale. From
/// Android 14 the system scales text non-linearly: large text grows less than
/// small, so no single factor describes it. MainActivity converts the app's
/// body size both as sp (through the system's curve) and as dp (without it),
/// and the zoom is the ratio of the two. Body text, which is most of what the
/// page shows, then comes out the size native text of that size would.
object TextZoom {
    /// The body's font size in CSS px (tokens.css: `body { font-size:
    /// calc(15px * var(--fs-scale)) }`), read as sp. TextZoomTest holds it to
    /// the stylesheet.
    const val BODY_SP = 15f

    /// AOSP's own settings run from 85% to 200%, so neither bound caps a real
    /// setting; they only stop a nonsensical metric from making the page
    /// unusable. Large text is deliberately not capped below that: a layout
    /// that breaks at the largest sizes is fixed in the page.
    const val MIN_PERCENT = 50
    const val MAX_PERCENT = 300

    /// `spPx` and `dpPx`: BODY_SP converted to pixels as sp and as dp. Returns
    /// the rounded percentage, within the bounds, or 100 (no zoom) when either
    /// is not a positive finite number.
    fun percent(spPx: Float, dpPx: Float): Int {
        if (!spPx.isFinite() || !dpPx.isFinite() || spPx <= 0f || dpPx <= 0f) return 100
        return (100f * spPx / dpPx).roundToInt().coerceIn(MIN_PERCENT, MAX_PERCENT)
    }
}
