"""Opt-in automatic active/backup IPv4 default-route failover.

This package is the "v0.2-style" extension: it is the *only* part of the
application allowed to mutate Windows network configuration, and only when
a user has explicitly enabled it via the GUI (disabled by default,
requires Administrator privileges). It is deliberately split into two
independently testable layers:

- ``policy.py`` -- pure, OS-independent decision logic (hysteresis,
  N-cycle confirmation, hold-down). No PowerShell/OS/Qt calls at all.
- ``controller.py`` -- orchestrates ``policy.py`` decisions against
  ``multilink_manager.networking.routes.RouteController`` (the actual
  Windows mutation layer), including save/verify/restore. No Qt/GUI
  imports; integrated into ``gui/worker.py``'s ``MonitorWorker`` so all
  route commands run on that background thread, never the GUI thread.

See the README "Automatic failover (opt-in)" section for the full
algorithm, safety model, and manual verification procedure.
"""
