package com.windowssdwan.multilink.util

import android.util.Log

/**
 * Thin wrapper around [android.util.Log].
 *
 * Used only for state changes and failures (link appeared/disappeared,
 * selection changed, a probe request failed, callbacks registered/torn
 * down) - deliberately NOT for every probe sample or packet, to avoid
 * flooding logcat during normal operation.
 */
object Logger {
    private const val PREFIX = "MultiLinkManager"

    fun i(tag: String, msg: String) = Log.i("$PREFIX:$tag", msg)
    fun w(tag: String, msg: String, t: Throwable? = null) = Log.w("$PREFIX:$tag", msg, t)
    fun e(tag: String, msg: String, t: Throwable? = null) = Log.e("$PREFIX:$tag", msg, t)
}
