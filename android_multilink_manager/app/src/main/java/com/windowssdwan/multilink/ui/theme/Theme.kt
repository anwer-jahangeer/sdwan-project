package com.windowssdwan.multilink.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColors = darkColorScheme(
    primary = PrimaryBrand,
    secondary = CellularGreen,
    tertiary = HotspotOrange,
    background = SurfaceDark,
    surface = SurfaceDarkElevated,
    onBackground = OnSurfaceDark,
    onSurface = OnSurfaceDark,
    error = BadRed
)

private val LightColors = lightColorScheme(
    primary = PrimaryBrand,
    secondary = CellularGreen,
    tertiary = HotspotOrange,
    error = BadRed
)

@Composable
fun MultiLinkManagerTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColors else LightColors
    MaterialTheme(
        colorScheme = colorScheme,
        typography = MultiLinkTypography,
        content = content
    )
}
