"""Background, per-interface link probing (ICMP RTT/loss/jitter/
reachability plus HTTP(S) request-latency/status probing).

Probing binds the *source* address of each probe to a specific
interface's IPv4 address:

- ICMP probes (gateway + configured ICMP targets) use
  ``ping.exe -S <source_ip>`` on Windows -- the Windows-supported
  source-selection mechanism for ICMP echo requests.
- HTTP(S) probes use Python's stdlib ``http.client.HTTPConnection`` /
  ``HTTPSConnection`` with ``source_address=(source_ip, 0)`` -- the
  standard-library, source-bound mechanism for outbound TCP sockets. No
  external HTTP library or driver is required.

Neither mechanism changes routes or affects any other process; each only
affects which local address that one ping/socket uses, and Windows
routing may still choose a different egress interface if the destination
is not reachable via the expected gateway for that source address (see
README "Source-bound ping/HTTP limitation").

This module never blocks the GUI: probing runs on a background daemon
thread managed by ``LinkProber``, and results are read by polling
thread-safe snapshots.
"""

from __future__ import annotations

import http.client
import re
import statistics
import threading
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

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

# Backward-compatible single-target default (matches the first entry of
# DEFAULT_ICMP_TARGETS below); kept for any external code/tests that still
# reference it directly.
DEFAULT_PUBLIC_TARGET = "1.1.1.1"

# Multi-target ICMP defaults: two well-known, reliable public resolvers on
# different providers/networks, so a single provider's outage does not by
# itself make an otherwise-healthy interface look unreachable (see
# scoring/aggregation.py).
DEFAULT_ICMP_TARGETS: List[str] = ["1.1.1.1", "8.8.8.8"]

# HTTPS connectivity-check endpoints: both return a lightweight
# "204 No Content" response with no page body when reachable, and are
# widely used exactly for this purpose (Android/Chrome captive-portal
# checks), making them a reasonable, low-overhead default for verifying
# real HTTPS reachability (TLS handshake + HTTP response), not just ICMP.
DEFAULT_HTTPS_TARGETS: List[str] = [
    "https://www.gstatic.com/generate_204",
    "https://connectivitycheck.gstatic.com/generate_204",
]

DEFAULT_PROBE_INTERVAL_S = 5.0
DEFAULT_PROBE_COUNT = 4
DEFAULT_PROBE_TIMEOUT_MS = 1000

# HTTPS probes are considerably more expensive per attempt than an ICMP
# echo (TCP + TLS handshake, at least one full request/response), so a
# smaller repeat count and a bounded per-request timeout are used by
# default to keep a full LinkProber tick's wall-clock cost reasonable
# (see README "Ping-based / HTTP-based probing is coarse" limitation).
DEFAULT_HTTPS_PROBE_COUNT = 2
DEFAULT_HTTPS_TIMEOUT_S = 3.0

INTERNET_TARGET_KINDS = ("icmp", "https")


def parse_icmp_targets(raw: str) -> List[str]:
    """Parse a comma-separated ICMP probe target list (IPv4 addresses or
    hostnames).

    Returns the cleaned, de-duplicated (order-preserving) list of
    non-empty targets. At least one target is required -- an empty result
    raises ``ValueError`` with a clear message, so the GUI/CLI can surface
    it instead of silently probing nothing.
    """
    targets: List[str] = []
    seen = set()
    for part in (raw or "").split(","):
        target = part.strip()
        if not target:
            continue
        if target not in seen:
            seen.add(target)
            targets.append(target)
    if not targets:
        raise ValueError(
            "At least one ICMP probe target is required "
            "(comma-separated IPv4 address(es)/hostname(s), e.g. '1.1.1.1, 8.8.8.8')."
        )
    return targets


def parse_https_targets(raw: str) -> List[str]:
    """Parse a comma-separated HTTPS/HTTP probe URL list, validating each
    entry has an ``http``/``https`` scheme and a hostname.

    Unlike ICMP targets, an empty result is allowed (HTTPS probing is
    optional). Any malformed entry raises ``ValueError`` naming exactly
    which entry was invalid, rather than silently dropping it.
    """
    targets: List[str] = []
    seen = set()
    invalid: List[str] = []
    for part in (raw or "").split(","):
        target = part.strip()
        if not target:
            continue
        parsed = urlsplit(target)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            invalid.append(target)
            continue
        if target not in seen:
            seen.add(target)
            targets.append(target)
    if invalid:
        raise ValueError(
            "Invalid HTTPS/HTTP probe target(s) (need an http:// or https:// URL with a "
            "hostname): " + ", ".join(invalid)
        )
    return targets


