"""Tests for scoring.aggregation.aggregate_internet_probes (documented
formula in scoring/aggregation.py's module docstring)."""

from __future__ import annotations

from multilink_manager.models.probe import ProbeResult
from multilink_manager.scoring.aggregation import aggregate_internet_probes


def _probe(kind, target, reachable, rtt_ms=None, loss_pct=None, jitter_ms=None, sent=4, recv=4):
    return ProbeResult(
        interface_name="eth0", target_kind=kind, target=target,
        target_id=f"{kind}:{target}", timestamp=1.0,
        rtt_ms=rtt_ms, loss_pct=loss_pct, jitter_ms=jitter_ms, reachable=reachable,
        samples_sent=sent, samples_received=recv,
    )


def test_no_internet_probes_returns_none():
    probes = {"gateway:192.168.1.1": _probe("gateway", "192.168.1.1", True, rtt_ms=1.0, loss_pct=0.0)}
    assert aggregate_internet_probes("eth0", probes) is None


def test_mixed_success_and_failure_is_reachable_and_averages_known_values():
    probes = {
        "icmp:1.1.1.1": _probe("icmp", "1.1.1.1", True, rtt_ms=10.0, loss_pct=0.0, jitter_ms=1.0),
        "icmp:8.8.8.8": _probe("icmp", "8.8.8.8", False, rtt_ms=None, loss_pct=100.0, jitter_ms=None),
        "gateway:192.168.1.1": _probe("gateway", "192.168.1.1", True, rtt_ms=1.0, loss_pct=0.0),
    }
    agg = aggregate_internet_probes("eth0", probes, timestamp=42.0)
    assert agg is not None
    assert agg.target_kind == "aggregate"
    assert agg.target_id == "aggregate"
    assert agg.reachable is True
    # Only the two icmp probes contribute (gateway excluded); rtt_ms known
    # value is only the reachable one (10.0), unreachable one is None.
    assert agg.rtt_ms == 10.0
    # The failed endpoint remains visible in its own row and sample
    # totals, but cannot tank aggregate quality while another independent
    # Internet endpoint is confirmed healthy.
    assert agg.loss_pct == 0.0
    assert agg.jitter_ms == 1.0  # mean of the only known jitter value
    assert agg.samples_sent == 8
    assert agg.samples_received == 8
    assert agg.timestamp == 42.0


def test_all_failed_is_not_reachable():
    probes = {
        "icmp:1.1.1.1": _probe("icmp", "1.1.1.1", False, loss_pct=100.0),
        "https:https://a": _probe("https", "https://a", False, loss_pct=100.0),
    }
    agg = aggregate_internet_probes("eth0", probes)
    assert agg is not None
    assert agg.reachable is False
    assert agg.loss_pct == 100.0


def test_all_unknown_is_unknown_not_false():
    probes = {
        "icmp:1.1.1.1": _probe("icmp", "1.1.1.1", None),
        "https:https://a": _probe("https", "https://a", None),
    }
    agg = aggregate_internet_probes("eth0", probes)
    assert agg is not None
    assert agg.reachable is None
    assert agg.loss_pct is None
    assert agg.rtt_ms is None
    assert agg.jitter_ms is None


def test_multiple_same_kind_targets_all_contribute_and_are_not_overwritten():
    probes = {
        "icmp:1.1.1.1": _probe("icmp", "1.1.1.1", True, rtt_ms=10.0, loss_pct=0.0),
        "icmp:8.8.8.8": _probe("icmp", "8.8.8.8", True, rtt_ms=20.0, loss_pct=0.0),
        "https:https://a": _probe("https", "https://a", True, rtt_ms=100.0, loss_pct=0.0),
        "https:https://b": _probe("https", "https://b", True, rtt_ms=200.0, loss_pct=0.0),
    }
    assert len(probes) == 4  # confirms distinct target_id keys did not collide
    agg = aggregate_internet_probes("eth0", probes)
    assert agg is not None
    # ICMP RTT is preferred over incomparable HTTPS request/TLS latency.
    assert agg.rtt_ms == (10.0 + 20.0) / 2


def test_https_timing_is_fallback_when_no_icmp_timing_is_available():
    probes = {
        "icmp:1.1.1.1": _probe("icmp", "1.1.1.1", False, loss_pct=100.0),
        "https:https://a": _probe("https", "https://a", True, rtt_ms=100.0, loss_pct=0.0),
        "https:https://b": _probe("https", "https://b", True, rtt_ms=200.0, loss_pct=0.0),
    }
    agg = aggregate_internet_probes("eth0", probes)
    assert agg is not None
    assert agg.rtt_ms == 150.0
    assert agg.loss_pct == 0.0
