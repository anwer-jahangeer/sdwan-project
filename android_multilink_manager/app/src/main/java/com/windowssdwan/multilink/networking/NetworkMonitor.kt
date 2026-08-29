package com.windowssdwan.multilink.networking

import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.util.Logger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.util.concurrent.ConcurrentHashMap

/**
 * Registers [ConnectivityManager.NetworkCallback]s for Wi-Fi and cellular
 * networks that declare internet capability, and keeps a live map of every
 * matching [Network] (keyed by [LinkId], i.e. `Network.getNetworkHandle()`)
 * translated into this app's own [NetworkLinkSnapshot] model.
 *
 * Only tracks networks this app is allowed to see as a normal app - it does
 * NOT request `NET_CAPABILITY_NOT_VPN`-excluded/system-only visibility, and
 * it never registers a default-network callback that would affect what the
 * OS considers the "current" network for other apps.
 */
class NetworkMonitor(private val connectivityManager: ConnectivityManager) {

    private companion object {
        const val TAG = "NetworkMonitor"
    }

    private val _links = MutableStateFlow<Map<LinkId, NetworkLinkSnapshot>>(emptyMap())
    val links: StateFlow<Map<LinkId, NetworkLinkSnapshot>> = _links.asStateFlow()

    /** The real [Network] object for a tracked link, needed to bind sockets/connections to it. */
    private val networkByLinkId = ConcurrentHashMap<LinkId, Network>()

    /** Latest known capabilities/properties per network, so a partial update can be merged with what's already known. */
    private val pendingCaps = ConcurrentHashMap<LinkId, NetworkCapabilities>()
    private val pendingProps = ConcurrentHashMap<LinkId, LinkProperties>()

    private var started = false
    private val wifiCallback = buildCallback("wifi")
    private val cellularCallback = buildCallback("cellular")

    fun networkFor(linkId: LinkId): Network? = networkByLinkId[linkId]

    @Synchronized
    fun start() {
        if (started) return
        started = true

        val wifiRequest = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        val cellularRequest = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()

        // requestNetwork(), rather than a passive registerNetworkCallback(),
        // keeps each matching transport available for sockets owned by this
        // app. This is especially important for cellular while Wi-Fi is the
        // system default. It does not change the default network for other
        // apps or for tethered clients.
        connectivityManager.requestNetwork(wifiRequest, wifiCallback)
        connectivityManager.requestNetwork(cellularRequest, cellularCallback)
        Logger.i(TAG, "Requested Wi-Fi + cellular networks for app-owned flows.")
    }

    @Synchronized
    fun stop() {
        if (!started) return
        started = false
        runCatching { connectivityManager.unregisterNetworkCallback(wifiCallback) }
            .onFailure { Logger.w(TAG, "Failed to unregister wifi callback", it) }
        runCatching { connectivityManager.unregisterNetworkCallback(cellularCallback) }
            .onFailure { Logger.w(TAG, "Failed to unregister cellular callback", it) }
        networkByLinkId.clear()
        pendingCaps.clear()
        pendingProps.clear()
        _links.value = emptyMap()
        Logger.i(TAG, "Unregistered network callbacks and cleared state.")
    }

    private fun buildCallback(label: String): ConnectivityManager.NetworkCallback =
        object : ConnectivityManager.NetworkCallback() {

            override fun onAvailable(network: Network) {
                val linkId = LinkId(network.networkHandle)
                networkByLinkId[linkId] = network
                Logger.i(TAG, "[$label] onAvailable handle=${linkId.networkHandle}")
                refresh(linkId)
            }

            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                val linkId = LinkId(network.networkHandle)
                pendingCaps[linkId] = capabilities
                refresh(linkId)
            }

            override fun onLinkPropertiesChanged(network: Network, linkProperties: LinkProperties) {
                val linkId = LinkId(network.networkHandle)
                pendingProps[linkId] = linkProperties
                refresh(linkId)
            }

            override fun onLost(network: Network) {
                val linkId = LinkId(network.networkHandle)
                Logger.i(TAG, "[$label] onLost handle=${linkId.networkHandle}")
                networkByLinkId.remove(linkId)
                pendingCaps.remove(linkId)
                pendingProps.remove(linkId)
                _links.update { current ->
                    NetworkLinkReducer.reduce(current, NetworkLinkEvent.Removed(linkId))
                }
            }

            override fun onUnavailable() {
                Logger.w(TAG, "[$label] onUnavailable: no matching network is currently reachable.")
            }
        }

    private fun refresh(linkId: LinkId) {
        val snapshot = SnapshotBuilder.build(
            linkId = linkId,
            capabilities = pendingCaps[linkId],
            linkProperties = pendingProps[linkId],
            nowMs = System.currentTimeMillis()
        )
        _links.update { current ->
            NetworkLinkReducer.reduce(current, NetworkLinkEvent.Updated(snapshot))
        }
    }
}
