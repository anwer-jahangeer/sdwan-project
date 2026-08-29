"""Typed dataclasses for the opt-in automatic active/backup IPv4
default-route steering feature (v0.2-style extension, disabled by default).

Pure data only -- no PowerShell/OS calls and no Qt/GUI imports live here.
See ``multilink_manager/networking/routes.py`` for the Windows route/metric
mutation layer and ``multilink_manager/steering/`` for the decision logic
that uses these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Stable policy defaults, as required: at least 3 consecutive eligible
# health cycles before acting, a >=10 point score advantage (hysteresis)
# to switch away from a *healthy* current path, a 30s hold-down after any
# switch to prevent flapping, and a primary-target score below 40.0 is
# treated as "unhealthy" (grounds to switch without needing the full
# hysteresis margin, still subject to the same consecutive-cycle
# confirmation). See ``steering/policy.py`` for the full algorithm and the
# README "Automatic failover (opt-in)" section for the documented
# rationale.
DEFAULT_MIN_CONSECUTIVE_CYCLES = 3
DEFAULT_SCORE_ADVANTAGE_THRESHOLD = 10.0
DEFAULT_HOLD_DOWN_SECONDS = 30.0
DEFAULT_UNHEALTHY_SCORE_THRESHOLD = 40.0


@dataclass(frozen=True)
class SteeringConfig:
    """Tunable steering policy parameters, configurable from the GUI at
    Enable time (see ``gui/main_window.py``'s Steering tab)."""

    min_consecutive_cycles: int = DEFAULT_MIN_CONSECUTIVE_CYCLES
    score_advantage_threshold: float = DEFAULT_SCORE_ADVANTAGE_THRESHOLD
    hold_down_seconds: float = DEFAULT_HOLD_DOWN_SECONDS
    unhealthy_score_threshold: float = DEFAULT_UNHEALTHY_SCORE_THRESHOLD


@dataclass(frozen=True)
class CandidateHealth:
    """Per-tick eligibility snapshot for one interface, resolved by the
    caller (``steering/controller.py``) from ``Snapshot`` data.

    ``SteeringPolicy`` has no knowledge of scoring internals, probes, or
    OS APIs -- this is the *only* input it sees, which is what makes it
    fully unit-testable without mocking any OS/PowerShell/psutil call.
    """

    interface_name: str
    score: Optional[float]
    reachable: Optional[bool]
    is_eligible_physical: bool
    has_default_route: bool


@dataclass
class SteeringDecision:
    """One tick's output from ``SteeringPolicy.decide()``."""

    should_switch: bool
    target_interface: Optional[str]
    reason: str
    consecutive_cycles: int
    hold_down_remaining_s: float


@dataclass
class OriginalInterfaceSetting:
    """Snapshot of one interface's IPv4 metric settings captured before
    this application mutates them, so they can be restored exactly.

    ``automatic_metric_enabled`` mirrors Windows' ``Get-NetIPInterface``
    ``AutomaticMetric`` property (Enabled/Disabled). When restoring, if it
    was originally ``Enabled``, restoration simply re-enables automatic
    metric computation (Windows recomputes ``InterfaceMetric`` itself);
    otherwise the exact original ``interface_metric`` value is restored.
    """

    interface_name: str
    interface_index: int
    automatic_metric_enabled: bool
    interface_metric: int


@dataclass
class SteeringStatus:
    """Presentational, GUI-facing snapshot of steering state, carried on
    ``Snapshot.steering_status`` each tick so the GUI never needs to query
    ``SteeringController`` directly from a different thread."""

    enabled: bool = False
    active_interface: Optional[str] = None
    target_interface: Optional[str] = None
    last_decision_reason: str = "steering disabled"
    consecutive_cycles: int = 0
    hold_down_remaining_s: float = 0.0
    last_switch_timestamp: Optional[float] = None
    last_error: Optional[str] = None
    restored: bool = True
