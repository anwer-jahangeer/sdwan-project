"""Tests for SteeringController using a hand-written FakeRouteController
(duck-typed, same method surface as networking.routes.RouteController) so
no real PowerShell mutation is ever issued. Covers: admin/Windows gating,
successful switch (save+apply+verify), failed apply (no save), failed
verification (rollback/restore), disable restoring all settings, and a
restore-failure surfacing case."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import multilink_manager.networking.interfaces as iface_mod
import multilink_manager.steering.controller as controller_mod
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.score import ScoreResult
from multilink_manager.models.steering import OriginalInterfaceSetting, SteeringConfig
from multilink_manager.networking.routes import RouteController
from multilink_manager.steering.controller import SteeringController


def _iface(name, index, gateway="192.168.1.1", if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP):
    return InterfaceInfo(
        name=name, friendly_name=name, index=index,
        if_type=if_type, status=status, ipv4_gateway=gateway,
    )


def _score(name, score, reachable=True):
    return ScoreResult(
        interface_name=name, timestamp=0.0, score=score, reachable=reachable,
        loss_pct=0.0, latency_ms=10.0, jitter_ms=1.0,
    )


class FakeRouteController:
    """Duck-typed stand-in for networking.routes.RouteController. Records
    every mutation attempted so tests can assert on exactly what would
    have been sent to Windows, without ever touching real PowerShell."""

    def __init__(self):
        self.effective_metrics: Dict[str, int] = {}
        self.route_metrics: Dict[int, int] = {}
        self.default_routes: Dict[int, bool] = {}
        self.ip_settings: Dict[int, OriginalInterfaceSetting] = {}
        self.preferred_name: Optional[str] = None
        self.apply_result: Tuple[bool, Optional[str]] = (True, None)
        self.verify_after_apply: Optional[str] = None
        self.restore_result: Tuple[bool, Optional[str]] = (True, None)
        self.applied_calls: List[Tuple[int, int]] = []
        self.restored_calls: List[OriginalInterfaceSetting] = []

    def get_effective_metrics(self, interfaces):
        return dict(self.effective_metrics)

    def get_route_metric(self, interface_index):
        return self.route_metrics.get(interface_index)

    def get_preferred_interface_name(self):
        return self.preferred_name

    def has_operational_ipv4_default_route(self, interface_index):
        return self.default_routes.get(interface_index, False)

    def get_ip_setting(self, interface_index):
        return self.ip_settings.get(interface_index)

    def apply_preferred_metric(self, interface_index, metric):
        self.applied_calls.append((interface_index, metric))
        success, error = self.apply_result
        if success and self.verify_after_apply is not None:
            self.preferred_name = self.verify_after_apply
        return success, error

    def restore_setting(self, setting):
        self.restored_calls.append(setting)
        return self.restore_result


def _enable(fake, config=None, monkeypatch=None):
    controller = SteeringController(route_controller=fake)
    monkeypatch.setattr(controller_mod, "is_windows", lambda: True)
    monkeypatch.setattr(controller_mod, "is_admin", lambda: True)
    ok, msg = controller.enable(config)
    assert ok is True
    return controller


def test_enable_refused_without_windows(monkeypatch):
    fake = FakeRouteController()
    controller = SteeringController(route_controller=fake)
    monkeypatch.setattr(controller_mod, "is_windows", lambda: False)
    monkeypatch.setattr(controller_mod, "is_admin", lambda: True)
    ok, msg = controller.enable()
    assert ok is False
    assert controller.enabled is False
    assert "Windows" in msg


def test_enable_refused_without_admin(monkeypatch):
    fake = FakeRouteController()
    controller = SteeringController(route_controller=fake)
    monkeypatch.setattr(controller_mod, "is_windows", lambda: True)
    monkeypatch.setattr(controller_mod, "is_admin", lambda: False)
    ok, msg = controller.enable()
    assert ok is False
    assert controller.enabled is False
    assert "Administrator" in msg


def test_successful_switch_saves_applies_and_verifies(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.effective_metrics = {"eth0": 30}
    fake.route_metrics = {2: 20}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [
        _iface("eth0", 1),
        _iface("wifi0", 2),
    ]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    assert status.target_interface == "wifi0"
    assert fake.applied_calls, "expected apply_preferred_metric to have been called"
    assert status.active_interface == "wifi0"
    assert status.last_error is None
    assert "wifi0" in controller._saved_settings


def test_failed_apply_does_not_save_setting(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.apply_result = (False, "Access is denied")

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    assert "wifi0" not in controller._saved_settings
    assert status.last_error is not None
    assert "Access is denied" in status.last_error


def test_failed_verification_rolls_back(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.preferred_name = "eth0"  # verification will observe no change
    fake.apply_result = (True, None)
    fake.restore_result = (True, None)

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    assert len(fake.restored_calls) == 1
    assert "wifi0" not in controller._saved_settings
    assert "verification" in status.last_error
    assert status.restored is True


def test_switch_refused_without_operational_default_route(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: False}  # wifi0 has no default route

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    # wifi0 is excluded as a candidate entirely (no operational default
    # route), so no switch is even attempted -- no PowerShell mutation
    # call, no target chosen, no saved setting.
    assert not fake.applied_calls
    assert status.target_interface is None
    assert "wifi0" not in controller._saved_settings


def test_disable_restores_all_saved_settings(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.effective_metrics = {"eth0": 30}
    fake.route_metrics = {2: 20}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    controller.tick(interfaces, scores, active_interface="eth0")
    assert "wifi0" in controller._saved_settings

    controller.disable()
    assert controller.enabled is False
    assert len(fake.restored_calls) == 1
    assert controller._saved_settings == {}
    assert controller.status.restored is True


def test_disable_surfaces_restore_failure(monkeypatch):
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.effective_metrics = {"eth0": 30}
    fake.route_metrics = {2: 20}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    controller.tick(interfaces, scores, active_interface="eth0")
    assert "wifi0" in controller._saved_settings

    fake.restore_result = (False, "Access is denied")
    controller.disable()

    assert controller.status.restored is False
    assert controller.status.last_error is not None
    assert "wifi0" in controller._saved_settings  # not cleared on failure


def test_disable_idempotent_when_never_enabled():
    fake = FakeRouteController()
    controller = SteeringController(route_controller=fake)
    controller.disable()  # must not raise
    assert controller.enabled is False
    assert fake.restored_calls == []


def test_two_switches_restore_previous_target_before_applying_new(monkeypatch):
    """wifi0 -> eth0 failback must restore wifi0's original setting BEFORE
    applying eth0's, leave only eth0 in _saved_settings afterward (never
    both pinned at once), and disable() must then restore eth0 cleanly."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    wifi0_original = OriginalInterfaceSetting("wifi0", 2, True, 35)
    eth0_original = OriginalInterfaceSetting("eth0", 1, True, 25)
    fake.ip_settings = {1: eth0_original, 2: wifi0_original}
    fake.effective_metrics = {"eth0": 30}
    fake.route_metrics = {1: 20, 2: 20}

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0, hold_down_seconds=0.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]

    # First switch: eth0 (unhealthy) -> wifi0 (healthy candidate).
    fake.verify_after_apply = "wifi0"
    scores_1 = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    status_1 = controller.tick(interfaces, scores_1, active_interface="eth0")
    assert status_1.active_interface == "wifi0"
    assert list(controller._saved_settings.keys()) == ["wifi0"]
    assert not fake.restored_calls  # nothing to restore yet on the very first switch

    # Second switch: wifi0 (now unhealthy) -> eth0 (now the healthy candidate).
    fake.effective_metrics = {"wifi0": 55}  # eth0 no longer artificially pinned once restored
    fake.verify_after_apply = "eth0"
    scores_2 = {
        "eth0": _score("eth0", 90.0, reachable=True),
        "wifi0": _score("wifi0", 15.0, reachable=False),
    }
    status_2 = controller.tick(interfaces, scores_2, active_interface="wifi0")

    # wifi0's original setting must have been restored BEFORE eth0 was applied.
    assert wifi0_original in fake.restored_calls
    assert fake.restored_calls.index(wifi0_original) == 0

    assert status_2.active_interface == "eth0"
    # At most the current target remains saved -- never both at once.
    assert controller._saved_settings == {"eth0": eth0_original}
    assert "wifi0" not in controller._saved_settings

    # disable() must restore exactly the remaining (eth0) setting cleanly.
    controller.disable()
    assert controller._saved_settings == {}
    assert controller.status.restored is True
    assert fake.restored_calls[-1] == eth0_original


