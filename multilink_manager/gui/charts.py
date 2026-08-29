"""Lightweight custom-painted time-series chart widget.

Implemented with plain ``QWidget``/``QPainter`` (no QtCharts / no extra
dependency) per the requirement to avoid additional packages where
practical. Supports multiple named series, a rolling time window, and a
simple legend.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from PySide6.QtCore import QMargins, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_PALETTE = [
    QColor("#2E86FF"), QColor("#FF7A2E"), QColor("#2EFF9E"),
    QColor("#D62EFF"), QColor("#FFD62E"), QColor("#2EFFF5"),
    QColor("#FF2E5C"), QColor("#8C2EFF"),
]


class TimeSeriesChart(QWidget):
    def __init__(self, title: str = "", y_label: str = "", window_seconds: float = 300.0, parent=None):
        super().__init__(parent)
        self.title = title
        self.y_label = y_label
        self.window_seconds = window_seconds
        self._series: Dict[str, Deque[Tuple[float, float]]] = {}
        self._colors: Dict[str, QColor] = {}
        self.setMinimumHeight(180)

    def add_point(self, series_name: str, value: float, timestamp: Optional[float] = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        if series_name not in self._series:
            self._series[series_name] = deque()
            self._colors[series_name] = _PALETTE[len(self._colors) % len(_PALETTE)]
        dq = self._series[series_name]
        dq.append((ts, value))
        cutoff = ts - self.window_seconds
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        self.update()

    def remove_series(self, series_name: str) -> None:
        self._series.pop(series_name, None)
        self._colors.pop(series_name, None)
        self.update()

    def set_window_seconds(self, window_seconds: float) -> None:
        """Change the rolling retention window (e.g. to follow a user's
        configurable history retention setting) and immediately prune any
        now-stale points from all series."""
        self.window_seconds = max(1.0, window_seconds)
        now = max((dq[-1][0] for dq in self._series.values() if dq), default=time.time())
        cutoff = now - self.window_seconds
        for dq in self._series.values():
            while dq and dq[0][0] < cutoff:
                dq.popleft()
        self.update()

    def clear(self) -> None:
        self._series.clear()
        self._colors.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().marginsRemoved(QMargins(50, 24, 12, 24))
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        painter.setPen(QColor("#cccccc"))
        if self.title:
            painter.drawText(8, 16, self.title)

        if not self._series or all(len(dq) < 2 for dq in self._series.values()):
            painter.setPen(QColor("#777777"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            painter.end()
            return

        now = max((dq[-1][0] for dq in self._series.values() if dq), default=time.time())
        t_min = now - self.window_seconds
        all_values = [v for dq in self._series.values() for _, v in dq]
        v_max = max(all_values) if all_values else 1.0
        v_max = v_max * 1.1 if v_max > 0 else 1.0
        v_min = 0.0

        # Axes
        painter.setPen(QColor("#555555"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topLeft(), rect.bottomLeft())

        # Y-axis labels
        painter.setPen(QColor("#999999"))
        painter.drawText(4, rect.top() + 6, f"{v_max:.1f}")
        painter.drawText(4, rect.bottom(), "0")
        if self.y_label:
            painter.drawText(4, rect.top() - 8, self.y_label)

        def to_point(ts: float, value: float) -> QPointF:
            x = rect.left() + ((ts - t_min) / self.window_seconds) * rect.width() if self.window_seconds else rect.left()
            y = rect.bottom() - ((value - v_min) / (v_max - v_min)) * rect.height() if v_max > v_min else rect.bottom()
            return QPointF(x, y)

        legend_x = rect.left()
        for name, dq in self._series.items():
            if len(dq) < 2:
                continue
            color = self._colors[name]
            pen = QPen(color)
            pen.setWidthF(2.0)
            painter.setPen(pen)
            points = [to_point(ts, v) for ts, v in dq if ts >= t_min]
            for i in range(1, len(points)):
                painter.drawLine(points[i - 1], points[i])

            painter.setPen(color)
            painter.drawText(int(legend_x), int(rect.top() - 8), name)
            legend_x += 10 * len(name) + 20

        painter.end()
