package com.windowssdwan.multilink.networking

import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetworkLinkReducerTest {

    private fun snapshot(linkId: LinkId, transport: TransportKind = TransportKind.WIFI, validated: Boolean = true) =
        NetworkLinkSnapshot(
            linkId = linkId,
            transport = transport,
            validated = validated,
            hasInternetCapability = true,
            metered = false,
            roaming = false,
            downstreamKbpsEstimate = null,
            upstreamKbpsEstimate = null,
            signalStrengthOrUnknown = null,
            interfaceName = "wlan0",
            ipAddresses = emptyList(),
            dnsServers = emptyList(),
            hasDefaultRoute = true,
            routeSummaries = emptyList(),
            lastUpdatedAtMs = 0L
        )

    @Test
    fun `updated event adds a new link`() {
        val linkId = LinkId(1L)
        val next = NetworkLinkReducer.reduce(emptyMap(), NetworkLinkEvent.Updated(snapshot(linkId)))
        assertTrue(next.containsKey(linkId))
    }

    @Test
    fun `updated event for an existing link replaces its snapshot`() {
        val linkId = LinkId(1L)
        val original = mapOf(linkId to snapshot(linkId, validated = false))
        val next = NetworkLinkReducer.reduce(original, NetworkLinkEvent.Updated(snapshot(linkId, validated = true)))
        assertTrue(next.getValue(linkId).validated)
    }

    @Test
    fun `removed event drops the link`() {
        val linkId = LinkId(1L)
        val original = mapOf(linkId to snapshot(linkId))
        val next = NetworkLinkReducer.reduce(original, NetworkLinkEvent.Removed(linkId))
        assertFalse(next.containsKey(linkId))
    }

    @Test
    fun `removed event for an unknown link is a no-op`() {
        val linkId = LinkId(1L)
        val other = LinkId(2L)
        val original = mapOf(linkId to snapshot(linkId))
        val next = NetworkLinkReducer.reduce(original, NetworkLinkEvent.Removed(other))
        assertEquals(original, next)
    }

    @Test
    fun `link disappearing then reappearing with the same handle produces a fresh entry`() {
        val linkId = LinkId(1L)
        var state = emptyMap<LinkId, NetworkLinkSnapshot>()
        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Updated(snapshot(linkId)))
        assertTrue(state.containsKey(linkId))

        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Removed(linkId))
        assertTrue(state.isEmpty())

        // Reappearance (e.g. Wi-Fi reconnect) gets a brand-new networkHandle
        // in real Android, but even if it happened to reuse the same
        // handle, the reducer must treat it as a normal update.
        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Updated(snapshot(linkId)))
        assertTrue(state.containsKey(linkId))
        assertEquals(1, state.size)
    }

    @Test
    fun `two independent links can coexist and be removed independently`() {
        val wifi = LinkId(1L)
        val cellular = LinkId(2L)
        var state = emptyMap<LinkId, NetworkLinkSnapshot>()
        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Updated(snapshot(wifi, TransportKind.WIFI)))
        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Updated(snapshot(cellular, TransportKind.CELLULAR)))
        assertEquals(2, state.size)

        state = NetworkLinkReducer.reduce(state, NetworkLinkEvent.Removed(wifi))
        assertEquals(1, state.size)
        assertTrue(state.containsKey(cellular))
    }
}
