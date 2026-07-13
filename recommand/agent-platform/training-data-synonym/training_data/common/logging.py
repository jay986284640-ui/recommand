"""Structured JSON-line logging.

Per Constitution V (Observability) + spec §FR-021.
Each event MUST be a single JSON line with at minimum:
  ts, level, stage, item_id (if applicable), event, latency_ms, outcome
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


_STANDARD_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Extra kwargs passed via `logger.info(..., extra={...})` are merged into the
    top-level JSON object alongside standard fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS:
                continue
            payload[key] = val
        payload["message"] = record.getMessage()
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotent setup — install JsonFormatter on root logger.

    Safe to call multiple times; subsequent calls just adjust the level.
    """
    global _configured
    root = logging.getLogger()
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.handlers.clear()
        root.addHandler(handler)
        _configured = True
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)