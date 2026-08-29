"""Process/connection visibility via psutil.net_connections().

Interface attribution is done ONLY by exact local-IP ownership: a
connection's local address is matched against the set of IPv4/IPv6
addresses currently bound to each discovered interface. If the local
address does not exactly match any known interface address (e.g. it is
0.0.0.0/::, a loopback address, or the interface list is stale), the
connection's ``interface_name`` is left as ``None`` rather than guessed
via routing-table heuristics.
"""

from __future__ import annotations

import socket
from typing import Dict, List, Optional

import psutil

from multilink_manager.models.connection import ConnectionInfo
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.utils.logging_config import get_logger

logger = get_logger(__name__)

_PROTO_MAP = {
    (socket.AF_INET, socket.SOCK_STREAM): "TCP",
    (socket.AF_INET, socket.SOCK_DGRAM): "UDP",
}
try:  # AF_INET6 not present on every platform build
    _PROTO_MAP[(socket.AF_INET6, socket.SOCK_STREAM)] = "TCP6"
    _PROTO_MAP[(socket.AF_INET6, socket.SOCK_DGRAM)] = "UDP6"
except AttributeError:  # pragma: no cover
    pass


def build_ip_to_interface_map(interfaces: List[InterfaceInfo]) -> Dict[str, str]:
    """Build an exact-match lookup of local IP address -> interface name."""
    mapping: Dict[str, str] = {}
    for iface in interfaces:
        for ip in (*iface.ipv4_addresses, *iface.ipv6_addresses):
            mapping[ip] = iface.name
    return mapping


def list_connections(interfaces: List[InterfaceInfo]) -> List[ConnectionInfo]:
    """Return current connections with process info and interface attribution.

    Byte counters are intentionally never populated here -- see
    ``models.connection.ConnectionInfo`` docstring for why.
    """
    ip_to_iface = build_ip_to_interface_map(interfaces)

    try:
        raw_connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        logger.warning(
            "psutil.net_connections() denied access; run elevated for full "
            "process/connection visibility"
        )
        return []
    except Exception:  # pragma: no cover - defensive
        logger.exception("psutil.net_connections() failed")
        return []

    results: List[ConnectionInfo] = []
    for c in raw_connections:
        process_name: Optional[str] = None
        if c.pid:
            try:
                process_name = psutil.Process(c.pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process_name = None

        protocol = _PROTO_MAP.get((c.family, c.type), str(c.type))
        laddr_ip = c.laddr.ip if c.laddr else None
        laddr_port = c.laddr.port if c.laddr else None
        raddr_ip = c.raddr.ip if c.raddr else None
        raddr_port = c.raddr.port if c.raddr else None

        interface_name = ip_to_iface.get(laddr_ip) if laddr_ip else None

        results.append(
            ConnectionInfo(
                pid=c.pid,
                process_name=process_name,
                protocol=protocol,
                laddr_ip=laddr_ip,
                laddr_port=laddr_port,
                raddr_ip=raddr_ip,
                raddr_port=raddr_port,
                state=c.status,
                interface_name=interface_name,
            )
        )
    return results
