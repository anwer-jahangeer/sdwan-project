package com.windowssdwan.multilink.networking

import android.net.Network
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Opens HTTP(S) connections bound to a specific [android.net.Network] -
 * i.e. this app choosing, for its own request, which of its available
 * links (Wi-Fi vs cellular) to send it over.
 *
 * This is exactly what [android.net.Network.openConnection] is documented
 * for, and is the only per-flow steering mechanism available to a normal
 * app: it affects only sockets this app itself opens through this factory,
 * never any other app's traffic, the OS's own default-network choice, or
 * traffic from devices tethered to this phone's hotspot.
 *
 * For call sites that need a raw `Socket`/`SocketChannel` instead of
 * `HttpURLConnection` (not used by this app today, but documented for
 * future extension), [android.net.Network.getSocketFactory] is the
 * equivalent bind-to-this-network primitive.
 */
interface BoundConnectionFactory {
    @Throws(IOException::class)
    fun openHttpsConnection(network: Network, url: URL): HttpURLConnection
}

class AndroidBoundConnectionFactory(
    private val connectTimeoutMs: Int,
    private val readTimeoutMs: Int
) : BoundConnectionFactory {

    override fun openHttpsConnection(network: Network, url: URL): HttpURLConnection {
        // network.openConnection(url) is bound to this specific Network -
        // this is the documented, non-privileged way to steer one
        // connection without affecting the device's default network.
        val connection = network.openConnection(url) as? HttpURLConnection
            ?: throw IOException("URL is not http(s): $url")
        connection.connectTimeout = connectTimeoutMs
        connection.readTimeout = readTimeoutMs
        connection.instanceFollowRedirects = true
        return connection
    }
}
