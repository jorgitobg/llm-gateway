from __future__ import annotations

import json
import logging
from typing import Any

ACCESS_LOGGER = "llm_gateway.access"


class JsonFormatter(logging.Formatter):
    """One JSON object per line from the structured `event` attached to a record."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = getattr(record, "event", {})
        return json.dumps({"level": record.levelname.lower(), **event}, sort_keys=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(ACCESS_LOGGER)
    if any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        return
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
