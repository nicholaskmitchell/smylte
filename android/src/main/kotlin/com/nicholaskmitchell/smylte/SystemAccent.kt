package com.nicholaskmitchell.smylte

import android.content.Context
import android.os.Build

/// The phone's accent palette (Material You), which hello reports so the page
/// can offer the wallpaper's colour as this phone's accent (system-accent.ts).
/// Android 12 added it; Android 11 has none.
object SystemAccent {
    /// One opaque ARGB colour per tone of HostProtocol.ACCENT_TONES, in that
    /// order, or null below Android 12 or when a colour cannot be read.
    fun read(context: Context): List<Int>? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return null
        // Each id by its own name, in tone order, never computed from the
        // first: the platform publishes them one by one and promises no
        // order. HostProtocolTest holds this list to ACCENT_TONES.
        val ids = intArrayOf(
            android.R.color.system_accent1_0,
            android.R.color.system_accent1_10,
            android.R.color.system_accent1_50,
            android.R.color.system_accent1_100,
            android.R.color.system_accent1_200,
            android.R.color.system_accent1_300,
            android.R.color.system_accent1_400,
            android.R.color.system_accent1_500,
            android.R.color.system_accent1_600,
            android.R.color.system_accent1_700,
            android.R.color.system_accent1_800,
            android.R.color.system_accent1_900,
            android.R.color.system_accent1_1000,
        )
        return runCatching { ids.map { context.resources.getColor(it, context.theme) } }.getOrNull()
    }
}
