"""Tests for the in-memory history store: retention window and CSV export."""

from __future__ import annotations

import csv
import time

from multilink_manager.models.history import HistoryRecord
from multilink_manager.storage.history_store import HistoryStore


def _record(ts, name="eth0"):
    return HistoryRecord(
        timestamp=ts, interface_name=name, rx_mbps=1.0, tx_mbps=2.0,
        rx_bytes=100, tx_bytes=200, latency_ms=10.0, loss_pct=0.0,
        jitter_ms=1.0, score=95.0,
    )


def test_retention_prunes_records_older_than_window():
    store = HistoryStore(retention_minutes=1)  # 60 second window
    now = time.time()
    store.add(_record(now - 120))  # older than window -> pruned
    store.add(_record(now - 5))    # within window -> kept
    records = store.get_records()
    assert len(records) == 1
    assert records[0].timestamp == now - 5


def test_set_retention_minutes_reprunes_immediately():
    store = HistoryStore(retention_minutes=60)
    now = time.time()
    store.add(_record(now - 600))  # 10 min old, within 60 min window
    assert len(store) == 1
    store.set_retention_minutes(1)  # shrink window to 1 min
    assert len(store) == 0


def test_clear_removes_all_records():
    store = HistoryStore()
    store.add(_record(time.time()))
    store.clear()
    assert len(store) == 0


def test_export_csv_writes_header_and_rows(tmp_path):
    store = HistoryStore()
    store.add(_record(time.time(), name="eth0"))
    store.add(_record(time.time(), name="wifi0"))
    out_path = tmp_path / "history.csv"

    count = store.export_csv(str(out_path))

    assert count == 2
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(HistoryRecord.CSV_FIELDS)
    assert len(rows) == 3
    assert rows[1][1] == "eth0"
    assert rows[2][1] == "wifi0"


def test_get_records_filters_by_interface():
    store = HistoryStore()
    store.add(_record(time.time(), name="eth0"))
    store.add(_record(time.time(), name="wifi0"))
    eth_only = store.get_records(interface_name="eth0")
    assert len(eth_only) == 1
    assert eth_only[0].interface_name == "eth0"
