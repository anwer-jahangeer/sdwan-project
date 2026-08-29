"""Configurable application logging.

Logging is intentionally quiet at INFO level: it records state transitions
and failures (interface appear/disappear, probe failures, PowerShell call
failures, monitor start/stop) but never logs per-packet or per-ping detail
at INFO level (that noise is only emitted at DEBUG level) to avoid log spam
during long-running monitoring sessions.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_CONFIGURED = False

DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"


def configure_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    fmt: str = DEFAULT_FORMAT,
) -> None:
    """Configure root logging for the application.

    Safe to call multiple times; only the first call takes effect unless
    ``force`` semantics are desired by the caller (tests may reset via
    ``reset_logging_for_tests``).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError:
            # Fall back silently to console-only logging if the file cannot
            # be created (e.g. read-only filesystem in a test sandbox).
            pass
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    _CONFIGURED = True


def reset_logging_for_tests() -> None:
    """Reset internal state so configure_logging can be re-applied in tests."""
    global _CONFIGURED
    _CONFIGURED = False
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
