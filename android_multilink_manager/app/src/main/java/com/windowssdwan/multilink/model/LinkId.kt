package com.windowssdwan.multilink.model

/**
 * Stable identifier for one [android.net.Network] instance, wrapping its
 * `networkHandle` (a stable per-network token per the platform docs, in
 * contrast to `Network.toString()` which is not guaranteed stable).
 *
 * Deliberately just a `Long` wrapper with no Android imports so it - and
 * everything keyed by it - can be unit tested on the plain JVM.
 */
@JvmInline
value class LinkId(val networkHandle: Long)
