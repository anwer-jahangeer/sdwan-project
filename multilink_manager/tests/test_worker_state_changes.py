"""Tests for MonitorWorker's pure, stateless state-change diff helpers
(interface add/remove/status-change, and reachability-change detection).

These are tested directly as module-level functions -- no QThread/QApplication
instantiation is required, so they run on any OS in headless CI.
"""

from __future__ import annotations

from multilink_manager.gui.worker import diff_interface_names, diff_reachability
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo


def _iface(name, status=InterfaceStatus.UP, if_type=InterfaceType.ETHERNET):
    return InterfaceInfo(name=name, friendly_name=name, index=1, if_type=if_type, status=status)


def test_diff_interface_names_detects_added_and_removed():
    previous = {"eth0": _iface("eth0")}
    current = {"eth0": _iface("eth0"), "wifi0": _iface("wifi0", if_type=InterfaceType.WIFI)}
    diff = diff_interface_names(previous, current)
    assert diff["added"] == ["wifi0"]
    assert diff["removed"] == []
    assert diff["status_changed"] == []


def test_diff_interface_names_detects_removed():
    previous = {"eth0": _iface("eth0"), "wifi0": _iface("wifi0")}
    current = {"eth0": _iface("eth0")}
    diff = diff_interface_names(previous, current)
    assert diff["removed"] == ["wifi0"]
    assert diff["added"] == []


def test_diff_interface_names_detects_status_change():
    previous = {"eth0": _iface("eth0", status=InterfaceStatus.UP)}
    current = {"eth0": _iface("eth0", status=InterfaceStatus.DOWN)}
    diff = diff_interface_names(previous, current)
    assert diff["status_changed"] == [("eth0", InterfaceStatus.UP, InterfaceStatus.DOWN)]
    assert diff["added"] == []
    assert diff["removed"] == []


def test_diff_interface_names_no_changes_when_identical():
    previous = {"eth0": _iface("eth0")}
    current = {"eth0": _iface("eth0")}
    diff = diff_interface_names(previous, current)
    assert diff == {"added": [], "removed": [], "status_changed": []}


def test_diff_reachability_detects_transition():
    previous = {"eth0": True}
    current = {"eth0": False}
    changes = diff_reachability(previous, current)
    assert changes == [("eth0", True, False)]


def test_diff_reachability_skips_first_time_observed_interfaces():
    previous = {}
    current = {"eth0": True}
    assert diff_reachability(previous, current) == []


def test_diff_reachability_ignores_unchanged():
    previous = {"eth0": True, "wifi0": None}
    current = {"eth0": True, "wifi0": None}
    assert diff_reachability(previous, current) == []


def test_diff_reachability_detects_unknown_to_known_transition():
    previous = {"eth0": None}
    current = {"eth0": True}
    assert diff_reachability(previous, current) == [("eth0", None, True)]
