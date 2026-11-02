package com.nicholaskmitchell.smylte

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/// AES-256-GCM under a key that lives in the Android keystore.
///
/// The desktop clients use DPAPI on Windows and a derived key on Linux; this is
/// the Android equivalent and the stronger of the three: the key is generated
/// inside the keystore (hardware-backed on most phones) and cannot be exported,
/// so a copy of the app's files is useless without the device. As on the
/// desktop, it does not stop code running as this app from reading the secret.
object PasswordVault {
    private const val ALIAS = "smylte-secrets"
    private const val KEYSTORE = "AndroidKeyStore"
    private const val TRANSFORM = "AES/GCM/NoPadding"
    private const val PREFIX = "v1:"

    fun seal(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val b64 = Base64.getEncoder()
        return PREFIX + b64.encodeToString(cipher.iv) + ":" + b64.encodeToString(sealed)
    }

    /// The plain text, or null when there is nothing stored or it cannot be
    /// opened: a corrupt value, or a key the keystore no longer has.
    fun open(stored: String?): String? {
        if (stored == null || !stored.startsWith(PREFIX)) return null
        return try {
            val parts = stored.substring(PREFIX.length).split(':')
            if (parts.size != 2) return null
            val b64 = Base64.getDecoder()
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.DECRYPT_MODE, existingKey() ?: return null, GCMParameterSpec(128, b64.decode(parts[0])))
            String(cipher.doFinal(b64.decode(parts[1])), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    private fun existingKey(): SecretKey? {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        return (store.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey
    }

    private fun key(): SecretKey {
        existingKey()?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }
}
