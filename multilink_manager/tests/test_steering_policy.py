"""Pure unit tests for SteeringPolicy: hysteresis, N-cycle confirmation,
hold-down, unknown-score exclusion (both sides), and ineligible-candidate
exclusion. No OS/PowerShell/Qt calls at all -- SteeringPolicy is fully
OS-independent by design."""

from __future__ import annotations

from multilink_manager.models.steering import CandidateHealth, SteeringConfig
from multilink_manager.steering.policy import SteeringPolicy


def _health(score=None, reachable=True, eligible=True, has_route=True, name="x"):
    return CandidateHealth(
        interface_name=name, score=score, reachable=reachable,
        is_eligible_physical=eligible, has_default_route=has_route,
    )


def _config(**overrides):
    return SteeringConfig(**overrides)


def test_no_candidates_never_switches():
    policy = SteeringPolicy(_config())
    decision = policy.decide(now=0.0, active_interface="eth0", candidates={
        "eth0": _health(score=80.0, name="eth0"),
    })
    assert decision.should_switch is False
    assert decision.target_interface is None


def test_unknown_candidate_score_excluded():
    """A candidate with score=None must never be selected, even if it
    would otherwise be the only option and the active path is unhealthy."""
    policy = SteeringPolicy(_config())
    candidates = {
        "eth0": _health(score=10.0, reachable=True, name="eth0"),  # unhealthy active
        "wifi0": _health(score=None, reachable=True, name="wifi0"),  # unknown score
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False
    assert decision.target_interface is None


def test_unknown_active_score_never_triggers_switch():
    """If the active interface's score is simply unknown (not confirmed
    unreachable), a switch must never be considered even with a great
    candidate available."""
    policy = SteeringPolicy(_config())
    candidates = {
        "eth0": _health(score=None, reachable=True, name="eth0"),
        "wifi0": _health(score=95.0, reachable=True, name="wifi0"),
    }
    for _ in range(5):
        decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
        assert decision.should_switch is False


def test_ineligible_candidate_excluded_wrong_type_or_down():
    policy = SteeringPolicy(_config())
    candidates = {
        "eth0": _health(score=10.0, reachable=False, name="eth0"),
        "vpn0": _health(score=99.0, reachable=True, eligible=False, name="vpn0"),
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False
    assert decision.target_interface is None


def test_ineligible_candidate_excluded_no_default_route():
    policy = SteeringPolicy(_config())
    candidates = {
        "eth0": _health(score=10.0, reachable=False, name="eth0"),
        "wifi0": _health(score=99.0, reachable=True, has_route=False, name="wifi0"),
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False


def test_ineligible_candidate_excluded_unreachable():
    policy = SteeringPolicy(_config())
    candidates = {
        "eth0": _health(score=10.0, reachable=False, name="eth0"),
        "wifi0": _health(score=99.0, reachable=False, name="wifi0"),
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False


def test_hysteresis_requires_full_advantage_for_healthy_active():
    """A healthy active path (score above the unhealthy threshold) must
    only be switched away from once the candidate exceeds it by the
    configured score_advantage_threshold."""
    cfg = _config(score_advantage_threshold=10.0, min_consecutive_cycles=1)
    policy = SteeringPolicy(cfg)
    candidates = {
        "eth0": _health(score=70.0, name="eth0"),
        "wifi0": _health(score=75.0, name="wifi0"),  # only +5, below threshold
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False

    candidates["wifi0"] = _health(score=81.0, name="wifi0")  # +11, above threshold
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is True
    assert decision.target_interface == "wifi0"


def test_unhealthy_active_switches_without_needing_full_hysteresis():
    cfg = _config(score_advantage_threshold=10.0, min_consecutive_cycles=1, unhealthy_score_threshold=40.0)
    policy = SteeringPolicy(cfg)
    candidates = {
        "eth0": _health(score=20.0, name="eth0"),  # below unhealthy threshold
        "wifi0": _health(score=25.0, name="wifi0"),  # only +5 advantage, but active is unhealthy
    }
    decision = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is True
    assert decision.target_interface == "wifi0"


def test_n_cycle_confirmation_required_before_switch():
    cfg = _config(score_advantage_threshold=10.0, min_consecutive_cycles=3)
    policy = SteeringPolicy(cfg)
    candidates = {
        "eth0": _health(score=50.0, name="eth0"),
        "wifi0": _health(score=90.0, name="wifi0"),
    }
    d1 = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert d1.should_switch is False
    assert d1.consecutive_cycles == 1

    d2 = policy.decide(now=1.0, active_interface="eth0", candidates=candidates)
    assert d2.should_switch is False
    assert d2.consecutive_cycles == 2

    d3 = policy.decide(now=2.0, active_interface="eth0", candidates=candidates)
    assert d3.should_switch is True
    assert d3.consecutive_cycles == 3
    assert d3.target_interface == "wifi0"


def test_streak_resets_when_candidate_changes():
    cfg = _config(score_advantage_threshold=10.0, min_consecutive_cycles=3)
    policy = SteeringPolicy(cfg)
    candidates = {
        "eth0": _health(score=50.0, name="eth0"),
        "wifi0": _health(score=90.0, name="wifi0"),
        "lte0": _health(score=5.0, name="lte0"),
    }
    d1 = policy.decide(now=0.0, active_interface="eth0", candidates=candidates)
    assert d1.consecutive_cycles == 1

    # Now lte0 becomes the best candidate instead -- streak must reset.
    candidates["lte0"] = _health(score=95.0, name="lte0")
    d2 = policy.decide(now=1.0, active_interface="eth0", candidates=candidates)
    assert d2.consecutive_cycles == 1
    assert d2.target_interface is None  # not confirmed yet
    assert d2.should_switch is False


def test_hold_down_blocks_new_switch_after_recorded_switch():
    cfg = _config(hold_down_seconds=30.0, min_consecutive_cycles=1, score_advantage_threshold=10.0)
    policy = SteeringPolicy(cfg)
    policy.record_switch(now=100.0)

    candidates = {
        "eth0": _health(score=10.0, name="eth0"),
        "wifi0": _health(score=99.0, name="wifi0"),
    }
    decision = policy.decide(now=110.0, active_interface="eth0", candidates=candidates)
    assert decision.should_switch is False
    assert decision.hold_down_remaining_s > 0.0
    assert "hold-down" in decision.reason


def test_hold_down_expires_and_confirmation_resumes_cold():
    cfg = _config(hold_down_seconds=30.0, min_consecutive_cycles=2, score_advantage_threshold=10.0)
    policy = SteeringPolicy(cfg)
    policy.record_switch(now=100.0)

    candidates = {
        "eth0": _health(score=10.0, name="eth0"),
        "wifi0": _health(score=99.0, name="wifi0"),
    }
    # Still in hold-down.
    d1 = policy.decide(now=110.0, active_interface="eth0", candidates=candidates)
    assert d1.should_switch is False

    # Hold-down expired: confirmation streak must resume from 1, not
    # continue from whatever it was before hold-down (it was reset).
    d2 = policy.decide(now=131.0, active_interface="eth0", candidates=candidates)
    assert d2.should_switch is False
    assert d2.consecutive_cycles == 1

    d3 = policy.decide(now=132.0, active_interface="eth0", candidates=candidates)
    assert d3.should_switch is True
    assert d3.consecutive_cycles == 2


def test_no_active_interface_treated_as_unhealthy():
    """An unknown active_interface (e.g. None, no preferred path yet)
    must be treated as confirmed-unhealthy, not as unknown-and-skip."""
    cfg = _config(min_consecutive_cycles=1, score_advantage_threshold=10.0)
    policy = SteeringPolicy(cfg)
    candidates = {
        "wifi0": _health(score=50.0, name="wifi0"),
    }
    decision = policy.decide(now=0.0, active_interface=None, candidates=candidates)
    assert decision.should_switch is True
    assert decision.target_interface == "wifi0"
