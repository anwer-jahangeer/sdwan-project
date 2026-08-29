package com.windowssdwan.multilink.scoring

import com.windowssdwan.multilink.model.ProbeSample

/**
 * Maintains a rolling window of [ProbeSample]s for one link and reduces them
 * into a [com.windowssdwan.multilink.model.LinkHealth] snapshot.
 *
 * Pure Kotlin, no Android dependency - safe to unit test on the plain JVM.
 * Not thread-safe by itself; callers (e.g. the monitoring coordinator) must
 * confine calls to a single coroutine/dispatcher per instance, which is how
 * this app uses it (one aggregator per link, fed only by that link's own
 * probe loop).
 */
class JitterLossAggregator(private val windowSize: Int) {

    init {
        require(windowSize >= 1) { "windowSize must be >= 1, was $windowSize" }
    }

    private val window = ArrayDeque<ProbeSample>()

    /** Adds a new sample (evicting the oldest if the window is full) and returns the updated aggregate. */
    fun addSample(sample: ProbeSample): com.windowssdwan.multilink.model.LinkHealth {
        window.addLast(sample)
        while (window.size > windowSize) {
            window.removeFirst()
        }
        return currentHealth()
    }

    /** Recomputes the aggregate from the current window without adding a sample. */
    fun currentHealth(): com.windowssdwan.multilink.model.LinkHealth {
        val samples = window
        if (samples.isEmpty()) {
            return com.windowssdwan.multilink.model.LinkHealth.UNKNOWN
        }

        val successCount = samples.count { it.success }
        val lossFraction = 1.0 - (successCount.toDouble() / samples.size.toDouble())

        val successfulTotals = samples.filter { it.success }.mapNotNull { it.totalMillis }
        val successfulConnects = samples.filter { it.success }.mapNotNull { it.connectMillis }

        val avgTotal = successfulTotals.averageOrNull()
        val avgConnect = successfulConnects.averageOrNull()

        // Jitter: mean absolute difference between consecutive successful
        // round-trip-ish (total) timings, in arrival order. Requires >= 2
        // successful samples; otherwise there is nothing to diff, so null.
        val jitter = if (successfulTotals.size >= 2) {
            val diffs = successfulTotals.zipWithNext { a, b -> kotlin.math.abs(b - a).toDouble() }
            diffs.average()
        } else {
            null
        }

        return com.windowssdwan.multilink.model.LinkHealth(
            sampleCount = samples.size,
            successCount = successCount,
            lossFraction = lossFraction,
            avgConnectMillis = avgConnect,
            avgTotalMillis = avgTotal,
            jitterMillis = jitter,
            lastSampleAtMs = samples.last().timestampMs
        )
    }

    /** Clears all buffered samples, e.g. when a link disappears and later reappears as a "fresh" network. */
    fun reset() {
        window.clear()
    }

    private fun List<Long>.averageOrNull(): Double? = if (isEmpty()) null else average()
}
