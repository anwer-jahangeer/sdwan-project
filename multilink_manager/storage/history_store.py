"""Configurable time-window in-memory history store.

Keeps a rolling window (default 60 minutes) of ``HistoryRecord`` samples
per interface, purging records older than the configured retention window
on every write. This is a pure in-memory store -- nothing is persisted to
disk except via explicit CSV export.
"""

from __future__ import annotations

import csv
import threading
import time
from typing import Iterable, List, Optional

from multilink_manager.models.history import HistoryRecord
from multilink_manager.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_RETENTION_MINUTES = 60


class HistoryStore:
    def __init__(self, retention_minutes: float = DEFAULT_RETENTION_MINUTES) -> None:
        self._lock = threading.Lock()
        self._records: List[HistoryRecord] = []
        self.retention_minutes = retention_minutes

    def set_retention_minutes(self, minutes: float) -> None:
        with self._lock:
            self.retention_minutes = minutes
            self._prune_locked()

    def add(self, record: HistoryRecord) -> None:
        with self._lock:
            self._records.append(record)
            self._prune_locked()

    def add_many(self, records: Iterable[HistoryRecord]) -> None:
        with self._lock:
            self._records.extend(records)
            self._prune_locked()

    def _prune_locked(self) -> None:
        cutoff = time.time() - (self.retention_minutes * 60.0)
        before = len(self._records)
        self._records = [r for r in self._records if r.timestamp >= cutoff]
        removed = before - len(self._records)
        if removed:
            logger.debug("History pruned %d record(s) older than %.1f minutes",
                         removed, self.retention_minutes)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
        logger.info("History cleared by user")

    def get_records(self, interface_name: Optional[str] = None) -> List[HistoryRecord]:
        with self._lock:
            records = list(self._records)
        if interface_name is not None:
            records = [r for r in records if r.interface_name == interface_name]
        return records

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def export_csv(self, path: str) -> int:
        """Write all currently retained records to a CSV file.

        Returns the number of rows written. Raises the underlying
        ``OSError`` on filesystem failures so the GUI can surface it.
        """
        records = self.get_records()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HistoryRecord.CSV_FIELDS)
            for r in records:
                writer.writerow(r.to_csv_row())
        logger.info("Exported %d history record(s) to %s", len(records), path)
        return len(records)
