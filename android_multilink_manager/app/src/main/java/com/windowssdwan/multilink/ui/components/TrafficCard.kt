package com.windowssdwan.multilink.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.windowssdwan.multilink.model.TrafficSnapshot
import com.windowssdwan.multilink.util.DisplayFormat

/**
 * Aggregate byte counters from `TrafficStats`. Deliberately does not (and
 * cannot, via any public API) split bytes by Wi-Fi vs cellular - see
 * [TrafficSnapshot]'s docs.
 */
@Composable
fun TrafficCard(traffic: TrafficSnapshot, modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = "Traffic (aggregate, not per-link)", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Android has no public API to attribute bytes to a specific link " +
                    "(Wi-Fi vs cellular). These are device/app aggregates only.",
                style = MaterialTheme.typography.labelSmall
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("This app (RX/TX)", style = MaterialTheme.typography.bodyMedium)
                Text(
                    "${DisplayFormat.bytesOrUnknown(traffic.appUidRxBytes)} / ${DisplayFormat.bytesOrUnknown(traffic.appUidTxBytes)}",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Device mobile total (RX/TX)", style = MaterialTheme.typography.bodyMedium)
                Text(
                    "${DisplayFormat.bytesOrUnknown(traffic.deviceMobileRxBytes)} / ${DisplayFormat.bytesOrUnknown(traffic.deviceMobileTxBytes)}",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Device total, all networks (RX/TX)", style = MaterialTheme.typography.bodyMedium)
                Text(
                    "${DisplayFormat.bytesOrUnknown(traffic.deviceTotalRxBytes)} / ${DisplayFormat.bytesOrUnknown(traffic.deviceTotalTxBytes)}",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}
