"""Tests for interface counter delta/Mbps/pps calculation."""

from __future__ import annotations

from multilink_manager.models.traffic import CounterSample
from multilink_manager.monitoring.counters import CounterMonitor


def _sample(name, ts, bytes_sent, bytes_recv, packets_sent, packets_recv,
            errin=0, errout=0, dropin=0, dropout=0):
    return CounterSample(
        interface_name=name, timestamp=ts,
        bytes_sent=bytes_sent, bytes_recv=bytes_recv,
        packets_sent=packets_sent, packets_recv=packets_recv,
        errin=errin, errout=errout, dropin=dropin, dropout=dropout,
    )


def test_first_sample_yields_zero_rate_and_flag():
    monitor = CounterMonitor()
    rates = monitor.update({"eth0": _sample("eth0", 100.0, 1000, 2000, 10, 20)})
    r = rates["eth0"]
    assert r.is_first_sample is True
    assert r.rx_mbps == 0.0
    assert r.tx_mbps == 0.0
    assert r.rx_pps == 0.0
    assert r.tx_pps == 0.0


def test_delta_and_mbps_pps_calculation():
    monitor = CounterMonitor()
    monitor.update({"eth0": _sample("eth0", 100.0, 0, 0, 0, 0)})
    rates = monitor.update({
        "eth0": _sample("eth0", 101.0, 125_000, 250_000, 100, 200,
                        errin=1, errout=2, dropin=3, dropout=4)
    })
    r = rates["eth0"]
    assert r.is_first_sample is False
    assert r.counter_reset_detected is False
    assert r.tx_bytes_delta == 125_000
    assert r.rx_bytes_delta == 250_000
    # 250,000 bytes * 8 bits / 1,000,000 / 1s = 2.0 Mbps
    assert abs(r.rx_mbps - 2.0) < 1e-9
    assert abs(r.tx_mbps - 1.0) < 1e-9
    assert r.rx_pps == 200.0
    assert r.tx_pps == 100.0
    assert r.rx_errors_delta == 1
    assert r.tx_errors_delta == 2
    assert r.rx_discards_delta == 3
    assert r.tx_discards_delta == 4


def test_counter_reset_is_detected_and_uses_new_value_as_delta():
    monitor = CounterMonitor()
    monitor.update({"eth0": _sample("eth0", 100.0, 100_000, 200_000, 100, 200)})
    rates = monitor.update({"eth0": _sample("eth0", 101.0, 500, 1_000, 5, 10)})
    r = rates["eth0"]
    assert r.counter_reset_detected is True
    assert r.tx_bytes_delta == 500
    assert r.rx_bytes_delta == 1_000


def test_zero_interval_produces_zero_rate_without_crashing():
    monitor = CounterMonitor()
    monitor.update({"eth0": _sample("eth0", 100.0, 0, 0, 0, 0)})
    rates = monitor.update({"eth0": _sample("eth0", 100.0, 1000, 1000, 1, 1)})
    r = rates["eth0"]
    assert r.interval_s == 0.0
    assert r.rx_mbps == 0.0
    assert r.tx_mbps == 0.0
