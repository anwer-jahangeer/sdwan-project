"""Tests for interface classification (never based on hardcoded names)."""

from __future__ import annotations

import multilink_manager.networking.interfaces as iface_mod
from multilink_manager.models.enums import InterfaceStatus, InterfaceType


class _FakeFamily:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAddr:
    def __init__(self, family_name: str, address: str) -> None:
        self.family = _FakeFamily(family_name)
        self.address = address


class _FakeStats:
    def __init__(self, isup: bool, speed: int = 0) -> None:
        self.isup = isup
        self.speed = speed
        self.duplex = None
        self.mtu = 1500
        self.flags = ""


def test_classify_ethernet_from_windows_metadata(monkeypatch):
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)

    def fake_run_ps(cmd, timeout=8.0):
        if "Get-NetAdapter" in cmd:
            return [{
                "Name": "AdapterA", "InterfaceIndex": 1, "InterfaceDescription": "Some NIC",
                "MediaType": "802.3", "PhysicalMediaType": "802.3", "Status": "Up",
                "MacAddress": "00-11-22-33-44-55", "LinkSpeed": "1 Gbps",
            }]
        if "Get-NetRoute" in cmd:
            return [{"ifIndex": 1, "DestinationPrefix": "0.0.0.0/0",
                      "NextHop": "192.168.1.1", "RouteMetric": 25}]
        if "Get-NetConnectionProfile" in cmd:
            return [{"InterfaceIndex": 1, "NetworkCategory": "Private"}]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run_ps)
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_addrs",
        lambda: {"AdapterA": [_FakeAddr("AF_INET", "192.168.1.10"),
                               _FakeAddr("AF_LINK", "00:11:22:33:44:55")]},
    )
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_stats",
        lambda: {"AdapterA": _FakeStats(isup=True, speed=0)},
    )

    result = iface_mod.discover_interfaces()
    assert len(result) == 1
    interface = result[0]
    assert interface.if_type == InterfaceType.ETHERNET
    assert interface.classification_source == "windows-netadapter-physicalmediatype"
    assert interface.link_speed_mbps == 1000.0
    assert interface.status == InterfaceStatus.UP
    assert interface.ipv4_gateway == "192.168.1.1"
    assert interface.network_profile == "Private"
    assert interface.ipv4_addresses == ["192.168.1.10"]


def test_classify_wifi_from_windows_metadata(monkeypatch):
    monkeypatch.setattr(iface_mod, "is_windows", lambda: True)

    def fake_run_ps(cmd, timeout=8.0):
        if "Get-NetAdapter" in cmd:
            return [{
                "Name": "AdapterB", "InterfaceIndex": 2, "InterfaceDescription": "Radio thing",
                "MediaType": "Native 802.11", "PhysicalMediaType": "Native 802.11",
                "Status": "Up", "MacAddress": None, "LinkSpeed": "433 Mbps",
            }]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run_ps)
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_addrs",
        lambda: {"AdapterB": [_FakeAddr("AF_INET", "10.0.0.5")]},
    )
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_stats",
        lambda: {"AdapterB": _FakeStats(isup=True, speed=0)},
    )

    result = iface_mod.discover_interfaces()
    assert result[0].if_type == InterfaceType.WIFI
    assert result[0].link_speed_mbps == 433.0


def test_degrades_cleanly_off_windows(monkeypatch):
    """No exception, no invented classification/gateway/profile data."""
    monkeypatch.setattr(iface_mod, "is_windows", lambda: False)
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_addrs",
        lambda: {"eth0": [_FakeAddr("AF_INET", "172.16.0.2")]},
    )
    monkeypatch.setattr(
        iface_mod.psutil, "net_if_stats",
        lambda: {"eth0": _FakeStats(isup=True, speed=100)},
    )

    result = iface_mod.discover_interfaces()
    assert len(result) == 1
    interface = result[0]
    assert interface.if_type in (InterfaceType.OTHER, InterfaceType.UNKNOWN)
    assert interface.classification_source == "no-windows-metadata"
    assert interface.ipv4_gateway is None
    assert interface.network_profile is None
    assert interface.link_speed_mbps == 100.0


