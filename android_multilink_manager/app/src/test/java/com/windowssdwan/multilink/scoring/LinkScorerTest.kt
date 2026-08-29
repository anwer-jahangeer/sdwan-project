package com.windowssdwan.multilink.scoring

import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LinkScorerTest {

    private fun snapshot(
        validated: Boolean = true,
        hasInternet: Boolean = true,
        transport: TransportKind = TransportKind.WIFI
    ) = NetworkLinkSnapshot(
        linkId = LinkId(1L),
        transport = transport,
        validated = validated,
        hasInternetCapability = hasInternet,
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
    fun `validated link with no probe data yet scores purely on connectivity`() {
        val score = LinkScorer.score(snapshot(validated = true), LinkHealth.UNKNOWN)
        // Only the connectivity component (40/40) is known, so it is
        // rescaled to the full 0-100 range: 100 * 40/40 = 100.
        assertEquals(100, score.total)
        assertEquals(1, score.knownComponentCount)
        assertNull(score.reliabilityComponent)
        assertNull(score.latencyComponent)
        assertNull(score.jitterComponent)
    }

    @Test
    fun `unvalidated but internet-capable link scores lower than validated`() {
        val validatedScore = LinkScorer.score(snapshot(validated = true, hasInternet = true), LinkHealth.UNKNOWN)
        val unvalidatedScore = LinkScorer.score(snapshot(validated = false, hasInternet = true), LinkHealth.UNKNOWN)
        assertTrue(unvalidatedScore.total!! < validatedScore.total!!)
    }

    @Test
    fun `no internet and not validated scores zero`() {
        val score = LinkScorer.score(snapshot(validated = false, hasInternet = false), LinkHealth.UNKNOWN)
        assertEquals(0, score.total)
    }

    @Test
    fun `perfect reliability latency and jitter combine with validated connectivity for a full score`() {
        val health = LinkHealth(
            sampleCount = 20,
            successCount = 20,
            lossFraction = 0.0,
            avgConnectMillis = 40.0,
            avgTotalMillis = 50.0, // <= GOOD_LATENCY_MS
            jitterMillis = 0.0,
            lastSampleAtMs = 1000L
        )
        val score = LinkScorer.score(snapshot(validated = true), health)
        assertEquals(100, score.total)
        assertEquals(4, score.knownComponentCount)
        assertEquals(40, score.connectivityComponent)
        assertEquals(30, score.reliabilityComponent)
        assertEquals(20, score.latencyComponent)
        assertEquals(10, score.jitterComponent)
    }

    @Test
    fun `high loss reduces reliability component proportionally`() {
        val health = LinkHealth(
            sampleCount = 10,
            successCount = 5,
            lossFraction = 0.5,
            avgConnectMillis = 100.0,
            avgTotalMillis = 100.0,
            jitterMillis = 10.0,
            lastSampleAtMs = 1000L
        )
        val score = LinkScorer.score(snapshot(validated = true), health)
        assertEquals(15, score.reliabilityComponent) // 30 * (1 - 0.5)
    }

    @Test
    fun `latency at or above the bad threshold scores zero latency points`() {
        val health = LinkHealth(
            sampleCount = 5,
            successCount = 5,
            lossFraction = 0.0,
            avgConnectMillis = LinkScorer.BAD_LATENCY_MS,
            avgTotalMillis = LinkScorer.BAD_LATENCY_MS,
            jitterMillis = 0.0,
            lastSampleAtMs = 1000L
        )
        val score = LinkScorer.score(snapshot(validated = true), health)
        assertEquals(0, score.latencyComponent)
    }

    @Test
    fun `jitter at or above the bad threshold scores zero jitter points`() {
        val health = LinkHealth(
            sampleCount = 5,
            successCount = 5,
            lossFraction = 0.0,
            avgConnectMillis = 50.0,
            avgTotalMillis = 50.0,
            jitterMillis = LinkScorer.BAD_JITTER_MS * 2,
            lastSampleAtMs = 1000L
        )
        val score = LinkScorer.score(snapshot(validated = true), health)
        assertEquals(0, score.jitterComponent)
    }
}
