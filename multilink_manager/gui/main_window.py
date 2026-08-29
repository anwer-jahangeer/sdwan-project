"""Main application window (PySide6).

Responsive, tabbed, read-only monitoring UI. All system/network work runs
on ``MonitorWorker`` (a ``QThread``); this module only ever renders data
delivered via the ``snapshot_ready`` Qt signal and never performs blocking
I/O on the GUI thread. Nothing here mutates routes, connects/disconnects
adapters, or installs drivers -- see README for the full read-only
contract.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multilink_manager.gui.charts import TimeSeriesChart
from multilink_manager.gui.worker import MonitorWorker, Snapshot
from multilink_manager.monitoring.selection import InterfaceSelectionManager
from multilink_manager.models.steering import (
    DEFAULT_HOLD_DOWN_SECONDS,
    DEFAULT_MIN_CONSECUTIVE_CYCLES,
    DEFAULT_SCORE_ADVANTAGE_THRESHOLD,
    SteeringConfig,
    SteeringStatus,
)
from multilink_manager.networking.probing import (
    DEFAULT_PROBE_INTERVAL_S,
    DEFAULT_PUBLIC_TARGET,
)
from multilink_manager.storage.history_store import DEFAULT_RETENTION_MINUTES, HistoryStore
from multilink_manager.utils.logging_config import get_logger
from multilink_manager.utils.platform_utils import is_admin

logger = get_logger(__name__)

DEFAULT_INTERVAL_S = 2.0


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _fmt_list(values) -> str:
    return ", ".join(values) if values else "—"


# Bounded but generous: every OS call inside MonitorWorker.run() (PowerShell
# reads/mutations, ping.exe probes) is itself internally timeout-bounded to a
# handful of seconds, so a real worker thread is always expected to actually
# finish well within this budget -- this is a last-resort safety valve, not a
# normal-case wait time.
_WORKER_STOP_CHUNK_MS = 2000
_WORKER_STOP_MAX_TOTAL_MS = 60000


def wait_for_worker_to_finish(
    worker,
    chunk_ms: int = _WORKER_STOP_CHUNK_MS,
    max_total_ms: int = _WORKER_STOP_MAX_TOTAL_MS,
    pump_events=None,
) -> bool:
    """Block until ``worker.wait(chunk_ms)`` reports the worker's ``run()``
    has actually returned, calling ``pump_events`` between chunks so a real
    Qt event loop doesn't appear fully frozen while we wait.

    This exists specifically so ``stop_monitoring``/``closeEvent`` never
    drop a ``MonitorWorker`` reference or read its final
    ``steering_status`` while the thread might still be inside its
    ``finally`` block restoring automatic-steering settings -- a single
    ``worker.wait(5000)`` call followed by unconditionally proceeding
    regardless of its return value could destroy a still-live ``QThread``
    and inspect steering status before restoration had actually completed.

    Returns ``True`` once the worker has genuinely finished. Returns
    ``False`` only if ``max_total_ms`` is exceeded with the worker still
    running -- callers MUST treat that as "not safe to proceed" (do not
    drop the reference, do not read steering status, do not allow the
    window to close) rather than assuming the wait was merely slow.

    ``worker`` only needs a ``wait(ms) -> bool`` method (matching
    ``QThread.wait``), and ``pump_events`` defaults to
    ``QApplication.processEvents`` -- both are parameterized so this
    function is fully unit-testable with a plain fake object, no
    QApplication/QThread required.
    """
    if pump_events is None:
        pump_events = QApplication.processEvents
    elapsed_ms = 0
    while not worker.wait(chunk_ms):
        pump_events()
        elapsed_ms += chunk_ms
        if elapsed_ms >= max_total_ms:
            return False
    return True


class MainWindow(QMainWindow):
    def __init__(
        self,
        initial_interval_s: float = DEFAULT_INTERVAL_S,
        initial_retention_minutes: float = DEFAULT_RETENTION_MINUTES,
        initial_public_target: str = DEFAULT_PUBLIC_TARGET,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MultiLink Manager - Monitoring + Opt-in Failover")
        self.resize(1280, 860)

        self.history_store = HistoryStore(retention_minutes=initial_retention_minutes)
        self.worker: Optional[MonitorWorker] = None
        self._latest_snapshot: Optional[Snapshot] = None
        # Owned by the GUI so explicit per-interface enable/disable
        # overrides survive across separate Start/Stop sessions (not just
        # one MonitorWorker's lifetime); injected into each MonitorWorker
        # at construction time (see start_monitoring).
        self._selection = InterfaceSelectionManager()

        self._build_ui(initial_interval_s, initial_retention_minutes, initial_public_target)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self, initial_interval_s, initial_retention_minutes, initial_public_target) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        root_layout.addWidget(self._build_control_bar(
            initial_interval_s, initial_retention_minutes, initial_public_target
        ))

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self.tabs.addTab(self._build_traffic_tab(), "Live Traffic")
        self.tabs.addTab(self._build_interfaces_tab(), "Interfaces")
        self.tabs.addTab(self._build_connections_tab(), "Applications / Connections")
        self.tabs.addTab(self._build_steering_tab(), "Steering (opt-in)")
        root_layout.addWidget(self.tabs, stretch=1)

        self.status_label = QLabel("Stopped.")
        root_layout.addWidget(self.status_label)

        self.setCentralWidget(central)

    def _build_control_bar(self, initial_interval_s, initial_retention_minutes, initial_public_target) -> QWidget:
        box = QGroupBox("Monitoring controls")
        layout = QHBoxLayout(box)

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)

        layout.addWidget(QLabel("Interval (s):"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(initial_interval_s)
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        layout.addWidget(self.interval_spin)

        layout.addWidget(QLabel("Retention (min):"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 24 * 60)
        self.retention_spin.setValue(int(initial_retention_minutes))
        self.retention_spin.valueChanged.connect(self._on_retention_changed)
        layout.addWidget(self.retention_spin)

        layout.addWidget(QLabel("Public probe target:"))
        self.public_target_edit = QLineEdit(initial_public_target)
        self.public_target_edit.setPlaceholderText("e.g. 1.1.1.1 (required, gateway probing is automatic)")
        self.public_target_edit.setMinimumWidth(160)
        layout.addWidget(self.public_target_edit)

        self.clear_btn = QPushButton("Clear History")
        self.clear_btn.clicked.connect(self._on_clear_history)
        layout.addWidget(self.clear_btn)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self._on_export_csv)
        layout.addWidget(self.export_btn)

        layout.addStretch(1)
        return box

    def _build_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        path_box = QGroupBox("Current path (observed preferred/default IPv4 route -- never switched by this app)")
        path_layout = QVBoxLayout(path_box)
        self.current_path_label = QLabel("Preferred interface: unknown")
        self.current_path_label.setWordWrap(True)
        path_layout.addWidget(self.current_path_label)
        layout.addWidget(path_box)

        dist_box = QGroupBox("RX / TX / Combined traffic distribution (current tick, per interface)")
        dist_layout = QVBoxLayout(dist_box)
        self.distribution_table = QTableWidget(0, 4)
        self.distribution_table.setHorizontalHeaderLabels(["Interface", "RX %", "TX %", "Combined %"])
        self.distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.distribution_table.setEditTriggers(QTableWidget.NoEditTriggers)
        dist_layout.addWidget(self.distribution_table)
        layout.addWidget(dist_box)

        health_box = QGroupBox(
            "Link health (per-interface, per-target: gateway + public probe endpoint; "
            "primary = public-preferred with gateway fallback, used for history/score)"
        )
        health_layout = QVBoxLayout(health_box)
        self.link_health_table = QTableWidget(0, 8)
        self.link_health_table.setHorizontalHeaderLabels(
            ["Interface", "Target", "Address", "Reachable", "RTT (ms)", "Loss (%)", "Jitter (ms)", "Score"]
        )
        self.link_health_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.link_health_table.setEditTriggers(QTableWidget.NoEditTriggers)
        health_layout.addWidget(self.link_health_table)
        layout.addWidget(health_box)

        return tab

    def _build_traffic_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)

        table_box = QGroupBox(
            "Per-interface counters (cumulative bytes/packets/errors/discards) and current rates"
        )
        table_layout = QVBoxLayout(table_box)
        self.traffic_table = QTableWidget(0, 14)
        self.traffic_table.setHorizontalHeaderLabels([
            "Interface", "RX Bytes", "TX Bytes", "RX Packets", "TX Packets",
            "RX Errors", "TX Errors", "RX Discards", "TX Discards",
            "RX Mbps", "TX Mbps", "Total Mbps", "RX pps", "TX pps",
        ])
        self.traffic_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.traffic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        table_layout.addWidget(self.traffic_table)
        layout.addWidget(table_box)

        retention_seconds = self.retention_spin.value() * 60 if hasattr(self, "retention_spin") else DEFAULT_RETENTION_MINUTES * 60

        self.rx_chart = TimeSeriesChart("RX throughput per interface", "Mbps", window_seconds=retention_seconds)
        self.tx_chart = TimeSeriesChart("TX throughput per interface", "Mbps", window_seconds=retention_seconds)
        self.combined_chart = TimeSeriesChart(
            "Combined (RX+TX) throughput per interface, plus TOTAL", "Mbps", window_seconds=retention_seconds
        )
        self.type_distribution_chart = TimeSeriesChart(
            "Ethernet / Wi-Fi / Other combined traffic share over time", "%", window_seconds=retention_seconds
        )
        self.latency_chart = TimeSeriesChart(
            "Latency (RTT, primary target per interface)", "ms", window_seconds=retention_seconds
        )
        self.loss_chart = TimeSeriesChart(
            "Packet loss (primary target per interface)", "%", window_seconds=retention_seconds
        )
        self.score_chart = TimeSeriesChart(
            "Link score (primary target per interface)", "0-100", window_seconds=retention_seconds
        )

        self._charts: List[TimeSeriesChart] = [
            self.rx_chart, self.tx_chart, self.combined_chart, self.type_distribution_chart,
            self.latency_chart, self.loss_chart, self.score_chart,
        ]
        for chart in self._charts:
            chart.setMinimumHeight(200)
            layout.addWidget(chart)

        scroll.setWidget(content)
        return outer

    def _build_interfaces_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        btn_layout = QHBoxLayout()
        self.select_physical_defaults_btn = QPushButton("Select physical defaults")
        self.select_physical_defaults_btn.setToolTip(
            "Reset every listed interface's selection to the type-based default: "
            "Ethernet/Wi-Fi enabled, everything else (Other/Unknown/virtual/VPN/"
            "loopback) disabled."
        )
        self.select_physical_defaults_btn.clicked.connect(self._on_select_physical_defaults_clicked)
        self.deselect_all_btn = QPushButton("Deselect all")
        self.deselect_all_btn.setToolTip(
            "Disable every listed interface for monitoring (they remain listed here "
            "so you can re-enable any of them)."
        )
        self.deselect_all_btn.clicked.connect(self._on_deselect_all_clicked)
        btn_layout.addWidget(self.select_physical_defaults_btn)
        btn_layout.addWidget(self.deselect_all_btn)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

        self.interfaces_table = QTableWidget(0, 13)
        self.interfaces_table.setHorizontalHeaderLabels([
            "Enabled", "Name", "Friendly Name", "Index", "Type", "Status",
            "IPv4", "IPv6", "IPv4 Gateway", "IPv6 Gateway",
            "MAC", "Link Speed (Mbps)", "Network Profile",
        ])
        self.interfaces_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # Every cell except the "Enabled" checkbox stays fully read-only;
        # NoEditTriggers only blocks text editing, not clicking a
        # checkable item's indicator, so the checkbox remains interactive.
        self.interfaces_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.interfaces_table.itemChanged.connect(self._on_interface_item_changed)
        layout.addWidget(self.interfaces_table)

        note = QLabel(
            "Classification is derived from interface type / Windows adapter metadata "
            "(never hardcoded by display name). Ethernet/Wi-Fi interfaces are enabled by "
            "default; Other/Unknown/virtual/VPN/loopback interfaces are disabled by "
            "default. Toggle 'Enabled' to control whether an interface is included in "
            "probing, live traffic/distribution/history, link health, and automatic "
            "steering candidates -- this NEVER disables/disconnects the adapter itself or "
            "touches Windows routing; deselected interfaces stay listed here so you can "
            "re-enable them at any time, even while monitoring is running. See README for "
            "classification_source detail."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return tab

    def _build_connections_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.connections_table = QTableWidget(0, 10)
        self.connections_table.setHorizontalHeaderLabels([
            "PID", "Process", "Protocol", "Local Address", "Local Port",
            "Remote Address", "Remote Port", "State", "Interface", "Bytes (sent/recv)",
        ])
        self.connections_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.connections_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.connections_table)

        note = QLabel(
            "Per-connection byte counters are always 'unavailable': psutil.net_connections() "
            "does not expose them. Real per-connection traffic volume requires a kernel driver, "
            "ETW, WFP, or packet capture -- none of which this MVP installs."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return tab

    def _build_steering_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        warn = QLabel(
            "Opt-in automatic failover -- DISABLED by default. Monitoring above is fully "
            "read-only regardless of this tab. Only when you explicitly click 'Enable "
            "automatic steering...' below does this application mutate anything: it changes "
            "the target interface's IPv4 interface metric (Windows 'Set-NetIPInterface', IPv4 "
            "default route scope only) to steer new outbound connections toward the "
            "healthiest eligible Ethernet/Wi-Fi interface. Requires Administrator privileges. "
            "Every original setting changed is saved and restored automatically on "
            "Disable/Restore, on Stop, and on normal app close. See README 'Automatic "
            "failover (opt-in)' for the full algorithm, safety model, and limitations."
        )
        warn.setWordWrap(True)
        layout.addWidget(warn)

        config_box = QGroupBox("Policy configuration (applied when you click Enable)")
        config_layout = QHBoxLayout(config_box)
        config_layout.addWidget(QLabel("Score advantage threshold:"))
        self.steering_threshold_spin = QDoubleSpinBox()
        self.steering_threshold_spin.setRange(0.0, 100.0)
        self.steering_threshold_spin.setValue(DEFAULT_SCORE_ADVANTAGE_THRESHOLD)
        config_layout.addWidget(self.steering_threshold_spin)

        config_layout.addWidget(QLabel("Confirmation cycles:"))
        self.steering_cycles_spin = QSpinBox()
        self.steering_cycles_spin.setRange(1, 20)
        self.steering_cycles_spin.setValue(DEFAULT_MIN_CONSECUTIVE_CYCLES)
        config_layout.addWidget(self.steering_cycles_spin)

        config_layout.addWidget(QLabel("Hold-down (s):"))
        self.steering_holddown_spin = QDoubleSpinBox()
        self.steering_holddown_spin.setRange(0.0, 600.0)
        self.steering_holddown_spin.setValue(DEFAULT_HOLD_DOWN_SECONDS)
        config_layout.addWidget(self.steering_holddown_spin)
        config_layout.addStretch(1)
        layout.addWidget(config_box)

        btn_layout = QHBoxLayout()
        self.enable_steering_btn = QPushButton("Enable automatic steering...")
        self.enable_steering_btn.clicked.connect(self._on_enable_steering_clicked)
        self.disable_steering_btn = QPushButton("Disable / Restore")
        self.disable_steering_btn.setEnabled(False)
        self.disable_steering_btn.clicked.connect(self._on_disable_steering_clicked)
        btn_layout.addWidget(self.enable_steering_btn)
        btn_layout.addWidget(self.disable_steering_btn)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

        status_box = QGroupBox("Steering status")
        status_layout = QGridLayout(status_box)
        self.steering_enabled_label = QLabel("Disabled")
        self.steering_active_label = QLabel("unknown")
        self.steering_target_label = QLabel("—")
        self.steering_reason_label = QLabel("steering disabled")
        self.steering_reason_label.setWordWrap(True)
        self.steering_cycles_label = QLabel("0")
        self.steering_holddown_label = QLabel("0s")
        self.steering_error_label = QLabel("")
        self.steering_error_label.setWordWrap(True)
        self.steering_error_label.setStyleSheet("color: #b00020; font-weight: bold;")

        status_layout.addWidget(QLabel("Enabled:"), 0, 0)
        status_layout.addWidget(self.steering_enabled_label, 0, 1)
        status_layout.addWidget(QLabel("Active path:"), 1, 0)
        status_layout.addWidget(self.steering_active_label, 1, 1)
        status_layout.addWidget(QLabel("Candidate/target:"), 2, 0)
        status_layout.addWidget(self.steering_target_label, 2, 1)
        status_layout.addWidget(QLabel("Consecutive cycles:"), 3, 0)
        status_layout.addWidget(self.steering_cycles_label, 3, 1)
        status_layout.addWidget(QLabel("Hold-down remaining:"), 4, 0)
        status_layout.addWidget(self.steering_holddown_label, 4, 1)
        status_layout.addWidget(QLabel("Last decision/reason:"), 5, 0)
        status_layout.addWidget(self.steering_reason_label, 5, 1)
        status_layout.addWidget(QLabel("Error:"), 6, 0)
        status_layout.addWidget(self.steering_error_label, 6, 1)
        layout.addWidget(status_box)

        layout.addStretch(1)
        return tab

    # ------------------------------------------------------------------
    # Start/Stop
    # ------------------------------------------------------------------
    def start_monitoring(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        public_target = self.public_target_edit.text().strip()
        if not public_target:
            QMessageBox.warning(
                self, "Public probe target required",
                "Please enter a public probe target (e.g. 1.1.1.1 or 8.8.8.8) before starting.",
            )
            return

        self.history_store.set_retention_minutes(self.retention_spin.value())

        self.worker = MonitorWorker(
            history_store=self.history_store,
            interval_s=self.interval_spin.value(),
            probe_interval_s=DEFAULT_PROBE_INTERVAL_S,
            public_target=public_target,
            selection_manager=self._selection,
        )
        self.worker.snapshot_ready.connect(self._on_snapshot)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.public_target_edit.setEnabled(False)
        self.status_label.setText(f"Running (public target: {public_target}).")
        logger.info("Monitoring started from GUI (public_target=%s)", public_target)

    def stop_monitoring(self) -> None:
        if self.worker is None:
            return
        worker = self.worker

        # Stop receiving snapshots immediately so no stale/racy render can
        # touch widgets while the worker thread is still winding down and
        # potentially still restoring automatic-steering settings.
        try:
            worker.snapshot_ready.disconnect(self._on_snapshot)
        except (TypeError, RuntimeError):
            pass
        try:
            worker.error_occurred.disconnect(self._on_worker_error)
        except (TypeError, RuntimeError):
            pass

        worker.request_stop()
        self.status_label.setText("Stopping (restoring any automatic-steering settings)...")
        finished = wait_for_worker_to_finish(worker)
        if not finished:
            # Do NOT drop the reference, do NOT read steering_status: the
            # thread may still be inside its restore path. Reconnect so the
            # GUI keeps updating while the caller (or the user clicking
            # Stop/closing again) can retry.
            logger.error(
                "Monitor worker did not stop within the expected time; refusing to drop its "
                "reference or read final steering status until it has genuinely finished."
            )
            worker.snapshot_ready.connect(self._on_snapshot)
            worker.error_occurred.connect(self._on_worker_error)
            self.status_label.setText("Still stopping (taking longer than expected)...")
            QMessageBox.critical(
                self, "Monitor worker not responding",
                "The monitoring/steering worker thread has not stopped within the expected "
                "time. It has NOT been abandoned - no reference was dropped and no steering "
                "status was read, to avoid destroying a live thread or inspecting settings "
                "before any restore attempt has actually completed. Please wait and try Stop "
                "again, or close the window again to retry.",
            )
            return

        final_steering_status = worker.steering_status
        self.worker = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.public_target_edit.setEnabled(True)
        self.status_label.setText("Stopped.")
        logger.info("Monitoring stopped from GUI")

        self._render_steering_status(final_steering_status)
        if not final_steering_status.restored:
            QMessageBox.critical(
                self, "Steering restore failed",
                "Automatic steering had changed IPv4 interface metric settings and restoring "
                "the original values FAILED:\n\n"
                f"{final_steering_status.last_error or 'see log for details'}\n\n"
                "Please verify your network interface metrics manually (see README "
                "'Automatic failover (opt-in)' -> known limitations / manual recovery).",
            )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.worker is not None:
            self.stop_monitoring()
        if self.worker is not None:
            # stop_monitoring above refused to drop the worker reference
            # because it had not actually finished (see
            # wait_for_worker_to_finish) -- normal close must not complete
            # until any pending steering-restore attempt has finished, so
            # refuse to close the window rather than abandon a live thread.
            event.ignore()
            return
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Control callbacks
    # ------------------------------------------------------------------
    def _on_interval_changed(self, value: float) -> None:
        if self.worker is not None:
            self.worker.set_interval(value)

    def _on_retention_changed(self, value: int) -> None:
        self.history_store.set_retention_minutes(value)
        window_seconds = value * 60
        for chart in getattr(self, "_charts", []):
            chart.set_window_seconds(window_seconds)

    def _on_clear_history(self) -> None:
        self.history_store.clear()
        for chart in getattr(self, "_charts", []):
            chart.clear()
        self.status_label.setText("History and all charts cleared.")

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export history CSV", "history.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            count = self.history_store.export_csv(path)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_label.setText(f"Exported {count} history record(s) to {path}.")

    def _on_worker_error(self, message: str) -> None:
        logger.error("Monitor worker reported error: %s", message)
        self.status_label.setText(f"Error: {message}")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _on_snapshot(self, snapshot: Snapshot) -> None:
        self._latest_snapshot = snapshot
        self._render_current_path(snapshot)
        self._render_distribution(snapshot)
        self._render_link_health(snapshot)
        self._render_traffic_table(snapshot)
        self._render_traffic_charts(snapshot)
        self._render_interfaces(snapshot)
        self._render_connections(snapshot)
        self._render_steering_status(snapshot.steering_status)

    def _render_current_path(self, snapshot: Snapshot) -> None:
        if snapshot.preferred_interface:
            note = ""
            if not snapshot.enabled_map.get(snapshot.preferred_interface, True):
                note = (
                    " [DESELECTED in Interfaces tab -- excluded from monitoring/steering/"
                    "history; shown here only because Windows currently uses it as the "
                    "observed preferred path]"
                )
            self.current_path_label.setText(
                f"Preferred interface (observed, effective-metric route selection): "
                f"{snapshot.preferred_interface}{note}"
            )
        else:
            self.current_path_label.setText(
                "Preferred interface: unknown (no default IPv4 route metadata available)"
            )

    def _render_distribution(self, snapshot: Snapshot) -> None:
        table = self.distribution_table
        table.setRowCount(len(snapshot.distribution))
        for row, (name, entry) in enumerate(sorted(snapshot.distribution.items())):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setCellWidget(row, 1, self._make_bar(entry.rx_pct))
            table.setCellWidget(row, 2, self._make_bar(entry.tx_pct))
            table.setCellWidget(row, 3, self._make_bar(entry.combined_pct))

    @staticmethod
    def _make_bar(pct: float) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(max(0.0, min(100.0, pct)))))
        bar.setFormat(f"{pct:.1f}%")
        return bar

    def _render_link_health(self, snapshot: Snapshot) -> None:
        rows = []
        for iface in snapshot.enabled_interfaces:
            name = iface.name
            iface_probes = snapshot.probes.get(name, {})
            primary_type = snapshot.primary_target.get(name)
            for target_type, probe in sorted(iface_probes.items()):
                row_score = snapshot.target_scores.get(name, {}).get(target_type)
                label = target_type
                if target_type == primary_type:
                    label = f"{target_type} (primary)"
                rows.append((name, label, probe, row_score))

        table = self.link_health_table
        table.setRowCount(len(rows))
        for row, (name, label, probe, score) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(label))
            table.setItem(row, 2, QTableWidgetItem(probe.target))
            reachable_text = "unknown" if probe.reachable is None else ("yes" if probe.reachable else "no")
            table.setItem(row, 3, QTableWidgetItem(reachable_text))
            table.setItem(row, 4, QTableWidgetItem(_fmt(probe.rtt_ms)))
            table.setItem(row, 5, QTableWidgetItem(_fmt(probe.loss_pct)))
            table.setItem(row, 6, QTableWidgetItem(_fmt(probe.jitter_ms)))
            score_text = "unavailable" if (score is None or score.score is None) else f"{score.score:.1f}"
            table.setItem(row, 7, QTableWidgetItem(score_text))

    def _render_traffic_table(self, snapshot: Snapshot) -> None:
        table = self.traffic_table
        names = sorted(snapshot.counter_samples.keys())
        table.setRowCount(len(names))
        for row, name in enumerate(names):
            sample = snapshot.counter_samples[name]
            rate = snapshot.rates.get(name)
            total_mbps = (rate.rx_mbps + rate.tx_mbps) if rate else 0.0
            values = [
                name,
                str(sample.bytes_recv),
                str(sample.bytes_sent),
                str(sample.packets_recv),
                str(sample.packets_sent),
                str(sample.errin),
                str(sample.errout),
                str(sample.dropin),
                str(sample.dropout),
                f"{rate.rx_mbps:.3f}" if rate else "0.000",
                f"{rate.tx_mbps:.3f}" if rate else "0.000",
                f"{total_mbps:.3f}",
                f"{rate.rx_pps:.1f}" if rate else "0.0",
                f"{rate.tx_pps:.1f}" if rate else "0.0",
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))

    def _render_traffic_charts(self, snapshot: Snapshot) -> None:
        ts = snapshot.timestamp
        total_combined = 0.0
        for name, rate in snapshot.rates.items():
            if rate.is_first_sample:
                continue
            self.rx_chart.add_point(name, rate.rx_mbps, ts)
            self.tx_chart.add_point(name, rate.tx_mbps, ts)
            combined = rate.rx_mbps + rate.tx_mbps
            self.combined_chart.add_point(name, combined, ts)
            total_combined += combined
        self.combined_chart.add_point("TOTAL", total_combined, ts)

        for type_name, entry in snapshot.type_distribution.items():
            self.type_distribution_chart.add_point(type_name, entry.combined_pct, ts)

        for iface in snapshot.enabled_interfaces:
            name = iface.name
            primary_type = snapshot.primary_target.get(name)
            probe = snapshot.probes.get(name, {}).get(primary_type) if primary_type else None
            score = snapshot.scores.get(name)
            if probe is not None:
                if probe.rtt_ms is not None:
                    self.latency_chart.add_point(name, probe.rtt_ms, ts)
                if probe.loss_pct is not None:
                    self.loss_chart.add_point(name, probe.loss_pct, ts)
            if score is not None and score.score is not None:
                self.score_chart.add_point(name, score.score, ts)

    def _render_interfaces(self, snapshot: Snapshot) -> None:
        self._render_interfaces_table(snapshot.interfaces, snapshot.enabled_map)

    def _render_interfaces_table(self, interfaces, enabled_map: Dict[str, bool]) -> None:
        table = self.interfaces_table
        # Block signals for the entire programmatic rebuild so setting
        # each checkbox's state below never re-enters
        # ``_on_interface_item_changed`` via ``itemChanged`` -- that signal
        # must only ever fire for a genuine user click on the checkbox.
        table.blockSignals(True)
        try:
            table.setRowCount(len(interfaces))
            for row, iface in enumerate(interfaces):
                enabled = enabled_map.get(iface.name, False)
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check_item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                check_item.setData(Qt.UserRole, iface.name)
                table.setItem(row, 0, check_item)
                values = [
                    iface.name,
                    iface.friendly_name,
                    _fmt(iface.index),
                    iface.if_type.value,
                    iface.status.value,
                    _fmt_list(iface.ipv4_addresses),
                    _fmt_list(iface.ipv6_addresses),
                    iface.ipv4_gateway or "unavailable",
                    iface.ipv6_gateway or "unavailable",
                    iface.mac_address or "unavailable",
                    _fmt(iface.link_speed_mbps),
                    iface.network_profile or "unavailable",
                ]
                for col, value in enumerate(values, start=1):
                    table.setItem(row, col, QTableWidgetItem(value))
        finally:
            table.blockSignals(False)

    def _on_interface_item_changed(self, item) -> None:
        if item.column() != 0:
            return
        name = item.data(Qt.UserRole)
        if not name:
            return
        enabled = item.checkState() == Qt.Checked
        self._selection.set_override(name, enabled)
        logger.info("Interface '%s' %s by user (Interfaces tab)", name, "enabled" if enabled else "disabled")

    def _on_select_physical_defaults_clicked(self) -> None:
        interfaces = self._latest_snapshot.interfaces if self._latest_snapshot else []
        self._selection.select_physical_defaults(interfaces)
        self._render_interfaces_table(interfaces, self._selection.resolve(interfaces))
        logger.info("Interface selection reset to physical defaults (Ethernet/Wi-Fi) from GUI")
        self.status_label.setText("Interface selection reset to physical defaults (Ethernet/Wi-Fi enabled).")

    def _on_deselect_all_clicked(self) -> None:
        interfaces = self._latest_snapshot.interfaces if self._latest_snapshot else []
        self._selection.deselect_all(interfaces)
        self._render_interfaces_table(interfaces, self._selection.resolve(interfaces))
        logger.info("All interfaces deselected from GUI")
        self.status_label.setText("All interfaces deselected (still listed; re-enable any at any time).")

    def _render_connections(self, snapshot: Snapshot) -> None:
        table = self.connections_table
        conns = snapshot.connections
        table.setRowCount(len(conns))
        for row, c in enumerate(conns):
            values = [
                _fmt(c.pid),
                c.process_name or "unavailable",
                c.protocol,
                c.laddr_ip or "",
                _fmt(c.laddr_port),
                c.raddr_ip or "",
                _fmt(c.raddr_port),
                c.state or "unavailable",
                c.interface_name or "unavailable",
                "unavailable",
            ]
            item = QTableWidgetItem(values[-1])
            item.setToolTip(c.bytes_unavailable_reason)
            for col, value in enumerate(values[:-1]):
                table.setItem(row, col, QTableWidgetItem(value))
            table.setItem(row, len(values) - 1, item)

    def _render_steering_status(self, status: Optional[SteeringStatus]) -> None:
        if status is None:
            return
        self.steering_enabled_label.setText("Enabled" if status.enabled else "Disabled")
        self.steering_active_label.setText(status.active_interface or "unknown")
        self.steering_target_label.setText(status.target_interface or "—")
        self.steering_cycles_label.setText(str(status.consecutive_cycles))
        self.steering_holddown_label.setText(f"{status.hold_down_remaining_s:.0f}s")
        self.steering_reason_label.setText(status.last_decision_reason)
        self.steering_error_label.setText(status.last_error or "")

        # Keep buttons/config controls in sync even if steering was
        # auto-restored due to a verification failure, or disabled for any
        # reason other than the user clicking Disable directly.
        self.disable_steering_btn.setEnabled(status.enabled)
        self.enable_steering_btn.setEnabled(not status.enabled)
        for spin in (self.steering_threshold_spin, self.steering_cycles_spin, self.steering_holddown_spin):
            spin.setEnabled(not status.enabled)

    # ------------------------------------------------------------------
    # Steering controls
    # ------------------------------------------------------------------
    def _on_enable_steering_clicked(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            QMessageBox.warning(
                self, "Monitoring not running",
                "Start monitoring before enabling automatic steering -- steering decisions are "
                "computed from the same per-tick link-health measurements.",
            )
            return

        if not is_admin():
            QMessageBox.critical(
                self, "Administrator privileges required",
                "Automatic steering modifies Windows IPv4 interface metrics and requires this "
                "application to be run as Administrator. Close it, restart it elevated "
                "(right-click -> Run as administrator), and try again.",
            )
            logger.error("Automatic steering enable refused in GUI: not running as Administrator")
            return

        confirm = QMessageBox.question(
            self, "Enable automatic steering",
            "This lets the application automatically change which network interface is "
            "preferred for outbound Internet traffic (IPv4 default route only), based on "
            "measured link health.\n\n"
            "Please read before continuing:\n"
            "- Requires Administrator privileges (already verified for this process).\n"
            "- Only NEW connections use the newly preferred path -- EXISTING TCP connections "
            "are not migrated and may stall or reset briefly around a switch.\n"
            "- A brief disruption is possible at the exact moment of each switch.\n"
            "- Every original setting this app changes is saved and will be restored "
            "automatically when you click Disable/Restore, click Stop, or close the "
            "application normally.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        config = SteeringConfig(
            min_consecutive_cycles=self.steering_cycles_spin.value(),
            score_advantage_threshold=self.steering_threshold_spin.value(),
            hold_down_seconds=self.steering_holddown_spin.value(),
        )
        self.worker.request_enable_steering(config)
        self.steering_threshold_spin.setEnabled(False)
        self.steering_cycles_spin.setEnabled(False)
        self.steering_holddown_spin.setEnabled(False)
        self.enable_steering_btn.setEnabled(False)
        self.disable_steering_btn.setEnabled(True)
        self.steering_reason_label.setText("enable requested; applying on next monitoring tick...")
        logger.info("Automatic steering enable requested from GUI")

    def _on_disable_steering_clicked(self) -> None:
        if self.worker is not None:
            self.worker.request_disable_steering()
            self.steering_reason_label.setText("disable requested; restoring on next monitoring tick...")
        self.steering_threshold_spin.setEnabled(True)
        self.steering_cycles_spin.setEnabled(True)
        self.steering_holddown_spin.setEnabled(True)
        self.enable_steering_btn.setEnabled(True)
        self.disable_steering_btn.setEnabled(False)
        logger.info("Automatic steering disable/restore requested from GUI")