def test_get_preferred_interface_returns_none_when_metadata_unavailable(monkeypatch):
    # Simulates both "not on Windows" and "PowerShell call failed" cases,
    # since run_powershell_json returns None in both situations.
    monkeypatch.setattr(iface_mod, "run_powershell_json", lambda cmd, timeout=8.0: None)
    assert iface_mod.get_preferred_ipv4_interface_name() is None


def test_get_preferred_interface_uses_effective_metric_not_route_metric_alone(monkeypatch):
    """Windows selects the default route by RouteMetric + InterfaceMetric.

    Here Ethernet (ifIndex 1) has a *higher* RouteMetric (25) than Wi-Fi
    (ifIndex 2, RouteMetric 5), so a RouteMetric-only comparison would
    incorrectly pick Wi-Fi. But Wi-Fi's InterfaceMetric (50) is high enough
    that its effective metric (5 + 50 = 55) loses to Ethernet's effective
    metric (25 + 5 = 30), so Ethernet must be selected as preferred.
    """

    def fake_run_ps(cmd, timeout=8.0):
        if "Get-NetRoute" in cmd:
            return [
                {"ifIndex": 1, "RouteMetric": 25},
                {"ifIndex": 2, "RouteMetric": 5},
            ]
        if "Get-NetIPInterface" in cmd:
            return [
                {"ifIndex": 1, "InterfaceMetric": 5},
                {"ifIndex": 2, "InterfaceMetric": 50},
            ]
        if "Get-NetAdapter" in cmd:
            return [
                {"Name": "Ethernet", "InterfaceIndex": 1, "InterfaceDescription": "NIC",
                 "MediaType": "802.3", "PhysicalMediaType": "802.3", "Status": "Up",
                 "MacAddress": "00-11-22-33-44-55", "LinkSpeed": "1 Gbps"},
                {"Name": "Wi-Fi", "InterfaceIndex": 2, "InterfaceDescription": "Radio",
                 "MediaType": "Native 802.11", "PhysicalMediaType": "Native 802.11",
                 "Status": "Up", "MacAddress": None, "LinkSpeed": "433 Mbps"},
            ]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run_ps)
    assert iface_mod.get_preferred_ipv4_interface_name() == "Ethernet"


def test_get_preferred_interface_falls_back_to_route_metric_when_interface_metric_missing(monkeypatch):
    """If InterfaceMetric cannot be read for any interface, effective
    metric degrades to RouteMetric alone (interface_metric treated as 0)."""

    def fake_run_ps(cmd, timeout=8.0):
        if "Get-NetRoute" in cmd:
            return [
                {"ifIndex": 1, "RouteMetric": 25},
                {"ifIndex": 2, "RouteMetric": 5},
            ]
        if "Get-NetIPInterface" in cmd:
            return None
        if "Get-NetAdapter" in cmd:
            return [
                {"Name": "Ethernet", "InterfaceIndex": 1, "InterfaceDescription": "NIC",
                 "MediaType": "802.3", "PhysicalMediaType": "802.3", "Status": "Up",
                 "MacAddress": "00-11-22-33-44-55", "LinkSpeed": "1 Gbps"},
                {"Name": "Wi-Fi", "InterfaceIndex": 2, "InterfaceDescription": "Radio",
                 "MediaType": "Native 802.11", "PhysicalMediaType": "Native 802.11",
                 "Status": "Up", "MacAddress": None, "LinkSpeed": "433 Mbps"},
            ]
        return None

    monkeypatch.setattr(iface_mod, "run_powershell_json", fake_run_ps)
    assert iface_mod.get_preferred_ipv4_interface_name() == "Wi-Fi"