def test_two_switches_aborts_when_previous_restore_fails(monkeypatch):
    """If restoring the previous target fails, the new switch must be
    aborted entirely -- never pin a second interface while the first one
    remains modified."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    wifi0_original = OriginalInterfaceSetting("wifi0", 2, True, 35)
    eth0_original = OriginalInterfaceSetting("eth0", 1, True, 25)
    fake.ip_settings = {1: eth0_original, 2: wifi0_original}
    fake.effective_metrics = {"eth0": 30}
    fake.route_metrics = {1: 20, 2: 20}

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0, hold_down_seconds=0.0)
    controller = _enable(fake, config, monkeypatch)
    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]

    fake.verify_after_apply = "wifi0"
    scores_1 = {
        "eth0": _score("eth0", 20.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    controller.tick(interfaces, scores_1, active_interface="eth0")
    assert list(controller._saved_settings.keys()) == ["wifi0"]

    fake.restore_result = (False, "Access is denied")
    scores_2 = {
        "eth0": _score("eth0", 90.0, reachable=True),
        "wifi0": _score("wifi0", 15.0, reachable=False),
    }
    status_2 = controller.tick(interfaces, scores_2, active_interface="wifi0")

    # eth0 must never have been applied -- only the failed restore attempt happened.
    applied_indices = [idx for idx, _metric in fake.applied_calls]
    assert 1 not in applied_indices
    assert controller._saved_settings == {"wifi0": wifi0_original}
    assert status_2.restored is False
    assert status_2.last_error is not None
    assert "wifi0" in status_2.last_error


def test_compute_target_metric_excludes_other_down_and_routeless_interfaces(monkeypatch):
    """_compute_target_metric must only compare against eligible
    (Ethernet/Wi-Fi, status up) interfaces that actually have a route
    metric -- Other/virtual and down interfaces must never influence the
    computed target metric, even if they happen to have a very low
    InterfaceMetric/RouteMetric of their own. Uses the REAL RouteController
    (not the fake) with monkeypatched PowerShell so the full
    get_effective_metrics() filtering integration is exercised, not just
    the controller's own orchestration."""
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)

    def fake_run(cmd, timeout=8.0):
        if "Get-NetRoute" in cmd:
            # eth0 (1) RouteMetric=25, wifi0 (2) RouteMetric=5,
            # vpn0 (3, Other) and lan_down (4, down Ethernet) each have a
            # very low RouteMetric of 1 -- if incorrectly considered
            # eligible, they would dominate the target-metric calculation.
            return [
                {"ifIndex": 1, "RouteMetric": 25}, {"ifIndex": 2, "RouteMetric": 5},
                {"ifIndex": 3, "RouteMetric": 1}, {"ifIndex": 4, "RouteMetric": 1},
            ]
        if "Get-NetIPInterface" in cmd:
            return [
                {"ifIndex": 1, "InterfaceMetric": 5}, {"ifIndex": 2, "InterfaceMetric": 25},
                {"ifIndex": 3, "InterfaceMetric": 1}, {"ifIndex": 4, "InterfaceMetric": 1},
            ]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run)

    real_routes = RouteController()
    controller = SteeringController(route_controller=real_routes)

    interfaces = [
        _iface("eth0", 1, if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP),
        _iface("wifi0", 2, if_type=InterfaceType.WIFI, status=InterfaceStatus.UP),
        _iface("vpn0", 3, if_type=InterfaceType.OTHER, status=InterfaceStatus.UP),
        _iface("lan_down", 4, if_type=InterfaceType.ETHERNET, status=InterfaceStatus.DOWN),
    ]
    metric = controller._compute_target_metric("eth0", 1, interfaces)

    # Only wifi0 (effective metric 5+25=30) may be considered. eth0's own
    # RouteMetric is 25, so the target InterfaceMetric must make eth0's
    # effective metric strictly below 30: max(1, 30 - 25 - 1) = 4. If
    # vpn0/lan_down (effective metric 1+1=2 each) were incorrectly
    # considered, the result would instead collapse to 1.
    assert metric == 4


