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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.windowssdwan.multilink.model.CapabilityVerdict

/**
 * Shows the capability inspector's verdict: what this app can/cannot do on
 * this device, plus a button to jump to the platform's own hotspot
 * settings (this app never toggles the hotspot itself).
 */
@Composable
fun CapabilityCard(
    verdict: CapabilityVerdict?,
    onOpenTetherSettings: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row {
                Text(
                    text = "Capability verdict",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
            }
            Spacer(modifier = Modifier.height(8.dp))

            if (verdict == null) {
                Text("Start monitoring to compute a verdict.", style = MaterialTheme.typography.bodyMedium)
            } else {
                Text(
                    text = "Both Wi-Fi + cellular validated right now: " +
                        if (verdict.bothConcurrentlyAvailable) "Yes" else "No",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium
                )
                Spacer(modifier = Modifier.height(8.dp))
                verdict.explanationLines.forEach { line ->
                    Text(text = "\u2022 $line", style = MaterialTheme.typography.bodyMedium)
                    Spacer(modifier = Modifier.height(4.dp))
                }
            }

            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = onOpenTetherSettings) {
                Text("Open hotspot / tethering settings")
            }
        }
    }
}
