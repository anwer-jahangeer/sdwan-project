package com.windowssdwan.multilink.policy

import com.windowssdwan.multilink.model.CapabilityVerdict
import com.windowssdwan.multilink.model.HotspotState

/**
 * Builds the [CapabilityVerdict] shown on the Capability card, from a small
 * set of booleans/enum gathered elsewhere (by
 * `com.windowssdwan.multilink.networking.CapabilityInspector`, which talks
 * to `PackageManager`/`ConnectivityManager`).
 *
 * Pure Kotlin - no Android dependency - so the verdict text and the fixed
 * architectural facts below are unit-testable without a device/emulator.
 */
object CapabilityVerdictPolicy {

    fun buildVerdict(
        hasPrivilegedTetherPermission: Boolean,
        wifiAvailableAndValidated: Boolean,
        cellularAvailableAndValidated: Boolean,
        hotspotState: HotspotState
    ): CapabilityVerdict {
        val bothConcurrent = wifiAvailableAndValidated && cellularAvailableAndValidated

        val lines = buildList {
            add(
                "App-owned per-flow selection: SUPPORTED. This app can bind its own " +
                    "sockets/HTTP(S) connections to a specific Wi-Fi or cellular " +
                    "android.net.Network, and pick between them per request."
            )
            add(
                "Phone-wide traffic steering (making OTHER apps use a chosen link): " +
                    "NOT SUPPORTED by this app as built. That requires a local VpnService " +
                    "acting as a userspace packet forwarder, a fundamentally different " +
                    "(and more invasive) app design - see the README's future-architecture section."
            )
            add(
                "Hotspot-client steering (choosing which link devices tethered to THIS " +
                    "phone use): NOT SUPPORTED, non-root. Tethered clients' traffic is " +
                    "handled by the kernel/tethering stack, which is invisible to a normal " +
                    "app's VpnService or socket APIs, and tethering policy/NAT control " +
                    "requires privileged/system permissions this app does not and will not request."
            )
            add(
                "True multi-link bonding (combining Wi-Fi + cellular bandwidth for a " +
                    "single flow): NOT SUPPORTED on-device alone. That requires a remote " +
                    "aggregation server the device connects to over every link " +
                    "simultaneously - see the README's future-architecture section."
            )
            add(
                if (hasPrivilegedTetherPermission) {
                    "Unexpected: this install holds a privileged tethering permission. " +
                        "That should never happen for a normal, non-rooted, sideloaded/Play " +
                        "install; this app never declares or requests it."
                } else {
                    "Privileged tethering permission check: NOT held (expected for any " +
                        "normal, non-rooted install)."
                }
            )
            add(
                "Hotspot/SoftAP state: " + when (hotspotState) {
                    HotspotState.ENABLED -> "Enabled."
                    HotspotState.DISABLED -> "Disabled."
                    HotspotState.UNKNOWN -> "Unknown - Android has no public API for a normal " +
                        "app to read this reliably. Use the button below to open hotspot " +
                        "settings and check/enable it yourself."
                }
            )
        }

        return CapabilityVerdict(
            hasPrivilegedTetherPermission = hasPrivilegedTetherPermission,
            wifiAvailableAndValidated = wifiAvailableAndValidated,
            cellularAvailableAndValidated = cellularAvailableAndValidated,
            bothConcurrentlyAvailable = bothConcurrent,
            hotspotState = hotspotState,
            perFlowSelectionSupported = true,
            phoneWideSteeringSupported = false,
            hotspotClientSteeringSupported = false,
            trueBondingSupportedOnDevice = false,
            explanationLines = lines
        )
    }
}
