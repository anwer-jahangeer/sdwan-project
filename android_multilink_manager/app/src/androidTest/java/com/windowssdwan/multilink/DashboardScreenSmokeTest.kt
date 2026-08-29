package com.windowssdwan.multilink

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.windowssdwan.multilink.model.ProbeConfig
import com.windowssdwan.multilink.ui.screens.DashboardScreen
import com.windowssdwan.multilink.ui.theme.MultiLinkManagerTheme
import org.junit.Rule
import org.junit.Test

/**
 * Minimal on-device smoke test: the dashboard renders its controls and the
 * limitations section without crashing. Deliberately does not exercise
 * real networking (that would need the device's actual radios and is
 * covered by the manual test matrix in the README instead).
 */
class DashboardScreenSmokeTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun dashboardShowsStartButtonAndLimitations() {
        composeRule.setContent {
            MultiLinkManagerTheme {
                DashboardScreen(
                    isMonitoring = false,
                    probeConfig = ProbeConfig.DEFAULT,
                    linkCards = emptyList(),
                    selection = null,
                    traffic = com.windowssdwan.multilink.model.TrafficSnapshot.EMPTY,
                    capabilityVerdict = null,
                    onStart = {},
                    onStop = {},
                    onConfigChanged = {},
                    onOpenTetherSettings = {}
                )
            }
        }

        composeRule.onNodeWithText("Start monitoring").assertExists()
        composeRule.onNodeWithText("Limitations - please read").assertExists()
    }
}
