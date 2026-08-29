"""Network interface discovery.

Combines cross-platform data from ``psutil`` (addresses, link state, link
speed) with Windows-only metadata retrieved via PowerShell CIM/NetAdapter
cmdlets (physical media type for classification, default-route gateways,
and network category/profile). No interface is ever renamed, connected,
disconnected, or otherwise mutated -- this module only reads state.

Classification never relies on matching adapter display names/strings such
as "Wi-Fi" or "Ethernet". On Windows it uses the ``PhysicalMediaType``/
``MediaType`` values reported by ``Get-NetAdapter`` (backed by the NDIS
driver's media type, not a name heuristic). When that metadata is
unavailable (non-Windows, PowerShell failure, virtual adapters that don't
report a physical media type) the interface is classified ``OTHER`` or
``UNKNOWN`` and ``classification_source`` documents why, rather than
guessing from the name.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import psutil

from multilink_manager.models.enums import InterfaceStatus, InterfaceType
from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.utils.logging_config import get_logger
from multilink_manager.utils.platform_utils import is_windows, run_powershell_json

logger = get_logger(__name__)

# NDIS physical media types considered Ethernet-family / Wi-Fi-family.
# Reference: Get-NetAdapter's PhysicalMediaType is sourced from the NDIS
# miniport driver (ndis.h NDIS_PHYSICAL_MEDIUM), not a display string.
_ETHERNET_PHYSICAL_MEDIA = {"802.3"}
_WIFI_PHYSICAL_MEDIA = {"native802.11", "802.11"}


def _classify_from_windows_metadata(meta: dict) -> tuple[InterfaceType, str]:
    physical = str(meta.get("PhysicalMediaType") or "").strip().lower()
    media = str(meta.get("MediaType") or "").strip().lower()
    if physical in _ETHERNET_PHYSICAL_MEDIA or media == "802.3":
        return InterfaceType.ETHERNET, "windows-netadapter-physicalmediatype"
    if physical in _WIFI_PHYSICAL_MEDIA or "802.11" in media:
        return InterfaceType.WIFI, "windows-netadapter-physicalmediatype"
    if physical or media:
        return InterfaceType.OTHER, "windows-netadapter-physicalmediatype-other"
    return InterfaceType.UNKNOWN, "windows-netadapter-metadata-missing"


def _get_windows_adapter_metadata() -> Dict[str, dict]:
    """Return Get-NetAdapter data keyed by adapter Name."""
    cmd = (
        "Get-NetAdapter | Select-Object Name, InterfaceIndex, InterfaceDescription, "
        "MediaType, PhysicalMediaType, Status, MacAddress, LinkSpeed "
        "| ConvertTo-Json -Depth 3"
    )
    data = run_powershell_json(cmd)
    if data is None:
        return {}
    if isinstance(data, dict):
        data = [data]
    result = {}
    for item in data:
        name = item.get("Name")
        if name:
            result[name] = item
    return result


def _get_windows_gateways() -> Dict[int, dict]:
    """Return {ifIndex: {"ipv4_gateway": str|None, "ipv6_gateway": str|None}}."""
    cmd = (
        "Get-NetRoute -DestinationPrefix '0.0.0.0/0','::/0' -ErrorAction SilentlyContinue "
        "| Select-Object ifIndex, DestinationPrefix, NextHop, RouteMetric "
        "| Sort-Object RouteMetric | ConvertTo-Json -Depth 3"
    )
    data = run_powershell_json(cmd)
    if data is None:
        return {}
    if isinstance(data, dict):
        data = [data]
    result: Dict[int, dict] = {}
    for item in data:
        idx = item.get("ifIndex")
        if idx is None:
            continue
        entry = result.setdefault(idx, {"ipv4_gateway": None, "ipv6_gateway": None})
        next_hop = item.get("NextHop")
        if not next_hop or next_hop in ("0.0.0.0", "::"):
            continue
        if item.get("DestinationPrefix") == "0.0.0.0/0" and entry["ipv4_gateway"] is None:
            entry["ipv4_gateway"] = next_hop
        elif item.get("DestinationPrefix") == "::/0" and entry["ipv6_gateway"] is None:
            entry["ipv6_gateway"] = next_hop
    return result


def _get_windows_network_profiles() -> Dict[int, str]:
    """Return {ifIndex: NetworkCategory} e.g. 'Public'/'Private'/'DomainAuthenticated'.

    ``NetworkCategory`` is serialized explicitly via ``.ToString()`` because
    ``ConvertTo-Json`` otherwise emits the underlying numeric enum value
    (e.g. ``0``) instead of the human-readable name.
    """
    cmd = (
        "Get-NetConnectionProfile -ErrorAction SilentlyContinue "
        "| Select-Object InterfaceIndex, "
        "@{Name='NetworkCategory';Expression={$_.NetworkCategory.ToString()}} "
        "| ConvertTo-Json -Depth 3"
    )
    data = run_powershell_json(cmd)
    if data is None:
        return {}
    if isinstance(data, dict):
        data = [data]
    result = {}
    for item in data:
        idx = item.get("InterfaceIndex")
        category = item.get("NetworkCategory")
        if idx is not None and category is not None:
            result[idx] = str(category)
    return result


def _parse_windows_link_speed(link_speed: Optional[str]) -> Optional[float]:
    """Parse strings like '1 Gbps' / '100 Mbps' / '0 bps' into Mbps."""
    if not link_speed:
        return None
    parts = link_speed.strip().split()
    if len(parts) != 2:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].lower()
    if unit.startswith("gbps"):
        return value * 1000.0
    if unit.startswith("mbps"):
        return value
    if unit.startswith("kbps"):
        return value / 1000.0
    if unit.startswith("bps"):
        return value / 1_000_000.0
    return None


def _get_windows_interface_metrics() -> Dict[int, int]:
    """Return {ifIndex: InterfaceMetric} for IPv4 interfaces.

    Used together with each route's ``RouteMetric`` to compute Windows'
    *effective* route metric (``RouteMetric + InterfaceMetric``, lower
    wins) for path preference -- see ``get_preferred_ipv4_interface_name``.
    """
    cmd = (
        "Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue "
        "| Select-Object ifIndex, InterfaceMetric | ConvertTo-Json -Depth 2"
    )
    data = run_powershell_json(cmd)
    if not data:
        return {}
    if isinstance(data, dict):
        data = [data]
    result: Dict[int, int] = {}
    for item in data:
        idx = item.get("ifIndex")
        metric = item.get("InterfaceMetric")
        if idx is not None and metric is not None:
            result[idx] = metric
    return result


def get_ipv4_interface_metrics() -> Dict[int, int]:
    """Public alias for :func:`_get_windows_interface_metrics`.

    Exposed for reuse by ``networking/routes.py`` (the opt-in steering
    feature's read-only candidate-metric planning) so both modules share
    one PowerShell query implementation instead of duplicating it.
    """
    return _get_windows_interface_metrics()


def get_ipv4_default_route_metrics() -> Dict[int, int]:
    """Return ``{ifIndex: RouteMetric}`` for each interface's IPv4 default
    route (``0.0.0.0/0``), keeping the lowest ``RouteMetric`` seen per
    interface if Windows reports more than one. Read-only; used by
    ``get_preferred_ipv4_interface_name`` and reused by
    ``networking/routes.py``.
    """
    cmd = (
        "Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue "
        "| Select-Object ifIndex, RouteMetric | ConvertTo-Json -Depth 2"
    )
    data = run_powershell_json(cmd)
    if not data:
        return {}
    if isinstance(data, dict):
        data = [data]
    result: Dict[int, int] = {}
    for item in data:
        idx = item.get("ifIndex")
        metric = item.get("RouteMetric")
        if idx is None or metric is None:
            continue
        if idx not in result or metric < result[idx]:
            result[idx] = metric
    return result


def get_preferred_ipv4_interface_name() -> Optional[str]:
    """Return the name of the interface Windows currently uses as the
    observed/default IPv4 path.

    Windows selects the "best" default route using an *effective* metric
    of ``RouteMetric + InterfaceMetric`` (lower wins), not the route
    metric alone -- two interfaces can have identical/near-identical
    ``RouteMetric`` values yet very different ``InterfaceMetric`` values
    (e.g. Wi-Fi is usually assigned a higher, less-preferred interface
    metric than Ethernet by Windows' automatic metric feature), which
    changes which one is actually preferred. This function mirrors that
    calculation using read-only ``Get-NetRoute``/``Get-NetIPInterface``
    queries; it never adds, removes, or reorders routes.

    Returns ``None`` on non-Windows platforms or if the route/adapter
    metadata cannot be read.
    """
    route_metrics = get_ipv4_default_route_metrics()
    if not route_metrics:
        return None

    interface_metrics = get_ipv4_interface_metrics()

    best_if_index: Optional[int] = None
    best_effective_metric: Optional[float] = None
    for if_index, route_metric in route_metrics.items():
        interface_metric = interface_metrics.get(if_index, 0)
        effective_metric = route_metric + interface_metric
        if best_effective_metric is None or effective_metric < best_effective_metric:
            best_effective_metric = effective_metric
            best_if_index = if_index

    if best_if_index is None:
        return None

    adapters = _get_windows_adapter_metadata()
    for name, meta in adapters.items():
        if meta.get("InterfaceIndex") == best_if_index:
            return name
    return None


def discover_interfaces() -> List[InterfaceInfo]:
    """Enumerate network interfaces with classification, addresses, gateways,
    MAC, negotiated link speed, and network profile where available.

    Never raises for platform-related reasons: on non-Windows platforms (or
    if Windows metadata retrieval fails) interfaces are still returned using
    psutil data alone, with unavailable fields left as ``None`` and
    ``if_type`` degraded to UNKNOWN/OTHER.
    """
    try:
        addrs = psutil.net_if_addrs()
    except Exception:  # pragma: no cover - defensive, psutil should not raise
        logger.exception("psutil.net_if_addrs() failed")
        addrs = {}
    try:
        stats = psutil.net_if_stats()
    except Exception:  # pragma: no cover
        logger.exception("psutil.net_if_stats() failed")
        stats = {}

    win_meta_by_name: Dict[str, dict] = {}
    win_gateways_by_index: Dict[int, dict] = {}
    win_profiles_by_index: Dict[int, str] = {}
    if is_windows():
        win_meta_by_name = _get_windows_adapter_metadata()
        win_gateways_by_index = _get_windows_gateways()
        win_profiles_by_index = _get_windows_network_profiles()

    interfaces: List[InterfaceInfo] = []
    for name, family_addrs in addrs.items():
        ipv4: List[str] = []
        ipv6: List[str] = []
        mac: Optional[str] = None
        for a in family_addrs:
            family_name = getattr(a.family, "name", str(a.family))
            if family_name == "AF_INET":
                ipv4.append(a.address)
            elif family_name == "AF_INET6":
                # Strip Windows zone-id suffix (e.g. "%12") for readability.
                ipv6.append(a.address.split("%")[0])
            elif family_name in ("AF_LINK", "AF_PACKET") and a.address:
                mac = a.address

        stat = stats.get(name)
        status = InterfaceStatus.UNKNOWN
        speed_mbps: Optional[float] = None
        if stat is not None:
            status = InterfaceStatus.UP if stat.isup else InterfaceStatus.DOWN
            if stat.speed and stat.speed > 0:
                speed_mbps = float(stat.speed)

        win_meta = win_meta_by_name.get(name)
        if_type = InterfaceType.UNKNOWN
        classification_source = "no-windows-metadata"
        index: Optional[int] = None
        gateway_v4: Optional[str] = None
        gateway_v6: Optional[str] = None
        profile: Optional[str] = None

        if win_meta:
            if_type, classification_source = _classify_from_windows_metadata(win_meta)
            index = win_meta.get("InterfaceIndex")
            if speed_mbps is None:
                speed_mbps = _parse_windows_link_speed(win_meta.get("LinkSpeed"))
            if not mac and win_meta.get("MacAddress"):
                mac = win_meta["MacAddress"]
            if win_meta.get("Status") and status == InterfaceStatus.UNKNOWN:
                status = (
                    InterfaceStatus.UP
                    if str(win_meta["Status"]).lower() == "up"
                    else InterfaceStatus.DOWN
                )
            if index is not None:
                gw = win_gateways_by_index.get(index, {})
                gateway_v4 = gw.get("ipv4_gateway")
                gateway_v6 = gw.get("ipv6_gateway")
                profile = win_profiles_by_index.get(index)
        else:
            if_type = InterfaceType.OTHER if ipv4 or ipv6 else InterfaceType.UNKNOWN

        interfaces.append(
            InterfaceInfo(
                name=name,
                friendly_name=name,
                index=index,
                if_type=if_type,
                status=status,
                ipv4_addresses=ipv4,
                ipv6_addresses=ipv6,
                ipv4_gateway=gateway_v4,
                ipv6_gateway=gateway_v6,
                mac_address=mac,
                link_speed_mbps=speed_mbps,
                network_profile=profile,
                classification_source=classification_source,
            )
        )

    return interfaces
