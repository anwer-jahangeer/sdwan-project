"""Tests for per-interface monitoring selection (enable/disable).

Covers: default classification-based selection, explicit user overrides,
override retention across interface disappearance/reappearance,
bulk 'select physical defaults'/'deselect all' operations, and the pure
filtering helpers used to exclude deselected interfaces' data from
traffic/distribution/connections display.

All tests here are pure (no Qt, no QThread, no OS calls) and run on any
platform.
"""

from __future__ import annotations

from multilink_manager.models.connection import ConnectionInfo
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.monitoring.distribution import compute_distribution
from multilink_manager.monitoring.selection import (
    InterfaceSelectionManager,
    default_enabled_for_type,
    filter_connections_for_display,
    filter_enabled_interfaces,
    resolve_enabled_map,
    visible_interfaces_for_default_view,
)
from multilink_manager.models.traffic import RateSample


def _iface(name: str, if_type: InterfaceType, status: InterfaceStatus = InterfaceStatus.UP) -> InterfaceInfo:
    return InterfaceInfo(name=name, friendly_name=name, index=1, if_type=if_type, status=status)


def _rate(name: str, rx_bytes: int, tx_bytes: int) -> RateSample:
    return RateSample(
        interface_name=name, timestamp=0.0, interval_s=1.0,
        rx_bytes_delta=rx_bytes, tx_bytes_delta=tx_bytes,
        rx_packets_delta=0, tx_packets_delta=0,
        rx_errors_delta=0, tx_errors_delta=0,
        rx_discards_delta=0, tx_discards_delta=0,
        rx_mbps=0.0, tx_mbps=0.0, rx_pps=0.0, tx_pps=0.0,
        is_first_sample=False,
    )


# ----------------------------------------------------------------------
# Default classification-based selection
# ----------------------------------------------------------------------

def test_default_enabled_for_ethernet_and_wifi():
    assert default_enabled_for_type(InterfaceType.ETHERNET) is True
    assert default_enabled_for_type(InterfaceType.WIFI) is True


def test_default_disabled_for_other_and_unknown():
    assert default_enabled_for_type(InterfaceType.OTHER) is False
    assert default_enabled_for_type(InterfaceType.UNKNOWN) is False


def test_resolve_enabled_map_uses_type_defaults_with_no_overrides():
    interfaces = [
        _iface("eth0", InterfaceType.ETHERNET),
        _iface("wifi0", InterfaceType.WIFI),
        _iface("vpn0", InterfaceType.OTHER),
        _iface("mystery0", InterfaceType.UNKNOWN),
    ]
    resolved = resolve_enabled_map(interfaces, overrides={})
    assert resolved == {"eth0": True, "wifi0": True, "vpn0": False, "mystery0": False}


# ----------------------------------------------------------------------
# Explicit overrides
# ----------------------------------------------------------------------

def test_explicit_override_takes_precedence_over_type_default():
    interfaces = [_iface("eth0", InterfaceType.ETHERNET), _iface("vpn0", InterfaceType.OTHER)]
    # Explicitly flip both away from their type-based defaults.
    overrides = {"eth0": False, "vpn0": True}
    resolved = resolve_enabled_map(interfaces, overrides)
    assert resolved == {"eth0": False, "vpn0": True}


def test_manager_set_override_and_resolve():
    manager = InterfaceSelectionManager()
    interfaces = [_iface("eth0", InterfaceType.ETHERNET), _iface("vpn0", InterfaceType.OTHER)]
    manager.set_override("vpn0", True)
    resolved = manager.resolve(interfaces)
    assert resolved == {"eth0": True, "vpn0": True}
    assert manager.get_override("vpn0") is True
    assert manager.get_override("eth0") is None  # never explicitly overridden


# ----------------------------------------------------------------------
# Disappearance / reappearance override retention
# ----------------------------------------------------------------------

