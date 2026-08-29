package com.windowssdwan.multilink.scoring

import com.windowssdwan.multilink.model.ProbeSample
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JitterLossAggregatorTest {

    private fun sample(
        success: Boolean,
        totalMillis: Long? = null,
        connectMillis: Long? = null,
        timestamp: Long = 0L
    ) = ProbeSample(
        timestampMs = timestamp,
        endpointUrl = "https://example.invalid/probe",
        success = success,
        httpStatus = if (success) 204 else null,
        connectMillis = connectMillis,
        totalMillis = totalMillis,
        errorMessage = if (success) null else "boom"
    )

    @Test
    fun `empty window reports fully unknown health`() {
        val aggregator = JitterLossAggregator(windowSize = 5)
        val health = aggregator.currentHealth()
        assertEquals(0, health.sampleCount)
        assertNull(health.lossFraction)
        assertNull(health.avgTotalMillis)
        assertNull(health.jitterMillis)
    }

    @Test
    fun `single sample has no jitter but has a loss fraction`() {
        val aggregator = JitterLossAggregator(windowSize = 5)
        val health = aggregator.addSample(sample(success = true, totalMillis = 100L, connectMillis = 80L))
        assertEquals(1, health.sampleCount)
        assertEquals(0.0, health.lossFraction!!, 0.0001)
        assertEquals(100.0, health.avgTotalMillis!!, 0.0001)
        assertNull(health.jitterMillis) // needs >= 2 successful samples
    }

    @Test
    fun `loss fraction reflects failures within the window`() {
        val aggregator = JitterLossAggregator(windowSize = 10)
        var health = aggregator.addSample(sample(success = true, totalMillis = 100L))
        health = aggregator.addSample(sample(success = false))
        health = aggregator.addSample(sample(success = false))
        health = aggregator.addSample(sample(success = true, totalMillis = 100L))
        assertEquals(4, health.sampleCount)
        assertEquals(0.5, health.lossFraction!!, 0.0001)
    }

    @Test
    fun `jitter is the mean absolute difference between consecutive successful totals`() {
        val aggregator = JitterLossAggregator(windowSize = 10)
        aggregator.addSample(sample(success = true, totalMillis = 100L))
        aggregator.addSample(sample(success = true, totalMillis = 120L)) // diff 20
        val health = aggregator.addSample(sample(success = true, totalMillis = 90L)) // diff 30
        assertEquals(25.0, health.jitterMillis!!, 0.0001) // (20+30)/2
    }

    @Test
    fun `window evicts oldest sample once full`() {
        val aggregator = JitterLossAggregator(windowSize = 2)
        aggregator.addSample(sample(success = false, timestamp = 1L))
        val health = aggregator.addSample(sample(success = true, totalMillis = 50L, timestamp = 2L))
        val health2 = aggregator.addSample(sample(success = true, totalMillis = 50L, timestamp = 3L))
        assertEquals(2, health2.sampleCount)
        // Oldest (failed) sample was evicted, so loss should now be 0.
        assertEquals(0.0, health2.lossFraction!!, 0.0001)
        assertTrue(health.sampleCount <= 2)
    }

    @Test
    fun `reset clears the window back to unknown`() {
        val aggregator = JitterLossAggregator(windowSize = 5)
        aggregator.addSample(sample(success = true, totalMillis = 50L))
        aggregator.reset()
        val health = aggregator.currentHealth()
        assertEquals(0, health.sampleCount)
        assertNull(health.lossFraction)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `zero window size is rejected`() {
        JitterLossAggregator(windowSize = 0)
    }
}
