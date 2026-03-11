"""MacroClaw structured logging — mirrors OpenClaw's tslog subsystem pattern.

Uses structlog for structured, subsystem-aware logging with both console
(rich-formatted) and file (JSON) output, matching OpenClaw's rolling-file strategy.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


# ── Custom processors ──────────────────────────────────────────────────────────

def _add_subsystem(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Inject subsystem prefix if provided, matching OpenClaw's subsystem: message format."""
    subsystem = event_dict.pop("subsystem", None)
    if subsystem:
        event_dict["event"] = f"{subsystem}: {event_dict.get('event', '')}"
    return event_dict


def _drop_color_message_key(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Remove duplicate color message added by rich formatters."""
    event_dict.pop("color_message", None)
    return event_dict


# ── Setup ──────────────────────────────────────────────────────────────────────

def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    max_bytes: int = 100 * 1024 * 1024,  # 100 MB (OpenClaw: 500 MB)
    backup_count: int = 3,
) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: Log level string (DEBUG/INFO/WARNING/ERROR).
        log_file: Path to the rolling log file. None disables file logging.
        max_bytes: Max size of a single log file before rotation.
        backup_count: Number of rotated backups to keep.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors applied to every log record
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_subsystem,
        _drop_color_message_key,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ── Handlers ────────────────────────────────────────────────────────────
    handlers: list[logging.Handler] = []

    # Console handler — pretty-print with colors when attached to a tty
    console_handler = logging.StreamHandler(sys.stderr)
    if sys.stderr.isatty():
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=shared_processors,
        )
    else:
        console_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)
    handlers.append(console_handler)

    # File handler — always JSON for machine-readable logs
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # always capture everything to file
        handlers.append(file_handler)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for handler in handlers:
        root_logger.addHandler(handler)

    # Silence noisy third-party libraries
    for noisy in ("httpx", "httpcore", "urllib3", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str, subsystem: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a subsystem-aware bound logger.

    Usage::

        log = get_logger(__name__, subsystem="commodity")
        log.info("Fetching WTI price", ticker="CL=F")

    Mirrors OpenClaw's getSubsystemLogger() pattern.
    """
    logger = structlog.get_logger(name)
    if subsystem:
        logger = logger.bind(subsystem=subsystem)
    return logger  # type: ignore[return-value]
