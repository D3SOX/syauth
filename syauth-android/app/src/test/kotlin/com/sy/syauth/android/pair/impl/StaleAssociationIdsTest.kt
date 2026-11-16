package com.sy.syauth.android.pair.impl

import org.junit.Assert.assertEquals
import org.junit.Test

class StaleAssociationIdsTest {
    @Test
    fun returns_other_associations_for_the_same_device_only() {
        val associations = listOf(
            1 to "84:1b:77:aa:85:b0",
            2 to "84:1B:77:AA:85:B0",
            3 to "11:22:33:44:55:66",
            4 to null,
            5 to "84:1b:77:aa:85:b0",
        )

        val stale = staleAssociationIds(associations, mac = "84:1b:77:aa:85:b0", keepId = 5)

        assertEquals(listOf(1, 2), stale)
    }

    @Test
    fun returns_nothing_when_the_kept_association_is_the_only_one() {
        val stale = staleAssociationIds(listOf(7 to "84:1b:77:aa:85:b0"), mac = "84:1b:77:aa:85:b0", keepId = 7)

        assertEquals(emptyList<Int>(), stale)
    }
}
