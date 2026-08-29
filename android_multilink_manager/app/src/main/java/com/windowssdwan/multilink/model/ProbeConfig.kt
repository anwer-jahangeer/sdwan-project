package com.windowssdwan.multilink.model

/**
 * User/UI-configurable settings for the per-link health prober.
 */
data class ProbeConfig(
    /** HTTPS endpoints probed in round-robin order. Must be non-empty; enforced by [sanitized]. */
    val endpoints: List<String>,
    val intervalMs: Long,
    val timeoutMs: Long,
    /** Rolling window size (in samples) used for loss/jitter aggregation. */
    val windowSize: Int
) {
    companion object {
        val DEFAULT = ProbeConfig(
            endpoints = listOf(
                "https://www.gstatic.com/generate_204",
                "https://connectivitycheck.gstatic.com/generate_204"
            ),
            intervalMs = 5_000L,
            timeoutMs = 4_000L,
            windowSize = 20
        )

        const val MIN_INTERVAL_MS = 1_000L
        const val MIN_TIMEOUT_MS = 500L
        const val MIN_WINDOW_SIZE = 3
    }

    /** Clamps to sane bounds and falls back to defaults for an empty endpoint list. */
    fun sanitized(): ProbeConfig = copy(
        endpoints = endpoints.filter { it.isNotBlank() }.ifEmpty { DEFAULT.endpoints },
        intervalMs = intervalMs.coerceAtLeast(MIN_INTERVAL_MS),
        timeoutMs = timeoutMs.coerceAtLeast(MIN_TIMEOUT_MS),
        windowSize = windowSize.coerceAtLeast(MIN_WINDOW_SIZE)
    )
}
