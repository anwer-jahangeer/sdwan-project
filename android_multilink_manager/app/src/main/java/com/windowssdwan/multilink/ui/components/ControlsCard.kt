package com.windowssdwan.multilink.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.windowssdwan.multilink.model.ProbeConfig

/**
 * Start/stop control plus the configurable probe endpoint list and probe
 * interval. Local text-field state is re-synced from [probeConfig] whenever
 * it changes elsewhere (e.g. on first load), and pushed back via
 * [onConfigChanged] only when the user taps Apply.
 */
@Composable
fun ControlsCard(
    isMonitoring: Boolean,
    probeConfig: ProbeConfig,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onConfigChanged: (ProbeConfig) -> Unit,
    modifier: Modifier = Modifier
) {
    var endpointsText by remember { mutableStateOf(probeConfig.endpoints.joinToString("\n")) }
    var intervalText by remember { mutableStateOf((probeConfig.intervalMs / 1000).toString()) }
    var timeoutText by remember { mutableStateOf((probeConfig.timeoutMs / 1000.0).toString()) }

    LaunchedEffect(probeConfig) {
        endpointsText = probeConfig.endpoints.joinToString("\n")
        intervalText = (probeConfig.intervalMs / 1000).toString()
        timeoutText = (probeConfig.timeoutMs / 1000.0).toString()
    }

    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row {
                Text(
                    text = "Monitoring controls",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = if (isMonitoring) onStop else onStart) {
                Text(if (isMonitoring) "Stop monitoring" else "Start monitoring")
            }

            Spacer(modifier = Modifier.height(12.dp))
            OutlinedTextField(
                value = endpointsText,
                onValueChange = { endpointsText = it },
                label = { Text("Probe URL(s), one per line (https:// only)") },
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = intervalText,
                    onValueChange = { intervalText = it },
                    label = { Text("Interval (s)") },
                    modifier = Modifier.weight(1f)
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = timeoutText,
                    onValueChange = { timeoutText = it },
                    label = { Text("Timeout (s)") },
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = {
                val endpoints = endpointsText.lines().map { it.trim() }.filter { it.isNotBlank() }
                val intervalSeconds = intervalText.toDoubleOrNull() ?: (ProbeConfig.DEFAULT.intervalMs / 1000.0)
                val timeoutSeconds = timeoutText.toDoubleOrNull() ?: (ProbeConfig.DEFAULT.timeoutMs / 1000.0)
                onConfigChanged(
                    probeConfig.copy(
                        endpoints = endpoints,
                        intervalMs = (intervalSeconds * 1000).toLong(),
                        timeoutMs = (timeoutSeconds * 1000).toLong()
                    ).sanitized()
                )
            }) {
                Text("Apply probe settings")
            }
        }
    }
}
