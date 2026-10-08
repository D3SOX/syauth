// Roadmap item S-015 — Robolectric JVM tests for the
// BiometricPrompt + Keystore-sign path on
// `ChallengeApprovalActivity`. Pins the DoD bullets from
// `specs/unlock-proximity/ROADMAP.md` Step S-015 verbatim:
//
//   1. `strong_authenticator_required` — the constructed
//      `BiometricPrompt.PromptInfo.allowedAuthenticators` equals
//      `BiometricManager.Authenticators.BIOMETRIC_STRONG` and
//      carries no DEVICE_CREDENTIAL bit.
//   2. `per_use_keystore_unlock` — a second request requires
//      a second `BiometricGate.authenticate(...)` call (the
//      Keystore key was released for exactly one use per
//      BiometricPrompt round; no cached signature reuse).
//   3. `cancel_writes_denied` — when the injected gate's
//      `fail(reason)` callback fires, the response sink receives
//      one call with bytes equal to `DENIED_FRAME_BYTES` and the
//      activity is `finishing`.
//
// The injected `BiometricGate` is the test seam the production
// flow goes through. In production the gate wraps the real
// `androidx.biometric.BiometricPrompt`; in tests a recording fake
// drives `succeed(signatureBytes)` / `fail(reason)` manually.
//
// Journey: specs/journeys/JOURNEY-S-015-biometric-keystore-sign.md
package com.sy.syauth.android.bg

import android.content.Intent
import androidx.biometric.BiometricManager
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Before
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

private const val FIXTURE_HOSTNAME: String = "alex-desktop"
private const val FIXTURE_PEER_ID: String = "AA:BB:CC:DD:EE:FF"
private const val FIXTURE_KEYSTORE_ALIAS: String = "syauth.test.s015.alias"
private const val FIXTURE_CHALLENGE_LEN: Int = 49
private val FIXTURE_SIGNATURE: ByteArray = ByteArray(SIGNATURE_LEN) { (it + 7).toByte() }
private val SECOND_FIXTURE_SIGNATURE: ByteArray = ByteArray(SIGNATURE_LEN) { (it + 13).toByte() }

private class RecordingResponseSink : ResponseSink {
    val calls: MutableList<Pair<String, ByteArray>> = mutableListOf()
    override fun onResponse(peerId: String, responseBytes: ByteArray) {
        calls += peerId to responseBytes
    }
}

private class RecordingBiometricGate : BiometricGate {
    var cancelCount = 0
    override fun cancel() { cancelCount += 1 }
    var lastChallenge: ByteArray = ByteArray(0)
        private set
    var lastCallback: BiometricGateCallback? = null
        private set
    var callCount: Int = 0
        private set

    override fun authenticate(
        keystoreAlias: String,
        challengeBytes: ByteArray,
        callback: BiometricGateCallback,
    ) {
        callCount += 1
        lastChallenge = challengeBytes
        lastCallback = callback
    }

    fun succeed(signatureBytes: ByteArray) {
        val cb = lastCallback ?: error("gate.authenticate was not called")
        cb.onSucceeded(signatureBytes)
    }

    fun dismiss() {
        val cb = lastCallback ?: error("gate.authenticate was not called")
        cb.onDismissed()
    }

    fun fail(reason: String) {
        val cb = lastCallback ?: error("gate.authenticate was not called")
        cb.onFailed(reason)
    }
}

