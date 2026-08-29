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
        "--icmp-targets",
        default=None,
        help=(
            "Comma-separated ICMP (ping.exe) probe targets used as the initial GUI "
            "value (default: 1.1.1.1, 8.8.8.8). Gateway probing is always automatic "
            "and is not configurable here. The GUI field can still be changed before "
            "pressing Start."
        ),
    )
    parser.add_argument(
        "--https-targets",
        default=None,
        help=(
            "Comma-separated HTTPS/HTTP probe URLs used as the initial GUI value "
            "(default: https://www.gstatic.com/generate_204, "
            "https://connectivitycheck.gstatic.com/generate_204). The GUI field can "
            "still be changed before pressing Start."
        ),
    )
    parser.add_argument(
        "--public-target",
        default=None,
        help=(
            "DEPRECATED alias for a single-entry --icmp-targets. Kept for backward "
            "compatibility; if both --public-target and --icmp-targets are given, "
            "--icmp-targets wins and a deprecation warning is logged."
        ),
    )
    args = parser.parse_args(argv)

    from multilink_manager.utils.logging_config import configure_logging

    configure_logging(level=getattr(logging, args.log_level), log_file=args.log_file)
    log = logging.getLogger("multilink_manager.app")

    icmp_targets_text = args.icmp_targets
    if icmp_targets_text is None and args.public_target:
        log.warning(
            "--public-target is deprecated; treating it as the sole --icmp-targets "
            "entry (%s). Use --icmp-targets instead.", args.public_target,
        )
        icmp_targets_text = args.public_target

    # Imported lazily so --help / logging setup works without a display
    # server or PySide6 installed (useful for headless CI smoke checks).
    from PySide6.QtWidgets import QApplication

    from multilink_manager.gui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow(
        initial_icmp_targets_text=icmp_targets_text,
        initial_https_targets_text=args.https_targets,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
