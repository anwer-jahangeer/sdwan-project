package com.windowssdwan.multilink.util

import java.io.InputStream

/**
 * Reads at most [maxBytes] from this stream and discards them, returning
 * the number of bytes actually read (which may be less than [maxBytes], or
 * 0 at end-of-stream).
 *
 * `InputStream.readNBytes(int)` is API 33+ only; this app's minSdk is 26,
 * so probes use this small manual loop instead, to read only a minimal
 * amount of response body (per this app's "minimal bytes" probe design)
 * without depending on a newer API.
 */
internal fun InputStream.readUpToCompat(maxBytes: Int): Int {
    val buffer = ByteArray(maxBytes)
    var totalRead = 0
    while (totalRead < maxBytes) {
        val read = read(buffer, totalRead, maxBytes - totalRead)
        if (read == -1) break
        totalRead += read
    }
    return totalRead
}
