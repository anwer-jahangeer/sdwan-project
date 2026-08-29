"""Tests for interface disappearance/reappearance behavior in counter monitoring."""

from __future__ import annotations

from multilink_manager.models.traffic import CounterSample
from multilink_manager.monitoring.counters import CounterMonitor


def _sample(name, ts, bytes_sent, bytes_recv, packets_sent=1, packets_recv=1):
    return CounterSample(
        interface_name=name, timestamp=ts,
        bytes_sent=bytes_sent, bytes_recv=bytes_recv,
        packets_sent=packets_sent, packets_recv=packets_recv,
        errin=0, errout=0, dropin=0, dropout=0,
    )


def test_interface_disappearance_clears_baseline():
    monitor = CounterMonitor()
    monitor.update({"eth0": _sample("eth0", 100.0, 1000, 2000)})
    rates = monitor.update({"eth0": _sample("eth0", 101.0, 2000, 4000)})
    assert rates["eth0"].is_first_sample is False

    # Interface vanishes from the OS-reported set (e.g. adapter unplugged).
    rates_after_disappear = monitor.update({})
    assert "eth0" not in rates_after_disappear
    assert "eth0" not in monitor._previous


def test_interface_reappearance_treated_as_fresh_first_sample():
    monitor = CounterMonitor()
    monitor.update({"eth0": _sample("eth0", 100.0, 1000, 2000)})
    monitor.update({"eth0": _sample("eth0", 101.0, 2000, 4000)})
    monitor.update({})  # disappears

    # Reappears later with unrelated (smaller) cumulative counters -- must
    # NOT be treated as a counter reset/huge negative delta against the
    # stale baseline, since the baseline was discarded on disappearance.
    rates = monitor.update({"eth0": _sample("eth0", 200.0, 50, 60)})
    r = rates["eth0"]
    assert r.is_first_sample is True
    assert r.counter_reset_detected is False
    assert r.rx_mbps == 0.0
    assert r.tx_mbps == 0.0


def test_other_interfaces_unaffected_by_one_disappearing():
    monitor = CounterMonitor()
    monitor.update({
        "eth0": _sample("eth0", 100.0, 1000, 2000),
        "wifi0": _sample("wifi0", 100.0, 500, 700),
    })
    rates = monitor.update({
        "wifi0": _sample("wifi0", 101.0, 1500, 1700),
    })
    assert "eth0" not in rates
    assert rates["wifi0"].is_first_sample is False
    assert rates["wifi0"].rx_bytes_delta == 1000
