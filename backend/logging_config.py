"""Structured JSON logging for production observability.

Call ``setup_logging()`` once at process start (main.py, worker.py). In
development it keeps human-readable output; when ``ENV=production`` or
``LOG_FORMAT=json``, every log record is emitted as one JSON object per line,
ready for ingestion by any structured-log sink.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        # Extra context passed via `logger.info("...", extra={...})`
        for key, value in getattr(record, "__dict__", {}).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        return json.dumps(entry, default=str)


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "taskName",
}


def setup_logging(level: int | None = None) -> None:
    """Configure the root logger once; no-op if a handler is already present."""
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    use_json = (
        os.getenv("LOG_FORMAT", "json" if os.getenv("ENV") == "production" else "text")
        == "json"
    )
    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level if level is not None else os.getenv("LOG_LEVEL", "INFO").upper())
