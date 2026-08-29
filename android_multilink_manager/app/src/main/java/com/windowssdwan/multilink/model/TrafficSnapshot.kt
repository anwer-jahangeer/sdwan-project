package com.windowssdwan.multilink.model

/**
 * A snapshot of coarse traffic byte counters from public `android.net.TrafficStats`
 * APIs only.
 *
 * IMPORTANT ACCURACY NOTE: Android has no public, reliable API for a normal
 * app to attribute observed bytes to "Wi-Fi" vs "cellular" specifically.
 * `TrafficStats` can report this app's own UID totals and a device-wide
 * *mobile* total, but there is no equivalent public "Wi-Fi total" counter -
 * so this app never fabricates one. Any field here is `null` when the
 * device/kernel reports `TrafficStats.UNSUPPORTED`, which must be shown as
 * "Unsupported on this device", never as zero bytes.
 */
data class TrafficSnapshot(
    /** This app's own process, all networks combined (`TrafficStats.getUidRxBytes/TxBytes`). */
    val appUidRxBytes: Long?,
    val appUidTxBytes: Long?,

    /** Device-wide, mobile-network-attributed only (`TrafficStats.getMobileRxBytes/TxBytes`). */
    val deviceMobileRxBytes: Long?,
    val deviceMobileTxBytes: Long?,

    /** Device-wide, every network combined - not split by transport (`TrafficStats.getTotalRxBytes/TxBytes`). */
    val deviceTotalRxBytes: Long?,
    val deviceTotalTxBytes: Long?,

    val capturedAtMs: Long
) {
    companion object {
        val EMPTY = TrafficSnapshot(null, null, null, null, null, null, 0L)
    }
}
