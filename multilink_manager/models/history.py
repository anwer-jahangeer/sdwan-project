"""History record model (used for the in-memory time-window history)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class HistoryRecord:
    timestamp: float
    interface_name: str
    rx_mbps: float
    tx_mbps: float
    rx_bytes: int
    tx_bytes: int
    latency_ms: Optional[float]
    loss_pct: Optional[float]
    jitter_ms: Optional[float]
    score: Optional[float]

    CSV_FIELDS = (
        "timestamp",
        "interface_name",
        "rx_mbps",
        "tx_mbps",
        "rx_bytes",
        "tx_bytes",
        "latency_ms",
        "loss_pct",
        "jitter_ms",
        "score",
    )

    def to_csv_row(self) -> list:
        return [
            self.timestamp,
            self.interface_name,
            self.rx_mbps,
            self.tx_mbps,
            self.rx_bytes,
            self.tx_bytes,
            self.latency_ms if self.latency_ms is not None else "",
            self.loss_pct if self.loss_pct is not None else "",
            self.jitter_ms if self.jitter_ms is not None else "",
            self.score if self.score is not None else "",
        ]
