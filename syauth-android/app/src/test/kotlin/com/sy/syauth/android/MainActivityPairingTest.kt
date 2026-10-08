// Regression: specs/bugs/BUG-2026-10-08-pairing-refresh.md
package com.sy.syauth.android

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import androidx.work.Configuration
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import com.sy.syauth.android.bg.SyauthCompanionService
import com.sy.syauth.android.bond.BondRecord
import com.sy.syauth.android.bond.BondStore
import com.sy.syauth.android.pair.PairingState
import org.junit.After
import org.junit.Before
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class MainActivityPairingTest {
    private val app: Application
        get() = ApplicationProvider.getApplicationContext()

    @Before
    fun setup() {
        WorkManagerTestInitHelper.initializeTestWorkManager(
            app,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build(),
        )
        BondStore(app.filesDir).storePath.delete()
    }

    @After
    fun cleanup() {
        BondStore(app.filesDir).storePath.delete()
        SyauthCompanionService.resetSeams()
    }

    @Test
    fun pairing_updates_home_and_starts_companion_without_recreating_activity() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        val activity = controller.get()
        assertNull(activity.bondRecord.value)
        assertNull(shadowOf(app).nextStartedService)
        val record = BondRecord(
            peerId = "AA:BB:CC:DD:EE:FF",
            hostName = "test-laptop",
            bondKey = ByteArray(32) { it.toByte() },
            keystoreAlias = "syauth.test.pairing",
            phonePubkey = ByteArray(32) { (it + 1).toByte() },
        )
        BondStore(app.filesDir).save(record)

        activity.onPairingFinished(PairingState.Bonded(record.hostName))

        assertEquals(record, activity.bondRecord.value)
        assertEquals(record.keystoreAlias, SyauthCompanionService.keystoreAliasResolver?.keystoreAliasFor(record.peerId))
        assertEquals(SyauthCompanionService::class.java.name, shadowOf(app).nextStartedService?.component?.className)
        controller.destroy()
    }

    @Test
    fun failed_pairing_does_not_activate_a_partially_saved_bond() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()
        BondStore(app.filesDir).save(BondRecord(
            peerId = "AA:BB:CC:DD:EE:FF",
            hostName = "failed-laptop",
            bondKey = ByteArray(32),
            keystoreAlias = "syauth.test.failed",
            phonePubkey = ByteArray(32),
        ))

        controller.get().onPairingFinished(PairingState.Failed("association failed"))

        assertNull(controller.get().bondRecord.value)
        assertNull(shadowOf(app).nextStartedService)
        controller.destroy()
    }

    @Test
    fun missing_bond_does_not_start_the_companion_service() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).create()

        controller.get().onPairingFinished(PairingState.Bonded("missing-laptop"))

        assertNull(controller.get().bondRecord.value)
        assertNull(shadowOf(app).nextStartedService)
        controller.destroy()
    }
}
