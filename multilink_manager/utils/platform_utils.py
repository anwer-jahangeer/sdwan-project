"""Platform detection and safe PowerShell invocation helpers.

All Windows-only metadata (adapter classification, gateways, network
profile) is retrieved through PowerShell CIM/NetAdapter cmdlets rather than
hardcoded name matching. On non-Windows platforms (or if PowerShell is
unavailable/fails), these helpers return ``None``/``[]`` so callers can
degrade cleanly instead of raising -- this is what allows the whole
application, including discovery code, to be imported and unit tested on
any OS.
"""

from __future__ import annotations

import json
import platform
import subprocess
import threading
from typing import Any, List, Optional

from multilink_manager.utils.logging_config import get_logger

logger = get_logger(__name__)

_POWERSHELL_TIMEOUT_S = 8.0

# Bounds total concurrent child-process creation (powershell.exe / ping.exe)
# across all threads. MonitorWorker's own thread and LinkProber's probe
# thread pool can otherwise attempt to spawn dozens of external processes
# simultaneously (one per interface/target); some Windows environments (in
# particular sandboxed/monitored ones where every new process is intercepted
# by security tooling) are measurably less stable under a large burst of
# concurrent process creation from multiple threads. Since every external
# call here is already advisory/best-effort (failures degrade to ``None``
# rather than raising), bounding concurrency to a small number trades a
# little parallelism for materially better reliability with no functional
# downside -- probes still run concurrently, just not all at once.
_PROCESS_CREATION_SEMAPHORE = threading.Semaphore(4)


def is_windows() -> bool:
    return platform.system() == "Windows"


def _windows_is_admin_impl() -> bool:
    """Actual ctypes call, isolated into its own function purely so tests
    can monkeypatch it directly (``ctypes.windll`` does not exist at all on
    non-Windows platforms, so it cannot be exercised for real outside a
    Windows process)."""
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def is_admin() -> bool:
    """Return True if this process is running with Windows Administrator
    privileges.

    Always ``False`` on non-Windows platforms -- elevation is a
    Windows-specific concept and only matters for the opt-in automatic
    route-steering feature (``steering/``), which is Windows-only and
    disabled by default. Never raises: any failure to query elevation
    status is treated as "not admin" so callers fail safely closed (the
    mutating steering feature simply refuses to enable) rather than ever
    assuming elevation that cannot be confirmed.
    """
    if not is_windows():
        return False
    try:
        return _windows_is_admin_impl()
    except Exception:
        logger.warning("Failed to determine Administrator elevation status; assuming not elevated")
        return False


def run_powershell_json(command: str, timeout: float = _POWERSHELL_TIMEOUT_S) -> Optional[Any]:
    """Run a PowerShell command that ends in ``| ConvertTo-Json`` and parse it.

    Returns ``None`` on any failure (not on Windows, PowerShell missing,
    non-zero exit, timeout, or invalid JSON). Failures are logged at
    WARNING/DEBUG level, never raised, so discovery/monitoring code can
    always fall back to a degraded-but-functional state.
    """
    if not is_windows():
        return None
    try:
        with _PROCESS_CREATION_SEMAPHORE:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("PowerShell invocation failed: %s", exc)
        return None

    output = completed.stdout.strip()
    if completed.returncode != 0:
        # Some read-only Get-Net* cmdlets (e.g. Get-NetRoute with a
        # DestinationPrefix that has no IPv6 match) set a non-zero process
        # exit code even with -ErrorAction SilentlyContinue and valid JSON
        # on stdout. Only treat this as a hard failure when there is no
        # usable output to parse.
        logger.debug(
            "PowerShell command exited %s (stderr=%s); attempting to parse stdout anyway",
            completed.returncode, completed.stderr.strip()
        )
        if not output:
            return None

    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        logger.debug("Failed to parse PowerShell JSON output: %s", exc)
        return None


def run_ping(args: List[str], timeout: float = 15.0) -> Optional[str]:
    """Run the platform ping executable and return raw stdout, or None on failure."""
    exe = "ping.exe" if is_windows() else "ping"
    try:
        with _PROCESS_CREATION_SEMAPHORE:
            completed = subprocess.run(
                [exe, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("ping invocation failed: %s", exc)
        return None
    return completed.stdout
