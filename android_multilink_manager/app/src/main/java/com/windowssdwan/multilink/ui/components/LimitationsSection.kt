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

/**
 * Always-visible, prominent limitations statement (mirrors the README's
 * scope section) - this app must never let a user believe it can steer
 * hotspot-client traffic or bond bandwidth across links.
 */
@Composable
fun LimitationsSection(modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Limitations - please read",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "This is a STOCK, NON-ROOT feasibility MVP. It can only choose which " +
                    "network THIS APP's OWN connections use. It cannot and does not:\n" +
                    "\u2022 steer traffic for other apps (would require a VpnService userspace forwarder)\n" +
                    "\u2022 steer traffic for devices connected to this phone's hotspot (privileged/root only)\n" +
                    "\u2022 combine/bond Wi-Fi and cellular bandwidth for a single connection (needs a remote server)\n" +
                    "\u2022 enable or disable the hotspot itself (always your own action via Settings)",
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}
