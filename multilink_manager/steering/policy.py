"""Pure, OS-independent automatic-failover decision engine.

**Algorithm summary** (mirrored in the README "Automatic failover
(opt-in)" section -- keep both in sync if you change this):

Each tick, ``SteeringPolicy.decide()`` is given the currently
OS-observed active interface (Windows' own effective-metric preferred
path) and a ``CandidateHealth`` snapshot for every known interface, and
returns a ``SteeringDecision``:

1. **Hold-down.** If a switch happened less than ``hold_down_seconds``
   ago, no new switch is considered at all this tick (flap prevention).
2. **Candidate selection.** Only interfaces that are eligible physical
   paths (Ethernet/Wi-Fi, status up, has an operational IPv4 default
   route), reachable (``reachable is True``, never ``None``/``False``),
   and have a *known* score (``score is not None``) are considered as
   candidates. The best-scoring eligible candidate is chosen; unknown
   scores can never make an interface a candidate.
3. **Switch condition.** A switch is only *considered* when the best
   candidate is demonstrably better than the current active interface,
   which means one of:
   - the active interface is **confirmed unhealthy**: no health data at
     all, ``reachable is False``, or a known score below
     ``unhealthy_score_threshold``; **or**
   - the active interface's score is known and healthy, and the
     candidate's score exceeds it by at least
     ``score_advantage_threshold`` (hysteresis).
   If the active interface's score is simply **unknown** (not confirmed
   unreachable, just never measured yet), no switch is considered --
   unknown scores must never trigger switching on their own, for either
   side of the comparison.
4. **N-cycle confirmation.** Even once the switch condition holds, the
   *same* candidate must keep meeting it for ``min_consecutive_cycles``
   consecutive ticks before ``should_switch`` becomes True. Any tick
   where the condition stops holding, or a different candidate becomes
   best, resets the streak to zero.
5. After a real switch is recorded (``record_switch``), the hold-down
   timer restarts and the streak resets, so the newly active interface
   gets a full, undisturbed observation window before another switch can
   even begin confirming.
"""

from __future__ import annotations

import time as _time
from typing import Dict, Optional

from multilink_manager.models.steering import CandidateHealth, SteeringConfig, SteeringDecision


class SteeringPolicy:
    """Stateful (but pure/OS-free) hysteresis + hold-down + N-cycle
    confirmation decision engine. One instance is owned per steering
    session and is reset on enable/disable (see
    ``steering.controller.SteeringController``)."""

    def __init__(self, config: Optional[SteeringConfig] = None) -> None:
        self.config = config or SteeringConfig()
        self._streak_candidate: Optional[str] = None
        self._streak_count: int = 0
        self._last_switch_time: Optional[float] = None

    def reset(self) -> None:
        """Clear all in-progress confirmation/hold-down state (used on
        enable and disable so a fresh session never inherits stale
        streak/timer state from a previous one)."""
        self._streak_candidate = None
        self._streak_count = 0
        self._last_switch_time = None

    def record_switch(self, now: Optional[float] = None) -> None:
        """Must be called by the controller immediately after a switch has
        been applied *and verified* successfully -- starts the hold-down
        window and resets the confirmation streak."""
        self._last_switch_time = now if now is not None else _time.time()
        self._streak_candidate = None
        self._streak_count = 0

    def decide(
        self,
        now: float,
        active_interface: Optional[str],
        candidates: Dict[str, CandidateHealth],
    ) -> SteeringDecision:
        cfg = self.config

        if self._last_switch_time is not None:
            elapsed = now - self._last_switch_time
            remaining = cfg.hold_down_seconds - elapsed
            if remaining > 0.0:
                # Intentionally do not touch the confirmation streak while
                # in hold-down; it was already reset by record_switch, and
                # resuming confirmation cold once hold-down expires is the
                # whole point of a hold-down (prevents flapping right back).
                return SteeringDecision(
                    should_switch=False,
                    target_interface=None,
                    reason=f"hold-down active ({remaining:.0f}s remaining since last switch)",
                    consecutive_cycles=0,
                    hold_down_remaining_s=remaining,
                )

        active_health = candidates.get(active_interface) if active_interface else None
        active_reachable = active_health.reachable if active_health else None
        active_score = active_health.score if active_health else None
        active_confirmed_unhealthy = (
            active_health is None
            or active_reachable is False
            or (active_score is not None and active_score < cfg.unhealthy_score_threshold)
        )

        best_name: Optional[str] = None
        best_score: Optional[float] = None
        for name, health in candidates.items():
            if name == active_interface:
                continue
            if not health.is_eligible_physical or not health.has_default_route:
                continue
            if health.reachable is not True:
                continue
            if health.score is None:
                continue
            if best_score is None or health.score > best_score:
                best_score = health.score
                best_name = name

        if best_name is None or best_score is None:
            self._streak_candidate = None
            self._streak_count = 0
            return SteeringDecision(
                False, None,
                "no eligible, reachable, known-score candidate available",
                0, 0.0,
            )

        if active_confirmed_unhealthy:
            meets_condition = True
            condition_note = "current active path is unhealthy/unreachable"
        elif active_score is None:
            # Genuinely unknown (not confirmed bad) current-path score:
            # never use an unknown value as a switching trigger.
            meets_condition = False
            condition_note = "current active path score unknown (not confirmed unhealthy); no switch on unknowns"
        else:
            advantage = best_score - active_score
            meets_condition = best_score > active_score and advantage >= cfg.score_advantage_threshold
            condition_note = f"advantage={advantage:.1f} (threshold={cfg.score_advantage_threshold:.1f})"

        if not meets_condition:
            self._streak_candidate = None
            self._streak_count = 0
            return SteeringDecision(
                False, None,
                f"candidate {best_name} (score={best_score:.1f}) does not meet switch criteria: "
                f"{condition_note}",
                0, 0.0,
            )

        if self._streak_candidate != best_name:
            self._streak_candidate = best_name
            self._streak_count = 1
        else:
            self._streak_count += 1

        if self._streak_count < cfg.min_consecutive_cycles:
            return SteeringDecision(
                False, None,
                f"candidate {best_name} meets switch criteria ({condition_note}); confirming "
                f"({self._streak_count}/{cfg.min_consecutive_cycles} consecutive cycles)",
                self._streak_count, 0.0,
            )

        return SteeringDecision(
            True, best_name,
            f"switching to {best_name}: confirmed for {self._streak_count} consecutive cycles "
            f"({condition_note})",
            self._streak_count, 0.0,
        )
