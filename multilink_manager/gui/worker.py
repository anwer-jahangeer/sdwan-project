"""Background QThread worker that gathers one snapshot per tick.

Runs all blocking/system work (interface discovery, counter reads,
connection enumeration, probe polling) off the GUI thread, then emits a
single ``Snapshot`` via a Qt signal for the main window to render. Probing
itself runs on its own independent background thread pool inside
``LinkProber`` at its own cadence, decoupled from the GUI refresh interval.

Logging policy: interface add/remove/status changes and per-interface
reachability changes are logged at INFO (bounded -- once per actual
transition, never every tick) so operators can see meaningful history
without flooding logs; raw per-tick measurements are logged at DEBUG only.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from multilink_manager.models.connection import ConnectionInfo
from multilink_manager.models.history import HistoryRecord
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.probe import ProbeResult
from multilink_manager.models.score import ScoreResult
from multilink_manager.models.steering import SteeringConfig, SteeringStatus
from multilink_manager.models.traffic import CounterSample, DistributionEntry, RateSample
from multilink_manager.monitoring.connections import list_connections
from multilink_manager.monitoring.counters import CounterMonitor, read_counter_samples
from multilink_manager.monitoring.distribution import (
    compute_distribution,
    compute_distribution_by_type,
)
from multilink_manager.networking.interfaces import (
    discover_interfaces,
    get_preferred_ipv4_interface_name,
)
from multilink_manager.networking.probing import DEFAULT_PUBLIC_TARGET, LinkProber
from multilink_manager.scoring.scorer import compute_score
from multilink_manager.steering.controller import SteeringController
from multilink_manager.storage.history_store import HistoryStore
from multilink_manager.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Snapshot:
    timestamp: float
    interfaces: List[InterfaceInfo]
    rates: Dict[str, RateSample]
    counter_samples: Dict[str, CounterSample]
    distribution: Dict[str, DistributionEntry]
    type_distribution: Dict[str, DistributionEntry]
    connections: List[ConnectionInfo]
    probes: Dict[str, Dict[str, ProbeResult]]
    scores: Dict[str, ScoreResult]
    target_scores: Dict[str, Dict[str, ScoreResult]] = field(default_factory=dict)
    primary_target: Dict[str, Optional[str]] = field(default_factory=dict)
    preferred_interface: Optional[str] = None
    steering_status: Optional[SteeringStatus] = None


def diff_interface_names(
    previous: Dict[str, InterfaceInfo], current: Dict[str, InterfaceInfo]
) -> Dict[str, list]:
    """Pure helper (easily unit tested) that computes interface-level
    changes between two ticks: additions, removals, and status changes.

    Returns ``{"added": [name, ...], "removed": [name, ...],
    "status_changed": [(name, old_status, new_status), ...]}``.
    """
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    status_changed = []
    for name in sorted(set(current) & set(previous)):
        old_status = previous[name].status
        new_status = current[name].status
        if old_status != new_status:
            status_changed.append((name, old_status, new_status))
    return {"added": added, "removed": removed, "status_changed": status_changed}


def diff_reachability(
    previous: Dict[str, Optional[bool]], current: Dict[str, Optional[bool]]
) -> List[Tuple[str, Optional[bool], Optional[bool]]]:
    """Pure helper (easily unit tested) that returns
    ``[(name, old_reachable, new_reachable), ...]`` for every interface
    whose reachability changed since the previous tick.

    Interfaces not present in ``previous`` (first observation) are
    intentionally skipped here -- their appearance is already logged via
    ``diff_interface_names``, so this only reports genuine transitions.
    """
    changes = []
    for name, new in current.items():
        if name in previous and previous[name] != new:
            changes.append((name, previous[name], new))
    return changes


class MonitorWorker(QThread):
    """QThread subclass; never touch GUI widgets directly from here."""

    snapshot_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self,
        history_store: HistoryStore,
        interval_s: float = 2.0,
        probe_interval_s: float = 5.0,
        public_target: str = DEFAULT_PUBLIC_TARGET,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.interval_s = interval_s
        self.history_store = history_store
        self._counter_monitor = CounterMonitor()
        self._stop_event = threading.Event()
        self._latest_interfaces: List[InterfaceInfo] = []
        self._prober = LinkProber(
            self._get_latest_interfaces,
            interval_s=probe_interval_s,
            public_target=public_target,
        )
        # State tracked across ticks purely for change-detection logging.
        self._previous_interfaces_by_name: Dict[str, InterfaceInfo] = {}
        self._previous_reachability: Dict[str, Optional[bool]] = {}

        # Opt-in automatic steering (disabled by default). Enable/disable
        # requests come from the GUI thread and are only *applied* here, at
        # the start of the next tick on this worker's own background
        # thread, so no PowerShell mutation command from steering ever runs
        # on the GUI thread.
        self._steering = SteeringController()
        self._steering_request_lock = threading.Lock()
        self._pending_steering_request: Optional[Tuple[str, Optional[SteeringConfig]]] = None

    def _get_latest_interfaces(self) -> List[InterfaceInfo]:
        return self._latest_interfaces

    def set_interval(self, interval_s: float) -> None:
        self.interval_s = max(0.5, interval_s)

    def request_stop(self) -> None:
        self._stop_event.set()

    def request_enable_steering(self, config: SteeringConfig) -> None:
        """Thread-safe: schedule automatic steering to be enabled at the
        start of the next tick (on this worker's own thread)."""
        with self._steering_request_lock:
            self._pending_steering_request = ("enable", config)

    def request_disable_steering(self) -> None:
        """Thread-safe: schedule automatic steering to be disabled (and any
        changed settings restored) at the start of the next tick."""
        with self._steering_request_lock:
            self._pending_steering_request = ("disable", None)

    @property
    def steering_status(self) -> SteeringStatus:
        """Safe to read after the thread has stopped (e.g. right after
        ``QThread.wait()`` returns in the GUI's ``stop_monitoring``) to
        confirm whether restore-on-stop succeeded."""
        return self._steering.status

    def _process_pending_steering_request(self) -> None:
        with self._steering_request_lock:
            request = self._pending_steering_request
            self._pending_steering_request = None
        if request is None:
            return
        action, config = request
        if action == "enable":
            success, message = self._steering.enable(config)
            if not success:
                self.error_occurred.emit(f"Automatic steering not enabled: {message}")
        elif action == "disable":
            self._steering.disable()

    def run(self) -> None:  # noqa: D102 (Qt override)
        logger.info("MonitorWorker starting (public_target=%s)", self._prober.public_target)
        self._prober.start()
        try:
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception("Monitor tick failed")
                    self.error_occurred.emit(str(exc))
                self._stop_event.wait(self.interval_s)
        finally:
            self._prober.stop()
            # Unconditionally attempt to restore any steering-changed
            # settings before this QThread's run() returns -- this is the
            # guarantee that stopping monitoring (or closing the app, which
            # calls stop_monitoring) never leaves a mutated IPv4 interface
            # metric in place. disable() logs internally and is a safe
            # no-op if steering was never enabled and nothing was changed.
            self._steering.disable()
            logger.info("MonitorWorker stopped")

    def _log_interface_changes(self, current_by_name: Dict[str, InterfaceInfo]) -> None:
        diff = diff_interface_names(self._previous_interfaces_by_name, current_by_name)
        for name in diff["added"]:
            iface = current_by_name[name]
            logger.info(
                "Interface appeared: %s (type=%s, status=%s)",
                name, iface.if_type.value, iface.status.value,
            )
        for name in diff["removed"]:
            logger.info("Interface disappeared: %s", name)
        for name, old_status, new_status in diff["status_changed"]:
            logger.info(
                "Interface status changed: %s (%s -> %s)",
                name, old_status.value, new_status.value,
            )
        self._previous_interfaces_by_name = current_by_name

    def _log_reachability_changes(self, current: Dict[str, Optional[bool]]) -> None:
        for name, old, new in diff_reachability(self._previous_reachability, current):
            logger.info("Interface reachability changed: %s (%s -> %s)", name, old, new)
        self._previous_reachability = current

    def _tick(self) -> None:
        self._process_pending_steering_request()

        interfaces = discover_interfaces()
        current_by_name = {i.name: i for i in interfaces}
        self._log_interface_changes(current_by_name)
        self._latest_interfaces = interfaces
        preferred = get_preferred_ipv4_interface_name()

        samples = read_counter_samples()
        rates = self._counter_monitor.update(samples)
        distribution = compute_distribution(rates.values())
        type_distribution = compute_distribution_by_type(rates.values(), interfaces)
        connections = list_connections(interfaces)
        probes = self._prober.get_results()

        now = time.time()
        scores: Dict[str, ScoreResult] = {}
        target_scores: Dict[str, Dict[str, ScoreResult]] = {}
        primary_target: Dict[str, Optional[str]] = {}
        reachability_now: Dict[str, Optional[bool]] = {}
        history_records = []

        for iface in interfaces:
            name = iface.name
            rate = rates.get(name)
            iface_probes = probes.get(name, {})

            # Score every target row independently so Link Health can show
            # a correct, target-specific score per row instead of reusing
            # one interface-wide value on both the gateway and public rows.
            row_scores = {
                target_type: compute_score(probe)
                for target_type, probe in iface_probes.items()
            }
            if row_scores:
                target_scores[name] = row_scores

            # The "primary" probe/score used for history and the headline
            # per-interface score consistently prefers the public target,
            # falling back to the gateway target when public is missing.
            if "public" in iface_probes:
                primary_type = "public"
            elif "gateway" in iface_probes:
                primary_type = "gateway"
            else:
                primary_type = None
            primary_target[name] = primary_type
            primary_probe = iface_probes.get(primary_type) if primary_type else None
            primary_score = row_scores.get(primary_type) if primary_type else None
            if primary_score is not None:
                scores[name] = primary_score

            reachability_now[name] = primary_probe.reachable if primary_probe else None

            if rate is not None and not rate.is_first_sample:
                history_records.append(
                    HistoryRecord(
                        timestamp=now,
                        interface_name=name,
                        rx_mbps=rate.rx_mbps,
                        tx_mbps=rate.tx_mbps,
                        rx_bytes=rate.rx_bytes_delta,
                        tx_bytes=rate.tx_bytes_delta,
                        latency_ms=primary_probe.rtt_ms if primary_probe else None,
                        loss_pct=primary_probe.loss_pct if primary_probe else None,
                        jitter_ms=primary_probe.jitter_ms if primary_probe else None,
                        score=primary_score.score if primary_score else None,
                    )
                )

            logger.debug(
                "measurement interface=%s rx_mbps=%.3f tx_mbps=%.3f rx_pps=%.1f tx_pps=%.1f "
                "rtt_ms=%s loss_pct=%s jitter_ms=%s score=%s",
                name,
                rate.rx_mbps if rate else 0.0,
                rate.tx_mbps if rate else 0.0,
                rate.rx_pps if rate else 0.0,
                rate.tx_pps if rate else 0.0,
                primary_probe.rtt_ms if primary_probe else None,
                primary_probe.loss_pct if primary_probe else None,
                primary_probe.jitter_ms if primary_probe else None,
                primary_score.score if primary_score else None,
            )

        self._log_reachability_changes(reachability_now)

        if history_records:
            self.history_store.add_many(history_records)

        steering_status = self._steering.tick(interfaces, scores, active_interface=preferred)

        snapshot = Snapshot(
            timestamp=now,
            interfaces=interfaces,
            rates=rates,
            counter_samples=samples,
            distribution=distribution,
            type_distribution=type_distribution,
            connections=connections,
            probes=probes,
            scores=scores,
            target_scores=target_scores,
            primary_target=primary_target,
            preferred_interface=preferred,
            steering_status=steering_status,
        )
        self.snapshot_ready.emit(snapshot)
