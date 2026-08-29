package com.windowssdwan.multilink.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.windowssdwan.multilink.model.TransportKind
import com.windowssdwan.multilink.ui.LinkCardUiState
import com.windowssdwan.multilink.ui.theme.CellularGreen
import com.windowssdwan.multilink.ui.theme.UnknownGray
import com.windowssdwan.multilink.ui.theme.WifiBlue
import com.windowssdwan.multilink.util.DisplayFormat

/** One link's full status: capabilities, probe health, score, and a small history sparkline. */
@Composable
fun LinkCard(state: LinkCardUiState, modifier: Modifier = Modifier) {
    val accent = when (state.snapshot.transport) {
        TransportKind.WIFI -> WifiBlue
        TransportKind.CELLULAR -> CellularGreen
        else -> UnknownGray
    }

    Card(modifier = modifier.fillMaxWidth(), colors = CardDefaults.cardColors()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = transportLabel(state.snapshot.transport),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = "Score: ${DisplayFormat.scoreOrUnknown(state.score?.total)}",
                    style = MaterialTheme.typography.titleMedium
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            InfoRow("Validated", if (state.snapshot.validated) "Yes" else "No")
            InfoRow("Internet capability", if (state.snapshot.hasInternetCapability) "Yes" else "No")
            InfoRow("Metered", if (state.snapshot.metered) "Yes" else "No")
            InfoRow("Roaming", if (state.snapshot.roaming) "Yes" else "No")
            InfoRow("Interface", state.snapshot.interfaceName ?: "Unknown")
            InfoRow("Downstream (estimate)", DisplayFormat.kbpsOrUnknown(state.snapshot.downstreamKbpsEstimate))
            InfoRow("Upstream (estimate)", DisplayFormat.kbpsOrUnknown(state.snapshot.upstreamKbpsEstimate))
            InfoRow("Signal", state.snapshot.signalStrengthOrUnknown?.toString() ?: "Unknown")
            InfoRow("Default route", if (state.snapshot.hasDefaultRoute) "Yes" else "No")
            InfoRow("IP address(es)", state.snapshot.ipAddresses.ifEmpty { listOf("Unknown") }.joinToString())
            InfoRow("DNS", state.snapshot.dnsServers.ifEmpty { listOf("Unknown") }.joinToString())

            Spacer(modifier = Modifier.height(8.dp))
            Text(text = "Probe health (HTTP-layer, not ICMP)", style = MaterialTheme.typography.labelSmall)
            InfoRow("Samples", "${state.health.successCount}/${state.health.sampleCount} succeeded")
            InfoRow("Loss", DisplayFormat.percentOrUnknown(state.health.lossFraction))
            InfoRow("Avg connect time", DisplayFormat.millisOrUnknown(state.health.avgConnectMillis))
            InfoRow("Avg total request time", DisplayFormat.millisOrUnknown(state.health.avgTotalMillis))
            InfoRow("Jitter", DisplayFormat.millisOrUnknown(state.health.jitterMillis))

            Spacer(modifier = Modifier.height(8.dp))
            HistorySparkline(values = state.scoreHistory, lineColor = accent)
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium)
        Text(text = value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
    }
}

private fun transportLabel(transport: TransportKind): String = when (transport) {
    TransportKind.WIFI -> "Wi-Fi"
    TransportKind.CELLULAR -> "Cellular"
    TransportKind.ETHERNET -> "Ethernet"
    TransportKind.OTHER -> "Other"
    TransportKind.UNKNOWN -> "Unknown"
}
