package com.windowssdwan.multilink.monitoring

import android.net.Network
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.model.ProbeSample
import com.windowssdwan.multilink.networking.BoundConnectionFactory
import com.windowssdwan.multilink.util.readUpToCompat
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Runs an independent, repeating HTTPS health probe loop against one
 * specific [Network], reporting each [ProbeSample] as it completes.
 *
 * Every request is opened via [BoundConnectionFactory], which binds it to
 * this exact network (see that class's docs) - so a Wi-Fi probe genuinely
 * measures the Wi-Fi path and a cellular probe genuinely measures the
 * cellular path, even if the OS's own default network is something else.
 *
 * Uses `GET` with a `Range: bytes=0-0` request (most CDNs/edge servers
 * honor it; a few ignore it and return the full small body, which is still
 * fine for a 204/redirect-style connectivity-check endpoint) instead of
 * `HEAD`, since some servers/load balancers handle `HEAD` inconsistently.
 * Reads at most a few dozen bytes of body and closes the connection
 * immediately - this is a connectivity/latency probe, not a download.
 */
class HealthProbe(private val connectionFactory: BoundConnectionFactory) {

    private companion object {
        const val MAX_BODY_BYTES = 256
    }

    /**
     * Runs until the calling coroutine is cancelled. Never throws for
     * ordinary probe failures (timeouts, DNS failures, HTTP errors) - those
     * are reported as a failed [ProbeSample] instead, so the loop keeps
     * running across transient failures.
     */
    suspend fun runLoop(
        network: Network,
        config: ProbeConfig,
        onSample: suspend (ProbeSample) -> Unit
    ) {
        var index = 0
        while (currentCoroutineContext().isActive) {
            val endpoint = config.endpoints[index % config.endpoints.size]
            index++
            onSample(probeOnce(network, endpoint, config))
            delay(config.intervalMs)
        }
    }

    private suspend fun probeOnce(network: Network, endpointUrl: String, config: ProbeConfig): ProbeSample =
        withContext(Dispatchers.IO) {
            val startNanos = System.nanoTime()
            var connection: HttpURLConnection? = null
            try {
                connection = connectionFactory.openHttpsConnection(network, URL(endpointUrl)).apply {
                    connectTimeout = config.timeoutMs.toInt()
                    readTimeout = config.timeoutMs.toInt()
                    requestMethod = "GET"
                    setRequestProperty("Range", "bytes=0-${MAX_BODY_BYTES - 1}")
                    setRequestProperty("Connection", "close")
                }

                val status = connection.responseCode
                val connectMillis = elapsedMillisSince(startNanos)

                // A valid 204/205 response intentionally has no body. Some
                // HttpURLConnection implementations throw when inputStream
                // is requested for such responses, so body consumption is
                // optional and must never downgrade an already-observed
                // successful status into a failed probe.
                if (status !in setOf(204, 205, 304)) {
                    try {
                        val stream = if (status in 200..299) {
                            connection.inputStream
                        } else {
                            connection.errorStream
                        }
                        stream?.use { it.readUpToCompat(MAX_BODY_BYTES) }
                    } catch (e: CancellationException) {
                        throw e
                    } catch (_: IOException) {
                        // Response status and timing remain valid. The body
                        // is not part of the health decision.
                    }
                }

                val totalMillis = elapsedMillisSince(startNanos)
                val ok = status in 200..299

                ProbeSample(
                    timestampMs = System.currentTimeMillis(),
                    endpointUrl = endpointUrl,
                    success = ok,
                    httpStatus = status,
                    connectMillis = connectMillis,
                    totalMillis = totalMillis,
                    errorMessage = if (ok) null else "HTTP $status"
                )
            } catch (e: CancellationException) {
                throw e // never swallow cancellation - let the probe loop stop cleanly.
            } catch (e: Exception) {
                ProbeSample(
                    timestampMs = System.currentTimeMillis(),
                    endpointUrl = endpointUrl,
                    success = false,
                    httpStatus = null,
                    connectMillis = null,
                    totalMillis = null,
                    errorMessage = "${e::class.simpleName}: ${e.message ?: "no message"}"
                )
            } finally {
                connection?.disconnect()
            }
        }

    private fun elapsedMillisSince(startNanos: Long): Long = (System.nanoTime() - startNanos) / 1_000_000
}
