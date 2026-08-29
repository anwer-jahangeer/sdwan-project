package com.windowssdwan.multilink.model

/**
 * Coarse classification of the underlying transport carrying a [NetworkLinkSnapshot].
 *
 * Deliberately small and derived only from [android.net.NetworkCapabilities.hasTransport]
 * bits that are visible to a normal (non-privileged) app.
 */
enum class TransportKind {
    WIFI,
    CELLULAR,
    ETHERNET,
    OTHER,

    /** Capabilities were not yet observed for this network, or matched no known transport. */
    UNKNOWN
}
