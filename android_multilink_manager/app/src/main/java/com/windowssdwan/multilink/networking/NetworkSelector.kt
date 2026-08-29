package com.windowssdwan.multilink.networking

import android.net.Network
import com.windowssdwan.multilink.model.LinkScore
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.SelectionState
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.policy.SelectionCandidate
import com.windowssdwan.multilink.policy.SelectionPolicy
import com.windowssdwan.multilink.policy.SelectionPolicyConfig
import com.windowssdwan.multilink.util.Logger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Exposes the app-owned per-flow selector's current decision, and the
 * actual [Network] callers inside this app should use for new
 * sockets/connections.
 *
 * IMPORTANT: this selection is consulted only by code in this app that
 * chooses to call [selectedNetworkOrNull] (e.g. the health probes
 * themselves probe every link directly, not through the selector - but a
 * hypothetical future "use the best link for this app's own traffic"
 * feature would go through here). It has no effect on the OS default
 * network, on other apps, or on hotspot clients.
 */
interface NetworkSelector {
    val selection: StateFlow<SelectionState>
    fun start()
    fun stop()
    fun selectedNetworkOrNull(): Network?
}

class HysteresisNetworkSelector(
    private val networkMonitor: NetworkMonitor,
    private val scores: StateFlow<Map<LinkId, LinkScore>>,
    scope: CoroutineScope,
    policyConfig: SelectionPolicyConfig = SelectionPolicyConfig()
) : NetworkSelector {

    private companion object {
        const val TAG = "NetworkSelector"
    }

    private val policy = SelectionPolicy(policyConfig)
    private val _selection = MutableStateFlow(SelectionState.none(System.currentTimeMillis(), "Not yet evaluated."))
    override val selection: StateFlow<SelectionState> = _selection.asStateFlow()

    private var selectionJob: Job? = null

    override fun start() {
        if (selectionJob?.isActive == true) return
        selectionJob = scope.launch {
            combine(networkMonitor.links, scores) { links, scoreMap -> links to scoreMap }
                .collect { (links, scoreMap) ->
                    val candidates = links.values
                        .filter { it.isUsable }
                        .mapNotNull { snapshot ->
                            val score = scoreMap[snapshot.linkId]?.total ?: return@mapNotNull null
                            SelectionCandidate(snapshot.linkId, snapshot.transport, score)
                        }
                    val next = policy.decide(System.currentTimeMillis(), _selection.value, candidates)
                    if (next.selectedLinkId != _selection.value.selectedLinkId) {
                        Logger.i(TAG, "Selection changed: ${next.selectedTransport} (${next.reason})")
                    }
                    _selection.value = next
                }
        }
    }

    override fun stop() {
        selectionJob?.cancel()
        selectionJob = null
        _selection.value = SelectionState.none(
            System.currentTimeMillis(),
            "Monitoring stopped."
        )
    }

    override fun selectedNetworkOrNull(): Network? =
        _selection.value.selectedLinkId?.let { networkMonitor.networkFor(it) }
}
