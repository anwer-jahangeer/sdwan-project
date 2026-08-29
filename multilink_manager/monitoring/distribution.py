"""RX/TX/combined percentage distribution across interfaces.

Zero-total behavior: when the summed RX (or TX, or combined) traffic
across all interfaces for the current tick is zero, every interface's
share for that metric is reported as ``0.0`` (not ``NaN`` and not an
even/artificial split) since there is no traffic to distribute.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.traffic import DistributionEntry, RateSample


def compute_distribution(rates: Iterable[RateSample]) -> Dict[str, DistributionEntry]:
    rates = list(rates)
    total_rx = sum(max(r.rx_bytes_delta, 0) for r in rates)
    total_tx = sum(max(r.tx_bytes_delta, 0) for r in rates)
    total_combined = total_rx + total_tx

    result: Dict[str, DistributionEntry] = {}
    for r in rates:
        rx = max(r.rx_bytes_delta, 0)
        tx = max(r.tx_bytes_delta, 0)
        rx_pct = (100.0 * rx / total_rx) if total_rx > 0 else 0.0
        tx_pct = (100.0 * tx / total_tx) if total_tx > 0 else 0.0
        combined_pct = (100.0 * (rx + tx) / total_combined) if total_combined > 0 else 0.0
        result[r.interface_name] = DistributionEntry(
            interface_name=r.interface_name,
            rx_pct=rx_pct,
            tx_pct=tx_pct,
            combined_pct=combined_pct,
        )
    return result


def compute_distribution_by_type(
    rates: Iterable[RateSample], interfaces: List[InterfaceInfo]
) -> Dict[str, DistributionEntry]:
    """Aggregate the same RX/TX/combined distribution, grouped by interface
    *type* (``ethernet``/``wifi``/``other``/``unknown``) instead of by
    individual interface name.

    This answers "what share of all traffic is going over Ethernet vs.
    Wi-Fi vs. other interfaces", complementing the per-interface
    distribution above. The returned dict is keyed by the ``InterfaceType``
    value string (reusing ``DistributionEntry.interface_name`` to hold that
    type name); same zero-total behavior applies.
    """
    type_by_name = {iface.name: iface.if_type.value for iface in interfaces}

    grouped_rx: Dict[str, int] = {}
    grouped_tx: Dict[str, int] = {}
    for r in rates:
        type_name = type_by_name.get(r.interface_name, "unknown")
        grouped_rx[type_name] = grouped_rx.get(type_name, 0) + max(r.rx_bytes_delta, 0)
        grouped_tx[type_name] = grouped_tx.get(type_name, 0) + max(r.tx_bytes_delta, 0)

    total_rx = sum(grouped_rx.values())
    total_tx = sum(grouped_tx.values())
    total_combined = total_rx + total_tx

    result: Dict[str, DistributionEntry] = {}
    for type_name in set(grouped_rx) | set(grouped_tx):
        rx = grouped_rx.get(type_name, 0)
        tx = grouped_tx.get(type_name, 0)
        rx_pct = (100.0 * rx / total_rx) if total_rx > 0 else 0.0
        tx_pct = (100.0 * tx / total_tx) if total_tx > 0 else 0.0
        combined_pct = (100.0 * (rx + tx) / total_combined) if total_combined > 0 else 0.0
        result[type_name] = DistributionEntry(
            interface_name=type_name,
            rx_pct=rx_pct,
            tx_pct=tx_pct,
            combined_pct=combined_pct,
        )
    return result
