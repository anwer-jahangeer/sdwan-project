"""Aggregation of per-target Internet probe results into one robust,
per-interface synthetic result.

Documented aggregation formula
-------------------------------
Given every icmp/https (i.e. "Internet") ProbeResult for one interface at
one tick (the interface's own gateway probe is deliberately excluded here
-- see below), aggregate_internet_probes computes a single synthetic
ProbeResult (target_kind="aggregate") as follows:

1. Reachable:
   - True if at least one Internet probe is confirmed reachable
     (reachable is True), regardless of how many others failed/are
     unknown -- a single failing endpoint must never by itself make an
     otherwise-healthy interface look unreachable.
   - None (unknown) only if every Internet probe result is itself
     unknown (reachable is None for all of them). This also covers the
     case of an interface with configured Internet targets whose first
     probe results simply have not arrived yet.
   - False otherwise (at least one probe attempted and got a definite
     answer, but none succeeded).

2. Quality metrics use confirmed-reachable probes when at least one
   endpoint is reachable, so one unrelated endpoint outage cannot tank an
   otherwise healthy link. If every endpoint is unreachable, known loss
   values from those failed probes are retained.

3. Latency and jitter prefer reachable ICMP probes because ICMP RTT and
   HTTPS request latency are different measurements. Reachable HTTPS
   timings are used only when no ICMP timing is available.

4. samples_sent / samples_received: summed across every contributing
   probe (informational only, not used in any calculation above).

5. If there are zero Internet probe results at all for the interface
   (e.g. no ICMP/HTTPS targets have produced a result yet this session),
   this function returns None -- the caller (MonitorWorker) is expected
   to fall back to using the interface's own gateway probe as a purely
   diagnostic substitute in that case, and only in that case. The
   gateway is intentionally never blended into the Internet aggregate
   itself: a healthy LAN hop to the gateway says nothing about real
   Internet reachability, and folding it in would let a fully
   Internet-down interface still report as "reachable" through a
   perfectly healthy local gateway.

This keeps interface-level health/score (used for the Dashboard headline,
history charts, and automatic-steering candidate scoring) robust to any
single configured Internet endpoint's outage, while still being fully
transparent (via the per-target rows in Link Health) about exactly which
individual endpoints are and are not reachable.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from multilink_manager.models.probe import ProbeResult

INTERNET_TARGET_KINDS = ("icmp", "https")


def _mean_known(values: Iterable[Optional[float]]) -> Optional[float]:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known) / len(known)


def aggregate_internet_probes(
    interface_name: str,
    probes: Dict[str, ProbeResult],
    timestamp: Optional[float] = None,
) -> Optional[ProbeResult]:
    """Aggregate every icmp/https entry of probes (a
    {target_id: ProbeResult} map for one interface, as produced by
    LinkProber.get_results()[interface_name]) into one synthetic
    ProbeResult with target_kind="aggregate".

    Returns None if there are no Internet (icmp/https) probe results to
    aggregate -- callers should fall back to the interface's gateway
    probe as a diagnostic-only substitute in that case (see module
    docstring, point 4).
    """
    internet_probes = [p for p in probes.values() if p.target_kind in INTERNET_TARGET_KINDS]
    if not internet_probes:
        return None

    reachable_flags = [p.reachable for p in internet_probes]
    if any(flag is True for flag in reachable_flags):
        reachable: Optional[bool] = True
    elif all(flag is None for flag in reachable_flags):
        reachable = None
    else:
        reachable = False

    reachable_probes = [p for p in internet_probes if p.reachable is True]
    quality_probes = reachable_probes or internet_probes
    loss_pct = _mean_known(p.loss_pct for p in quality_probes)

    reachable_icmp = [p for p in reachable_probes if p.target_kind == "icmp"]
    timing_probes = reachable_icmp or [
        p for p in reachable_probes if p.target_kind == "https"
    ]
    rtt_ms = _mean_known(p.rtt_ms for p in timing_probes)
    jitter_ms = _mean_known(p.jitter_ms for p in timing_probes)
    samples_sent = sum(p.samples_sent for p in internet_probes)
    samples_received = sum(p.samples_received for p in internet_probes)
    ts = timestamp if timestamp is not None else max((p.timestamp for p in internet_probes), default=0.0)
    contributing = ", ".join(sorted({p.target for p in internet_probes}))

    return ProbeResult(
        interface_name=interface_name,
        target_kind="aggregate",
        target=f"{len(internet_probes)} Internet probe(s): {contributing}",
        target_id="aggregate",
        timestamp=ts,
        rtt_ms=rtt_ms,
        loss_pct=loss_pct,
        jitter_ms=jitter_ms,
        reachable=reachable,
        samples_sent=samples_sent,
        samples_received=samples_received,
        http_status=None,
        error=None,
    )
