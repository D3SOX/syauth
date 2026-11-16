package com.sy.syauth.android.bond

import java.security.KeyStore
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SigningKeyTest {
    private fun emptyStore(): KeyStore = KeyStore.getInstance("PKCS12").apply { load(null, null) }

    @Test
    fun missing_alias_is_not_usable() {
        assertFalse(isSigningKeyUsable("syauth.ed25519.841B77AA85B0", ::emptyStore))
    }

    @Test
    fun empty_alias_is_not_usable() {
        assertFalse(isSigningKeyUsable("", ::emptyStore))
    }

    @Test
    fun unrelated_keystore_failure_does_not_ask_for_a_re_pair() {
        assertTrue(isSigningKeyUsable("syauth.ed25519.841B77AA85B0") { error("keystore unavailable") })
    }
}
