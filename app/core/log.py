"""One JSON line per event. Callers pass only safe fields (request id, caller name, payment
reference, decision, timings). Never names, phone numbers, wallets, keys or request bodies."""

import json
import logging
from typing import Any

logger = logging.getLogger("connector")


def configure_logging() -> None:
    """Idempotent: attach one stdout handler to the 'connector' logger."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    clean = {key: value for key, value in fields.items() if value is not None}
    logger.log(level, json.dumps({"event": event, **clean}, default=str))
