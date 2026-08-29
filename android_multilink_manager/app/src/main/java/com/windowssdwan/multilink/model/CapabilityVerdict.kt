package com.windowssdwan.multilink.model

/**
 * The capability inspector's verdict about what this app can and cannot do
 * on this device, in this non-root configuration. See
 * `com.windowssdwan.multilink.policy.CapabilityVerdictPolicy` for how this
 * is built, and the project README for the full supported/unsupported
 * matrix.
 *
 * The four `...Supported` booleans below are fixed architectural facts
 * about this app as built (not runtime-detected), included here as
 * booleans so the UI/tests can assert on them directly instead of parsing
 * [explanationLines].
 */
data class CapabilityVerdict(
    /** Expected `false` for any normal, non-privileged, non-rooted install. */
    val hasPrivilegedTetherPermission: Boolean,

    val wifiAvailableAndValidated: Boolean,
    val cellularAvailableAndValidated: Boolean,
    val bothConcurrentlyAvailable: Boolean,
    val hotspotState: HotspotState,

    /** This app CAN choose which of its own connections use Wi-Fi vs cellular. */
    val perFlowSelectionSupported: Boolean,

    /** This app CANNOT steer other apps' traffic without a VpnService userspace forwarder. */
    val phoneWideSteeringSupported: Boolean,

    /** This app CANNOT steer tethered hotspot clients' traffic; that's privileged/root territory. */
    val hotspotClientSteeringSupported: Boolean,

    /** This app CANNOT bond Wi-Fi+cellular bandwidth for one flow without a remote aggregation server. */
    val trueBondingSupportedOnDevice: Boolean,

    /** Human-readable explanation lines, in display order, for the Capability card. */
    val explanationLines: List<String>
)