private fun fixtureIntent(): Intent {
    val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    return Intent(context, ChallengeApprovalActivity::class.java).apply {
        putExtra(EXTRA_PEER_ID, FIXTURE_PEER_ID)
        putExtra(EXTRA_HOSTNAME, FIXTURE_HOSTNAME)
        putExtra(EXTRA_CHALLENGE_BYTES, ByteArray(FIXTURE_CHALLENGE_LEN) { it.toByte() })
        putExtra(EXTRA_KEYSTORE_ALIAS, FIXTURE_KEYSTORE_ALIAS)
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class BiometricPromptTest {

    @Before
    fun setup() {
        ChallengeApprovalActivity.biometricGate = RecordingBiometricGate()
    }

    @After
    fun cleanup() {
        ChallengeApprovalActivity.resetSeams()
        SyauthCompanionService.resetSeams()
    }

    @Test
    fun request_opens_biometrics_once_without_an_approve_tap() {
        val gate = RecordingBiometricGate()
        val sink = RecordingResponseSink()
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = sink
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()

        assertEquals("request opens the fingerprint prompt", 1, gate.callCount)
        assertTrue("opening a prompt does not authorize", sink.calls.isEmpty())
        controller.pause().resume()
        assertEquals("resuming does not open a duplicate prompt", 1, gate.callCount)
        gate.succeed(FIXTURE_SIGNATURE)
        assertEquals(1, sink.calls.size)
        assertArrayEquals(FIXTURE_SIGNATURE, sink.calls.single().second)
        controller.pause().stop().destroy()
    }

    @Test
    fun dismissing_biometrics_returns_to_approval_and_allows_manual_retry() {
        val gate = RecordingBiometricGate()
        val sink = RecordingResponseSink()
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = sink
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()
        val activity = controller.get()

        val dismissedCallback = gate.lastCallback!!
        gate.dismiss()
        dismissedCallback.onSucceeded(FIXTURE_SIGNATURE)

        assertTrue("dismissal returns to the approval screen", !activity.isFinishing)
        assertTrue("dismissal does not reject or authorize", sink.calls.isEmpty())
        controller.pause().resume()
        assertEquals("returning to the screen does not reopen biometrics", 1, gate.callCount)
        activity.startAuthentication()
        assertEquals("Authorize can reopen biometrics", 2, gate.callCount)
        dismissedCallback.onSucceeded(FIXTURE_SIGNATURE)
        assertTrue("a dismissed operation cannot answer a retry", sink.calls.isEmpty())
        gate.succeed(FIXTURE_SIGNATURE)
        assertEquals(1, sink.calls.size)
        assertArrayEquals(FIXTURE_SIGNATURE, sink.calls.single().second)
        controller.pause().stop().destroy()
    }

    @Test
    fun disallow_rejects_the_request_after_biometrics_are_dismissed() {
        val gate = RecordingBiometricGate()
        val responses = RecordingResponseSink()
        var denied = 0
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = responses
        ChallengeApprovalActivity.cancelSink = CancelSink { peerId, bytes ->
            assertEquals(FIXTURE_PEER_ID, peerId)
            assertArrayEquals(DENIED_FRAME_BYTES, bytes)
            denied += 1
        }
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()
        gate.dismiss()

        controller.get().onCancelClicked()
        gate.succeed(FIXTURE_SIGNATURE)

        assertEquals(1, denied)
        assertTrue(controller.get().isFinishing)
        assertTrue(responses.calls.isEmpty())
        controller.pause().stop().destroy()
    }

    @Test
    fun missing_request_extras_do_not_open_biometrics() {
        val gate = RecordingBiometricGate()
        ChallengeApprovalActivity.biometricGate = gate
        val controller = Robolectric.buildActivity(
            ChallengeApprovalActivity::class.java,
            fixtureIntent().apply { removeExtra(EXTRA_HOSTNAME) },
        ).create().start().resume()

        assertTrue(controller.get().isFinishing)
        assertEquals(0, gate.callCount)
        controller.pause().stop().destroy()
    }

    @Test
    fun strong_authenticator_required() {
        val controller = Robolectric.buildActivity(
            ChallengeApprovalActivity::class.java,
            fixtureIntent(),
        ).create().start().resume()
        val activity = controller.get()

        val promptInfo = activity.buildPromptInfoForTest()

        assertNotNull("PromptInfo must be non-null", promptInfo)
        assertEquals(
            "allowedAuthenticators must equal BIOMETRIC_STRONG only",
            BiometricManager.Authenticators.BIOMETRIC_STRONG,
            promptInfo.allowedAuthenticators,
        )
    }

    @Test
    fun per_use_keystore_unlock() {
        val gate = RecordingBiometricGate()
        val sink = RecordingResponseSink()
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = sink
        val controller = Robolectric.buildActivity(
            ChallengeApprovalActivity::class.java,
            fixtureIntent(),
        ).create().start().resume()
        assertEquals("first request invokes gate exactly once", 1, gate.callCount)
        gate.succeed(FIXTURE_SIGNATURE)

        // A fresh request must perform a new per-use biometric operation.
        ChallengeApprovalActivity.biometricGate = gate
        val secondController = Robolectric.buildActivity(
            ChallengeApprovalActivity::class.java,
            fixtureIntent(),
        ).create().start().resume()
        gate.succeed(SECOND_FIXTURE_SIGNATURE)

        assertEquals("each request invokes gate exactly once", 2, gate.callCount)
        assertEquals(2, sink.calls.size)
        assertArrayEquals(
            "first response carries the first signature",
            FIXTURE_SIGNATURE,
            sink.calls[0].second,
        )
        assertArrayEquals(
            "second response carries the second signature",
            SECOND_FIXTURE_SIGNATURE,
            sink.calls[1].second,
        )
        controller.pause().stop().destroy()
        secondController.pause().stop().destroy()
    }

    @Test
    fun cancel_writes_denied() {
        val gate = RecordingBiometricGate()
        val sink = RecordingResponseSink()
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = sink
        val controller = Robolectric.buildActivity(
            ChallengeApprovalActivity::class.java,
            fixtureIntent(),
        ).create().start().resume()
        val activity = controller.get()

        gate.fail("keystore unavailable")

        assertEquals("fail path writes exactly one response", 1, sink.calls.size)
        assertEquals(FIXTURE_PEER_ID, sink.calls[0].first)
        assertArrayEquals(
            "fail path writes DENIED_FRAME_BYTES",
            DENIED_FRAME_BYTES,
            sink.calls[0].second,
        )
        assertTrue("activity is finishing after biometric fail", activity.isFinishing)
    }
    @Test
    fun host_cancel_dismisses_biometric_and_ignores_late_success() {
        val gate = RecordingBiometricGate()
        val sink = RecordingResponseSink()
        ChallengeApprovalActivity.biometricGate = gate
        ChallengeApprovalActivity.responseSink = sink
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()
        val activity = controller.get()
        val nonce = ByteArray(FIXTURE_CHALLENGE_LEN) { it.toByte() }.copyOfRange(1, 17)
        SyauthCompanionService.cancelledApproval.value = FIXTURE_PEER_ID to nonce
        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertTrue(activity.isFinishing)
        assertEquals(1, gate.cancelCount)
        gate.succeed(ByteArray(64))
        assertTrue(sink.calls.isEmpty())
        controller.pause().stop().destroy()
    }

    @Test
    fun mismatched_or_unverified_host_cancel_does_not_dismiss() {
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()
        val activity = controller.get()
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        SyauthCompanionService.bondKeyProvider = BondKeyProvider { ByteArray(32) }
        SyauthCompanionService.challengeVerifier = ChallengeVerifier { _, _ -> null }
        val forged = ByteArray(39)
        ByteArray(FIXTURE_CHALLENGE_LEN) { it.toByte() }.copyInto(forged, endIndex = 17)
        "cancel".toByteArray().copyInto(forged, destinationOffset = 17)
        SyauthCompanionService.handleChallengeFrame(context, FIXTURE_PEER_ID, forged)
        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertTrue(SyauthCompanionService.cancelledApproval.value == null)
        assertTrue(!activity.isFinishing)
        SyauthCompanionService.cancelledApproval.value = FIXTURE_PEER_ID to ByteArray(16)
        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertTrue(!activity.isFinishing)
        controller.pause().stop().destroy()
    }

    @Test
    fun verified_cancel_received_before_activity_launch_dismisses_matching_nonce() {
        val gate = RecordingBiometricGate()
        ChallengeApprovalActivity.biometricGate = gate
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val frame = ByteArray(39)
        ByteArray(FIXTURE_CHALLENGE_LEN) { it.toByte() }.copyInto(frame, endIndex = 17)
        SyauthCompanionService.bondKeyProvider = BondKeyProvider { ByteArray(32) }
        SyauthCompanionService.challengeVerifier = ChallengeVerifier { _, _ -> "cancel".toByteArray() }
        SyauthCompanionService.handleChallengeFrame(context, FIXTURE_PEER_ID, frame)
        val controller = Robolectric.buildActivity(ChallengeApprovalActivity::class.java, fixtureIntent())
            .create().start().resume()
        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
        assertTrue(controller.get().isFinishing)
        assertEquals("cancelled request must not open biometrics", 0, gate.callCount)
        controller.pause().stop().destroy()
    }

}
