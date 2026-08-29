"""Orchestrates the opt-in automatic active/backup IPv4 default-route
steering feature: combines ``SteeringPolicy``'s pure decision logic with
``RouteController``'s typed Windows route/metric mutations, including
save-before-mutate / verify-after-mutate / restore-on-failure-or-disable.

No Qt/GUI imports live here (see ``gui/worker.py`` for the integration
that ensures every call in this module runs on ``MonitorWorker``'s
background ``QThread``, never the GUI thread). ``route_controller`` is
injectable specifically so tests can substitute a fake implementation and
guarantee no real PowerShell mutation command is ever issued during the
automated test suite.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.score import ScoreResult
from multilink_manager.models.steering import (
    CandidateHealth,
    OriginalInterfaceSetting,
    SteeringConfig,
    SteeringStatus,
)
from multilink_manager.networking.routes import RouteController
from multilink_manager.steering.policy import SteeringPolicy
from multilink_manager.utils.logging_config import get_logger
from multilink_manager.utils.platform_utils import is_admin, is_windows

logger = get_logger(__name__)

# Any interface metric this low leaves generous headroom below typical
# Windows-assigned automatic metrics (usually tens to a few hundred) --
# used only as a last-resort floor when no other eligible interface's
# effective metric is known (e.g. this is the only other candidate ever
# observed). The real target value is always derived from currently
# observed effective metrics of other eligible interfaces, never this
# constant alone -- see ``SteeringController._compute_target_metric``.
_FALLBACK_INTERFACE_METRIC = 1


class SteeringController:
    """Owns one steering "session": enable/disable, per-tick decisions,
    and all save/apply/verify/restore bookkeeping.

    Intended to be owned directly by ``MonitorWorker`` (one instance per
    monitoring session) and driven exclusively from that worker's own
    background thread -- never call ``tick``/``enable``/``disable`` from
    the GUI thread, since all three may issue PowerShell commands.
    """

    def __init__(self, route_controller: Optional[RouteController] = None) -> None:
        self.config = SteeringConfig()
        self._routes = route_controller or RouteController()
        self._policy = SteeringPolicy(self.config)
        self.enabled = False
        self._saved_settings: Dict[str, OriginalInterfaceSetting] = {}
        self._last_logged_phase: Optional[str] = None
        self.status = SteeringStatus()

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------
    def enable(self, config: Optional[SteeringConfig] = None) -> Tuple[bool, str]:
        """Enable automatic steering. Refuses (returns ``False``) without
        mutating anything if not on Windows or not running elevated, or if
        a previous disable/restore attempt left settings modified."""
        if not is_windows():
            msg = "Automatic steering requires Windows."
            logger.error("Automatic steering enable REJECTED: %s", msg)
            self.status = SteeringStatus(enabled=False, last_decision_reason=msg, last_error=msg)
            return False, msg
        if not is_admin():
            msg = "Automatic steering requires the application to be run as Administrator."
            logger.error("Automatic steering enable REJECTED: %s", msg)
            self.status = SteeringStatus(enabled=False, last_decision_reason=msg, last_error=msg)
            return False, msg
        if self._saved_settings:
            msg = (
                f"Cannot enable automatic steering: {len(self._saved_settings)} previously "
                f"modified interface setting(s) failed to restore and remain modified "
                f"({', '.join(sorted(self._saved_settings))}). Manual correction is required "
                "(e.g. 'Set-NetIPInterface -AutomaticMetric Enabled') before steering can be "
                "safely re-enabled -- see the log for the exact original values that were saved."
            )
            logger.error("Automatic steering enable REFUSED: %s", msg)
            self.status = SteeringStatus(
                enabled=False, last_decision_reason=msg, last_error=msg, restored=False,
            )
            return False, msg

        self.config = config or self.config
        self._policy = SteeringPolicy(self.config)
        self._last_logged_phase = None
        self.enabled = True
        self.status = SteeringStatus(
            enabled=True, last_decision_reason="steering enabled; observing", restored=True
        )
        logger.info(
            "Automatic steering ENABLED (min_consecutive_cycles=%d, "
            "score_advantage_threshold=%.1f, hold_down_seconds=%.1f, "
            "unhealthy_score_threshold=%.1f)",
            self.config.min_consecutive_cycles, self.config.score_advantage_threshold,
            self.config.hold_down_seconds, self.config.unhealthy_score_threshold,
        )
        return True, "enabled"

    def disable(self) -> None:
        """Disable automatic steering and restore every setting this
        session has changed. Safe/idempotent to call even if never
        enabled or already disabled (e.g. from ``MonitorWorker``'s
        shutdown path, unconditionally, to guarantee restore-on-stop)."""
        was_enabled = self.enabled
        had_saved = bool(self._saved_settings)
        if not was_enabled and not had_saved:
            return
        if was_enabled or had_saved:
            logger.info(
                "Automatic steering DISABLE requested; restoring %d saved setting(s)",
                len(self._saved_settings),
            )
        self._restore_all()
        self.enabled = False
        self._policy.reset()
        self._last_logged_phase = None
        restored = not self._saved_settings
        self.status = SteeringStatus(
            enabled=False,
            last_decision_reason="steering disabled",
            restored=restored,
            last_error=self.status.last_error if not restored else None,
        )

    def _restore_all(self) -> None:
        remaining = {}
        for name, setting in list(self._saved_settings.items()):
            success, error = self._routes.restore_setting(setting)
            if success:
                logger.info("Restored original IPv4 metric settings for interface '%s'", name)
            else:
                logger.error(
                    "FAILED to restore original IPv4 metric settings for interface '%s': %s. "
                    "Manual correction may be required -- see README known limitations.",
                    name, error,
                )
                remaining[name] = setting
        self._saved_settings = remaining
        if remaining:
            self.status.last_error = (
                f"Failed to restore original settings for: {', '.join(sorted(remaining))}. "
                "See log for details; you may need to manually run "
                "'Set-NetIPInterface -AutomaticMetric Enabled' for that interface."
            )

    # ------------------------------------------------------------------
    # Per-tick decision + execution
    # ------------------------------------------------------------------
    def tick(
        self,
        interfaces: List[InterfaceInfo],
        scores: Dict[str, ScoreResult],
        active_interface: Optional[str],
    ) -> SteeringStatus:
        if not self.enabled:
            return self.status

        now = time.time()

        # Never steer away from an active VPN/virtual/"Other" preferred
        # path. Even though this feature never mutates a VPN/virtual/Other
        # adapter's own settings, lowering a *physical* interface's metric
        # could inadvertently make it preferred over the active
        # VPN/virtual path's default route, silently bypassing intentional
        # routing. If Windows' currently observed preferred interface is
        # not an eligible physical Ethernet/Wi-Fi interface that is up, do
        # not attempt any switch this tick. ``active_interface is None``
        # (no currently observed preferred path at all) is NOT covered by
        # this guard -- normal N-cycle candidate selection still applies.
        active_iface_obj = None
        if active_interface is not None:
            active_iface_obj = next((i for i in interfaces if i.name == active_interface), None)
        if active_iface_obj is not None and not (
            active_iface_obj.if_type in (InterfaceType.ETHERNET, InterfaceType.WIFI)
            and active_iface_obj.status == InterfaceStatus.UP
        ):
            reason = (
                f"active path '{active_interface}' is not an eligible physical Ethernet/Wi-Fi "
                "interface (e.g. VPN/virtual/Other) -- refusing to steer to avoid inadvertently "
                "bypassing it by lowering a physical interface's metric"
            )
            phase = "active_path_not_eligible_skip"
            if phase != self._last_logged_phase:
                logger.info("Steering decision: %s", reason)
            else:
                logger.debug("Steering decision (unchanged phase): %s", reason)
            self._last_logged_phase = phase
            self.status.active_interface = active_interface
            self.status.target_interface = None
            self.status.last_decision_reason = reason
            self.status.consecutive_cycles = 0
            self.status.hold_down_remaining_s = 0.0
            return self.status

        candidates: Dict[str, CandidateHealth] = {}
        for iface in interfaces:
            score_result = scores.get(iface.name)
            score = score_result.score if score_result else None
            reachable = score_result.reachable if score_result else None
            is_eligible_physical = (
                iface.if_type in (InterfaceType.ETHERNET, InterfaceType.WIFI)
                and iface.status == InterfaceStatus.UP
            )
            has_default_route = (
                iface.index is not None
                and bool(iface.ipv4_gateway)
                and self._routes.has_operational_ipv4_default_route(iface.index)
            )
            candidates[iface.name] = CandidateHealth(
                interface_name=iface.name,
                score=score,
                reachable=reachable,
                is_eligible_physical=is_eligible_physical,
                has_default_route=has_default_route,
            )

        decision = self._policy.decide(now, active_interface, candidates)

        # Log at INFO only on a *phase* transition (hold-down entered,
        # confirmation of a given candidate started, or a switch actually
        # happening), never every tick -- otherwise a ticking hold-down
        # countdown or a multi-cycle confirmation would flood INFO. The
        # detailed human-readable reason is always logged, just gated on
        # whether the coarse phase actually changed since last tick.
        phase = self._phase_of(decision)
        if phase != self._last_logged_phase:
            logger.info("Steering decision: %s", decision.reason)
        else:
            logger.debug("Steering decision (unchanged phase): %s", decision.reason)
        self._last_logged_phase = phase

        self.status.active_interface = active_interface
        self.status.target_interface = decision.target_interface
        self.status.last_decision_reason = decision.reason
        self.status.consecutive_cycles = decision.consecutive_cycles
        self.status.hold_down_remaining_s = decision.hold_down_remaining_s

        if decision.should_switch and decision.target_interface:
            self._perform_switch(decision.target_interface, interfaces, now)

        return self.status

    @staticmethod
    def _phase_of(decision) -> str:
        if decision.hold_down_remaining_s > 0.0:
            return "hold_down"
        if decision.should_switch:
            return "switching"
        if decision.consecutive_cycles > 0 and decision.target_interface:
            return f"confirming:{decision.target_interface}"
        if decision.consecutive_cycles > 0:
            return "confirming"
        return "stable_or_no_candidate"

    def _compute_target_metric(self, target_name: str, target_index: int, interfaces: List[InterfaceInfo]) -> int:
        """Derive an ``InterfaceMetric`` for the target interface that is
        guaranteed to make its *effective* metric lower than every other
        currently eligible physical interface's *current* effective
        metric -- without mutating any interface other than the target.

        Only compares against interfaces that are themselves eligible
        physical paths (Ethernet/Wi-Fi, status up) *and* have an actual
        route metric (``RouteController.get_effective_metrics`` already
        excludes interfaces with no IPv4 default route) -- Other/virtual/
        VPN adapters and down/no-route interfaces are never considered,
        so the target metric is never planned relative to a value that
        doesn't reflect a real competing default-route path.
        """
        eligible_interfaces = [
            i for i in interfaces
            if i.if_type in (InterfaceType.ETHERNET, InterfaceType.WIFI) and i.status == InterfaceStatus.UP
        ]
        effective_metrics = self._routes.get_effective_metrics(eligible_interfaces)
        other_metrics = [m for name, m in effective_metrics.items() if name != target_name]
        target_route_metric = self._routes.get_route_metric(target_index) or 0
        if other_metrics:
            return max(1, min(other_metrics) - target_route_metric - 1)
        return _FALLBACK_INTERFACE_METRIC

    def _perform_switch(self, target_name: str, interfaces: List[InterfaceInfo], now: float) -> None:
        target_iface = next((i for i in interfaces if i.name == target_name), None)
        if target_iface is None or target_iface.index is None:
            logger.error("Steering: cannot switch to '%s' -- interface index unavailable", target_name)
            self.status.last_error = f"cannot switch to {target_name}: interface index unavailable"
            return

        if not self._routes.has_operational_ipv4_default_route(target_iface.index):
            logger.error(
                "Steering: refusing to switch to '%s' -- no operational IPv4 default route", target_name
            )
            self.status.last_error = f"refused switch to {target_name}: no operational IPv4 default route"
            return

        # Deterministic failback: never leave more than the current target
        # modified. Any interface other than the new target that still has
        # a saved original setting from a *previous* switch must be fully
        # restored first, so effective metrics are recomputed against
        # genuinely-current values (not a stale, still-pinned prior
        # target) and _saved_settings never accumulates more than one
        # entry. If any of these restores fail, the new switch is aborted
        # entirely -- we never pin a second interface while a prior one
        # remains modified.
        for prev_name in [n for n in self._saved_settings if n != target_name]:
            prev_setting = self._saved_settings[prev_name]
            restore_success, restore_error = self._routes.restore_setting(prev_setting)
            if restore_success:
                logger.info(
                    "Steering: restored previous target '%s' before switching to '%s'",
                    prev_name, target_name,
                )
                del self._saved_settings[prev_name]
            else:
                logger.error(
                    "Steering: FAILED to restore previous target '%s' before switching to '%s': %s; "
                    "aborting new switch to avoid leaving more than one interface modified",
                    prev_name, target_name, restore_error,
                )
                self.status.last_error = (
                    f"cannot switch to {target_name}: failed to restore previous target "
                    f"'{prev_name}' first: {restore_error}. Manual correction required."
                )
                self.status.restored = False
                return
        self.status.restored = True

        original = self._routes.get_ip_setting(target_iface.index)
        if original is None:
            logger.error(
                "Steering: cannot read original IPv4 settings for '%s'; aborting switch", target_name
            )
            self.status.last_error = f"cannot read original settings for {target_name}; switch aborted"
            return

        target_metric = self._compute_target_metric(target_name, target_iface.index, interfaces)

        logger.info(
            "Steering: switching preferred IPv4 path to '%s' (InterfaceMetric -> %d; "
            "saving original AutomaticMetric=%s/InterfaceMetric=%s for restore)",
            target_name, target_metric,
            original.automatic_metric_enabled, original.interface_metric,
        )

        success, error = self._routes.apply_preferred_metric(target_iface.index, target_metric)
        if not success:
            logger.error("Steering: failed to apply preferred metric to '%s': %s", target_name, error)
            self.status.last_error = f"failed to switch to {target_name}: {error}"
            return

        # Only remember this setting for restore once mutation succeeded.
        self._saved_settings[target_name] = original

        verified = self._routes.get_preferred_interface_name() == target_name
        if not verified:
            logger.error(
                "Steering: verification FAILED after switching to '%s' (observed preferred path "
                "did not change as expected); restoring original settings", target_name,
            )
            restore_success, restore_error = self._routes.restore_setting(original)
            self._saved_settings.pop(target_name, None)
            if not restore_success:
                logger.error(
                    "Steering: restore-after-failed-switch ALSO failed for '%s': %s. "
                    "Manual correction required.", target_name, restore_error,
                )
                self.status.last_error = (
                    f"switch to {target_name} failed verification AND restore failed: "
                    f"{restore_error}. Manual correction required -- see log."
                )
                self.status.restored = False
            else:
                logger.info("Steering: original settings for '%s' restored after failed verification", target_name)
                self.status.last_error = (
                    f"switch to {target_name} failed verification; original settings restored"
                )
                self.status.restored = True
            return

        logger.info("Steering: switch to '%s' verified successful", target_name)
        self._policy.record_switch(now)
        self.status.active_interface = target_name
        self.status.last_switch_timestamp = now
        self.status.last_error = None
