"""Link quality scoring.

Documented formula (also mirrored in README "Scoring" section)
------------------------------------------------------------
Given a single ``ProbeResult`` for an interface (an aggregate probe
covering gateway and/or public-endpoint reachability), the score is
computed as follows:

1. If ``reachable`` is unknown (``None``) -- the probe could not be
   attempted at all -- the score is ``None`` ("unknown"), never a guessed
   number.
2. If ``reachable`` is ``False``, the score is ``0.0``.
3. Otherwise start at 100.0 and subtract penalties (each capped) for the
   metrics that ARE known; unknown individual metrics (e.g. jitter could
   not be computed because fewer than 2 replies were received) contribute
   **zero** penalty rather than being treated as a fault, and this is
   reflected in ``ScoreResult.notes``:

   - ``loss_penalty = min(loss_pct * 2.0, 60.0)``               (0-60 pts)
   - ``latency_penalty`` via fixed RTT bands                    (0-45 pts)
       <= 20ms: 0, <= 50ms: 5, <= 100ms: 15, <= 200ms: 30, else: 45
   - ``jitter_penalty`` via fixed jitter bands                  (0-20 pts)
       <= 5ms: 0, <= 15ms: 5, <= 30ms: 10, else: 20

   ``score = max(0.0, 100.0 - loss_penalty - latency_penalty - jitter_penalty)``

The weighting favors packet loss (most disruptive to real-time and TCP
throughput) over raw latency, and raw latency over jitter, while capping
each component so a single bad metric cannot alone claim the entire 0-100
range without corroboration from the others.
"""

from __future__ import annotations

from multilink_manager.models.probe import ProbeResult
from multilink_manager.models.score import ScoreResult

_MAX_LOSS_PENALTY = 60.0
_MAX_JITTER_PENALTY = 20.0


def _latency_penalty(latency_ms):
    if latency_ms is None:
        return 0.0, "latency unknown (no penalty applied); "
    if latency_ms <= 20:
        return 0.0, ""
    if latency_ms <= 50:
        return 5.0, ""
    if latency_ms <= 100:
        return 15.0, ""
    if latency_ms <= 200:
        return 30.0, ""
    return 45.0, ""


def _jitter_penalty(jitter_ms):
    if jitter_ms is None:
        return 0.0, "jitter unknown (no penalty applied); "
    if jitter_ms <= 5:
        return 0.0, ""
    if jitter_ms <= 15:
        return 5.0, ""
    if jitter_ms <= 30:
        return 10.0, ""
    return _MAX_JITTER_PENALTY, ""


def compute_score(probe: ProbeResult) -> ScoreResult:
    """Compute a 0-100 link quality score from one ProbeResult.

    See module docstring for the full formula.
    """
    if probe.reachable is None:
        return ScoreResult(
            interface_name=probe.interface_name,
            timestamp=probe.timestamp,
            score=None,
            reachable=None,
            loss_pct=probe.loss_pct,
            latency_ms=probe.rtt_ms,
            jitter_ms=probe.jitter_ms,
            penalty_breakdown={},
            notes="reachability unknown; probe could not be attempted",
        )

    if probe.reachable is False:
        return ScoreResult(
            interface_name=probe.interface_name,
            timestamp=probe.timestamp,
            score=0.0,
            reachable=False,
            loss_pct=probe.loss_pct,
            latency_ms=probe.rtt_ms,
            jitter_ms=probe.jitter_ms,
            penalty_breakdown={"unreachable": 100.0},
            notes="target unreachable",
        )

    notes = ""
    if probe.loss_pct is None:
        loss_penalty = 0.0
        notes += "loss unknown (no penalty applied); "
    else:
        loss_penalty = min(probe.loss_pct * 2.0, _MAX_LOSS_PENALTY)

    latency_penalty, lat_note = _latency_penalty(probe.rtt_ms)
    jitter_penalty, jit_note = _jitter_penalty(probe.jitter_ms)
    notes += lat_note + jit_note

    score = max(0.0, 100.0 - loss_penalty - latency_penalty - jitter_penalty)

    return ScoreResult(
        interface_name=probe.interface_name,
        timestamp=probe.timestamp,
        score=score,
        reachable=True,
        loss_pct=probe.loss_pct,
        latency_ms=probe.rtt_ms,
        jitter_ms=probe.jitter_ms,
        penalty_breakdown={
            "loss_penalty": loss_penalty,
            "latency_penalty": latency_penalty,
            "jitter_penalty": jitter_penalty,
        },
        notes=notes.strip(),
    )
