"""Interface (network adapter) metadata model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from multilink_manager.models.enums import InterfaceStatus, InterfaceType


@dataclass
class InterfaceInfo:
    """Static/slow-changing metadata describing one network adapter.

    ``classification_source`` documents *how* ``if_type`` was determined
    (e.g. "windows-netadapter-physicalmediatype", "psutil-fallback-unknown")
    so the UI/README can be transparent about accuracy per platform.
    """

    name: str
    friendly_name: str
    index: Optional[int]
    if_type: InterfaceType
    status: InterfaceStatus
    ipv4_addresses: List[str] = field(default_factory=list)
    ipv6_addresses: List[str] = field(default_factory=list)
    ipv4_gateway: Optional[str] = None
    ipv6_gateway: Optional[str] = None
    mac_address: Optional[str] = None
    link_speed_mbps: Optional[float] = None
    network_profile: Optional[str] = None
    classification_source: str = "unknown"