def parse_ping_output(output: str, samples_sent_requested: int) -> ProbeResult:
    """Pure parsing helper (platform-independent, easy to unit test).

    Returns a *partial* ProbeResult (interface_name/target/target_kind/
    target_id/timestamp left blank for the caller to fill in) built from
    raw ping stdout text.
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
        target_kind="",
        target="",
        target_id="",
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
    target_kind: str,
    interface_name: str,
    count: int = DEFAULT_PROBE_COUNT,
    timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS,
) -> ProbeResult:
    """Run one blocking round of ICMP pings from ``source_ip`` to
    ``target`` (used for both ``target_kind="gateway"`` and
    ``target_kind="icmp"``).

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
    result.target_kind = target_kind
    result.target_id = f"{target_kind}:{target}"
    result.timestamp = time.time()
    if output is None:
        result.error = "ping executable unavailable or invocation failed"
        result.reachable = None
    return result


def _default_https_connection_factory(scheme: str, host: str, port: int, timeout_s: float, source_ip: str):
    """Real (non-test) connection factory: stdlib ``http.client``, bound to
    ``source_ip`` via ``source_address`` -- the standard-library
    source-bound mechanism for outbound TCP sockets, requiring no external
    HTTP library or driver."""
    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return conn_cls(host, port, timeout=timeout_s, source_address=(source_ip, 0))


def probe_https_once(
    source_ip: str,
    url: str,
    interface_name: str,
    count: int = DEFAULT_HTTPS_PROBE_COUNT,
    timeout_s: float = DEFAULT_HTTPS_TIMEOUT_S,
    connection_factory: Optional[Callable] = None,
) -> ProbeResult:
    """Run ``count`` sequential source-bound HTTP(S) requests to ``url``
    from ``source_ip`` and summarize them into one ``ProbeResult``.

    ``connection_factory(scheme, host, port, timeout_s, source_ip)`` must
    return an object exposing ``request(method, path, headers=...)``,
    ``getresponse()`` (returning an object with ``.status`` and
    ``.read()``), and ``close()`` -- exactly the subset of
    ``http.client.HTTPConnection``'s interface this function uses. This is
    injectable purely so unit tests can exercise parsing/aggregation logic
    with a fake connection and no real network access; production code
    always uses the real stdlib connection classes (see
    ``_default_https_connection_factory``).

    A GET request is used (not HEAD) because some connectivity-check
    endpoints only implement GET reliably; the response body is drained
    and discarded (these endpoints return an empty/near-empty body, e.g.
    "204 No Content"). Any HTTP response at all (including a 4xx/5xx
    status) proves reachability over this source-bound path -- only a
    genuine connect/TLS/timeout/DNS failure counts as unreachable. A
    Any HTTP response is a successful transport sample: TCP/TLS and an
    HTTP round trip completed, regardless of application-level status.
    A 4xx/5xx status is still recorded via ``error`` so endpoint failures
    remain visible, but it is not misreported as packet loss.

    ``rtt_ms`` on the returned ``ProbeResult`` is **HTTP request/response
    latency**, not an ICMP round-trip time -- this function's caller and
    the UI must present it as such (``target_kind="https"`` on the result
    makes this unambiguous downstream).
    """
    factory = connection_factory or _default_https_connection_factory
    target_id = f"https:{url}"
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "https").lower()
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    if not host:
        return ProbeResult(
            interface_name=interface_name, target_kind="https", target=url,
            target_id=target_id, timestamp=time.time(), rtt_ms=None, loss_pct=None,
            jitter_ms=None, reachable=None, samples_sent=0, samples_received=0,
            error="malformed URL: no hostname",
        )

    latencies: List[float] = []
    statuses: List[int] = []
    errors: List[str] = []
    attempts = max(1, count)

    for _ in range(attempts):
        start = time.monotonic()
        conn = None
        try:
            conn = factory(scheme, host, port, timeout_s, source_ip)
            conn.request(
                "GET", path,
                headers={"User-Agent": "multilink-manager-probe/1", "Connection": "close"},
            )
            response = conn.getresponse()
            status = response.status
            try:
                response.read()
            except Exception:  # pragma: no cover - draining is best-effort
                pass
            elapsed_ms = (time.monotonic() - start) * 1000.0
            statuses.append(status)
            latencies.append(elapsed_ms)
            if not 200 <= status < 400:
                errors.append(f"HTTP {status} (endpoint reachable but returned an error status)")
        except Exception as exc:  # noqa: BLE001 - any connect/TLS/timeout failure
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass

    received = len(statuses)
    loss_pct = 100.0 * (1 - (received / attempts))
    rtt_ms = statistics.mean(latencies) if latencies else None
    jitter_ms = None
    if len(latencies) >= 2:
        diffs = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
        jitter_ms = statistics.mean(diffs)
    # Reachability is proven by receiving ANY HTTP response at all (even a
    # 4xx/5xx status still means the TCP+TLS handshake and an HTTP
    # round-trip succeeded over this source-bound path) -- distinct from
    # `received`/`loss_pct`, which count transport responses rather than
    # interpreting an HTTP application status as network packet loss.
    reachable = len(statuses) > 0
    http_status = statuses[-1] if statuses else None
    error = None
    if errors:
        error = f"{len(errors)}/{attempts} request(s) failed or errored: {errors[-1]}"

    return ProbeResult(
        interface_name=interface_name, target_kind="https", target=url,
        target_id=target_id, timestamp=time.time(), rtt_ms=rtt_ms, loss_pct=loss_pct,
        jitter_ms=jitter_ms, reachable=reachable, samples_sent=attempts,
        samples_received=received, http_status=http_status, error=error,
    )