def test_override_retained_when_interface_disappears_and_reappears():
    manager = InterfaceSelectionManager()
    eth0 = _iface("eth0", InterfaceType.ETHERNET)
    manager.set_override("eth0", False)  # user explicitly disables a physical default-enabled adapter

    # Interface disappears from discovery entirely for a tick.
    resolved_gone = manager.resolve([])
    assert resolved_gone == {}

    # It reappears later -- the override must still apply, not reset to
    # the type-based default of True.
    resolved_back = manager.resolve([eth0])
    assert resolved_back == {"eth0": False}


def test_new_physical_interface_defaults_enabled_and_new_other_defaults_disabled():
    manager = InterfaceSelectionManager()
    # No override ever set for either -- simulate them appearing for the
    # first time on some later tick.
    new_eth = _iface("eth1", InterfaceType.ETHERNET)
    new_vpn = _iface("tap0", InterfaceType.OTHER)
    resolved = manager.resolve([new_eth, new_vpn])
    assert resolved == {"eth1": True, "tap0": False}


# ----------------------------------------------------------------------
# filter_enabled_interfaces
# ----------------------------------------------------------------------

def test_filter_enabled_interfaces_excludes_disabled():
    interfaces = [
        _iface("eth0", InterfaceType.ETHERNET),
        _iface("vpn0", InterfaceType.OTHER),
    ]
    enabled_map = resolve_enabled_map(interfaces, overrides={})
    filtered = filter_enabled_interfaces(interfaces, enabled_map)
    assert [i.name for i in filtered] == ["eth0"]


# ----------------------------------------------------------------------
# Bulk operations: select physical defaults / deselect all
# ----------------------------------------------------------------------

def test_select_physical_defaults_resets_all_overrides():
    manager = InterfaceSelectionManager()
    interfaces = [
        _iface("eth0", InterfaceType.ETHERNET),
        _iface("wifi0", InterfaceType.WIFI),
        _iface("vpn0", InterfaceType.OTHER),
    ]
    # Start from a scrambled state: eth0 manually disabled, vpn0 manually enabled.
    manager.set_override("eth0", False)
    manager.set_override("vpn0", True)

    manager.select_physical_defaults(interfaces)

    resolved = manager.resolve(interfaces)
    assert resolved == {"eth0": True, "wifi0": True, "vpn0": False}


def test_deselect_all_disables_every_known_interface():
    manager = InterfaceSelectionManager()
    interfaces = [
        _iface("eth0", InterfaceType.ETHERNET),
        _iface("wifi0", InterfaceType.WIFI),
    ]
    manager.deselect_all(interfaces)
    resolved = manager.resolve(interfaces)
    assert resolved == {"eth0": False, "wifi0": False}


# ----------------------------------------------------------------------
# Deselected path excluded from rates/distribution/history/probes/steering
# (composition tests using pure helpers, per requirements)
# ----------------------------------------------------------------------

def test_deselected_interface_excluded_from_distribution_totals():
    interfaces = [
        _iface("eth0", InterfaceType.ETHERNET),
        _iface("vpn0", InterfaceType.OTHER),
    ]
    enabled_map = resolve_enabled_map(interfaces, overrides={})
    enabled_interfaces = filter_enabled_interfaces(interfaces, enabled_map)

    all_rates = {
        "eth0": _rate("eth0", rx_bytes=1000, tx_bytes=1000),
        "vpn0": _rate("vpn0", rx_bytes=9000, tx_bytes=9000),
    }
    enabled_names = {i.name for i in enabled_interfaces}
    filtered_rates = {n: r for n, r in all_rates.items() if n in enabled_names}

    distribution = compute_distribution(filtered_rates.values())
    # Only eth0 remains -- and since it is the only contributor, its own
    # share is 100%, not diluted by vpn0's much larger (but deselected)
    # traffic.
    assert set(distribution.keys()) == {"eth0"}
    assert distribution["eth0"].combined_pct == 100.0


