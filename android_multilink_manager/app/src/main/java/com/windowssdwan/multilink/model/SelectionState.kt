package com.windowssdwan.multilink.model

/**
 * The app-owned per-flow network selector's current decision: which link
 * *this app's own* new sockets/URL connections should prefer, and why.
 *
 * This has no effect on any other app, on the OS's own default network,
 * or on tethered hotspot clients - see [CapabilityVerdict] and the README
 * for why that is out of scope for a non-root app.
 */
data class SelectionState(
    val selectedLinkId: LinkId?,
    val selectedTransport: TransportKind?,
    val reason: String,
    val decidedAtMs: Long
) {
    companion object {
        fun none(atMs: Long, reason: String) = SelectionState(
            selectedLinkId = null,
            selectedTransport = null,
            reason = reason,
            decidedAtMs = atMs
        )
    }
}