def test_candidate_with_missing_index_can_never_have_default_route(monkeypatch):
    """A candidate interface with index=None must never be considered to
    have a default route, and therefore can never be selected as a
    steering target, regardless of a configured gateway."""
    fake = FakeRouteController()
    fake.default_routes = {1: True}

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [
        _iface("eth0", 1),
        InterfaceInfo(
            name="wifi0", friendly_name="wifi0", index=None,
            if_type=InterfaceType.WIFI, status=InterfaceStatus.UP, ipv4_gateway="192.168.1.1",
        ),
    ]
    scores = {
        "eth0": _score("eth0", 10.0, reachable=False),  # unhealthy active
        "wifi0": _score("wifi0", 99.0, reachable=True),  # otherwise-perfect candidate
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    assert not fake.applied_calls
    assert status.target_interface is None
    assert "wifi0" not in controller._saved_settings


def test_active_vpn_or_other_preferred_path_skips_steering(monkeypatch):
    """If the currently observed preferred path is not an eligible
    physical Ethernet/Wi-Fi interface (e.g. an active VPN/virtual/Other
    adapter), steering must refuse to act at all this tick, even with an
    excellent, healthy physical candidate available -- lowering a
    physical interface's metric could otherwise inadvertently bypass the
    VPN/virtual path's own default route."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 5: True}

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [
        _iface("eth0", 1, if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP),
        _iface("vpn0", 5, if_type=InterfaceType.OTHER, status=InterfaceStatus.UP),
    ]
    scores = {
        "eth0": _score("eth0", 99.0, reachable=True),
        "vpn0": _score("vpn0", 50.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="vpn0")

    assert not fake.applied_calls
    assert status.target_interface is None
    assert "not an eligible physical" in status.last_decision_reason
    assert "eth0" not in controller._saved_settings


def test_active_interface_none_still_allows_normal_selection(monkeypatch):
    """An active_interface of None (no currently observed preferred path)
    must NOT be treated as an ineligible VPN/Other guard case -- normal
    N-cycle candidate selection still applies."""
    fake = FakeRouteController()
    fake.default_routes = {1: True}
    fake.ip_settings = {1: OriginalInterfaceSetting("eth0", 1, True, 25)}
    fake.verify_after_apply = "eth0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1, if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP)]
    scores = {"eth0": _score("eth0", 80.0, reachable=True)}
    status = controller.tick(interfaces, scores, active_interface=None)

    assert status.target_interface == "eth0"
    assert fake.applied_calls


def test_reenable_refused_when_previous_restore_left_settings_modified(monkeypatch):
    """If a previous disable/restore attempt failed and _saved_settings
    remains nonempty, re-enabling must be refused until the leftover
    setting is resolved -- steering must never pin a *second* interface
    on top of one that failed to restore."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    wifi0_original = OriginalInterfaceSetting("wifi0", 2, True, 35)
    fake.ip_settings = {2: wifi0_original}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)
    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 10.0, reachable=False),
        "wifi0": _score("wifi0", 90.0, reachable=True),
    }
    controller.tick(interfaces, scores, active_interface="eth0")
    assert controller._saved_settings == {"wifi0": wifi0_original}

    # disable() fails to restore -- leftover modified setting remains.
    fake.restore_result = (False, "Access is denied")
    controller.disable()
    assert controller._saved_settings == {"wifi0": wifi0_original}
    assert controller.status.restored is False

    # Re-enable must now be refused, preserving restored=False and a
    # prominent error, without touching _saved_settings.
    ok, msg = controller.enable(config)
    assert ok is False
    assert controller.enabled is False
    assert controller.status.restored is False
    assert controller.status.last_error is not None
    assert "wifi0" in controller.status.last_error
    assert controller._saved_settings == {"wifi0": wifi0_original}