class LinkProber:
    """Runs background, per-interface probing on a fixed cadence.

    Each tick, every interface with a known IPv4 source address is probed
    (sequentially, on this prober's own background thread) against its
    gateway (if known), every configured ICMP target, and every configured
    HTTPS target. Interfaces that disappear have their stale results
    removed immediately at the start of the next tick (see ``_tick``), so
    vanished adapters do not linger in Link Health; they start fresh again
    automatically once discovery reports them once more (since discovery
    is re-evaluated every tick via ``interfaces_provider``). Probing never
    blocks the GUI thread or MonitorWorker: it runs entirely on its own
    daemon thread, independent of the GUI refresh cadence.

    Results are stored as ``{interface_name: {target_id: ProbeResult}}``,
    where ``target_id`` (e.g. ``"gateway:192.168.1.1"``,
    ``"icmp:1.1.1.1"``, ``"https:https://www.gstatic.com/generate_204"``)
    is a stable, unique key per target -- so multiple ICMP targets or
    multiple HTTPS targets never overwrite each other the way a plain
    ``target_kind`` key would.
    """

    def __init__(
        self,
        interfaces_provider: Callable[[], List[InterfaceInfo]],
        interval_s: float = DEFAULT_PROBE_INTERVAL_S,
        count: int = DEFAULT_PROBE_COUNT,
        timeout_ms: int = DEFAULT_PROBE_TIMEOUT_MS,
        icmp_targets: Optional[List[str]] = None,
        https_targets: Optional[List[str]] = None,
        https_count: int = DEFAULT_HTTPS_PROBE_COUNT,
        https_timeout_s: float = DEFAULT_HTTPS_TIMEOUT_S,
        public_target: Optional[str] = None,
    ) -> None:
        self._interfaces_provider = interfaces_provider
        self.interval_s = interval_s
        self.count = count
        self.timeout_ms = timeout_ms
        # ``public_target`` is a deprecated backward-compatible alias: if
        # given (and icmp_targets is not), it becomes the sole ICMP
        # target. Prefer icmp_targets/https_targets for new code.
        if icmp_targets is not None:
            self.icmp_targets = list(icmp_targets)
        elif public_target:
            self.icmp_targets = [public_target]
        else:
            self.icmp_targets = list(DEFAULT_ICMP_TARGETS)
        self.https_targets = list(https_targets) if https_targets is not None else list(DEFAULT_HTTPS_TARGETS)
        self.https_count = https_count
        self.https_timeout_s = https_timeout_s
        # Kept for any code/tests that still read ``public_target`` off a
        # LinkProber instance; reflects the first configured ICMP target.
        self.public_target = self.icmp_targets[0] if self.icmp_targets else None

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
        logger.info(
            "LinkProber started (interval=%.1fs, icmp_targets=%s, https_targets=%s)",
            self.interval_s, self.icmp_targets, self.https_targets,
        )

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

            jobs = []  # (kind, target)
            if iface.ipv4_gateway:
                jobs.append(("gateway", iface.ipv4_gateway))
            for target in self.icmp_targets:
                jobs.append(("icmp", target))
            for url in self.https_targets:
                jobs.append(("https", url))

            for kind, target in jobs:
                if self._stop_event.is_set():
                    return
                try:
                    if kind == "https":
                        result = probe_https_once(
                            source_ip, target, iface.name, self.https_count, self.https_timeout_s
                        )
                    else:
                        result = probe_once(
                            source_ip, target, kind, iface.name, self.count, self.timeout_ms
                        )
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Probe job raised an exception")
                    continue
                with self._lock:
                    self._results.setdefault(result.interface_name, {})[
                        result.target_id
                    ] = result
