package com.windowssdwan.multilink.scoring

import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.ProbeSample
import com.windowssdwan.multilink.model.TransportKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Focused tests that "unknown" (not enough data yet) is always kept
 * distinct from "known and bad" throughout the aggregation -> scoring
 * pipeline, per this app's unknown-handling rules.
 */
class UnknownMetricsHandlingTest {

    private fun wifiSnapshot(validated: Boolean = true) = NetworkLinkSnapshot(
        linkId = LinkId(1L),
        transport = TransportKind.WIFI,
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
    fun `all-failed samples yield a known loss fraction but unknown latency and jitter`() {
        val aggregator = JitterLossAggregator(windowSize = 5)
        aggregator.addSample(
            ProbeSample(0L, "https://example.invalid", success = false, httpStatus = null, connectMillis = null, totalMillis = null, errorMessage = "timeout")
        )
        val health = aggregator.addSample(
            ProbeSample(1L, "https://example.invalid", success = false, httpStatus = null, connectMillis = null, totalMillis = null, errorMessage = "timeout")
        )

        // Loss is knowable (100% of samples failed)...
        assertEquals(1.0, health.lossFraction!!, 0.0001)
        // ...but latency/jitter genuinely cannot be computed from zero successful samples.
        assertNull(health.avgTotalMillis)
        assertNull(health.avgConnectMillis)
        assertNull(health.jitterMillis)
    }

    @Test
    fun `scorer treats all-failed health as bad reliability but unknown latency and jitter, not zero`() {
        val health = LinkHealth(
            sampleCount = 5,
            successCount = 0,
            lossFraction = 1.0,
            avgConnectMillis = null,
            avgTotalMillis = null,
            jitterMillis = null,
            lastSampleAtMs = 5L
        )
        val score = LinkScorer.score(wifiSnapshot(validated = true), health)

        assertEquals(0, score.reliabilityComponent) // known: 30 * (1 - 1.0) = 0
        assertNull(score.latencyComponent) // unknown, not 0
        assertNull(score.jitterComponent) // unknown, not 0
        // total = 100 * (connectivity(40) + reliability(0)) / (40 + 30) = 100 * 40/70
        assertEquals(57, score.total) // round(100 * 40/70) = 57
        assertEquals(2, score.knownComponentCount)
    }

    @Test
    fun `brand-new unvalidated link with no probe data still only reports the one known component`() {
        val score = LinkScorer.score(wifiSnapshot(validated = false), LinkHealth.UNKNOWN)
        assertEquals(1, score.knownComponentCount)
        assertNull(score.reliabilityComponent)
        assertNull(score.latencyComponent)
        assertNull(score.jitterComponent)
    }
}
