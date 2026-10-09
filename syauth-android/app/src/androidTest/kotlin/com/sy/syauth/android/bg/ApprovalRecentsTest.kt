package com.sy.syauth.android.bg

import android.accessibilityservice.AccessibilityService
import android.app.ActivityManager
import android.content.Context
import android.os.SystemClock
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises real Android task removal without Bluetooth or fingerprint hardware. */
@RunWith(AndroidJUnit4::class)
class ApprovalRecentsTest {
    @Test
    fun dismissed_biometrics_preserve_background_request_until_terminal_outcome() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val tasks = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        var pendingCallback: BiometricGateCallback? = null
        ChallengeApprovalActivity.biometricGate = object : BiometricGate {
            override fun cancel() = Unit
            override fun authenticate(keystoreAlias: String, challengeBytes: ByteArray, callback: BiometricGateCallback) {
                pendingCallback = callback
            }
        }
        try {
            for (outcome in listOf("approved", "disallowed", "host-cancelled", "error")) {
                SyauthCompanionService.cancelledApproval.value = null
                val challenge = ByteArray(CHALLENGE_LENGTH) { it.toByte() }
                val intent = buildApprovalIntent(context, PEER_ID, "test-desktop", challenge, "test-key")
                ActivityScenario.launch<ChallengeApprovalActivity>(intent).use { scenario ->
                    var taskId = -1
                    scenario.onActivity { taskId = it.taskId }
                    assertTrue("pending $outcome task exists", tasks.findTask(taskId) != null)
                    scenario.onActivity { pendingCallback!!.onDismissed() }
                    assertTrue(instrumentation.uiAutomation.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME))
                    val backgroundDeadline = SystemClock.uptimeMillis() + TASK_REMOVAL_TIMEOUT_MILLIS
                    while (scenario.state != Lifecycle.State.CREATED && scenario.state != Lifecycle.State.DESTROYED &&
                        SystemClock.uptimeMillis() < backgroundDeadline) {
                        Thread.sleep(TASK_POLL_INTERVAL_MILLIS)
                    }
                    assertEquals("switching apps keeps the request pending", Lifecycle.State.CREATED, scenario.state)
                    assertTrue("background pending task remains in Recents", tasks.findTask(taskId) != null)
                    if (outcome == "host-cancelled") {
                        instrumentation.runOnMainSync {
                            SyauthCompanionService.cancelledApproval.value = PEER_ID to challenge.copyOfRange(1, CHALLENGE_HEADER_BYTES)
                        }
                    } else {
                        requireNotNull(tasks.findTask(taskId)).moveToFront()
                        scenario.moveToState(Lifecycle.State.RESUMED)
                        scenario.onActivity { activity ->
                            activity.startAuthentication()
                            when (outcome) {
                                "approved" -> pendingCallback!!.onSucceeded(ByteArray(SIGNATURE_LEN))
                                "disallowed" -> activity.onCancelClicked()
                                "error" -> pendingCallback!!.onFailed("test error")
                            }
                        }
                    }
                    instrumentation.waitForIdleSync()
                    val deadline = SystemClock.uptimeMillis() + TASK_REMOVAL_TIMEOUT_MILLIS
                    while (tasks.findTask(taskId) != null && SystemClock.uptimeMillis() < deadline) {
                        Thread.sleep(TASK_POLL_INTERVAL_MILLIS)
                    }
                    assertFalse("finished $outcome task remains in Recents", tasks.findTask(taskId) != null)
                }
            }
        } finally {
            ChallengeApprovalActivity.resetSeams()
            SyauthCompanionService.cancelledApproval.value = null
        }
    }

    // Android can remove a task between listing it and reading its taskInfo.
    private fun ActivityManager.findTask(taskId: Int): ActivityManager.AppTask? =
        appTasks.firstOrNull { task ->
            try {
                task.taskInfo.taskId == taskId
            } catch (_: IllegalArgumentException) {
                false
            }
        }

    private companion object {
        const val PEER_ID = "recents-test-peer"
        const val CHALLENGE_LENGTH = 33
        const val TASK_REMOVAL_TIMEOUT_MILLIS = 5_000L
        const val TASK_POLL_INTERVAL_MILLIS = 50L
    }
}
