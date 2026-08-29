"""Scoring result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ScoreResult:
    """Output of the link scoring formula for one interface at one instant.

    ``score`` is ``None`` when there is not enough information to compute a
    meaningful value (e.g. reachability itself is unknown). See
    ``multilink_manager/scoring/scorer.py`` and the README for the full
    documented formula and rationale for each penalty term.
    """

    interface_name: str
    timestamp: float
    score: Optional[float]
    reachable: Optional[bool]
    loss_pct: Optional[float]
    latency_ms: Optional[float]
    jitter_ms: Optional[float]
    penalty_breakdown: Dict[str, float] = field(default_factory=dict)
    notes: str = ""
