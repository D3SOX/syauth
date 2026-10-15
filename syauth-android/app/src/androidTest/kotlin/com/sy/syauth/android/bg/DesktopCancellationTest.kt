package com.sy.syauth.android.bg

import android.content.Context
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

// Generated with syauth_core::Frame and compute_tag, using key=[1;32].
private const val CHALLENGE_HEX = "0102020202020202020202020202020202fae96b53288e050d62f15ff1ef14924d"
private const val CANCEL_HEX = "010202020202020202020202020202020263616e63656c8ab8868f8126f2a91df0b0f7c919b233"
private const val STALE_CANCEL_HEX = "010303030303030303030303030303030363616e63656c773ba3067140aa4718b4763206cae805"
private const val PEER = "cancellation-test"

@RunWith(AndroidJUnit4::class)
class DesktopCancellationTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private var previousKeys: BondKeyProvider? = null
    private var previousVerifier: ChallengeVerifier? = null

    @Before
    fun setup() {
        previousKeys = SyauthCompanionService.bondKeyProvider
        previousVerifier = SyauthCompanionService.challengeVerifier
        SyauthCompanionService.bondKeyProvider = BondKeyProvider { if (it == PEER) ByteArray(32) { 1 } else null }
        SyauthCompanionService.challengeVerifier = UniffiChallengeVerifier()
        ChallengeApprovalActivity.resetSeams()
        ChallengeApprovalActivity.biometricGate = object : BiometricGate {
            override fun cancel() = Unit
            override fun authenticate(keystoreAlias: String, challengeBytes: ByteArray, callback: BiometricGateCallback) = Unit
        }
    }

    @After
    fun restore() {
        SyauthCompanionService.bondKeyProvider = previousKeys
        SyauthCompanionService.challengeVerifier = previousVerifier
        ChallengeApprovalActivity.resetSeams()
        SyauthCompanionService.cancelledApproval.value = null
    }

    private fun decode(hex: String): ByteArray = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    private fun launch(): ActivityScenario<ChallengeApprovalActivity> {
        val frame = decode(CHALLENGE_HEX)
        return ActivityScenario.launch(buildApprovalIntent(context, PEER, "cancel-test", frame.copyOfRange(0, frame.size - 16), ""))
    }

    private fun deliver(frame: ByteArray) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync { SyauthCompanionService.handleChallengeFrame(context, PEER, frame) }
        instrumentation.waitForIdleSync()
    }

    @Test
    fun authenticated_cancellation_closes_the_native_approval() {
        launch().use { scenario ->
            assertEquals(Lifecycle.State.RESUMED, scenario.state)
            deliver(decode(CANCEL_HEX))
            assertEquals(Lifecycle.State.DESTROYED, scenario.state)
        }
    }

    @Test
    fun tampered_cancellation_cannot_close_the_approval() {
        launch().use { scenario ->
            val forged = decode(CANCEL_HEX)
            forged[forged.lastIndex] = (forged.last().toInt() xor 1).toByte()
            deliver(forged)
            assertEquals(Lifecycle.State.RESUMED, scenario.state)
        }
    }

    @Test
    fun authenticated_cancellation_for_another_nonce_is_ignored() {
        launch().use { scenario ->
            deliver(decode(STALE_CANCEL_HEX))
            assertEquals(Lifecycle.State.RESUMED, scenario.state)
        }
    }
}
