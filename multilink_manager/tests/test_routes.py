"""Tests for RouteController: PowerShell command construction/parsing via
monkeypatched run_powershell_json, mirroring the existing
test_classification.py style. No real PowerShell/route mutation is ever
invoked -- run_powershell_json itself is replaced with a fake."""

from __future__ import annotations

import multilink_manager.networking.interfaces as iface_mod
import multilink_manager.networking.routes as routes_mod
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.steering import OriginalInterfaceSetting
from multilink_manager.networking.routes import RouteController


def _iface(name, index):
    return InterfaceInfo(
        name=name, friendly_name=name, index=index,
        if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP,
    )


def test_off_windows_all_mutations_and_reads_fail_safe(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: False)
    controller = RouteController()

    assert controller.has_operational_ipv4_default_route(1) is False
    assert controller.get_ip_setting(1) is None
    success, error = controller.apply_preferred_metric(1, 5)
    assert success is False
    assert error == "not running on Windows"
    setting = OriginalInterfaceSetting("eth0", 1, True, 25)
    success, error = controller.restore_setting(setting)
    assert success is False


def test_has_operational_ipv4_default_route_true_when_route_present(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)

    def fake_run(cmd, timeout=8.0):
        assert "Get-NetRoute" in cmd
        assert "InterfaceIndex 3" in cmd
        return {"RouteMetric": 25}

    monkeypatch.setattr(routes_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    assert controller.has_operational_ipv4_default_route(3) is True


def test_has_operational_ipv4_default_route_false_when_absent(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    monkeypatch.setattr(routes_mod, "run_powershell_json", lambda cmd, timeout=8.0: None)
    controller = RouteController()
    assert controller.has_operational_ipv4_default_route(3) is False


def test_get_ip_setting_parses_enabled_automatic_metric(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)

    def fake_run(cmd, timeout=8.0):
        assert "Get-NetIPInterface" in cmd
        return {
            "InterfaceAlias": "Ethernet", "ifIndex": 3,
            "InterfaceMetric": 25, "AutomaticMetric": "Enabled",
        }

    monkeypatch.setattr(routes_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    setting = controller.get_ip_setting(3)
    assert setting is not None
    assert setting.interface_name == "Ethernet"
    assert setting.interface_index == 3
    assert setting.automatic_metric_enabled is True
    assert setting.interface_metric == 25


def test_get_ip_setting_returns_none_on_incomplete_data(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    monkeypatch.setattr(routes_mod, "run_powershell_json", lambda cmd, timeout=8.0: {"ifIndex": 3})
    controller = RouteController()
    assert controller.get_ip_setting(3) is None


def test_apply_preferred_metric_success(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)

    captured = {}

    def fake_run(cmd, timeout=8.0):
        captured["cmd"] = cmd
        return {"success": True}

    monkeypatch.setattr(routes_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    success, error = controller.apply_preferred_metric(3, 5)
    assert success is True
    assert error is None
    assert "Set-NetIPInterface" in captured["cmd"]
    assert "InterfaceMetric 5" in captured["cmd"]
    assert "AutomaticMetric Disabled" in captured["cmd"]
    # Never issues a Set-NetRoute mutation -- interface metric only.
    assert "Set-NetRoute" not in captured["cmd"]


def test_apply_preferred_metric_failure_reports_error(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    monkeypatch.setattr(
        routes_mod, "run_powershell_json",
        lambda cmd, timeout=8.0: {"success": False, "error": "Access is denied"},
    )
    controller = RouteController()
    success, error = controller.apply_preferred_metric(3, 5)
    assert success is False
    assert error == "Access is denied"


def test_apply_preferred_metric_no_result_treated_as_failure(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    monkeypatch.setattr(routes_mod, "run_powershell_json", lambda cmd, timeout=8.0: None)
    controller = RouteController()
    success, error = controller.apply_preferred_metric(3, 5)
    assert success is False
    assert error is not None


def test_restore_setting_enabled_reenables_automatic_metric(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    captured = {}

    def fake_run(cmd, timeout=8.0):
        captured["cmd"] = cmd
        return {"success": True}

    monkeypatch.setattr(routes_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    setting = OriginalInterfaceSetting("Ethernet", 3, True, 25)
    success, error = controller.restore_setting(setting)
    assert success is True
    assert "AutomaticMetric Enabled" in captured["cmd"]
    assert "InterfaceMetric" not in captured["cmd"]


def test_restore_setting_disabled_restores_exact_metric(monkeypatch):
    monkeypatch.setattr(routes_mod, "is_windows", lambda: True)
    captured = {}

    def fake_run(cmd, timeout=8.0):
        captured["cmd"] = cmd
        return {"success": True}

    monkeypatch.setattr(routes_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    setting = OriginalInterfaceSetting("Ethernet", 3, False, 25)
    success, error = controller.restore_setting(setting)
    assert success is True
    assert "AutomaticMetric Disabled" in captured["cmd"]
    assert "InterfaceMetric 25" in captured["cmd"]


def test_get_effective_metrics_sums_route_and_interface_metric(monkeypatch):
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)

    def fake_run(cmd, timeout=8.0):
        if "Get-NetRoute" in cmd:
            return [{"ifIndex": 1, "RouteMetric": 25}, {"ifIndex": 2, "RouteMetric": 10}]
        if "Get-NetIPInterface" in cmd:
            return [{"ifIndex": 1, "InterfaceMetric": 5}, {"ifIndex": 2, "InterfaceMetric": 35}]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    metrics = controller.get_effective_metrics(interfaces)
    assert metrics == {"eth0": 30, "wifi0": 45}


def test_get_effective_metrics_excludes_interfaces_without_default_route(monkeypatch):
    """An interface with no IPv4 default route at all must be excluded
    entirely, never defaulted to a fabricated route metric of 0 (which
    would make it look like the most-preferred competitor)."""
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)

    def fake_run(cmd, timeout=8.0):
        if "Get-NetRoute" in cmd:
            # Only eth0 (ifIndex 1) has a default route; wifi0 (ifIndex 2) has none.
            return [{"ifIndex": 1, "RouteMetric": 25}]
        if "Get-NetIPInterface" in cmd:
            return [{"ifIndex": 1, "InterfaceMetric": 5}, {"ifIndex": 2, "InterfaceMetric": 35}]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run)
    controller = RouteController()
    interfaces = [_iface("eth0", 1), _iface("wifi0", 2)]
    metrics = controller.get_effective_metrics(interfaces)
    assert metrics == {"eth0": 30}
    assert "wifi0" not in metrics


def test_get_route_metric_reads_single_interface(monkeypatch):
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)
    monkeypatch.setattr(
        iface_mod, "run_powershell_json",
        lambda cmd, timeout=8.0: [{"ifIndex": 1, "RouteMetric": 25}],
    )
    controller = RouteController()
    assert controller.get_route_metric(1) == 25
    assert controller.get_route_metric(99) is None
