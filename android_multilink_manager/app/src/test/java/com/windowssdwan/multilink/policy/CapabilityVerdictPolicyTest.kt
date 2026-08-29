package com.windowssdwan.multilink.policy

import com.windowssdwan.multilink.model.HotspotState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CapabilityVerdictPolicyTest {

    @Test
    fun `fixed architectural facts never change regardless of inputs`() {
        val verdict = CapabilityVerdictPolicy.buildVerdict(
            hasPrivilegedTetherPermission = false,
            wifiAvailableAndValidated = true,
            cellularAvailableAndValidated = true,
            hotspotState = HotspotState.UNKNOWN
        )
        assertTrue(verdict.perFlowSelectionSupported)
        assertFalse(verdict.phoneWideSteeringSupported)
        assertFalse(verdict.hotspotClientSteeringSupported)
        assertFalse(verdict.trueBondingSupportedOnDevice)
    }

    @Test
    fun `both concurrently available is true only when both are validated`() {
        val bothUp = CapabilityVerdictPolicy.buildVerdict(false, true, true, HotspotState.UNKNOWN)
        val onlyWifi = CapabilityVerdictPolicy.buildVerdict(false, true, false, HotspotState.UNKNOWN)
        val neither = CapabilityVerdictPolicy.buildVerdict(false, false, false, HotspotState.UNKNOWN)

        assertTrue(bothUp.bothConcurrentlyAvailable)
        assertFalse(onlyWifi.bothConcurrentlyAvailable)
        assertFalse(neither.bothConcurrentlyAvailable)
    }

    @Test
    fun `expected normal-app case reports no privileged permission`() {
        val verdict = CapabilityVerdictPolicy.buildVerdict(false, true, false, HotspotState.UNKNOWN)
        assertFalse(verdict.hasPrivilegedTetherPermission)
        assertTrue(verdict.explanationLines.any { it.contains("NOT held") })
    }

    @Test
    fun `unexpected privileged permission is called out explicitly in explanation`() {
        val verdict = CapabilityVerdictPolicy.buildVerdict(true, true, false, HotspotState.UNKNOWN)
        assertTrue(verdict.hasPrivilegedTetherPermission)
        assertTrue(verdict.explanationLines.any { it.contains("Unexpected") })
    }

    @Test
    fun `unknown hotspot state is explained rather than guessed`() {
        val verdict = CapabilityVerdictPolicy.buildVerdict(false, true, false, HotspotState.UNKNOWN)
        assertEquals(HotspotState.UNKNOWN, verdict.hotspotState)
        assertTrue(verdict.explanationLines.any { it.contains("Unknown", ignoreCase = false) })
    }
}
