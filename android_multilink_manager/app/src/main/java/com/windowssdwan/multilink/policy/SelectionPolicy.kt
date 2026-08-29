package com.windowssdwan.multilink.policy

import com.windowssdwan.multilink.model.LinkId
import com.windowssdwan.multilink.model.SelectionState
import com.windowssdwan.multilink.model.TransportKind

/**
 * Configuration for [SelectionPolicy]'s hold-down/hysteresis behavior.
 */
data class SelectionPolicyConfig(
    /** Minimum time a link must remain selected before a switch is even considered, unless it becomes ineligible. */
    val holdDownMs: Long = 15_000L,
    /** A challenger must beat the current selection's score by at least this many points to trigger a switch. */
    val switchMarginPoints: Int = 8
)

/**
 * A candidate link that is currently eligible to be selected (validated,
 * has internet capability, and has a known score), paired with a score to
 * rank it by.
 */
data class SelectionCandidate(
    val linkId: LinkId,
    val transport: TransportKind,
    val score: Int
)

/**
 * Pure, deterministic (given `now`) app-owned per-flow link selection
 * policy with hold-down and hysteresis so the active selection does not
 * "flap" between two similarly-scoring links.
 *
 * This only decides which link *this app's own* new connections should
 * prefer - see [com.windowssdwan.multilink.model.CapabilityVerdict] for why
 * that is fundamentally different from (and much more limited than)
 * phone-wide or hotspot-client traffic steering.
 *
 * No Android dependency - safe to unit test on the plain JVM with fake
 * timestamps.
 *
 * Decision rules, in order:
 * 1. No eligible candidates at all -> select nothing.
 * 2. No previous selection, or the previously selected link is no longer
 *    eligible -> immediately select the best-scoring candidate (nothing to
 *    hold down from).
 * 3. Previous selection is still eligible and is *also* the best-scoring
 *    candidate -> keep it.
 * 4. Previous selection is still eligible but a different candidate scores
 *    higher:
 *    - if still within the hold-down window since the last switch, keep
 *      the previous selection regardless of margin (anti-flap);
 *    - otherwise, switch only if the challenger's score exceeds the
 *      previous selection's score by at least [SelectionPolicyConfig.switchMarginPoints]
 *      (hysteresis band), otherwise keep the previous selection.
 */
class SelectionPolicy(private val config: SelectionPolicyConfig = SelectionPolicyConfig()) {

    fun decide(
        now: Long,
        previous: SelectionState?,
        candidates: List<SelectionCandidate>
    ): SelectionState {
        if (candidates.isEmpty()) {
            return SelectionState.none(now, "No eligible app-owned network is currently validated.")
        }

        val best = candidates.maxBy { it.score }
        val previousCandidate = previous?.selectedLinkId?.let { id -> candidates.find { it.linkId == id } }

        if (previous == null || previousCandidate == null) {
            return select(now, best, "No prior selection (or previous link is no longer eligible); choosing best-scoring link.")
        }

        if (previousCandidate.linkId == best.linkId) {
            return select(now, best, "Currently selected link remains the best-scoring eligible link.", keepSince = previous.decidedAtMs)
        }

        val heldSinceMs = now - previous.decidedAtMs
        if (heldSinceMs < config.holdDownMs) {
            val remaining = config.holdDownMs - heldSinceMs
            return previous.copy(
                reason = "Hold-down active (${remaining}ms remaining) - would switch to " +
                    "${best.transport} (score ${best.score}) vs current ${previousCandidate.transport} " +
                    "(score ${previousCandidate.score}), but avoiding rapid flapping."
            )
        }

        val margin = best.score - previousCandidate.score
        return if (margin >= config.switchMarginPoints) {
            select(
                now,
                best,
                "Switching: ${best.transport} scores $margin points higher than current " +
                    "${previousCandidate.transport} (>= ${config.switchMarginPoints}-point hysteresis margin)."
            )
        } else {
            previous.copy(
                reason = "Best alternative (${best.transport}, score ${best.score}) only leads by " +
                    "$margin point(s), below the ${config.switchMarginPoints}-point switch margin; keeping " +
                    "${previousCandidate.transport} to avoid flapping."
            )
        }
    }

    private fun select(now: Long, candidate: SelectionCandidate, reason: String, keepSince: Long = now): SelectionState =
        SelectionState(
            selectedLinkId = candidate.linkId,
            selectedTransport = candidate.transport,
            reason = reason,
            decidedAtMs = keepSince
        )
}
