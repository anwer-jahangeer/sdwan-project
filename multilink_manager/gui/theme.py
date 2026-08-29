"""Application-wide Qt stylesheet (QSS) for a coherent, professional look.

Plain PySide6/Qt widgets only -- no extra GUI dependency. This is purely
cosmetic (spacing/colors/typography); it changes no behavior, no data, and
no widget hierarchy. Applied once, at the top level (MainWindow), so it
cascades to every child widget/tab automatically.
"""

from __future__ import annotations

APP_VERSION = "0.3.0"

# A single neutral dark theme -- deliberately restrained (a handful of
# grays plus one accent color) rather than a busy multi-color palette, so
# tables/graphs stay the visual focus. Chosen to match the existing
# TimeSeriesChart widget's own dark background (#1e1e1e in gui/charts.py)
# so charts do not look like a mismatched inset against a lighter window.
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1b1e23;
    color: #e6e6e6;
    font-size: 10.5pt;
}

QGroupBox {
    background-color: #22262c;
    border: 1px solid #3a3f47;
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #7fc4ff;
}

QLabel {
    color: #dcdfe4;
}

QLabel[role="heading"] {
    font-size: 13pt;
    font-weight: 700;
    color: #ffffff;
    padding: 2px 0 4px 0;
}

QLabel[role="subheading"] {
    font-size: 10pt;
    color: #9aa4b2;
}

QLabel[role="metric-good"] {
    color: #52d17c;
    font-weight: 700;
}

QLabel[role="metric-bad"] {
    color: #ff6b6b;
    font-weight: 700;
}

QLabel[role="metric-warn"] {
    color: #ffb454;
    font-weight: 700;
}

QPushButton {
    background-color: #2c333d;
    border: 1px solid #454c56;
    border-radius: 5px;
    padding: 6px 14px;
    color: #f0f0f0;
}

QPushButton:hover {
    background-color: #384049;
    border-color: #5a6472;
}

QPushButton:pressed {
    background-color: #232830;
}

QPushButton:disabled {
    color: #6b7178;
    background-color: #24272c;
    border-color: #333840;
}

QPushButton#startButton {
    background-color: #1f6f4a;
    border-color: #2a9161;
}

QPushButton#startButton:hover {
    background-color: #24875a;
}

QPushButton#stopButton {
    background-color: #7a2626;
    border-color: #9b3232;
}

QPushButton#stopButton:hover {
    background-color: #93302f;
}

QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #14171b;
    border: 1px solid #3a3f47;
    border-radius: 4px;
    padding: 4px 6px;
    color: #f0f0f0;
    selection-background-color: #2a6bb0;
}

QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #7a828c;
    background-color: #1a1d21;
}

QCheckBox {
    spacing: 6px;
    color: #dcdfe4;
}

QTabWidget::pane {
    border: 1px solid #3a3f47;
    border-radius: 6px;
    top: -1px;
    background-color: #1b1e23;
}

QTabBar::tab {
    background-color: #22262c;
    border: 1px solid #3a3f47;
    border-bottom: none;
    padding: 7px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #b6bdc6;
}

QTabBar::tab:selected {
    background-color: #1b1e23;
    color: #ffffff;
    font-weight: 600;
}

QTabBar::tab:hover {
    color: #ffffff;
}

QTableWidget {
    background-color: #14171b;
    alternate-background-color: #191c21;
    gridline-color: #2c313a;
    border: 1px solid #3a3f47;
    border-radius: 4px;
    selection-background-color: #2a6bb0;
}

QHeaderView::section {
    background-color: #262b32;
    color: #cfd6df;
    padding: 5px;
    border: none;
    border-right: 1px solid #3a3f47;
    border-bottom: 1px solid #3a3f47;
    font-weight: 600;
}

QProgressBar {
    background-color: #14171b;
    border: 1px solid #3a3f47;
    border-radius: 4px;
    text-align: center;
    color: #f0f0f0;
}

QProgressBar::chunk {
    background-color: #2a6bb0;
    border-radius: 3px;
}

QScrollArea {
    border: none;
}

QScrollBar:vertical {
    background: #1b1e23;
    width: 12px;
}

QScrollBar::handle:vertical {
    background: #3a3f47;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #4c5460;
}
"""
