package com.windowssdwan.multilink.util

import android.content.Context
import android.content.Intent
import android.provider.Settings

/**
 * Builds an intent to open the platform's tethering/hotspot settings
 * screen, with a public, documented fallback for devices/OEM skins where
 * that screen does not resolve.
 *
 * NOTE: `Settings.ACTION_TETHER_SETTINGS` is not a documented, public SDK
 * constant (it does not exist in the public `android.jar`), so it cannot
 * be referenced by name here. Its underlying action string,
 * `"android.settings.TETHER_SETTINGS"`, is a long-standing, widely used
 * value that AOSP's own Settings app registers an intent-filter for, so it
 * is used directly as a plain string. Because this is always resolved via
 * [Intent.resolveActivity] before use, an OEM build that does not expose
 * this screen simply falls through to the guaranteed-public
 * [Settings.ACTION_WIRELESS_SETTINGS] instead of crashing.
 *
 * This app never enables/disables the hotspot itself - hotspot state
 * remains entirely user-driven via this Settings screen, per this app's
 * non-root, non-privileged design.
 */
object SettingsIntents {
    private const val ACTION_TETHER_SETTINGS = "android.settings.TETHER_SETTINGS"

    fun tetherSettingsOrFallback(context: Context): Intent {
        val primary = Intent(ACTION_TETHER_SETTINGS)
        return if (primary.resolveActivity(context.packageManager) != null) {
            primary
        } else {
            Intent(Settings.ACTION_WIRELESS_SETTINGS)
        }
    }
}
