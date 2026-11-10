"""Structured JSON logging with per-request IDs. Never log PII (names, emails, account numbers)."""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Generate a short random request id."""
    return uuid.uuid4().hex[:16]


def _add_request_id(_: object, __: str, event_dict: dict[str, object]) -> dict[str, object]:
    event_dict.setdefault("request_id", request_id_var.get())
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging to emit JSON lines to stdout."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    # Uvicorn's access log prints full URLs incl. query strings (e.g. ?search=<client name>),
    # which can contain PII. Our request middleware logs method/path/status/timing instead.
    logging.getLogger("uvicorn.access").disabled = True
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,  # type: ignore[list-item]
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    """Return a structured logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
