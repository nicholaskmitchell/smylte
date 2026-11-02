package com.nicholaskmitchell.smylte

import android.view.View
import android.view.Window
import android.view.WindowInsets

/// Edge to edge, with the content padded clear of the bars and the keyboard.
///
/// Android 15 draws every app targeting it edge to edge whether it asks or
/// not, and on 16 an app cannot opt out. So the window draws behind the bars
/// on every version, and the root view pads its content by the insets. What
/// shows behind the bars is the root's own background: the page's colour, in
/// MainActivity.
///
/// The keyboard is an inset too. Edge to edge, `adjustResize` no longer
/// shrinks the window, so without the IME term a field near the bottom of the
/// page would sit under the keyboard.
object Insets {
    fun edgeToEdge(window: Window, root: View) {
        window.setDecorFitsSystemWindows(false)
        root.setOnApplyWindowInsetsListener { view, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsets.CONSUMED
        }
        root.requestApplyInsets()
    }
}
