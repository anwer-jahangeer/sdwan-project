"""Typed dataclass models shared across the application.

Every model is a plain ``@dataclass`` with explicit ``Optional`` fields for
any value that may be unknown/unavailable on the current platform or
adapter. Consumers (GUI, scoring, storage) must treat ``None`` as "unknown"
and render it distinctly from a real zero value -- never invent data.
"""

from multilink_manager.models.connection import ConnectionInfo
from multilink_manager.models.enums import InterfaceStatus, InterfaceType, TargetType
from multilink_manager.models.history import HistoryRecord
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.probe import ProbeResult
from multilink_manager.models.score import ScoreResult
from multilink_manager.models.traffic import CounterSample, DistributionEntry, RateSample

__all__ = [
    "ConnectionInfo",
    "InterfaceStatus",
    "InterfaceType",
    "TargetType",
    "HistoryRecord",
    "InterfaceInfo",
    "ProbeResult",
    "ScoreResult",
    "CounterSample",
    "DistributionEntry",
    "RateSample",
]
