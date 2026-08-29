package com.windowssdwan.multilink.networking

import android.net.LinkProperties
import android.net.NetworkCapabilities
import android.os.Build
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.TransportKind

/**
 * Maps Android's `NetworkCapabilities`/`LinkProperties` into this app's own
 * Android-free [NetworkLinkSnapshot] model. Kept as a small, isolated
 * translation layer so every other layer of the app (scoring, policy, UI)
 * never touches `android.net.*` types directly.
 */
internal object SnapshotBuilder {

    /** `NetworkCapabilities.getSignalStrength()` returns this when no value is available. */
    private const val SIGNAL_STRENGTH_UNSPECIFIED = Int.MIN_VALUE

    /** `NetworkCapabilities.getLinkXBandwidthKbps()` returns this when no value is available. */
    private const val LINK_BANDWIDTH_UNSPECIFIED = 0

    fun build(
        linkId: LinkId,
        capabilities: NetworkCapabilities?,
        linkProperties: LinkProperties?,
        nowMs: Long
    ): NetworkLinkSnapshot {
        val transport = transportOf(capabilities)

        val downstream = capabilities?.linkDownstreamBandwidthKbps
            ?.takeIf { it != LINK_BANDWIDTH_UNSPECIFIED }
        val upstream = capabilities?.linkUpstreamBandwidthKbps
            ?.takeIf { it != LINK_BANDWIDTH_UNSPECIFIED }

        val signal = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            capabilities?.signalStrength?.takeIf { it != SIGNAL_STRENGTH_UNSPECIFIED }
        } else {
            null
        }

        val routes = linkProperties?.routes.orEmpty()
        val hasDefaultRoute = routes.any { it.isDefaultRoute }
        val routeSummaries = routes.map { route ->
            val dest = route.destination?.toString() ?: "0.0.0.0/0"
            val via = route.gateway?.hostAddress
            val iface = route.`interface`
            buildString {
                append(dest)
                if (via != null) append(" via $via")
                if (iface != null) append(" dev $iface")
                if (route.isDefaultRoute) append(" (default)")
            }
        }

        return NetworkLinkSnapshot(
            linkId = linkId,
            transport = transport,
            validated = capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) ?: false,
            hasInternetCapability = capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ?: false,
            metered = capabilities?.let { !it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) } ?: false,
            roaming = capabilities?.let { !it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_ROAMING) } ?: false,
            downstreamKbpsEstimate = downstream,
            upstreamKbpsEstimate = upstream,
            signalStrengthOrUnknown = signal,
            interfaceName = linkProperties?.interfaceName,
            ipAddresses = linkProperties?.linkAddresses.orEmpty().map { it.toString() },
            dnsServers = linkProperties?.dnsServers.orEmpty().mapNotNull { it.hostAddress },
            hasDefaultRoute = hasDefaultRoute,
            routeSummaries = routeSummaries,
            lastUpdatedAtMs = nowMs
        )
    }

    private fun transportOf(capabilities: NetworkCapabilities?): TransportKind {
        capabilities ?: return TransportKind.UNKNOWN
        return when {
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> TransportKind.WIFI
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> TransportKind.CELLULAR
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> TransportKind.ETHERNET
            else -> TransportKind.OTHER
        }
    }
}
