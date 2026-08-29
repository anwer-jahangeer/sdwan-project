package com.windowssdwan.multilink.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.windowssdwan.multilink.model.CapabilityVerdict
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.model.SelectionState
import com.windowssdwan.multilink.model.TrafficSnapshot
import com.windowssdwan.multilink.ui.LinkCardUiState
import com.windowssdwan.multilink.ui.components.CapabilityCard
import com.windowssdwan.multilink.ui.components.ControlsCard
import com.windowssdwan.multilink.ui.components.LimitationsSection
import com.windowssdwan.multilink.ui.components.LinkCard
import com.windowssdwan.multilink.ui.components.SelectionCard
import com.windowssdwan.multilink.ui.components.TrafficCard

/**
 * The single-screen dashboard. Deliberately a plain scrolling
 * [LazyColumn] of cards (no navigation, no bottom sheets) - this is a
 * focused feasibility tool, not a full app.
 */
@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun DashboardScreen(
    isMonitoring: Boolean,
    probeConfig: ProbeConfig,
    linkCards: List<LinkCardUiState>,
    selection: SelectionState?,
    traffic: TrafficSnapshot,
    capabilityVerdict: CapabilityVerdict?,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onConfigChanged: (ProbeConfig) -> Unit,
    onOpenTetherSettings: () -> Unit
) {
    Scaffold(
        topBar = {
            TopAppBar(title = { Text("MultiLink Manager") })
        }
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 12.dp)
        ) {
            item {
                ControlsCard(
                    isMonitoring = isMonitoring,
                    probeConfig = probeConfig,
                    onStart = onStart,
                    onStop = onStop,
                    onConfigChanged = onConfigChanged
                )
            }
            item { LimitationsSection() }
            item { SelectionCard(selection = selection) }

            if (linkCards.isEmpty()) {
                item {
                    Text(
                        text = if (isMonitoring) {
                            "No Wi-Fi or cellular link with internet capability detected yet."
                        } else {
                            "Start monitoring to see link cards."
                        },
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            } else {
                items(linkCards, key = { it.linkId.networkHandle }) { card ->
                    LinkCard(state = card)
                }
            }

            item { TrafficCard(traffic = traffic) }
            item { CapabilityCard(verdict = capabilityVerdict, onOpenTetherSettings = onOpenTetherSettings) }
        }
    }
}
