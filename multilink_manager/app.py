"""Application entry point.

Run with ``python -m multilink_manager.app`` (see README for details).
This module is intentionally free of business logic: it configures
logging and launches the Qt event loop with ``MainWindow``.
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="multilink_manager", description=__doc__)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO). DEBUG also enables per-probe detail.",
    )
    parser.add_argument("--log-file", default=None, help="Optional path to also log to a file.")
    parser.add_argument(
        "--public-target",
        default=None,
        help=(
            "Optional public probe endpoint used as the initial GUI value "
            "(default: 1.1.1.1). Gateway probing is always automatic and is "
            "not configurable here. The GUI field can still be changed "
            "before pressing Start."
        ),
    )
    args = parser.parse_args(argv)

    from multilink_manager.utils.logging_config import configure_logging

    configure_logging(level=getattr(logging, args.log_level), log_file=args.log_file)

    # Imported lazily so --help / logging setup works without a display
    # server or PySide6 installed (useful for headless CI smoke checks).
    from PySide6.QtWidgets import QApplication

    from multilink_manager.gui.main_window import MainWindow
    from multilink_manager.networking.probing import DEFAULT_PUBLIC_TARGET

    app = QApplication(sys.argv[:1])
    window = MainWindow(initial_public_target=args.public_target or DEFAULT_PUBLIC_TARGET)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
