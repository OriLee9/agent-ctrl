"""Structured logging configuration for Agent Workflow Framework.

Usage:
    from utils.logging_config import get_logger, setup_logging

    setup_logging(level="INFO")
    logger = get_logger("agent_workflow.core.agent")
    logger.info("Agent started", extra={"agent_id": "coder", "task": "write_code"})
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

# ── Default Configuration ────────────────────────────────────

DEFAULT_LOG_LEVEL = os.environ.get("AGENT_LOG_LEVEL", "INFO")
DEFAULT_LOG_FORMAT = os.environ.get(
    "AGENT_LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# ── Structured JSON Formatter (optional) ─────────────────────


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging (production mode)."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Merge extra fields
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "asctime", "getMessage",
            }:
                data[key] = value

        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        return json.dumps(data, ensure_ascii=False, default=str)


# ── Setup ────────────────────────────────────────────────────

_setup_done = False


def setup_logging(
    level: str | int | None = None,
    fmt: str | None = None,
    json_format: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure root logger for the framework.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to env AGENT_LOG_LEVEL or INFO.
        fmt: Custom format string. Defaults to env AGENT_LOG_FORMAT or a readable default.
        json_format: Use JSON formatter instead of plain text.
        log_file: Optional file path to also write logs to.
    """
    global _setup_done
    if _setup_done:
        return

    if level is None:
        level = DEFAULT_LOG_LEVEL
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    if fmt is None:
        fmt = DEFAULT_LOG_FORMAT

    handlers: list[logging.Handler] = []

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    if json_format:
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    handlers.append(console)

    # File handler
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        if json_format:
            fh.setFormatter(JSONFormatter())
        else:
            fh.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        handlers.append(fh)

    # Configure root logger
    root = logging.getLogger("agent_workflow")
    root.setLevel(level)
    # Remove existing handlers to avoid duplicates on re-entry
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)

    # Also suppress overly verbose third-party logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    _setup_done = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the agent_workflow namespace.

    Args:
        name: Logger name. If not prefixed with 'agent_workflow.', it will be added.

    Returns:
        Configured logger instance.
    """
    if not name.startswith("agent_workflow."):
        name = f"agent_workflow.{name}"
    return logging.getLogger(name)


# Auto-setup on first import if AGENT_AUTO_LOG env is set
if os.environ.get("AGENT_AUTO_LOG", "1") == "1":
    setup_logging()
