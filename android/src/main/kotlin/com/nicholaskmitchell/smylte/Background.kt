package com.nicholaskmitchell.smylte

import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/// The threads that work off the main thread.
object Background {
    /// The one thread every update step runs on.
    ///
    /// Process-wide rather than per activity, so a window recreated mid-download
    /// (a crashed renderer, say) cannot start a second download that stages into
    /// the same directory as the first. Serialising them is the whole job.
    val updates: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "smylte-updates").apply { isDaemon = true }
    }

    /// Writing a file the user chose to save. Its own thread: the update thread can be busy
    /// with an APK download for minutes, and someone is waiting on a save.
    val files: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "smylte-files").apply { isDaemon = true }
    }
}
