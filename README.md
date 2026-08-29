# MultiLink Manager - MVP v0.1 + opt-in automatic failover (v0.2-style extension)

> **Looking for the Android version?** See
> [`android_multilink_manager/`](android_multilink_manager/README.md) - a
> separate, independent Kotlin + Jetpack Compose app for stock, non-root
> Android phones (e.g. Realme GT 7 Pro). It shares no code with this
> Windows project; see its own README for scope and limitations.

A Windows desktop application for observing the health of a multi-WAN /
multi-link machine: which network interfaces exist, how they are
classified, how much traffic they are carrying, which one Windows is
currently using as its default path, how well each one probes to its
gateway and to the public Internet, and which processes/connections are
using which local interface.

**Monitoring (v0.1) is strictly observational and always on.** It never
modifies routes, never connects/disconnects/enables/disables adapters, and
never installs drivers, kernel filters, or packet-capture components.
Every metric is either read from the OS (via `psutil` or Windows
PowerShell CIM/NetAdapter cmdlets) or computed from those reads. Where a
metric cannot be obtained without doing something out of scope (e.g.
per-connection byte counters), the application says so explicitly instead
of inventing a number.

**Automatic failover (v0.2-style extension) is the one deliberate,
explicitly documented exception to that rule, and it is opt-in and OFF by
default.** Only when a user with Administrator privileges explicitly
clicks **Enable automatic steering...** in the Steering tab does this
application mutate anything at all - and even then, only a target
interface's IPv4 interface metric (`Set-NetIPInterface`, IPv4 default
route scope only), never routes themselves, never adapters, never
drivers. Every original setting changed is saved and is always restored on
Disable, Stop, or normal application close. See
[Automatic failover (opt-in)](#automatic-failover-opt-in) below for the
full algorithm, safety model, and limitations before enabling it.


---

## Table of contents

1. [Architecture](#architecture)
2. [Installation](#installation)
3. [Running the application](#running-the-application)
4. [Windows executable (prebuilt build)](#windows-executable-prebuilt-build)
5. [Metric source / method / accuracy](#metric-source--method--accuracy)
6. [Scoring formula](#scoring-formula)
7. [Manual verification procedures (8 scenarios)](#manual-verification-procedures)
8. [Automatic failover (opt-in)](#automatic-failover-opt-in)
9. [Supported vs. unsupported metrics](#supported-vs-unsupported-metrics)
10. [Known limitations](#known-limitations)
11. [Recommended future architecture](#recommended-future-architecture)

---

## Architecture

```
multilink_manager/
  app.py                  Entry point: argument parsing, logging setup, Qt event loop
  models/                 Typed dataclasses shared by every layer (no logic)
    enums.py              InterfaceType, InterfaceStatus, TargetType
    interface.py           InterfaceInfo
    traffic.py             CounterSample, RateSample, DistributionEntry
    probe.py                ProbeResult
    connection.py           ConnectionInfo
    history.py               HistoryRecord (+ CSV field order)
    score.py                  ScoreResult
    steering.py               SteeringConfig, CandidateHealth, SteeringDecision,
                               OriginalInterfaceSetting, SteeringStatus (opt-in failover, pure data)
  networking/              Read-only OS/network interaction (except routes.py, see below)
    interfaces.py          Interface discovery + classification + gateways + profile
    probing.py              Background, per-interface source-bound ping probing
    routes.py                Opt-in-only: typed Set-NetIPInterface wrapper with
                              save/apply/verify/restore semantics (steering feature)
  monitoring/              Turns raw OS state into typed samples
    counters.py            Cumulative counters -> delta rates (Mbps/pps)
    distribution.py         RX/TX/combined percentage distribution
    connections.py           psutil.net_connections() -> ConnectionInfo (no bytes)
    selection.py              Per-interface monitoring enable/disable (app-level
                               only -- never touches the OS adapter/routes)
  scoring/
    scorer.py                Documented 0-100 link quality formula
  steering/                Opt-in automatic active/backup failover (OFF by default)
    policy.py                Pure, OS-independent hysteresis/hold-down/N-cycle decision engine
    controller.py             Orchestrates policy vs. routes.RouteController; save/verify/restore/rollback
  storage/
    history_store.py         In-memory rolling time-window history + CSV export
  utils/
    platform_utils.py        is_windows(), is_admin(), safe PowerShell/ping subprocess helpers
    logging_config.py        Central logging configuration
  gui/                      PySide6 desktop UI
    worker.py                 QThread that ticks the pipeline above (+ steering) off the GUI thread
    charts.py                  Custom QPainter-based time-series chart (no QtCharts dep)
    main_window.py              Tabs, controls, and Qt-signal-driven rendering (incl. Steering tab)
  tests/                    OS-independent unit tests (platform calls are mocked)
```

**Data flow per tick** (default every 2s, configurable):

```
discover_interfaces()          -> InterfaceInfo[]           (networking/interfaces.py; EVERY discovered interface)
InterfaceSelectionManager.resolve() -> {name: enabled}       (monitoring/selection.py; override or Ethernet/Wi-Fi-by-type default)
                                                              filter to enabled-only for everything below except
                                                              the Interfaces tab, which always lists every interface
get_preferred_ipv4_interface_name() -> str|None             (effective metric = RouteMetric + InterfaceMetric, lowest wins; NOT filtered by selection -- always the real OS-observed path)
read_counter_samples()          -> CounterSample{}          (monitoring/counters.py; read for EVERY interface, for baseline continuity)
CounterMonitor.update()          -> RateSample{}             (delta vs previous sample, computed for every interface; emitted/Snapshot fields below are filtered to enabled interfaces only)
compute_distribution()           -> DistributionEntry{}      (monitoring/distribution.py; RX/TX/combined, enabled interfaces only)
compute_distribution_by_type()   -> DistributionEntry{}      (monitoring/distribution.py; grouped by Ethernet/Wi-Fi/Other, Snapshot.type_distribution, enabled interfaces only)
list_connections()               -> ConnectionInfo[]         (monitoring/connections.py; attributed against every interface, then filtered -- unattributed connections always kept)
LinkProber.get_results()         -> ProbeResult{iface:{gateway,public}}  (independent background cadence; provider returns enabled interfaces only, stale entries pruned immediately on disappearance OR deselection)
compute_score() per target       -> ScoreResult              (scoring/scorer.py; Snapshot.target_scores["iface"]["gateway"|"public"], enabled interfaces only)
choose primary_target per iface  -> "public" if scored, else "gateway" fallback (Snapshot.primary_target; used for HistoryRecord/history + Link Health "(primary)" label)
HistoryStore.add_many()          -> retained for the configured time window, using each interface's primary_target score/RTT/loss/jitter (enabled interfaces only)
SteeringController.tick()        -> SteeringStatus            (steering/controller.py; no-op unless explicitly enabled; sees every interface for the VPN/Other guard and target-metric planning, but enabled_names restricts which interfaces can ever become a switch candidate; carried as Snapshot.steering_status)
Snapshot                         -> emitted via Qt signal to MainWindow for rendering
```

`LinkProber` runs on its own daemon thread, completely decoupled from the
GUI refresh cadence. Each tick it first drops any stale results for
interfaces that have disappeared since the previous tick (so a removed
adapter never lingers in Link Health), then probes each configured target
(gateway + public endpoint) for each known interface **sequentially, in a
plain loop** on that single background thread - deliberately *not* via a
nested `ThreadPoolExecutor`. This is a stability-motivated design choice:
during development, running probes through an additional thread-pool layer
underneath both a `QThread` and `LinkProber`'s own thread (three
independently process-spawning thread layers at once) was observed to
occasionally trigger a native crash at Python interpreter shutdown in a
constrained test environment. Sequential probing removes that third layer
entirely; for a typical handful of interfaces and two targets each, a full
probe pass still completes well within the default 5s probe interval. A
small `threading.Semaphore` in `utils/platform_utils.py` additionally caps
how many `powershell.exe`/`ping.exe` child processes may be in flight at
once from any caller, as a cheap extra safety margin. `MonitorWorker` is a
`QThread`; all its work (discovery, psutil calls, PowerShell calls, probe
polling, and steering decisions/mutations when enabled) happens off the Qt
GUI thread, and results are only ever pushed to the GUI via the
`snapshot_ready` Qt signal - the GUI never blocks and no worker code
touches a QWidget directly. `MonitorWorker` also logs, at `INFO`, whenever
an interface appears/disappears/changes status or a target's reachability
changes for an interface, and logs full per-tick measurements at `DEBUG` -
so normal operation does not flood `INFO` with per-tick noise, but state
transitions are always visible at the default log level.

`SteeringController` (owned one-per-session by `MonitorWorker`) is the
**only** part of the codebase permitted to mutate anything, and only ever
runs on `MonitorWorker`'s own background thread - the GUI thread only ever
calls thread-safe `request_enable_steering()`/`request_disable_steering()`
setters (no I/O), which are processed at the very start of the next tick.
`MonitorWorker.run()`'s `finally` block unconditionally calls
`SteeringController.disable()` so that stopping monitoring - or closing
the app, which calls `stop_monitoring()` - always restores any changed
setting before the worker thread exits, even if the user forgot to click
Disable first.

**Interface selection (enable/disable per adapter for monitoring only)**
is a separate, purely in-application concept from all of the above and
from the opt-in steering feature - it never issues any OS command at all.
`InterfaceSelectionManager` (`monitoring/selection.py`) is owned by
`MainWindow` (so overrides survive across separate Start/Stop sessions,
not just one `MonitorWorker`'s lifetime) and injected into each
`MonitorWorker` at construction. Toggling the **Enabled** checkbox in the
Interfaces tab calls `set_override(name, enabled)` directly from the GUI
thread; this is safe without deferring to the next tick (unlike steering
enable/disable) because it only ever guards a plain dict with a
`threading.Lock` - no PowerShell/ping/adapter command is ever involved.
`MonitorWorker` resolves the current enabled/disabled state once per tick
(explicit override, else Ethernet/Wi-Fi-by-type default) and filters
probing, live traffic/distribution/history, link health, and steering
candidates to enabled interfaces only; the Interfaces tab itself always
lists every discovered interface (enabled or not) so a deselected adapter
can be re-enabled at any time.

---

## Installation

Requires Python 3.9+ (tested with 3.12) on Windows 10/11 for full
functionality; degrades cleanly (reduced classification/gateway/profile
data) on other platforms for running the automated test suite.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt`:
```
PySide6>=6.5
psutil>=5.9
pytest>=7.4
```

## Running the application

```powershell
python -m multilink_manager.app
```

Optional flags:

```powershell
python -m multilink_manager.app --log-level DEBUG --log-file multilink_manager.log --public-target 1.1.1.1
```

`--public-target` only pre-fills the GUI's **Public target** field (see
below); it is optional on the command line because the field itself is
editable and validated in the GUI before every Start.

In the window:

1. Enter a **Public target** (IPv4 address or hostname, e.g. `1.1.1.1`) in
   the control bar text field. This is the configurable public endpoint
   probed independently per interface; it is required and validated
   (non-empty) when you click **Start** - an empty field is rejected with
   an inline error and monitoring will not start. The gateway target is
   always automatic (each interface's own default gateway) and needs no
   input.
2. Click **Start** to begin monitoring (background worker thread starts;
   link probing starts on its own background thread using the public
   target you entered). The public-target field is disabled while running
   to avoid changing it mid-session; **Stop** re-enables it.
3. Adjust **Interval (s)** to change how often the GUI refreshes (counter
   read / connection scan cadence). This does not change the probe
   cadence, which is independent.
4. Adjust **Retention (min)** to change how long history samples are kept
   in memory (default 60 minutes) - this **also drives the visible time
   window of every history chart** on the Live Traffic tab, so shrinking
   or growing retention immediately narrows/widens what the charts show,
   in addition to pruning older `HistoryStore` records.
5. **Clear History** empties the in-memory history store **and every
   history chart** (RX, TX, Combined+TOTAL, type-distribution, latency,
   loss, score) in one action - none are left showing stale data.
6. **Export CSV** writes the currently retained history (subject to the
   retention window) to a CSV file you choose.
7. Click **Stop** to halt both the refresh worker and background probing.
   Closing the window also stops monitoring cleanly.

Tabs:

- **Dashboard** - three panels: (1) **Current path**, the interface
  Windows currently prefers for the default IPv4 route computed from each
  interface's *effective* route metric (`RouteMetric + InterfaceMetric`,
  lowest wins - not `RouteMetric` alone), shown for information only; this
  application never switches or reorders routes. If the currently
  Windows-preferred interface has been deselected in the Interfaces tab
  (see below), the label still shows the true OS-observed path but appends
  a clear `[DESELECTED - excluded from monitoring/steering]` note - the
  app never hides or misrepresents Windows' actual routing decision, it
  only clarifies that this app is not currently tracking that interface.
  (2) **RX/TX/Combined traffic distribution**, current-tick percentage
  bars per interface. (3) **Link Health**, one row per interface **per
  target** (gateway and public each get their own row with their own
  RTT/loss/jitter/ reachability/score); the row whose score is used for
  history/scoring purposes is labelled `(primary)` - public-preferred,
  falling back to gateway only when the public probe itself has no usable
  result. Deselected interfaces never appear in Link Health.
- **Live Traffic** - an explicit per-interface counters table (cumulative
  RX/TX bytes, cumulative RX/TX packets, cumulative RX/TX errors and
  discards, current RX/TX/Total Mbps, RX/TX pps - 14 columns), plus seven
  rolling time-series charts: RX Mbps, TX Mbps, Combined Mbps (per
  interface plus a `TOTAL` series), Ethernet/Wi-Fi/Other percentage
  distribution over time, latency (ms), packet loss (%), and link score,
  each per interface. All seven charts share the same retention-driven
  time window and are all cleared together by **Clear History**.
- **Interfaces** - full interface metadata table (type, classification
  source, status, addresses, MAC, negotiated link speed, network profile,
  gateways) for **every** discovered interface, plus a leading
  **Enabled** checkbox column controlling whether that interface is
  included in monitoring (see "Interface selection" below). This tab
  always lists every discovered interface regardless of its enabled
  state, so a deselected adapter remains visible and can be re-enabled at
  any time. Two buttons above the table: **Select physical defaults**
  resets every interface back to its type-based default (checked for
  Ethernet/Wi-Fi, unchecked for Other/Unknown/virtual/VPN/loopback -
  classification is never based on adapter name); **Deselect all**
  unchecks every interface. Toggling a checkbox takes effect on the next
  tick without needing to Stop/Start.
- **Applications / Connections** - process/PID/endpoint/protocol/state per
  connection, with interface attribution and an explicit "unavailable"
  byte-counter column.
- **Steering (opt-in)** - disabled by default; lets an Administrator-
  elevated session enable automatic active/backup IPv4 default-route
  failover. See [Automatic failover (opt-in)](#automatic-failover-opt-in)
  below for the full algorithm, safety model, and required confirmation
  steps before using it.

### Interface selection (per-adapter monitoring enable/disable)

Every discovered interface can be independently included in or excluded
from monitoring via the **Enabled** checkbox on the Interfaces tab. This
is a purely app-level, in-memory concept - it never issues any OS
command, never changes routes/metrics, and never disconnects/reconfigures
an adapter; a deselected interface's OS state is completely untouched.

- **Defaults** (no explicit override yet): enabled for interfaces
  classified `ETHERNET` or `WIFI`; disabled for `OTHER`/`UNKNOWN` (this is
  where virtual adapters, VPN clients, and loopback/pseudo-interfaces end
  up, since classification is by Windows media-type metadata, never by
  adapter name). A newly appearing physical Ethernet/Wi-Fi adapter is
  enabled by default; a newly appearing `Other` adapter is disabled by
  default.
- **Explicit overrides** always win over the type-based default and are
  keyed by interface **name**, so your choice is remembered for the
  current app session even if that adapter temporarily disappears and
  later reappears (e.g. unplug/replug a USB NIC, or a VPN client
  reconnecting under the same adapter name).
- **What gets excluded** when an interface is deselected: link probing
  (gateway/public RTT/loss/jitter/reachability), the Live Traffic
  counters table and all seven history charts, the RX/TX/combined
  distribution (both current-tick bars and the percentage-over-time
  chart), history retained for CSV export, Link Health rows on the
  Dashboard, and eligibility as an automatic-steering switch candidate.
  Connections/applications whose local IP address exactly matches a
  deselected interface are hidden from the Applications/Connections tab;
  connections that cannot be attributed to any interface at all
  (`laddr` unknown/loopback/wildcard) remain shown regardless, since they
  were never attributed to the deselected interface in the first place.
- **What is never hidden**: the Interfaces tab itself always lists every
  discovered interface so it can be re-enabled later, and the Dashboard's
  "Current path" always reports Windows' real, currently-preferred
  interface even if that interface happens to be deselected (annotated
  with a `[DESELECTED]` note rather than substituted or hidden) - this
  app never misrepresents what Windows itself is actually doing.
- **Steering safety**: a deselected interface can never be chosen as an
  automatic-failover switch target, regardless of its score, because the
  candidate-building step is filtered by the same enabled set used
  everywhere else.

---

## Windows executable (prebuilt build)

A one-file, windowed Windows executable (`MultiLinkManager.exe`) can be
built with [PyInstaller](https://pyinstaller.org/) and is automatically
built and tested by CI (see `.github/workflows/windows-build.yml`) on
every push/PR touching the app and on manual `workflow_dispatch` runs.

### Download and run (from a CI artifact)

1. Open the workflow run's **Actions** tab on GitHub, select the latest
   successful **Windows Build** run, and download the
   `MultiLinkManager-windows-exe` artifact (a zip containing
   `MultiLinkManager.exe`). Artifacts are retained for 14 days.
2. Unzip anywhere and double-click `MultiLinkManager.exe` - no installer,
   no admin prompt, no registry writes. It is a portable, single-file
   app: PyInstaller's one-file mode extracts its bundled Python runtime to
   a private temp folder on each launch and cleans it up on exit.
3. **Windows SmartScreen / "unknown publisher" warning**: because this
   build is not code-signed, Windows may show *"Windows protected your
   PC"* on first run. This is expected for any unsigned, freshly-built
   executable - click **More info -> Run anyway** to proceed. There is no
   way to avoid this warning without a paid code-signing certificate,
   which is out of scope for this MVP.
4. **Administrator privileges are only needed for steering.** Running and
   using the app normally - monitoring, link health, traffic, interface
   selection - all work fine as a standard (non-elevated) user, exactly
   as when running from source. Only clicking **Enable automatic
   steering** on the Steering tab requires (and checks for) an elevated
   session; the app itself never requests or forces elevation at launch.

### Building locally

```powershell
pip install -r requirements.txt -r requirements-build.txt
pyinstaller packaging\MultiLinkManager.spec --noconfirm
# Output: dist\MultiLinkManager.exe
```

`requirements-build.txt` adds only PyInstaller on top of the app's normal
runtime requirements, so a plain `pip install -r requirements.txt` (used
to run the app or the test suite) never pulls in PyInstaller. The spec
(`packaging/MultiLinkManager.spec`) builds from the thin entry-point
wrapper `run_multilink_manager.py` (needed because PyInstaller's static
analysis wants a plain script, not a `python -m package` invocation), sets
`console=False` for a windowed app, and does **not** request or embed any
elevation manifest - launching the EXE never triggers a UAC prompt;
elevation is only ever required interactively at the in-app "Enable
automatic steering" click, exactly as when running from source.

---

## Metric source / method / accuracy

| Metric | Source | Method | Accuracy / caveats |
|---|---|---|---|
| Interface name/index | `psutil.net_if_addrs()` / Windows `Get-NetAdapter` | Direct read | Exact |
| Interface type (Ethernet/Wi-Fi/Other) | Windows `Get-NetAdapter` `PhysicalMediaType`/`MediaType` | NDIS media-type classification, **not** name matching | Exact when Windows metadata is available; falls back to `OTHER`/`UNKNOWN` (never guessed) off-Windows or for virtual adapters lacking a physical media type |
| Status (up/down) | `psutil.net_if_stats().isup`, cross-checked with `Get-NetAdapter.Status` | Direct read | Exact, but reflects the OS's momentary view; can flicker during adapter reconfiguration |
| IPv4/IPv6 addresses | `psutil.net_if_addrs()` | Direct read | Exact |
| Gateway(s) | Windows `Get-NetRoute -DestinationPrefix 0.0.0.0/0`/`::/0`, lowest metric per interface | Read-only route table query | Exact when a default route exists for that interface; `None` (not guessed) otherwise |
| Preferred/default IPv4 path (shown on Dashboard "Current path") | Windows `Get-NetRoute` (`RouteMetric`) joined with `Get-NetIPInterface` (`InterfaceMetric`) | Computes each candidate interface's **effective metric = `RouteMetric + InterfaceMetric`**, lowest wins - matching how Windows itself actually selects the outbound interface, not `RouteMetric` alone | Falls back to `RouteMetric`-only ranking if `InterfaceMetric` cannot be queried (logged); `None` when no default IPv4 route exists at all. Never mutated - this is a read-only, observational best-effort reconstruction of Windows' own route-selection decision |
| MAC address | `psutil.net_if_addrs()` (`AF_LINK`) or `Get-NetAdapter.MacAddress` | Direct read | Exact |
| Negotiated link speed | `psutil.net_if_stats().speed`, or Windows `Get-NetAdapter.LinkSpeed` parsed to Mbps | Direct read of NIC-negotiated speed | This is the **link's negotiated capacity** (e.g. "1 Gbps port"), **not** observed throughput and **not** Internet throughput - see distinctions below |
| Network profile | Windows `Get-NetConnectionProfile.NetworkCategory` | Direct read | `Public`/`Private`/`DomainAuthenticated`; `None` off-Windows |
| Cumulative bytes/packets/errors/discards | `psutil.net_io_counters(pernic=True)` | Direct read of OS-maintained interface counters (IP Helper API on Windows) | Exact cumulative counters as reported by the OS; wraps/resets are detected (see below) |
| RX/TX Mbps, pps | Computed in `monitoring/counters.py` | `(byte_delta * 8) / (interval_s * 1e6)`; `packet_delta / interval_s` | This is **observed local interface traffic** (everything crossing that NIC), **not** the throughput of any single Internet path or application |
| RX/TX/combined distribution % | Computed in `monitoring/distribution.py` | Interface's byte delta as a % of the summed delta across all interfaces for that tick | 0% for all interfaces when total traffic for the tick is zero (not NaN, not an artificial even split) |
| RTT / loss / jitter / reachability | `ping.exe -S <source_ip>` per interface | Windows-supported source-address binding for ICMP Echo; RTT = mean of successful replies; loss = 100% * (1 - received/sent) using ping.exe's own summary line when available; jitter = mean absolute difference between consecutive successful RTT samples | See "Source-bound ping limitation" below. `None` fields mean "not measurable this cycle", never a fabricated value |
| Link quality score | `scoring/scorer.py` | Deterministic formula from loss/latency/jitter/reachability (see below) | `None` when reachability itself is unknown |
| Process/PID/endpoints/protocol/state | `psutil.net_connections(kind="inet")` + `psutil.Process(pid).name()` | Direct read | Requires elevation for full visibility into other users'/system processes; degrades to an empty list (logged) if denied, never fabricated |
| Per-connection interface attribution | Exact match of `laddr.ip` against each interface's known IPv4/IPv6 addresses | Direct set-membership lookup | `None` when the local address is `0.0.0.0`/`::`, loopback-only, or doesn't exactly match a currently known interface address - **never inferred from the routing table or heuristics** |
| Per-connection byte counters | **Not modeled.** | N/A | `psutil` does not expose per-socket byte counters on Windows. Real per-connection throughput requires a kernel driver, ETW flow logging, WFP callouts, or packet capture (WinDivert/npcap) - all out of scope for this MVP's "never install drivers" constraint. Rendered as "unavailable" everywhere, never as `0`. |

### Distinguishing throughput concepts (important!)

These four numbers are easily confused and are kept **strictly separate**
throughout the app and the data model:

1. **Negotiated link speed** (`InterfaceInfo.link_speed_mbps`) - the
   PHY-negotiated capacity of the NIC/port (e.g. "1 Gbps"). This is a
   ceiling, not a measurement of anything currently happening.
2. **Observed interface traffic** (`RateSample.rx_mbps`/`tx_mbps`) - actual
   bytes crossing that NIC per second, for *all* traffic on that interface
   (every app, every destination). This is what "Live Traffic" shows.
3. **Internet throughput** (e.g. a speed test to a specific server) - **not
   measured by this MVP at all**. Observed interface traffic is a superset
   of Internet-bound traffic and is not a substitute for a real
   throughput/bandwidth test.
4. **Per-process/per-connection traffic** - **not measured** (see byte
   counter row above); only which process owns which connection and (by
   exact local-IP match) which interface that connection is bound to.

### Source-bound ping limitation and Windows routing behavior

`ping.exe -S <source_ip>` asks Windows to *originate* the ICMP Echo Request
from a specific local address. This is the Windows-supported mechanism
this MVP uses to probe "through" a specific interface without touching the
routing table. However:

- Windows' route selection for the *destination* is still governed by the
  routing table at the time of the ping, not solely by the chosen source
  address. If no route exists via that source interface's subnet/gateway
  for the destination, Windows may still send the packet out a *different*
  interface (or fail outright), because `-S` constrains the source address
  of the packet, not the egress adapter selection itself.
- As a result, a probe issued "from" interface A's IP can, in unusual
  routing configurations (e.g. asymmetric multi-homing, overlapping
  subnets, VPN split-tunnel routes), actually traverse a different NIC.
  The RTT/loss/jitter reported for interface A in that case reflects
  whatever path Windows actually used, which may not be interface A's
  physical path.
- This is a fundamental limitation of user-mode, non-driver source-address
  probing on Windows and is called out in the UI's Link Health tab
  description and here rather than silently assumed away.

---

## Scoring formula

See `multilink_manager/scoring/scorer.py` for the authoritative
implementation (fully unit tested in `tests/test_scoring.py`). Summary:

1. If reachability is **unknown** (probe could not be attempted), the
   score is `None` - never a guessed number.
2. If the target is **confirmed unreachable**, the score is `0.0`.
3. Otherwise, start at `100.0` and subtract capped penalties for each
   *known* metric (an unknown individual metric contributes **zero**
   penalty, not a fault, and is called out in `ScoreResult.notes`):

   | Component | Formula | Max penalty |
   |---|---|---|
   | Packet loss | `min(loss_pct * 2.0, 60.0)` | 60 |
   | Latency (RTT) | `<=20ms:0, <=50ms:5, <=100ms:15, <=200ms:30, else:45` | 45 |
   | Jitter | `<=5ms:0, <=15ms:5, <=30ms:10, else:20` | 20 |

   `score = max(0.0, 100.0 - loss_penalty - latency_penalty - jitter_penalty)`

Loss is weighted most heavily because it degrades both TCP throughput and
real-time traffic the most; latency next; jitter last, since jitter mainly
affects real-time/interactive traffic and is the least universally
impactful of the three. Each component is capped so no single metric alone
can claim the entire 0-100 range without corroboration from the others.

**Per-target scores vs. the "primary" score.** `compute_score()` is run
independently for **each** probe target (gateway and public) of each
interface, so the Link Health table can show a gateway score and a public
score side by side without one overwriting the other. For history/CSV
export and the Live Traffic score chart, each interface needs exactly
*one* score per tick; this "primary" score is chosen as the **public**
target's score whenever the public probe produced a usable result that
tick, and falls back to the **gateway** target's score only when the
public probe itself has no usable result (e.g. the public endpoint is
unreachable or not yet sampled). This keeps the historical/health score
consistently anchored to "can this interface actually reach the Internet"
when that information is available, while still surfacing *something*
meaningful (LAN-segment reachability) when it isn't. The Dashboard's Link
Health table marks whichever row was chosen this way with a `(primary)`
suffix so it is never ambiguous which score is being recorded.

---

## Manual verification procedures

The 8 procedures below are organized by the exact **scenario** requested
(not by feature), so each one is a self-contained script you can run
against a machine with at least one Ethernet and one Wi-Fi adapter. Start
the app first (`python -m multilink_manager.app`), enter a **Public
target** (e.g. `1.1.1.1`), click **Start**, and keep it running throughout
each scenario. Within each scenario, check whatever tabs are called out.

1. **Ethernet only** (Wi-Fi disabled/disconnected, Ethernet connected with
   Internet access)
   - **Interfaces** tab: the Ethernet adapter shows `Type = ethernet`,
     `Status = up`, valid IPv4/MAC/negotiated link speed; any Wi-Fi adapter
     shows `down` or is simply not carrying traffic.
   - **Dashboard**: "Current path" names the Ethernet interface. Link
     Health shows a `gateway` and a `public` row for it, both
     `Reachable = Yes`, with the `public` row marked `(primary)`.
   - **Live Traffic**: the counters table shows the Ethernet row's
     cumulative bytes/packets increasing tick over tick; RX/TX/Total Mbps
     non-zero if traffic is flowing.

2. **Wi-Fi only** (Ethernet disabled/disconnected, Wi-Fi connected with
   Internet access)
   - Same checks as scenario 1, but for the Wi-Fi adapter: **Interfaces**
     shows `Type = wifi`, an associated `Network profile`; **Dashboard**
     "Current path" names the Wi-Fi interface; Link Health's `public`
     row for it is `(primary)` and reachable.

3. **Both simultaneously** (Ethernet and Wi-Fi both connected with
   Internet access at the same time)
   - **Interfaces**: both adapters show `up` with independent
     addresses/MACs/speeds.
   - **Dashboard**: "Current path" names exactly **one** interface - the
     one with the lowest effective metric (`RouteMetric + InterfaceMetric`
     from `Get-NetRoute`/`Get-NetIPInterface`), which you can cross-check
     with `Get-NetIPInterface -AddressFamily IPv4 | Select
     InterfaceAlias, InterfaceMetric` and `Get-NetRoute -DestinationPrefix
     0.0.0.0/0 | Select InterfaceAlias, RouteMetric` - the interface with
     the lowest **sum**, not necessarily the lowest `RouteMetric` alone,
     should match. Both interfaces get independent Link Health rows.
   - **Live Traffic** distribution bars (RX/TX/Combined) split
     proportionally between the two interfaces rather than showing 100%
     on one arbitrarily.

4. **Disconnect Ethernet while Wi-Fi remains** (starting from scenario 3)
   - Unplug the Ethernet cable (or disable the adapter in Windows
     Settings - a manual, user-driven action; this app never does this
     itself). Within one monitor tick, **Interfaces** shows Ethernet as
     `down` (or the row disappears if Windows removes it from
     `psutil.net_if_addrs()`); **Dashboard** Link Health for the Ethernet
     interface stops showing new probe results within one probe cycle,
     and if the interface itself disappears, its Link Health rows are
     **removed immediately** (not left showing stale RTT/loss from before
     the disconnect - covered by `tests/test_link_prober_stale.py`).
     "Current path" now names Wi-Fi. Traffic charts continue for Wi-Fi
     without interruption.

5. **Disconnect Wi-Fi while Ethernet remains** (starting from scenario 3,
   mirror of scenario 4)
   - Disable/disconnect Wi-Fi instead. Confirm the same behaviors as
     scenario 4 but for the Wi-Fi row, and that "Current path" now names
     Ethernet.

6. **One interface connected without Internet access** (e.g. Ethernet
   plugged into a LAN switch with no upstream Internet, or a Wi-Fi AP with
   no WAN)
   - **Dashboard** Link Health: the `gateway` row for that interface is
     still `Reachable = Yes` (LAN hop responds) with a normal score, but
     the `public` row is `Reachable = No` with RTT/jitter shown as blank
     (`n/a`), never `0`, and its score is `0.0` (confirmed unreachable, not
     `None`). Because the public probe has no usable result, the
     `(primary)` label falls back to the `gateway` row for that interface
     per the documented fallback rule (see Scoring formula above) -
     confirm exactly one row per interface is marked `(primary)`.

7. **Generate traffic on both simultaneously** (both interfaces connected
   with Internet access, both actively transferring)
   - Start a sustained transfer on each interface at the same time (e.g.
     bind two `Invoke-WebRequest`/`curl` downloads via `--interface`, or
     use two different applications/devices routed through each NIC).
     Confirm **Live Traffic**'s per-interface counters table shows both
     rows' cumulative bytes/packets climbing concurrently, RX/TX/Total
     Mbps non-zero for both, and the Combined-throughput chart's per-
     interface series plus its `TOTAL` series both rise together. Confirm
     the RX/TX/Combined distribution bars/chart reflect the real relative
     share between the two (not always 50/50) and that the type-
     distribution chart (Ethernet vs. Wi-Fi vs. Other, %) tracks which
     interface is carrying more.

8. **Verify Windows counters** (cross-check reported counters against an
   independent Windows source)
   - While traffic is flowing on at least one interface, compare the
     **Live Traffic** counters table's cumulative RX/TX bytes and packets
     for that interface against PowerShell's own
     `Get-NetAdapterStatistics -Name "<adapter name>"` (fields
     `ReceivedBytes`/`SentBytes`/`ReceivedUnicastPackets`/
     `SentUnicastPackets`, etc.) and/or Task Manager's Performance tab for
     that NIC. Values should closely track (small differences are
     expected due to sampling-time skew and slightly different counter
     definitions between `psutil`/IP Helper and `Get-NetAdapterStatistics`,
     but they must not diverge wildly or go backwards tick over tick
     except across a genuine counter reset, which the app detects and
     treats as a fresh baseline rather than a negative delta).

### Manual test procedure: interface selection (enable/disable per adapter)

Not one of the 8 required scenarios above, but included here since it
directly relates to the v0.2-style interface-selection feature added on
top of them:

1. If you have a VPN client, virtual adapter, or other non-Ethernet/Wi-Fi
   interface, connect it (or otherwise ensure at least one `Other`-
   classified interface is present) alongside a physical Ethernet or
   Wi-Fi adapter, then Start monitoring.
2. **Interfaces** tab: confirm the physical Ethernet/Wi-Fi adapter(s) show
   the **Enabled** checkbox checked by default, and the VPN/virtual/Other
   adapter shows it **unchecked** by default - with no adapter-name-based
   logic involved (classification is by Windows media-type metadata).
3. Uncheck the physical adapter's **Enabled** box. Within one tick,
   confirm it disappears from **Dashboard** Link Health, from the **Live
   Traffic** counters table and all seven history charts, and from the
   RX/TX/Combined distribution bars - while it remains visible (still
   listed, just unchecked) on the **Interfaces** tab itself.
4. Re-check the box. Confirm the interface reappears in Link Health/Live
   Traffic/distribution within one tick, and that its counters resume
   from a sane baseline (no artificial traffic spike from the gap).
5. Click **Select physical defaults**. Confirm every Ethernet/Wi-Fi
   adapter becomes checked and every Other/Unknown adapter becomes
   unchecked, regardless of any manual overrides made in steps 3-4.
6. Click **Deselect all**. Confirm every adapter becomes unchecked and
   Link Health / Live Traffic / distribution go empty for all interfaces,
   while the Interfaces tab itself still lists all of them.
7. If Steering is enabled, confirm a deselected interface never appears
   as a switch candidate/target even if it would otherwise score higher
   than the active path (covered automatically by
   `tests/test_steering_controller.py::test_deselected_interface_never_becomes_steering_candidate`,
   but may be manually cross-checked via the Steering tab's decision log).

---

## Automatic failover (opt-in)

**Status: v0.2-style extension, disabled by default.** Everything above
this section describes v0.1 monitoring, which remains fully read-only
regardless of this feature's state. This section documents the one
explicit, opt-in exception: automatic active/backup IPv4 default-route
steering, which a user can enable from the **Steering (opt-in)** tab.
Monitoring itself never requires elevation; only *enabling* steering does.

### What it actually does (and does not do)

When enabled, `SteeringController` may change the **IPv4 interface
metric** of one physical Ethernet/Wi-Fi adapter at a time, via Windows'
`Set-NetIPInterface -AddressFamily IPv4 -AutomaticMetric Disabled
-InterfaceMetric <n>`. This changes how Windows *ranks* an already-
existing default route so that a different interface becomes the
preferred outbound path for new IPv4 connections. It:

- **Never** creates, removes, or reassigns a route (`Set-NetRoute` route
  mutation is never issued).
- **Never** touches IPv6.
- **Never** connects, disconnects, enables, or disables an adapter.
- **Never** installs a driver, service, or kernel component.
- **Never** touches a VPN/virtual/"Other"-classified adapter's own
  settings - only interfaces classified Ethernet or Wi-Fi, currently up,
  with an already-operational IPv4 default route are ever eligible
  targets. Additionally, if Windows' *currently observed preferred path*
  is itself a VPN/virtual/"Other" interface, steering refuses to act at
  all that tick (see "No-bypass VPN/Other guard" below) - even though
  this feature never writes to that adapter directly, lowering a
  *physical* interface's metric underneath it could otherwise
  inadvertently make the physical path preferred over the VPN's own
  default route, silently bypassing it.
- **At most one interface has a modified setting at any given moment.**
  When failing back from one target to a different one, the previous
  target's original setting is fully restored *before* the new target is
  ever touched (see "Deterministic failback" below) - this feature does
  not "pin" multiple interfaces low at once and does not accumulate
  unrestored settings across repeated switches.

### No-bypass VPN/Other guard

Before evaluating any candidate, `SteeringController.tick()` resolves
Windows' currently observed preferred interface (the same effective-
metric calculation as "Current path") to an `InterfaceInfo`. If that
interface exists and is **not** classified Ethernet/Wi-Fi with status up
(e.g. it is an active VPN/virtual/"Other" adapter), steering skips this
tick entirely - no candidate is selected, no switch is attempted, and
`SteeringStatus.last_decision_reason` explains why. This prevents a
scenario where a user has intentionally routed traffic through a VPN
(which this feature never mutates directly) and steering would otherwise
still lower a physical Ethernet/Wi-Fi interface's metric far enough to
become preferred over that VPN's own default route, silently defeating
the user's VPN routing. If there is **no** currently observed preferred
path at all (`active_interface is None` - e.g. nothing has an effective
metric yet), this guard does not apply and normal N-cycle candidate
selection proceeds as usual.

### Requirements

- **Windows only.** `SteeringController.enable()` refuses (and mutates
  nothing) off Windows.
- **Administrator privileges.** Checked via `utils.platform_utils.is_admin()`
  (Windows `IsUserAnAdmin()`) before every enable; the GUI shows a clear
  `QMessageBox.critical` and refuses to proceed if you are not elevated.
  Restart the application "Run as administrator" to use this feature.
- Monitoring must already be running (Start clicked) - steering decisions
  are derived from the same per-tick link-health measurements.

### Algorithm (mirrors `steering/policy.py`'s docstring - keep in sync)

Each tick, `SteeringPolicy.decide()` is given the currently OS-observed
active interface (the same effective-metric calculation as "Current
path") and a resolved eligibility/health snapshot for every known
interface, and decides whether to switch:

1. **Hold-down.** If a switch happened less than `hold_down_seconds`
   (default **30s**) ago, no new switch is even considered this tick.
2. **No-bypass VPN/Other guard.** If Windows' currently observed
   preferred path is not an eligible physical Ethernet/Wi-Fi interface
   that is up (e.g. an active VPN/virtual/"Other" adapter), skip this
   tick entirely rather than risk bypassing it - see above. Does not
   apply when there is no currently observed preferred path at all.
3. **Candidate selection.** Only interfaces that are eligible physical
   paths (Ethernet/Wi-Fi, status up, a **known interface index**, and an
   operational IPv4 default route confirmed via that index - an
   interface with no known index can never satisfy this and can never be
   selected), reachable (`reachable is True`, never unknown/false), and
   have a *known* score are candidates; the best-scoring one is chosen.
   **An unknown score can never make an interface a candidate.**
4. **Switch condition.** A switch is only considered when the best
   candidate is demonstrably better than the current active interface:
   either the active interface is **confirmed unhealthy** (no health data
   at all, confirmed unreachable, or a known score below
   `unhealthy_score_threshold`, default **40.0**), or the active
   interface's score is known and healthy and the candidate beats it by
   at least `score_advantage_threshold` (default **10.0** points -
   hysteresis). **If the active interface's score is simply unknown (not
   confirmed unhealthy), no switch is ever considered on that basis
   alone** - unknown scores must never trigger switching, on either side
   of the comparison.
5. **N-cycle confirmation.** Even once the switch condition holds, the
   *same* candidate must keep meeting it for `min_consecutive_cycles`
   consecutive ticks (default **3**) before a switch actually happens. Any
   tick where the condition stops holding, or a different candidate
   becomes best, resets the streak to zero.
6. **Deterministic failback before applying.** Before touching the new
   target, any *previously* modified interface (from an earlier switch)
   is fully restored first - see "Save / apply / verify / restore /
   rollback" below. If that restore fails, the new switch is aborted
   entirely rather than leaving two interfaces modified at once.
7. After a switch is applied **and verified**, the hold-down timer
   restarts and the confirmation streak resets, so the newly active
   interface gets a full, undisturbed observation window.

`min_consecutive_cycles`, `score_advantage_threshold`, and
`hold_down_seconds` are configurable in the Steering tab (spinboxes,
editable only while steering is disabled); if you don't need to change
them, the named, documented `SteeringConfig` defaults above apply.

**Health source for decisions.** Per the same public-preferred/gateway-
fallback rule used for Link Health/history elsewhere in this app, each
interface's health for steering purposes uses its **public probe** score
when the public probe has a usable result that tick, falling back to its
**gateway** probe score only when the public probe itself has no usable
result. A gateway-fallback score is therefore an acceptable steering input
only when the public probe is genuinely unavailable that tick - it is
never preferred over a usable public-probe score.

### Save / apply / verify / restore / rollback

**Deterministic failback: restore-old-before-new.** At the start of every
switch attempt, `SteeringController._perform_switch()` first checks
whether any interface *other than* the new target still has a saved
original setting from an earlier switch. If so, that previous target is
fully restored **first** - if this restore fails, the new switch is
**aborted entirely** (the new target is never touched) and the failure is
logged at `ERROR` and surfaced in `SteeringStatus.last_error`, so a
failure never results in more than one interface being modified at once.
Only once any previous target has been cleanly restored does the
controller proceed. This guarantees `_saved_settings` never holds more
than one entry (the current active target) during normal operation, and
that target-metric planning (below) is always computed against genuinely
current values rather than a stale, still-pinned prior target.

Then, before mutating the (new) target interface,
`RouteController.get_ip_setting()` reads and `SteeringController` saves
that interface's **exact original** `AutomaticMetric`/`InterfaceMetric`
values. The target's new `InterfaceMetric` is computed
(`SteeringController._compute_target_metric`) by comparing only against
*other currently-eligible* interfaces (Ethernet/Wi-Fi, status up, with an
actual route metric - Other/virtual/VPN, down, and route-less interfaces
are excluded from this comparison entirely, never treated as having a
route metric of `0`) so the target's new *effective* metric
(`RouteMetric + InterfaceMetric`) is strictly lower than every one of
those interfaces' *current* effective metric - without mutating any of
them. After applying, the switch is **verified** by re-reading Windows'
own observed preferred interface (`get_preferred_ipv4_interface_name()`);
if verification fails, the original setting is restored immediately and
the failure is logged at `ERROR` and surfaced in
`SteeringStatus.last_error`. If that restore *also* fails, this is logged
at `ERROR` and surfaced prominently - never a silent success. All original
settings are restored automatically when you click **Disable/Restore**,
click **Stop**, or close the application normally (`MonitorWorker.run()`'s
`finally` block unconditionally calls `SteeringController.disable()`
before the worker thread exits, and the GUI's `stop_monitoring()`/
`closeEvent()` block - pumping the Qt event loop, never abandoning the
thread - until that has genuinely finished before reading final status or
allowing the window to close).

**Refusing to re-enable with unresolved leftover settings.** If a
previous `disable()` (or a restore-before-new-switch, above) ever failed
to restore a setting, that interface remains in `_saved_settings` and
`SteeringStatus.restored` stays `False`. In that state,
`SteeringController.enable()` **refuses to re-enable at all** - it will
not attempt to layer a new switch on top of an already-unresolved
modified interface - and keeps `restored=False` with a prominent error
until the leftover setting is manually corrected (or a future successful
restore clears it).

### GUI usage

1. Start monitoring first (Steering tab requires it).
2. Optionally adjust the score-advantage-threshold/confirmation-cycles/
   hold-down spinboxes (locked once enabled).
3. Click **Enable automatic steering...**. If not elevated, you get a
   clear error and nothing is changed. Otherwise a confirmation dialog
   explains: Administrator requirement (already verified), that **only
   new connections** use the newly preferred path while **existing TCP
   connections are not migrated** and may stall/reset briefly around a
   switch, that a brief disruption is possible at the exact moment of a
   switch, and that original settings are always restored automatically
   on Disable/Stop/close.
4. The **Steering status** panel shows: enabled/disabled, current active
   path, candidate/target, consecutive confirmation cycles, hold-down
   remaining, the last decision's human-readable reason, and any error.
5. Click **Disable / Restore** at any time to restore original settings
   and return to pure observation.
6. Clicking **Stop**, or closing the application window, blocks (pumping
   the UI so it does not appear fully hung) until the monitor/steering
   worker thread has actually finished - including any in-progress
   restore - before the window updates its final status or is allowed to
   close; it will never abandon a live thread or a pending restore
   attempt partway through.
7. If a restore ever fails (e.g. on Stop), a `QMessageBox.critical` dialog
   is shown with the exact error and the interface(s) affected - this is
   never silently swallowed. If a leftover restore failure remains
   unresolved, subsequent attempts to re-enable steering are refused until
   it is manually corrected.

### Manual safe route-steering verification procedure

Use this to confirm the feature is behaving as documented, on a
non-production machine with at least one Ethernet and one Wi-Fi adapter
both connected with Internet access:

1. Before enabling, record the baseline: `Get-NetIPInterface -AddressFamily
   IPv4 | Select InterfaceAlias, AutomaticMetric, InterfaceMetric` and
   `Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Select InterfaceAlias,
   RouteMetric`. Note the "Current path" shown on the Dashboard.
2. In the app, elevate (Run as administrator), Start monitoring, open the
   Steering tab, and click **Enable automatic steering...**; accept the
   confirmation dialog.
3. If the currently active interface is artificially made "unhealthy"
   (e.g. temporarily unplug it, or block ICMP to the public target on it)
   and a healthier eligible candidate exists, after the configured
   confirmation cycles you should see the Steering status panel's
   "Candidate/target" and "Active path" update, and a log line at `INFO`
   ("Steering: switch to '...' verified successful").
4. Re-run the `Get-NetIPInterface`/`Get-NetRoute` commands from step 1 -
   the newly active interface's `AutomaticMetric` should now show
   `Disabled` with a low `InterfaceMetric`, and its effective metric
   (`RouteMetric + InterfaceMetric`) should be the lowest among eligible
   interfaces. Confirm "Current path" on the Dashboard agrees.
5. Click **Disable / Restore**. Re-run the same commands again - the
   previously-switched interface's `AutomaticMetric`/`InterfaceMetric`
   should exactly match your step-1 baseline.
6. **Failback determinism check.** With steering still running, make the
   *newly active* interface from step 3 unhealthy in turn (e.g. unplug
   it) so the *other* eligible interface becomes the better candidate.
   After confirmation, re-run the `Get-NetIPInterface` command: exactly
   **one** interface should show `AutomaticMetric = Disabled` at a time -
   the interface from step 3 should be back to its original
   `AutomaticMetric`/`InterfaceMetric` (restored before the new switch was
   applied), never left low alongside the new target.
7. Restart the scenario and instead click **Stop** (or close the app)
   while steering is still enabled - confirm settings are restored the
   same way (the app will briefly show "Stopping..." while it waits for
   the restore to finish), without needing to click Disable first.

**Do not** perform steps 2-4 on a production/shared machine without
understanding the "existing TCP connections are not migrated" limitation
below.

### Limitations specific to automatic failover

- **Existing TCP connections are not migrated.** Only *new* outbound
  connections use the newly preferred interface; sockets already
  established on the old path are unaffected by the metric change and may
  stall, reset, or continue on the old (possibly degraded) path until they
  naturally close/reconnect.
- **No per-packet load balancing or link bonding.** This is single-active
  path selection (active/backup failover), not multi-path bandwidth
  aggregation - only one interface is preferred for new IPv4 traffic at a
  time.
- **Subject to Windows' own route-selection behavior**, including DNS
  resolution and VPN/split-tunnel routing, which this feature does not
  control or override; a VPN or DNS configuration that pins traffic
  independently of the default route's interface metric is unaffected by
  this feature (and VPN/virtual/"Other" adapters are never touched, by
  design).
- **No crash/power-loss restoration.** Original settings are restored on
  Disable, Stop, or normal application close only. If the process is
  killed abruptly (crash, forced power-off, `taskkill /F`) while steering
  has changed a setting, that setting is **not** automatically restored on
  next launch - this application does not claim otherwise. `SteeringStatus`
  and the `INFO`-level log line emitted on every switch (recording the
  exact original `AutomaticMetric`/`InterfaceMetric` values) are the only
  persisted record; if you suspect an unclean shutdown occurred while
  steering was enabled, check the log file and manually run
  `Set-NetIPInterface -AutomaticMetric Enabled` for the affected
  interface(s), or compare against the manual verification procedure's
  baseline capture.
- **IPv4 default-route scope only.** IPv6 is never touched.

---

**Supported (this MVP):**
- Interface enumeration, Windows-metadata-based classification, addresses,
  MAC, negotiated link speed, network profile, gateways.
- Cumulative and delta interface counters: bytes, packets, errors,
  discards; derived Mbps/pps.
- RX/TX/combined traffic distribution across interfaces.
- In-memory time-window history with CSV export.
- Independent per-interface source-bound ping probing: RTT, loss, jitter,
  reachability, against gateway and a configurable public endpoint.
- Deterministic, documented 0-100 link quality scoring.
- Process/connection enumeration with protocol/state/endpoints and
  exact-match interface attribution.
- **Opt-in automatic active/backup IPv4 default-route failover** (OFF by
  default, requires Administrator) - see
  [Automatic failover (opt-in)](#automatic-failover-opt-in).

**Explicitly unsupported (documented, not faked):**
- Per-connection/per-process byte counters or throughput.
- True end-to-end Internet bandwidth/speed testing.
- Any route *creation/removal*, adapter connect/disconnect, or driver
  installation - by design, not by omission. (The opt-in steering feature
  only ever re-prioritizes an already-existing default route via interface
  metric; see [Automatic failover (opt-in)](#automatic-failover-opt-in).)
- Multi-path load balancing/link bonding - steering is single-active-path
  selection only.
- Guaranteed interface attribution for probes when Windows' actual route
  selection diverges from the requested source address (see "Source-bound
  ping limitation").
- IPv6 default gateway/profile parity is best-effort; some fields may be
  `None` on IPv6-only or dual-stack edge configurations not exercised in
  testing.

---

## Known limitations

*(For limitations specific to the opt-in automatic failover extension -
existing-connections-not-migrated, no load balancing/bonding, Windows
route-selection/DNS/VPN interplay, and the crash/power-loss caveat - see
[Automatic failover (opt-in) -> Limitations](#automatic-failover-opt-in)
above.)*

- **PowerShell dependency for rich metadata.** Classification, gateway,
  and network-profile lookups depend on PowerShell CIM cmdlets being
  available and fast enough (an 8-second timeout is enforced per call);
  a heavily loaded system or a locked-down PowerShell execution policy can
  degrade these fields to `None`/`OTHER` even on Windows.
- **`Get-NetRoute`/`Get-NetConnectionProfile` process exit codes.** These
  cmdlets can return a non-zero process exit code from `powershell.exe`
  even when they produce valid JSON (e.g. no IPv6 default route exists);
  `run_powershell_json` therefore still attempts to parse stdout in that
  case rather than discarding valid data.
- **Elevation affects connection visibility.** `psutil.net_connections()`
  can only see connections owned by the current user's processes unless
  the app is run elevated; the app logs this and returns an empty list
  rather than partial/misleading data.
- **Ping-based probing is coarse and now strictly sequential.**
  `ping.exe` invocations have their own process-start latency and are not
  a substitute for a dedicated low-level ICMP/UDP probing library. As of
  this revision, `LinkProber` probes every interface/target pair
  **sequentially** on its own single background thread rather than
  concurrently via a thread pool - a deliberate stability tradeoff (see
  Architecture above). This means a full probe pass's wall-clock duration
  is roughly the *sum* of each individual `ping.exe` call's latency, which
  scales with the number of interfaces and targets; for a typical 2-3
  interface setup with 2 targets each this stays comfortably within the
  default 5s probe interval, but a machine with many virtual/VPN adapters
  may see slower probe cadence than the configured interval.
- **Observed intermittent process-exit-time instability in constrained
  test environments.** During development, this application occasionally
  exhibited a native crash (Windows STATUS_STACK_BUFFER_OVERRUN) at Python
  interpreter shutdown - strictly *after* `app.exec()` had already
  returned normally and all monitoring/GUI functionality had already
  completed correctly - when many `powershell.exe`/`ping.exe` child
  processes had been spawned from multiple background threads over a long
  session, in one specific sandboxed Windows VM used for testing. It did
  not corrupt data, violate the read-only contract, or affect anything
  observed *during* normal operation, only interpreter teardown. Reducing
  concurrent thread layers (sequential probing above) and bounding
  concurrent process creation (a `threading.Semaphore` in
  `utils/platform_utils.py`) substantially reduced its frequency in
  testing. If you observe an exit-time crash on your target hardware,
  please treat it as an environment-specific stability issue to monitor,
  not a data-integrity concern - functional behavior up to that point is
  unaffected.
- **No persistence across restarts.** History is in-memory only; closing
  the app discards it (aside from any CSV you exported).
- **Single time-series chart window is naive.** The custom `TimeSeriesChart`
  widget re-paints the full visible window each tick; it is adequate for a
  handful of interfaces at multi-second cadences but is not optimized for
  very high-frequency updates or many dozens of series.
- **Interface selection is app-level filtering, not adapter control.**
  Deselecting an interface only stops this app from probing/graphing/
  scoring it and from considering it as a steering candidate - it does
  **not** disable, disconnect, or reconfigure the adapter in Windows in
  any way, and the OS continues to route traffic through it exactly as
  before. A deselected interface can still be the OS's actual preferred
  default route, which the Dashboard clearly annotates rather than hides.
  Overrides are session-scoped (in-memory, tied to the running
  `InterfaceSelectionManager` instance) and are not currently persisted
  across an app restart.
- **The prebuilt Windows `.exe` is unsigned.** It will trigger a Windows
  SmartScreen "unknown publisher" warning on first run (see "Windows
  executable (prebuilt build)" above); there is no code-signing
  certificate applied in this MVP's CI build.

## Recommended future architecture

The items below remain forward-looking recommendations for further
evolution **beyond** the automatic-failover extension already implemented
in this revision (see
[Automatic failover (opt-in)](#automatic-failover-opt-in) above for what
already exists today):

- **Replace ping.exe shelling with ICMP via a proper library** (e.g. a
  raw-socket or `pywin32` `IcmpSendEcho2` binding) to remove per-probe
  process-spawn overhead, get finer-grained timing, and support
  configurable packet sizes/TTL - still without installing a driver. This
  would also remove the process-creation-related stability motivation for
  today's sequential-only probing loop, making it safe to reintroduce
  bounded concurrent probing (e.g. an async event loop or a small,
  in-process worker pool with no child-process spawning) for lower total
  probe-pass latency on machines with many interfaces.
- **Add a well-scoped, explicitly-consented ETW session** (e.g.
  `Microsoft-Windows-TCPIP` provider) as an *optional* feature to unlock
  real per-connection byte counters, clearly gated behind an explicit
  opt-in and elevation prompt, rather than silently attempting driver
  installation.
- **Persist history to a local embedded database** (e.g. SQLite) with
  configurable retention beyond in-memory limits, enabling
  restart-resilient long-term trend charts.
- **Introduce a proper plugin/provider architecture** for scoring so
  additional signals (e.g. DNS resolution time, HTTP HEAD probe latency)
  can be added without changing the core formula contract.
- **Move charting to QtCharts (or a GPU-accelerated alternative)** once
  the dependency footprint is acceptable for the target deployment, to
  support smoother high-frequency rendering and richer interactions (zoom,
  pan, tooltips) than the current custom-painted widget.
- **Add multi-endpoint/geo-diverse public probing** with statistical
  aggregation (percentiles, not just mean) for more robust Internet-path
  quality signals distinct from local-interface traffic.
- **Formal integration tests behind a Windows-only CI matrix** (in
  addition to today's OS-independent mocked unit tests) to catch
  regressions in the PowerShell-dependent code paths.
