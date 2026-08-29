package com.windowssdwan.multilink.ui

import com.windowssdwan.multilink.model.CapabilityVerdict
import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.LinkScore
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.model.SelectionState
import com.windowssdwan.multilink.model.TrafficSnapshot

/** One link's combined view for a [LinkCardUiState] - everything the dashboard needs for one card. */
data class LinkCardUiState(
    val linkId: LinkId,
    val snapshot: NetworkLinkSnapshot,
    val health: LinkHealth,
    val score: LinkScore?,
    val scoreHistory: List<Int>
)

/** Whole-screen state for the dashboard, exposed by [DashboardViewModel]. */
data class DashboardUiState(
    val isMonitoring: Boolean = false,
    val probeConfig: ProbeConfig = ProbeConfig.DEFAULT,
    val linkCards: List<LinkCardUiState> = emptyList(),
    val selection: SelectionState? = null,
    val traffic: TrafficSnapshot = TrafficSnapshot.EMPTY,
    val capabilityVerdict: CapabilityVerdict? = null
)
