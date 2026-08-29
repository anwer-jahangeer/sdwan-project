"""Process/connection model.

Per-connection byte counters are intentionally NOT modeled as numbers here.
psutil.net_connections() exposes socket 5-tuples and state but no byte
counters; obtaining real per-connection traffic volume on Windows requires
a kernel-mode driver, ETW (Event Tracing for Windows) flow events, WFP
(Windows Filtering Platform) callouts, or live packet capture (e.g. WinDivert
or npcap), none of which this MVP installs (per the "never install
drivers" constraint). ``bytes_sent``/``bytes_recv`` therefore always stay
``None`` and the UI must render them as "unavailable", not zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ConnectionInfo:
    pid: Optional[int]
    process_name: Optional[str]
    protocol: str
    laddr_ip: Optional[str]
    laddr_port: Optional[int]
    raddr_ip: Optional[str]
    raddr_port: Optional[int]
    state: Optional[str]
    interface_name: Optional[str]
    bytes_sent: Optional[int] = None
    bytes_recv: Optional[int] = None
    bytes_unavailable_reason: str = (
        "Per-connection byte counters require a driver, ETW, WFP, or packet "
        "capture; not exposed by psutil.net_connections(). Not implemented "
        "in this MVP because it never installs drivers."
    )
