"""Link probe result model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProbeResult:
    """Result of probing one target from one interface's bound source IP
    (or, for ``target_kind == "aggregate"``, a synthetic combination of
    several such results -- see ``scoring/aggregation.py``).

    ``target_kind`` distinguishes the *kind* of probe/target so the UI and
    scoring pipeline can clearly label what is actually being measured:

    - ``"gateway"``  -- ICMP echo to the interface's own default gateway.
    - ``"icmp"``     -- ICMP echo to a configured public/Internet target
                        (e.g. ``1.1.1.1``); ``rtt_ms`` here is a true ICMP
                        round-trip time.
    - ``"https"``    -- an HTTP(S) request/response probe to a configured
                        URL; ``rtt_ms`` here is **HTTP request/response
                        latency**, not an ICMP RTT -- the UI must label it
                        accordingly (see ``target_kind`` on the row).
    - ``"aggregate"`` -- a synthetic, per-interface combination of every
                        ``icmp``/``https`` ("Internet") probe result for
                        that interface, computed by
                        :func:`scoring.aggregation.aggregate_internet_probes`
                        so a single failing endpoint cannot alone force an
                        interface to look unreachable.

    ``target_id`` is a stable, unique dictionary key for this exact
    target -- typically ``f"{target_kind}:{target}"`` (or the literal
    string ``"aggregate"`` for the synthetic aggregate) -- so that
    multiple same-kind targets (e.g. two ICMP targets, or two HTTPS URLs)
    never overwrite each other in a ``{target_id: ProbeResult}`` result
    map the way a plain ``target_kind`` key would.

    Any field that could not be determined is left as ``None`` rather than
    guessed -- e.g. ``rtt_ms`` is ``None`` when every probe in the sample
    window timed out, and ``reachable`` is ``None`` (not ``False``) if the
    probe could not even be attempted (e.g. no source IP available yet).
    """

    interface_name: str
    target_kind: str  # "gateway" | "icmp" | "https" | "aggregate"
    target: str
    target_id: str
    timestamp: float
    rtt_ms: Optional[float]
    loss_pct: Optional[float]
    jitter_ms: Optional[float]
    reachable: Optional[bool]
    samples_sent: int = 0
    samples_received: int = 0
    http_status: Optional[int] = None
    error: Optional[str] = None
