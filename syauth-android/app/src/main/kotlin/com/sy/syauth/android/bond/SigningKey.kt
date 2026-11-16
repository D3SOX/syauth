// Detects a bond whose Keystore signing key is gone.
//
// Android Keystore keys never leave the device and are not part of app
// backups. Restoring app data (for example with a root backup tool) or
// re-enrolling biometrics leaves `syauth-bond.toml` in place while the
// key under its alias is missing or permanently invalidated. Every
// approval then fails, and the desktop only sees failed signatures, so
// the app checks the key on startup and asks the user to re-pair.
package com.sy.syauth.android.bond

import android.security.keystore.KeyPermanentlyInvalidatedException
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature

/** Android Keystore provider name. */
private const val ANDROID_KEYSTORE: String = "AndroidKeyStore"

/** JCA name of the bond's signing algorithm. */
private const val ED25519: String = "Ed25519"

/**
 * Return false when [alias] has no usable private key in [keyStore]:
 * the alias is empty or missing, the entry is not a private key, or
 * the key was permanently invalidated. An invalidated key is deleted,
 * as the approval gate does, because pairing reuses an existing alias
 * and would otherwise keep the broken key. Other failures return true
 * so an unrelated Keystore error does not tell the user to re-pair.
 *
 * `initSign` does not need a biometric unlock for per-use keys; only
 * `sign()` does, so the check is silent.
 */
public fun isSigningKeyUsable(alias: String, keyStore: () -> KeyStore = ::androidKeyStore): Boolean {
    if (alias.isEmpty()) return false
    val store = try {
        keyStore()
    } catch (_: Exception) {
        return true
    }
    return try {
        if (!store.containsAlias(alias)) return false
        val key = store.getKey(alias, null) as? PrivateKey ?: return false
        Signature.getInstance(ED25519).initSign(key)
        true
    } catch (_: KeyPermanentlyInvalidatedException) {
        runCatching { store.deleteEntry(alias) }
        false
    } catch (_: Exception) {
        true
    }
}

private fun androidKeyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
