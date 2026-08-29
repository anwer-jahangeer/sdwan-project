package com.windowssdwan.multilink.util

/**
 * Small, null-aware formatting helpers for the UI. A `null` input always
 * formats as "Unknown" - never as "0" - to keep the unknown-vs-zero
 * distinction visible to the user everywhere metrics are displayed.
 */
object DisplayFormat {

    fun bytesOrUnknown(bytes: Long?): String = bytes?.let(::humanBytes) ?: "Unknown"

    fun kbpsOrUnknown(kbps: Int?): String = kbps?.let { "$it kbps (estimate)" } ?: "Unknown"

    fun millisOrUnknown(ms: Double?): String = ms?.let { "%.0f ms".format(it) } ?: "Unknown"

    fun percentOrUnknown(fraction: Double?): String = fraction?.let { "%.0f%%".format(it * 100.0) } ?: "Unknown"

    fun scoreOrUnknown(score: Int?): String = score?.toString() ?: "Unknown"

    private fun humanBytes(bytes: Long): String {
        if (bytes < 1024) return "$bytes B"
        val units = listOf("KB", "MB", "GB", "TB")
        var value = bytes.toDouble()
        var unitIndex = -1
        while (value >= 1024 && unitIndex < units.lastIndex) {
            value /= 1024
            unitIndex++
        }
        return "%.1f %s".format(value, units[unitIndex.coerceAtLeast(0)])
    }
}
