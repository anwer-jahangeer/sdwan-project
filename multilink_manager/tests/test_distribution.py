"""Tests for RX/TX/combined distribution, including zero-total behavior."""

from __future__ import annotations

from multilink_manager.models.traffic import RateSample
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.monitoring.distribution import compute_distribution, compute_distribution_by_type


def _rate(name, rx_bytes, tx_bytes):
    return RateSample(
        interface_name=name, timestamp=0.0, interval_s=1.0,
        rx_bytes_delta=rx_bytes, tx_bytes_delta=tx_bytes,
        rx_packets_delta=0, tx_packets_delta=0,
        rx_errors_delta=0, tx_errors_delta=0,
        rx_discards_delta=0, tx_discards_delta=0,
        rx_mbps=0.0, tx_mbps=0.0, rx_pps=0.0, tx_pps=0.0,
    )


def test_distribution_normal_case_sums_to_100():
    rates = [_rate("a", 100, 50), _rate("b", 300, 150)]
    dist = compute_distribution(rates)
    assert abs(dist["a"].rx_pct - 25.0) < 1e-9
    assert abs(dist["b"].rx_pct - 75.0) < 1e-9
    assert abs(dist["a"].tx_pct - 25.0) < 1e-9
    assert abs(dist["b"].tx_pct - 75.0) < 1e-9
    assert abs(dist["a"].combined_pct - 25.0) < 1e-9
    assert abs(dist["a"].rx_pct + dist["b"].rx_pct - 100.0) < 1e-9


def test_distribution_zero_total_reports_zero_not_nan():
    rates = [_rate("a", 0, 0), _rate("b", 0, 0)]
    dist = compute_distribution(rates)
    assert dist["a"].rx_pct == 0.0
    assert dist["a"].tx_pct == 0.0
    assert dist["a"].combined_pct == 0.0
    assert dist["b"].combined_pct == 0.0


def test_distribution_single_interface_gets_full_share():
    rates = [_rate("only", 500, 500)]
    dist = compute_distribution(rates)
    assert dist["only"].rx_pct == 100.0
    assert dist["only"].combined_pct == 100.0


def _iface(name, if_type):
    return InterfaceInfo(
        name=name, friendly_name=name, index=1,
        if_type=if_type, status=InterfaceStatus.UP,
    )


def test_distribution_by_type_groups_ethernet_and_wifi():
    rates = [_rate("eth0", 100, 100), _rate("wifi0", 300, 300)]
    interfaces = [_iface("eth0", InterfaceType.ETHERNET), _iface("wifi0", InterfaceType.WIFI)]
    dist = compute_distribution_by_type(rates, interfaces)
    assert abs(dist["ethernet"].combined_pct - 25.0) < 1e-9
    assert abs(dist["wifi"].combined_pct - 75.0) < 1e-9
    assert abs(dist["ethernet"].combined_pct + dist["wifi"].combined_pct - 100.0) < 1e-9


def test_distribution_by_type_unknown_interface_falls_back_to_unknown_bucket():
    rates = [_rate("mystery0", 100, 0)]
    dist = compute_distribution_by_type(rates, [])  # no matching InterfaceInfo at all
    assert "unknown" in dist
    assert dist["unknown"].rx_pct == 100.0


def test_distribution_by_type_zero_total_reports_zero_not_nan():
    rates = [_rate("eth0", 0, 0), _rate("wifi0", 0, 0)]
    interfaces = [_iface("eth0", InterfaceType.ETHERNET), _iface("wifi0", InterfaceType.WIFI)]
    dist = compute_distribution_by_type(rates, interfaces)
    assert dist["ethernet"].combined_pct == 0.0
    assert dist["wifi"].combined_pct == 0.0
