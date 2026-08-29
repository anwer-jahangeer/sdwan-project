package com.windowssdwan.multilink.model

/**
 * Aggregated probe statistics for one link over a rolling sample window.
 *
 * Every metric is `null` (Unknown) until enough samples exist to compute it
 * meaningfully - this class never substitutes a fabricated zero/default for
 * "not enough data yet".
 */
data class LinkHealth(
    val sampleCount: Int,
    val successCount: Int,

    /** `1 - successCount/sampleCount`. Null when [sampleCount] is 0. */
    val lossFraction: Double?,

    /** Mean of [ProbeSample.connectMillis] across *successful* samples in the window. Null if none. */
    val avgConnectMillis: Double?,

    /** Mean of [ProbeSample.totalMillis] across *successful* samples in the window. Null if none. */
    val avgTotalMillis: Double?,

    /**
     * Mean absolute difference between consecutive successful [ProbeSample.totalMillis]
     * values in the window - a simple, robust jitter estimate. Null when fewer
     * than 2 successful samples are available.
     */
    val jitterMillis: Double?,

    val lastSampleAtMs: Long?
) {
    companion object {
        /** The state before any probe has ever completed for a link. */
        val UNKNOWN = LinkHealth(
            sampleCount = 0,
            successCount = 0,
            lossFraction = null,
            avgConnectMillis = null,
            avgTotalMillis = null,
            jitterMillis = null,
            lastSampleAtMs = null
        )
    }
}