def test_deselected_interface_never_probed_by_link_prober():
    """LinkProber's interfaces_provider must only ever be given enabled
    interfaces -- verified here by feeding it a provider that itself
    performs the enabled-interfaces filtering, confirming a deselected
    interface is never present in probe results (nor kept stale)."""
    import multilink_manager.networking.probing as probing_mod
    from multilink_manager.models.probe import ProbeResult
    from multilink_manager.networking.probing import LinkProber

    def _probe_iface(name, ip, if_type):
        return InterfaceInfo(
            name=name, friendly_name=name, index=1, if_type=if_type,
            status=InterfaceStatus.UP, ipv4_addresses=[ip], ipv4_gateway="192.168.1.1",
        )

    def _fake_probe_once(source_ip, target, target_kind, interface_name, count=4, timeout_ms=1000):
        return ProbeResult(
            interface_name=interface_name, target=target, target_kind=target_kind,
            target_id=f"{target_kind}:{target}",
            timestamp=0.0, rtt_ms=5.0, loss_pct=0.0, jitter_ms=0.5, reachable=True,
            samples_sent=count, samples_received=count,
        )

    manager = InterfaceSelectionManager()
    all_interfaces = [
        _probe_iface("eth0", "192.168.1.10", InterfaceType.ETHERNET),
        _probe_iface("vpn0", "192.168.1.20", InterfaceType.OTHER),
    ]

    def provider():
        return manager.filter_enabled(all_interfaces)

    monkeypatch_probe_once = probing_mod.probe_once
    probing_mod.probe_once = _fake_probe_once
    try:
        # https_targets=[] avoids any real network call in this test.
        prober = LinkProber(provider, interval_s=999.0, https_targets=[])
        prober._tick()
        results = prober.get_results()
        assert "eth0" in results
        assert "vpn0" not in results  # OTHER defaults disabled -> never probed
    finally:
        probing_mod.probe_once = monkeypatch_probe_once


def test_filter_connections_for_display_excludes_deselected_but_keeps_unattributed():
    conn_eth0 = ConnectionInfo(
        pid=1, process_name="app.exe", protocol="TCP", laddr_ip="192.168.1.10",
        laddr_port=1234, raddr_ip="1.1.1.1", raddr_port=443, state="ESTABLISHED",
        interface_name="eth0",
    )
    conn_vpn0 = ConnectionInfo(
        pid=2, process_name="vpnapp.exe", protocol="TCP", laddr_ip="10.8.0.2",
        laddr_port=5555, raddr_ip="8.8.8.8", raddr_port=443, state="ESTABLISHED",
        interface_name="vpn0",
    )
    conn_unattributed = ConnectionInfo(
        pid=3, process_name="mystery.exe", protocol="TCP", laddr_ip="0.0.0.0",
        laddr_port=0, raddr_ip=None, raddr_port=None, state="LISTEN",
        interface_name=None,
    )
    connections = [conn_eth0, conn_vpn0, conn_unattributed]
    enabled_names = {"eth0"}  # vpn0 is deselected

    filtered = filter_connections_for_display(connections, enabled_names)
    names = {c.pid for c in filtered}
    assert names == {1, 3}  # eth0 kept, vpn0 dropped, unattributed always kept


def test_visible_default_view_hides_disabled_other_but_keeps_enabled_other():
    eth0 = _iface("eth0", InterfaceType.ETHERNET)
    wifi0 = _iface("wifi0", InterfaceType.WIFI)
    vpn0 = _iface("vpn0", InterfaceType.OTHER)
    vpn1 = _iface("vpn1", InterfaceType.OTHER)
    interfaces = [eth0, wifi0, vpn0, vpn1]
    enabled_map = {"eth0": True, "wifi0": False, "vpn0": False, "vpn1": True}

    visible = visible_interfaces_for_default_view(interfaces, enabled_map)
    visible_names = {i.name for i in visible}

    # eth0/wifi0 (physical) always visible regardless of enabled state;
    # vpn0 (disabled Other) hidden; vpn1 (user-enabled Other) stays visible.
    assert visible_names == {"eth0", "wifi0", "vpn1"}


def test_visible_default_view_all_visible_when_all_enabled_or_physical():
    eth0 = _iface("eth0", InterfaceType.ETHERNET)
    wifi0 = _iface("wifi0", InterfaceType.WIFI)
    interfaces = [eth0, wifi0]
    enabled_map = {"eth0": True, "wifi0": True}
    visible = visible_interfaces_for_default_view(interfaces, enabled_map)
    assert {i.name for i in visible} == {"eth0", "wifi0"}
