package com.windowssdwan.multilink.ui

import android.app.Application
import android.net.ConnectivityManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.LinkScore
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.monitoring.MonitoringCoordinator
import com.windowssdwan.multilink.monitoring.TrafficStatsReader
import com.windowssdwan.multilink.networking.AndroidBoundConnectionFactory
import com.windowssdwan.multilink.networking.CapabilityInspector
import com.windowssdwan.multilink.networking.NetworkMonitor
import com.windowssdwan.multilink.util.Logger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap

/**
 * Owns the [MonitoringCoordinator] and exposes a single, responsive
 * [DashboardUiState] flow to the Compose UI. All monitoring/probing work
 * happens in [MonitoringCoordinator]'s coroutines (off the main thread for
 * any actual I/O); this ViewModel only assembles UI-friendly state.
 */
class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    private companion object {
        const val TAG = "DashboardViewModel"
        const val SCORE_HISTORY_LIMIT = 60
    }

    private val connectivityManager =
        application.getSystemService(ConnectivityManager::class.java)

    private val networkMonitor = NetworkMonitor(connectivityManager)
    private val connectionFactory = AndroidBoundConnectionFactory(
        connectTimeoutMs = ProbeConfig.DEFAULT.timeoutMs.toInt(),
        readTimeoutMs = ProbeConfig.DEFAULT.timeoutMs.toInt()
    )
    private val trafficStatsReader = TrafficStatsReader(appUid = application.applicationInfo.uid)
    private val capabilityInspector = CapabilityInspector(application)

    private val coordinator = MonitoringCoordinator(
        networkMonitor = networkMonitor,
        connectionFactory = connectionFactory,
        trafficStatsReader = trafficStatsReader,
        capabilityInspector = capabilityInspector,
        scope = viewModelScope
    )

    private val scoreHistories = ConcurrentHashMap<LinkId, ArrayDeque<Int>>()

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(coordinator.links, coordinator.health, coordinator.scores) { links, health, scores ->
                buildLinkCards(links, health, scores)
            }.collect { cards -> _uiState.update { it.copy(linkCards = cards) } }
        }
        viewModelScope.launch {
            coordinator.traffic.collect { traffic -> _uiState.update { it.copy(traffic = traffic) } }
        }
        viewModelScope.launch {
            coordinator.capabilityVerdict.collect { verdict -> _uiState.update { it.copy(capabilityVerdict = verdict) } }
        }
        viewModelScope.launch {
            coordinator.selector.selection.collect { selection -> _uiState.update { it.copy(selection = selection) } }
        }
        viewModelScope.launch {
            coordinator.probeConfig.collect { config -> _uiState.update { it.copy(probeConfig = config) } }
        }
    }

    fun startMonitoring() {
        Logger.i(TAG, "User requested start.")
        scoreHistories.clear()
        coordinator.start()
        _uiState.update { it.copy(isMonitoring = true) }
    }

    fun stopMonitoring() {
        Logger.i(TAG, "User requested stop.")
        coordinator.stop()
        _uiState.update { it.copy(isMonitoring = false, linkCards = emptyList(), selection = null) }
    }

    fun updateProbeConfig(config: ProbeConfig) {
        coordinator.updateProbeConfig(config)
    }

    private fun buildLinkCards(
        links: Map<LinkId, NetworkLinkSnapshot>,
        health: Map<LinkId, LinkHealth>,
        scores: Map<LinkId, LinkScore>
    ): List<LinkCardUiState> {
        // Drop history for links that no longer exist, so a reappearing
        // link (possibly a different physical network) starts a fresh
        // history rather than showing a stale graph.
        scoreHistories.keys.retainAll(links.keys)

        return links.entries
            .sortedBy { it.value.transport.name }
            .map { (linkId, snapshot) ->
                val score = scores[linkId]
                val history = scoreHistories.getOrPut(linkId) { ArrayDeque() }
                score?.total?.let { total ->
                    history.addLast(total)
                    while (history.size > SCORE_HISTORY_LIMIT) history.removeFirst()
                }
                LinkCardUiState(
                    linkId = linkId,
                    snapshot = snapshot,
                    health = health[linkId] ?: LinkHealth.UNKNOWN,
                    score = score,
                    scoreHistory = history.toList()
                )
            }
    }

    override fun onCleared() {
        coordinator.stop()
        super.onCleared()
    }
}
