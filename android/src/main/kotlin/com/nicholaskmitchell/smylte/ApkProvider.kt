package com.nicholaskmitchell.smylte

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException

/// Hands the one downloaded, verified APK to the system installer.
///
/// The installer reads it through a content URI granted on the install intent,
/// which is how Android wants a file passed to another app. This serves exactly
/// one path, read-only, and is not exported: nothing reaches it without that
/// grant. AndroidX's FileProvider does the same job for any file; it is not used
/// because this client takes no dependencies.
class ApkProvider : ContentProvider() {
    companion object {
        const val MIME = "application/vnd.android.package-archive"
        private const val NAME = "Smylte-android.apk"

        fun file(context: Context): File = File(File(context.cacheDir, "updates"), NAME)

        fun uri(context: Context): Uri = Uri.Builder()
            .scheme("content")
            .authority("${context.packageName}.apk")
            .appendPath(NAME)
            .build()
    }

    override fun onCreate(): Boolean = true

    private fun isOurs(uri: Uri): Boolean = uri.pathSegments == listOf(NAME)

    override fun getType(uri: Uri): String? = if (isOurs(uri)) MIME else null

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (!isOurs(uri) || mode != "r") throw FileNotFoundException("Not available.")
        val file = file(context ?: throw FileNotFoundException("No context."))
        if (!file.isFile) throw FileNotFoundException("No update has been downloaded.")
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    /// Name and size, which installers ask for before reading.
    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? {
        if (!isOurs(uri)) return null
        val file = file(context ?: return null)
        val columns = projection?.filter {
            it == OpenableColumns.DISPLAY_NAME || it == OpenableColumns.SIZE
        }?.toTypedArray() ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        return MatrixCursor(columns, 1).apply {
            addRow(columns.map { if (it == OpenableColumns.DISPLAY_NAME) NAME else file.length() })
        }
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
