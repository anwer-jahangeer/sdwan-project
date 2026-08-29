package com.windowssdwan.multilink.ui.components

import androidx.compose.foundation.layout.Column
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
import com.windowssdwan.multilink.model.SelectionState

/**
 * Shows which link this app's OWN outgoing connections currently prefer,
 * and why - explicitly not a claim about the OS default network, other
 * apps, or hotspot clients.
 */
@Composable
fun SelectionCard(selection: SelectionState?, modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "This app's selected path (app-owned traffic only)",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = selection?.selectedTransport?.name ?: "None selected yet",
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = selection?.reason ?: "Start monitoring to begin selecting.",
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}
