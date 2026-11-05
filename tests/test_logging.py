from __future__ import annotations

import json
import logging

from llm_gateway.logging_setup import ACCESS_LOGGER, JsonFormatter, configure_logging


def test_json_formatter_emits_one_sorted_object() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "request", None, None)
    record.event = {"b": 2, "a": 1}
    assert json.loads(JsonFormatter().format(record)) == {"a": 1, "b": 2, "level": "info"}
    assert JsonFormatter().format(record).index('"a"') < JsonFormatter().format(record).index('"b"')


def test_configure_logging_is_idempotent_and_not_propagated() -> None:
    configure_logging()
    configure_logging()
    logger = logging.getLogger(ACCESS_LOGGER)
    assert len([h for h in logger.handlers if isinstance(h.formatter, JsonFormatter)]) == 1
    assert logger.propagate is False
