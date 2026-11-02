package com.nicholaskmitchell.smylte

/// Where the client and the web build come from: the same rolling release the
/// desktop clients read (desktop/Smylte.Desktop/Updater.cs). One release carries
/// every client and the one platform-neutral web build they all share.
object Release {
    const val OWNER = "nicholaskmitchell"
    const val REPO = "smylte"
    const val TAG = "desktop-latest"

    /// The web build. The same bytes the Windows and Linux clients unpack.
    const val WEB_ASSET = "smylte-web.zip"

    /// This client. Each client asks only about its own binary.
    const val CLIENT_ASSET = "Smylte-android.apk"

    const val API = "https://api.github.com/repos/$OWNER/$REPO"

    /// Where to send someone when the in-app update cannot finish. The release
    /// is rolling, so this link never changes.
    const val PAGE = "https://github.com/$OWNER/$REPO/releases/tag/$TAG"
}

/// One asset of the release, as much of it as the updater reads.
///
/// `digest` is GitHub's own "sha256:<hex>" for the uploaded bytes, or null when
/// the release does not state one.
data class ReleaseAsset(
    val id: Long,
    val name: String,
    val updatedAt: String,
    val digest: String?,
) {
    /// What a web build on disk records about where it came from.
    val identity: BuildIdentity get() = BuildIdentity(id, updatedAt)
}

/// Which upload a web build was unpacked from. The asset id alone is not
/// enough: `gh release upload --clobber` can keep an id and replace the bytes,
/// which is why the desktop client keys on id AND updated_at too.
data class BuildIdentity(val id: Long, val updatedAt: String)
