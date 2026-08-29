package com.windowssdwan.multilink.model

/**
 * Whether this device's Wi-Fi hotspot / SoftAP is currently enabled.
 *
 * There is no public, non-privileged Android API to reliably read this as
 * of Android 16 (`WifiManager`'s AP-state getters are `@SystemApi`/hidden).
 * This app never uses reflection or hidden APIs to work around that, so in
 * this codebase [currentState] will in practice always resolve to
 * [UNKNOWN] - that is intentional, not a bug, and is surfaced to the user
 * as "Unknown" rather than guessed.
 */
enum class HotspotState {
    ENABLED,
    DISABLED,
    UNKNOWN
}