def test_deselected_interface_never_becomes_steering_candidate(monkeypatch):
    """A deselected (app-level, not OS-level) interface must never be
    selected as a switch target, no matter how much better its score is,
    when its name is excluded from ``enabled_names``."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 10.0, reachable=False),  # confirmed unhealthy
        "wifi0": _score("wifi0", 95.0, reachable=True),  # would otherwise clearly win
    }
    # wifi0 is deselected in the GUI -- never a candidate even though it
    # is the only healthy, reachable, high-scoring option.
    status = controller.tick(
        interfaces, scores, active_interface="eth0", enabled_names={"eth0"},
    )

    assert status.target_interface is None
    assert not fake.applied_calls
    assert "no eligible" in status.last_decision_reason


def test_enabled_names_none_allows_every_interface_as_candidate(monkeypatch):
    """Passing enabled_names=None (the default) must behave exactly as
    before this feature existed -- every interface remains a candidate."""
    fake = FakeRouteController()
    fake.default_routes = {1: True, 2: True}
    fake.ip_settings = {2: OriginalInterfaceSetting("wifi0", 2, True, 35)}
    fake.verify_after_apply = "wifi0"

    config = SteeringConfig(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    controller = _enable(fake, config, monkeypatch)

    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    scores = {
        "eth0": _score("eth0", 10.0, reachable=False),
        "wifi0": _score("wifi0", 95.0, reachable=True),
    }
    status = controller.tick(interfaces, scores, active_interface="eth0")

    assert status.target_interface == "wifi0"
    assert fake.applied_calls
