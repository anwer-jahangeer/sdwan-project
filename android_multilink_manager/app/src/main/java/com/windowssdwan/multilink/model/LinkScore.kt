package com.windowssdwan.multilink.model

/**
 * A link's computed health score, 0-100, plus its component breakdown so
 * the UI/logs can show *why* a link scored the way it did rather than a
 * single opaque number.
 *
 * See `com.windowssdwan.multilink.scoring.LinkScorer` for the documented
 * formula that produces this. Any component that could not be computed
 * (not enough probe data yet) is `null`, and [total] is re-normalized over
 * only the known components rather than penalizing unknowns as failures -
 * "unknown" and "bad" are kept clearly distinct throughout this app.
 */
data class LinkScore(
    /** 0-100, or null only if *no* component could be computed at all (brand-new link). */
    val total: Int?,

    /** 0-40: connectivity/validation component. Always computable once a snapshot exists. */
    val connectivityComponent: Int,

    /** 0-30: probe success-rate component. Null until at least one probe sample exists. */
    val reliabilityComponent: Int?,

    /** 0-20: probe latency component. Null until at least one successful probe sample exists. */
    val latencyComponent: Int?,

    /** 0-10: probe jitter component. Null until at least two successful probe samples exist. */
    val jitterComponent: Int?,

    /** Number of the 4 components above that were actually computed (0-4). */
    val knownComponentCount: Int
)
