package com.nicholaskmitchell.smylte

import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/// The one thread every update step runs on.
///
/// Process-wide rather than per activity, so a window recreated mid-download
/// (a crashed renderer, say) cannot start a second download that stages into
/// the same directory as the first. Serialising them is the whole job.
object Background {
    val updates: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "smylte-updates").apply { isDaemon = true }
    }
}
