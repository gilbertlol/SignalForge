"""Structured JSON log formatting without third-party dependencies.

Only well-known LogRecord attributes are emitted; arbitrary ``extra=`` values
passed by call sites are included, but nothing captures full request bodies,
headers, or environment dumps, so secrets are not accidentally logged.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    reserved: ClassVar[frozenset[str]] = _STANDARD_ATTRS

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.reserved and not key.startswith("_")
        }
        if extra:
            payload["context"] = extra

        return json.dumps(payload, default=str)
