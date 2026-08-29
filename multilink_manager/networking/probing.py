"""Background, per-interface link probing (RTT/loss/jitter/reachability).

Probing binds the *source* address of each ping to a specific interface's
IPv4 address using ``ping.exe -S <source_ip>`` on Windows -- the
Windows-supported source-selection mechanism for ICMP echo requests. This
does **not** change routes or bind sockets in a way that affects any other
process; it only affects which local address this particular ping process
uses, and Windows routing may still choose a different egress interface if
the destination is not reachable via the expected gateway for that source
address (see README "Source-bound ping limitation").

This module never blocks the GUI: probing runs on background daemon
threads managed by ``LinkProber``, and results are read by polling
thread-safe snapshots.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from typing import Callable, Dict, List, Optional

from multilink_manager.models.interface import InterfaceInfo
from multilink_manager.models.probe import ProbeResult
from multilink_manager.utils.logging_config import get_logger
from multilink_manager.utils.platform_utils import is_windows, run_ping

logger = get_logger(__name__)

_RTT_RE = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*loss", re.IGNORECASE)
_SENT_RECV_RE = re.compile(
    r"Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)", re.IGNORECASE
)

DEFAULT_PUBLIC_TARGET = "1.1.1.1"
DEFAULT_PROBE_INTERVAL_S = 5.0
DEFAULT_PROBE_COUNT = 4
DEFAULT_PROBE_TIMEOUT_MS = 1000


def parse_ping_output(output: str, samples_sent_requested: int) -> ProbeResult:
    """Pure parsing helper (platform-independent, easy to unit test).

    Returns a *partial* ProbeResult (interface_name/target/target_type/
    timestamp left blank for the caller to fill in) built from raw ping
    stdout text.
    """
    rtts = [float(m) for m in _RTT_RE.findall(output or "")]
    sent, received = None, None
    m = _SENT_RECV_RE.search(output or "")
    if m:
        sent, received = int(m.group(1)), int(m.group(2))
    else:
        sent = samples_sent_requested
        received = len(rtts)

    loss_pct: Optional[float] = None
    loss_match = _LOSS_RE.search(output or "")
    if loss_match:
        loss_pct = float(loss_match.group(1))
    elif sent:
        loss_pct = 100.0 * (1 - (received / sent))

    rtt_ms: Optional[float] = statistics.mean(rtts) if rtts else None
    jitter_ms: Optional[float] = None
    if len(rtts) >= 2:
        diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
        jitter_ms = statistics.mean(diffs)

    reachable: Optional[bool] = None
    if sent is not None:
        reachable = received is not None and received > 0

    return ProbeResult(
        interface_name="",
        target="",
        target_type="",
        timestamp=0.0,
        rtt_ms=rtt_ms,
        loss_pct=loss_pct,
        jitter_ms=jitter_ms,
        reachable=reachable,
        samples_sent=sent or 0,
        samples_received=received or 0,
        error=None if output else "no ping output received",
    )


def probe_once(
    source_ip: str,
    target: str,
    target_type: str,
    interface_name: str,
    count: int = DEFAULT_PROBE_COUNT,
    timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS,
) -> ProbeResult:
    """Run one blocking round of pings from ``source_ip`` to ``target``.

    Intended to be called from a worker thread, never from the GUI thread.
    """
    if is_windows():
        args = ["-S", source_ip, "-n", str(count), "-w", str(timeout_ms), target]
    else:
        # Best-effort only: most non-Windows ping implementations do not
        # support binding an arbitrary local source address the same way;
        # this path exists purely so the module degrades instead of
        # crashing when imported/exercised on non-Windows systems.
        args = ["-c", str(count), "-W", str(max(1, timeout_ms // 1000)), target]

    output = run_ping(args, timeout=(timeout_ms / 1000.0) * count + 5.0)
    result = parse_ping_output(output or "", count)
    result.interface_name = interface_name
    result.target = target
    result.target_type = target_type
    result.timestamp = time.time()
    if output is None:
        result.error = "ping executable unavailable or invocation failed"
        result.reachable = None
    return result


class LinkProber:
    """Runs background, per-interface probing on a fixed cadence.

    Each tick, every interface with a known IPv4 source address is probed
    (sequentially, on this prober's own background thread) against its
    gateway (if known) and a configurable public endpoint. Interfaces that
    disappear have their stale results removed immediately at the start of
    the next tick (see ``_tick``), so vanished adapters do not linger in
    Link Health; they start fresh again automatically once discovery
    reports them once more (since discovery is re-evaluated every tick via
    ``interfaces_provider``). Probing never blocks the GUI thread or
    MonitorWorker: it runs entirely on its own daemon thread, independent
    of the GUI refresh cadence.
    """

    def __init__(
        self,
        interfaces_provider: Callable[[], List[InterfaceInfo]],
        interval_s: float = DEFAULT_PROBE_INTERVAL_S,
        count: int = DEFAULT_PROBE_COUNT,
        timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS,
        public_target: str = DEFAULT_PUBLIC_TARGET,
    ) -> None:
        self._interfaces_provider = interfaces_provider
        self.interval_s = interval_s
        self.count = count
        self.timeout_ms = timeout_ms
        self.public_target = public_target

        self._lock = threading.Lock()
        self._results: Dict[str, Dict[str, ProbeResult]] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="LinkProber", daemon=True
        )
        self._thread.start()
        logger.info("LinkProber started (interval=%.1fs, public_target=%s)",
                    self.interval_s, self.public_target)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s + 5)
        logger.info("LinkProber stopped")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def get_results(self) -> Dict[str, Dict[str, ProbeResult]]:
        with self._lock:
            return {k: dict(v) for k, v in self._results.items()}

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:  # pragma: no cover - defensive
                logger.exception("LinkProber tick failed")
            self._stop_event.wait(self.interval_s)

    def _tick(self) -> None:
        interfaces = self._interfaces_provider() or []
        current_names = {iface.name for iface in interfaces}

        # Remove stale results for interfaces that are no longer reported
        # by discovery *before* launching new probes, so a vanished
        # adapter's last-known (and now meaningless) RTT/loss/reachability
        # never lingers in Link Health.
        with self._lock:
            stale = set(self._results.keys()) - current_names
            for name in stale:
                logger.info(
                    "Interface '%s' disappeared; removing stale link-health results", name
                )
                del self._results[name]

        # Probe every eligible interface/target sequentially on this
        # background thread rather than via a nested thread pool. LinkProber
        # already runs independently of the GUI thread and MonitorWorker, so
        # this remains fully "background only" and non-blocking; avoiding a
        # third layer of concurrent worker threads (on top of this thread and
        # MonitorWorker's own QThread) has proven materially more stable for
        # sustained runs, since some Windows environments are measurably less
        # reliable when many threads race to spawn external processes at once.
        for iface in interfaces:
            if not iface.ipv4_addresses:
                continue
            source_ip = iface.ipv4_addresses[0]
            targets = []
            if iface.ipv4_gateway:
                targets.append((iface.ipv4_gateway, "gateway"))
            targets.append((self.public_target, "public"))

            for target, target_type in targets:
                if self._stop_event.is_set():
                    return
                try:
                    result = probe_once(
                        source_ip, target, target_type, iface.name, self.count, self.timeout_ms
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Probe job raised an exception")
                    continue
                with self._lock:
                    self._results.setdefault(result.interface_name, {})[
                        result.target_type
                    ] = result
