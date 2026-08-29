package com.windowssdwan.multilink.monitoring

import android.net.TrafficStats
import com.windowssdwan.multilink.model.TrafficSnapshot

/**
 * Reads public, aggregate traffic counters via `android.net.TrafficStats`.
 *
 * Deliberately does not attempt to attribute bytes to "Wi-Fi" vs
 * "cellular" - there is no public, reliable Android API for that
 * distinction on a normal app. See [TrafficSnapshot]'s docs.
 */
class TrafficStatsReader(private val appUid: Int) {

    fun snapshot(nowMs: Long = System.currentTimeMillis()): TrafficSnapshot = TrafficSnapshot(
        appUidRxBytes = supportedOrNull(TrafficStats.getUidRxBytes(appUid)),
        appUidTxBytes = supportedOrNull(TrafficStats.getUidTxBytes(appUid)),
        deviceMobileRxBytes = supportedOrNull(TrafficStats.getMobileRxBytes()),
        deviceMobileTxBytes = supportedOrNull(TrafficStats.getMobileTxBytes()),
        deviceTotalRxBytes = supportedOrNull(TrafficStats.getTotalRxBytes()),
        deviceTotalTxBytes = supportedOrNull(TrafficStats.getTotalTxBytes()),
        capturedAtMs = nowMs
    )

    /** `TrafficStats.UNSUPPORTED` (-1) means "this device/kernel does not support this counter" - never a real 0-or-more byte count. */
    private fun supportedOrNull(value: Long): Long? =
        if (value == TrafficStats.UNSUPPORTED.toLong()) null else value
}
