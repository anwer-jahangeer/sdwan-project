package com.windowssdwan.multilink.scoring

import com.windowssdwan.multilink.model.LinkHealth
import com.windowssdwan.multilink.model.LinkScore
import com.windowssdwan.multilink.model.NetworkLinkSnapshot
import kotlin.math.roundToInt

/**
 * Computes a 0-100 [LinkScore] for a link from its current capabilities
 * snapshot and its rolling probe health.
 *
 * ### Documented formula
 *
 * Four independently-computable components, each worth a fixed maximum
 * number of points that sum to 100:
 *
 * | Component      | Max points | Input                                  | Unknown when...                |
 * |----------------|-----------:|-----------------------------------------|---------------------------------|
 * | Connectivity   | 40         | [NetworkLinkSnapshot.validated] / [NetworkLinkSnapshot.hasInternetCapability] | never - always computable once a snapshot exists |
 * | Reliability    | 30         | [LinkHealth.lossFraction]                | no probe samples yet            |
 * | Latency        | 20         | [LinkHealth.avgTotalMillis]               | no *successful* probe sample yet |
 * | Jitter         | 10         | [LinkHealth.jitterMillis]                 | fewer than 2 successful samples |
 *
 * **Connectivity** (0-40): 40 if platform-validated internet access, 15 if
 * the network merely declares `NET_CAPABILITY_INTERNET` without being
 * validated yet (e.g. captive portal, just connected), 0 if neither.
 *
 * **Reliability** (0-30): `30 * (1 - lossFraction)`, i.e. linear in probe
 * success rate over the rolling window.
 *
 * **Latency** (0-20): linear ramp from [GOOD_LATENCY_MS] (or better) = 20
 * points down to [BAD_LATENCY_MS] (or worse) = 0 points, using the mean
 * successful *total* HTTP request time (see [ProbeSample] docs - this is
 * HTTP-layer timing, not ICMP).
 *
 * **Jitter** (0-10): linear ramp from 0ms = 10 points down to
 * [BAD_JITTER_MS] (or worse) = 0 points.
 *
 * ### Unknown handling
 *
 * A component that cannot yet be computed is `null` and is **excluded from
 * both the numerator and denominator** when computing [LinkScore.total] -
 * it is never treated as 0 (worst) or as full marks (best). Concretely:
 *
 * ```
 * total = round(100 * sum(knownComponentValues) / sum(knownComponentMaxPoints))
 * ```
 *
 * so a brand-new, validated Wi-Fi link with zero probe samples yet scores
 * `round(100 * 40/40) = 100` (based purely on what's known: connectivity is
 * good), not a misleadingly low score just because reliability/latency/
 * jitter haven't been measured yet. [LinkScore.knownComponentCount] tells
 * the UI/tests how much of the score is actually backed by data, so a
 * confidence indicator can be shown alongside the number.
 *
 * If literally nothing is known (should not happen in practice, since
 * connectivity is always computable), [LinkScore.total] is `null`.
 */
object LinkScorer {

    const val CONNECTIVITY_MAX = 40
    const val RELIABILITY_MAX = 30
    const val LATENCY_MAX = 20
    const val JITTER_MAX = 10

    const val GOOD_LATENCY_MS = 80.0
    const val BAD_LATENCY_MS = 1500.0

    const val BAD_JITTER_MS = 400.0

    fun score(snapshot: NetworkLinkSnapshot, health: LinkHealth): LinkScore {
        val connectivity = connectivityComponent(snapshot)

        val reliability = health.lossFraction?.let { loss ->
            (RELIABILITY_MAX * (1.0 - loss)).roundToInt().coerceIn(0, RELIABILITY_MAX)
        }

        val latency = health.avgTotalMillis?.let { ms ->
            rampDown(ms, GOOD_LATENCY_MS, BAD_LATENCY_MS, LATENCY_MAX)
        }

        val jitter = health.jitterMillis?.let { ms ->
            rampDown(ms, 0.0, BAD_JITTER_MS, JITTER_MAX)
        }

        val knownValues = listOfNotNull(
            connectivity to CONNECTIVITY_MAX,
            reliability?.let { it to RELIABILITY_MAX },
            latency?.let { it to LATENCY_MAX },
            jitter?.let { it to JITTER_MAX }
        )

        val knownMaxSum = knownValues.sumOf { it.second }
        val total = if (knownMaxSum == 0) {
            null
        } else {
            (100.0 * knownValues.sumOf { it.first } / knownMaxSum).roundToInt().coerceIn(0, 100)
        }

        return LinkScore(
            total = total,
            connectivityComponent = connectivity,
            reliabilityComponent = reliability,
            latencyComponent = latency,
            jitterComponent = jitter,
            knownComponentCount = knownValues.size
        )
    }

    private fun connectivityComponent(snapshot: NetworkLinkSnapshot): Int = when {
        snapshot.validated -> CONNECTIVITY_MAX
        snapshot.hasInternetCapability -> (CONNECTIVITY_MAX * 0.375).roundToInt() // 15/40
        else -> 0
    }

    /** Linear ramp: `goodValue` (or better/lower) maps to `maxPoints`, `badValue` (or worse/higher) maps to 0. */
    private fun rampDown(value: Double, goodValue: Double, badValue: Double, maxPoints: Int): Int {
        if (value <= goodValue) return maxPoints
        if (value >= badValue) return 0
        val fraction = 1.0 - ((value - goodValue) / (badValue - goodValue))
        return (maxPoints * fraction).roundToInt().coerceIn(0, maxPoints)
    }
}
