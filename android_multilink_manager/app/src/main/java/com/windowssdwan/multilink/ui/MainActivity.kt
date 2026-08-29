package com.windowssdwan.multilink.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.windowssdwan.multilink.ui.screens.DashboardScreen
import com.windowssdwan.multilink.ui.theme.MultiLinkManagerTheme
import com.windowssdwan.multilink.util.SettingsIntents

/**
 * Single-Activity launcher. No other permissions/runtime prompts are
 * requested here - INTERNET/ACCESS_NETWORK_STATE/ACCESS_WIFI_STATE are
 * normal (install-time) permissions declared in the manifest only.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MultiLinkManagerTheme {
                val viewModel: DashboardViewModel = viewModel()
                val uiState by viewModel.uiState.collectAsStateWithLifecycle()

                DashboardScreen(
                    isMonitoring = uiState.isMonitoring,
                    probeConfig = uiState.probeConfig,
                    linkCards = uiState.linkCards,
                    selection = uiState.selection,
                    traffic = uiState.traffic,
                    capabilityVerdict = uiState.capabilityVerdict,
                    onStart = viewModel::startMonitoring,
                    onStop = viewModel::stopMonitoring,
                    onConfigChanged = viewModel::updateProbeConfig,
                    onOpenTetherSettings = {
                        startActivity(SettingsIntents.tetherSettingsOrFallback(this))
                    }
                )
            }
        }
    }
}
