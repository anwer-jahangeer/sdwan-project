"""Windows IPv4 default-route steering: typed, testable route/interface
metric controller for the opt-in automatic active/backup failover feature.

**Safety model / scope (read this before touching this module).**

Everything in this module is read-only by default -- it can enumerate
current effective metrics, saved settings, and default-route presence
without changing anything. Mutation only ever happens through
``RouteController.apply_preferred_metric`` and
``RouteController.restore_setting``, both of which:

- Operate exclusively on IPv4 *interface metrics* via
  ``Set-NetIPInterface`` (``AutomaticMetric`` / ``InterfaceMetric``).
  This changes how Windows *ranks* an existing default route, it never
  creates, removes, or reassigns a route, never touches IPv6, and never
  connects/disconnects/enables/disables an adapter or installs a driver.
- Are only ever invoked by ``multilink_manager.steering.controller
  .SteeringController`` for a target interface that has already been
  read-only-validated to have an *operational* IPv4 default route (see
  ``has_operational_ipv4_default_route``) -- this module refuses to
  mutate an interface that doesn't already have Windows' own default
  route through it.
- Always report ``(success, error_message)`` rather than raising, and
  every caller is expected to save the interface's original
  ``OriginalInterfaceSetting`` *before* mutating and restore it via
  ``restore_setting`` on disable/stop/close, or on switch-verification
  failure.

This module is Windows-only in effect (every mutating/reading call is a
no-op returning a safe default off Windows) but is always importable and
callable on any platform so it can be unit tested with a fake/mocked
``run_powershell_json`` -- automated tests must never invoke real
PowerShell mutation commands; see ``tests/test_routes.py`` and
``tests/test_steering_controller.py``, which monkeypatch this module's
``run_powershell_json`` reference or substitute a fake ``RouteController``
entirely.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.steering import OriginalInterfaceSetting
from multilink_manager.networking.interfaces import (
    get_ipv4_default_route_metrics,
    get_ipv4_interface_metrics,
    get_preferred_ipv4_interface_name,
)
from multilink_manager.utils.logging_config import get_logger
from multilink_manager.utils.platform_utils import is_windows, run_powershell_json

logger = get_logger(__name__)


def _run_mutating_command(body: str) -> Tuple[bool, Optional[str]]:
    """Run a mutating PowerShell statement, wrapped in try/catch so
    success/failure and any error message are captured as JSON rather than
    relying on the process exit code alone (some ``Set-Net*`` cmdlets can
    still set a non-zero exit code on partial/harmless warnings). Never
    raises.
    """
    wrapped = (
        "try { " + body + "; Write-Output (@{success=$true} | ConvertTo-Json) } "
        "catch { Write-Output (@{success=$false; error=$_.Exception.Message} | ConvertTo-Json) }"
    )
    result = run_powershell_json(wrapped)
    if not isinstance(result, dict):
        return False, "no result from PowerShell (command failed to execute or produced no output)"
    success = bool(result.get("success"))
    error = result.get("error")
    return success, (None if success else str(error or "unknown error"))


class RouteController:
    """Thin, typed wrapper around the Windows PowerShell commands used by
    the opt-in automatic steering feature.

    Every method is safe to call on any platform (returns a safe
    read-only/failure default off Windows) and never raises, so
    ``SteeringController`` can be exercised in unit tests without a real
    Windows machine by monkeypatching ``run_powershell_json`` in this
    module, or by substituting an entirely fake object with the same
    method surface.
    """

    def get_effective_metrics(self, interfaces: List[InterfaceInfo]) -> Dict[str, int]:
        """Read-only: ``{interface_name: effective_metric}`` for every
        interface with a known index that actually has an IPv4 default
        route, where
        ``effective_metric = RouteMetric + InterfaceMetric`` (missing
        ``InterfaceMetric`` treated as 0) -- the same calculation Windows
        itself uses (see ``networking.interfaces.get_preferred_ipv4_interface_name``).
        Used to compute a target metric that is guaranteed lower than
        every other eligible interface's *current* effective metric
        without needing to mutate those other interfaces at all.

        Interfaces with no IPv4 default route at all are excluded
        entirely (not defaulted to route metric ``0``) -- including them
        with a fabricated ``0`` route metric would corrupt target-metric
        planning by making a route-less interface look like the
        lowest-metric (most preferred) competitor.
        """
        route_metrics = get_ipv4_default_route_metrics()
        interface_metrics = get_ipv4_interface_metrics()
        result: Dict[str, int] = {}
        for iface in interfaces:
            if iface.index is None or iface.index not in route_metrics:
                continue
            result[iface.name] = route_metrics[iface.index] + interface_metrics.get(iface.index, 0)
        return result

    def get_route_metric(self, interface_index: int) -> Optional[int]:
        """Read-only: this interface's current IPv4 default-route
        ``RouteMetric``, or ``None`` if it has none / cannot be read."""
        return get_ipv4_default_route_metrics().get(interface_index)

    def get_preferred_interface_name(self) -> Optional[str]:
        """Read-only: Windows' current observed preferred IPv4 interface
        (by effective metric). Used to *verify* a switch actually took
        effect -- see ``SteeringController._perform_switch``."""
        return get_preferred_ipv4_interface_name()

    def has_operational_ipv4_default_route(self, interface_index: int) -> bool:
        """Read-only: True if this interface currently owns at least one
        operational IPv4 default route (``0.0.0.0/0``). Steering never
        makes an interface preferred unless Windows already has a usable
        default route through it -- this module only ever reprioritizes an
        *existing* route via its interface metric, it never creates one.
        """
        if not is_windows():
            return False
        cmd = (
            f"Get-NetRoute -InterfaceIndex {int(interface_index)} -DestinationPrefix '0.0.0.0/0' "
            "-AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object RouteMetric "
            "| ConvertTo-Json -Depth 2"
        )
        data = run_powershell_json(cmd)
        if data is None:
            return False
        if isinstance(data, dict):
            return True
        return bool(data)

    def get_ip_setting(self, interface_index: int) -> Optional[OriginalInterfaceSetting]:
        """Read-only: the current ``AutomaticMetric``/``InterfaceMetric``
        for one interface's IPv4 stack, to be saved before mutation.
        Returns ``None`` off-Windows or on any read failure -- callers
        must never proceed to mutate an interface whose original settings
        could not be captured.
        """
        if not is_windows():
            return None
        cmd = (
            f"Get-NetIPInterface -InterfaceIndex {int(interface_index)} -AddressFamily IPv4 "
            "-ErrorAction Stop | Select-Object InterfaceAlias, ifIndex, InterfaceMetric, "
            "@{Name='AutomaticMetric';Expression={$_.AutomaticMetric.ToString()}} "
            "| ConvertTo-Json -Depth 2"
        )
        data = run_powershell_json(cmd)
        if not isinstance(data, dict):
            return None
        name = data.get("InterfaceAlias")
        idx = data.get("ifIndex", interface_index)
        metric = data.get("InterfaceMetric")
        auto = data.get("AutomaticMetric")
        if name is None or metric is None or auto is None:
            return None
        return OriginalInterfaceSetting(
            interface_name=str(name),
            interface_index=int(idx),
            automatic_metric_enabled=(str(auto).strip().lower() == "enabled"),
            interface_metric=int(metric),
        )

    def apply_preferred_metric(self, interface_index: int, metric: int) -> Tuple[bool, Optional[str]]:
        """Mutating: disable automatic metric and set an explicit,
        low ``InterfaceMetric`` on this interface only, so its *effective*
        metric becomes the lowest among eligible interfaces. Never issues
        ``Set-NetRoute`` route creation/removal -- Windows' own route
        selection picks up the changed effective metric automatically for
        the default route(s) already present on the system.
        """
        if not is_windows():
            return False, "not running on Windows"
        body = (
            f"Set-NetIPInterface -InterfaceIndex {int(interface_index)} -AddressFamily IPv4 "
            f"-AutomaticMetric Disabled -InterfaceMetric {int(metric)} -ErrorAction Stop"
        )
        return _run_mutating_command(body)

    def restore_setting(self, setting: OriginalInterfaceSetting) -> Tuple[bool, Optional[str]]:
        """Mutating: restore exactly the ``AutomaticMetric``/
        ``InterfaceMetric`` that were in effect before this application
        changed them."""
        if not is_windows():
            return False, "not running on Windows"
        if setting.automatic_metric_enabled:
            body = (
                f"Set-NetIPInterface -InterfaceIndex {setting.interface_index} -AddressFamily IPv4 "
                "-AutomaticMetric Enabled -ErrorAction Stop"
            )
        else:
            body = (
                f"Set-NetIPInterface -InterfaceIndex {setting.interface_index} -AddressFamily IPv4 "
                f"-AutomaticMetric Disabled -InterfaceMetric {int(setting.interface_metric)} -ErrorAction Stop"
            )
        return _run_mutating_command(body)
