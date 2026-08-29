"""Traffic counter and rate/distribution models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CounterSample:
    """A single cumulative read of an interface's OS-reported counters."""

    interface_name: str
    timestamp: float
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errin: int
    errout: int
    dropin: int
    dropout: int


@dataclass
class RateSample:
    """Delta-derived rates between two consecutive CounterSamples."""

    interface_name: str
    timestamp: float
    interval_s: float
    rx_bytes_delta: int
    tx_bytes_delta: int
    rx_packets_delta: int
    tx_packets_delta: int
    rx_errors_delta: int
    tx_errors_delta: int
    rx_discards_delta: int
    tx_discards_delta: int
    rx_mbps: float
    tx_mbps: float
    rx_pps: float
    tx_pps: float
    is_first_sample: bool = False
    counter_reset_detected: bool = False


@dataclass
class DistributionEntry:
    """Percentage share of an interface within the current total traffic."""

    interface_name: str
    rx_pct: float
    tx_pct: float
    combined_pct: float
