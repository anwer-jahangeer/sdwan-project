package com.windowssdwan.multilink.networking

import android.content.Context
import android.content.pm.PackageManager
import com.windowssdwan.multilink.model.CapabilityVerdict
import com.windowssdwan.multilink.model.HotspotState
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.TransportKind
import com.windowssdwan.multilink.policy.CapabilityVerdictPolicy

/**
 * Gathers the handful of Android-specific facts the capability verdict
 * needs (a `PackageManager` permission check, and which transports are
 * currently validated), then delegates the actual verdict text/booleans to
 * the pure [CapabilityVerdictPolicy].
 *
 * Uses `PackageManager.checkPermission` only - a read-only check of this
 * app's own already-granted/declared permissions. Never requests, elevates,
 * or works around a permission via reflection or hidden APIs.
 */
class CapabilityInspector(private val context: Context) {

    /** Read-only check: does this install hold `TETHER_PRIVILEGED`? This app never declares/requests it, so this should always be false. */
    fun hasPrivilegedTetherPermission(): Boolean =
        context.packageManager.checkPermission(
            "android.permission.TETHER_PRIVILEGED",
            context.packageName
        ) == PackageManager.PERMISSION_GRANTED

    /**
     * Always [HotspotState.UNKNOWN]: there is no public, non-privileged API
     * to read SoftAP/hotspot enablement state as of Android 16. This method
     * exists (rather than being omitted) so that fact is visible and
     * documented in one obvious place, instead of silently absent.
     */
    fun currentHotspotState(): HotspotState = HotspotState.UNKNOWN

    fun buildVerdict(links: Map<LinkId, NetworkLinkSnapshot>): CapabilityVerdict {
        val wifiOk = links.values.any { it.transport == TransportKind.WIFI && it.validated }
        val cellOk = links.values.any { it.transport == TransportKind.CELLULAR && it.validated }
        return CapabilityVerdictPolicy.buildVerdict(
            hasPrivilegedTetherPermission = hasPrivilegedTetherPermission(),
            wifiAvailableAndValidated = wifiOk,
            cellularAvailableAndValidated = cellOk,
            hotspotState = currentHotspotState()
        )
    }
}
