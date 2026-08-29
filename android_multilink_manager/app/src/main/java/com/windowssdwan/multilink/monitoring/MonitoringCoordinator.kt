package com.windowssdwan.multilink.monitoring

import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.LinkScore
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.model.TrafficSnapshot
import com.windowssdwan.multilink.model.CapabilityVerdict
import com.windowssdwan.multilink.networking.BoundConnectionFactory
import com.windowssdwan.multilink.networking.CapabilityInspector
import com.windowssdwan.multilink.networking.HysteresisNetworkSelector
import com.windowssdwan.multilink.networking.NetworkMonitor
import com.windowssdwan.multilink.networking.NetworkSelector
import com.windowssdwan.multilink.scoring.JitterLossAggregator
import com.windowssdwan.multilink.scoring.LinkScorer
import com.windowssdwan.multilink.util.Logger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap

/**
 * Ties together [NetworkMonitor] (which links exist), [HealthProbe] (are
 * they healthy), [JitterLossAggregator] + [LinkScorer] (how healthy,
 * scored), [HysteresisNetworkSelector] (which one this app's own traffic
 * should prefer), [TrafficStatsReader] (coarse byte counters), and
 * [CapabilityInspector] (what this app can/cannot do) into the single
 * object the ViewModel observes.
 *
 * Owns starting/stopping one probe coroutine per currently-known link, and
 * cleans up state for links that disappear (so a stale score/health entry
 * never lingers for a network that no longer exists).
 */
class MonitoringCoordinator(
    private val networkMonitor: NetworkMonitor,
    connectionFactory: BoundConnectionFactory,
    private val trafficStatsReader: TrafficStatsReader,
    private val capabilityInspector: CapabilityInspector,
    private val scope: CoroutineScope
) {
    private companion object {
        const val TAG = "MonitoringCoordinator"
        const val TRAFFIC_POLL_INTERVAL_MS = 3_000L
    }

    private val healthProbe = HealthProbe(connectionFactory)
    private val aggregators = ConcurrentHashMap<LinkId, JitterLossAggregator>()
    private val probeJobs = ConcurrentHashMap<LinkId, Job>()

    val links: StateFlow<Map<LinkId, NetworkLinkSnapshot>> get() = networkMonitor.links

    private val _health = MutableStateFlow<Map<LinkId, LinkHealth>>(emptyMap())
    val health: StateFlow<Map<LinkId, LinkHealth>> = _health.asStateFlow()

    private val _scores = MutableStateFlow<Map<LinkId, LinkScore>>(emptyMap())
    val scores: StateFlow<Map<LinkId, LinkScore>> = _scores.asStateFlow()

    private val _traffic = MutableStateFlow(TrafficSnapshot.EMPTY)
    val traffic: StateFlow<TrafficSnapshot> = _traffic.asStateFlow()

    private val _capabilityVerdict = MutableStateFlow<CapabilityVerdict?>(null)
    val capabilityVerdict: StateFlow<CapabilityVerdict?> = _capabilityVerdict.asStateFlow()

    private val _probeConfig = MutableStateFlow(ProbeConfig.DEFAULT)
    val probeConfig: StateFlow<ProbeConfig> = _probeConfig.asStateFlow()

    val selector: NetworkSelector = HysteresisNetworkSelector(networkMonitor, scores, scope)

    private var reconcileJob: Job? = null
    private var scoringJob: Job? = null
    private var trafficJob: Job? = null
    private var capabilityJob: Job? = null
    private var running = false
    private var lastAppliedConfig: ProbeConfig? = null

    fun updateProbeConfig(config: ProbeConfig) {
        _probeConfig.value = config.sanitized()
    }

    @Synchronized
    fun start() {
        if (running) return
        running = true
        Logger.i(TAG, "Starting monitoring.")
        networkMonitor.start()
        selector.start()

        reconcileJob = scope.launch {
            combine(networkMonitor.links, _probeConfig) { linkMap, config -> linkMap.keys to config }
                .collect { (linkIds, config) -> reconcileProbes(linkIds, config) }
        }

        // Re-score whenever either the link capabilities or the probe
        // health for any link changes, so e.g. a validation-state flip is
        // reflected even between probe samples.
        scoringJob = scope.launch {
            combine(networkMonitor.links, _health) { linkMap, healthMap -> linkMap to healthMap }
                .collect { (linkMap, healthMap) ->
                    _scores.value = linkMap.mapValues { (linkId, snapshot) ->
                        LinkScorer.score(snapshot, healthMap[linkId] ?: LinkHealth.UNKNOWN)
                    }
                }
        }

        trafficJob = scope.launch {
            while (isActive) {
                _traffic.value = trafficStatsReader.snapshot()
                delay(TRAFFIC_POLL_INTERVAL_MS)
            }
        }

        capabilityJob = scope.launch {
            networkMonitor.links.collect { linkMap ->
                _capabilityVerdict.value = capabilityInspector.buildVerdict(linkMap)
            }
        }
    }

    @Synchronized
    fun stop() {
        if (!running) return
        running = false
        Logger.i(TAG, "Stopping monitoring.")

        reconcileJob?.cancel(); reconcileJob = null
        scoringJob?.cancel(); scoringJob = null
        trafficJob?.cancel(); trafficJob = null
        capabilityJob?.cancel(); capabilityJob = null
        selector.stop()

        probeJobs.values.forEach { it.cancel() }
        probeJobs.clear()
        aggregators.clear()

        _health.value = emptyMap()
        _scores.value = emptyMap()
        _traffic.value = TrafficSnapshot.EMPTY
        _capabilityVerdict.value = null
        lastAppliedConfig = null

        networkMonitor.stop()
    }

    private fun reconcileProbes(currentLinkIds: Set<LinkId>, config: ProbeConfig) {
        if (config != lastAppliedConfig) {
            // The probe URL(s)/interval/window changed - restart every
            // in-flight probe loop so the new configuration takes effect
            // immediately instead of only applying to newly-seen links.
            Logger.i(TAG, "Probe configuration changed; restarting all probe loops.")
            probeJobs.values.forEach { it.cancel() }
            probeJobs.clear()
            aggregators.clear()
            _health.value = emptyMap()
            lastAppliedConfig = config
        }

        for (linkId in currentLinkIds) {
            if (linkId in probeJobs) continue
            val network = networkMonitor.networkFor(linkId) ?: continue
            val aggregator = aggregators.getOrPut(linkId) { JitterLossAggregator(config.windowSize) }
            Logger.i(TAG, "Starting probe loop for link handle=${linkId.networkHandle}")
            probeJobs[linkId] = scope.launch {
                healthProbe.runLoop(network, config) { sample ->
                    _health.update { current ->
                        current + (linkId to aggregator.addSample(sample))
                    }
                }
            }
        }

        val disappeared = probeJobs.keys - currentLinkIds
        for (linkId in disappeared) {
            Logger.i(TAG, "Stopping probe loop for link handle=${linkId.networkHandle} (link no longer present)")
            probeJobs.remove(linkId)?.cancel()
            aggregators.remove(linkId)
            _health.update { it - linkId }
            _scores.update { it - linkId }
        }
    }
}
