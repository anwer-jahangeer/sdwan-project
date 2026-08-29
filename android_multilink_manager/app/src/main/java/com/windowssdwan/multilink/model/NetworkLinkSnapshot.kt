package com.windowssdwan.multilink.model

/**
 * A point-in-time view of one [android.net.Network]'s capabilities and link
 * properties, as visible to a normal (non-privileged) app.
 *
 * Every nullable field here means "not currently known" rather than a
 * fabricated default - callers (scoring, UI) must treat `null` as Unknown,
 * never as zero/false/absent.
 *
 * Fields that look like throughput are **not** observed traffic; see the
 * [downstreamKbpsEstimate] / [upstreamKbpsEstimate] docs below.
 */
data class NetworkLinkSnapshot(
    val linkId: LinkId,
    val transport: TransportKind,

    /** `NetworkCapabilities.NET_CAPABILITY_VALIDATED`: platform confirmed real internet access. */
    val validated: Boolean,

    /** `NetworkCapabilities.NET_CAPABILITY_INTERNET`: network *declares* it can reach the internet. */
    val hasInternetCapability: Boolean,

    /** `!NET_CAPABILITY_NOT_METERED`. */
    val metered: Boolean,

    /** `!NET_CAPABILITY_NOT_ROAMING`. */
    val roaming: Boolean,

    /**
     * `NetworkCapabilities.getLinkDownstreamBandwidthKbps()`.
     *
     * This is the platform/driver's *negotiated or estimated capability*
     * (e.g. PHY link speed class), NOT measured throughput of any traffic
     * this app has sent. `null` means the platform did not report a value
     * (`LINK_BANDWIDTH_UNSPECIFIED`).
     */
    val downstreamKbpsEstimate: Int?,

    /** Same caveat as [downstreamKbpsEstimate], for the upstream direction. */
    val upstreamKbpsEstimate: Int?,

    /**
     * `NetworkCapabilities.getSignalStrength()`, API 29+ only.
     *
     * In practice this reliably reports a value only for requests that
     * included `NET_CAPABILITY_SIGNAL_STRENGTH` *and* when the caller holds
     * location permission; since this app does not request location
     * permission, this will usually be `null` (Unknown) here. Kept as a
     * field - and surfaced as Unknown - rather than removed, so the UI/README
     * can honestly explain why it is usually blank instead of silently
     * omitting it.
     */
    val signalStrengthOrUnknown: Int?,

    /** `LinkProperties.getInterfaceName()`, e.g. "wlan0", "rmnet_data0". */
    val interfaceName: String?,

    /** Textual IP addresses (`LinkProperties.getLinkAddresses()`), e.g. "192.168.1.23/24". */
    val ipAddresses: List<String>,

    /** Textual DNS server addresses (`LinkProperties.getDnsServers()`). */
    val dnsServers: List<String>,

    /** True if any `RouteInfo` on this link is a default route (`RouteInfo.isDefaultRoute()`). */
    val hasDefaultRoute: Boolean,

    /** Human-readable one-line summaries of `LinkProperties.getRoutes()`, for the UI/logs. */
    val routeSummaries: List<String>,

    /** Wall-clock time this snapshot was last refreshed (capabilities or link properties changed). */
    val lastUpdatedAtMs: Long
) {
    /** Convenience: eligible to be probed/selected at all (has internet capability and is validated). */
    val isUsable: Boolean get() = hasInternetCapability && validated
}
