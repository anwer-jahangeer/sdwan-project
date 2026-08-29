package com.windowssdwan.multilink.model

/**
 * The result of one HTTP(S) probe request bound to a specific [android.net.Network].
 *
 * [connectMillis] / [totalMillis] are **HTTP-layer** timings (time to first
 * response byte / time to finish reading a minimal response body over a
 * TCP+TLS connection this app opened), not ICMP echo round-trip time. This
 * app deliberately never assumes ICMP (ping) is available or meaningful -
 * many carriers and captive portals block/deprioritize ICMP - so all
 * "latency" in this app is this HTTP request timing, and is labeled as such
 * everywhere it is displayed.
 */
data class ProbeSample(
    val timestampMs: Long,
    val endpointUrl: String,
    val success: Boolean,

    /** Null if the request failed before a status line was received. */
    val httpStatus: Int?,

    /** Elapsed ms from request start to receiving a response status/headers. Null if unknown. */
    val connectMillis: Long?,

    /** Elapsed ms from request start to fully reading the (minimal) response body. Null if unknown. */
    val totalMillis: Long?,

    /** Short human-readable failure reason, e.g. "SocketTimeoutException: connect timed out". Null on success. */
    val errorMessage: String?
)
