"""Per-interface monitoring selection (enable/disable), independent of any
GUI widget and independent of the OS.

This is a purely in-application, in-memory concept: deselecting an
interface here never touches Windows adapter state (never disables/
disconnects it, never changes routes) -- it only controls whether *this
application* includes that interface's data in probing, live traffic/
distribution/history, link health, and automatic-steering candidates.
Deselected interfaces remain fully visible in the Interfaces tab (with
their checkbox unchecked) so the user can re-enable them at any time.

Classification-based defaults (never hardcoded by adapter name):
Ethernet/Wi-Fi interfaces default **enabled**; every other classification
(``OTHER`` -- which covers virtual/VPN/loopback-style adapters -- and
``UNKNOWN``) defaults **disabled**. An explicit user override (tracked by
interface *name*) always takes precedence over the type-based default,
and is retained for the lifetime of ``InterfaceSelectionManager`` even if
the interface temporarily disappears and later reappears (e.g. unplugged/
replugged), since the override dict is keyed purely by name and is never
cleared on disappearance.

Thread safety: ``InterfaceSelectionManager`` guards its override dict with
a plain ``threading.Lock``. This is sufficient (unlike the opt-in
steering feature's enable/disable, which must defer to the next tick on
``MonitorWorker``'s own thread) because setting/reading an override here
never issues any OS/network call -- it is safe to call directly from the
GUI thread while ``MonitorWorker`` concurrently reads it once per tick on
its own background thread.
"""

from __future__ import annotations

import threading
from typing import Dict, Iterable, List, Optional, Set

from multilink_manager.models.connection import ConnectionInfo
from multilink_manager.models.enums import InterfaceType
from multilink_manager.models.interface import InterfaceInfo


def default_enabled_for_type(if_type: InterfaceType) -> bool:
    """Pure predicate: the type-based default enabled state for an
    interface with no explicit user override.

    Based purely on ``InterfaceType`` classification (itself derived from
    Windows adapter metadata / NDIS physical media type -- see
    ``networking/interfaces.py``), never on the adapter's display name.
    """
    return if_type in (InterfaceType.ETHERNET, InterfaceType.WIFI)


def resolve_enabled_map(
    interfaces: Iterable[InterfaceInfo], overrides: Dict[str, bool]
) -> Dict[str, bool]:
    """Pure helper (no I/O, no locking): resolve enabled/disabled for every
    given interface, given an explicit ``{name: enabled}`` override dict.

    An interface with a name present in ``overrides`` always uses that
    value; any other interface falls back to
    :func:`default_enabled_for_type`. This means a newly-appeared physical
    Ethernet/Wi-Fi interface with no prior override defaults to enabled,
    and a newly-appeared Other/Unknown interface defaults to disabled,
    automatically.
    """
    result: Dict[str, bool] = {}
    for iface in interfaces:
        if iface.name in overrides:
            result[iface.name] = overrides[iface.name]
        else:
            result[iface.name] = default_enabled_for_type(iface.if_type)
    return result


def filter_enabled_interfaces(
    interfaces: Iterable[InterfaceInfo], enabled_map: Dict[str, bool]
) -> List[InterfaceInfo]:
    """Pure helper: return only the interfaces whose resolved state in
    ``enabled_map`` is ``True`` (missing entries are treated as disabled,
    never as an implicit "enabled")."""
    return [iface for iface in interfaces if enabled_map.get(iface.name, False)]


def filter_connections_for_display(
    connections: Iterable[ConnectionInfo], enabled_names: Set[str]
) -> List[ConnectionInfo]:
    """Pure helper: drop connections attributed (by exact local-IP
    ownership) to a currently-deselected interface, while keeping every
    connection whose interface could not be attributed at all
    (``interface_name is None``) -- unattributed connections are always
    shown regardless of selection, since we cannot know which interface
    (if any) they belong to.
    """
    return [
        c for c in connections
        if c.interface_name is None or c.interface_name in enabled_names
    ]


def visible_interfaces_for_default_view(
    interfaces: Iterable[InterfaceInfo], enabled_map: Dict[str, bool]
) -> List[InterfaceInfo]:
    """Pure helper for the Interfaces tab's default ("Show all adapters"
    OFF) view: hide a *disabled* Other/Unknown interface (virtual/VPN/
    loopback-style adapters typically end up here), while keeping every
    other interface visible.

    An interface remains visible in this default view when EITHER:

    - it is currently enabled (any classification -- including an
      Other/Unknown interface the user has explicitly enabled, which must
      stay visible so they can toggle it back off), OR
    - it is classified Ethernet or Wi-Fi, even if currently disabled (so
      a physical NIC that simply isn't plugged in / is momentarily
      deselected remains discoverable and re-enable-able without needing
      "Show all adapters").

    A *disabled* Other/Unknown interface is the only case hidden by this
    predicate. Toggling "Show all adapters" ON bypasses this filter
    entirely and lists every interface, matching the full
    ``enabled_map``-driven checkbox behaviour that existed before this
    default-hide behaviour was added.
    """
    return [
        iface for iface in interfaces
        if enabled_map.get(iface.name, False) or iface.if_type in (InterfaceType.ETHERNET, InterfaceType.WIFI)
    ]


class InterfaceSelectionManager:
    """Thread-safe holder of explicit per-interface enable/disable
    overrides, keyed by interface name.

    One instance is intended to be owned by the GUI (``MainWindow``) for
    the lifetime of the application (so overrides survive Stop/Start of
    monitoring, not just a single ``MonitorWorker`` session) and shared
    read-only-ish with ``MonitorWorker`` via constructor injection.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: Dict[str, bool] = {}

    def set_override(self, name: str, enabled: bool) -> None:
        """Explicitly enable/disable one interface by name. Safe to call
        from the GUI thread at any time, including while monitoring is
        running -- ``MonitorWorker`` picks up the new value at the start
        of its next tick via :meth:`resolve`."""
        with self._lock:
            self._overrides[name] = bool(enabled)

    def get_override(self, name: str) -> Optional[bool]:
        with self._lock:
            return self._overrides.get(name)

    def get_overrides(self) -> Dict[str, bool]:
        with self._lock:
            return dict(self._overrides)

    def resolve(self, interfaces: Iterable[InterfaceInfo]) -> Dict[str, bool]:
        """Resolve the enabled/disabled state of every given interface,
        combining current overrides with the type-based default for any
        interface never explicitly toggled."""
        with self._lock:
            overrides = dict(self._overrides)
        return resolve_enabled_map(interfaces, overrides)

    def filter_enabled(self, interfaces: Iterable[InterfaceInfo]) -> List[InterfaceInfo]:
        interfaces = list(interfaces)
        enabled_map = self.resolve(interfaces)
        return filter_enabled_interfaces(interfaces, enabled_map)

    def select_physical_defaults(self, interfaces: Iterable[InterfaceInfo]) -> None:
        """Reset the override for every currently-known interface back to
        its type-based default (Ethernet/Wi-Fi enabled, everything else
        disabled) -- used by the GUI's 'Select physical defaults' button.
        Interfaces not currently known are left untouched (they will still
        get a sensible type-based default the first time they are seen,
        with no override present)."""
        with self._lock:
            for iface in interfaces:
                self._overrides[iface.name] = default_enabled_for_type(iface.if_type)

    def deselect_all(self, interfaces: Iterable[InterfaceInfo]) -> None:
        """Force every currently-known interface's override to disabled --
        used by the GUI's 'Deselect all' button."""
        with self._lock:
            for iface in interfaces:
                self._overrides[iface.name] = False
