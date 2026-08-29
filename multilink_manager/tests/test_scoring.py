"""Tests for the documented link-scoring formula."""

from __future__ import annotations

from multilink_manager.models.probe import ProbeResult
from multilink_manager.scoring.scorer import compute_score


def _probe(reachable, rtt_ms=None, loss_pct=None, jitter_ms=None):
    return ProbeResult(
        interface_name="eth0", target="8.8.8.8", target_kind="icmp", target_id="icmp:8.8.8.8",
        timestamp=0.0, rtt_ms=rtt_ms, loss_pct=loss_pct, jitter_ms=jitter_ms,
        reachable=reachable,
    )


def test_unreachable_scores_zero():
    result = compute_score(_probe(False))
    assert result.score == 0.0
    assert result.reachable is False


def test_unknown_reachability_scores_none_not_a_number():
    result = compute_score(_probe(None))
    assert result.score is None
    assert result.reachable is None


def test_perfect_link_scores_100():
    result = compute_score(_probe(True, rtt_ms=10.0, loss_pct=0.0, jitter_ms=1.0))
    assert result.score == 100.0


def test_high_loss_applies_capped_penalty():
    result = compute_score(_probe(True, rtt_ms=10.0, loss_pct=50.0, jitter_ms=1.0))
    assert result.penalty_breakdown["loss_penalty"] == 60.0  # capped at 60
    assert result.score == 40.0


def test_high_latency_applies_expected_band_penalty():
    result = compute_score(_probe(True, rtt_ms=250.0, loss_pct=0.0, jitter_ms=1.0))
    assert result.penalty_breakdown["latency_penalty"] == 45.0
    assert result.score == 55.0


def test_high_jitter_applies_expected_band_penalty():
    result = compute_score(_probe(True, rtt_ms=10.0, loss_pct=0.0, jitter_ms=40.0))
    assert result.penalty_breakdown["jitter_penalty"] == 20.0
    assert result.score == 80.0


def test_unknown_metrics_contribute_no_penalty():
    result = compute_score(_probe(True, rtt_ms=None, loss_pct=None, jitter_ms=None))
    assert result.score == 100.0
    assert "unknown" in result.notes


def test_score_never_goes_negative():
    result = compute_score(_probe(True, rtt_ms=999.0, loss_pct=100.0, jitter_ms=999.0))
    assert result.score == 0.0
