"""Link probe result model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProbeResult:
    """Result of probing one target (gateway or public endpoint) from one
    interface's bound source IP.

    Any field that could not be determined is left as ``None`` rather than
    guessed -- e.g. ``rtt_ms`` is ``None`` when every probe in the sample
    window timed out, and ``reachable`` is ``None`` (not ``False``) if the
    probe could not even be attempted (e.g. no source IP available yet).
    """

    interface_name: str
    target: str
    target_type: str  # "gateway" | "public"
    timestamp: float
    rtt_ms: Optional[float]
    loss_pct: Optional[float]
    jitter_ms: Optional[float]
    reachable: Optional[bool]
    samples_sent: int = 0
    samples_received: int = 0
    error: Optional[str] = None
