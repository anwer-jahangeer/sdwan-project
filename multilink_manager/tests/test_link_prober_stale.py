"""Focused test: LinkProber removes stale results immediately when an
interface disappears, so vanished adapters do not linger in Link Health."""

from __future__ import annotations

import multilink_manager.networking.probing as probing_mod
from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.probe import ProbeResult
from multilink_manager.networking.probing import LinkProber


def _iface(name: str, ip: str, gateway: str = "192.168.1.1") -> InterfaceInfo:
    return InterfaceInfo(
        name=name, friendly_name=name, index=1,
        if_type=InterfaceType.ETHERNET, status=InterfaceStatus.UP,
        ipv4_addresses=[ip], ipv4_gateway=gateway,
    )


def _fake_probe_once(source_ip, target, target_kind, interface_name, count=4, timeout_ms=1000):
    return ProbeResult(
        interface_name=interface_name, target=target, target_kind=target_kind,
        target_id=f"{target_kind}:{target}",
        timestamp=0.0, rtt_ms=10.0, loss_pct=0.0, jitter_ms=1.0, reachable=True,
        samples_sent=count, samples_received=count,
    )


def test_stale_results_removed_when_interface_disappears(monkeypatch):
    monkeypatch.setattr(probing_mod, "probe_once", _fake_probe_once)

    interfaces = [_iface("eth0", "192.168.1.10"), _iface("wifi0", "192.168.1.20")]

    # https_targets=[] avoids any real network call in this ICMP-focused
    # test; HTTPS probing is covered separately with a mocked connection
    # factory.
    prober = LinkProber(lambda: interfaces, interval_s=999.0, https_targets=[])
    prober._tick()

    results = prober.get_results()
    assert "eth0" in results
    assert "wifi0" in results
    assert any(target_id.startswith("gateway:") for target_id in results["eth0"])
    assert any(target_id.startswith("icmp:") for target_id in results["eth0"])

    # wifi0 disappears from discovery.
    interfaces.pop()
    prober._tick()

    results_after = prober.get_results()
    assert "wifi0" not in results_after
    assert "eth0" in results_after


def test_stale_results_removed_even_without_new_probe_targets(monkeypatch):
    """Stale removal must happen even if the surviving interface set is
    empty (no new probe jobs launched at all)."""
    monkeypatch.setattr(probing_mod, "probe_once", _fake_probe_once)

    interfaces = [_iface("eth0", "192.168.1.10")]
    prober = LinkProber(lambda: interfaces, interval_s=999.0, https_targets=[])
    prober._tick()
    assert "eth0" in prober.get_results()

    interfaces.clear()
    prober._tick()
    assert prober.get_results() == {}
