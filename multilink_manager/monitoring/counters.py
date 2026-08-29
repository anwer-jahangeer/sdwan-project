"""Interface counter sampling and delta/rate computation.

Uses ``psutil.net_io_counters(pernic=True)`` for cumulative bytes, packets,
errors ("errin"/"errout"), and discards ("dropin"/"dropout") -- these map
directly to the Windows IP Helper / GetIfEntry2 counters that psutil reads
on Windows. Only true incremental deltas are reported: the first sample for
an interface has no baseline (``is_first_sample=True``, zero rates) and a
counter value that goes backwards (adapter reset, driver reload, 32-bit
counter wrap) is treated as a reset (`counter_reset_detected=True`) using
the new value as the delta rather than producing a nonsensical negative or
huge wrapped number.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

import psutil

from multilink_manager.models.traffic import CounterSample, RateSample
from multilink_manager.utils.logging_config import get_logger

logger = get_logger(__name__)


def read_counter_samples() -> Dict[str, CounterSample]:
    """Read current cumulative per-interface counters from the OS via psutil."""
    now = time.time()
    try:
        raw = psutil.net_io_counters(pernic=True)
    except Exception:  # pragma: no cover - defensive
        logger.exception("psutil.net_io_counters() failed")
        return {}
    samples = {}
    for name, c in raw.items():
        samples[name] = CounterSample(
            interface_name=name,
            timestamp=now,
            bytes_sent=c.bytes_sent,
            bytes_recv=c.bytes_recv,
            packets_sent=c.packets_sent,
            packets_recv=c.packets_recv,
            errin=getattr(c, "errin", 0),
            errout=getattr(c, "errout", 0),
            dropin=getattr(c, "dropin", 0),
            dropout=getattr(c, "dropout", 0),
        )
    return samples


def _delta(current: int, previous: int) -> tuple[int, bool]:
    """Return (delta, counter_reset_detected)."""
    if current >= previous:
        return current - previous, False
    # Counter went backwards: adapter reset/reload. Treat the new cumulative
    # value itself as the delta since the last reset, rather than a large
    # (wrapped) or negative number.
    return current, True


class CounterMonitor:
    """Stateful tracker that turns cumulative CounterSamples into RateSamples."""

    def __init__(self) -> None:
        self._previous: Dict[str, CounterSample] = {}

    def update(self, samples: Dict[str, CounterSample]) -> Dict[str, RateSample]:
        rates: Dict[str, RateSample] = {}
        for name, sample in samples.items():
            prev = self._previous.get(name)
            if prev is None:
                rates[name] = RateSample(
                    interface_name=name,
                    timestamp=sample.timestamp,
                    interval_s=0.0,
                    rx_bytes_delta=0,
                    tx_bytes_delta=0,
                    rx_packets_delta=0,
                    tx_packets_delta=0,
                    rx_errors_delta=0,
                    tx_errors_delta=0,
                    rx_discards_delta=0,
                    tx_discards_delta=0,
                    rx_mbps=0.0,
                    tx_mbps=0.0,
                    rx_pps=0.0,
                    tx_pps=0.0,
                    is_first_sample=True,
                )
                self._previous[name] = sample
                continue

            interval_s = sample.timestamp - prev.timestamp
            rx_bytes_delta, reset1 = _delta(sample.bytes_recv, prev.bytes_recv)
            tx_bytes_delta, reset2 = _delta(sample.bytes_sent, prev.bytes_sent)
            rx_packets_delta, reset3 = _delta(sample.packets_recv, prev.packets_recv)
            tx_packets_delta, reset4 = _delta(sample.packets_sent, prev.packets_sent)
            rx_errors_delta, _ = _delta(sample.errin, prev.errin)
            tx_errors_delta, _ = _delta(sample.errout, prev.errout)
            rx_discards_delta, _ = _delta(sample.dropin, prev.dropin)
            tx_discards_delta, _ = _delta(sample.dropout, prev.dropout)
            counter_reset_detected = any((reset1, reset2, reset3, reset4))

            if interval_s > 0:
                rx_mbps = (rx_bytes_delta * 8) / (interval_s * 1_000_000)
                tx_mbps = (tx_bytes_delta * 8) / (interval_s * 1_000_000)
                rx_pps = rx_packets_delta / interval_s
                tx_pps = tx_packets_delta / interval_s
            else:
                rx_mbps = tx_mbps = rx_pps = tx_pps = 0.0

            rates[name] = RateSample(
                interface_name=name,
                timestamp=sample.timestamp,
                interval_s=max(interval_s, 0.0),
                rx_bytes_delta=rx_bytes_delta,
                tx_bytes_delta=tx_bytes_delta,
                rx_packets_delta=rx_packets_delta,
                tx_packets_delta=tx_packets_delta,
                rx_errors_delta=rx_errors_delta,
                tx_errors_delta=tx_errors_delta,
                rx_discards_delta=rx_discards_delta,
                tx_discards_delta=tx_discards_delta,
                rx_mbps=rx_mbps,
                tx_mbps=tx_mbps,
                rx_pps=rx_pps,
                tx_pps=tx_pps,
                is_first_sample=False,
                counter_reset_detected=counter_reset_detected,
            )
            self._previous[name] = sample

        # Interfaces that vanished from this sample are dropped from
        # _previous so that if they reappear later they are treated as a
        # fresh first sample rather than producing a bogus huge delta.
        for stale_name in set(self._previous) - set(samples):
            logger.info("Interface '%s' disappeared from counters", stale_name)
            del self._previous[stale_name]

        return rates
